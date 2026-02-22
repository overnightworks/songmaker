"""Launch the ACE-Step 1.5 API server.

Starts the FastAPI server on port 8001 using the _models/acestep/.venv venv.
The server loads the model once and serves generation requests over HTTP.

Usage:
    python scripts/start_acestep.py              # Default port 8001
    python scripts/start_acestep.py --port 8002  # Custom port

The server must be running before any track script that uses
acestep_engine.AceStepClient can generate vocals.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ACESTEP_DIR = Path(__file__).resolve().parent.parent / "_models" / "acestep"
DEFAULT_PORT = 8001


def _find_uv() -> list[str]:
    """Find a working uv command."""
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
        home = Path.home()
        candidates = [
            home / ".local" / "bin" / "uv.exe",
            home / ".cargo" / "bin" / "uv.exe",
            home / "AppData" / "Roaming" / "Python" / "Python312" / "Scripts" / "uv.exe",
        ]
        for candidate in candidates:
            if candidate.exists():
                return [str(candidate)]

    return []


def main() -> None:
    parser = argparse.ArgumentParser(description="Start ACE-Step API server")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--device", default="cuda", help="Device (cuda/cpu)")
    args = parser.parse_args()

    venv_python = ACESTEP_DIR / ".venv" / "Scripts" / "python.exe"
    if not venv_python.exists():
        print(f"Error: {ACESTEP_DIR}/.venv not found. Run: python scripts/setup_acestep.py")
        sys.exit(1)

    uv = _find_uv()
    if not uv:
        print("Error: uv not found. Install with: pip install uv")
        sys.exit(1)

    # Set environment variables for ACE-Step config
    env = os.environ.copy()
    env["ACESTEP_API_PORT"] = str(args.port)
    env["ACESTEP_API_HOST"] = "0.0.0.0"
    env["ACESTEP_DEVICE"] = args.device
    # Use PyTorch LM backend (avoids nano-vllm CUDA/triton issues on Windows)
    env.setdefault("ACESTEP_LM_BACKEND", "pt")

    print(f"Starting ACE-Step server on port {args.port}...")
    print(f"  Device: {args.device}")
    print(f"  Python: {venv_python.resolve()}")
    print(f"  Health: http://localhost:{args.port}/health")
    print()

    # Use uv run from the ACE-Step directory (resolves all paths correctly)
    cmd = [*uv, "run", "acestep-api", "--port", str(args.port)]

    try:
        subprocess.run(cmd, env=env, cwd=ACESTEP_DIR)
    except KeyboardInterrupt:
        print("\nServer stopped.")


if __name__ == "__main__":
    main()
