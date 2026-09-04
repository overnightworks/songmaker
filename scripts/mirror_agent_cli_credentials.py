#!/usr/bin/env python3
"""Mirror the agent CLI logins to the copies the containers are allowed to read.

Issue #350. Three problems are solved by the same file.

**Ownership.** The operator's machine is the only owner of these credentials.
Only the CLIs running there may renew a token, so the mirror publishes the
short-lived access token and *never* the renewal secret: a container that is
taken over can spend what it holds until it expires, but it cannot mint a new
one, and the refresh token — good for weeks — never leaves the host. What each
provider tolerates was measured, not assumed; see the redaction table below.

**Why a copy at all.** These CLIs replace their credential file atomically:
write a temporary file, rename it over the old one. A file bind-mount is
pinned to the inode it was made from and does not follow that rename, so a
read-only mount of the real file would serve the token that was current when
the container started, forever, and the co-writer would die at the operator's
next refresh. The mirror therefore writes IN PLACE — one write into the
existing inode, never a rename — so the mount keeps pointing at what we wrote.

**Not being a foothold itself.** Every path is opened without following
symlinks and checked while open (regular file, our own uid, one link only),
so nothing that appears between the check and the write can redirect it.

On tearing: the file is never truncated (shorter content is padded with
trailing spaces, which JSON ignores) and the payload is written from offset
zero, so a reader never sees a short document. On Linux, ext4 and xfs
serialise a buffered ``write()`` against a concurrent ``read()`` on the same
inode, so a reader there sees either all of the old bytes or all of the new
ones. That is a property of those filesystems and of a *completed* write, not
a universal guarantee: a short write is retried and verified below, and a
reader using ``mmap`` or several reads can still straddle the change. The
consequence of losing that race is one CLI invocation reporting a parse error
and the next one succeeding, which is why it is worth stating rather than
hiding.

A missing source is a real answer, not an error: the operator is simply not
signed in to that CLI, and the mirror says so with an empty JSON object. A
source that exists but does not parse, or that fails a safety check, is an
error — it is left un-mirrored, the previous good copy stays in place, and
this script exits non-zero so systemd records the failure.
"""

from __future__ import annotations

import argparse
import errno
import fcntl
import json
import os
import re
import stat
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

MIRROR_DIR_MODE = 0o700
MIRROR_FILE_MODE = 0o600
LOCK_NAME = ".mirror.lock"
# Long enough to outlast a concurrent run of this same script (it copies three
# small files), short enough that a stuck holder fails the unit rather than
# hanging systemd's start.
LOCK_WAIT_SECONDS = 30
LOCK_POLL_SECONDS = 0.2

# A login document is a few kilobytes. The cap is what keeps a source that has
# been replaced by something enormous from being read into memory at all.
SOURCE_READ_LIMIT_BYTES = 256 * 1024

# Valid JSON that carries no login. What the CLI makes of it is what we want it
# to make of it: not signed in.
SIGNED_OUT = b"{}"


class MirrorError(Exception):
    """A source or target is not what it must be, so nothing is written."""


# ── what each provider's document may carry into a container ───────────
#
# Measured on 2026-09-02 against the mounted CLIs, each variant run in a
# throwaway container with the candidate document mounted read-only.
#
# Claude takes an ALLOWLIST: `accessToken` plus `scopes` is the whole
# requirement — dropping `scopes` alone flips `claude auth status` to
# loggedIn:false — and `expiresAt` is kept only as a freshness signal for a
# human debugging the mount. Nothing else is copied, so nothing else can leak,
# and a field Anthropic adds tomorrow is simply not carried.
#
# Grok and Codex cannot take an allowlist that ignores the rest: both
# deserialise into structs whose fields are required, and dropping
# `create_time` alone already yields "You are not authenticated". So their
# whole document is carried — and that is exactly why an unknown field must be
# a LOUD FAILURE rather than a silent copy. A CLI update that introduces
# `device_refresh_token` would otherwise ride into the container unnoticed.
# The lists below are the measured field set of each provider; anything
# outside them stops the mirror with a named error the operator sees.

CLAUDE_ALLOWED_FIELDS: Final = ("accessToken", "expiresAt", "scopes")
# Measured: without `scopes` the CLI reports loggedIn:false. A document that
# cannot drive the CLI must not replace the last one that could.
CLAUDE_REQUIRED_FIELDS: Final = frozenset({"accessToken", "scopes"})

