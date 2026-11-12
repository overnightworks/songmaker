"""G1–G3: Repository contract for the reusable quality gate (live proof is CI)."""

import datetime
import fnmatch
import os
import re
import shutil
import subprocess
import sys
import tomllib
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from itertools import product
from pathlib import Path
from urllib.parse import urlsplit

import coverage
import pytest
import yaml
from support.workflow_shape import (
    CI_JOBS,
    CI_WORKFLOW,
    E2E_JOBS,
    E2E_WORKFLOW,
    backend_step,
    expression,
    step_text,
    steps_using,
)

ROOT = Path(__file__).resolve().parents[2]
JOBS = CI_JOBS
REPORTS = ("reports/coverage.xml", "reports/frontend-coverage/lcov.info")


def as_list(value):
    return [value] if isinstance(value, str) else value


SELF_REPOSITORY_PREFIX = "$/"


def aggregator_of(called_jobs):
    aggregators = [
        (job_id, called)
        for job_id, called in called_jobs.items()
        if set(called_jobs) - {job_id} <= set(as_list(called.get("needs", [])))
    ]
    assert len(aggregators) == 1, "the called workflow needs exactly one aggregator job"
    return aggregators[0]


def called_workflow_aggregator_name(job):
    uses = job["uses"]
    assert uses.startswith(SELF_REPOSITORY_PREFIX), f"unresolvable call: {uses}"
    called_file = ROOT / uses.removeprefix(SELF_REPOSITORY_PREFIX)
    _, aggregator = aggregator_of(yaml.safe_load(called_file.read_text())["jobs"])
    return f"{job['name']} / {aggregator['name']}"


def test_g1_mandatory_names_match_rendered_dependencies():
    rendered_names = set()
    for job_id in set(JOBS["quality"]["needs"]) - {"coverage"}:
        job = JOBS[job_id]
        if "uses" in job:
            rendered_names.add(called_workflow_aggregator_name(job))
            continue
        matrix = job.get("strategy", {}).get("matrix", {})
        for values in product(*matrix.values()):
            name = job["name"]
            for axis, value in zip(matrix, values, strict=True):
                name = name.replace("${{ matrix." + axis + " }}", str(value))
            rendered_names.add(name)
    config = tomllib.loads((ROOT / "quality/config.toml").read_text())
    assert set(config["gate"]) == {"mandatory_jobs", "loosened"}
    loosened = config["gate"]["loosened"]
    assert isinstance(loosened, list)
    for entry in loosened:
        assert set(entry) == {"what", "item", "date", "reason"}
        assert isinstance(entry["date"], datetime.date)
    mandatory = config["gate"]["mandatory_jobs"]
    assert len(mandatory) == len(set(mandatory))
    assert set(mandatory) == rendered_names


def test_g2_assembly_transports_both_reports():
    assembly = JOBS["coverage"]
    steps = assembly["steps"]
    (upload,) = [s for s in steps if s.get("uses", "").startswith("actions/upload-artifact@")]
    assert upload["with"]["name"] == JOBS["quality"]["with"]["coverage-artifact"]
    paths = [Path(p) for p in upload["with"]["path"].splitlines()]
    artifact_root = Path(os.path.commonpath([p.parent for p in paths]))
    properties = dict(
        line.split("=", 1)
        for line in (ROOT / "sonar-project.properties").read_text().splitlines()
        if line and not line.startswith("#")
    )
    assert [
        properties[key]
        for key in (
            "sonar.python.coverage.reportPaths",
            "sonar.javascript.lcov.reportPaths",
        )
    ] == [str(p.relative_to(artifact_root)) for p in paths]


@pytest.mark.parametrize("report", REPORTS)
@pytest.mark.parametrize("state", ["missing", "empty", "present"])
def test_g2_assembly_rejects_missing_or_empty_reports(tmp_path, report, state):
    for relative in REPORTS:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if relative != report or state != "missing":
            path.write_text("" if relative == report and state == "empty" else "coverage")
    (script,) = [s["run"] for s in JOBS["coverage"]["steps"] if "run" in s]
    result = subprocess.run(["bash", "-e", "-c", script], cwd=tmp_path, check=False)
    assert (result.returncode == 0) == (state == "present")


