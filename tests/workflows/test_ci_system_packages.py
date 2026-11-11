"""The backend shards' system packages: one owner, and one cache that shard 1 writes on main."""

import re

from support.workflow_shape import (
    CI_JOBS,
    E2E_JOBS,
    backend_step,
    expression,
    step_text,
    steps_using,
)

CACHE_RESTORE_ACTION = "actions/cache/restore@"
CACHE_SAVE_ACTION = "actions/cache/save@"
SYSTEM_PACKAGES_STEP = "Install system dependencies"
ARCHIVES_OPTION = re.compile(r'Dir::Cache::Archives="([^"]+)"')


def system_package_steps():
    steps = CI_JOBS["backend-shard"]["steps"]
    (resolve,) = [step for step in steps if step.get("id") == "system-packages"]
    (restore,) = steps_using(steps, CACHE_RESTORE_ACTION)
    (save,) = steps_using(steps, CACHE_SAVE_ACTION)
    return resolve, restore, backend_step("backend-shard", SYSTEM_PACKAGES_STEP), save


def test_the_system_package_files_are_restored_into_the_directory_apt_installs_from():
    _, restore, install, _ = system_package_steps()
    restored_directory = restore["with"]["path"].replace("${{ runner.temp }}", "$RUNNER_TEMP")
    assert set(ARCHIVES_OPTION.findall(install["run"])) == {restored_directory.rsplit("/", 1)[0]}


def test_the_cache_saves_the_path_it_restores_under_the_same_key():
    _, restore, _, save = system_package_steps()
    assert save["with"]["path"] == restore["with"]["path"]
    assert save["with"]["key"] == restore["with"]["key"]


def test_the_restore_key_and_prefix_are_the_outputs_of_the_resolve_step():
    resolve, restore, _, _ = system_package_steps()
    outputs = f"steps.{resolve['id']}.outputs"
    assert {expression(restore["with"]["key"]), expression(restore["with"]["restore-keys"])} == {
        f"{outputs}.key",
        f"{outputs}.prefix",
    }


def test_the_system_packages_have_one_owner_in_the_job_environment():
    shard = CI_JOBS["backend-shard"]
    resolve, _, install, _ = system_package_steps()
    for variable in ("SYSTEM_PACKAGES", "APT_OPTIONS"):
        assert all(f"${variable}" in step["run"] for step in (resolve, install)), variable
        assert variable in shard["env"]
    named = {word for step in shard["steps"] for word in step_text(step).split()}
    assert not set(shard["env"]["SYSTEM_PACKAGES"].split()) & named


def test_exactly_one_system_package_cache_writer_and_only_on_main_shard_one_after_a_miss():
    saves = [
        step
        for jobs in (CI_JOBS, E2E_JOBS)
        for job in jobs.values()
        for step in steps_using(job.get("steps", []), CACHE_SAVE_ACTION)
    ]
    _, restore, _, save = system_package_steps()
    assert saves == [save]
    condition = expression(save["if"])
    assert "github.ref == 'refs/heads/main'" in condition
    assert len(re.findall(r"matrix\.shard == \S+", condition)) == 1
    assert f"steps.{restore['id']}.outputs.cache-hit != 'true'" in condition


def test_a_slow_restore_gives_up_before_its_step_does():
    _, restore, _, _ = system_package_steps()
    assert int(restore["env"]["SEGMENT_DOWNLOAD_TIMEOUT_MINS"]) < restore["timeout-minutes"]
