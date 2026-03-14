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

import numpy as np

from acestep_engine.models import AceStepConfig, AceStepResult
from audio_engine.constants import TARGET_SAMPLE_RATE

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
    the result as audio samples at 44100 Hz mono.

    Usage:
        client = AceStepClient()
        if client.is_available:
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

    def generate(self, config: AceStepConfig) -> AceStepResult | None:
        """Generate music via ACE-Step and return audio samples.

        Submits a generation job, polls until complete, downloads the
        audio, resamples to 44100 Hz mono, and returns an AceStepResult.

        Args:
            config: Generation parameters.

        Returns:
            AceStepResult with audio samples, or None on failure.
        """
        if not self.is_available:
            log.error("ACE-Step server not available at %s", self.base_url)
            return None

        # Submit job
        task_id = self._submit_task(config)
        if task_id is None:
            return None

        # Poll for completion
        poll_result = self._poll_result(task_id)
        if poll_result is None:
            return None

        audio_path, seed = poll_result

        # Download and convert audio
        return self._download_audio(audio_path, seed)

    def _submit_task(self, config: AceStepConfig) -> str | None:
        """Submit a generation task to the server."""
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
                log.error("ACE-Step returned no task_id: %s", result)
                return None

            log.info("ACE-Step task submitted: %s", task_id)
            return task_id

        except (URLError, OSError, json.JSONDecodeError) as exc:
            log.error("Failed to submit ACE-Step task: %s", exc)
            return None

    def _poll_result(self, task_id: str) -> tuple[str, int] | None:
        """Poll until the generation task completes.

        Returns:
            Tuple of (audio_file_path, seed) on success, or None on failure.
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
                    # Failed
                    result_str = entry.get("result", "[]")
                    log.error("ACE-Step generation failed: %s", result_str)
                    return None

                if status == 1:
                    # Succeeded — extract audio path from result
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
                    log.error("ACE-Step completed but no audio returned: %s", result_str)
                    return None

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

        log.error("ACE-Step generation timed out after %.0fs", POLL_TIMEOUT)
        return None

    def _download_audio(
        self, audio_path: str, seed: int,
    ) -> AceStepResult | None:
        """Download generated audio from the server and convert to samples."""
        try:
            # audio_path may be a full URL path (/v1/audio?path=...) or a raw file path
            if audio_path.startswith("/"):
                url = f"{self.base_url}{audio_path}"
            else:
                from urllib.parse import quote
                url = f"{self.base_url}/v1/audio?path={quote(audio_path)}"
            req = Request(url, method="GET")
            with urlopen(req, timeout=60) as resp:
                wav_bytes = resp.read()

            from audio_engine.audio_io import read_wav_bytes
            samples, src_rate = read_wav_bytes(wav_bytes)
            if len(samples) == 0:
                log.error("Downloaded audio is empty")
                return None

            # Resample from 48000 to 44100 if needed
            if src_rate != TARGET_SAMPLE_RATE:
                samples = _resample(samples, src_rate, TARGET_SAMPLE_RATE)

            duration = len(samples) / TARGET_SAMPLE_RATE

            log.info(
                "ACE-Step audio downloaded: %.1fs at %d Hz",
                duration, TARGET_SAMPLE_RATE,
            )

            return AceStepResult(
                samples=samples,
                sample_rate=TARGET_SAMPLE_RATE,
                duration=duration,
                seed=seed,
            )

        except (URLError, OSError) as exc:
            log.error("Failed to download ACE-Step audio: %s", exc)
            return None


def _resample(
    samples: np.ndarray, src_rate: int, dst_rate: int,
) -> np.ndarray:
    """Resample audio from src_rate to dst_rate via scipy.signal.resample_poly."""
    import math

    if src_rate == dst_rate:
        return samples

    from scipy.signal import resample_poly

    gcd = math.gcd(dst_rate, src_rate)
    up, down = dst_rate // gcd, src_rate // gcd
    return resample_poly(samples, up, down).astype(np.float64)
