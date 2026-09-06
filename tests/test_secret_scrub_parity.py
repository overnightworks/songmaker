"""Pins that every owner of a secret-scrub list names the same environment keys.

``acestep_worker`` must never import ``songmaker_cli`` (see CLAUDE.md "Engine
packages are independent") and ``agent_providers`` must import neither, so the
list exists three times: as a constant in each of the two packages, and as the
value songmaker injects into the provider runtime at startup (issue #836).
These tests are the only thing standing between them silently drifting apart
again — see issue #157, where the Claude CLI child process inherited
``SONGMAKER_INTERNAL_TOKEN`` because two lists disagreed. Each list is pinned
against the same expected set, so agreement between them follows and a drifted
list names its own owner.
"""

from __future__ import annotations

import pytest

from acestep_worker.constants import SECRET_ENV_KEYS as WORKER_SECRET_ENV_KEYS
from agent_providers.config import current_config
from songmaker_cli.constants import SECRET_ENV_KEYS as CLI_SECRET_ENV_KEYS

EXPECTED_SECRET_ENV_KEYS = frozenset({
    "ANTHROPIC_API_KEY",
    "XAI_API_KEY",
    "OPENAI_API_KEY",
    "SESSION_SECRET",
    "SONGMAKER_INTERNAL_TOKEN",
    "DATABASE_URL",
    "REDIS_URL",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "HF_TOKEN",
    "ADMIN_USERNAME",
    "ADMIN_PASSWORD",
    "GRAFANA_USER",
    "GRAFANA_PASSWORD",
})

SECRET_ENV_KEY_OWNERS = {
    "songmaker_cli": lambda: CLI_SECRET_ENV_KEYS,
    "acestep_worker": lambda: WORKER_SECRET_ENV_KEYS,
    "injected provider runtime": lambda: current_config().secret_env_keys,
}


@pytest.mark.parametrize(
    "secret_env_keys", SECRET_ENV_KEY_OWNERS.values(), ids=SECRET_ENV_KEY_OWNERS,
)
def test_every_scrub_list_matches_the_known_secret_set(secret_env_keys) -> None:
    """Guards against every list agreeing on the wrong thing, e.g. ``()``."""
    assert set(secret_env_keys()) == EXPECTED_SECRET_ENV_KEYS


@pytest.mark.parametrize(
    "secret_env_keys", SECRET_ENV_KEY_OWNERS.values(), ids=SECRET_ENV_KEY_OWNERS,
)
def test_no_scrub_list_repeats_a_key(secret_env_keys) -> None:
    keys = secret_env_keys()
    assert len(keys) == len(set(keys))