# Kept because the CLI needs them, blanked because they renew or authorise on
# their own, dropped because they are the operator's person and no CLI misses
# them (all three measured).
GROK_ALLOWED_FIELDS: Final = frozenset({
    "key", "auth_mode", "create_time", "expires_at", "user_id", "team_id",
    "principal_type", "principal_id", "oidc_issuer", "oidc_client_id",
    "coding_data_retention_opt_out",
})
GROK_BLANKED_FIELDS: Final = frozenset({"refresh_token"})
GROK_DROPPED_FIELDS: Final = frozenset({
    "email", "first_name", "last_name", "profile_image_asset_id",
})
# Everything its CLI needs. Measured: dropping `create_time` alone already
# yields "You are not authenticated".
GROK_REQUIRED_FIELDS: Final = GROK_ALLOWED_FIELDS | GROK_BLANKED_FIELDS

CODEX_ALLOWED_FIELDS: Final = frozenset({"auth_mode", "last_refresh"})
CODEX_NULLED_FIELDS: Final = frozenset({"OPENAI_API_KEY"})
CODEX_TOKEN_ALLOWED_FIELDS: Final = frozenset({"id_token", "access_token", "account_id"})
CODEX_TOKEN_BLANKED_FIELDS: Final = frozenset({"refresh_token"})
# Measured: absent `refresh_token` is "missing field `refresh_token`", and a
# blanked `id_token` is "invalid ID token format".
CODEX_REQUIRED_FIELDS: Final = frozenset({"auth_mode", "tokens"})
CODEX_TOKEN_REQUIRED_FIELDS: Final = frozenset(
    {"id_token", "access_token", "account_id", "refresh_token"},
)


def _reject_unknown(fields: Iterable[str], known: frozenset[str], where: str) -> None:
    """Fail closed. An unrecognised field is a secret we cannot rule out."""
    unknown = sorted(set(fields) - known)
    if unknown:
        raise MirrorError(
            f"{where} carries field(s) this mirror has never seen: "
            f"{', '.join(unknown)}. Until each is measured and listed as kept, "
            f"blanked or dropped, nothing is published — a field that renews a "
            f"login must not reach a container by default",
        )


def _require_present(fields: Iterable[str], required: frozenset[str], where: str) -> None:
    """The other half of fail-closed: a field we measured as needed is needed.

    Publishing a document the CLI cannot use would replace the last good copy
    with an unusable one — the CLI would report itself signed out and nobody
    would know why. Missing means: stop, and leave what is there.
    """
    missing = sorted(required - set(fields))
    if missing:
        raise MirrorError(
            f"{where} is missing field(s) its CLI needs: {', '.join(missing)}",
        )


def _redact_claude(document: dict) -> dict:
    oauth = document.get("claudeAiOauth")
    if not isinstance(oauth, dict):
        raise MirrorError("claude credentials have no claudeAiOauth object")
    _require_present(oauth, CLAUDE_REQUIRED_FIELDS, "claude credentials")
    return {"claudeAiOauth": {k: oauth[k] for k in CLAUDE_ALLOWED_FIELDS if k in oauth}}


def _redact_grok(document: dict) -> dict:
    published = {}
    for realm, entry in document.items():
        if not isinstance(entry, dict):
            raise MirrorError(f"grok realm {realm!r} is not an object")
        where = f"grok realm {realm!r}"
        _reject_unknown(
            entry,
            GROK_ALLOWED_FIELDS | GROK_BLANKED_FIELDS | GROK_DROPPED_FIELDS,
            where,
        )
        _require_present(entry, GROK_REQUIRED_FIELDS, where)
        published[realm] = {
            key: ("" if key in GROK_BLANKED_FIELDS else value)
            for key, value in entry.items()
            if key not in GROK_DROPPED_FIELDS
        }
    return published


def _redact_codex(document: dict) -> dict:
    _reject_unknown(
        document,
        CODEX_ALLOWED_FIELDS | CODEX_NULLED_FIELDS | {"tokens"},
        "codex credentials",
    )
    _require_present(document, CODEX_REQUIRED_FIELDS, "codex credentials")
    tokens = document.get("tokens")
    if not isinstance(tokens, dict):
        raise MirrorError("codex credentials have no tokens object")
    _reject_unknown(
        tokens,
        CODEX_TOKEN_ALLOWED_FIELDS | CODEX_TOKEN_BLANKED_FIELDS,
        "codex tokens",
    )
    _require_present(tokens, CODEX_TOKEN_REQUIRED_FIELDS, "codex tokens")
    published = {
        key: (None if key in CODEX_NULLED_FIELDS else value)
        for key, value in document.items()
        if key != "tokens"
    }
    published["tokens"] = {
        key: ("" if key in CODEX_TOKEN_BLANKED_FIELDS else value)
        for key, value in tokens.items()
    }
    return published


