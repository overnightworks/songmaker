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
import subprocess
import sys
from pathlib import Path

from common import find_uv

ACESTEP_DIR = Path(__file__).resolve().parent.parent / "_models" / "acestep"
DEFAULT_PORT = 8001


def main() -> None:
    parser = argparse.ArgumentParser(description="Start ACE-Step API server")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--device", default="cuda", help="Device (cuda/cpu)")
    parser.add_argument(
        "--lm-model",
        default="acestep-5Hz-lm-4B",
        help=(
            "LM model for song planning. RTX 3090: 4B (best). "
            "12-16GB: 1.7B. 6-8GB: 0.6B. Use 'none' to disable."
        ),
    )
    parser.add_argument(
        "--lm-backend",
        default="vllm",
        choices=["pt", "vllm"],
        help="LM inference backend (vllm=fast, recommended for 3090; pt=fallback)",
    )
    parser.add_argument(
        "--config",
        default="acestep-v15-sft",
        help="DiT model config (acestep-v15-sft / acestep-v15-turbo / acestep-v15-base)",
    )
    args = parser.parse_args()

    # Platform-aware venv python path
    if sys.platform == "win32":
        venv_python = ACESTEP_DIR / ".venv" / "Scripts" / "python.exe"
    else:
        venv_python = ACESTEP_DIR / ".venv" / "bin" / "python"
    if not venv_python.exists():
        print(f"Error: {ACESTEP_DIR}/.venv not found. Run: python scripts/setup_acestep.py")
        sys.exit(1)

    uv = find_uv()
    if not uv:
        print("Error: uv not found. Install with: pip install uv")
        sys.exit(1)

    # Set environment variables for ACE-Step config
    env = os.environ.copy()
    env["ACESTEP_API_PORT"] = str(args.port)
    env["ACESTEP_API_HOST"] = "0.0.0.0"
    env["ACESTEP_DEVICE"] = args.device
    # DiT model config (turbo = 8 steps, Very High quality, no CFG)
    env.setdefault("ACESTEP_CONFIG_PATH", args.config)
    # LM planner — enables query rewriting + CoT for better song structure
    if args.lm_model.lower() == "none":
        env.setdefault("ACESTEP_INIT_LLM", "0")
    else:
        env.setdefault("ACESTEP_INIT_LLM", "1")
        env.setdefault("ACESTEP_LM_MODEL_PATH", args.lm_model)
        env.setdefault("ACESTEP_LM_BACKEND", args.lm_backend)
    # RTX 3090 (24GB): no offloading needed — all models fit in VRAM
    # Disable torch.compile (torchao INT8 incompatible with torch 2.7.1)
    env.setdefault("ACESTEP_COMPILE_MODEL", "0")

    if args.lm_model.lower() == "none":
        lm_status = "disabled"
    else:
        lm_status = f"{args.lm_model} ({args.lm_backend})"
    print(f"Starting ACE-Step server on port {args.port}...")
    print(f"  Device:    {args.device}")
    print(f"  DiT:       {args.config}")
    print(f"  LM model:  {lm_status}")
    print(f"  Python:    {venv_python.resolve()}")
    print(f"  Health:    http://localhost:{args.port}/health")
    print()

    # Use uv run from the ACE-Step directory (resolves all paths correctly)
    cmd = [*uv, "run", "acestep-api", "--port", str(args.port)]

    try:
        subprocess.run(cmd, env=env, cwd=ACESTEP_DIR)
    except KeyboardInterrupt:
        print("\nServer stopped.")


if __name__ == "__main__":
    main()
