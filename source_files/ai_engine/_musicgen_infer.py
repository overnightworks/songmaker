"""MusicGen inference script — runs inside the isolated venv.

This script is called by MusicGenRenderer via subprocess. It reads
a JSON config file, generates audio using Meta's MusicGen, and writes
the output WAV file.

Do NOT import this from the main codebase — it runs in a
separate Python environment (3.12).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python _musicgen_infer.py <config.json>", file=sys.stderr)
        return 1

    config_path = Path(sys.argv[1])
    if not config_path.exists():
        print(f"Config file not found: {config_path}", file=sys.stderr)
        return 1

    config = json.loads(config_path.read_text(encoding="utf-8"))

    prompt = config["prompt"]
    output_path = config["output_path"]
    duration_seconds = config.get("duration_seconds", 10)
    model_name = config.get("model_name", "facebook/musicgen-small")
    sample_rate = config.get("sample_rate", 32000)

    try:
        import torch
        import torchaudio
        from audiocraft.models import MusicGen

        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"Device: {device}", file=sys.stderr)

        # Load model
        model = MusicGen.get_pretrained(model_name, device=device)
        model.set_generation_params(duration=duration_seconds)

        # Generate audio
        descriptions = [prompt]
        wav = model.generate(descriptions)

        # wav shape: (batch, channels, samples) — take first batch item
        audio = wav[0]  # (channels, samples)

        # Save as WAV
        torchaudio.save(output_path, audio.cpu(), sample_rate=sample_rate)

        if Path(output_path).exists():
            print(f"OK: {output_path}")
            return 0
        else:
            print("Output file was not created", file=sys.stderr)
            return 1

    except ImportError as exc:
        print(
            f"audiocraft not installed in this environment. "
            f"Run: pip install audiocraft ({exc})",
            file=sys.stderr,
        )
        return 1
    except Exception as exc:
        print(f"MusicGen inference failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
