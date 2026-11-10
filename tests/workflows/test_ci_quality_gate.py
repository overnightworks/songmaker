"""G1–G3: Repository contract for the reusable quality gate (live proof is CI)."""

import datetime
import fnmatch
import os
import re
import subprocess
import tomllib
from itertools import product
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
JOBS = WORKFLOW["jobs"]
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


@pytest.mark.parametrize("job_id", ["coverage", "quality"])
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
    backend = JOBS["backend"]
    (test_step,) = [s for s in backend["steps"] if s.get("name") == "Run tests with coverage"]
    assert " -m " not in test_step["run"]
    service_port = backend["services"]["postgres"]["ports"][0].split(":")[0]
    (database_url,) = [url for key, url in backend["env"].items() if key.endswith("DATABASE_URL")]
    assert f"@localhost:{service_port}/" in database_url
    assert not [job_id for job_id in JOBS if "postgresql" in job_id]


COMPOSE_BASE = ROOT / "docker/docker-compose.ci.yml"
COMPOSE_CACHE_OVERLAY = ROOT / "docker/docker-compose.ci-cache.yml"
E2E_FILE = ROOT / ".github/workflows/e2e.yml"
E2E = yaml.safe_load(E2E_FILE.read_text())
E2E_JOBS = E2E["jobs"]
AGGREGATOR_ID, AGGREGATOR = aggregator_of(E2E_JOBS)
LEG_IDS = sorted(as_list(AGGREGATOR["needs"]))
LEGS = [E2E_JOBS[leg_id] for leg_id in LEG_IDS]
AGGREGATOR_STEPS = AGGREGATOR["steps"]
NOT_SUCCESS = ("failure", "cancelled", "skipped")
CONTINUES_AFTER_A_FAILED_STEP = ("!cancelled()", "always()")
LEG_RESULT = re.compile(r"\$\{\{\s*needs\.([\w-]+)\.result\s*\}\}")
STEP_OUTCOME = re.compile(r"\$\{\{\s*steps\.([\w-]+)\.outcome\s*\}\}")
SHARD_ARGUMENT = re.compile(r"--shard=\$\{\{ matrix\.shard \}\}/\$\{\{ env\.(\w+) \}\}")
HELPER_ARGUMENTS = re.compile(r"shard-artifacts\.ts (\S+)")
UPLOAD_ACTION = "actions/upload-artifact@"
DOWNLOAD_ACTION = "actions/download-artifact@"


def expression(value):
    match = re.fullmatch(r"\$\{\{\s*(.*?)\s*\}\}", str(value).strip())
    return match.group(1) if match else str(value)


def steps_using(steps, action):
    return [step for step in steps if step.get("uses", "").startswith(action)]


def leg_uploads():
    return [upload for leg in LEGS for upload in steps_using(leg["steps"], UPLOAD_ACTION)]


def comparison_steps():
    return [step for step in AGGREGATOR_STEPS if "report-identity.ts" in step.get("run", "")]


def is_coverage_step(step):
    if "uses" in step:
        named = f"{step['with'].get('name', '')}{step['with'].get('pattern', '')}"
        return step["uses"].startswith((UPLOAD_ACTION, DOWNLOAD_ACTION)) and "coverage" in named
    return "coverage-report.ts" in step.get("run", "")


def leg_result_step():
    (step,) = [
        step
        for step in AGGREGATOR_STEPS
        if any(LEG_RESULT.search(str(value)) for value in step.get("env", {}).values())
    ]
    return step, {
        name: LEG_RESULT.fullmatch(expression_text).group(1)
        for name, expression_text in step["env"].items()
    }


def leg_shards():
    return sorted({shard for leg in LEGS for shard in leg["strategy"]["matrix"]["shard"]})


def leg_projects():
    return {project for leg in LEGS for project in leg["strategy"]["matrix"]["project"]}


def test_the_aggregator_always_runs():
    assert expression(AGGREGATOR["if"]) == "always()"


def test_the_aggregator_decides_on_the_result_of_every_leg_and_nothing_can_skip_it():
    step, result_variables = leg_result_step()
    assert set(result_variables.values()) == set(LEG_IDS)
    assert AGGREGATOR_STEPS[0] is step
    assert "continue-on-error" not in step
    assert "if" not in step


@pytest.mark.parametrize("result", NOT_SUCCESS)
@pytest.mark.parametrize("failing_leg", LEG_IDS)
def test_the_aggregator_fails_unless_every_leg_succeeded(failing_leg, result):
    step, result_variables = leg_result_step()

    def exit_code(results):
        environment = {"PATH": os.environ["PATH"]} | {
            name: results[leg] for name, leg in result_variables.items()
        }
        return subprocess.run(
            ["bash", "-e", "-c", step["run"]], env=environment, check=False
        ).returncode

    assert exit_code(dict.fromkeys(LEG_IDS, "success")) == 0
    assert exit_code(dict.fromkeys(LEG_IDS, "success") | {failing_leg: result}) != 0


def test_every_aggregator_step_after_the_legs_result_runs_after_a_failed_step():
    for step in AGGREGATOR_STEPS[1:]:
        assert expression(step["if"]) in CONTINUES_AFTER_A_FAILED_STEP, step["name"]


def test_the_comparison_of_each_project_can_fail_the_job():
    comparisons = comparison_steps()
    assert {step["env"]["PROJECT"] for step in comparisons} == leg_projects()
    assert len(comparisons) == len(leg_projects())
    for step in comparisons:
        assert "continue-on-error" not in step
        assert AGGREGATOR_STEPS.index(step) > 0


