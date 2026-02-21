"""Set up an isolated Python 3.12 virtual environment for AI backends.

Multiple AI packages (RVC, XTTS, MusicGen, Demucs) require Python 3.10-3.12
and specific dependency versions that conflict with Python 3.14. This script
creates a shared venv with all backends installed.

Usage:
    python setup_rvc_venv.py              # Install all available backends
    python setup_rvc_venv.py --rvc        # Install RVC only
    python setup_rvc_venv.py --xtts       # Install XTTS only
    python setup_rvc_venv.py --musicgen   # Install MusicGen only
    python setup_rvc_venv.py --demucs     # Install Demucs only
    python setup_rvc_venv.py --list       # Show what's installed

Prerequisites:
    - Python 3.12 must be installed (py -3.12 must work)
    - Internet connection for pip downloads
    - GPU: CUDA-capable GPU recommended (auto-detected)
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

VENV_DIR = Path(".venv")
REQUIRED_PYTHON = "3.12"


@dataclass
class Backend:
    """Backend package definition."""

    name: str
    pip_packages: list[str]
    verify_import: str
    description: str


BACKENDS: dict[str, Backend] = {
    "rvc": Backend(
        name="RVC Voice Conversion",
        pip_packages=["rvc-python"],
        verify_import="from rvc_python.infer import RVCInference; print('ok')",
        description="Convert vocals through trained voice models",
    ),
    "xtts": Backend(
        name="XTTS v2 Text-to-Speech",
        pip_packages=["coqui-tts"],
        verify_import="from TTS.api import TTS; print('ok')",
        description="High-quality speech synthesis with voice cloning",
    ),
    "musicgen": Backend(
        name="MusicGen AI Instrumentals",
        pip_packages=["audiocraft"],
        verify_import="from audiocraft.models import MusicGen; print('ok')",
        description="Generate instrumentals from text descriptions",
    ),
    "demucs": Backend(
        name="Demucs Stem Separation",
        pip_packages=["demucs"],
        verify_import="from demucs.pretrained import get_model; print('ok')",
        description="Split audio into vocals/drums/bass/other stems",
    ),
}


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


def get_venv_python() -> str:
    """Get the Python executable path for the venv."""
    if sys.platform == "win32":
        return str(VENV_DIR / "Scripts" / "python.exe")
    return str(VENV_DIR / "bin" / "python")


def create_venv(python_cmd: str) -> bool:
    """Create the virtual environment if it doesn't exist."""
    if VENV_DIR.exists():
        venv_python = get_venv_python()
        if Path(venv_python).exists():
            print(f"\nVenv already exists at {VENV_DIR}/")
            return True

    print(f"\nCreating venv at {VENV_DIR}/...")
    subprocess.run(
        python_cmd.split() + ["-m", "venv", str(VENV_DIR)],
        check=True,
    )

    venv_python = get_venv_python()
    print(f"Venv created: {venv_python}")

    # Upgrade pip
    print("\nUpgrading pip...")
    subprocess.run(
        [venv_python, "-m", "pip", "install", "--upgrade", "pip"],
        check=True,
        capture_output=True,
    )

    # Install PyTorch with CUDA
    print("\nInstalling PyTorch with CUDA...")
    subprocess.run(
        [
            venv_python, "-m", "pip", "install",
            "torch", "torchaudio",
            "--index-url", "https://download.pytorch.org/whl/cu121",
        ],
        check=True,
    )

    return True


def install_backend(backend_key: str) -> bool:
    """Install a specific backend into the venv.

    Args:
        backend_key: Backend identifier (rvc, xtts, musicgen, demucs).

    Returns:
        True if installation succeeded.
    """
    backend = BACKENDS[backend_key]
    venv_python = get_venv_python()

    print(f"\nInstalling {backend.name}...")
    for pkg in backend.pip_packages:
        print(f"  pip install {pkg}")
        result = subprocess.run(
            [venv_python, "-m", "pip", "install", pkg],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"  Failed to install {pkg}:")
            # Show last few lines of stderr for diagnosis
            lines = result.stderr.strip().split("\n")
            for line in lines[-5:]:
                print(f"    {line}")
            return False

    # Verify
    print(f"  Verifying {backend.name}...")
    result = subprocess.run(
        [venv_python, "-c", backend.verify_import],
        capture_output=True,
        text=True,
        timeout=60,
    )

    if result.returncode == 0 and "ok" in result.stdout:
        print(f"  {backend.name} installed successfully!")
        return True
    else:
        print(f"  Verification failed: {result.stderr[:200]}")
        return False


