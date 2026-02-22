"""Track 03 — Rap Battle Part 2 (Flex0r vs MC Tobbisch).

Hip-hop battle rap, Eminem 8 Mile style, Denglisch.
ACE-Step full-mix generation.

Run: .venv/Scripts/python albums/apologiez/tracks/03_rap_battle_part_2.py
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
OUTPUT_NAME: Final[str] = "03_rap_battle_part_2"

ACESTEP_CONFIG: Final[AceStepConfig] = AceStepConfig(
    prompt=(
        "aggressive hip-hop battle rap, male rapper, raw aggressive delivery, "
        "boom bap drums, heavy 808 bass, dark piano loop, crowd hype sounds, "
        "Eminem 8 Mile style rap battle, two rappers trading verses, "
        "German and English mix, energetic, confrontational, funny"
    ),
    lyrics=(
        "[intro]\n"
        "Ladies and Gentlemen!\n"
        "Rap Battle Part Two!\n"
        "Flex0r versus MC Tobbisch!\n"
        "Last time was trash, this time we mean it!\n"
        "\n"
        "[verse]\n"
        "Yo Tobbisch, Part eins war peinlich, ich gebs zu,\n"
        "Die KI hat gerappt wie ne Waschmaschine im Schuh,\n"
        "Aber jetzt bin ich upgraded, neues Modell, neuer Sound,\n"
        "Und du bist immer noch der Typ der in der Schule rumgeclownt!\n"
        "\n"
        "Du hast mich von der Seite gepiekst im Unterricht,\n"
        "Ich dreh mich um und hau dich, Frau Loschert sieht nur mich!\n"
        "Sie hat mich ermahnt und du sitzt da und lachst,\n"
        "Immer ich der Dumme, weil du den Scheiss angefangen hast!\n"
        "\n"
        "[verse]\n"
        "Flex0r, mein Assistent, du hast Kabel sortiert,\n"
        "Im E-Werk Back to School, ich hab aufgelegt, du hast kassiert,\n"
        "Ich stand am Pult, du standst daneben mit nem Bier,\n"
        "Und jetzt machst du AI Musik? Bruder, lass das lieber mir!\n"
        "\n"
        "Du warst der Sportler und der Gamer, ich der Kuenstler hier,\n"
        "Jedes Jahr am Berg die gleiche Jeansjacke, Alter, seriously?\n"
        "Ich hoer ein Lied einmal und sing es, du hast keinen Plan,\n"
        "Und jetzt schickst du mir AI Songs von nem Typ der nicht mal singen kann!\n"
        "\n"
        "[verse]\n"
        "Okay okay, du bist der Musiktyp, ich der Gamer mit GPU,\n"
        "Mein Bruder hatte Internet, wir haben Napster durchgezogen, du und ich,\n"
        "Tausend Songs gesaugt, die ganze Nacht am Stueck,\n"
        "Und jetzt willst du sagen ICH versteh nichts von Musik?\n"
        "\n"
        "Du hast aufgelegt, ich hab die Technik aufgebaut,\n"
        "Du hast die Crowd gerockt, ich hab auf dein Equipment geschaut,\n"
        "Ohne mich waerst du im E-Werk aufgeschmissen, check das Bild,\n"
        "Der DJ ist nur so gut wie sein Roadie, und das gilt!\n"
        "\n"
        "[verse]\n"
        "Flex0r, du sitzt in Erlangen, kommst nicht raus aus der Stadt,\n"
        "Alle reisen um die Welt und du sitzt da wo du immer schon sassst,\n"
        "Erst Poker, dann Gaming, fast gut aber nie genug,\n"
        "Und jetzt AI Musik, Bruder, wann lernst du, wann ist Schluss?\n"
        "\n"
        "Ich hab Tessa, Charlotte, Berlin, mein Leben ist komplett,\n"
        "Und du hast GPUs und Kaffee um vier Uhr im Bett,\n"
        "Aber egal wie schlecht die Songs sind, egal wie schief der Ton,\n"
        "Du bist mein Bruder seit der Schulbank, das reicht als Grund, Champion!\n"
        "\n"
        "[verse]\n"
        "Du sagst ich sitz in Erlangen, ja stimmt, ich geb's zu,\n"
        "Aber wenigstens kenn ich hier jeden, und jeder kennt mich, Bruh,\n"
        "Du bist nach Berlin gezogen, grosser Mann in der Stadt,\n"
        "Aber rufst mich trotzdem an wenn du Heimweh hast!\n"
        "\n"
        "Und ja, meine Songs sind KI, meine Stimme ist fake,\n"
        "Aber wenigstens versuch ich was, ich mach was, ich schaff,\n"
        "Du singst im Wohnzimmer Karaoke fuer Tessa allein,\n"
        "Und ich stream meine Kunst in die Welt, Alter, das ist fein!\n"
        "\n"
        "[verse]\n"
        "Streamen, Alter, bitte, wer hoert sich den Scheiss an?\n"
        "Deine Mutter und ich, und deine Mutter nur aus Mitleid, Mann,\n"
        "Du hast dreissig Jahre gebraucht fuer dein erstes Album hier,\n"
        "Und es klingt wie AutoTune auf nem kaputten Klavier!\n"
        "\n"
        "Aber weisst du was, Flex0r, ich sag dir jetzt was Echtes,\n"
        "Kein Diss, kein Joke, jetzt mal was Gerechtes,\n"
        "Von all den Leuten die ich kenn, Berlin bis Erlangen,\n"
        "Bist du der Einzige der nie aufhoert anzufangen!\n"
        "\n"
        "[outro]\n"
        "Unentschieden!\n"
        "Wie immer!\n"
        "Flex0r und MC Tobbisch!\n"
        "Part drei kommt wenn die KI Gefuehle hat!\n"
    ),
    bpm=95,
    duration=210,
    key="Dm",
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
    print(f"  Rap Battle Part 2 — Flex0r vs MC Tobbisch — v{version}")
    print(f"  {ACESTEP_CONFIG.bpm} BPM | D minor | {ACESTEP_CONFIG.duration}s")
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
