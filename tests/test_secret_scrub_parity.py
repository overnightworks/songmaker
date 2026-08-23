"""Pins that songmaker_cli and acestep_worker agree on which env vars to scrub.

acestep_worker must never import songmaker_cli (see CLAUDE.md "Engine
packages are independent"), so the two packages keep separate
``SECRET_ENV_KEYS`` tuples rather than sharing one module. This test is
the only thing standing between them silently drifting apart again — see
issue #157, where the Claude CLI child process inherited
``SONGMAKER_INTERNAL_TOKEN`` because the two lists disagreed.
"""

from __future__ import annotations

from acestep_worker.constants import SECRET_ENV_KEYS as WORKER_SECRET_ENV_KEYS
from songmaker_cli.constants import SECRET_ENV_KEYS as CLI_SECRET_ENV_KEYS


def test_secret_env_keys_are_identical_sets() -> None:
    assert set(CLI_SECRET_ENV_KEYS) == set(WORKER_SECRET_ENV_KEYS)


def test_secret_env_keys_have_no_internal_duplicates() -> None:
    assert len(CLI_SECRET_ENV_KEYS) == len(set(CLI_SECRET_ENV_KEYS))
    assert len(WORKER_SECRET_ENV_KEYS) == len(set(WORKER_SECRET_ENV_KEYS))
