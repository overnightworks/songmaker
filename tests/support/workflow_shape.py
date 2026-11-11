"""The GitHub workflow files the shape tests read, and the reading of their steps."""

import re
from pathlib import Path
from typing import Final

import yaml
from support.repository_root import REPOSITORY_ROOT


def load_workflow(path: Path):
    return yaml.safe_load(path.read_text())


CI_WORKFLOW: Final = load_workflow(REPOSITORY_ROOT / ".github/workflows/ci.yml")
E2E_WORKFLOW: Final = load_workflow(REPOSITORY_ROOT / ".github/workflows/e2e.yml")
CI_JOBS: Final = CI_WORKFLOW["jobs"]
E2E_JOBS: Final = E2E_WORKFLOW["jobs"]


def expression(value):
    match = re.fullmatch(r"\$\{\{\s*(.*?)\s*\}\}", str(value).strip())
    return match.group(1) if match else str(value)


def steps_using(steps, action):
    return [step for step in steps if step.get("uses", "").startswith(action)]


def step_text(step):
    return "\n".join([step.get("run", ""), *(f"{k}={v}" for k, v in step.get("env", {}).items())])


def backend_step(job_id, name):
    (step,) = [step for step in CI_JOBS[job_id]["steps"] if step.get("name") == name]
    return step
