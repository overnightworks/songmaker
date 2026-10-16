"""Measurement only: candidate code routes for #1498, never merged."""

import argparse
import os
import re
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parent.parent

DIM_CURRENT = re.compile(r"(?<![\w-])(-?(?:\d+(?:\.\d+)?|\.\d+))([a-z%]*)", re.IGNORECASE)
IMP_LOOKBEHIND = re.compile(r"(?<!\s)\s*!important\b", re.IGNORECASE)
IMP_POSSESSIVE = re.compile(r"\s*+!important\b", re.IGNORECASE)
IMP_ATOMIC = re.compile(r"(?>\s*)!important\b", re.IGNORECASE)
IMP_PLAIN = re.compile(r"!important\b", re.IGNORECASE)
IMP_ORIGINAL = re.compile(r"\s*!important\b", re.IGNORECASE)
DIM_ORIGINAL = re.compile(r"(?<![\w-])(-?(?:\d*\.)?\d+)([a-z%]*)", re.IGNORECASE)


def use_patterns(value: str) -> list[object]:
    return [
        DIM_CURRENT.findall(value),
        IMP_LOOKBEHIND.sub("", value),
        IMP_POSSESSIVE.sub("", value),
        IMP_ATOMIC.sub("", value),
        IMP_PLAIN.sub("", value),
        IMP_ORIGINAL.sub("", value),
        DIM_ORIGINAL.findall(value),
    ]


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=Path)
    return parser.parse_args()


def control() -> str:
    return arguments().target.read_text()


def resolved_inline() -> str:
    return arguments().target.resolve().read_text()


def resolved_variable() -> str:
    target = arguments().target.resolve()
    return target.read_text()


def contained() -> str:
    target = arguments().target.resolve()
    if not target.is_relative_to(REPOSITORY):
        raise ValueError(target)
    return target.read_text()


def realpath_wrapped() -> str:
    return Path(os.path.realpath(arguments().target)).read_text()


def resolved_write() -> None:
    arguments().target.resolve().write_text("x")


def control_write() -> None:
    arguments().target.write_text("x")


def read_through_helper(path: Path) -> str:
    return path.resolve().read_text()


def helper_caller() -> str:
    return read_through_helper(arguments().target)


def keyed() -> str:
    return arguments().target.read_text()  # NOSONAR(S8707) Operator-named CLI path.