def test_g3_properties_have_no_gate_overrides_or_exemptions():
    keys = {
        line.split("=", 1)[0]
        for line in (ROOT / "sonar-project.properties").read_text().splitlines()
        if line and not line.startswith("#")
    }
    assert "sonar.qualitygate.wait" not in keys
    assert not any(key.startswith("sonar.issue.ignore.") for key in keys)


@pytest.mark.parametrize("job_id", ["coverage", "quality", "backend-shard"])
def test_g3_new_action_references_are_commit_pinned(job_id):
    job = JOBS[job_id]
    references = (
        [job["uses"]]
        if "uses" in job
        else [step["uses"] for step in job["steps"] if "uses" in step]
    )
    assert references
    assert all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", ref) for ref in references)


def test_backend_runs_the_database_tests_against_its_own_postgres_service():
    shard = JOBS["backend-shard"]
    (test_step,) = [s for s in shard["steps"] if s.get("name") == "Run tests with coverage"]
    assert " -m " not in test_step["run"]
    service_port = shard["services"]["postgres"]["ports"][0].split(":")[0]
    (database_url,) = [url for key, url in shard["env"].items() if key.endswith("DATABASE_URL")]
    assert f"@localhost:{service_port}/" in database_url
    assert not [job_id for job_id in JOBS if "postgresql" in job_id]


def test_backend_reaches_its_redis_service_on_the_published_port():
    shard = JOBS["backend-shard"]
    service_port = shard["services"]["redis"]["ports"][0].split(":")[0]
    redis_url = urlsplit(shard["env"]["TEST_REDIS_URL"])
    assert (redis_url.hostname, redis_url.port) == ("localhost", int(service_port))


NOT_SUCCESS = ("failure", "cancelled", "skipped")
CONTINUES_AFTER_A_FAILED_STEP = ("!cancelled()", "always()")
LEG_RESULT = re.compile(r"\$\{\{\s*needs\.([\w-]+)\.result\s*\}\}")
STEP_OUTCOME = re.compile(r"\$\{\{\s*steps\.([\w-]+)\.outcome\s*\}\}")
SHARD_TOTAL_USE = re.compile(
    r"(?:--shard=\$\{\{ matrix\.shard \}\}/|TEST_SHARDS=)\$\{\{ env\.(\w+) \}\}"
)
HELPER_ARGUMENTS = re.compile(r"shard-artifacts\.ts (\S+) (\S+)")
UPLOAD_ACTION = "actions/upload-artifact@"
DOWNLOAD_ACTION = "actions/download-artifact@"
SETUP_UV_ACTION = "astral-sh/setup-uv@"
FIRST_ATTEMPT_CONTEXTS = {"github.run_attempt": "1", "github.run_id": "7"}


def is_coverage_step(step):
    if "uses" in step:
        named = f"{step['with'].get('name', '')}{step['with'].get('pattern', '')}"
        return step["uses"].startswith((UPLOAD_ACTION, DOWNLOAD_ACTION)) and "coverage" in named
    return "coverage-report.ts" in step.get("run", "")


def render_name(name, matrix_values):
    contexts = {f"matrix.{axis}": str(value) for axis, value in matrix_values.items()}
    return re.sub(
        r"\$\{\{\s*([\w.]+)\s*\}\}",
        lambda match: (contexts | FIRST_ATTEMPT_CONTEXTS)[match.group(1)],
        name,
    )