def check_installed() -> dict[str, bool]:
    """Check which backends are installed in the venv."""
    venv_python = get_venv_python()
    if not Path(venv_python).exists():
        return {k: False for k in BACKENDS}

    status = {}
    for key, backend in BACKENDS.items():
        try:
            result = subprocess.run(
                [venv_python, "-c", backend.verify_import],
                capture_output=True,
                text=True,
                timeout=30,
            )
            status[key] = result.returncode == 0 and "ok" in result.stdout
        except (subprocess.TimeoutExpired, FileNotFoundError):
            status[key] = False

    return status


def list_status() -> None:
    """Print the installation status of all backends."""
    print(f"\n{'='*60}")
    print("Songmaker AI Backend Status")
    print(f"{'='*60}")

    venv_python = get_venv_python()
    venv_exists = Path(venv_python).exists()

    print(f"\nVenv: {VENV_DIR}/ {'(exists)' if venv_exists else '(not created)'}")

    if venv_exists:
        # Check CUDA
        try:
            result = subprocess.run(
                [venv_python, "-c",
                 "import torch; print(f'CUDA {torch.cuda.get_device_name(0)}' "
                 "if torch.cuda.is_available() else 'CPU only')"],
                capture_output=True, text=True, timeout=15,
            )
            print(f"Device: {result.stdout.strip()}")
        except Exception:
            pass

    status = check_installed()

    print()
    for key, backend in BACKENDS.items():
        installed = status.get(key, False)
        mark = "INSTALLED" if installed else "not installed"
        print(f"  [{key:10}] {backend.name:35} [{mark}]")
        print(f"              {backend.description}")

    not_installed = [k for k, v in status.items() if not v]
    if not_installed:
        print(f"\nTo install missing backends:")
        for key in not_installed:
            print(f"  python setup_rvc_venv.py --{key}")
        print(f"  python setup_rvc_venv.py           # (install all)")


def main() -> int:
    print("=" * 60)
    print("Songmaker AI Backend Setup")
    print("=" * 60)

    args = sys.argv[1:]

    # List mode
    if "--list" in args:
        list_status()
        return 0

    # Find Python 3.12
    python_cmd = find_python312()
    if python_cmd is None:
        print(
            f"\nPython {REQUIRED_PYTHON} not found.\n"
            f"Install it from https://www.python.org/downloads/\n"
            f"Make sure to check 'Add Python to PATH' during install.\n"
            f"After installing, run this script again."
        )
        return 1

    print(f"\nFound Python: {python_cmd}")

    # Create venv
    if not create_venv(python_cmd):
        return 1

    # Determine which backends to install
    requested = []
    for key in BACKENDS:
        if f"--{key}" in args:
            requested.append(key)

    # If no specific backends requested, install all
    if not requested:
        requested = list(BACKENDS.keys())

    # Install backends
    results: dict[str, bool] = {}
    for key in requested:
        results[key] = install_backend(key)

    # Check CUDA
    venv_python = get_venv_python()
    result = subprocess.run(
        [venv_python, "-c",
         "import torch; print('CUDA' if torch.cuda.is_available() else 'CPU')"],
        capture_output=True, text=True,
    )
    device = result.stdout.strip()

    # Create supporting directories
    Path("rvc_models").mkdir(exist_ok=True)
    Path("voice_refs").mkdir(exist_ok=True)

    # Summary
    print(f"\n{'='*60}")
    print("Setup Summary")
    print(f"{'='*60}")
    print(f"Device: {device}")

    for key, success in results.items():
        status = "OK" if success else "FAILED"
        print(f"  {BACKENDS[key].name}: {status}")

    success_count = sum(results.values())
    print(f"\n{success_count}/{len(results)} backends installed successfully.")

    if results.get("rvc"):
        print(f"\nRVC next steps:")
        print(f"  1. Download a voice model (.pth + .index)")
        print(f"  2. Place in rvc_models/")
        print(f"  3. Set rvc_model='model_name' in VocalSection")

    if results.get("xtts"):
        print(f"\nXTTS next steps:")
        print(f"  1. Record or find a ~6 second voice reference (.wav)")
        print(f"  2. Place in voice_refs/")
        print(f"  3. Set backend='xtts', voice_ref='name' in VocalSection")

    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
