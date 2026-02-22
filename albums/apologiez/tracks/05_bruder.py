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
        "Du weisst das, ich weiss das,\n"
        "Ich sag lieber nichts als was Falsches,\n"
        "Und dann sag ich gar nichts\n"
        "\n"
        "Wir sehen uns einmal im Jahr wenn's gut laeuft,\n"
        "Weihnachten oder dein Geburtstag,\n"
        "Und dazwischen ist Stille,\n"
        "Aber keine die wehtut, eine die reicht\n"
        "\n"
        "[chorus]\n"
        "Du bist mein Bruder,\n"
        "Nicht weil wir mussten, weil wir's sind,\n"
        "Du bist mein Bruder,\n"
        "Seit dem Pausenhof, seit wir Kinder sind,\n"
        "Und ich hab dir das nie gesagt,\n"
        "Weil Maenner sowas halt nicht sagen,\n"
        "Aber heute Nacht sagt's ne Maschine fuer mich,\n"
        "Und ich mein jedes Wort, das sie singt\n"
        "\n"
        "[verse]\n"
        "Bei dir muss ich nicht so tun als waer ich irgendwer,\n"
        "Kein Smalltalk, keine Rolle, einfach da,\n"
        "Einfach Felix, der Typ aus Erlangen,\n"
        "Der mit dir auf dem Boden sass und Bier getrunken hat\n"
        "\n"
        "Du in Berlin mit Tessa und der Kleinen,\n"
        "Und ich hier, immer noch am selben Fleck,\n"
        "Aber wenn du anrufst ist es wie frueh um neun im Schulhof,\n"
        "Als haett sich nichts veraendert, als waer keiner je weg\n"
        "\n"
        "[chorus]\n"
        "Du bist mein Bruder,\n"
        "Nicht weil wir mussten, weil wir's sind,\n"
        "Du bist mein Bruder,\n"
        "Seit dem Pausenhof, seit wir Kinder sind,\n"
        "Und ich hab dir das nie gesagt,\n"
        "Weil Maenner sowas halt nicht sagen,\n"
        "Aber heute Nacht sagt's ne Maschine fuer mich,\n"
        "Und ich mein jedes Wort, das sie singt\n"
        "\n"
        "[bridge]\n"
        "Dreissig Jahre, Tobi,\n"
        "Vom Klassenzimmer bis hierher,\n"
        "Vom E-Werk bis Berlin,\n"
        "Von Napster bis Spotify,\n"
        "Wir sind aelter geworden,\n"
        "Aber das hier ist gleich geblieben,\n"
        "Und das ist mehr als die meisten Menschen jemals haben\n"
        "\n"
        "[chorus]\n"
        "Du bist mein Bruder,\n"
        "Das ist alles was ich sagen will,\n"
        "Du bist mein Bruder,\n"
        "Und das reicht, das reicht, das reicht,\n"
        "Und wenn die Maschine aufhoert zu singen,\n"
        "Dann bleibt das hier,\n"
        "Bleibt das hier\n"
        "\n"
        "[outro]\n"
        "Ich hab dich lieb, Bruder,\n"
        "Das war's, mehr brauch ich nicht zu sagen\n"
    ),
    bpm=78,
    duration=240,
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