@dataclass(frozen=True)
class Suite:
    """A sharded suite whose mandatory job is an aggregator over its shard jobs."""

    name: str
    workflow: dict
    jobs: dict
    aggregator_id: str
    consumer_ids: tuple[str, ...]
    measurement_steps: Callable[[list], list]

    @property
    def aggregator(self):
        return self.jobs[self.aggregator_id]

    @property
    def steps(self):
        return self.aggregator["steps"]

    @property
    def leg_ids(self):
        return sorted(as_list(self.aggregator["needs"]))

    @property
    def matrix_legs(self):
        return [self.jobs[leg_id] for leg_id in self.leg_ids if "strategy" in self.jobs[leg_id]]

    @property
    def consumer_steps(self):
        return [step for job_id in self.consumer_ids for step in self.jobs[job_id]["steps"]]

    def helper_calls(self):
        return [
            step for step in self.consumer_steps if HELPER_ARGUMENTS.search(step.get("run", ""))
        ]

    def total_variable(self):
        (variable,) = {
            match.group(1)
            for leg in self.matrix_legs
            for step in leg["steps"]
            if (match := SHARD_TOTAL_USE.search(step_text(step)))
        }
        return variable

    def total(self):
        return int(self.workflow["env"][self.total_variable()])

    def uploads(self):
        return [
            upload
            for leg in self.matrix_legs
            for upload in steps_using(leg["steps"], UPLOAD_ACTION)
        ]

    def upload_names(self):
        """Every upload name of every matrix combination, as a run's first attempt renders it."""
        names = set()
        for leg in self.matrix_legs:
            matrix = leg["strategy"]["matrix"]
            for values in product(*matrix.values()):
                names |= {
                    render_name(upload["with"]["name"], dict(zip(matrix, values, strict=True)))
                    for upload in steps_using(leg["steps"], UPLOAD_ACTION)
                }
        return names

    def result_step(self):
        (step,) = [
            step
            for step in self.steps
            if any(LEG_RESULT.search(str(value)) for value in step.get("env", {}).values())
        ]
        return step, {
            name: LEG_RESULT.fullmatch(expression_text).group(1)
            for name, expression_text in step["env"].items()
        }


BROWSER = Suite(
    name="browser",
    workflow=E2E_WORKFLOW,
    jobs=E2E_JOBS,
    aggregator_id=aggregator_of(E2E_JOBS)[0],
    consumer_ids=(aggregator_of(E2E_JOBS)[0],),
    measurement_steps=lambda steps: [step for step in steps if is_coverage_step(step)],
)
BACKEND_JOB_IDS = ("backend-static", "backend-shard", "backend", "backend-coverage")
BACKEND = Suite(
    name="backend",
    workflow=CI_WORKFLOW,
    jobs={job_id: JOBS[job_id] for job_id in BACKEND_JOB_IDS},
    aggregator_id="backend",
    consumer_ids=("backend", "backend-coverage"),
    measurement_steps=lambda steps: [],
)
SUITES = [BROWSER, BACKEND]
WAIT_BOUND_MINUTES = 15
across_suites = pytest.mark.parametrize("suite", SUITES, ids=lambda suite: suite.name)
BROWSER_STEPS = BROWSER.steps
BROWSER_LEGS = BROWSER.matrix_legs
BROWSER_PROJECTS = {
    project for leg in BROWSER_LEGS for project in leg["strategy"]["matrix"]["project"]
}


@across_suites
def test_the_aggregator_always_runs(suite):
    assert expression(suite.aggregator["if"]) == "always()"


@across_suites
def test_the_aggregator_decides_on_the_result_of_every_leg_and_nothing_can_skip_it(suite):
    step, result_variables = suite.result_step()
    assert set(result_variables.values()) == set(suite.leg_ids)
    assert suite.steps[0] is step
    assert "continue-on-error" not in step
    assert "if" not in step


@pytest.mark.parametrize("result", NOT_SUCCESS)
@pytest.mark.parametrize(
    ("suite", "failing_leg"),
    [
        pytest.param(suite, leg, id=f"{suite.name}-{leg}")
        for suite in SUITES
        for leg in suite.leg_ids
    ],
)
def test_the_aggregator_fails_unless_every_leg_succeeded(suite, failing_leg, result):
    step, result_variables = suite.result_step()

    def exit_code(results):
        environment = {"PATH": os.environ["PATH"]} | {
            name: results[leg] for name, leg in result_variables.items()
        }
        return subprocess.run(
            ["bash", "-e", "-c", step["run"]], env=environment, check=False
        ).returncode

    assert exit_code(dict.fromkeys(suite.leg_ids, "success")) == 0
    assert exit_code(dict.fromkeys(suite.leg_ids, "success") | {failing_leg: result}) != 0


