"""Measurement only: candidate code routes for the three security markers (#1482)."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def a0_path_replace(output: Path, text: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(output)


def a6_realpath_only(output: Path, text: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, os.path.realpath(output))


def a7_resolve_only(output: Path, text: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(output.resolve())


def a8_abspath_only(output: Path, text: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, os.path.abspath(output))


def a9_parent_and_name(output: Path, text: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(output.parent / output.name)


def a10_os_rename(output: Path, text: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.rename(temporary, output)


def main() -> int:
    arguments = _arguments()
    a0_path_replace(arguments.output, "a0")
    a6_realpath_only(arguments.output, "a6")
    a7_resolve_only(arguments.output, "a7")
    a8_abspath_only(arguments.output, "a8")
    a9_parent_and_name(arguments.output, "a9")
    a10_os_rename(arguments.output, "a10")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
