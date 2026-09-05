from __future__ import annotations

import json
import logging
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from acestep_worker.__main__ import (
    _AcestepWorkerLogHandler,
    build_deps,
    configure_logging,
    main,
)
from acestep_worker.gpu_util import GpuHealth


def test_build_deps_minimal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORKER_ID", "acestep-worker-0")
    monkeypatch.setenv("REDIS_URL", "redis://fake")
    monkeypatch.delenv("CONTROL_PLANE_URL", raising=False)
    monkeypatch.setenv("SONGMAKER_INTERNAL_TOKEN", "secret")
    from acestep_worker.settings import get_worker_settings
    get_worker_settings.cache_clear()

    fake_redis = MagicMock()
    with (
        patch("acestep_worker.__main__.Redis.from_url", return_value=fake_redis),
        patch(
            "acestep_worker.__main__.make_acestep_runner",
            return_value=(MagicMock(), MagicMock()),
        ),
    ):
        deps = build_deps()

    assert deps.worker_id == "acestep-worker-0"
    assert deps.registry_client is None
    assert deps.registration is None
    assert deps.heartbeat is not None
    assert isinstance(deps.gpu_health_checker(), GpuHealth)


def test_build_deps_with_registration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORKER_ID", "acestep-worker-0")
    monkeypatch.setenv("REDIS_URL", "redis://fake")
    monkeypatch.setenv("CONTROL_PLANE_URL", "http://web:8080")
    monkeypatch.setenv("SONGMAKER_INTERNAL_TOKEN", "secret")
    monkeypatch.setenv("GPU_ID", "1")
    monkeypatch.setenv("VRAM_BUDGET_GB", "16")
    from acestep_worker.settings import get_worker_settings
    get_worker_settings.cache_clear()

    with (
        patch("acestep_worker.__main__.Redis.from_url", return_value=MagicMock()),
        patch(
            "acestep_worker.__main__.make_acestep_runner",
            return_value=(MagicMock(), MagicMock()),
        ),
    ):
        deps = build_deps()

    assert deps.registry_client is not None
    assert deps.registration is not None
    assert deps.registration.gpu_id == 1
    assert deps.registration.vram_total_gb == 16.0


def test_main_runs_uvicorn(monkeypatch: pytest.MonkeyPatch, isolated_logging) -> None:
    monkeypatch.setenv("WORKER_ID", "acestep-worker-0")
    monkeypatch.setenv("REDIS_URL", "redis://fake")
    monkeypatch.setenv("WORKER_PORT", "8765")
    monkeypatch.setenv("SONGMAKER_INTERNAL_TOKEN", "secret")

    with (
        patch("acestep_worker.__main__.Redis.from_url", return_value=MagicMock()),
        patch(
            "acestep_worker.__main__.make_acestep_runner",
            return_value=(MagicMock(), MagicMock()),
        ),
        patch("acestep_worker.__main__.uvicorn.run") as run_mock,
    ):
        main()

    run_mock.assert_called_once()
    _, kwargs = run_mock.call_args
    assert kwargs["port"] == 8765


def test_configure_logging_emits_common_json_fields(
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    isolated_logging,
) -> None:
    configure_logging("INFO")
    configure_logging("INFO")

    logging.getLogger("acestep.worker").info("worker ready")

    root = logging.getLogger()
    assert caplog.handler in root.handlers
    assert sum(
        isinstance(handler, _AcestepWorkerLogHandler) for handler in root.handlers
    ) == 1
    payload = json.loads(capsys.readouterr().err)
    assert payload == {
        "event": "worker ready",
        "level": "info",
        "logger": "acestep.worker",
        "timestamp": payload["timestamp"],
    }
    assert datetime.fromisoformat(payload["timestamp"])


def test_configure_logging_includes_exception_traceback(
    capsys: pytest.CaptureFixture[str],
    isolated_logging,
) -> None:
    configure_logging("INFO")

    try:
        raise ValueError("generation failed")
    except ValueError:
        logging.getLogger("acestep.worker").exception("generation failed")

    payload = json.loads(capsys.readouterr().err)
    assert "ValueError: generation failed" in payload["exception"]
