"""ACE-Step REST API client.

Talks to an ACE-Step 1.5 server running on localhost. The server runs
in a separate venv (.venv-acestep) because ACE-Step pins a different
torch version than Songmaker.

Server launch:  python scripts/start_acestep.py
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Final
from urllib.error import URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

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


POLL_INTERVAL: Final[float] = 3.0
SUBMIT_RETRIES: Final[int] = 3
SUBMIT_RETRY_DELAYS: Final[tuple[float, ...]] = (1.0, 3.0, 10.0)
_TASK_STATUS_COMPLETE: Final[int] = 1
_TASK_STATUS_FAILED: Final[int] = 2
DOWNLOAD_DEADLINE_SECONDS: Final[float] = 60.0
_DOWNLOAD_CHUNK_SIZE: Final[int] = 65536


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
    except (URLError, OSError):
        return False


ALLOWED_AUDIO_PATH_RE = re.compile(r"^(/v1/audio\b|[a-zA-Z0-9_./ -]+$)")


def validate_audio_path(audio_path: str) -> None:
    """Reject server-returned audio paths that look like path traversal."""
    if ".." in audio_path or not ALLOWED_AUDIO_PATH_RE.match(audio_path):
        raise AudioDownloadError(
            f"Server returned suspicious audio path: {audio_path!r}"
        )


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
        except (URLError, OSError, json.JSONDecodeError):
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
        task_id = self._submit_task(config)
        poll_result = self._poll_result(task_id, on_progress=on_progress)
        result = self._download_audio(poll_result.audio_path, poll_result.seed)
        if poll_result.cot_caption or poll_result.cot_lyrics:
            result = replace(
                result,
                cot_caption=poll_result.cot_caption,
                cot_lyrics=poll_result.cot_lyrics,
            )
        return result

    def _submit_task(self, config: AceStepConfig) -> str:
        """Submit a generation task to the server with retry.

        Retries up to SUBMIT_RETRIES times on transient network errors.

        Raises:
            TaskSubmissionError: On persistent network error or missing task_id.
        """
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
            "audio_format": "wav",
            "batch_size": config.batch_size,
        }
        if config.lm_negative_prompt:
            payload["lm_negative_prompt"] = config.lm_negative_prompt
        if config.src_audio_path:
            payload["src_audio_path"] = config.src_audio_path
        if config.task_type == "repaint":
            payload["repainting_start"] = config.repainting_start
            payload["repainting_end"] = config.repainting_end
            if config.repaint_mode:
                payload["repaint_mode"] = config.repaint_mode
            if config.repaint_strength != 0.5:
                payload["repaint_strength"] = config.repaint_strength
            if config.repaint_latent_crossfade_frames > 0:
                payload["repaint_latent_crossfade_frames"] = config.repaint_latent_crossfade_frames
            if config.repaint_wav_crossfade_sec > 0:
                payload["repaint_wav_crossfade_sec"] = config.repaint_wav_crossfade_sec
        if config.task_type == "cover":
            payload["audio_cover_strength"] = config.audio_cover_strength
            if config.cover_noise_strength > 0:
                payload["cover_noise_strength"] = config.cover_noise_strength
        if config.reference_audio_path:
            payload["reference_audio_path"] = config.reference_audio_path
        if config.timesteps:
            payload["timesteps"] = config.timesteps
        if not config.use_cot_caption:
            payload["use_cot_caption"] = False
        if not config.use_cot_language:
            payload["use_cot_language"] = False
        if config.constrained_decoding:
            payload["constrained_decoding"] = True
        if config.lm_repetition_penalty != 1.0:
            payload["lm_repetition_penalty"] = config.lm_repetition_penalty
        if config.use_adg:
            payload["use_adg"] = True
        if config.cfg_interval_start > 0.0:
            payload["cfg_interval_start"] = config.cfg_interval_start
        if config.cfg_interval_end < 1.0:
            payload["cfg_interval_end"] = config.cfg_interval_end
        if config.model:
            payload["model"] = config.model

        last_exc: Exception | None = None
        for attempt in range(SUBMIT_RETRIES):
            try:
                return self._send_submit_request(payload)
            except (URLError, OSError) as exc:
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
        data = json.dumps(payload).encode()
        req = Request(
            f"{self.base_url}/release_task",
            data=data,
            headers={"Content-Type": "application/json"},
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
                req = Request(
                    f"{self.base_url}/query_result",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(req, timeout=10) as resp:
                    raw = json.loads(resp.read())

                response = TaskQueryResponse.model_validate(raw)
                if not response.data:
                    time.sleep(POLL_INTERVAL)
                    continue

                entry = response.data[0]

                if entry.status == _TASK_STATUS_FAILED:
                    raise GenerationFailedError(
                        f"ACE-Step generation failed: {entry.result}"
                    )

                if entry.status == _TASK_STATUS_COMPLETE:
                    items = entry.parse_result_items()
                    if items and items[0].file:
                        elapsed = time.monotonic() - start
                        log.info("ACE-Step generation complete (%.1fs)", elapsed)
                        item = items[0]
                        return _PollResult(
                            audio_path=item.file,
                            seed=item.seed,
                            cot_caption=item.cot_caption,
                            cot_lyrics=item.cot_lyrics,
                        )
                    raise GenerationFailedError(
                        f"ACE-Step completed but no audio returned: {entry.result}"
                    )

                elapsed = time.monotonic() - start
                progress = entry.progress_text or f"generating ({elapsed:.0f}s)"
                log.info("ACE-Step: %s", progress)
                if on_progress:
                    on_progress(progress)

            except KeyboardInterrupt:
                log.warning("Generation cancelled by user (task_id=%s)", task_id)
                raise

            except (URLError, OSError, json.JSONDecodeError, PydanticValidationError) as exc:
                log.warning("Poll error (retrying): %s", exc)

            time.sleep(POLL_INTERVAL)

        raise GenerationTimeoutError(
            f"ACE-Step generation timed out after {poll_timeout:.0f}s"
        )

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

        except (URLError, OSError) as exc:
            raise AudioDownloadError(
                f"Failed to download ACE-Step audio: {exc}"
            ) from exc
