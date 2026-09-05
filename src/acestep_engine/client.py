"""ACE-Step REST API client.

Talks to an ACE-Step 1.5 server running on localhost. The server runs
in a separate venv (.venv-acestep) because ACE-Step pins a different
torch version than Songmaker.

Server launch:  python scripts/start_acestep.py
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen
from uuid import uuid4

from pydantic import ValidationError as PydanticValidationError

from acestep_engine.errors import (
    AudioDownloadError,
    GenerationFailedError,
    GenerationTimeoutError,
    TaskSubmissionError,
)
from acestep_engine.models import (
    AceStepConfig,
    AceStepResult,
    ServerInfo,
    TaskQueryEntry,
    TaskQueryResponse,
    TaskSubmitResponse,
)
from acestep_engine.settings import get_engine_settings

log = logging.getLogger(__name__)

@dataclass(frozen=True)
class _PollResult:
    audio_path: str
    seed: int
    cot_caption: str = ""
    cot_lyrics: str = ""
    requested_batch_size: int | None = None
    delivered_batch_size: int | None = None


POLL_INTERVAL: Final[float] = 3.0
SUBMIT_RETRIES: Final[int] = 3
SUBMIT_RETRY_DELAYS: Final[tuple[float, ...]] = (1.0, 3.0, 10.0)
_TASK_STATUS_COMPLETE: Final[int] = 1
_TASK_STATUS_FAILED: Final[int] = 2
DOWNLOAD_DEADLINE_SECONDS: Final[float] = 60.0
_DOWNLOAD_CHUNK_SIZE: Final[int] = 65536
_NO_FAILURE_DETAIL: Final[str] = "generation failed (no detail from ACE-Step)"
_MAX_CAUSE_CHARS: Final[int] = 300
_AUDIO_UPLOAD_FIELDS: Final[tuple[tuple[str, str], ...]] = (
    ("src_audio_path", "ctx_audio"),
    ("reference_audio_path", "ref_audio"),
)
_JSON_CONTENT_TYPE: Final[str] = "application/json"


def _completed_poll_result(entry: TaskQueryEntry, started_at: float) -> _PollResult:
    items = entry.parse_result_items()
    if not items or not items[0].file:
        raise GenerationFailedError(
            f"ACE-Step completed but no audio returned: {entry.result}"
        )

    elapsed = time.monotonic() - started_at
    log.info("ACE-Step generation complete (%.1fs)", elapsed)
    item = items[0]
    return _PollResult(
        audio_path=item.file,
        seed=item.seed,
        cot_caption=item.cot_caption,
        cot_lyrics=item.cot_lyrics,
        requested_batch_size=item.requested_batch_size,
        delivered_batch_size=item.delivered_batch_size,
    )


def _report_poll_progress(
    entry: TaskQueryEntry,
    started_at: float,
    on_progress: Callable[[str], None] | None,
) -> None:
    elapsed = time.monotonic() - started_at
    progress = entry.progress_text or f"generating ({elapsed:.0f}s)"
    log.info("ACE-Step: %s", progress)
    if on_progress is not None:
        on_progress(progress)


def _failure_cause(entry: TaskQueryEntry) -> str:
    """Return ACE-Step's own text for a failed task, short enough to show.

    A failed task carries its cause in the result entry's ``error``
    field. The server records it as a full traceback, so only its last
    line — the exception type and message — is user-facing; the full
    text goes to the log. When the server sends no detail at all, the
    caller still gets a named reason instead of an empty string.
    """
    for item in entry.parse_result_items():
        detail = (item.error or item.status_message or "").strip()
        if detail:
            log.error("ACE-Step task %s failed: %s", entry.task_id, detail)
            return _shorten_cause(detail)
    log.error(
        "ACE-Step task %s failed without detail: %.500s", entry.task_id, entry.result,
    )
    return _NO_FAILURE_DETAIL


def _shorten_cause(detail: str) -> str:
    """Reduce a recorded traceback to a single capped line."""
    last_line = detail.splitlines()[-1].strip()
    if len(last_line) <= _MAX_CAUSE_CHARS:
        return last_line
    return last_line[: _MAX_CAUSE_CHARS - 1] + "\u2026"


def _default_host() -> str:
    return get_engine_settings().acestep_host


def _default_port() -> int:
    return get_engine_settings().acestep_port


def is_acestep_available(host: str | None = None, port: int | None = None) -> bool:
    """Check if the ACE-Step server is running and healthy."""
    host = host or _default_host()
    port = port or _default_port()
    try:
        req = Request(f"{host}:{port}/health", method="GET")
        with urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except OSError:
        return False


ALLOWED_AUDIO_PATH_RE = re.compile(
    r"^(?:/v1/audio\b|[a-zA-Z0-9_./ -]+$)"
)


def validate_audio_path(audio_path: str) -> None:
    """Reject server-returned audio paths that look like path traversal."""
    if ".." in audio_path or not ALLOWED_AUDIO_PATH_RE.match(audio_path):
        raise AudioDownloadError(
            f"Server returned suspicious audio path: {audio_path!r}"
        )


def _build_submit_payload(config: AceStepConfig) -> dict[str, object]:
    """Build the canonical ``/release_task`` payload for one generation."""
    payload: dict[str, object] = {
        "task_type": config.task_type,
        "prompt": config.prompt,
        "lyrics": config.lyrics,
        "bpm": config.bpm,
        "audio_duration": config.audio_duration,
        "key_scale": config.key_scale,
        "time_signature": config.time_signature,
        "vocal_language": config.vocal_language,
        "seed": config.seed,
        "use_random_seed": config.seed < 0,
        "inference_steps": config.inference_steps,
        "guidance_scale": config.guidance_scale,
        "shift": config.shift,
        "thinking": config.thinking,
        "lm_temperature": config.lm_temperature,
        "lm_top_k": config.lm_top_k,
        "lm_top_p": config.lm_top_p,
        "lm_cfg_scale": config.lm_cfg_scale,
        "infer_method": config.infer_method,
        "sampler_mode": config.sampler_mode,
        "velocity_norm_threshold": config.velocity_norm_threshold,
        "velocity_ema_factor": config.velocity_ema_factor,
        "latent_shift": config.latent_shift,
        "latent_rescale": config.latent_rescale,
        "audio_format": "wav",
        "batch_size": config.batch_size,
    }
    payload.update(_optional_submit_payload(config))
    return payload


def _optional_submit_payload(config: AceStepConfig) -> dict[str, object]:
    payload: dict[str, object] = {}
    optional_values = {
        "lm_negative_prompt": config.lm_negative_prompt,
        "src_audio_path": config.src_audio_path,
        "reference_audio_path": config.reference_audio_path,
        "timesteps": config.timesteps,
        "model": config.model,
    }
    payload.update({key: value for key, value in optional_values.items() if value})
    if config.task_type == "repaint":
        payload.update(_repaint_submit_payload(config))
    if config.task_type == "cover":
        payload.update(_cover_submit_payload(config))
    if not config.use_cot_caption:
        payload["use_cot_caption"] = False
    if not config.use_cot_language:
        payload["use_cot_language"] = False
    if config.constrained_decoding:
        payload["constrained_decoding"] = True
    if config.lm_repetition_penalty != 1.0:  # NOSONAR Exact protocol values must be forwarded.
        payload["lm_repetition_penalty"] = config.lm_repetition_penalty
    if config.use_adg:
        payload["use_adg"] = True
    if config.cfg_interval_start > 0.0:
        payload["cfg_interval_start"] = config.cfg_interval_start
    if config.cfg_interval_end < 1.0:
        payload["cfg_interval_end"] = config.cfg_interval_end
    return payload


def _repaint_submit_payload(config: AceStepConfig) -> dict[str, object]:
    payload: dict[str, object] = {
        "repainting_start": config.repainting_start,
        "repainting_end": config.repainting_end,
    }
    if config.repaint_mode:
        payload["repaint_mode"] = config.repaint_mode
    if config.repaint_strength != 0.5:  # NOSONAR Exact protocol values must be forwarded.
        payload["repaint_strength"] = config.repaint_strength
    if config.repaint_latent_crossfade_frames > 0:
        payload["repaint_latent_crossfade_frames"] = config.repaint_latent_crossfade_frames
    if config.repaint_wav_crossfade_sec > 0:
        payload["repaint_wav_crossfade_sec"] = config.repaint_wav_crossfade_sec
    return payload


def _cover_submit_payload(config: AceStepConfig) -> dict[str, object]:
    payload: dict[str, object] = {"audio_cover_strength": config.audio_cover_strength}
    if config.cover_noise_strength > 0:
        payload["cover_noise_strength"] = config.cover_noise_strength
    return payload


def _encode_multipart_submit_payload(payload: dict) -> tuple[bytes, str] | None:
    """Encode audio inputs as the multipart form accepted by ``/release_task``.

    Each upload is read completely into memory; a six-hour reference file needs
    a full in-memory buffer until its submission request is sent.
    """
    audio_files = [
        (payload_name, form_name, Path(path))
        for payload_name, form_name in _AUDIO_UPLOAD_FIELDS
        if isinstance(path := payload.get(payload_name), str) and path
    ]
    if not audio_files:
        return None

    for _, _, audio_path in audio_files:
        if not audio_path.is_file():
            raise TaskSubmissionError(
                f"ACE-Step audio input is not a file: {audio_path}",
            )

    boundary = f"----songmaker-{uuid4().hex}"
    chunks: list[bytes] = []
    audio_payload_names = {payload_name for payload_name, _, _ in audio_files}

    for name, value in payload.items():
        if name in audio_payload_names or value is None:
            continue
        chunks.extend((
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
            f"{str(value).lower() if isinstance(value, bool) else value}\r\n".encode(),
        ))

    for _, form_name, audio_path in audio_files:
        chunks.extend((
            f"--{boundary}\r\n".encode(),
            (
                "Content-Disposition: form-data; "
                f'name="{form_name}"; filename="{audio_path.name}"\r\n'
            ).encode(),
            b"Content-Type: audio/wav\r\n\r\n",
            audio_path.read_bytes(),
            b"\r\n",
        ))

    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


class AceStepClient:
    """HTTP client for the ACE-Step 1.5 REST API.

    Submits generation jobs, polls for completion, and downloads
    the result as stereo audio at the server's native sample rate.

    Usage:
        client = AceStepClient()
        result = client.generate(AceStepConfig(
            prompt="female vocal, piano ballad",
            lyrics="[verse]\\nHello world",
            bpm=72,
            audio_duration=30,
        ))
    """

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
    ) -> None:
        self.base_url = f"{host or _default_host()}:{port or _default_port()}"

    @property
    def is_available(self) -> bool:
        """Whether the ACE-Step server is reachable."""
        parsed = urlparse(self.base_url)
        host = f"{parsed.scheme}://{parsed.hostname}"
        port = parsed.port or _default_port()
        return is_acestep_available(host=host, port=port)

    def server_info(self) -> ServerInfo | None:
        """Fetch model and version info from the /health endpoint."""
        try:
            req = Request(f"{self.base_url}/health", method="GET")
            with urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read()).get("data", {})
            return ServerInfo(
                model=data.get("loaded_model", ""),
                lm_model=data.get("loaded_lm_model", ""),
                version=data.get("version", ""),
            )
        except (OSError, json.JSONDecodeError):
            return None

    def generate(
        self, config: AceStepConfig,
        on_progress: Callable[[str], None] | None = None,
    ) -> AceStepResult:
        """Generate music via ACE-Step and return audio samples.

        Args:
            config: Generation parameters.
            on_progress: Called with raw progress text on each poll tick.

        Raises:
            TaskSubmissionError: Failed to submit the generation task.
            GenerationFailedError: Server reported generation failure.
            GenerationTimeoutError: Polling timed out.
            AudioDownloadError: Failed to download or parse audio.
        """
        lora_loaded_by_us = False
        if config.lora_path:
            lora_loaded_by_us = self._ensure_lora_loaded(config.lora_path)
            if not lora_loaded_by_us:
                raise TaskSubmissionError(
                    f"Failed to load configured LoRA adapter: {config.lora_path}"
                )
        try:
            task_id = self._submit_task(config)
            poll_result = self._poll_result(task_id, on_progress=on_progress)
            result = self._download_audio(poll_result.audio_path, poll_result.seed)
            result = replace(
                result,
                cot_caption=poll_result.cot_caption,
                cot_lyrics=poll_result.cot_lyrics,
                requested_batch_size=poll_result.requested_batch_size,
                delivered_batch_size=poll_result.delivered_batch_size,
            )
            return result
        finally:
            if lora_loaded_by_us:
                self._unload_lora_best_effort()

    def _ensure_lora_loaded(self, lora_path: str) -> bool:
        """Load adapter if not already loaded. Returns True if we triggered the load.

        Adapter name is the sha256 of the path so repeated loads of the
        same path with the same adapter name are a no-op on the server
        side.
        """
        adapter_name = hashlib.sha256(lora_path.encode("utf-8")).hexdigest()[:16]
        try:
            payload = json.dumps(
                {"lora_path": lora_path, "adapter_name": adapter_name},
            ).encode()
            req = Request(
                f"{self.base_url}/v1/lora/load",
                data=payload,
                headers={"Content-Type": _JSON_CONTENT_TYPE},
                method="POST",
            )
            with urlopen(req, timeout=30) as resp:
                resp.read()
            log.info("LoRA loaded: path=%s adapter=%s", lora_path, adapter_name)
            return True
        except OSError as exc:
            log.warning("Failed to load LoRA %s: %s", lora_path, exc)
            return False

    def _unload_lora_best_effort(self) -> None:
        try:
            req = Request(
                f"{self.base_url}/v1/lora/unload",
                data=b"",
                headers={"Content-Type": _JSON_CONTENT_TYPE},
                method="POST",
            )
            with urlopen(req, timeout=30) as resp:
                resp.read()
            log.info("LoRA unloaded")
        except OSError as exc:
            log.warning("Failed to unload LoRA: %s", exc)

    def _submit_task(self, config: AceStepConfig) -> str:
        """Submit a generation task to the server with retry.

        Retries up to SUBMIT_RETRIES times on transient network errors.

        Raises:
            TaskSubmissionError: On persistent network error or missing task_id.
        """
        payload = _build_submit_payload(config)

        last_exc: Exception | None = None
        for attempt in range(SUBMIT_RETRIES):
            try:
                return self._send_submit_request(payload)
            except OSError as exc:
                last_exc = exc
                if attempt < SUBMIT_RETRIES - 1:
                    delay = SUBMIT_RETRY_DELAYS[attempt]
                    log.warning(
                        "Submit attempt %d/%d failed (%s), retrying in %.0fs",
                        attempt + 1, SUBMIT_RETRIES, exc, delay,
                    )
                    time.sleep(delay)
            except (json.JSONDecodeError, PydanticValidationError) as exc:
                raise TaskSubmissionError(
                    f"Failed to submit ACE-Step task: {exc}"
                ) from exc

        raise TaskSubmissionError(
            f"Failed to submit ACE-Step task after {SUBMIT_RETRIES} attempts: {last_exc}"
        ) from last_exc

    def _send_submit_request(self, payload: dict) -> str:
        """Send one submission request and return the task_id.

        Raises:
            URLError/OSError: On network error (retryable).
            json.JSONDecodeError/PydanticValidationError: On bad response (not retryable).
            TaskSubmissionError: If the server returns no task_id.
        """
        multipart = _encode_multipart_submit_payload(payload)
        if multipart is None:
            data = json.dumps(payload).encode()
            content_type = _JSON_CONTENT_TYPE
        else:
            data, content_type = multipart
        req = Request(
            f"{self.base_url}/release_task",
            data=data,
            headers={"Content-Type": content_type},
            method="POST",
        )
        with urlopen(req, timeout=30) as resp:
            raw = json.loads(resp.read())

        response = TaskSubmitResponse.model_validate(raw)
        task_id = response.data.task_id
        if not task_id:
            raise TaskSubmissionError(
                f"ACE-Step returned no task_id: {raw}"
            )

        log.info("ACE-Step task submitted: %s", task_id)
        return task_id

    def _poll_result(
        self, task_id: str,
        on_progress: Callable[[str], None] | None = None,
    ) -> _PollResult:
        """Poll until the generation task completes.

        Returns:
            _PollResult with audio path, seed, and optional CoT data.

        Raises:
            GenerationFailedError: Server reported failure.
            GenerationTimeoutError: Polling exceeded ``acestep_poll_timeout``.
            KeyboardInterrupt: User cancelled during generation.
        """
        poll_timeout = get_engine_settings().acestep_poll_timeout
        payload = json.dumps({"task_id_list": [task_id]}).encode()
        start = time.monotonic()

        while time.monotonic() - start < poll_timeout:
            try:
                result = self._read_polled_result(payload, start, on_progress)
                if result is not None:
                    return result

            except KeyboardInterrupt:
                log.warning("Generation cancelled by user (task_id=%s)", task_id)
                raise

            except (OSError, json.JSONDecodeError, PydanticValidationError) as exc:
                log.warning("Poll error (retrying): %s", exc)

            time.sleep(POLL_INTERVAL)

        raise GenerationTimeoutError(
            f"ACE-Step generation timed out after {poll_timeout:.0f}s"
        )

    def _read_polled_result(
        self,
        payload: bytes,
        started_at: float,
        on_progress: Callable[[str], None] | None,
    ) -> _PollResult | None:
        response = self._query_task_result(payload)
        if not response.data:
            return None

        entry = response.data[0]
        if entry.status == _TASK_STATUS_FAILED:
            raise GenerationFailedError(_failure_cause(entry))
        if entry.status == _TASK_STATUS_COMPLETE:
            return _completed_poll_result(entry, started_at)

        _report_poll_progress(entry, started_at, on_progress)
        return None

    def _query_task_result(self, payload: bytes) -> TaskQueryResponse:
        req = Request(
            f"{self.base_url}/query_result",
            data=payload,
            headers={"Content-Type": _JSON_CONTENT_TYPE},
            method="POST",
        )
        with urlopen(req, timeout=10) as resp:
            raw = json.loads(resp.read())
        return TaskQueryResponse.model_validate(raw)

    def _download_audio(
        self, audio_path: str, seed: int,
    ) -> AceStepResult:
        """Download generated audio from the server and return raw WAV bytes.

        Raises:
            AudioDownloadError: On network error or empty response.
        """
        try:
            validate_audio_path(audio_path)
            if audio_path.startswith("/"):
                url = f"{self.base_url}{audio_path}"
            else:
                url = f"{self.base_url}/v1/audio?path={quote(audio_path)}"
            req = Request(url, method="GET")
            with urlopen(req, timeout=60) as resp:
                start = time.monotonic()
                chunks: list[bytes] = []
                while True:
                    if time.monotonic() - start > DOWNLOAD_DEADLINE_SECONDS:
                        raise AudioDownloadError(
                            f"Audio download exceeded {DOWNLOAD_DEADLINE_SECONDS:.0f}s deadline"
                        )
                    chunk = resp.read(_DOWNLOAD_CHUNK_SIZE)
                    if not chunk:
                        break
                    chunks.append(chunk)
                wav_bytes = b"".join(chunks)

            if len(wav_bytes) < 44:
                raise AudioDownloadError("Downloaded audio is empty or too small")

            log.info("ACE-Step audio downloaded: %d bytes", len(wav_bytes))

            return AceStepResult(wav_bytes=wav_bytes, seed=seed)

        except OSError as exc:
            raise AudioDownloadError(
                f"Failed to download ACE-Step audio: {exc}"
            ) from exc