@across_suites
def test_every_aggregator_step_after_the_legs_result_runs_after_a_failed_step(suite):
    for step in suite.steps[1:]:
        assert expression(step["if"]) in CONTINUES_AFTER_A_FAILED_STEP, step["name"]


@across_suites
def test_only_measurement_steps_of_the_aggregator_continue_on_error(suite):
    assert [step for step in suite.steps if "continue-on-error" in step] == suite.measurement_steps(
        suite.steps
    )


def test_the_comparison_of_each_project_can_fail_the_job():
    comparisons = [step for step in BROWSER_STEPS if "report-identity.ts" in step.get("run", "")]
    assert {step["env"]["PROJECT"] for step in comparisons} == BROWSER_PROJECTS
    assert len(comparisons) == len(BROWSER_PROJECTS)
    for step in comparisons:
        assert "continue-on-error" not in step
        assert BROWSER_STEPS.index(step) > 0


SUCCEEDING_NODE = "#!/bin/sh\nexit 0\n"
FAILING_NODE = "#!/bin/sh\nexit 1\n"
SHARD_PROOF_STEPS = [
    pytest.param(step, id=step["name"])
    for step in BROWSER_STEPS
    if "node e2e/" in step.get("run", "") and not is_coverage_step(step)
]


def run_browser_step(step, workdir, *, node):
    """Runs a step's script in a directory of its own, with `node` replaced by a stand-in."""
    stand_ins = workdir / "stand-ins"
    stand_ins.mkdir(exist_ok=True)
    (stand_ins / "node").write_text(node)
    (stand_ins / "node").chmod(0o755)
    (workdir / f"chosen-{step['env']['PROJECT']}.txt").write_text("")
    variables = {
        "PATH": os.pathsep.join([str(stand_ins), os.environ["PATH"]]),
        "RUNNER_TEMP": str(workdir),
        BROWSER.total_variable(): str(BROWSER.total()),
    } | step["env"]
    return subprocess.run(
        ["bash", "-e", "-c", step["run"]],
        cwd=workdir,
        env=variables,
        check=False,
        capture_output=True,
        text=True,
    )


def test_every_project_has_a_step_that_chooses_and_a_step_that_compares_its_shards():
    assert len(SHARD_PROOF_STEPS) == 2 * len(BROWSER_PROJECTS)


@pytest.mark.parametrize("step", SHARD_PROOF_STEPS)
def test_a_step_that_proves_the_shards_fails_when_its_command_fails(tmp_path, step):
    assert run_browser_step(step, tmp_path, node=SUCCEEDING_NODE).returncode == 0
    assert run_browser_step(step, tmp_path, node=FAILING_NODE).returncode != 0


def test_none_of_the_coverage_steps_of_the_browser_aggregator_can_use_up_the_job():
    coverage = BROWSER.measurement_steps(BROWSER_STEPS)
    assert coverage
    for step in coverage:
        assert step["continue-on-error"] is True
        assert expression(step["if"]) == "!cancelled()"
    assert sum(step["timeout-minutes"] for step in coverage) < BROWSER.aggregator["timeout-minutes"]


def test_a_failed_coverage_step_is_warned_about_in_a_step_that_cannot_fail_the_job():
    coverage = BROWSER.measurement_steps(BROWSER_STEPS)
    (warning,) = [
        step
        for step in BROWSER_STEPS
        if any(STEP_OUTCOME.search(str(value)) for value in step.get("env", {}).values())
    ]
    reported = {
        step_id for value in warning["env"].values() for step_id in STEP_OUTCOME.findall(value)
    }
    assert reported == {step["id"] for step in coverage}
    assert BROWSER_STEPS.index(warning) > max(BROWSER_STEPS.index(step) for step in coverage)
    assert expression(warning["if"]) == "!cancelled()"
    assert "continue-on-error" not in warning


