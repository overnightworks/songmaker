"""Owner-scoped reference-audio path resolution."""

from __future__ import annotations

import hashlib
import logging
import os
import stat
import uuid
from contextlib import ExitStack
from pathlib import Path
from typing import Final

from sqlalchemy.orm import Session, sessionmaker

from songmaker_cli.api_helpers import _begin_exclusive
from songmaker_cli.audio_files import read_audio_duration
from songmaker_cli.constants import REFERENCE_AUDIO_DIR, REFERENCE_AUDIO_EXTENSIONS
from songmaker_cli.db.models import User
from songmaker_cli.db.queries.reference_recordings import (
    create_reference_recording,
    owner_reference_usage,
)
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
    """Serializes one owner's reference work: upload admission now, remnant reconciliation later.

    The lock lasts until the caller commits or rolls back.
    """
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


def _remove_unrecorded_file(directory: int, name: str, user_id: str) -> None:
    """Best effort: a file that stays is a remnant, which counts nowhere and is never touched."""
    try:
        os.unlink(name, dir_fd=directory)
    except OSError as exc:
        log.error(
            "Reference audio remnant stays for user %s: %s", user_id, type(exc).__name__,
        )


def _write_reference(directory: int, name: str, content: bytes, user_id: str) -> None:
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
        _remove_unrecorded_file(directory, name, user_id)
        raise


def _record_reference(
    session: Session,
    directory: int,
    audio_dir: Path,
    user_id: str,
    name: str,
    original_filename: str,
    size_bytes: int,
) -> str:
    """Insert the row for the file just written; a failure before the commit removes the file."""
    storage_path = str(Path(user_id) / REFERENCE_AUDIO_DIR / name)
    try:
        recording = create_reference_recording(
            session,
            user_id=user_id,
            storage_path=storage_path,
            original_filename=original_filename,
            size_bytes=size_bytes,
            duration_sec=read_audio_duration(audio_dir / storage_path),
        )
    except BaseException:
        _remove_unrecorded_file(directory, name, user_id)
        raise
    try:
        session.commit()
    except BaseException as exc:
        # The commit may have succeeded with its confirmation lost: keep the file.
        log.error(
            "Reference audio commit failed for user %s: %s", user_id, type(exc).__name__,
        )
        raise
    log.info(
        "Reference audio stored for user %s: reference %s, %d bytes",
        user_id, recording.id, size_bytes,
    )
    return storage_path


def store_reference_audio(
    factory: sessionmaker[Session],
    audio_dir: Path,
    user_id: str,
    extension: str,
    content: bytes,
    settings: Settings,
    original_filename: str,
) -> str:
    """Own the session and lock from the row count through the commit of the new row."""
    if extension not in REFERENCE_AUDIO_EXTENSIONS:
        raise ReferenceAudioRejected("Unsupported reference audio extension")
    with factory() as session:
        entry_kind = "owner directory"
        try:
            _lock_reference_owner(session, user_id)
            with ExitStack() as stack:
                directory = _reference_directory(stack, audio_dir, user_id)
                usage = owner_reference_usage(session, user_id)
                if (
                    usage.files + 1 > settings.reference_audio_quota_files
                    or usage.bytes + len(content) > settings.reference_audio_quota_bytes
                ):
                    raise ReferenceAudioQuotaExceeded(REFERENCE_AUDIO_QUOTA_DETAIL)
                name = f"{uuid.uuid4()}{extension}"
                entry_kind = "regular upload file"
                _write_reference(directory, name, content, user_id)
                return _record_reference(
                    session, directory, audio_dir, user_id, name, original_filename, len(content),
                )
        except OSError as exc:
            kind = (
                str(exc)
                if isinstance(exc, ReferenceAudioStorageError)
                else f"{entry_kind}: {type(exc).__name__}"
            )
            log.error("Reference audio storage refused for user %s: %s", user_id, kind)
            raise ReferenceAudioStorageError(REFERENCE_AUDIO_STORAGE_DETAIL) from exc
