"""RVC inference script — runs inside the isolated RVC venv.

This script is called by RVCConverter via subprocess. It reads
a JSON config file, performs voice conversion using rvc-python,
and writes the output WAV file.

Do NOT import this from the main codebase — it runs in a
separate Python environment (3.10-3.12).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python _rvc_infer.py <config.json>", file=sys.stderr)
        return 1

    config_path = Path(sys.argv[1])
    if not config_path.exists():
        print(f"Config file not found: {config_path}", file=sys.stderr)
        return 1

    config = json.loads(config_path.read_text(encoding="utf-8"))

    input_path = config["input_path"]
    output_path = config["output_path"]
    model_path = config["model_path"]
    index_path = config.get("index_path", "")
    pitch_shift = config.get("pitch_shift", 0)
    index_rate = config.get("index_rate", 0.66)
    filter_radius = config.get("filter_radius", 3)
    rms_mix_rate = config.get("rms_mix_rate", 0.25)
    protect = config.get("protect", 0.33)
    f0_method = config.get("f0_method", "rmvpe")

    if not Path(input_path).exists():
        print(f"Input file not found: {input_path}", file=sys.stderr)
        return 1

    if not Path(model_path).exists():
        print(f"Model file not found: {model_path}", file=sys.stderr)
        return 1

    try:
        from rvc_python.infer import RVCInference

        import torch

        device = "cuda:0" if torch.cuda.is_available() else "cpu"

        rvc = RVCInference(device=device)
        rvc.load_model(model_path)

        rvc.infer_file(
            input_path=input_path,
            output_path=output_path,
            f0method=f0_method,
            f0up_key=pitch_shift,
            index_path=index_path if index_path else None,
            index_rate=index_rate,
            filter_radius=filter_radius,
            rms_mix_rate=rms_mix_rate,
            protect=protect,
        )

        if Path(output_path).exists():
            print(f"OK: {output_path}")
            return 0
        else:
            print("Output file was not created", file=sys.stderr)
            return 1

    except ImportError:
        print(
            "rvc-python not installed in this environment. "
            "Run: pip install rvc-python",
            file=sys.stderr,
        )
        return 1
    except Exception as exc:
        print(f"RVC inference failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