@across_suites
def test_the_matrix_shards_agree_with_the_total_every_consumer_is_called_with(suite):
    assert suite.matrix_legs
    for leg in suite.matrix_legs:
        assert leg["strategy"]["matrix"]["shard"] == list(range(1, suite.total() + 1))
        assert leg["strategy"]["fail-fast"] is False
    assert suite.helper_calls()
    for step in suite.helper_calls():
        assert re.search(rf"\$\{{?{suite.total_variable()}\b", step["run"]), step["name"]


@across_suites
def test_every_upload_of_a_leg_is_named_by_shard_and_attempt_and_never_overwrites(suite):
    uploads = suite.uploads()
    assert uploads
    names = [upload["with"]["name"] for upload in uploads]
    for leg in suite.matrix_legs:
        for upload in steps_using(leg["steps"], UPLOAD_ACTION):
            assert all(
                "${{ " + context + " }}" in upload["with"]["name"]
                for context in (
                    *(f"matrix.{axis}" for axis in leg["strategy"]["matrix"]),
                    "github.run_attempt",
                )
            ), upload["with"]["name"]
    assert len(set(names)) == len(names)
    assert all(upload["with"]["overwrite"] is False for upload in uploads)


@across_suites
def test_the_aggregator_downloads_and_chooses_what_the_legs_upload_under_one_naming(suite):
    names = suite.upload_names()
    downloads = steps_using(suite.consumer_steps, DOWNLOAD_ACTION)
    assert suite.helper_calls()
    for step in suite.helper_calls():
        for prefix, project_argument in HELPER_ARGUMENTS.findall(step["run"]):
            project = (
                step["env"][project_argument.strip('"$')]
                if project_argument.startswith('"$')
                else project_argument
            )
            family = {f"{prefix}-{project}-{shard}-1" for shard in range(1, suite.total() + 1)}
            assert family <= names, (prefix, project)
            downloaded = [
                download
                for download in downloads
                if {n for n in names if fnmatch.fnmatch(n, download["with"]["pattern"])} == family
            ]
            assert len(downloaded) == 1, (prefix, project)


def test_a_missing_report_fails_its_leg_and_a_missing_coverage_store_never_does():
    uploads = BROWSER.uploads()
    (report,) = [upload for upload in uploads if upload["with"]["path"].endswith(".json")]
    comparisons = [step for step in BROWSER_STEPS if "report-identity.ts" in step.get("run", "")]
    assert all(f"/{Path(report['with']['path']).name}" in step["run"] for step in comparisons)
    assert report["with"]["if-no-files-found"] == "error"
    assert "continue-on-error" not in report
    assert expression(report["if"]) == "!cancelled()"
    (store,) = [upload for upload in uploads if "coverage" in upload["with"]["name"]]
    assert store["continue-on-error"] is True
    assert store["with"]["include-hidden-files"] is True
    assert store["with"]["if-no-files-found"] == "warn"


@across_suites
def test_every_job_has_a_literal_limit_of_at_most_fifteen_minutes_that_no_step_outlasts(suite):
    for job_id, job in suite.jobs.items():
        assert isinstance(job.get("timeout-minutes"), int), job_id
        assert job["timeout-minutes"] <= WAIT_BOUND_MINUTES, job_id
        for step in job["steps"]:
            limit = step.get("timeout-minutes", 0)
            assert isinstance(limit, int), step["name"]
            assert limit <= job["timeout-minutes"], step["name"]


