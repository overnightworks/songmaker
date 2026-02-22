"""Setup script for DiffSinger singing voice synthesis.

Clones the DiffSinger repo, installs dependencies, and downloads
the TIGER English voicebank + vocoder models.

Usage:
    .venv/Scripts/python scripts/setup_diffsinger.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from urllib.request import urlretrieve

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIFFSINGER_DIR = PROJECT_ROOT / "_diffsinger"
CHECKPOINTS_DIR = DIFFSINGER_DIR / "checkpoints"

# TIGER voicebank v106 (CC BY-NC-ND 4.0)
TIGER_URL = "https://github.com/spicytigermeat/tiger_diffsinger/releases/download/v106/TIGER_DS_v106_PACK.zip"
TIGER_ZIP = "TIGER_DS_v106_PACK.zip"

# Vocoder — TIGER's custom HiFiGAN
# (Already included in the TIGER pack under dsvocoder/)


def run(cmd: list[str], **kwargs):
    """Run a command and print it."""
    print(f"$ {' '.join(str(c) for c in cmd)}")
    subprocess.check_call(cmd, **kwargs)


def clone_diffsinger():
    """Clone openvpi/DiffSinger repo (for reference/utils only)."""
    if (DIFFSINGER_DIR / "README.md").exists():
        print("DiffSinger repo already cloned.")
        return

    print("Cloning DiffSinger repository...")
    run(["git", "clone", "--depth", "1",
         "https://github.com/openvpi/DiffSinger.git",
         str(DIFFSINGER_DIR)])


def install_dependencies():
    """Install DiffSinger and engine dependencies into the main venv."""
    print("\nInstalling dependencies...")
    pip = [sys.executable, "-m", "pip", "install"]

    # g2p_en for English phonemization
    run(pip + ["g2p_en"])

    # ONNX Runtime for inference
    run(pip + ["onnxruntime-gpu"])

    # NLTK data for g2p_en
    print("Downloading NLTK data...")
    subprocess.check_call([
        sys.executable, "-c",
        "import nltk; nltk.download('averaged_perceptron_tagger_eng'); nltk.download('cmudict')"
    ])


def _download_with_progress(url: str, dest: Path):
    """Download a file with progress reporting."""
    def reporthook(count, block_size, total_size):
        pct = count * block_size * 100 / total_size if total_size > 0 else 0
        print(f"\r  {pct:.0f}% ({count * block_size / 1024 / 1024:.0f} MB)", end="", flush=True)

    print(f"  Downloading {url}")
    urlretrieve(url, str(dest), reporthook=reporthook)
    print()


def download_tiger():
    """Download and extract the TIGER English voicebank."""
    tiger_voice_dir = CHECKPOINTS_DIR / "tiger_voice"
    if tiger_voice_dir.exists() and (tiger_voice_dir / "dsconfig.yaml").exists():
        print("TIGER voicebank already installed.")
        return

    CHECKPOINTS_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = CHECKPOINTS_DIR / TIGER_ZIP

    if not zip_path.exists():
        print("\nDownloading TIGER v106 voicebank (~530 MB)...")
        _download_with_progress(TIGER_URL, zip_path)

    print("Extracting TIGER pack...")
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(CHECKPOINTS_DIR / "tiger_pack_tmp")

    # The pack contains a nested zip: Voice Library/TIGER_DS_v106.zip
    inner_zip = CHECKPOINTS_DIR / "tiger_pack_tmp" / "TIGER_DS_v106_PACK" / "Voice Library" / "TIGER_DS_v106.zip"
    if inner_zip.exists():
        print("Extracting inner voice library...")
        with zipfile.ZipFile(inner_zip) as zf:
            zf.extractall(tiger_voice_dir)
    else:
        raise FileNotFoundError(f"Inner voice zip not found: {inner_zip}")

    # Cleanup
    shutil.rmtree(CHECKPOINTS_DIR / "tiger_pack_tmp", ignore_errors=True)
    zip_path.unlink(missing_ok=True)

    print(f"TIGER voicebank installed to: {tiger_voice_dir}")


def verify():
    """Verify the installation."""
    print("\nVerifying installation...")

    tiger_dir = CHECKPOINTS_DIR / "tiger_voice"
    acoustic = tiger_dir / "dsacoustic" / "acoustic.onnx"
    vocoder = tiger_dir / "dsvocoder" / "tgm_hifigan.onnx"
    dsconfig = tiger_dir / "dsconfig.yaml"

    errors = []
    for path, name in [
        (dsconfig, "TIGER dsconfig.yaml"),
        (acoustic, "Acoustic model"),
        (vocoder, "Vocoder model"),
    ]:
        if path.exists():
            print(f"  OK: {name} ({path.stat().st_size / 1024 / 1024:.0f} MB)")
        else:
            errors.append(f"  MISSING: {name} — {path}")

    # Test import
    try:
        sys.path.insert(0, str(PROJECT_ROOT / "source_files"))
        from diffsinger_engine import DiffSingerEngine
        engine = DiffSingerEngine(voicebank_dir=str(tiger_dir), device="cpu")
        print(f"  OK: Engine initialized, {len(engine.config.phoneme_map)} phonemes")
        print(f"  OK: {len(engine.speaker_embeds)} speaker embeddings loaded")
    except Exception as e:
        errors.append(f"  ERROR: Engine init failed: {e}")

    if errors:
        print("\nErrors found:")
        for err in errors:
            print(err)
        return False

    print("\nDiffSinger setup complete!")
    return True


def main():
    print("=" * 60)
    print("DiffSinger Setup for Songmaker")
    print("=" * 60)

    clone_diffsinger()
    install_dependencies()
    download_tiger()

    if verify():
        print("\nReady to generate singing vocals!")
        print("Usage: from diffsinger_engine import DiffSingerEngine, VocalNote, VocalPhrase")
    else:
        print("\nSetup completed with errors. Please check above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
