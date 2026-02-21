"""Patch fairseq 0.12.2 for Python 3.12 compatibility.

fairseq uses mutable dataclass defaults (e.g., `field: Config = Config()` and
`field(default=Config())`) which Python 3.12 rejects. This script:
1. Scans ALL .py files in fairseq and fixes mutable defaults in @dataclass classes
2. Wraps hydra_init and module imports in try/except (omegaconf compat)

Run after: uv sync
"""

from pathlib import Path
import re
import sys

VENV = Path(".venv")
FAIRSEQ_DIR = VENV / "Lib" / "site-packages" / "fairseq"
INIT = FAIRSEQ_DIR / "__init__.py"

if not FAIRSEQ_DIR.exists():
    print("fairseq not found — skipping patch")
    sys.exit(0)


def patch_dataclass_defaults(content: str) -> str:
    """Fix mutable defaults in @dataclass classes only.

    Patches two patterns inside @dataclass class bodies (4-space indent):
      1. `name: Type = Type()`           → `name: Type = field(default_factory=Type)`
      2. `name: Type = field(default=Type())` → `name: Type = field(default_factory=Type)`
    """
    lines = content.split("\n")
    result = []
    in_dataclass = False

    for line in lines:
        stripped = line.strip()

        if stripped == "@dataclass" or stripped.startswith("@dataclass("):
            in_dataclass = True
            result.append(line)
            continue

        if in_dataclass and stripped.startswith("class ") and stripped.endswith(":"):
            result.append(line)
            continue

        if in_dataclass:
            if stripped and not line.startswith("    ") and not line.startswith("\t"):
                in_dataclass = False
                result.append(line)
                continue

            # Pattern 1: name: Type = Type()
            m = re.match(
                r"^(    )(\w+):\s+(\w+)\s*=\s*(\w+)\(\)\s*$",
                line,
            )
            if m:
                indent, name, type_hint, factory = m.groups()
                result.append(f"{indent}{name}: {type_hint} = field(default_factory={factory})")
                continue

            # Pattern 2: name: Type = field(default=Type())
            m2 = re.match(
                r"^(    )(\w+):\s+(\w+)\s*=\s*field\(default=(\w+)\(\)\)",
                line,
            )
            if m2:
                indent, name, type_hint, factory = m2.groups()
                result.append(f"{indent}{name}: {type_hint} = field(default_factory={factory})")
                continue

        result.append(line)

    return "\n".join(result)


# --- Patch 1: Fix mutable dataclass defaults in ALL fairseq .py files ---
total_fixes = 0
for py_file in FAIRSEQ_DIR.rglob("*.py"):
    try:
        content = py_file.read_text(encoding="utf-8")
    except Exception:
        continue

    if "@dataclass" not in content:
        continue

    patched = patch_dataclass_defaults(content)

    if patched != content:
        if "from dataclasses import" in patched:
            import_line = patched.split("from dataclasses import")[1].split("\n")[0]
            if "field" not in import_line:
                patched = patched.replace(
                    "from dataclasses import dataclass",
                    "from dataclasses import dataclass, field",
                    1,
                )

        py_file.write_text(patched, encoding="utf-8")
        fixes = patched.count("default_factory=") - content.count("default_factory=")
        total_fixes += fixes

print(f"[1/2] Patched {total_fixes} mutable dataclass defaults across fairseq")

# --- Patch 2: Wrap hydra_init + module imports in __init__.py ---
init_content = INIT.read_text(encoding="utf-8")
if "# [patched]" in init_content:
    print("[2/2] __init__.py already patched")
    sys.exit(0)

old_block = """# backwards compatibility to support `from fairseq.X import Y`
from fairseq.distributed import utils as distributed_utils
from fairseq.logging import meters, metrics, progress_bar  # noqa

sys.modules["fairseq.distributed_utils"] = distributed_utils
sys.modules["fairseq.meters"] = meters
sys.modules["fairseq.metrics"] = metrics
sys.modules["fairseq.progress_bar"] = progress_bar

# initialize hydra
from fairseq.dataclass.initialize import hydra_init

hydra_init()

import fairseq.criterions  # noqa
import fairseq.distributed  # noqa
import fairseq.models  # noqa
import fairseq.modules  # noqa
import fairseq.optim  # noqa
import fairseq.optim.lr_scheduler  # noqa
import fairseq.pdb  # noqa
import fairseq.scoring  # noqa
import fairseq.tasks  # noqa
import fairseq.token_generation_constraints  # noqa

import fairseq.benchmark  # noqa
import fairseq.model_parallel  # noqa"""

new_block = """# [patched] Python 3.12 compatibility — wrap imports that may fail
try:
    from fairseq.distributed import utils as distributed_utils
    from fairseq.logging import meters, metrics, progress_bar  # noqa
    sys.modules["fairseq.distributed_utils"] = distributed_utils
    sys.modules["fairseq.meters"] = meters
    sys.modules["fairseq.metrics"] = metrics
    sys.modules["fairseq.progress_bar"] = progress_bar
except Exception:
    pass

try:
    from fairseq.dataclass.initialize import hydra_init
    hydra_init()
except Exception:
    pass

for _mod in [
    "fairseq.criterions", "fairseq.distributed", "fairseq.models",
    "fairseq.modules", "fairseq.optim", "fairseq.optim.lr_scheduler",
    "fairseq.pdb", "fairseq.scoring", "fairseq.tasks",
    "fairseq.token_generation_constraints", "fairseq.benchmark",
    "fairseq.model_parallel",
]:
    try:
        __import__(_mod)
    except Exception:
        pass"""

if old_block in init_content:
    init_patched = init_content.replace(old_block, new_block)
    INIT.write_text(init_patched, encoding="utf-8")
    print("[2/2] Patched __init__.py with try/except wrappers")
else:
    print("[2/2] __init__.py already patched or block not found")