REPORTS_STEP = "Choose the newest report of each shard"
COPY_STEP = "Copy the chosen reports where the identity check reads them"
COLLECT_STEP = "Collect the backend tests"
IDENTITY_STEP = "Compare the shards with the collected tests"
PROOF_STEP = "Require every database proof to execute"
SUMMARY_STEP = "Backend test summary"
COMBINE_STEP = "Combine backend coverage"
BACKEND_SHARD_TOTAL = BACKEND.total_variable()
QUOTA_MODULE = "tests.songmaker_cli.test_reference_audio_quota"
COVERAGE_CONFIG = ".github/workflows/coveragerc-ci.ini"
PASS_THROUGH_UV = '#!/bin/sh\nshift\nwhile [ "${1#--}" != "$1" ]; do shift; done\nexec "$@"\n'
SUCCEEDING_UV = "#!/bin/sh\nexit 0\n"
FAILING_UV = "#!/bin/sh\nexit 1\n"


def run_backend_step(step, workdir, *, uv=PASS_THROUGH_UV, environment=None):
    """Runs a step's script in a directory of its own, with `uv run` replaced by a stand-in."""
    stand_ins = workdir / "stand-ins"
    stand_ins.mkdir(exist_ok=True)
    (stand_ins / "uv").write_text(uv)
    (stand_ins / "uv").chmod(0o755)
    variables = {
        "PATH": os.pathsep.join(
            [str(stand_ins), str(Path(sys.executable).parent), os.environ["PATH"]]
        ),
        BACKEND_SHARD_TOTAL: str(BACKEND.total()),
        "GITHUB_STEP_SUMMARY": str(workdir / "summary.md"),
    } | (environment or {})
    return subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", step["run"]],
        cwd=workdir,
        env=variables,
        check=False,
        capture_output=True,
        text=True,
    )


def write_junit(path, cases):
    """Writes a junit report of `(class name, database case, skipped)` cases."""
    path.parent.mkdir(parents=True, exist_ok=True)
    suite = ET.Element(
        "testsuite",
        tests=str(len(cases)),
        skipped=str(sum(skipped for *_, skipped in cases)),
        failures="0",
        errors="0",
    )
    for index, (class_name, database_case, skipped) in enumerate(cases):
        record = ET.SubElement(suite, "testcase", classname=class_name, name=f"test_{index}")
        if database_case:
            properties = ET.SubElement(record, "properties")
            ET.SubElement(properties, "property", name="database_case", value="true")
        if skipped:
            ET.SubElement(record, "skipped")
    root = ET.Element("testsuites")
    root.append(suite)
    ET.ElementTree(root).write(path)


def plain_cases(count, *, skipped=False):
    return [("tests.plain", False, skipped)] * count


def shard_reports(*, quota_module=QUOTA_MODULE, database=True, skipped_database=False):
    """Three shards of 6, 7 and 6 cases (19 in all, 7 skipped); the quota module is in shard 2."""
    return {
        1: [("tests.a", database, False), *plain_cases(5)],
        2: [(quota_module, database, False), *plain_cases(4, skipped=True), *plain_cases(2)],
        3: [
            ("tests.b", database, skipped_database),
            *plain_cases(3, skipped=True),
            *plain_cases(2),
        ],
    }


def write_reports(workdir, reports):
    for shard, cases in reports.items():
        write_junit(workdir / "reports" / f"backend-junit-{shard}.xml", cases)


@pytest.mark.parametrize("step_name", [PROOF_STEP, SUMMARY_STEP], ids=["database-proof", "summary"])
@pytest.mark.parametrize("missing_shard", [None, 1, 2, 3])
def test_the_backend_proofs_read_the_file_of_every_shard(tmp_path, step_name, missing_shard):
    write_reports(tmp_path, shard_reports())
    if missing_shard:
        (tmp_path / "reports" / f"backend-junit-{missing_shard}.xml").unlink()
    result = run_backend_step(backend_step("backend", step_name), tmp_path)
    assert (result.returncode == 0) == (missing_shard is None), result.stderr


