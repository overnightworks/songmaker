from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from acestep_worker.__main__ import (
    _optional_int_env,
    _require_env,
    build_deps,
    main,
)


def test_require_env_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("X_VAR", "value")
    assert _require_env("X_VAR") == "value"


def test_require_env_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("X_VAR", raising=False)
    with pytest.raises(RuntimeError, match="X_VAR"):
        _require_env("X_VAR")


def test_require_env_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("X_VAR", "")
    with pytest.raises(RuntimeError):
        _require_env("X_VAR")


def test_optional_int_env_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("N", "42")
    assert _optional_int_env("N") == 42


def test_optional_int_env_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("N", raising=False)
    assert _optional_int_env("N") is None


def test_optional_int_env_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("N", "")
    assert _optional_int_env("N") is None


def test_build_deps_minimal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORKER_ID", "acestep-worker-0")
    monkeypatch.setenv("REDIS_URL", "redis://fake")
    monkeypatch.delenv("CONTROL_PLANE_URL", raising=False)
    monkeypatch.delenv("SONGMAKER_INTERNAL_TOKEN", raising=False)

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


def test_build_deps_with_registration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORKER_ID", "acestep-worker-0")
    monkeypatch.setenv("REDIS_URL", "redis://fake")
    monkeypatch.setenv("CONTROL_PLANE_URL", "http://web:8080")
    monkeypatch.setenv("SONGMAKER_INTERNAL_TOKEN", "secret")
    monkeypatch.setenv("GPU_ID", "1")
    monkeypatch.setenv("VRAM_BUDGET_GB", "16")

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


def test_main_runs_uvicorn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORKER_ID", "acestep-worker-0")
    monkeypatch.setenv("REDIS_URL", "redis://fake")
    monkeypatch.setenv("WORKER_PORT", "8765")

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
