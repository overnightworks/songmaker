"""Tests for the StrEnum centralization in constants.py."""

from __future__ import annotations

import json

from songmaker_cli.constants import (
    ACESTEP_SSE_READ_TIMEOUT_SECONDS,
    GENERATE_JOB_HEARTBEAT_TICK_RESERVE_SECONDS,
    JOB_ACTIVE_STATUSES,
    JOB_TERMINAL_STATUSES,
    MODEL_AVAILABLE_MODES,
    MODEL_DEFAULT_MODE,
    STALE_JOB_THRESHOLDS,
    AuditAction,
    JobFunction,
    JobStatus,
    JobType,
    ResourceType,
)
from songmaker_cli.settings import Settings


def test_default_model_mode_is_in_available() -> None:
    assert MODEL_DEFAULT_MODE in MODEL_AVAILABLE_MODES


def test_builtin_defaults_keys_match_available_modes() -> None:
    from songmaker_cli.acestep_capabilities import ACESTEP_PROFILES
    from songmaker_cli.config import (
        _BUILTIN_DEFAULTS,
        _MODEL_NAME_TO_MODE,
    )

    assert set(_BUILTIN_DEFAULTS.keys()) == MODEL_AVAILABLE_MODES
    assert set(ACESTEP_PROFILES.keys()) == MODEL_AVAILABLE_MODES
    assert set(_MODEL_NAME_TO_MODE.values()) <= MODEL_AVAILABLE_MODES


def test_acestep_worker_size_dicts_cover_available_modes() -> None:
    from acestep_worker.__main__ import DEFAULT_MODEL_SIZES_GB
    from acestep_worker.downloads import ESTIMATED_MODEL_SIZE_BYTES

    assert set(ESTIMATED_MODEL_SIZE_BYTES.keys()) == MODEL_AVAILABLE_MODES
    assert set(DEFAULT_MODEL_SIZES_GB.keys()) == MODEL_AVAILABLE_MODES


def test_job_status_values_match_db_strings():
    assert JobStatus.QUEUED == "queued"
    assert JobStatus.RUNNING == "running"
    assert JobStatus.COMPLETED == "completed"
    assert JobStatus.FAILED == "failed"
    assert JobStatus.PARTIAL == "partial"


def test_job_status_str_compat():
    assert str(JobStatus.QUEUED) == "queued"
    assert isinstance(JobStatus.QUEUED, str)
    assert JobStatus.QUEUED in ("queued", "running")


def test_job_status_active_and_terminal_partition():
    all_statuses = set(JobStatus)
    assert JOB_ACTIVE_STATUSES | JOB_TERMINAL_STATUSES == all_statuses
    assert JOB_ACTIVE_STATUSES & JOB_TERMINAL_STATUSES == set()


def test_plain_strings_match_strenum_frozensets():
    assert "queued" in JOB_ACTIVE_STATUSES
    assert "running" in JOB_ACTIVE_STATUSES
    assert "completed" in JOB_TERMINAL_STATUSES
    assert "cancelled" in JOB_TERMINAL_STATUSES
    assert "completed" not in JOB_ACTIVE_STATUSES
    assert "queued" not in JOB_TERMINAL_STATUSES


def test_job_type_values():
    assert JobType.GENERATE == "generate"
    assert JobType.SCORE == "score"
    assert JobType.CHAT == "chat"


def test_stale_job_policy_covers_every_type_create_job_can_receive() -> None:
    """ARQ job functions and direct job types share the reaper's one policy."""
    reachable_types = set(JobType) | {JobType(job_function) for job_function in JobFunction}

    assert set(STALE_JOB_THRESHOLDS) == reachable_types


def test_generate_sse_timeout_precedes_arq_and_sets_reaper_threshold() -> None:
    settings = Settings(
        database_url="postgresql://example",
        redis_url="redis://example",
        session_secret="session-secret",
        songmaker_internal_token="internal-token",
    )

    assert ACESTEP_SSE_READ_TIMEOUT_SECONDS < settings.arq_job_timeout
    assert STALE_JOB_THRESHOLDS[JobType.GENERATE].heartbeat_seconds == (
        ACESTEP_SSE_READ_TIMEOUT_SECONDS
        + GENERATE_JOB_HEARTBEAT_TICK_RESERVE_SECONDS
    )


def test_resource_type_values():
    assert ResourceType.SONG == "song"
    assert ResourceType.GENERATION == "generation"
    assert ResourceType.SESSION == "session"


def test_audit_action_values():
    assert AuditAction.GENERATE == "generate"
    assert AuditAction.HARD_DELETE == "hard_delete"
    assert AuditAction.SESSION_IP_CHANGE == "session_ip_change"


def test_str_enums_json_serialize_as_value():
    payload = {
        "status": JobStatus.COMPLETED,
        "type": JobType.GENERATE,
        "resource": ResourceType.SONG,
        "action": AuditAction.SHARE,
    }
    encoded = json.dumps(payload)
    assert json.loads(encoded) == {
        "status": "completed",
        "type": "generate",
        "resource": "song",
        "action": "share",
    }
