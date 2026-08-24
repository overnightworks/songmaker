"""Tests for the ACE-Step HTTP client (mocked)."""

from __future__ import annotations

import json
from http.client import HTTPResponse
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from conftest import mock_http_response as _mock_response

from acestep_engine.client import (
    _MAX_CAUSE_CHARS,
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


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        (
            AceStepConfig(prompt="test", lyrics="test"),
            {
                "sampler_mode": "euler",
                "velocity_norm_threshold": 0.0,
                "velocity_ema_factor": 0.0,
                "latent_shift": 0.0,
                "latent_rescale": 1.0,
                "use_random_seed": True,
            },
        ),
        (
            AceStepConfig(
                prompt="test",
                lyrics="test",
                seed=42,
                sampler_mode="heun",
                velocity_norm_threshold=2.0,
                velocity_ema_factor=0.1,
                latent_shift=0.05,
                latent_rescale=1.2,
            ),
            {
                "sampler_mode": "heun",
                "velocity_norm_threshold": 2.0,
                "velocity_ema_factor": 0.1,
                "latent_shift": 0.05,
                "latent_rescale": 1.2,
                "use_random_seed": False,
            },
        ),
    ],
)
def test_submit_task_forwards_dit_params_and_seed_policy(
    config: AceStepConfig, expected: dict[str, object],
) -> None:
    """The payload handed to the HTTP sender contains every visible DiT knob."""
    client = AceStepClient()

    with patch.object(
        client, "_send_submit_request", return_value="abc123",
    ) as mock_send:
        assert client._submit_task(config) == "abc123"

    payload = mock_send.call_args.args[0]
    assert {name: payload[name] for name in expected} == expected


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

    result_items = json.dumps([{"file": "/v1/audio?path=test.wav", "seed_value": "42"}])
    response_data = json.dumps({
        "data": [{"task_id": "abc", "status": 1, "result": result_items}],
    }).encode()

    with patch("acestep_engine.client.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _mock_response(response_data)
        result = client._poll_result("abc")

    assert result is not None
    assert result.audio_path == "/v1/audio?path=test.wav"
    assert result.seed == 42


def test_poll_result_surfaces_batch_reduction() -> None:
    """A VRAM-guard batch reduction on the server must reach the caller.

    The server can silently cut the requested batch size down; the poll
    result has to carry both numbers so nothing downstream has to infer
    a reduction happened from a missing audio file.
    """
    client = AceStepClient()

    result_items = json.dumps([{
        "file": "/v1/audio?path=test.wav",
        "seed_value": "42",
        "requested_batch_size": 2,
        "delivered_batch_size": 1,
    }])
    response_data = json.dumps({
        "data": [{"task_id": "abc", "status": 1, "result": result_items}],
    }).encode()

    with patch("acestep_engine.client.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _mock_response(response_data)
        result = client._poll_result("abc")

    assert result.requested_batch_size == 2
    assert result.delivered_batch_size == 1


_VRAM_CAUSE = (
    "Music generation failed: Insufficient free VRAM: "
    "need ~2.0 GB, only 1.3 GB available"
)
_VRAM_TRACEBACK = (
    "Traceback (most recent call last):\n"
    '  File "/opt/acestep/acestep/api/job_execution_runtime.py", line 79, in _run\n'
    "    result = run_fn()\n"
    f"RuntimeError: {_VRAM_CAUSE}"
)
_NO_DETAIL = "generation failed (no detail from ACE-Step)"


def _failed_cache_entry(**overrides: object) -> str:
    """The failure payload ACE-Step caches for a failed job.

    Mirrors ``update_local_cache`` in the vendored fork, which serves
    ``/query_result`` before the job store does.
    """
    entry: dict[str, object] = {
        "file": "",
        "wave": "",
        "status": 2,
        "create_time": 1755000000,
        "env": "development",
        "progress": 0.0,
        "stage": "failed",
        "error": None,
    }
    entry.update(overrides)
    return json.dumps([entry])


@pytest.mark.parametrize(
    ("result", "expected_message"),
    [
        (_failed_cache_entry(error=_VRAM_TRACEBACK), f"RuntimeError: {_VRAM_CAUSE}"),
        (_failed_cache_entry(error=_VRAM_CAUSE), _VRAM_CAUSE),
        (_failed_cache_entry(error=None), _NO_DETAIL),
        (_failed_cache_entry(error=""), _NO_DETAIL),
        (_failed_cache_entry(error=None, status_message="Model load failed"),
         "Model load failed"),
        ("not json at all", _NO_DETAIL),
    ],
)
def test_poll_result_failure_reports_acestep_cause(
    result: str, expected_message: str,
) -> None:
    client = AceStepClient()

    response_data = json.dumps({
        "data": [{"task_id": "abc", "status": 2, "result": result}],
    }).encode()

    with patch("acestep_engine.client.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _mock_response(response_data)
        with pytest.raises(GenerationFailedError) as excinfo:
            client._poll_result("abc")

    assert str(excinfo.value) == expected_message


def test_poll_result_failure_caps_the_cause_and_logs_it_in_full(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = AceStepClient()
    long_cause = "RuntimeError: " + "x" * 1000
    response_data = json.dumps({
        "data": [{
            "task_id": "abc",
            "status": 2,
            "result": _failed_cache_entry(error=long_cause),
        }],
    }).encode()

    with patch("acestep_engine.client.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _mock_response(response_data)
        with caplog.at_level("ERROR", logger="acestep_engine.client"):
            with pytest.raises(GenerationFailedError) as excinfo:
                client._poll_result("abc")

    message = str(excinfo.value)
    assert len(message) == _MAX_CAUSE_CHARS
    assert message.startswith("RuntimeError: x")
    assert message.endswith("\u2026")
    assert any(long_cause in record.getMessage() for record in caplog.records)


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
    result_items = json.dumps([{"file": "", "seed_value": "1"}])
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
    result_items = json.dumps([{"file": "/v1/audio?path=test.wav", "seed_value": "7"}])
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
    assert result.requested_batch_size is None
    assert result.delivered_batch_size is None


def test_generate_full_flow_surfaces_batch_reduction() -> None:
    """`generate()` must return the server's requested/delivered batch size.

    Confirms the field survives the whole submit -> poll -> download path,
    not just the isolated `_poll_result` step.
    """
    client = AceStepClient()
    config = AceStepConfig(prompt="test", lyrics="[verse]\nHello")
    wav_header = b"RIFF" + b"\x00" * 40 + b"extra_data_here"

    submit_resp = json.dumps({
        "data": {"task_id": "t1", "status": "queued"}, "code": 200,
    }).encode()
    result_items = json.dumps([{
        "file": "/v1/audio?path=test.wav",
        "seed_value": "7",
        "requested_batch_size": 2,
        "delivered_batch_size": 1,
    }])
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

    assert result.requested_batch_size == 2
    assert result.delivered_batch_size == 1


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


# ── lm_negative_prompt in payload ──────────────────────────────────


def test_submit_task_with_lm_negative_prompt() -> None:
    client = AceStepClient()
    config = AceStepConfig(
        prompt="test", lyrics="[verse]\nHello",
        lm_negative_prompt="no drums",
    )

    response_data = json.dumps({
        "data": {"task_id": "abc123", "status": "queued"},
        "code": 200,
    }).encode()

    with patch("acestep_engine.client.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _mock_response(response_data)
        task_id = client._submit_task(config)

    assert task_id == "abc123"
    call_args = mock_urlopen.call_args
    req = call_args[0][0]
    payload = json.loads(req.data)
    assert payload["lm_negative_prompt"] == "no drums"


# ── repaint/cover payload keys ────────────────────────────────────


def test_submit_task_repaint_sends_src_audio_path() -> None:
    client = AceStepClient()
    config = AceStepConfig(
        prompt="test", lyrics="la la",
        task_type="repaint", src_audio_path="/audio/src.wav",
        repainting_start=10.0, repainting_end=20.0,
    )

    response_data = json.dumps({
        "data": {"task_id": "r1", "status": "queued"},
        "code": 200,
    }).encode()

    with patch("acestep_engine.client.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _mock_response(response_data)
        client._submit_task(config)

    payload = json.loads(mock_urlopen.call_args[0][0].data)
    assert payload["src_audio_path"] == "/audio/src.wav"
    assert "src_audio" not in payload
    assert payload["repainting_start"] == 10.0
    assert payload["repainting_end"] == 20.0


def test_submit_task_sends_reference_audio_path() -> None:
    client = AceStepClient()
    config = AceStepConfig(
        prompt="test", lyrics="la la",
        reference_audio_path="/audio/ref.wav",
    )

    response_data = json.dumps({
        "data": {"task_id": "ref1", "status": "queued"},
        "code": 200,
    }).encode()

    with patch("acestep_engine.client.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _mock_response(response_data)
        client._submit_task(config)

    payload = json.loads(mock_urlopen.call_args[0][0].data)
    assert payload["reference_audio_path"] == "/audio/ref.wav"
    assert "reference_audio" not in payload


# ── submit json/pydantic decode error (non-retryable) ─────────────


def test_submit_task_bad_json_response() -> None:
    client = AceStepClient()
    config = AceStepConfig(prompt="test", lyrics="test")

    with patch("acestep_engine.client.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _mock_response(b"not json at all")
        with pytest.raises(TaskSubmissionError, match="Failed to submit"):
            client._submit_task(config)


# ── poll empty data continues ──────────────────────────────────────


def test_poll_result_empty_data_continues() -> None:
    client = AceStepClient()

    empty_resp = json.dumps({"data": []}).encode()
    result_items = json.dumps([{"file": "/v1/audio?path=test.wav", "seed_value": "42"}])
    success_resp = json.dumps({
        "data": [{"task_id": "abc", "status": 1, "result": result_items}],
    }).encode()

    with (
        patch("acestep_engine.client.urlopen") as mock_urlopen,
        patch("acestep_engine.client.time.sleep"),
    ):
        mock_urlopen.side_effect = [
            _mock_response(empty_resp),
            _mock_response(success_resp),
        ]
        result = client._poll_result("abc")

    assert result.audio_path == "/v1/audio?path=test.wav"
    assert result.seed == 42


# ── poll with progress_text logging ────────────────────────────────


def test_poll_result_logs_progress_text() -> None:
    client = AceStepClient()

    progress_resp = json.dumps({
        "data": [{"task_id": "abc", "status": 0, "progress_text": "Generating bars 10/20"}],
    }).encode()
    result_items = json.dumps([{"file": "/v1/audio?path=test.wav", "seed_value": "1"}])
    success_resp = json.dumps({
        "data": [{"task_id": "abc", "status": 1, "result": result_items}],
    }).encode()

    call_count = 0

    def fake_monotonic() -> float:
        nonlocal call_count
        call_count += 1
        return 0.0

    with (
        patch("acestep_engine.client.urlopen") as mock_urlopen,
        patch("acestep_engine.client.time.sleep"),
        patch("acestep_engine.client.time.monotonic", side_effect=fake_monotonic),
    ):
        mock_urlopen.side_effect = [
            _mock_response(progress_resp),
            _mock_response(success_resp),
        ]
        result = client._poll_result("abc")

    assert result.audio_path == "/v1/audio?path=test.wav"
    assert result.seed == 1


# ── poll with no progress_text logging ─────────────────────────────


def test_poll_result_logs_elapsed_without_progress_text() -> None:
    client = AceStepClient()

    progress_resp = json.dumps({
        "data": [{"task_id": "abc", "status": 0, "progress_text": ""}],
    }).encode()
    result_items = json.dumps([{"file": "/v1/audio?path=test.wav", "seed_value": "1"}])
    success_resp = json.dumps({
        "data": [{"task_id": "abc", "status": 1, "result": result_items}],
    }).encode()

    call_count = 0

    def fake_monotonic() -> float:
        nonlocal call_count
        call_count += 1
        return 0.0

    with (
        patch("acestep_engine.client.urlopen") as mock_urlopen,
        patch("acestep_engine.client.time.sleep"),
        patch("acestep_engine.client.time.monotonic", side_effect=fake_monotonic),
    ):
        mock_urlopen.side_effect = [
            _mock_response(progress_resp),
            _mock_response(success_resp),
        ]
        result = client._poll_result("abc")

    assert result.audio_path == "/v1/audio?path=test.wav"
    assert result.seed == 1


# ── poll KeyboardInterrupt ─────────────────────────────────────────


def test_poll_result_keyboard_interrupt() -> None:
    client = AceStepClient()

    with (
        patch("acestep_engine.client.urlopen") as mock_urlopen,
        patch("acestep_engine.client.time.sleep"),
    ):
        mock_urlopen.side_effect = KeyboardInterrupt
        with pytest.raises(KeyboardInterrupt):
            client._poll_result("abc")


# ── poll transient error retries ───────────────────────────────────


def test_poll_result_retries_on_transient_error() -> None:
    client = AceStepClient()

    from urllib.error import URLError

    result_items = json.dumps([{"file": "/v1/audio?path=test.wav", "seed_value": "1"}])
    success_resp = json.dumps({
        "data": [{"task_id": "abc", "status": 1, "result": result_items}],
    }).encode()

    with (
        patch("acestep_engine.client.urlopen") as mock_urlopen,
        patch("acestep_engine.client.time.sleep"),
    ):
        mock_urlopen.side_effect = [
            URLError("transient error"),
            _mock_response(success_resp),
        ]
        result = client._poll_result("abc")

    assert result.audio_path == "/v1/audio?path=test.wav"
    assert result.seed == 1


# ── acestep_engine/models.py coverage ─────────────────────────────


def test_result_item_seed_invalid() -> None:
    from acestep_engine.models import ResultItem

    item = ResultItem(file="test.wav", seed_value="not_a_number")
    assert item.seed == -1


def test_result_item_seed_empty() -> None:
    from acestep_engine.models import ResultItem

    item = ResultItem(file="test.wav", seed_value="")
    assert item.seed == -1


def test_task_query_entry_parse_invalid_json_string() -> None:
    from acestep_engine.models import TaskQueryEntry

    entry = TaskQueryEntry(result="not valid json{{{")
    items = entry.parse_result_items()
    assert items == []


def test_task_query_entry_parse_non_list_result() -> None:
    from acestep_engine.models import TaskQueryEntry

    entry = TaskQueryEntry(result=json.dumps({"key": "value"}))
    items = entry.parse_result_items()
    assert items == []


def test_task_query_entry_parse_list_with_non_dict() -> None:
    from acestep_engine.models import TaskQueryEntry

    entry = TaskQueryEntry(result=json.dumps(["not a dict", 42]))
    items = entry.parse_result_items()
    assert items == []


# ── download deadline ─────────────────────────────────────────────


def test_download_audio_deadline_exceeded() -> None:
    client = AceStepClient()

    call_count = 0

    def fake_monotonic() -> float:
        nonlocal call_count
        call_count += 1
        if call_count <= 1:
            return 0.0
        return 999.0

    wav_data = b"RIFF" + b"\x00" * 100

    resp = MagicMock(spec=HTTPResponse)
    resp.status = 200
    buf = BytesIO(wav_data)
    resp.read = buf.read
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)

    with (
        patch("acestep_engine.client.urlopen", return_value=resp),
        patch("acestep_engine.client.time.monotonic", side_effect=fake_monotonic),
    ):
        with pytest.raises(AudioDownloadError, match="exceeded"):
            client._download_audio("/v1/audio?path=test.wav", 1)
