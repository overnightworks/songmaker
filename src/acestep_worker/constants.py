"""Non-model constants for the acestep-worker package.

Lives here (not imported from ``songmaker_cli``) because the
acestep-worker container is a slim image that does not install
``songmaker_cli`` — see CLAUDE.md "Engine packages are independent".
"""

from __future__ import annotations

from typing import Final

# Env var names stripped from the environment of every child process this
# package spawns (the ACE-Step HTTP subprocess, in subprocess_runner.py).
# Kept identical in content and name to songmaker_cli.constants.SECRET_ENV_KEYS
# — the two packages cannot share an import, so
# tests/test_secret_scrub_parity.py pins the two as equal sets.
#
# HF_TOKEN is included even though the acestep-worker *process* itself
# reads it (via WorkerSettings.hf_token, in downloads.py) to authenticate
# model downloads from Hugging Face. The ACE-Step HTTP subprocess started
# by subprocess_runner.py never downloads models itself — downloads run
# in-process in acestep_worker before the subprocess is started — so the
# subprocess has no legitimate use for HF_TOKEN and it is scrubbed like
# every other secret here.
SECRET_ENV_KEYS: Final[tuple[str, ...]] = (
    "ANTHROPIC_API_KEY",
    "SESSION_SECRET",
    "SONGMAKER_INTERNAL_TOKEN",
    "DATABASE_URL",
    "REDIS_URL",
    "POSTGRES_PASSWORD",
    "HF_TOKEN",
)
