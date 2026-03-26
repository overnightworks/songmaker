"""ACE-Step REST API client.

Talks to an ACE-Step 1.5 server running on localhost. The server runs
in a separate venv (.venv-acestep) because ACE-Step pins a different
torch version than Songmaker.

Server launch:  python scripts/start_acestep.py
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
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

log = logging.getLogger(__name__)

_FALLBACK_HOST: Final[str] = "http://localhost"
_FALLBACK_PORT: Final[int] = 8001
POLL_INTERVAL: Final[float] = 3.0
POLL_TIMEOUT: Final[float] = 1800.0
SUBMIT_RETRIES: Final[int] = 3
SUBMIT_RETRY_DELAYS: Final[tuple[float, ...]] = (1.0, 3.0, 10.0)
_TASK_STATUS_COMPLETE: Final[int] = 1
_TASK_STATUS_FAILED: Final[int] = 2
DOWNLOAD_DEADLINE_SECONDS: Final[float] = 60.0
_DOWNLOAD_CHUNK_SIZE: Final[int] = 65536


def _default_host() -> str:
    return os.environ.get("ACESTEP_HOST", _FALLBACK_HOST)


def _default_port() -> int:
    return int(os.environ.get("ACESTEP_PORT", _FALLBACK_PORT))


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
            duration=30,
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

    def generate(self, config: AceStepConfig) -> AceStepResult:
        """Generate music via ACE-Step and return audio samples.

        Submits a generation job, polls until complete, downloads the
        audio, and returns an AceStepResult.

        Args:
            config: Generation parameters.

        Raises:
            TaskSubmissionError: Failed to submit the generation task.
            GenerationFailedError: Server reported generation failure.
            GenerationTimeoutError: Polling timed out.
            AudioDownloadError: Failed to download or parse audio.
        """
        task_id = self._submit_task(config)
        audio_path, seed = self._poll_result(task_id)
        return self._download_audio(audio_path, seed)

    def _submit_task(self, config: AceStepConfig) -> str:
        """Submit a generation task to the server with retry.

        Retries up to SUBMIT_RETRIES times on transient network errors.

        Raises:
            TaskSubmissionError: On persistent network error or missing task_id.
        """
        payload = {
            "task_type": "text2music",
            "caption": config.prompt,
            "lyrics": config.lyrics,
            "bpm": config.bpm,
            "audio_duration": config.duration,
            "key_scale": config.key,
            "time_signature": config.time_signature,
            "vocal_language": config.vocal_language,
            "instrumental": config.instrumental,
            "seed": config.seed,
            "inference_steps": config.inference_steps,
            "guidance_scale": config.guidance_scale,
            "shift": config.shift,
            "thinking": config.think_mode not in ("off", "", "false"),
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

    def _poll_result(self, task_id: str) -> tuple[str, int]:
        """Poll until the generation task completes.

        Returns:
            Tuple of (audio_file_path, seed) on success.

        Raises:
            GenerationFailedError: Server reported failure.
            GenerationTimeoutError: Polling exceeded POLL_TIMEOUT.
            KeyboardInterrupt: User cancelled during generation.
        """
        payload = json.dumps({"task_id_list": [task_id]}).encode()
        start = time.monotonic()

        while time.monotonic() - start < POLL_TIMEOUT:
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
                        return items[0].file, items[0].seed
                    raise GenerationFailedError(
                        f"ACE-Step completed but no audio returned: {entry.result}"
                    )

                elapsed = time.monotonic() - start
                if entry.progress_text:
                    log.info("ACE-Step: %s (%.0fs)", entry.progress_text, elapsed)
                else:
                    log.info("ACE-Step generating... (%.0fs elapsed)", elapsed)

            except KeyboardInterrupt:
                log.warning("Generation cancelled by user (task_id=%s)", task_id)
                raise

            except (URLError, OSError, json.JSONDecodeError, PydanticValidationError) as exc:
                log.warning("Poll error (retrying): %s", exc)

            time.sleep(POLL_INTERVAL)

        raise GenerationTimeoutError(
            f"ACE-Step generation timed out after {POLL_TIMEOUT:.0f}s"
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
