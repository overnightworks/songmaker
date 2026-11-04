#!/usr/bin/env python3
"""Copy the stack's secrets out of ``.env`` into files, and verify compose's declared ones.

    ./scripts/secret_files.py            copy each moved key's value into its file
    ./scripts/secret_files.py --verify   judge the files compose declares

The directory is ``SONGMAKER_SECRETS_DIR`` (an exported value, then ``.env``),
by default ``$HOME/.secrets/songmaker``.

Copy never regenerates a value: it writes the ``.env`` value, refuses to
overwrite a file holding another one, and leaves ``.env`` alone. Verify reads
``docker compose config --format json`` in memory only (that output carries
every interpolated value) and judges just the top-level ``secrets.*.file``
paths. Neither mode ever prints a value; a refusal names the file and the key.

Stdlib only, runnable under the system ``python3``.
"""
# ruff: noqa: T201 - this command reports what it copied and why it refused

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from dotenv_file import DotenvError, compose_value, effective_assignment

DIRECTORY_KEY = "SONGMAKER_SECRETS_DIR"
DEFAULT_DIRECTORY = Path(".secrets") / "songmaker"
DIRECTORY_MODE = 0o700
FILE_MODE = 0o644
CONFIG_COMMAND = ("docker", "compose", "config", "--format", "json")


@dataclass(frozen=True)
class SecretFile:
    name: str
    key: str
    optional: bool = False


TABLE = (
    SecretFile("session-secret", "SESSION_SECRET"),
    SecretFile("postgres-password", "POSTGRES_PASSWORD"),
    SecretFile("internal-token", "SONGMAKER_INTERNAL_TOKEN"),
    SecretFile("monitoring-token", "SONGMAKER_MONITORING_TOKEN"),
    SecretFile("hf-token", "HF_TOKEN", optional=True),
)
TABLE_BY_NAME = {entry.name: entry for entry in TABLE}


class Refusal(Exception):
    """A named reason to stop; never carries a value."""


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--verify", action="store_true", help="judge compose's declared files")
    arguments = parser.parse_args(argv)
    project_root = Path(__file__).resolve().parent.parent
    try:
        if arguments.verify:
            verify(project_root, Path.home())
        else:
            copy(project_root, Path.home())
    except Refusal as refusal:
        print(f"secret_files.py: {refusal}", file=sys.stderr)
        return 1
    return 0


def _read_env_text(env_file: Path, *, required: bool) -> str:
    try:
        return env_file.read_text()
    except FileNotFoundError as exc:
        if required:
            raise Refusal(f"no .env at {env_file}") from exc
        return ""
    except (OSError, UnicodeDecodeError) as exc:
        raise Refusal(f"cannot read {env_file}") from exc


def _env_value(text: str, entry: SecretFile, env_file: Path) -> str | None:
    """The ``.env`` value for the entry's key, refusing an exported value that differs."""
    try:
        assignment = effective_assignment(text, entry.key, env_file)
    except DotenvError as exc:
        raise Refusal(str(exc)) from exc
    if assignment is None:
        return None
    exported = os.environ.get(entry.key)
    if exported is not None and exported != assignment.value:
        raise Refusal(
            f"{entry.key} is exported in the shell with a value that differs from "
            f"{env_file}; compose would use the exported one",
        )
    return assignment.value


def _resolve_directory(text: str, env_file: Path, home: Path) -> Path:
    try:
        configured = compose_value(os.environ, text, DIRECTORY_KEY, env_file)
    except DotenvError as exc:
        raise Refusal(str(exc)) from exc
    if not configured:
        return home / DEFAULT_DIRECTORY
    if configured.startswith("~/"):
        return home / configured[2:]
    if not configured.startswith("/"):
        raise Refusal(f"{DIRECTORY_KEY} must be an absolute path or ~/…")
    return Path(configured)


def _read_file(path: Path) -> str | None:
    if path.is_symlink() or path.parent.is_symlink():
        raise Refusal(f"{path} or its directory is a symbolic link; a secret file must be real")
    try:
        return path.read_text()
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as exc:
        raise Refusal(f"cannot read {path}") from exc


