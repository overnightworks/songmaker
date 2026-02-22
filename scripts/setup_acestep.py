"""Setup ACE-Step 1.5 using uv.

This script:
  1. Clones the ACE-Step 1.5 repo into _models/acestep/
  2. Runs `uv sync` inside the repo (creates _models/acestep/.venv with all deps)
  3. Downloads model checkpoints (turbo model + 0.6B LM)

ACE-Step's pyproject.toml uses [tool.uv.sources] for CUDA-specific
torch wheels and local path deps (nano-vllm). Only uv can resolve
these — pip cannot. So we use uv natively.

Requires: uv (pip install uv)

Run once:
    python scripts/setup_acestep.py

After setup, start the server:
    python scripts/start_acestep.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REPO_URL = "https://github.com/ACE-Step/ACE-Step-1.5.git"
ACESTEP_DIR = Path(__file__).resolve().parent.parent / "_models" / "acestep"


def _find_uv() -> list[str]:
    """Find a working uv command.

    Returns the command prefix as a list (e.g. ["uv"] or
    [sys.executable, "-m", "uv"]).
    """
    # 1. Try bare `uv` on PATH
    if shutil.which("uv"):
        return ["uv"]

    # 2. Try `python -m uv` (pip-installed into current interpreter)
    try:
        subprocess.run(
            [sys.executable, "-m", "uv", "--version"],
            capture_output=True, check=True,
        )
        return [sys.executable, "-m", "uv"]
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass

    # 3. Check common install locations on Windows
    if sys.platform == "win32":
        from pathlib import Path as _Path
        home = _Path.home()
        candidates = [
            home / ".local" / "bin" / "uv.exe",
            home / ".cargo" / "bin" / "uv.exe",
            home / "AppData" / "Roaming" / "Python" / "Python312" / "Scripts" / "uv.exe",
        ]
        for candidate in candidates:
            if candidate.exists():
                return [str(candidate)]

    return []


def run(cmd: list[str], cwd: str | Path | None = None) -> None:
    """Run a command and exit on failure."""
    print(f"  > {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd)
    if result.returncode != 0:
        print(f"  FAILED (exit {result.returncode})")
        sys.exit(1)


def main() -> None:
    print("=" * 60)
    print("  ACE-Step 1.5 Setup (via uv)")
    print("=" * 60)

    # Find uv
    uv = _find_uv()
    if not uv:
        print("\n  Error: uv not found. Install with: pip install uv")
        sys.exit(1)
    print(f"\n  Using uv: {' '.join(uv)}")

    # Step 1: Clone repo
    if ACESTEP_DIR.exists():
        print(f"\n  [1/3] {ACESTEP_DIR} already exists, pulling latest...")
        run(["git", "-C", str(ACESTEP_DIR), "pull"])
    else:
        print(f"\n  [1/3] Cloning ACE-Step 1.5 into {ACESTEP_DIR}/...")
        run(["git", "clone", "--depth", "1", REPO_URL, str(ACESTEP_DIR)])

    # Step 2: uv sync (creates _acestep/.venv with all deps)
    print("\n  [2/3] Installing ACE-Step via uv sync...")
    print("        (this may take a while — torch + many ML deps)")
    run([*uv, "sync"], cwd=ACESTEP_DIR)

    # Step 3: Download models
    # "main" = bundled package: vae + turbo DiT + 1.7B LM + embeddings (~5 GB)
    # "acestep-5Hz-lm-0.6B" = smaller LM for 6GB GPUs (optional, saves VRAM)
    print("\n  [3/3] Downloading model checkpoints...")
    print("        This may take a while (~5 GB)...")
    run([*uv, "run", "acestep-download", "--model", "main"],
        cwd=ACESTEP_DIR)

    venv_path = ACESTEP_DIR / ".venv"
    print("\n" + "=" * 60)
    print("  Setup complete!")
    print(f"  Venv: {venv_path.resolve()}")
    print(f"  Repo: {ACESTEP_DIR.resolve()}")
    print()
    print("  Next: python scripts/start_acestep.py")
    print("=" * 60)


if __name__ == "__main__":
    main()
