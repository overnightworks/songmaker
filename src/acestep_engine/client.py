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
import time
from typing import Final
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from acestep_engine.errors import (
    AudioDownloadError,
    GenerationFailedError,
    GenerationTimeoutError,
    ServerUnavailableError,
    TaskSubmissionError,
)
from acestep_engine.models import AceStepConfig, AceStepResult

log = logging.getLogger(__name__)

DEFAULT_HOST: Final[str] = os.environ.get("ACESTEP_HOST", "http://localhost")
DEFAULT_PORT: Final[int] = int(os.environ.get("ACESTEP_PORT", "8001"))
POLL_INTERVAL: Final[float] = 3.0
POLL_TIMEOUT: Final[float] = 1800.0


def is_acestep_available(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> bool:
    """Check if the ACE-Step server is running and healthy."""
    try:
        req = Request(f"{host}:{port}/health", method="GET")
        with urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except (URLError, OSError, TimeoutError):
        return False


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
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
    ) -> None:
        self.base_url = f"{host}:{port}"

    @property
    def is_available(self) -> bool:
        """Whether the ACE-Step server is reachable."""
        parsed = urlparse(self.base_url)
        host = f"{parsed.scheme}://{parsed.hostname}"
        port = parsed.port or DEFAULT_PORT
        return is_acestep_available(host=host, port=port)

    def generate(self, config: AceStepConfig) -> AceStepResult:
        """Generate music via ACE-Step and return audio samples.

        Submits a generation job, polls until complete, downloads the
        audio, and returns an AceStepResult.

        Args:
            config: Generation parameters.

        Raises:
            ServerUnavailableError: Server is not reachable.
            TaskSubmissionError: Failed to submit the generation task.
            GenerationFailedError: Server reported generation failure.
            GenerationTimeoutError: Polling timed out.
            AudioDownloadError: Failed to download or parse audio.
        """
        if not self.is_available:
            raise ServerUnavailableError(
                f"ACE-Step server not available at {self.base_url}"
            )

        task_id = self._submit_task(config)
        audio_path, seed = self._poll_result(task_id)
        return self._download_audio(audio_path, seed)

    def _submit_task(self, config: AceStepConfig) -> str:
        """Submit a generation task to the server.

        Raises:
            TaskSubmissionError: On network error or missing task_id.
        """
        payload = {
            "task_type": "text2music",
            "caption": config.prompt,
            "lyrics": config.lyrics,
            "bpm": config.bpm,
            "audio_duration": config.duration,
            "key_scale": config.key,        # server field name
            "keyscale": config.key,         # v1.5 alternate field name
            "time_signature": config.time_signature,
            "vocal_language": config.vocal_language,
            "instrumental": config.instrumental,
            "seed": config.seed,
            "inference_steps": config.inference_steps,
            "guidance_scale": config.guidance_scale,
            "shift": config.shift,
            "thinking": config.think_mode,   # server field is "thinking" not "think"
            "lm_temperature": config.lm_temperature,
            "infer_method": config.infer_method,
            "audio_format": "wav",
            "batch_size": 1,
        }

        try:
            data = json.dumps(payload).encode()
            req = Request(
                f"{self.base_url}/release_task",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())

            # Response is wrapped: {"data": {"task_id": ..., "status": "queued"}, "code": 200}
            inner = result.get("data", result)
            task_id = inner.get("task_id") if isinstance(inner, dict) else None
            if not task_id:
                raise TaskSubmissionError(
                    f"ACE-Step returned no task_id: {result}"
                )

            log.info("ACE-Step task submitted: %s", task_id)
            return task_id

        except (URLError, OSError, json.JSONDecodeError) as exc:
            raise TaskSubmissionError(
                f"Failed to submit ACE-Step task: {exc}"
            ) from exc

    def _poll_result(self, task_id: str) -> tuple[str, int]:
        """Poll until the generation task completes.

        Returns:
            Tuple of (audio_file_path, seed) on success.

        Raises:
            GenerationFailedError: Server reported failure.
            GenerationTimeoutError: Polling exceeded POLL_TIMEOUT.
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
                    result = json.loads(resp.read())

                # Response: {"data": [{"task_id": ..., "result": "<json>", "status": 0|1|2}]}
                # Status mapping: 0=queued/running, 1=succeeded, 2=failed
                data_list = result.get("data", [])
                if not data_list:
                    time.sleep(POLL_INTERVAL)
                    continue

                entry = data_list[0]
                status = entry.get("status", 0)

                if status == 2:
                    result_str = entry.get("result", "[]")
                    raise GenerationFailedError(
                        f"ACE-Step generation failed: {result_str}"
                    )

                if status == 1:
                    result_str = entry.get("result", "[]")
                    try:
                        items = (
                            json.loads(result_str)
                            if isinstance(result_str, str)
                            else result_str
                        )
                    except json.JSONDecodeError:
                        items = []

                    if items and isinstance(items, list):
                        item = items[0]
                        file_path = item.get("file", "")
                        if file_path:
                            elapsed = time.monotonic() - start
                            seed = item.get("seed", -1)
                            log.info(
                                "ACE-Step generation complete (%.1fs)", elapsed,
                            )
                            return file_path, seed
                    raise GenerationFailedError(
                        f"ACE-Step completed but no audio returned: {result_str}"
                    )

                # Still processing
                elapsed = time.monotonic() - start
                progress_text = entry.get("progress_text", "")
                if progress_text:
                    log.info("ACE-Step: %s (%.0fs)", progress_text, elapsed)
                else:
                    log.info("ACE-Step generating... (%.0fs elapsed)", elapsed)

            except (URLError, OSError, json.JSONDecodeError) as exc:
                log.warning("Poll error (retrying): %s", exc)

            time.sleep(POLL_INTERVAL)

        raise GenerationTimeoutError(
            f"ACE-Step generation timed out after {POLL_TIMEOUT:.0f}s"
        )

    def _download_audio(
        self, audio_path: str, seed: int,
    ) -> AceStepResult:
        """Download generated audio from the server and return stereo samples.

        Raises:
            AudioDownloadError: On network error or empty/unparseable audio.
        """
        try:
            if audio_path.startswith("/"):
                url = f"{self.base_url}{audio_path}"
            else:
                from urllib.parse import quote
                url = f"{self.base_url}/v1/audio?path={quote(audio_path)}"
            req = Request(url, method="GET")
            with urlopen(req, timeout=60) as resp:
                wav_bytes = resp.read()

            from audio_engine.audio_io import read_wav_bytes
            left, right, sample_rate = read_wav_bytes(wav_bytes)
            if len(left) == 0:
                raise AudioDownloadError("Downloaded audio is empty")

            duration = len(left) / sample_rate

            log.info(
                "ACE-Step audio downloaded: %.1fs at %d Hz",
                duration, sample_rate,
            )

            return AceStepResult(
                left=left,
                right=right,
                sample_rate=sample_rate,
                duration=duration,
                seed=seed,
            )

        except (URLError, OSError) as exc:
            raise AudioDownloadError(
                f"Failed to download ACE-Step audio: {exc}"
            ) from exc
