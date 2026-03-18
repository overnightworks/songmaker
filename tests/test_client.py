"""Tests for the ACE-Step HTTP client (mocked)."""

from __future__ import annotations

import json
from http.client import HTTPResponse
from unittest.mock import MagicMock, patch

import pytest

from acestep_engine.client import (
    AceStepClient,
    is_acestep_available,
    validate_audio_path,
)
from acestep_engine.errors import (
    AudioDownloadError,
    GenerationFailedError,
    GenerationTimeoutError,
    TaskSubmissionError,
)
from acestep_engine.models import AceStepConfig


def _mock_response(data: bytes, status: int = 200) -> MagicMock:
    """Build a mock urllib response."""
    resp = MagicMock(spec=HTTPResponse)
    resp.status = status
    resp.read.return_value = data
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def test_is_acestep_available_true() -> None:
    with patch("acestep_engine.client.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _mock_response(b"ok", 200)
        assert is_acestep_available() is True


def test_is_acestep_available_false() -> None:
    with patch("acestep_engine.client.urlopen") as mock_urlopen:
        from urllib.error import URLError
        mock_urlopen.side_effect = URLError("Connection refused")
        assert is_acestep_available() is False


def test_submit_task_success() -> None:
    client = AceStepClient()
    config = AceStepConfig(prompt="test", lyrics="[verse]\nHello")

    response_data = json.dumps({
        "data": {"task_id": "abc123", "status": "queued"},
        "code": 200,
    }).encode()

    with patch("acestep_engine.client.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _mock_response(response_data)
        task_id = client._submit_task(config)

    assert task_id == "abc123"


def test_submit_task_failure() -> None:
    client = AceStepClient()
    config = AceStepConfig(prompt="test", lyrics="test")

    with (
        patch("acestep_engine.client.urlopen") as mock_urlopen,
        patch("acestep_engine.client.time.sleep"),
    ):
        from urllib.error import URLError
        mock_urlopen.side_effect = URLError("Connection refused")
        with pytest.raises(TaskSubmissionError, match="Connection refused"):
            client._submit_task(config)


def test_submit_task_retries_on_transient_error() -> None:
    client = AceStepClient()
    config = AceStepConfig(prompt="test", lyrics="[verse]\nHello")

    success_data = json.dumps({
        "data": {"task_id": "abc123", "status": "queued"},
        "code": 200,
    }).encode()

    from urllib.error import URLError

    with (
        patch("acestep_engine.client.urlopen") as mock_urlopen,
        patch("acestep_engine.client.time.sleep") as mock_sleep,
    ):
        mock_urlopen.side_effect = [
            URLError("Connection refused"),
            _mock_response(success_data),
        ]
        task_id = client._submit_task(config)

    assert task_id == "abc123"
    mock_sleep.assert_called_once_with(1.0)


def test_poll_result_success() -> None:
    client = AceStepClient()

    result_items = json.dumps([{"file": "/v1/audio?path=test.wav", "seed": 42}])
    response_data = json.dumps({
        "data": [{"task_id": "abc", "status": 1, "result": result_items}],
    }).encode()

    with patch("acestep_engine.client.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _mock_response(response_data)
        result = client._poll_result("abc")

    assert result is not None
    assert result == ("/v1/audio?path=test.wav", 42)


def test_poll_result_failure() -> None:
    client = AceStepClient()

    response_data = json.dumps({
        "data": [{"task_id": "abc", "status": 2, "result": "error"}],
    }).encode()

    with patch("acestep_engine.client.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _mock_response(response_data)
        with pytest.raises(GenerationFailedError, match="generation failed"):
            client._poll_result("abc")


def test_validate_audio_path_valid() -> None:
    validate_audio_path("/v1/audio?path=test.wav")
    validate_audio_path("output/song.wav")


def test_validate_audio_path_traversal() -> None:
    with pytest.raises(AudioDownloadError, match="suspicious"):
        validate_audio_path("/../../../etc/passwd")


def test_validate_audio_path_dotdot() -> None:
    with pytest.raises(AudioDownloadError, match="suspicious"):
        validate_audio_path("/v1/audio/../../secret")


def test_is_available_property() -> None:
    client = AceStepClient()
    with patch("acestep_engine.client.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _mock_response(b"ok", 200)
        assert client.is_available is True


def test_submit_task_no_task_id() -> None:
    client = AceStepClient()
    config = AceStepConfig(prompt="test", lyrics="test")
    response_data = json.dumps({"data": {"status": "queued"}, "code": 200}).encode()

    with patch("acestep_engine.client.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _mock_response(response_data)
        with pytest.raises(TaskSubmissionError, match="no task_id"):
            client._submit_task(config)


def test_poll_result_completed_no_audio() -> None:
    client = AceStepClient()
    result_items = json.dumps([{"file": "", "seed": 1}])
    response_data = json.dumps({
        "data": [{"task_id": "abc", "status": 1, "result": result_items}],
    }).encode()

    with patch("acestep_engine.client.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _mock_response(response_data)
        with pytest.raises(GenerationFailedError, match="no audio returned"):
            client._poll_result("abc")


def test_poll_result_timeout() -> None:
    client = AceStepClient()
    response_data = json.dumps({
        "data": [{"task_id": "abc", "status": 0}],
    }).encode()

    call_count = 0

    def fake_monotonic() -> float:
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            return 0.0
        return 99999.0

    with (
        patch("acestep_engine.client.urlopen") as mock_urlopen,
        patch("acestep_engine.client.time.monotonic", side_effect=fake_monotonic),
        patch("acestep_engine.client.time.sleep"),
    ):
        mock_urlopen.return_value = _mock_response(response_data)
        with pytest.raises(GenerationTimeoutError, match="timed out"):
            client._poll_result("abc")


def test_download_audio_success() -> None:
    client = AceStepClient()
    wav_header = b"RIFF" + b"\x00" * 40 + b"extra_data_here"

    with patch("acestep_engine.client.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _mock_response(wav_header)
        result = client._download_audio("/v1/audio?path=test.wav", 42)

    assert result.seed == 42
    assert len(result.wav_bytes) > 44


def test_download_audio_too_small() -> None:
    client = AceStepClient()

    with patch("acestep_engine.client.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _mock_response(b"tiny")
        with pytest.raises(AudioDownloadError, match="empty or too small"):
            client._download_audio("/v1/audio?path=test.wav", 1)


def test_download_audio_relative_path() -> None:
    client = AceStepClient()
    wav_header = b"RIFF" + b"\x00" * 40 + b"extra_data_here"

    with patch("acestep_engine.client.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _mock_response(wav_header)
        result = client._download_audio("output/song.wav", 99)

    assert result.seed == 99


def test_download_audio_network_error() -> None:
    client = AceStepClient()

    with patch("acestep_engine.client.urlopen") as mock_urlopen:
        from urllib.error import URLError
        mock_urlopen.side_effect = URLError("Connection refused")
        with pytest.raises(AudioDownloadError, match="Failed to download"):
            client._download_audio("/v1/audio?path=test.wav", 1)


def test_generate_full_flow() -> None:
    client = AceStepClient()
    config = AceStepConfig(prompt="test", lyrics="[verse]\nHello")
    wav_header = b"RIFF" + b"\x00" * 40 + b"extra_data_here"

    submit_resp = json.dumps({
        "data": {"task_id": "t1", "status": "queued"}, "code": 200,
    }).encode()
    result_items = json.dumps([{"file": "/v1/audio?path=test.wav", "seed": 7}])
    poll_resp = json.dumps({
        "data": [{"task_id": "t1", "status": 1, "result": result_items}],
    }).encode()

    with patch("acestep_engine.client.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = [
            _mock_response(submit_resp),
            _mock_response(poll_resp),
            _mock_response(wav_header),
        ]
        result = client.generate(config)

    assert result.seed == 7
    assert len(result.wav_bytes) > 44


def test_server_info_success() -> None:
    client = AceStepClient()
    health_data = json.dumps({
        "data": {
            "loaded_model": "acestep-v15-turbo",
            "loaded_lm_model": "acestep-5Hz-lm-4B",
            "version": "1.0",
        },
        "code": 200,
    }).encode()

    with patch("acestep_engine.client.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _mock_response(health_data)
        info = client.server_info()

    assert info is not None
    assert info.model == "acestep-v15-turbo"
    assert info.lm_model == "acestep-5Hz-lm-4B"
    assert info.version == "1.0"


def test_server_info_unavailable() -> None:
    client = AceStepClient()

    with patch("acestep_engine.client.urlopen") as mock_urlopen:
        from urllib.error import URLError
        mock_urlopen.side_effect = URLError("Connection refused")
        info = client.server_info()

    assert info is None