@pytest.mark.parametrize(
    "reports",
    [
        pytest.param(shard_reports(skipped_database=True), id="a-database-case-is-skipped"),
        pytest.param(shard_reports(quota_module="tests.other"), id="no-quota-module"),
        pytest.param(shard_reports(database=False), id="no-database-case"),
    ],
)
def test_the_database_proof_fails_over_the_union_of_the_shards(tmp_path, reports):
    write_reports(tmp_path, reports)
    result = run_backend_step(backend_step("backend", PROOF_STEP), tmp_path)
    assert result.returncode != 0


def test_the_summary_counts_every_shard_once(tmp_path):
    write_reports(tmp_path, shard_reports())
    assert run_backend_step(backend_step("backend", SUMMARY_STEP), tmp_path).returncode == 0
    summary = (tmp_path / "summary.md").read_text()
    assert "### Backend: 19 tests, 7 skipped, 0 failures, 0 errors" in summary


@pytest.mark.parametrize("step_name", [COLLECT_STEP, IDENTITY_STEP])
def test_a_step_that_proves_identity_fails_when_its_command_fails(tmp_path, step_name):
    step = backend_step("backend", step_name)
    assert run_backend_step(step, tmp_path, uv=SUCCEEDING_UV).returncode == 0
    assert run_backend_step(step, tmp_path, uv=FAILING_UV).returncode != 0


def test_the_collection_runs_without_a_shard_selection_and_without_a_pipe():
    step = backend_step("backend", COLLECT_STEP)
    assert "--collect-only" in step["run"]
    assert "|" not in step["run"]
    scopes = (CI_WORKFLOW["env"], JOBS["backend"].get("env", {}), step.get("env", {}))
    assert not [name for scope in scopes for name in scope if name.startswith("TEST_SHARD")]


def test_every_backend_step_that_reads_the_shard_count_reads_the_one_workflow_value():
    for name in (IDENTITY_STEP, PROOF_STEP, SUMMARY_STEP):
        assert BACKEND_SHARD_TOTAL in backend_step("backend", name)["run"], name
    assert (
        BACKEND_SHARD_TOTAL
        in backend_step("backend-coverage", "Choose the newest coverage data of each shard")["run"]
    )
    assert BACKEND_SHARD_TOTAL in CI_WORKFLOW["env"]


def test_the_aggregator_keeps_the_mandatory_name_of_the_pythons_it_runs():
    assert JOBS["backend"]["name"] == f"Backend (Python {CI_WORKFLOW['env']['BACKEND_PYTHON']})"
    assert "strategy" not in JOBS["backend"]
    assert JOBS["backend-coverage"]["needs"] == ["backend"]


def test_the_shards_hand_in_the_files_the_aggregator_and_the_combine_read():
    test_step = backend_step("backend-shard", "Run tests with coverage")
    uploads = {
        upload["with"]["name"].split("-${{")[0]: upload
        for upload in steps_using(JOBS["backend-shard"]["steps"], UPLOAD_ACTION)
    }
    assert set(uploads) == {"junit-backend", "coverage-data-backend"}
    assert (
        re.search(r"--junitxml=(\S+)", test_step["run"]).group(1)
        == uploads["junit-backend"]["with"]["path"]
    )
    assert test_step["env"]["COVERAGE_FILE"] == uploads["coverage-data-backend"]["with"]["path"]
    assert (
        Path(uploads["junit-backend"]["with"]["path"]).name
        in backend_step("backend", COPY_STEP)["run"]
    )
    assert (
        Path(uploads["coverage-data-backend"]["with"]["path"]).name
        in backend_step("backend-coverage", COMBINE_STEP)["run"]
    )
    for upload in uploads.values():
        assert expression(upload["if"]) == "!cancelled()"
        assert upload["with"]["if-no-files-found"] == "error"
        assert "continue-on-error" not in upload


def test_no_step_of_a_backend_job_continues_on_error():
    for job in BACKEND.jobs.values():
        assert not [step["name"] for step in job["steps"] if "continue-on-error" in step]