@dataclass(frozen=True)
class MirroredCredential:
    """One CLI login: where the operator's CLI keeps it, what the copy is called."""

    cli: str
    source: Path
    mirror_name: str
    redact: Callable[[dict], dict]


def credentials(home: Path) -> tuple[MirroredCredential, ...]:
    return (
        MirroredCredential(
            "claude", home / ".claude/.credentials.json", "claude.json", _redact_claude,
        ),
        MirroredCredential("grok", home / ".grok/auth.json", "grok.json", _redact_grok),
        MirroredCredential("codex", home / ".codex/auth.json", "codex.json", _redact_codex),
    )


# ── where the mirror lives ─────────────────────────────────────────


MIRROR_DIR_KEY: Final = "SONGMAKER_CLI_CREDENTIALS_DIR"


def resolve_mirror_directory(project_root: Path, home: Path) -> Path:
    """The one answer to "where do the mirrors live", in compose's own order.

    An exported variable wins, then the same key in ``.env``, then the default
    under the stack owner's home — exactly how compose resolves it, so this
    answer and the directory compose mounts cannot be different ones.

    The configuration is deliberately narrow rather than a half-imitation of
    dotenv: an absolute path or ``~/…``, with no whitespace and no ``%``. The
    autodeploy installer rejects the same two characters for the same reason —
    systemd splits directive values on whitespace and expands ``%`` as a
    specifier, so a path containing either cannot be embedded in a unit at all.
    A value we cannot honour exactly is refused loudly instead of being
    silently mangled.
    """
    if MIRROR_DIR_KEY in os.environ:
        # Exported, even empty, wins — and compose's `${VAR:-default}` treats
        # an empty value as "take the default", so this does too.
        configured = os.environ[MIRROR_DIR_KEY]
    else:
        configured = _mirror_dir_from_env_file(project_root / ".env")
    if not configured:
        return home / ".songmaker/agent-cli-credentials"
    return _validated_mirror_directory(configured, home)


def _mirror_dir_from_env_file(env_file: Path) -> str:
    """The key's value from ``.env``, read as Compose reads it — or refused.

    Compose's dotenv accepts ``KEY=value`` and ``KEY: value``, an optional
    ``export`` prefix, single quotes (literal), double quotes (with escapes and
    interpolation), and — for UNQUOTED values only — a trailing ``#`` comment
    that must be preceded by whitespace. ``/srv/creds#blue`` is therefore a
    path, not a truncation.

    This reads a deliberate SUBSET of that: no escapes, no interpolation.
    Anything outside the subset is refused by name rather than guessed at,
    because guessing differently from Compose is precisely how a check passes
    for a directory nobody mounts.
    """
    try:
        lines = env_file.read_text().splitlines()
    except OSError:
        return ""
    value = ""
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, separator, raw = _split_assignment(stripped)
        if not separator or key != MIRROR_DIR_KEY:
            continue
        value = _dotenv_value(raw, env_file)
    return value


def _split_assignment(line: str) -> tuple[str, str, str]:
    """``KEY=v``, ``KEY: v`` and an optional ``export`` prefix, as Compose does."""
    if line.startswith("export "):
        line = line[len("export "):].lstrip()
    equals, colon = line.find("="), line.find(":")
    if equals == -1 and colon == -1:
        return "", "", ""
    if equals != -1 and (colon == -1 or equals < colon):
        key, separator, raw = line.partition("=")
    else:
        key, separator, raw = line.partition(":")
    return key.strip(), separator, raw


