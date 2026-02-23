"""BONUS Track — Fire in the Hole (Counter-Strike Anthem).

Boom-bap hip-hop, Denglisch, Power Terminators LAN party.
ACE-Step full-mix generation.

Run: .venv/Scripts/python albums/apologiez/tracks/bonus_fire_in_the_hole.py
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
OUTPUT_NAME: Final[str] = "bonus_fire_in_the_hole"

ACESTEP_CONFIG: Final[AceStepConfig] = AceStepConfig(
    prompt=(
        "aggressive boom-bap hip-hop, male rapper, raw energetic delivery, "
        "dusty vinyl drums, heavy kick, tight snare, jazzy piano loop, "
        "deep sub bass, 90s hip-hop style, Mobb Deep style, Wu-Tang style, "
        "German rap, gaming anthem, hype, hard, singalong chorus, "
        "dark atmosphere, LAN party energy"
    ),
    lyrics=(
        "[intro]\n"
        "Power Terminators connected,\n"
        "Server Dark Terrorists,\n"
        "Map de_aztec, alle da, let's go!\n"
        "\n"
        "[verse]\n"
        "Runde eins, CT Spawn, AWP schon in der Hand,\n"
        "Flexx0r scoped die Brücke, Fadenkreuz am Rand,\n"
        "Noob Saibot gibt die Ansage, links halten, rechts ist frei,\n"
        "Kill O Zap zieht die Deagle, Headshot, eins, zwei, drei!\n"
        "\n"
        "Tobbisch rennt mit AK rein, FIRE IN THE HOLE!\n"
        "Spray Control, vier Kills, der Typ hat keine Kontrolle?\n"
        "Doch! Ace! Der ganze Raum schreit, Monitor wackelt,\n"
        "Was war das, Wichser?! Nächste Runde, weiter geballert!\n"
        "\n"
        "[chorus]\n"
        "Fire in the Hole! Power Terminators kommen rein,\n"
        "Dark Terrorists Server, cs_militia, de_aztec, alles mein!\n"
        "Fire in the Hole! AWP, AK, Deagle am Start,\n"
        "Frag um Frag um Frag, Power Terminators, hart!\n"
        "MONSTER KILL!\n"
        "\n"
        "[verse]\n"
        "Vier Uhr morgens, Bildschirm brennt, Augen komplett rot,\n"
        "Pizza aufm Boden, Schlaf ist tot, Red Bull auch schon tot,\n"
        "Du Spasst, kauf Kevlar! Halts Maul, ich spar auf AWP!\n"
        "Nächste Runde Eco, trotzdem Clutch, hört die Welt noch?\n"
        "\n"
        "Clan War läuft, plötzlich, Wallhack! Scheiß Cheater!\n"
        "Der Typ sieht durch die Wand, Autoaim, was ein Biter!\n"
        "Vote kick! Der hat Aimbot, Alter, meld den Wichser!\n"
        "Scheiß drauf, nächste Runde, wir sind trotzdem krasser!\n"
        "\n"
        "Noob Saibot ruft den Strat, Alle B, jetzt pushen!\n"
        "Kill O Zap, Deagle ready, Headshot durch die Büsche,\n"
        "Tobbisch sprüht die AK leer, der Smoke verzieht sich,\n"
        "Flexx0r wartet hinten, Scope, Zoom, Kopf, erledigt, sicher!\n"
        "\n"
        "[chorus]\n"
        "Fire in the Hole! Power Terminators kommen rein,\n"
        "Dark Terrorists Server, cs_militia, de_aztec, alles mein!\n"
        "Fire in the Hole! AWP, AK, Deagle am Start,\n"
        "Frag um Frag um Frag, Power Terminators, hart!\n"
        "MONSTER KILL!\n"
        "\n"
        "[bridge]\n"
        "Die Server sind jetzt offline,\n"
        "Kein Ping, kein Frag, kein Sound,\n"
        "Doch mach ich die Augen zu,\n"
        "Hör ich Fire in the Hole, eine letzte Runde\n"
        "\n"
        "[chorus]\n"
        "FIRE IN THE HOLE! Power Terminators kommen rein!\n"
        "Dark Terrorists Server, Spaßten, de_aztec ist mein!\n"
        "Noob Saibot! Kill O Zap! Tobbisch! Flexx0r!\n"
        "HEADSHOT! HEADSHOT! HEADSHOT! GAME OVER!\n"
        "MONSTER KILL!\n"
        "\n"
        "[outro]\n"
        "Server disconnected,\n"
        "GG WP\n"
    ),
    bpm=90,
    duration=210,
    key="Am",
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
    print(f"  Fire in the Hole — BONUS — v{version}")
    print(f"  {ACESTEP_CONFIG.bpm} BPM | A minor | {ACESTEP_CONFIG.duration}s")
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
