"""Measurement only: candidate code routes for the CLI-path sinks of #1498, never merged."""

import argparse
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parent.parent


def read_plain(path: Path) -> str:
    return path.read_text()


def read_resolved(path: Path) -> str:
    return path.resolve().read_text()


def read_contained(path: Path) -> str:
    resolved = path.resolve()
    if not resolved.is_relative_to(REPOSITORY):
        raise ValueError(resolved)
    return resolved.read_text()


def write_plain(path: Path) -> None:
    path.write_text("x")


def write_resolved(path: Path) -> None:
    path.resolve().write_text("x")


def write_contained(path: Path) -> None:
    resolved = path.resolve()
    if not resolved.is_relative_to(REPOSITORY):
        raise ValueError(resolved)
    resolved.write_text("x")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=Path)
    args = parser.parse_args()
    read_plain(args.target)
    read_resolved(args.target)
    read_contained(args.target)
    write_plain(args.target)
    write_resolved(args.target)
    write_contained(args.target)
    return 0
