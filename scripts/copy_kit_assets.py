"""Copy the appkit look (family tokens and fonts) into frontend/kit-assets/.

Run it with the wheel's group only:
    uv run --frozen --only-group frontend python scripts/copy_kit_assets.py
"""

import importlib.resources
import shutil
from pathlib import Path

KIT_ASSETS_DIRECTORY = Path(__file__).resolve().parent.parent / "frontend" / "kit-assets"


def replace_with_copy(source: Path, target: Path) -> None:
    """Make `target` an exact copy of `source`, dropping anything it held before."""
    fresh = target.with_name(f"{target.name}.new")
    shutil.rmtree(fresh, ignore_errors=True)
    shutil.copytree(source, fresh)
    shutil.rmtree(target, ignore_errors=True)
    fresh.rename(target)


def main() -> None:
    with importlib.resources.as_file(importlib.resources.files("appkit") / "static") as static:
        replace_with_copy(static, KIT_ASSETS_DIRECTORY)


if __name__ == "__main__":
    main()