def _dotenv_value(raw: str, env_file: Path) -> str:
    """One assignment's value: quotes honoured, comments only where Compose has them."""
    raw = raw.strip()
    for quote in ('"', "'"):
        if raw.startswith(quote):
            closing = raw.find(quote, 1)
            if closing == -1:
                raise MirrorError(f"{env_file}: {MIRROR_DIR_KEY} has an unclosed quote")
            inner = raw[1:closing]
            if quote == '"' and "\\" in inner:
                raise MirrorError(
                    f"{env_file}: {MIRROR_DIR_KEY} uses a backslash escape. This "
                    f"reader does not process escapes, and guessing differently "
                    f"from Compose would point the mirror somewhere else — write "
                    f"the path without escapes",
                )
            if "$" in inner:
                raise MirrorError(
                    f"{env_file}: {MIRROR_DIR_KEY} uses interpolation. This "
                    f"reader does not interpolate — write the path out in full",
                )
            trailing = raw[closing + 1:].strip()
            if trailing and not trailing.startswith("#"):
                raise MirrorError(
                    f"{env_file}: {MIRROR_DIR_KEY} has trailing text after its "
                    f"quoted value: {trailing!r}",
                )
            return inner
    # Unquoted: a '#' only starts a comment when whitespace precedes it, which
    # is what keeps '/srv/creds#blue' a path.
    comment = re.search(r"\s#", raw)
    if comment:
        raw = raw[: comment.start()]
    if "$" in raw:
        raise MirrorError(
            f"{env_file}: {MIRROR_DIR_KEY} uses interpolation. This reader does "
            f"not interpolate — write the path out in full",
        )
    return raw.strip()


def _validated_mirror_directory(configured: str, home: Path) -> Path:
    if any(character.isspace() for character in configured) or "%" in configured:
        raise MirrorError(
            f"{MIRROR_DIR_KEY} must not contain whitespace or '%', got "
            f"{configured!r}: systemd splits unit directives on whitespace and "
            f"expands '%' as a specifier, so such a path cannot be installed",
        )
    if configured.startswith("~/"):
        return home / configured[2:]
    if not configured.startswith("/"):
        raise MirrorError(
            f"{MIRROR_DIR_KEY} must be an absolute path or ~/…, got {configured!r}",
        )
    return Path(configured)


# ── opening things that cannot have been swapped underneath us ─────────


def _checked(descriptor: int, what: str) -> os.stat_result:
    info = os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode):
        raise MirrorError(f"{what} is not a regular file")
    if info.st_uid != os.getuid():
        raise MirrorError(f"{what} is owned by uid {info.st_uid}, not by us")
    if info.st_nlink != 1:
        raise MirrorError(f"{what} has {info.st_nlink} hard links; it must have exactly one")
    return info


def read_source(source: Path) -> bytes:
    """The login as the CLI left it, or the signed-out answer when there is none."""
    try:
        descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return SIGNED_OUT
    except OSError as exc:
        raise MirrorError(f"{source} could not be opened safely: {exc}") from exc
    try:
        info = _checked(descriptor, str(source))
        if info.st_size > SOURCE_READ_LIMIT_BYTES:
            raise MirrorError(
                f"{source} is {info.st_size} bytes, more than the "
                f"{SOURCE_READ_LIMIT_BYTES} a login document may be",
            )
        return os.read(descriptor, SOURCE_READ_LIMIT_BYTES)
    finally:
        os.close(descriptor)


def prepare_mirror_directory(mirror_directory: Path) -> None:
    """Create it already private, and refuse anything that is not ours."""
    # Parents first, then the directory itself with its mode set at creation.
    # `~/.songmaker` need not exist yet, and creating only the last segment is
    # how the default path failed on a machine that had never seen it.
    # The parents are ordinary directories; only this one must be private, and
    # it is created private rather than chmodded afterwards, so there is no
    # moment in which it is readable by anyone else.
    mirror_directory.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.mkdir(mirror_directory, MIRROR_DIR_MODE)  # NOSONAR: validated absolute target
    except FileExistsError:
        pass
    info = mirror_directory.lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise MirrorError(f"{mirror_directory} is not a directory")
    if info.st_uid != os.getuid():
        raise MirrorError(f"{mirror_directory} is owned by uid {info.st_uid}, not by us")
    if stat.S_IMODE(info.st_mode) != MIRROR_DIR_MODE:
        raise MirrorError(
            f"{mirror_directory} is mode {stat.S_IMODE(info.st_mode):04o}, "
            f"not {MIRROR_DIR_MODE:04o}",
        )