def copy(project_root: Path, home: Path) -> None:
    env_file = project_root / ".env"
    text = _read_env_text(env_file, required=True)
    directory = _resolve_directory(text, env_file, home)
    _require_private_directory(directory)
    pending: list[tuple[SecretFile, str]] = []
    for entry in TABLE:
        value = _env_value(text, entry, env_file)
        if value is None:
            print(f"skipped {entry.name}: {entry.key} is not in {env_file}")
            continue
        if not value and not entry.optional:
            raise Refusal(f"{entry.key} is empty in {env_file}; {entry.name} would be empty")
        if value != value.strip():
            raise Refusal(f"{entry.key} in {env_file} has surrounding whitespace; fix it there")
        existing = _read_file(directory / entry.name)
        if existing is None:
            pending.append((entry, value))
        elif existing.strip() == value:
            print(f"already copied {entry.name}")
        else:
            raise Refusal(
                f"{directory / entry.name} holds another value than {entry.key} in "
                f"{env_file}; not overwriting it",
            )
    if pending and not directory.exists():
        try:
            directory.parent.mkdir(parents=True, exist_ok=True)
            directory.mkdir(mode=DIRECTORY_MODE)
            directory.chmod(DIRECTORY_MODE)
        except OSError as exc:
            raise Refusal(f"cannot create {directory}") from exc
    for entry, value in pending:
        if _publish(directory / entry.name, value):
            print(f"copied {entry.key} to {directory / entry.name}")
        else:
            print(f"already copied {entry.name}")


def _require_private_directory(directory: Path) -> None:
    try:
        status = directory.lstat()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise Refusal(f"cannot inspect {directory}") from exc
    if (
        not stat.S_ISDIR(status.st_mode)
        or status.st_uid != os.getuid()
        or stat.S_IMODE(status.st_mode) != DIRECTORY_MODE
    ):
        raise Refusal(
            f"{directory} must be a directory owned by you with mode {DIRECTORY_MODE:o}",
        )


def _publish(path: Path, value: str) -> bool:
    """Link a finished temporary file to ``path``; never replaces a file that appeared meanwhile.

    Returns whether it wrote; a file that is already there is judged like any
    existing one (equal after stripping is a no-op, another value is refused).
    """
    try:
        descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    except OSError as exc:
        raise Refusal(f"cannot write {path}") from exc
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(value.encode())
            handle.flush()
            os.fchmod(handle.fileno(), FILE_MODE)  # noqa: E501  # NOSONAR(S2612) 0644 inside the 0700 secrets directory: postgres (uid 70) and prometheus (65534) read these files, as hal's own secrets do.
            os.fsync(handle.fileno())
        os.link(temporary, path)
    except FileExistsError as exc:
        existing = _read_file(path)
        if existing is not None and existing.strip() == value:
            return False
        raise Refusal(f"{path} holds another value; not overwriting it") from exc
    except OSError as exc:
        raise Refusal(f"cannot write {path}") from exc
    finally:
        Path(temporary).unlink(missing_ok=True)
    return True


def verify(project_root: Path, home: Path) -> None:
    env_file = project_root / ".env"
    text = _read_env_text(env_file, required=False)
    directory = _resolve_directory(text, env_file, home)
    for declared in _declared_files(project_root):
        entry = TABLE_BY_NAME.get(declared.name)
        if declared.parent == directory and entry is None:
            raise Refusal(f"{declared} is declared but is not a secret file this stack knows")
        if entry is None:
            continue
        if declared.parent != directory:
            raise Refusal(
                f"{entry.name} is declared in {declared.parent}, but the secrets "
                f"directory is {directory}",
            )
        _judge(entry, declared, _env_value(text, entry, env_file))


def _judge(entry: SecretFile, declared: Path, env_value: str | None) -> None:
    content = _read_file(declared)  # refuses a linked file or directory
    if content is None:
        raise Refusal(f"{declared} is declared but missing; copy it from {entry.key}")
    value = content.strip()
    if not value and not entry.optional:
        raise Refusal(f"{declared} is empty")
    if env_value is not None and value != env_value:
        raise Refusal(f"{declared} differs from {entry.key} in .env")


def _declared_files(project_root: Path) -> list[Path]:
    """Compose's resolved ``secrets.*.file`` paths; its output stays in memory."""
    try:
        completed = subprocess.run(  # noqa: S603 - a fixed argument list
            CONFIG_COMMAND, cwd=project_root, capture_output=True, check=False,
        )
    except OSError as exc:
        raise Refusal("cannot run docker compose config") from exc
    if completed.returncode != 0:
        raise Refusal(f"docker compose config failed with exit code {completed.returncode}")
    try:
        secrets = json.loads(completed.stdout).get("secrets") or {}
        return [Path(secret["file"]) for secret in secrets.values() if "file" in secret]
    except (ValueError, TypeError, AttributeError, KeyError) as exc:
        raise Refusal("docker compose config printed no readable secrets block") from exc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
