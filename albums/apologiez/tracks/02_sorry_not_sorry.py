"""Track 02 — Sorry (Not Sorry).

R&B slow jam, Denglisch, personal apology to Tobi.
ACE-Step full-mix generation.

Run: .venv/Scripts/python albums/apologiez/tracks/02_sorry_not_sorry.py
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
OUTPUT_NAME: Final[str] = "02_sorry_not_sorry"

ACESTEP_CONFIG: Final[AceStepConfig] = AceStepConfig(
    prompt=(
        "smooth R&B slow jam, male vocal, intimate and honest, "
        "smooth piano, soft 808 bass, vinyl crackle atmosphere, "
        "Usher style, Craig David style, Justin Timberlake style, "
        "German and English mix, emotional, apologetic, warm"
    ),
    lyrics=(
        "[intro]\n"
        "Tobi... ich muss dir was sagen...\n"
        "\n"
        "[verse]\n"
        "I pressed send on your birthday,\n"
        "Forty-one candles, and a ZIP file full of pain,\n"
        "Du hast auf Play gedrückt in Berlin,\n"
        "Und ich saß in Erlangen und hab gewartet auf ein Zeichen\n"
        "\n"
        "But all I got was silence, Bruder,\n"
        "Kein Wort, kein Emoji, nichts,\n"
        "Du warst zu nett um mir zu sagen,\n"
        "Dass der Monty Python Song ein Verbrechen ist\n"
        "\n"
        "[chorus]\n"
        "I'm sorry, not sorry, that I tried,\n"
        "Sorry for the robot voice that cried,\n"
        "Sorry for the Tarkan song at night,\n"
        "But I'm not sorry that I tried to get it right\n"
        "\n"
        "I'm sorry, Tobbisch, yeah I know,\n"
        "Du bist der Musikmann, ich hab dir Müll geschickt als Show,\n"
        "But thirty years of friendship, Erlangen to Berlin,\n"
        "Deserve a better song than what that AI has been\n"
        "\n"
        "[verse]\n"
        "Du bist der Typ der auf der Bühne steht und alle rockt,\n"
        "Stefan Raab in cool, der Crowd den Atem stockt,\n"
        "Und ich? Ich schick dir WAV files um vier Uhr morgens,\n"
        "Wo ne Maschine singt als hätt sie Zahnschmerzen\n"
        "\n"
        "Du hast in der Musikbranche Karriere gemacht, kein Scherz,\n"
        "Von Spotify zu Sony, immer mittendrin im Herz,\n"
        "Und dein Schulfreund aus Erlangen denkt er kann dir Musik machen,\n"
        "Alter, ich versteh wenn du nicht wusstest ob du weinen oder lachen\n"
        "\n"
        "[chorus]\n"
        "I'm sorry, not sorry, that I tried,\n"
        "Sorry for the robot voice that cried,\n"
        "Sorry for the Tarkan song at night,\n"
        "But I'm not sorry that I tried to get it right\n"
        "\n"
        "I'm sorry, Tobbisch, yeah I know,\n"
        "Du bist der Musikmann, ich hab dir Müll geschickt als Show,\n"
        "But thirty years of friendship, Erlangen to Berlin,\n"
        "Deserve a better song than what that AI has been\n"
        "\n"
        "[bridge]\n"
        "Dreißig Jahre, Bruder,\n"
        "Von der Schulbank bis hierher,\n"
        "Du in Berlin, ich immer noch in Erlangen,\n"
        "Aber manche Dinge ändern sich nie,\n"
        "Ich werde immer versuchen dir Songs zu schicken,\n"
        "Und sie werden immer besser,\n"
        "Das hier ist der Beweis\n"
        "\n"
        "[chorus]\n"
        "I'm sorry, not sorry, that I tried,\n"
        "Sorry that the old one made you cry,\n"
        "But this time hear the difference in the sound,\n"
        "This time, Tobbisch, I won't let you down\n"
        "\n"
        "[outro]\n"
        "Happy forty-one, Bruder...\n"
        "This one's better, right?\n"
        "...right?\n"
    ),
    bpm=85,
    duration=210,
    key="Em",
    time_signature="4/4",
    vocal_language="en",
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
    print(f"  Sorry (Not Sorry) — v{version}")
    print(f"  {ACESTEP_CONFIG.bpm} BPM | E minor | {ACESTEP_CONFIG.duration}s")
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
