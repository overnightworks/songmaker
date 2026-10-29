"""Owner-scoped reference-audio path resolution."""

from __future__ import annotations

import hashlib
import logging
import os
import stat
import uuid
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from sqlalchemy.orm import Session, sessionmaker

from songmaker_cli.api_helpers import _begin_exclusive
from songmaker_cli.constants import REFERENCE_AUDIO_DIR, REFERENCE_AUDIO_EXTENSIONS
from songmaker_cli.db.models import User
from songmaker_cli.settings import Settings

REFERENCE_AUDIO_NOT_OWNED_DETAIL: Final = "reference audio path is not owned"


class ReferenceAudioRejected(ValueError):
    pass


def owner_reference_audio_root(audio_dir: Path, user_id: str) -> Path:
    return audio_dir / user_id / REFERENCE_AUDIO_DIR


def resolve_owned_reference_audio(
    audio_dir: Path,
    user_id: str,
    stored_relative: str,
) -> Path:
    if not stored_relative or stored_relative.startswith("/") or ".." in stored_relative:
        raise ReferenceAudioRejected(REFERENCE_AUDIO_NOT_OWNED_DETAIL)
    root = owner_reference_audio_root(audio_dir, user_id).resolve()
    raw = audio_dir / stored_relative
    if raw.is_symlink():
        raise ReferenceAudioRejected(REFERENCE_AUDIO_NOT_OWNED_DETAIL)
    candidate = raw.resolve()
    if not candidate.is_relative_to(root):
        raise ReferenceAudioRejected(REFERENCE_AUDIO_NOT_OWNED_DETAIL)
    if not candidate.is_file():
        raise ReferenceAudioRejected(REFERENCE_AUDIO_NOT_OWNED_DETAIL)
    if candidate.suffix.lower() not in REFERENCE_AUDIO_EXTENSIONS:
        raise ReferenceAudioRejected(REFERENCE_AUDIO_NOT_OWNED_DETAIL)
    return candidate


REFERENCE_AUDIO_QUOTA_DETAIL: Final = "Reference audio storage limit reached."
REFERENCE_AUDIO_STORAGE_DETAIL: Final = "Reference audio storage could not be checked."
_REFERENCE_LOCK_NAMESPACE: Final = "songmaker.reference-audio:"
log = logging.getLogger(__name__)


class ReferenceAudioQuotaExceeded(ValueError):
    pass


class ReferenceAudioStorageError(OSError):
    pass


def _lock_reference_owner(session: Session, user_id: str) -> None:
    """All reference admission and future cleanup must hold this owner lock."""
    digest = hashlib.sha256((_REFERENCE_LOCK_NAMESPACE + user_id).encode()).digest()
    lock_id = int.from_bytes(digest[:8], "big", signed=True)
    _begin_exclusive(session, lock_id)
    if session.get(User, user_id) is None:
        raise ReferenceAudioStorageError("missing owner")


def resolve_owned_reference_audio_under_lock(
    session: Session, audio_dir: Path, user_id: str, stored_relative: str,
) -> Path:
    """Take the owner lock, then resolve: the lock lasts until the caller commits."""
    _lock_reference_owner(session, user_id)
    return resolve_owned_reference_audio(audio_dir, user_id, stored_relative)


def _reference_directory(stack: ExitStack, audio_dir: Path, user_id: str) -> int:
    if Path(user_id).name != user_id or user_id in {"", ".", ".."}:
        raise ReferenceAudioStorageError("invalid owner")
    root = owner_reference_audio_root(audio_dir.absolute(), user_id)
    descriptor = os.open(root.anchor, os.O_RDONLY | os.O_DIRECTORY)
    stack.callback(os.close, descriptor)
    for part in root.parts[1:]:
        try:
            os.mkdir(part, dir_fd=descriptor)
        except FileExistsError:
            mode = os.stat(part, dir_fd=descriptor, follow_symlinks=False).st_mode
            if not stat.S_ISDIR(mode):
                kind = "symlink ancestor" if stat.S_ISLNK(mode) else "non-directory ancestor"
                raise ReferenceAudioStorageError(kind) from None
        descriptor = os.open(
            part,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=descriptor,
        )
        stack.callback(os.close, descriptor)
    return descriptor


@dataclass(frozen=True)
class _ReferenceUsage:
    files: int
    bytes: int


def _reference_usage(directory: int) -> _ReferenceUsage:
    count, size = 0, 0
    with os.scandir(directory) as entries:
        for entry in entries:
            metadata = entry.stat(follow_symlinks=False)
            if not stat.S_ISREG(metadata.st_mode):
                kind = "symlink" if stat.S_ISLNK(metadata.st_mode) else "nonregular entry"
                raise ReferenceAudioStorageError(kind)
            try:
                descriptor = os.open(
                    entry.name,
                    os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                    dir_fd=directory,
                )
            except OSError as exc:
                raise ReferenceAudioStorageError("unreadable regular entry") from exc
            try:
                metadata = os.fstat(descriptor)
                if not stat.S_ISREG(metadata.st_mode):
                    raise ReferenceAudioStorageError("nonregular entry")
                size += metadata.st_size
                count += 1
            finally:
                os.close(descriptor)
    return _ReferenceUsage(count, size)


def _write_reference(directory: int, name: str, content: bytes) -> None:
    descriptor = os.open(
        name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
        dir_fd=directory,
    )
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
    except BaseException:
        os.unlink(name, dir_fd=directory)
        raise


def store_reference_audio(
    factory: sessionmaker[Session],
    audio_dir: Path,
    user_id: str,
    extension: str,
    content: bytes,
    settings: Settings,
) -> str:
    """Own the session and lock through inventory and the completed exclusive write."""
    if extension not in REFERENCE_AUDIO_EXTENSIONS:
        raise ReferenceAudioRejected("Unsupported reference audio extension")
    with factory() as session:
        entry_kind = "owner directory"
        try:
            _lock_reference_owner(session, user_id)
            with ExitStack() as stack:
                directory = _reference_directory(stack, audio_dir, user_id)
                entry_kind = "inventory entry"
                usage = _reference_usage(directory)
                if (
                    usage.files + 1 > settings.reference_audio_quota_files
                    or usage.bytes + len(content) > settings.reference_audio_quota_bytes
                ):
                    raise ReferenceAudioQuotaExceeded(REFERENCE_AUDIO_QUOTA_DETAIL)
                name = f"{uuid.uuid4()}{extension}"
                entry_kind = "regular upload file"
                _write_reference(directory, name, content)
                return str(Path(user_id) / REFERENCE_AUDIO_DIR / name)
        except OSError as exc:
            kind = (
                str(exc)
                if isinstance(exc, ReferenceAudioStorageError)
                else f"{entry_kind}: {type(exc).__name__}"
            )
            log.error("Reference audio storage refused for user %s: %s", user_id, kind)
            raise ReferenceAudioStorageError(REFERENCE_AUDIO_STORAGE_DETAIL) from exc
