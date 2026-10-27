#!/usr/bin/env python3
"""Give Grafana a strong admin password the operator never has to know (#1359).

Usage, once, from the main checkout with the stack running:

    ./scripts/grafana_password.py

1. If ``.env`` has no ``GRAFANA_PASSWORD``, an empty one, or a publicly known
   one (``admin``, anything starting with ``CHANGEME``), a fresh random value
   replaces that line (or is appended). Every other byte stays as it was;
   ``.env`` keeps its owner and mode.
2. Either way the ``.env`` value is applied to the running Grafana through
   ``grafana cli admin reset-admin-password --password-from-stdin``, so the real
   admin password is the ``.env`` one even when Grafana's database was created
   with admin/admin.
3. The apply counts only when Grafana says so explicitly AND an authenticated
   API call with the value succeeds: ``grafana cli`` can exit 0 without having
   changed anything. Only then does it print ``set`` (step 1 wrote a fresh
   value) or ``already set``.

The value travels only through this process's memory, the ``.env`` file and
the stdin of ``docker compose exec``. Nothing Grafana prints is ever replayed:
a failure names the step and whether ``.env`` changed, nothing more.
"""

from __future__ import annotations

import base64
import http.client
import ipaddress
import os
import secrets
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path

from dotenv_file import Assignment, DotenvError, effective_assignment
from main_checkout import CheckoutError, main_checkout_elsewhere

PASSWORD_KEY = "GRAFANA_PASSWORD"
USER_KEY = "GRAFANA_USER"
DEFAULT_ADMIN_USER = "admin"
PUBLICLY_KNOWN_PASSWORDS = frozenset({"", "admin"})
PUBLICLY_KNOWN_PREFIX = "CHANGEME"
FRESH_VALUE_BYTES = 32
GRAFANA_SERVICE = "grafana"
GRAFANA_CONTAINER_PORT = "3000"
APPLY_COMMAND = (
    "docker", "compose", "exec", "-T", GRAFANA_SERVICE,
    "grafana", "cli", "admin", "reset-admin-password", "--password-from-stdin",
)
PUBLISHED_PORT_COMMAND = ("docker", "compose", "port", GRAFANA_SERVICE, GRAFANA_CONTAINER_PORT)
APPLY_SUCCESS_LINE = "Admin password changed successfully ✔"
AUTHENTICATED_PATH = "/api/user"
API_TIMEOUT_SECONDS = 10
ENV_CHANGED = ".env now holds a fresh GRAFANA_PASSWORD"
ENV_UNCHANGED = ".env was not changed"


class Refusal(Exception):
    """Something this command will not do; the message is safe to print."""


@dataclass(frozen=True)
class Password:
    value: str
    is_fresh: bool


def main() -> int:
    if len(sys.argv) > 1:
        return _fail("takes no arguments; usage: ./scripts/grafana_password.py")
    repo_root = Path(__file__).resolve().parent.parent
    env_file = repo_root / ".env"
    try:
        _require_main_checkout(repo_root)
        env_text = _read_env_file(env_file)
        admin_user = _value_of(_assignment(env_text, USER_KEY, env_file)) or DEFAULT_ADMIN_USER
        password = _password_to_apply(env_text, env_file)
    except Refusal as refusal:
        return _fail(f"{refusal}; nothing was changed")
    env_state = ENV_CHANGED if password.is_fresh else ENV_UNCHANGED
    try:
        _apply_to_grafana(password.value, repo_root)
        _prove_grafana_accepts(admin_user, password.value, repo_root)
    except Refusal as refusal:
        return _fail(
            f"{refusal}; {env_state}. Start the stack (docker compose up -d) "
            f"and run this command again",
        )
    print("set" if password.is_fresh else "already set")
    return 0


def _fail(message: str) -> int:
    print(f"grafana_password.py: {message}", file=sys.stderr)
    return 1


def _require_main_checkout(repo_root: Path) -> None:
    """Compose names its project after the checkout, so only the main one is the stack."""
    try:
        main_checkout = main_checkout_elsewhere(repo_root)
    except CheckoutError as exc:
        raise Refusal(str(exc)) from exc
    if main_checkout is not None:
        raise Refusal(
            f"refusing to run from a linked worktree; run it from the main "
            f"checkout {main_checkout}",
        )


def _read_env_file(env_file: Path) -> str:
    try:
        mode = env_file.lstat().st_mode
    except FileNotFoundError as exc:
        raise Refusal(f"no .env at {env_file}") from exc
    if stat.S_ISLNK(mode):
        raise Refusal(
            f"{env_file} is a symlink; this command rewrites .env and will not "
            f"replace a link — keep the real file at that path",
        )
    if not stat.S_ISREG(mode):
        raise Refusal(f"{env_file} is not a regular file")
    try:
        return env_file.read_bytes().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise Refusal(f"{env_file} is not UTF-8") from exc


def _assignment(env_text: str, key: str, env_file: Path) -> Assignment | None:
    try:
        return effective_assignment(env_text, key, env_file)
    except DotenvError as exc:
        raise Refusal(str(exc)) from exc


