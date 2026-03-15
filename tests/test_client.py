"""Tests for the ACE-Step HTTP client (mocked)."""

from __future__ import annotations

import json
from http.client import HTTPResponse
from unittest.mock import MagicMock, patch

import pytest

from acestep_engine.client import AceStepClient, is_acestep_available
from acestep_engine.errors import GenerationFailedError, TaskSubmissionError
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

    with patch("acestep_engine.client.urlopen") as mock_urlopen:
        from urllib.error import URLError
        mock_urlopen.side_effect = URLError("Connection refused")
        with pytest.raises(TaskSubmissionError, match="Connection refused"):
            client._submit_task(config)


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


