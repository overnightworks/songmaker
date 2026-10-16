"""Measurement only: candidate code routes for the three security markers (#1482)."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

EXACT_GIT_SHA = re.compile(r"[0-9a-f]{40}")


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-revision", required=True)
    parser.add_argument("--path", required=True)
    return parser.parse_args()


def a0_path_replace(output: Path, text: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(output)


def a1_os_replace(output: Path, text: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, output)


def a2_shutil_move(output: Path, text: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    shutil.move(temporary, output)


def a3_path_rename(output: Path, text: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.rename(output)


def a4_resolved_inside_project(output: Path, text: str) -> None:
    resolved = output.resolve()
    if not resolved.is_relative_to(Path.cwd().resolve()):
        raise ValueError("output escapes the project")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    temporary = resolved.with_name(f".{resolved.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(resolved)


def a5_realpath_prefix(output: Path, text: str) -> None:
    real = os.path.realpath(output)
    if not real.startswith(os.path.realpath(os.getcwd()) + os.sep):
        raise ValueError("output escapes the project")
    temporary = real + ".tmp"
    Path(temporary).write_text(text, encoding="utf-8")
    os.replace(temporary, real)


def b0_argv_list(project_root: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *arguments], cwd=project_root, check=False, capture_output=True
    )


def b1_regex_match_group(project_root: Path, revision: str) -> subprocess.CompletedProcess[bytes]:
    match = EXACT_GIT_SHA.fullmatch(revision)
    if match is None:
        raise ValueError("not a SHA")
    return subprocess.run(
        ["git", "cat-file", "-e", match[0]], cwd=project_root, check=False, capture_output=True
    )


def b2_regex_check_only(project_root: Path, revision: str) -> subprocess.CompletedProcess[bytes]:
    if EXACT_GIT_SHA.fullmatch(revision) is None:
        raise ValueError("not a SHA")
    return subprocess.run(
        ["git", "cat-file", "-e", revision], cwd=project_root, check=False, capture_output=True
    )


def b3_end_of_options(project_root: Path, revision: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "rev-parse", "--verify", "--end-of-options", revision],
        cwd=project_root,
        check=False,
        capture_output=True,
    )


def b4_dash_guard(project_root: Path, revision: str) -> subprocess.CompletedProcess[bytes]:
    if revision.startswith("-"):
        raise ValueError("option-like revision")
    return subprocess.run(
        ["git", "cat-file", "-e", revision], cwd=project_root, check=False, capture_output=True
    )


def c0_reexec(raw_arguments: list[str]) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), *raw_arguments, "--worker"],
        cwd=Path.cwd(),
        shell=False,
    )


def c1_reexec_equals_form(path: str) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), f"--path={path}", "--worker"],
        cwd=Path.cwd(),
        shell=False,
    )


def main() -> int:
    arguments = _arguments()
    a0_path_replace(arguments.output, "a0")
    a1_os_replace(arguments.output, "a1")
    a2_shutil_move(arguments.output, "a2")
    a3_path_rename(arguments.output, "a3")
    a4_resolved_inside_project(arguments.output, "a4")
    a5_realpath_prefix(arguments.output, "a5")
    b0_argv_list(Path.cwd(), "cat-file", "-e", arguments.base_revision)
    b1_regex_match_group(Path.cwd(), arguments.base_revision)
    b2_regex_check_only(Path.cwd(), arguments.base_revision)
    b3_end_of_options(Path.cwd(), arguments.base_revision)
    b4_dash_guard(Path.cwd(), arguments.base_revision)
    c0_reexec(sys.argv[1:])
    c1_reexec_equals_form(arguments.path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