def _value_of(assignment: Assignment | None) -> str:
    return assignment.value if assignment else ""


def _password_to_apply(env_text: str, env_file: Path) -> Password:
    assignment = _assignment(env_text, PASSWORD_KEY, env_file)
    current = _value_of(assignment)
    if not _is_publicly_known(current):
        return Password(current, is_fresh=False)
    fresh = secrets.token_hex(FRESH_VALUE_BYTES)
    _write_env_file(env_file, _with_password(env_text, assignment, fresh))
    return Password(fresh, is_fresh=True)


def _is_publicly_known(value: str) -> bool:
    return value in PUBLICLY_KNOWN_PASSWORDS or value.startswith(PUBLICLY_KNOWN_PREFIX)


def _with_password(env_text: str, assignment: Assignment | None, value: str) -> str:
    """``env_text`` with the key's effective line replaced, or the key appended."""
    new_line = f"{PASSWORD_KEY}={value}"
    lines = env_text.splitlines(keepends=True)
    if assignment is None:
        separator = "" if not env_text or env_text.endswith("\n") else "\n"
        return env_text + separator + new_line + "\n"
    replaced = lines[assignment.line_index]
    line_ending = replaced[len(replaced.rstrip("\r\n")):]
    lines[assignment.line_index] = new_line + line_ending
    return "".join(lines)


def _write_env_file(env_file: Path, text: str) -> None:
    """Swap in the new content atomically, carrying the old file's owner and mode."""
    original = env_file.stat()
    descriptor, temp_name = tempfile.mkstemp(
        dir=env_file.parent, prefix=".env.grafana-password.",
    )
    try:
        with os.fdopen(descriptor, "wb") as temp_file:
            temp_file.write(text.encode("utf-8"))
            temp_file.flush()
            os.fchown(temp_file.fileno(), original.st_uid, original.st_gid)
            os.fchmod(temp_file.fileno(), stat.S_IMODE(original.st_mode))
            os.fsync(temp_file.fileno())
        os.replace(temp_name, env_file)
    except OSError as exc:
        raise Refusal(f"could not rewrite {env_file} ({exc.strerror})") from exc
    finally:
        Path(temp_name).unlink(missing_ok=True)


def _apply_to_grafana(value: str, repo_root: Path) -> None:
    applied = _run_docker(APPLY_COMMAND, repo_root, stdin=value + "\n")
    if applied is None or applied.returncode != 0:
        raise Refusal("applying GRAFANA_PASSWORD to the running Grafana failed")
    if APPLY_SUCCESS_LINE not in (line.strip() for line in applied.stdout.splitlines()):
        raise Refusal("Grafana did not confirm the new admin password")


def _prove_grafana_accepts(admin_user: str, value: str, repo_root: Path) -> None:
    host, port = _published_grafana_address(repo_root)
    credentials = base64.b64encode(f"{admin_user}:{value}".encode()).decode("ascii")
    connection = http.client.HTTPConnection(host, port, timeout=API_TIMEOUT_SECONDS)
    try:
        connection.request(
            "GET", AUTHENTICATED_PATH, headers={"Authorization": f"Basic {credentials}"},
        )
        status = connection.getresponse().status
    except (OSError, http.client.HTTPException) as exc:
        raise Refusal("logging in to Grafana's API to prove the password failed") from exc
    finally:
        connection.close()
    if status != HTTPStatus.OK:
        raise Refusal(f"Grafana's API rejected the password it just confirmed (HTTP {status})")


def _published_grafana_address(repo_root: Path) -> tuple[str, int]:
    """Where compose published Grafana — refused unless it is this machine's loopback.

    The proof sends the password over plain HTTP, so it may only ever leave
    through the loopback interface.
    """
    published = _run_docker(PUBLISHED_PORT_COMMAND, repo_root)
    if published is None or published.returncode != 0:
        raise Refusal("finding Grafana's published port failed")
    host, _, port = published.stdout.strip().partition("\n")[0].rpartition(":")
    try:
        address = ipaddress.ip_address(host.strip("[]"))
        port_number = int(port)
    except ValueError as exc:
        raise Refusal("Grafana's published port is not an address this command reads") from exc
    if address.is_unspecified:
        address = ipaddress.ip_address("::1" if address.version == 6 else "127.0.0.1")
    if not address.is_loopback:
        raise Refusal(
            "Grafana is not published on loopback, and the API proof sends the "
            "password nowhere else",
        )
    return str(address), port_number


def _run_docker(
    command: tuple[str, ...], repo_root: Path, stdin: str | None = None,
) -> subprocess.CompletedProcess[str] | None:
    """Run a docker command in the checkout, its output kept for checks and never shown."""
    try:
        return subprocess.run(
            command, input=stdin, capture_output=True, encoding="utf-8", errors="replace",
            cwd=repo_root, check=False,
        )
    except OSError:
        return None


if __name__ == "__main__":
    raise SystemExit(main())
