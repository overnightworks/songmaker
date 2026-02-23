"""Track 04 — Die KI singt für dich.

Pop-punk comedy, Denglisch, meta song about AI music.
ACE-Step full-mix generation.

Run: .venv/Scripts/python albums/apologiez/tracks/04_die_ki_singt.py
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
OUTPUT_NAME: Final[str] = "04_die_ki_singt"

ACESTEP_CONFIG: Final[AceStepConfig] = AceStepConfig(
    prompt=(
        "upbeat pop-punk anthem, male vocal, fun and energetic, "
        "fast electric guitar, driving drums, punchy bass, claps, "
        "Blink-182 style, Die Aerzte style, comedy rock, "
        "German and English mix, self-deprecating humor, singalong chorus, "
        "fast tempo, happy, proud, celebratory"
    ),
    lyrics=(
        "[intro]\n"
        "Eins, zwei, drei, vier!\n"
        "\n"
        "[verse]\n"
        "Ich kann nicht singen, das ist Fakt,\n"
        "Meine Stimme klingt wie'n Staubsauger der rappt,\n"
        "Ich kann kein Klavier, keine Gitarre, keinen Bass,\n"
        "Aber ich kann coden, Bruder, und das reicht für Spass!\n"
        "\n"
        "Vier Uhr morgens, Bildschirm leuchtet blau,\n"
        "Prompt rein, Beat raus, ich weiß genau,\n"
        "Mein Nachbar klopft und fragt ob alles klar,\n"
        "Ich sag ja, Alter, ich mach grad ein Album, ist doch wunderbar!\n"
        "\n"
        "[chorus]\n"
        "Die KI singt für dich,\n"
        "Weil ich es selber nicht kann,\n"
        "Die KI singt für dich,\n"
        "Und sie gibt alles was sie hat, Mann!\n"
        "Ich hab keine Stimme, ich hab keinen Plan,\n"
        "Aber ich hab ne Maschine die für mich singen kann,\n"
        "Die KI singt für dich,\n"
        "Und ich mein jedes Wort!\n"
        "\n"
        "[verse]\n"
        "Version eins war Bark, oh Gott, was für ein Graus,\n"
        "Die Stimme klang als würd ein Roboter kotzen im Haus,\n"
        "Ich hab dir trotzdem zehn Songs geschickt, zum Geburtstag, wie nett,\n"
        "Und du hast geschwiegen, Bruder, und ich lag wach im Bett!\n"
        "\n"
        "Dann kam ACE-Step, neues Modell, neuer Sound,\n"
        "Plötzlich klingt es fast nach Musik, ich dreh mich im Kreis, ich bin Hound,\n"
        "Zehn Stunden rendern für drei Minuten Song,\n"
        "Meine GPU glüht, aber Tobi, es hat sich gelohnt!\n"
        "\n"
        "[chorus]\n"
        "Die KI singt für dich,\n"
        "Weil ich es selber nicht kann,\n"
        "Die KI singt für dich,\n"
        "Und sie gibt alles was sie hat, Mann!\n"
        "Ich hab keine Stimme, ich hab keinen Plan,\n"
        "Aber ich hab ne Maschine die für mich singen kann,\n"
        "Die KI singt für dich,\n"
        "Und ich mein jedes Wort!\n"
        "\n"
        "[bridge]\n"
        "Und ja, du bist der Musikmann,\n"
        "Du hörst sofort wenn irgendwas nicht stimmen kann,\n"
        "Und ja, das hier ist künstlich, fake, aus Nullen und aus Einsen,\n"
        "Aber die Gefühle dahinter, Bruder, die sind meins!\n"
        "\n"
        "[chorus]\n"
        "Die KI singt für dich,\n"
        "Weil ich es selber nicht kann,\n"
        "Die KI singt für dich,\n"
        "Und sie wird besser, Song für Song, das ist der Plan!\n"
        "Ich hab keine Stimme, aber ich hab nen Freund,\n"
        "Der das hier hört und vielleicht, vielleicht, ein bisschen weint,\n"
        "Die KI singt für dich,\n"
        "Tobi, das hier ist für dich!\n"
        "\n"
        "[outro]\n"
        "Die KI singt für dich...\n"
        "Und naechstes Jahr wird sie noch besser, versprochen!\n"
    ),
    bpm=140,
    duration=200,
    key="A",
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
    print(f"  Die KI singt für dich — v{version}")
    print(f"  {ACESTEP_CONFIG.bpm} BPM | A major | {ACESTEP_CONFIG.duration}s")
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