def write_in_place(path: Path, payload: bytes) -> None:
    """Replace the file's content without replacing the file.

    Never truncates and never renames: either would break the container's
    mount. See this module's docstring for what that does and does not
    guarantee a concurrent reader.
    """
    if len(payload) > SOURCE_READ_LIMIT_BYTES:
        raise MirrorError(
            f"{path} payload is {len(payload)} bytes, more than the "
            f"{SOURCE_READ_LIMIT_BYTES} a login document may be",
        )
    # O_RDWR, not O_WRONLY: the write is read back through this same
    # descriptor, so no second open can be pointed somewhere else.
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, MIRROR_FILE_MODE)
    try:
        info = _checked(descriptor, str(path))
        # The existing size decides how much padding is written, so it is not
        # taken on trust: a target that had somehow grown would otherwise pull
        # a payload that size into memory and back onto disk on every run.
        if info.st_size > SOURCE_READ_LIMIT_BYTES:
            raise MirrorError(
                f"{path} is already {info.st_size} bytes, more than the "
                f"{SOURCE_READ_LIMIT_BYTES} a login document may be",
            )
        os.fchmod(descriptor, MIRROR_FILE_MODE)
        padded = payload.ljust(info.st_size)
        _write_all(descriptor, padded, path)
        os.fsync(descriptor)
        _verify(descriptor, padded, path)
    finally:
        os.close(descriptor)


def _write_all(descriptor: int, payload: bytes, path: Path) -> None:
    written = 0
    while written < len(payload):
        just_written = os.pwrite(descriptor, payload[written:], written)
        if just_written == 0:
            raise MirrorError(f"{path} accepted no bytes at offset {written}")
        written += just_written


def _verify(descriptor: int, payload: bytes, path: Path) -> None:
    """Read the file back through the same descriptor and insist it matches.

    A short write is retried above, which is exactly the moment a reader could
    have seen a mixed document. Confirming the final bytes is what turns that
    from a silent possibility into either a correct file or a loud failure.
    """
    read_back = os.pread(descriptor, len(payload) + 1, 0)
    if read_back != payload:
        raise MirrorError(
            f"{path} holds {len(read_back)} bytes that differ from the "
            f"{len(payload)} we wrote",
        )


def mirror_one(credential: MirroredCredential, mirror_directory: Path) -> str:
    target = mirror_directory / credential.mirror_name
    payload = read_source(credential.source)
    if payload == SIGNED_OUT:
        write_in_place(target, SIGNED_OUT)
        return "signed out"
    document = json.loads(payload)
    if not isinstance(document, dict):
        raise MirrorError(f"{credential.source} is not a JSON object")
    write_in_place(target, json.dumps(credential.redact(document)).encode())
    return "signed in, renewal secret withheld"


def mirror(home: Path, mirror_directory: Path) -> int:
    prepare_mirror_directory(mirror_directory)
    failures = 0
    for credential in credentials(home):
        target = mirror_directory / credential.mirror_name
        try:
            state = mirror_one(credential, mirror_directory)
        except (MirrorError, OSError, ValueError) as exc:
            print(
                f"{credential.cli}: {exc} — leaving {target} as it was",
                file=sys.stderr,
            )
            failures += 1
            continue
        print(f"{credential.cli}: {state} -> {target}")
    return failures


# ── verifying what is about to be mounted ──────────────────────────
#
# The preflight (scripts/check_agent_cli_mounts.sh) calls this rather than
# re-implementing it in shell: one check, two callers. A shell `test -f` plus
# a grep promises less than it claims — it follows symlinks, cannot see the
# owner or the link count, and does not know JSON.


def verify_mirror_file(path: Path, cli: str) -> None:
    """Refuse anything a container must not be handed.

    Same file discipline as writing (no symlink followed, checked while open,
    ours, one link), plus the invariant the whole arrangement exists for: the
    document must parse, and it must carry no renewal secret. A hand-copied
    login would otherwise undo that quietly.
    """
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError as exc:
        raise MirrorError(
            f"{path} is missing — run this script, or start "
            f"songmaker-cli-credentials-mirror.service, before deploying",
        ) from exc
    except OSError as exc:
        raise MirrorError(f"{path} could not be opened safely: {exc}") from exc
    try:
        info = _checked(descriptor, str(path))
        if stat.S_IMODE(info.st_mode) != MIRROR_FILE_MODE:
            raise MirrorError(
                f"{path} is mode {stat.S_IMODE(info.st_mode):04o}, "
                f"not {MIRROR_FILE_MODE:04o}",
            )
        # The size is checked, not just the read capped. Reading the first
        # 256 KiB and judging that would clear a file whose first bytes are
        # valid JSON and whose remainder — a renewal token, anything — was
        # never looked at.
        if info.st_size > SOURCE_READ_LIMIT_BYTES:
            raise MirrorError(
                f"{path} is {info.st_size} bytes, more than the "
                f"{SOURCE_READ_LIMIT_BYTES} a login document may be, so it "
                f"cannot be judged in full",
            )
        payload = os.read(descriptor, SOURCE_READ_LIMIT_BYTES)
    finally:
        os.close(descriptor)
    try:
        document = json.loads(payload)
    except ValueError as exc:
        raise MirrorError(f"{path} is not a JSON document: {exc}") from exc
    if not isinstance(document, dict):
        raise MirrorError(f"{path} is not a JSON object")
    _reject_renewal_secrets(document, cli, path)


