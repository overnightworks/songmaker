"""ACE-Step REST API client.

Talks to an ACE-Step 1.5 server running on localhost. The server runs
in a separate venv (.venv-acestep) because ACE-Step pins a different
torch version than Songmaker.

Server launch:  python scripts/start_acestep.py
"""

from __future__ import annotations

import json
import logging
import struct
import time
from typing import Final
from urllib.error import URLError
from urllib.request import Request, urlopen

from acestep_engine.models import AceStepConfig, AceStepResult

logger = logging.getLogger(__name__)

DEFAULT_HOST: Final[str] = "http://localhost"
DEFAULT_PORT: Final[int] = 8001
TARGET_SAMPLE_RATE: Final[int] = 44100
POLL_INTERVAL: Final[float] = 3.0
POLL_TIMEOUT: Final[float] = 600.0


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
        return is_acestep_available(
            host=self.base_url.rsplit(":", 1)[0],
            port=int(self.base_url.rsplit(":", 1)[1]),
        )

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
            logger.error("ACE-Step server not available at %s", self.base_url)
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
            "key_scale": config.key,
            "time_signature": config.time_signature,
            "vocal_language": config.vocal_language,
            "instrumental": config.instrumental,
            "seed": config.seed,
            "inference_steps": config.inference_steps,
            "guidance_scale": config.guidance_scale,
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
                logger.error("ACE-Step returned no task_id: %s", result)
                return None

            logger.info("ACE-Step task submitted: %s", task_id)
            return task_id

        except (URLError, OSError, json.JSONDecodeError) as exc:
            logger.error("Failed to submit ACE-Step task: %s", exc)
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
                    logger.error("ACE-Step generation failed: %s", result_str)
                    return None

                if status == 1:
                    # Succeeded — extract audio path from result
                    result_str = entry.get("result", "[]")
                    try:
                        items = json.loads(result_str) if isinstance(result_str, str) else result_str
                    except json.JSONDecodeError:
                        items = []

                    if items and isinstance(items, list):
                        item = items[0]
                        file_path = item.get("file", "")
                        if file_path:
                            elapsed = time.monotonic() - start
                            seed = item.get("seed", -1)
                            logger.info(
                                "ACE-Step generation complete (%.1fs)", elapsed,
                            )
                            return file_path, seed
                    logger.error("ACE-Step completed but no audio returned: %s", result_str)
                    return None

                # Still processing
                elapsed = time.monotonic() - start
                progress_text = entry.get("progress_text", "")
                if progress_text:
                    logger.info("ACE-Step: %s (%.0fs)", progress_text, elapsed)
                else:
                    logger.info("ACE-Step generating... (%.0fs elapsed)", elapsed)

            except (URLError, OSError, json.JSONDecodeError) as exc:
                logger.warning("Poll error (retrying): %s", exc)

            time.sleep(POLL_INTERVAL)

        logger.error("ACE-Step generation timed out after %.0fs", POLL_TIMEOUT)
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

            samples, src_rate = _read_wav_bytes(wav_bytes)
            if not samples:
                logger.error("Downloaded audio is empty")
                return None

            # Resample from 48000 to 44100 if needed
            if src_rate != TARGET_SAMPLE_RATE:
                samples = _resample(samples, src_rate, TARGET_SAMPLE_RATE)

            duration = len(samples) / TARGET_SAMPLE_RATE

            logger.info(
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
            logger.error("Failed to download ACE-Step audio: %s", exc)
            return None


def _read_wav_bytes(data: bytes) -> tuple[list[float], int]:
    """Read WAV bytes into float samples (mono mixdown).

    Supports PCM int16/int32 (format 1) and IEEE float32 (format 3).
    Python's wave module doesn't handle format 3, so we parse manually.
    """
    # Parse RIFF header manually to support float32 WAV (format 3)
    if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return [], 0

    # Find fmt and data chunks
    pos = 12
    fmt_data = None
    audio_data = None
    while pos < len(data) - 8:
        chunk_id = data[pos:pos + 4]
        chunk_size = struct.unpack_from("<I", data, pos + 4)[0]
        if chunk_id == b"fmt ":
            fmt_data = data[pos + 8:pos + 8 + chunk_size]
        elif chunk_id == b"data":
            audio_data = data[pos + 8:pos + 8 + chunk_size]
            break
        pos += 8 + chunk_size
        if pos % 2 == 1:
            pos += 1  # WAV chunks are word-aligned

    if fmt_data is None or audio_data is None:
        return [], 0

    audio_format = struct.unpack_from("<H", fmt_data, 0)[0]
    n_channels = struct.unpack_from("<H", fmt_data, 2)[0]
    framerate = struct.unpack_from("<I", fmt_data, 4)[0]
    sampwidth = struct.unpack_from("<H", fmt_data, 14)[0] // 8  # bits -> bytes

    if audio_format == 3 and sampwidth == 4:
        # IEEE float32
        n_samples = len(audio_data) // 4
        float_samples = list(struct.unpack(f"<{n_samples}f", audio_data[:n_samples * 4]))
    elif audio_format == 1 and sampwidth == 2:
        # PCM int16
        n_samples = len(audio_data) // 2
        int_samples = struct.unpack(f"<{n_samples}h", audio_data[:n_samples * 2])
        float_samples = [s / 32768.0 for s in int_samples]
    elif audio_format == 1 and sampwidth == 4:
        # PCM int32
        n_samples = len(audio_data) // 4
        int_samples = struct.unpack(f"<{n_samples}i", audio_data[:n_samples * 4])
        float_samples = [s / 2147483648.0 for s in int_samples]
    else:
        return [], 0

    # Mixdown to mono if stereo
    if n_channels == 2:
        mono = []
        for i in range(0, len(float_samples), 2):
            mono.append((float_samples[i] + float_samples[i + 1]) * 0.5)
        return mono, framerate

    return float_samples, framerate


def _resample(samples: list[float], src_rate: int, dst_rate: int) -> list[float]:
    """Resample audio using linear interpolation.

    Good enough for 48000 -> 44100. For higher quality, scipy.signal.resample
    could be used, but it adds a heavy dependency import.
    """
    if src_rate == dst_rate:
        return samples

    ratio = dst_rate / src_rate
    out_len = int(len(samples) * ratio)
    result = []

    for i in range(out_len):
        src_pos = i / ratio
        idx = int(src_pos)
        frac = src_pos - idx

        if idx + 1 < len(samples):
            val = samples[idx] * (1.0 - frac) + samples[idx + 1] * frac
        elif idx < len(samples):
            val = samples[idx]
        else:
            val = 0.0
        result.append(val)

    return result
