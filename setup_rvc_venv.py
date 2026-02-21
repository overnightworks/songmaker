"""Set up an isolated Python 3.12 virtual environment for RVC.

RVC requires Python 3.10-3.12 and specific dependency versions
(faiss-cpu, numpy, etc.) that conflict with Python 3.14. This
script creates a separate venv with everything RVC needs.

Run this script once from an admin terminal:
    python setup_rvc_venv.py

Prerequisites:
    - Python 3.12 must be installed (py -3.12 must work)
    - Internet connection for pip downloads
    - Visual C++ Build Tools for pyworld compilation
      (or use --no-pyworld flag to skip)
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

VENV_DIR = Path("_rvc_venv")
REQUIRED_PYTHON = "3.12"


def find_python312() -> str | None:
    """Find Python 3.12 on the system."""
    candidates = [
        f"py -{REQUIRED_PYTHON}",
        "python3.12",
        "python3",
    ]

    for cmd in candidates:
        try:
            result = subprocess.run(
                cmd.split() + ["--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 and "3.12" in result.stdout:
                return cmd
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue

    # Check common install paths on Windows
    common_paths = [
        Path("C:/Python312/python.exe"),
        Path("C:/Program Files/Python312/python.exe"),
        Path.home() / "AppData/Local/Programs/Python/Python312/python.exe",
    ]
    for p in common_paths:
        if p.exists():
            return str(p)

    return None


def main() -> int:
    print("=" * 60)
    print("RVC Virtual Environment Setup")
    print("=" * 60)

    # Find Python 3.12
    python_cmd = find_python312()
    if python_cmd is None:
        print(
            f"\n❌ Python {REQUIRED_PYTHON} not found.\n"
            f"Install it from https://www.python.org/downloads/\n"
            f"Make sure to check 'Add Python to PATH' during install.\n"
            f"After installing, run this script again."
        )
        return 1

    print(f"\n✅ Found Python: {python_cmd}")

    # Create venv
    if VENV_DIR.exists():
        print(f"\n⚠️  Venv already exists at {VENV_DIR}/")
        response = input("Delete and recreate? [y/N]: ").strip().lower()
        if response != "y":
            print("Aborted.")
            return 0
        import shutil
        shutil.rmtree(VENV_DIR)

    print(f"\n🔧 Creating venv at {VENV_DIR}/...")
    subprocess.run(
        python_cmd.split() + ["-m", "venv", str(VENV_DIR)],
        check=True,
    )

    # Get venv Python path
    if sys.platform == "win32":
        venv_python = str(VENV_DIR / "Scripts" / "python.exe")
    else:
        venv_python = str(VENV_DIR / "bin" / "python")

    print(f"✅ Venv created: {venv_python}")

    # Upgrade pip
    print("\n📦 Upgrading pip...")
    subprocess.run(
        [venv_python, "-m", "pip", "install", "--upgrade", "pip"],
        check=True,
        capture_output=True,
    )

    # Install PyTorch with CUDA
    print("\n📦 Installing PyTorch with CUDA...")
    subprocess.run(
        [
            venv_python, "-m", "pip", "install",
            "torch", "torchaudio",
            "--index-url", "https://download.pytorch.org/whl/cu121",
        ],
        check=True,
    )

    # Install rvc-python and dependencies
    print("\n📦 Installing rvc-python...")
    subprocess.run(
        [venv_python, "-m", "pip", "install", "rvc-python"],
        check=True,
    )

    # Verify installation
    print("\n🔍 Verifying installation...")
    result = subprocess.run(
        [venv_python, "-c", "from rvc_python.infer import RVCInference; print('OK')"],
        capture_output=True,
        text=True,
    )

    if result.returncode == 0 and "OK" in result.stdout:
        print("✅ RVC installed successfully!")
    else:
        print(f"❌ Verification failed: {result.stderr}")
        return 1

    # Check CUDA
    result = subprocess.run(
        [venv_python, "-c", "import torch; print('CUDA' if torch.cuda.is_available() else 'CPU')"],
        capture_output=True,
        text=True,
    )
    device = result.stdout.strip()
    print(f"✅ Device: {device}")

    # Create models directory
    models_dir = Path("rvc_models")
    models_dir.mkdir(exist_ok=True)
    print(f"\n✅ Models directory: {models_dir}/")

    print("\n" + "=" * 60)
    print("Setup complete!")
    print("=" * 60)
    print(f"\nNext steps:")
    print(f"  1. Download an RVC voice model (.pth + .index files)")
    print(f"     from https://voice-models.com or https://weights.com")
    print(f"  2. Place the files in {models_dir}/")
    print(f"  3. Set rvc_model='model_name' in your VocalSection config")
    print(f"\nThe main engine will auto-detect the RVC venv at {VENV_DIR}/")

    return 0


if __name__ == "__main__":
    sys.exit(main())