def _is_renewal_token_field(key: str) -> bool:
    """`refresh_token`, `refreshToken`, `device_refresh_token` — not `last_refresh`.

    Keyed on the word pair, not on "refresh" alone: a timestamp called
    `last_refresh` is not a credential, and treating it as one would make this
    check cry wolf until someone switched it off. Names that carry a renewal
    secret without saying "refresh token" are caught a layer earlier, where an
    unknown field stops the mirror outright.
    """
    return "refreshtoken" in "".join(c for c in key.lower() if c.isalnum())


def _reject_renewal_secrets(node: object, cli: str, path: Path) -> None:
    """No key that names a renewal token may carry a value. Anywhere."""
    if isinstance(node, dict):
        for key, value in node.items():
            if _is_renewal_token_field(key) and value not in ("", None, [], {}):
                raise MirrorError(
                    f"{path} still carries a renewal token in {key!r}. Re-run "
                    f"this script; never copy a {cli} login into the mirror by "
                    f"hand",
                )
            _reject_renewal_secrets(value, cli, path)
    elif isinstance(node, list):
        for item in node:
            _reject_renewal_secrets(item, cli, path)


def verify(mirror_directory: Path) -> int:
    failures = 0
    for credential in credentials(Path.home()):
        target = mirror_directory / credential.mirror_name
        try:
            verify_mirror_file(target, credential.cli)
        except MirrorError as exc:
            print(f"{credential.cli}: {exc}", file=sys.stderr)
            failures += 1
            continue
        print(f"{credential.cli}: {target} is mounted-safe, no renewal token in it")
    return failures


def main() -> int:
    home = Path.home()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--mirror-dir",
        type=Path,
        default=None,
        help="where the container-readable copies live (resolved when omitted)",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="the checkout whose .env may name the mirror directory",
    )
    parser.add_argument(
        "--print-mirror-dir",
        action="store_true",
        help="print the resolved mirror directory and exit",
    )
    parser.add_argument(
        "--home",
        type=Path,
        default=home,
        help="whose CLI logins to mirror (the invoking user's home by default)",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="check what is already mirrored instead of writing it",
    )
    arguments = parser.parse_args()

    try:
        if arguments.mirror_dir is None:
            arguments.mirror_dir = resolve_mirror_directory(
                arguments.project_root, arguments.home,
            )
    except MirrorError as exc:
        print(f"{exc}", file=sys.stderr)
        return 2

    if arguments.print_mirror_dir:
        print(arguments.mirror_dir)
        return 0

    if arguments.verify:
        return 1 if verify(arguments.mirror_dir) else 0

    try:
        prepare_mirror_directory(arguments.mirror_dir)
        lock = os.open(
            arguments.mirror_dir / LOCK_NAME, os.O_WRONLY | os.O_CREAT, MIRROR_FILE_MODE,
        )
    except (MirrorError, OSError) as exc:
        print(f"mirror directory unusable: {exc}", file=sys.stderr)
        return 1
    try:
        _take_lock(lock)
        return 1 if mirror(arguments.home, arguments.mirror_dir) else 0
    except MirrorError as exc:
        print(f"{exc}", file=sys.stderr)
        return 1
    finally:
        os.close(lock)


def _take_lock(lock: int) -> None:
    """Wait for the lock, and treat only contention as something to wait out.

    Standing down on *any* flock error was wrong: a run that could not take the
    lock for some other reason would report success without having mirrored,
    and the stack would then start on stale files. Contention is waited out
    within a deadline; running out of that deadline, or any other error, is a
    failure the unit must show.
    """
    deadline = time.monotonic() + LOCK_WAIT_SECONDS
    while True:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except OSError as exc:
            if exc.errno not in (errno.EAGAIN, errno.EACCES):
                raise MirrorError(f"could not lock the mirror: {exc}") from exc
            if time.monotonic() >= deadline:
                raise MirrorError(
                    f"another mirror run held the lock for more than "
                    f"{LOCK_WAIT_SECONDS}s; nothing was mirrored",
                ) from exc
            time.sleep(LOCK_POLL_SECONDS)


if __name__ == "__main__":
    raise SystemExit(main())
