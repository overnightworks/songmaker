"""Failure inputs the generation tests share, and the lines each is expected to leave."""

from __future__ import annotations

import pytest

from acestep_engine.errors import AudioDownloadError
from songmaker_cli.scheduler import NoCapacityError

GENERATION_SETUP_MESSAGES = [
    "Song not found",
    "Version not found",
    "Reference audio not found",
    "The reference track was deleted while this take was generating.",
    "Selected voice is unavailable for this generation",
]

OTHER_GENERATION_ERROR_TYPES = [
    None,
    "server_restart",
    "no_worker_alive",
    "queued_full_queue_bound",
    "queued_too_long",
    "setup_error",
    "unknown",
]


SONGMAKER_FAILURE_CASES = [
    pytest.param(
        (
            TimeoutError, "private timeout",
            "Generation timed out", "Generation timed out", "generation_error",
        ),
        id="S5-B-D-timeout",
    ),
    pytest.param(
        (
            AudioDownloadError, "private download",
            "Failed to download generated audio", "Failed to download generated audio",
            "generation_error",
        ),
        id="S5-B-D-download",
    ),
    pytest.param(
        (
            ConnectionError, "private connection",
            "ACE-Step server not reachable", "ACE-Step server not reachable", "generation_error",
        ),
        id="S5-B-D-connection",
    ),
    pytest.param(
        (
            NoCapacityError, "private capacity",
            "No ACE-Step workers available", "Generating isn't available right now.",
            "generation_unavailable",
        ),
        id="S5-B-L10-capacity",
    ),
    pytest.param(
        (
            RuntimeError, "private runtime",
            "Internal error during processing", "Internal error during processing",
            "generation_error",
        ),
        id="S5-B-D-runtime",
    ),
    pytest.param(
        (
            ValueError, "private unknown",
            "An unexpected error occurred", "An unexpected error occurred", "generation_error",
        ),
        id="S5-B-D-unknown",
    ),
]
