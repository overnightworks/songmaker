"""Demucs inference script — runs inside the isolated venv.

This script is called by DemucsSeparator via subprocess. It reads
a JSON config file, performs stem separation using Demucs, and writes
the output WAV files.

Do NOT import this from the main codebase — it runs in a
separate Python environment (3.12).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python _demucs_infer.py <config.json>", file=sys.stderr)
        return 1

    config_path = Path(sys.argv[1])
    if not config_path.exists():
        print(f"Config file not found: {config_path}", file=sys.stderr)
        return 1

    config = json.loads(config_path.read_text(encoding="utf-8"))

    input_path = config["input_path"]
    output_dir = config["output_dir"]
    model_name = config.get("model_name", "htdemucs")
    segment = config.get("segment", 7)

    if not Path(input_path).exists():
        print(f"Input file not found: {input_path}", file=sys.stderr)
        return 1

    try:
        import torch
        import torchaudio
        from demucs.pretrained import get_model
        from demucs.apply import apply_model

        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"Device: {device}", file=sys.stderr)

        # Load model
        model = get_model(model_name)
        model.to(device)

        # Load audio
        wav, sr = torchaudio.load(input_path)
        # Ensure stereo
        if wav.shape[0] == 1:
            wav = wav.repeat(2, 1)
        # Add batch dimension
        wav = wav.unsqueeze(0).to(device)

        # Separate
        with torch.no_grad():
            sources = apply_model(
                model,
                wav,
                segment=segment,
                device=device,
            )

        # sources shape: (batch, stems, channels, samples)
        # stems order: drums, bass, other, vocals (for htdemucs)
        source_names = model.sources  # e.g., ['drums', 'bass', 'other', 'vocals']

        Path(output_dir).mkdir(parents=True, exist_ok=True)

        for i, name in enumerate(source_names):
            stem = sources[0, i]  # (channels, samples)
            output_path = Path(output_dir) / f"{name}.wav"
            torchaudio.save(str(output_path), stem.cpu(), sample_rate=sr)
            print(f"OK: {name} -> {output_path}")

        return 0

    except ImportError as exc:
        print(
            f"demucs not installed in this environment. "
            f"Run: pip install demucs ({exc})",
            file=sys.stderr,
        )
        return 1
    except Exception as exc:
        print(f"Demucs separation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
