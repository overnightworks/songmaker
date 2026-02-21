"""XTTS v2 inference script — runs inside the isolated venv.

This script is called by XTTSConverter via subprocess. It reads
a JSON config file, performs TTS using Coqui XTTS v2, and writes
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
        print("Usage: python _xtts_infer.py <config.json>", file=sys.stderr)
        return 1

    config_path = Path(sys.argv[1])
    if not config_path.exists():
        print(f"Config file not found: {config_path}", file=sys.stderr)
        return 1

    config = json.loads(config_path.read_text(encoding="utf-8"))

    text = config["text"]
    output_path = config["output_path"]
    language = config.get("language", "en")
    speaker_wav = config.get("speaker_wav", "")
    model_name = config.get("model_name", "tts_models/multilingual/multi-dataset/xtts_v2")

    try:
        import torch
        from TTS.api import TTS

        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"Device: {device}", file=sys.stderr)

        tts = TTS(model_name).to(device)

        kwargs = {
            "text": text,
            "language": language,
            "file_path": output_path,
        }

        # Voice cloning requires a reference audio file
        if speaker_wav and Path(speaker_wav).exists():
            kwargs["speaker_wav"] = speaker_wav

        tts.tts_to_file(**kwargs)

        if Path(output_path).exists():
            print(f"OK: {output_path}")
            return 0
        else:
            print("Output file was not created", file=sys.stderr)
            return 1

    except ImportError:
        print(
            "coqui-tts not installed in this environment. "
            "Run: pip install coqui-tts",
            file=sys.stderr,
        )
        return 1
    except Exception as exc:
        print(f"XTTS inference failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
