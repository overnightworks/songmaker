"""Track 05 — Bruder (Album Closer).

Emotional pop ballad, German, intimate and honest.
ACE-Step full-mix generation.

Run: .venv/Scripts/python albums/apologiez/tracks/05_bruder.py
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Final

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

from acestep_engine import AceStepClient, AceStepConfig, is_acestep_available
from bark_engine.audio_io import master_to_mp3, normalize_audio, write_wav_file

OUTPUT_DIR: Final[Path] = Path("_output/apologiez")
OUTPUT_NAME: Final[str] = "05_bruder"

ACESTEP_CONFIG: Final[AceStepConfig] = AceStepConfig(
    prompt=(
        "emotional acoustic pop ballad, male vocal, intimate and vulnerable, "
        "simple piano, gentle acoustic guitar, soft strings, warm and honest, "
        "Ed Sheeran style, Clueso style, German singer songwriter, "
        "slow build to emotional climax, heartfelt, raw, like a voicemail at 2am"
    ),
    lyrics=(
        "[verse]\n"
        "Ich bin nicht gut in sowas,\n"
        "Du weißt das, ich weiß das,\n"
        "Ich sag lieber nichts,\n"
        "Und dann sag ich gar nichts\n"
        "\n"
        "[chorus]\n"
        "Du bist mein Bruder,\n"
        "Weil wir's sind,\n"
        "Du bist mein Bruder,\n"
        "Seit wir Kinder sind,\n"
        "Heute sagt's ne Maschine,\n"
        "Und ich mein jedes Wort\n"
        "\n"
        "[verse]\n"
        "Bei dir bin ich einfach da,\n"
        "Einfach Felix aus Erlangen,\n"
        "Du in Berlin, ich hier,\n"
        "Aber wenn du anrufst,\n"
        "Ist es wie im Schulhof\n"
        "\n"
        "[bridge]\n"
        "Dreißig Jahre, Tobi,\n"
        "Wir sind älter geworden,\n"
        "Aber das hier ist gleich geblieben\n"
        "\n"
        "[chorus]\n"
        "Du bist mein Bruder,\n"
        "Das reicht, das reicht,\n"
        "Die Maschine hört auf,\n"
        "Aber das hier bleibt\n"
        "\n"
        "[outro]\n"
        "Ich hab dich lieb, Bruder\n"
    ),
    bpm=78,
    duration=210,
    key="C",
    time_signature="4/4",
    vocal_language="de",
    seed=-1,
)


def next_version(output_dir: Path, base_name: str) -> int:
    """Find the next version number for a track (v1, v2, ...)."""
    existing = list(output_dir.glob(f"{base_name}_v*.mp3"))
    if not existing:
        return 1
    versions = []
    for p in existing:
        part = p.stem.replace(base_name + "_v", "")
        if part.isdigit():
            versions.append(int(part))
    return max(versions, default=0) + 1


def main() -> None:
    start_time = time.time()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    version = next_version(OUTPUT_DIR, OUTPUT_NAME)
    versioned = f"{OUTPUT_NAME}_v{version}"

    print("=" * 60)
    print(f"  Bruder — Album Closer — v{version}")
    print(f"  {ACESTEP_CONFIG.bpm} BPM | C major | {ACESTEP_CONFIG.duration}s")
    print("=" * 60)

    if not is_acestep_available():
        print("  ERROR: ACE-Step server not running!")
        print("  Start it with: python scripts/start_acestep.py")
        return

    print("\n  Generating via ACE-Step...")
    client = AceStepClient()
    result = client.generate(ACESTEP_CONFIG)
    if result is None:
        print("  ERROR: Generation failed!")
        return

    raw_wav = str(OUTPUT_DIR / f"{versioned}_raw.wav")
    write_wav_file(raw_wav, result.samples)

    samples = normalize_audio(result.samples, 0.95)
    wav_path = str(OUTPUT_DIR / f"{versioned}.wav")
    write_wav_file(wav_path, samples)

    mp3_path = str(OUTPUT_DIR / f"{versioned}.mp3")
    master_to_mp3(wav_path, mp3_path)

    elapsed = time.time() - start_time
    print(f"\n{'=' * 60}")
    print(f"  Done: {mp3_path}")
    print(f"  Time: {elapsed:.0f}s | Duration: {result.duration:.1f}s | Seed: {result.seed}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
