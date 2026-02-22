"""Download recommended SoundFont files for Songmaker.

Run once to populate the _models/soundfonts/ directory with high-quality
General MIDI SoundFont files. These are large binary files (~150-400 MB)
that are gitignored.

Usage:
    python scripts/download_soundfonts.py           # Download all recommended
    python scripts/download_soundfonts.py --list    # Show available SoundFonts
    python scripts/download_soundfonts.py fluidr3   # Download specific one

Prerequisites:
    - Internet connection
    - ~600 MB free disk space for all SoundFonts
"""

from __future__ import annotations

import shutil
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOUNDFONTS_DIR = PROJECT_ROOT / "_models" / "soundfonts"


@dataclass(frozen=True)
class SoundFontInfo:
    """Metadata for a downloadable SoundFont."""

    name: str
    filename: str
    url: str
    size_mb: int
    description: str
    sha256: str | None = None


# Verified, direct-download URLs for recommended SoundFonts.
# These are well-established community resources that have been
# available for many years.
AVAILABLE_SOUNDFONTS: dict[str, SoundFontInfo] = {
    "fluidr3": SoundFontInfo(
        name="FluidR3 GM",
        filename="FluidR3_GM.sf2",
        url="https://sourceforge.net/projects/pianobooster/files/pianobooster/1.0.0/FluidR3_GM.sf2/download",
        size_mb=141,
        description="Good general-purpose GM SoundFont. Solid all-around quality.",
    ),
    "musescore": SoundFontInfo(
        name="MuseScore General",
        filename="MuseScore_General.sf2",
        url="https://ftp.osuosl.org/pub/musescore/soundfont/MuseScore_General/MuseScore_General.sf2",
        size_mb=208,
        description="MuseScore's default SoundFont. Excellent piano and orchestral.",
    ),
}


def _download_with_progress(url: str, dest: Path, expected_mb: int) -> bool:
    """Download a file with progress display.

    Args:
        url: URL to download from.
        dest: Destination file path.
        expected_mb: Expected file size in MB (for progress display).

    Returns:
        True if download succeeded.
    """
    temp_path = dest.with_suffix(".part")

    try:
        print(f"   Downloading from: {url}")
        print(f"   Expected size: ~{expected_mb} MB")

        req = urllib.request.Request(url, headers={"User-Agent": "Songmaker/1.0"})
        response = urllib.request.urlopen(req, timeout=120)

        total_size = int(response.headers.get("Content-Length", 0))
        downloaded = 0
        chunk_size = 1024 * 1024  # 1 MB chunks

        with open(temp_path, "wb") as f:
            while True:
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                mb_done = downloaded / (1024 * 1024)
                if total_size > 0:
                    pct = (downloaded / total_size) * 100
                    total_mb = total_size / (1024 * 1024)
                    msg = f"\r   Progress: {mb_done:.1f} / {total_mb:.1f} MB ({pct:.0f}%)"
                    print(msg, end="", flush=True)
                else:
                    print(f"\r   Downloaded: {mb_done:.1f} MB", end="", flush=True)

        print()  # Newline after progress

        # Move to final location
        shutil.move(str(temp_path), str(dest))
        final_mb = dest.stat().st_size / (1024 * 1024)
        print(f"   Saved: {dest} ({final_mb:.1f} MB)")
        return True

    except Exception as exc:
        print(f"\n   Download failed: {exc}")
        temp_path.unlink(missing_ok=True)
        return False


def download_soundfont(key: str) -> bool:
    """Download a specific SoundFont by key.

    Args:
        key: SoundFont identifier (e.g., "fluidr3", "musescore").

    Returns:
        True if download succeeded or file already exists.
    """
    info = AVAILABLE_SOUNDFONTS.get(key)
    if info is None:
        print(f"Unknown SoundFont: {key!r}")
        print(f"Available: {', '.join(AVAILABLE_SOUNDFONTS.keys())}")
        return False

    dest = SOUNDFONTS_DIR / info.filename

    if dest.exists():
        mb = dest.stat().st_size / (1024 * 1024)
        print(f"   Already exists: {dest} ({mb:.1f} MB)")
        return True

    print(f"\n{'='*60}")
    print(f"Downloading: {info.name}")
    print(f"Description: {info.description}")
    print(f"{'='*60}")

    return _download_with_progress(info.url, dest, info.size_mb)


def list_soundfonts() -> None:
    """Print available SoundFonts and their status."""
    print(f"\n{'='*60}")
    print("Available SoundFonts for Songmaker")
    print(f"{'='*60}")

    for key, info in AVAILABLE_SOUNDFONTS.items():
        dest = SOUNDFONTS_DIR / info.filename
        status = "INSTALLED" if dest.exists() else "not installed"
        print(f"\n  [{key}] {info.name} (~{info.size_mb} MB) [{status}]")
        print(f"    {info.description}")
        print(f"    File: {info.filename}")

    # Check for manually installed SoundFonts
    if SOUNDFONTS_DIR.exists():
        manual = [f for f in SOUNDFONTS_DIR.glob("*.sf2")
                  if f.name not in {i.filename for i in AVAILABLE_SOUNDFONTS.values()}]
        if manual:
            print("\n  Manually installed SoundFonts:")
            for sf in manual:
                mb = sf.stat().st_size / (1024 * 1024)
                print(f"    {sf.name} ({mb:.1f} MB)")


def main() -> int:
    SOUNDFONTS_DIR.mkdir(exist_ok=True)

    args = sys.argv[1:]

    if not args:
        # Download all recommended SoundFonts
        print("Downloading recommended SoundFonts for Songmaker...")
        print(f"Target directory: {SOUNDFONTS_DIR.resolve()}\n")

        success_count = 0
        for key in AVAILABLE_SOUNDFONTS:
            if download_soundfont(key):
                success_count += 1

        print(f"\n{'='*60}")
        print(f"Done! {success_count}/{len(AVAILABLE_SOUNDFONTS)} SoundFonts installed.")
        print(f"{'='*60}")

        if success_count > 0:
            print("\nSoundFonts are automatically detected by the engine.")
            print("Use 'sf:' prefix instruments in your track scripts:")
            print("  instrument_id='sf:piano'")
            print("  instrument_id='sf:strings'")

        return 0 if success_count == len(AVAILABLE_SOUNDFONTS) else 1

    if args[0] == "--list":
        list_soundfonts()
        return 0

    # Download specific SoundFont
    key = args[0].lower()
    return 0 if download_soundfont(key) else 1


if __name__ == "__main__":
    sys.exit(main())