def test_only_coverage_steps_continue_on_error_and_none_can_use_up_the_job():
    coverage = [step for step in AGGREGATOR_STEPS if is_coverage_step(step)]
    assert coverage
    assert [step for step in AGGREGATOR_STEPS if "continue-on-error" in step] == coverage
    for step in coverage:
        assert step["continue-on-error"] is True
        assert expression(step["if"]) == "!cancelled()"
    assert sum(step["timeout-minutes"] for step in coverage) < AGGREGATOR["timeout-minutes"]


def test_a_failed_coverage_step_is_warned_about_in_a_step_that_cannot_fail_the_job():
    coverage = [step for step in AGGREGATOR_STEPS if is_coverage_step(step)]
    (warning,) = [
        step
        for step in AGGREGATOR_STEPS
        if any(STEP_OUTCOME.search(str(value)) for value in step.get("env", {}).values())
    ]
    reported = {
        step_id for value in warning["env"].values() for step_id in STEP_OUTCOME.findall(value)
    }
    assert reported == {step["id"] for step in coverage}
    assert AGGREGATOR_STEPS.index(warning) > max(AGGREGATOR_STEPS.index(step) for step in coverage)
    assert expression(warning["if"]) == "!cancelled()"
    assert "continue-on-error" not in warning


def test_the_matrix_shards_agree_with_the_total_the_suite_is_called_with():
    for leg in LEGS:
        (suite,) = [step for step in leg["steps"] if SHARD_ARGUMENT.search(step.get("run", ""))]
        total_variable = SHARD_ARGUMENT.search(suite["run"]).group(1)
        total = int(E2E["env"][total_variable])
        assert leg["strategy"]["matrix"]["shard"] == list(range(1, total + 1))
        assert leg["strategy"]["fail-fast"] is False
        helper_calls = [
            step for step in AGGREGATOR_STEPS if "shard-artifacts.ts" in step.get("run", "")
        ]
        assert helper_calls
        assert all(re.search(rf"\$\{{?{total_variable}\b", step["run"]) for step in helper_calls)


def test_every_upload_of_a_leg_is_named_by_project_shard_and_attempt_and_never_overwrites():
    uploads = leg_uploads()
    assert uploads
    names = [upload["with"]["name"] for upload in uploads]
    for name in names:
        assert all(
            "${{ " + context + " }}" in name
            for context in ("matrix.project", "matrix.shard", "github.run_attempt")
        ), name
    assert len(set(names)) == len(names)
    assert all(upload["with"]["overwrite"] is False for upload in uploads)


def test_the_aggregator_downloads_and_chooses_what_the_legs_upload_under_one_naming():
    names = [upload["with"]["name"] for upload in leg_uploads()]
    downloads = steps_using(AGGREGATOR_STEPS, DOWNLOAD_ACTION)
    assert [step for step in AGGREGATOR_STEPS if HELPER_ARGUMENTS.search(step.get("run", ""))]
    for step in AGGREGATOR_STEPS:
        for prefix in HELPER_ARGUMENTS.findall(step.get("run", "")):
            contexts = ("matrix.project", "matrix.shard", "github.run_attempt")
            assert "-".join([prefix, *("${{ " + context + " }}" for context in contexts)]) in names
            project = step["env"]["PROJECT"]
            downloaded = [
                download
                for download in downloads
                if all(
                    fnmatch.fnmatch(f"{prefix}-{project}-{shard}-1", download["with"]["pattern"])
                    for shard in leg_shards()
                )
                and not any(
                    fnmatch.fnmatch(f"{prefix}-{other}-1-1", download["with"]["pattern"])
                    for other in leg_projects() - {project}
                )
            ]
            assert len(downloaded) == 1, (prefix, project)


def test_a_missing_report_fails_its_leg_and_a_missing_coverage_store_never_does():
    uploads = leg_uploads()
    (report,) = [upload for upload in uploads if upload["with"]["path"].endswith(".json")]
    assert all(
        f"/{Path(report['with']['path']).name}" in step["run"] for step in comparison_steps()
    )
    assert report["with"]["if-no-files-found"] == "error"
    assert "continue-on-error" not in report
    assert expression(report["if"]) == "!cancelled()"
    (store,) = [upload for upload in uploads if "coverage" in upload["with"]["name"]]
    assert store["continue-on-error"] is True
    assert store["with"]["include-hidden-files"] is True
    assert store["with"]["if-no-files-found"] == "warn"


def test_every_limit_is_a_literal_and_no_step_outlasts_its_job():
    for job in E2E_JOBS.values():
        assert isinstance(job["timeout-minutes"], int)
        for step in job["steps"]:
            assert step.get("timeout-minutes", 0) <= job["timeout-minutes"], step["name"]
    assert AGGREGATOR["timeout-minutes"] <= 15


class ComposeLoader(yaml.SafeLoader):
    """Reads a compose file whose merge tags (`!reset`, `!override`) do not matter here."""


ComposeLoader.add_multi_constructor("!", lambda loader, tag, node: None)


def test_one_job_writes_the_build_cache_and_only_on_main():
    def build(path):
        return yaml.load(path.read_text(), Loader=ComposeLoader)["services"]["songmaker-web"][  # noqa: S506 - ComposeLoader extends SafeLoader
            "build"
        ]

    assert "cache_to" not in build(COMPOSE_BASE)
    assert build(COMPOSE_BASE)["cache_from"]
    assert build(COMPOSE_CACHE_OVERLAY)["cache_to"]
    overlay_mentions = [
        line for line in E2E_FILE.read_text().splitlines() if COMPOSE_CACHE_OVERLAY.name in line
    ]
    assert len(overlay_mentions) == 1
    assert "github.ref == 'refs/heads/main'" in overlay_mentions[0]
    assert "matrix.shard == 1" in overlay_mentions[0]
