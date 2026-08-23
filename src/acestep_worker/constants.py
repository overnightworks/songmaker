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
# HF_TOKEN: the ACE-Step subprocess *does* call Hugging Face itself — see
# vendor/acestep/acestep/api/model_download.py:download_from_huggingface,
# invoked at subprocess startup (startup_model_init.py, for the DiT and VAE
# models) and at request time (llm_readiness.py, runtime_helpers.py,
# startup_llm_init.py, sample_format_routes.py, for LM models). That call
# passes no explicit token=, so huggingface_hub would pick up HF_TOKEN from
# the environment implicitly if it were present. But every repo ID the
# subprocess can resolve (via MODEL_REPO_MAPPING / DEFAULT_REPO_ID in
# model_download.py) is public and answers anonymously; the only two gated
# repos in the ACE-Step catalog (ACE-Step/acestep-v15-turbo and
# ACE-Step/acestep-5Hz-lm-1.7B) are fetched exclusively by
# acestep_worker.downloads.run_download, which passes token= explicitly and
# does not depend on ambient env. So scrubbing HF_TOKEN here does not break
# any download this deployment performs — it only means the subprocess's
# own Hugging Face requests go out anonymously and are subject to Hugging
# Face's stricter unauthenticated rate limits.
SECRET_ENV_KEYS: Final[tuple[str, ...]] = (
    "ANTHROPIC_API_KEY",
    "SESSION_SECRET",
    "SONGMAKER_INTERNAL_TOKEN",
    "DATABASE_URL",
    "REDIS_URL",
    "POSTGRES_PASSWORD",
    "HF_TOKEN",
)
