"""Track 01 — Happy Birthday Tobbisch (Album Opener).

Feel-good pop/dance, Denglisch, birthday celebration.
ACE-Step full-mix generation.

Run: .venv/Scripts/python albums/apologiez/tracks/01_happy_birthday_tobbisch.py
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
OUTPUT_NAME: Final[str] = "01_happy_birthday_tobbisch"

ACESTEP_CONFIG: Final[AceStepConfig] = AceStepConfig(
    prompt=(
        "feel-good pop dance, male vocal, warm and celebratory, "
        "funky guitar, groovy bass, piano chords, claps, tight drums, "
        "Mark Ronson style, Bruno Mars style, upbeat birthday song, "
        "German and English mix, singalong chorus, happy, honest, "
        "fun energy, not cheesy, real friendship vibes"
    ),
    lyrics=(
        "[intro]\n"
        "Tobbisch!\n"
        "This one's for you, Bruder\n"
        "\n"
        "[verse]\n"
        "Du warst bei Spotify, Sony Music, the real deal,\n"
        "Und ich sitz hier mit nem GPU und frag die KI how she feels,\n"
        "Du warst DJ in den Clubs, ich war zu Hause am coden,\n"
        "Aber irgendwie sind wir connected seit dem Pausenhof-Boden\n"
        "\n"
        "Du bist der Stefan Raab unter unseren Leuten,\n"
        "Kannst singen, kannst labern, kannst die ganze Crowd begeistern,\n"
        "Und ich? Ich bau Maschinen die versuchen das zu tun,\n"
        "Was du schon konntest mit dreizehn, Alter, gönn dir Ruh!\n"
        "\n"
        "[chorus]\n"
        "Happy Birthday Tobbisch, raise your glass tonight!\n"
        "Du bist der Grund warum ich Songs schreib auch wenn keiner klingt ganz right,\n"
        "Happy Birthday Tobbisch, dieses Mal klingts gut,\n"
        "Weil die KI jetzt endlich singt als hätt sie echten Mut!\n"
        "\n"
        "[verse]\n"
        "Wir sehen uns nicht oft, aber Bruder das ist egal,\n"
        "Manche Freundschaften brauchen keinen Terminkalender, keine Wahl,\n"
        "Du rufst an, ich ruf an, manchmal Jahre dazwischen,\n"
        "Aber wenn wir reden fühlt sichs an wie gestern auf den Tischen\n"
        "\n"
        "In der Schule warst du schon der Typ der alle zum Lachen bringt,\n"
        "Der eine der aufsteht und einfach irgendwas Verrücktes singt,\n"
        "Du hast das beruflich gemacht, Sony, Spotify, die ganze Welt,\n"
        "Und ich schick dir AI-Songs, sorry dass der letzte hat gefehlt!\n"
        "\n"
        "[chorus]\n"
        "Happy Birthday Tobbisch, raise your glass tonight!\n"
        "Du bist der Grund warum ich Songs schreib auch wenn keiner klingt ganz right,\n"
        "Happy Birthday Tobbisch, dieses Mal klingts gut,\n"
        "Weil die KI jetzt endlich singt als hätt sie echten Mut!\n"
        "\n"
        "[bridge]\n"
        "Okay, real talk Tobi,\n"
        "Das letzte Album war Müll, ich weiß,\n"
        "Die Stimmen klangen wie ein Roboter der weint,\n"
        "Aber ich hab weitergemacht, für dich,\n"
        "Weil du der Einzige bist ders verdient,\n"
        "Dass jemand um vier Uhr morgens,\n"
        "Einer KI beibringt zu singen,\n"
        "Happy Birthday, du Legende!\n"
        "\n"
        "[chorus]\n"
        "Happy Birthday Tobbisch, raise your glass tonight!\n"
        "Flex0r und die Maschinen singen nur für dich heut Nacht,\n"
        "Happy Birthday Tobbisch, Freunde seit Tag eins,\n"
        "Egal wie weit, du weißt, ich meins!\n"
        "\n"
        "[outro]\n"
        "Happy Birthday, Bruder\n"
        "Happy Birthday, Tobbisch\n"
        "GG WP\n"
    ),
    bpm=116,
    duration=240,
    key="G",
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
    print(f"  Happy Birthday Tobbisch — v{version}")
    print(f"  {ACESTEP_CONFIG.bpm} BPM | G major | {ACESTEP_CONFIG.duration}s")
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