def test_the_chosen_reports_are_copied_by_shard_not_by_position(tmp_path):
    for name in ("junit-backend-1-1", "junit-backend-3-2"):
        (tmp_path / "temp" / "junit" / name).mkdir(parents=True)
        (tmp_path / "temp" / "junit" / name / "backend-junit.xml").write_text(name)
    chosen = [
        tmp_path / "temp" / "junit" / "junit-backend-1-1",
        tmp_path / "temp" / "junit" / "junit-backend-3-2",
    ]
    (tmp_path / "temp" / "chosen-junit.txt").write_text("\n".join(map(str, chosen)) + "\n")
    result = run_backend_step(
        backend_step("backend", COPY_STEP),
        tmp_path,
        environment={"RUNNER_TEMP": str(tmp_path / "temp")},
    )
    assert result.returncode == 0, result.stderr
    copied = {path.name: path.read_text() for path in (tmp_path / "reports").iterdir()}
    assert copied == {
        "backend-junit-1.xml": "junit-backend-1-1",
        "backend-junit-3.xml": "junit-backend-3-2",
    }


def prepare_combine(workdir, *, spoil=None):
    (workdir / ".github/workflows").mkdir(parents=True)
    shutil.copy(ROOT / COVERAGE_CONFIG, workdir / COVERAGE_CONFIG)
    chosen = []
    for shard in range(1, BACKEND.total() + 1):
        source = workdir / "src" / f"shard{shard}.py"
        source.parent.mkdir(exist_ok=True)
        source.write_text("value = 1\n")
        directory = workdir / "reports" / "shard-coverage" / f"coverage-data-backend-{shard}-1"
        directory.mkdir(parents=True)
        data = coverage.CoverageData(basename=str(directory / "coverage-data-backend"))
        data.add_lines({f"src/shard{shard}.py": [1]})
        data.write()
        chosen.append(f"reports/shard-coverage/coverage-data-backend-{shard}-1")
    (workdir / "reports" / "chosen-coverage.txt").write_text("\n".join(chosen) + "\n")
    if spoil:
        spoil(workdir / chosen[1] / "coverage-data-backend")


@pytest.mark.parametrize(
    ("spoil", "passes"),
    [
        pytest.param(None, True, id="every-shard-has-data"),
        pytest.param(lambda path: path.unlink(), False, id="a-shards-data-is-missing"),
        pytest.param(
            lambda path: path.write_bytes(b"not a data file"),
            False,
            id="a-shards-data-is-unreadable",
        ),
    ],
)
def test_the_combine_requires_the_data_of_every_shard(tmp_path, spoil, passes):
    prepare_combine(tmp_path, spoil=spoil)
    result = run_backend_step(backend_step("backend-coverage", COMBINE_STEP), tmp_path)
    assert (result.returncode == 0) == passes, result.stdout + result.stderr


def setup_uv_steps():
    return [
        (job_id, step)
        for job_id, job in JOBS.items()
        for step in steps_using(job.get("steps", []), SETUP_UV_ACTION)
    ]


def test_exactly_one_uv_cache_writer_and_only_on_main():
    savers = [step for _, step in setup_uv_steps() if step["with"].get("save-cache") is not False]
    assert len(savers) == 1
    assert "github.ref == 'refs/heads/main'" in savers[0]["with"]["save-cache"]


def test_every_backend_job_sets_up_the_one_python():
    assert setup_uv_steps()
    for job_id, step in setup_uv_steps():
        assert step["with"]["python-version"] == "${{ env.BACKEND_PYTHON }}", job_id


def test_a_module_that_needs_the_vendored_engine_is_collected_without_it():
    # A module skipped whole at collection leaves a junit record without a node id.
    block_engine_then_run_pytest = (
        "import sys; sys.modules['acestep'] = None; import pytest; "
        "raise SystemExit(pytest.main(sys.argv[1:]))"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            block_engine_then_run_pytest,
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            "tests/acestep_engine/test_client_contract.py",
        ],
        cwd=ROOT,
        env={k: v for k, v in os.environ.items() if k not in ("TEST_SHARD", "TEST_SHARDS")},
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout
    assert [line for line in result.stdout.splitlines() if "::" in line]
