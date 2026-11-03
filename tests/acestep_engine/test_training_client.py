"""Tests for acestep_engine.training_client — HTTP wrapper for training routes."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from support.acestep_http import mock_http_response

from acestep_engine.models import LoraTrainingConfig
from acestep_engine.training_client import (
    AceStepTrainingClient,
    ExportResult,
    PreprocessStatus,
    PreprocessTaskHandle,
    ScanDatasetResult,
    TrainingRequestError,
    TrainingResponseError,
    TrainingStartedHandle,
    TrainingStatus,
)


def _resp(payload: dict) -> MagicMock:
    return mock_http_response(json.dumps(payload).encode())


def test_scan_dataset_happy_path(tmp_path: Path) -> None:
    client = AceStepTrainingClient(host="localhost", port=8001)
    envelope = {
        "data": {
            "num_samples": 5,
            "message": "ok",
            "dataset_json_path": str(tmp_path / "ds.json"),
        },
    }
    with patch("acestep_engine.training_client.urlopen", return_value=_resp(envelope)):
        result = client.scan_dataset(str(tmp_path / "dataset"))
    assert isinstance(result, ScanDatasetResult)
    assert result.num_samples == 5
    assert result.message == "ok"


def test_start_preprocess_returns_handle(tmp_path: Path) -> None:
    client = AceStepTrainingClient(host="localhost", port=8001)
    envelope = {"data": {"task_id": "abc-123", "total": 4}}
    with patch("acestep_engine.training_client.urlopen", return_value=_resp(envelope)):
        handle = client.start_preprocess(str(tmp_path / "tensors"))
    assert isinstance(handle, PreprocessTaskHandle)
    assert handle.task_id == "abc-123"
    assert handle.total == 4


def test_start_preprocess_missing_task_id_raises(tmp_path: Path) -> None:
    client = AceStepTrainingClient(host="localhost", port=8001)
    with patch(
        "acestep_engine.training_client.urlopen",
        return_value=_resp({"data": {"message": "oops"}}),
    ):
        with pytest.raises(TrainingResponseError):
            client.start_preprocess(str(tmp_path / "tensors"))


def test_poll_preprocess_completed_has_num_tensors() -> None:
    client = AceStepTrainingClient(host="localhost", port=8001)
    envelope = {
        "data": {
            "task_id": "abc",
            "status": "completed",
            "progress": "done",
            "current": 4,
            "total": 4,
            "result": {"num_tensors": 4, "message": "ok"},
        },
    }
    with patch("acestep_engine.training_client.urlopen", return_value=_resp(envelope)):
        status = client.poll_preprocess("abc")
    assert isinstance(status, PreprocessStatus)
    assert status.status == "completed"
    assert status.num_tensors == 4


def test_poll_preprocess_failed_has_error() -> None:
    client = AceStepTrainingClient(host="localhost", port=8001)
    envelope = {
        "data": {
            "task_id": "abc", "status": "failed", "progress": "Failed: OOM",
            "error": "OOM", "current": 0, "total": 4,
        },
    }
    with patch("acestep_engine.training_client.urlopen", return_value=_resp(envelope)):
        status = client.poll_preprocess("abc")
    assert status.status == "failed"
    assert status.error == "OOM"


def test_start_lokr_dumps_config(tmp_path: Path) -> None:
    client = AceStepTrainingClient(host="localhost", port=8001)
    envelope = {
        "data": {
            "tensor_dir": str(tmp_path / "t"),
            "output_dir": str(tmp_path / "o"),
            "message": "started",
        },
    }
    captured: dict = {}

    def capture(req, timeout):
        captured["payload"] = json.loads(req.data)
        captured["url"] = req.full_url
        return _resp(envelope)

    with patch("acestep_engine.training_client.urlopen", side_effect=capture):
        handle = client.start_lokr(
            LoraTrainingConfig(tensor_dir=str(tmp_path / "t"), output_dir=str(tmp_path / "o")),
        )
    assert isinstance(handle, TrainingStartedHandle)
    assert "start_lokr" in captured["url"]
    assert captured["payload"]["tensor_dir"] == str(tmp_path / "t")
    assert captured["payload"]["output_dir"] == str(tmp_path / "o")
    assert captured["payload"]["learning_rate"] == 0.03


def test_poll_training_is_training_true() -> None:
    client = AceStepTrainingClient(host="localhost", port=8001)
    envelope = {
        "data": {
            "is_training": True, "current_epoch": 5, "current_step": 100,
            "current_loss": 0.123, "steps_per_second": 1.5,
            "status": "Training...", "estimated_time_remaining": 10.0,
        },
    }
    with patch("acestep_engine.training_client.urlopen", return_value=_resp(envelope)):
        status = client.poll_training()
    assert isinstance(status, TrainingStatus)
    assert status.is_training is True
    assert status.current_epoch == 5
    assert status.current_loss == pytest.approx(0.123)


def test_stop_training_posts() -> None:
    client = AceStepTrainingClient(host="localhost", port=8001)
    with patch(
        "acestep_engine.training_client.urlopen",
        return_value=_resp({"data": {"message": "Stopping..."}}),
    ) as mock_u:
        client.stop_training()
    mock_u.assert_called_once()


def test_export_training_returns_result(tmp_path: Path) -> None:
    client = AceStepTrainingClient(host="localhost", port=8001)
    envelope = {
        "data": {
            "export_path": str(tmp_path / "out/final"),
            "source": str(tmp_path / "out/final"),
            "message": "exported",
        },
    }
    with patch("acestep_engine.training_client.urlopen", return_value=_resp(envelope)):
        result = client.export_training(str(tmp_path / "out"), str(tmp_path / "out/final"))
    assert isinstance(result, ExportResult)
    assert result.export_path == str(tmp_path / "out/final")


def test_bad_json_response_raises(tmp_path: Path) -> None:
    client = AceStepTrainingClient(host="localhost", port=8001)
    resp = MagicMock()
    resp.read = MagicMock(return_value=b"not json")
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    with patch("acestep_engine.training_client.urlopen", return_value=resp):
        with pytest.raises(TrainingResponseError):
            client.scan_dataset(str(tmp_path / "x"))


def test_network_error_retries_then_raises(tmp_path: Path) -> None:
    from urllib.error import URLError

    client = AceStepTrainingClient(host="localhost", port=8001)
    with (
        patch("acestep_engine.training_client.urlopen", side_effect=URLError("boom")),
        patch("acestep_engine.training_client.time.sleep", return_value=None),
    ):
        with pytest.raises(TrainingRequestError):
            client.scan_dataset(str(tmp_path / "x"))


def test_unwrap_envelope_without_data_key(tmp_path: Path) -> None:
    client = AceStepTrainingClient(host="localhost", port=8001)
    envelope = {"num_samples": 3}
    with patch("acestep_engine.training_client.urlopen", return_value=_resp(envelope)):
        result = client.scan_dataset(str(tmp_path / "x"))
    assert result.num_samples == 3


def test_non_dict_response_raises(tmp_path: Path) -> None:
    client = AceStepTrainingClient(host="localhost", port=8001)
    resp = mock_http_response(b"[]")
    with patch("acestep_engine.training_client.urlopen", return_value=resp):
        with pytest.raises(TrainingResponseError):
            client.scan_dataset(str(tmp_path / "x"))
