"""Tests: AceStepClient loads/unloads LoRA around generation when configured."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from conftest import mock_http_response

from acestep_engine.client import AceStepClient
from acestep_engine.models import AceStepConfig, AceStepResult


def _config(lora_path: str = "") -> AceStepConfig:
    return AceStepConfig(
        prompt="p", lyrics="L",
        bpm=120, audio_duration=10,
        lora_path=lora_path,
    )


def _make_client() -> AceStepClient:
    return AceStepClient(host="http://localhost", port=8001)


def test_generate_skips_lora_when_path_empty() -> None:
    client = _make_client()
    config = _config(lora_path="")

    calls: list[str] = []

    def fake_ensure(self, lora_path: str) -> bool:
        calls.append(f"load:{lora_path}")
        return True

    def fake_unload(self) -> None:
        calls.append("unload")

    with (
        patch.object(AceStepClient, "_ensure_lora_loaded", fake_ensure),
        patch.object(AceStepClient, "_unload_lora_best_effort", fake_unload),
        patch.object(
            AceStepClient, "_submit_task", return_value="task-1",
        ),
        patch.object(
            AceStepClient, "_poll_result",
            return_value=_fake_poll_result(),
        ),
        patch.object(
            AceStepClient, "_download_audio",
            return_value=AceStepResult(wav_bytes=b"\x00" * 44, seed=42),
        ),
    ):
        client.generate(config)

    assert calls == []


def test_generate_loads_and_unloads_when_lora_set() -> None:
    client = _make_client()
    config = _config(lora_path="/tmp/my-lora")

    calls: list[str] = []

    def fake_ensure(self, lora_path: str) -> bool:
        calls.append(f"load:{lora_path}")
        return True

    def fake_unload(self) -> None:
        calls.append("unload")

    with (
        patch.object(AceStepClient, "_ensure_lora_loaded", fake_ensure),
        patch.object(AceStepClient, "_unload_lora_best_effort", fake_unload),
        patch.object(AceStepClient, "_submit_task", return_value="task-1"),
        patch.object(
            AceStepClient, "_poll_result",
            return_value=_fake_poll_result(),
        ),
        patch.object(
            AceStepClient, "_download_audio",
            return_value=AceStepResult(wav_bytes=b"\x00" * 44, seed=42),
        ),
    ):
        client.generate(config)

    assert calls == ["load:/tmp/my-lora", "unload"]


def test_generate_does_not_unload_if_load_failed() -> None:
    client = _make_client()
    config = _config(lora_path="/tmp/bad")

    calls: list[str] = []

    def fake_ensure(self, lora_path: str) -> bool:
        calls.append("load-failed")
        return False

    def fake_unload(self) -> None:
        calls.append("unload")

    with (
        patch.object(AceStepClient, "_ensure_lora_loaded", fake_ensure),
        patch.object(AceStepClient, "_unload_lora_best_effort", fake_unload),
        patch.object(AceStepClient, "_submit_task", return_value="t"),
        patch.object(
            AceStepClient, "_poll_result", return_value=_fake_poll_result(),
        ),
        patch.object(
            AceStepClient, "_download_audio",
            return_value=AceStepResult(wav_bytes=b"\x00" * 44, seed=42),
        ),
    ):
        client.generate(config)

    assert calls == ["load-failed"]


def test_ensure_lora_loaded_idempotent_uses_sha_adapter_name() -> None:
    import hashlib

    client = _make_client()
    lora_path = "/tmp/my-lora"
    expected_name = hashlib.sha256(lora_path.encode()).hexdigest()[:16]
    captured: dict = {}

    def capture(req, timeout):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data)
        return mock_http_response(b"{}")

    with patch("acestep_engine.client.urlopen", side_effect=capture):
        result_a = client._ensure_lora_loaded(lora_path)
        result_b = client._ensure_lora_loaded(lora_path)
    assert result_a is True
    assert result_b is True
    assert "/v1/lora/load" in captured["url"]
    assert captured["body"]["adapter_name"] == expected_name


def test_ensure_lora_loaded_returns_false_on_network_error() -> None:
    from urllib.error import URLError

    client = _make_client()
    with patch("acestep_engine.client.urlopen", side_effect=URLError("boom")):
        assert client._ensure_lora_loaded("/tmp/x") is False


def test_unload_lora_best_effort_swallows_errors() -> None:
    from urllib.error import URLError

    client = _make_client()
    with patch("acestep_engine.client.urlopen", side_effect=URLError("boom")):
        client._unload_lora_best_effort()


def test_unload_lora_sends_post() -> None:
    client = _make_client()
    captured: dict = {}

    def capture(req, timeout):
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        return mock_http_response(b"{}")

    with patch("acestep_engine.client.urlopen", side_effect=capture):
        client._unload_lora_best_effort()
    assert "/v1/lora/unload" in captured["url"]
    assert captured["method"] == "POST"


def _fake_poll_result():
    from acestep_engine.client import _PollResult

    return _PollResult(audio_path="/tmp/x.wav", seed=42)


@pytest.mark.parametrize(
    "lora_a,lora_b,expect_same",
    [
        ("/tmp/a", "/tmp/a", True),
        ("/tmp/a", "/tmp/b", False),
    ],
)
def test_adapter_name_varies_with_path(lora_a, lora_b, expect_same) -> None:
    import hashlib

    name_a = hashlib.sha256(lora_a.encode()).hexdigest()[:16]
    name_b = hashlib.sha256(lora_b.encode()).hexdigest()[:16]
    assert (name_a == name_b) is expect_same
