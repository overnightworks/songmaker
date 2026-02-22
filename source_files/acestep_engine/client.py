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
import wave
from io import BytesIO
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
        audio_path = self._poll_result(task_id)
        if audio_path is None:
            return None

        # Download and convert audio
        return self._download_audio(audio_path, config)

    def _submit_task(self, config: AceStepConfig) -> str | None:
        """Submit a generation task to the server."""
        payload = {
            "task_type": "text2music",
            "caption": config.prompt,
            "lyrics": config.lyrics,
            "bpm": config.bpm,
            "duration": config.duration,
            "key_scale": config.key,
            "time_signature": config.time_signature,
            "vocal_language": config.vocal_language,
            "instrumental": config.instrumental,
            "seed": config.seed,
            "infer_step": config.inference_steps,
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

            task_id = result.get("task_id")
            if not task_id:
                logger.error("ACE-Step returned no task_id: %s", result)
                return None

            logger.info("ACE-Step task submitted: %s", task_id)
            return task_id

        except (URLError, OSError, json.JSONDecodeError) as exc:
            logger.error("Failed to submit ACE-Step task: %s", exc)
            return None

    def _poll_result(self, task_id: str) -> str | None:
        """Poll until the generation task completes."""
        payload = json.dumps({"task_id": task_id}).encode()
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

                status = result.get("status", "")

                if status == "completed":
                    audios = result.get("audios", [])
                    if audios:
                        path = audios[0].get("path", "")
                        seed = audios[0].get("seed", -1)
                        elapsed = time.monotonic() - start
                        logger.info(
                            "ACE-Step generation complete (%.1fs, seed=%s)",
                            elapsed, seed,
                        )
                        return path
                    logger.error("ACE-Step completed but no audio returned")
                    return None

                if status == "failed":
                    error = result.get("error", "unknown error")
                    logger.error("ACE-Step generation failed: %s", error)
                    return None

                # Still processing
                elapsed = time.monotonic() - start
                logger.info(
                    "ACE-Step generating... (%.0fs elapsed)", elapsed,
                )

            except (URLError, OSError, json.JSONDecodeError) as exc:
                logger.warning("Poll error (retrying): %s", exc)

            time.sleep(POLL_INTERVAL)

        logger.error("ACE-Step generation timed out after %.0fs", POLL_TIMEOUT)
        return None

    def _download_audio(
        self, audio_path: str, config: AceStepConfig,
    ) -> AceStepResult | None:
        """Download generated audio from the server and convert to samples."""
        try:
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

            # Extract seed from config (server may not return it in audio endpoint)
            seed = config.seed

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
    """Read WAV bytes into float samples (mono mixdown)."""
    buf = BytesIO(data)
    try:
        with wave.open(buf, "rb") as wf:
            n_channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            framerate = wf.getframerate()
            n_frames = wf.getnframes()
            raw = wf.readframes(n_frames)
    except wave.Error:
        return [], 0

    # Convert raw bytes to float samples
    if sampwidth == 2:
        fmt = f"<{n_frames * n_channels}h"
        int_samples = struct.unpack(fmt, raw)
        scale = 1.0 / 32768.0
    elif sampwidth == 4:
        fmt = f"<{n_frames * n_channels}i"
        int_samples = struct.unpack(fmt, raw)
        scale = 1.0 / 2147483648.0
    else:
        return [], 0

    float_samples = [s * scale for s in int_samples]

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
