"""Owner-scoped reference-audio path resolution."""

from __future__ import annotations

import hashlib
import logging
import os
import stat
import uuid
from contextlib import ExitStack, suppress
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Final

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from songmaker_cli.api_helpers import _begin_exclusive
from songmaker_cli.audio_files import read_audio_duration
from songmaker_cli.constants import REFERENCE_AUDIO_DIR, REFERENCE_AUDIO_EXTENSIONS
from songmaker_cli.db.models import User
from songmaker_cli.db.queries.auth import list_user_ids
from songmaker_cli.db.queries.reference_recordings import (
    create_reference_recording,
    get_owned_reference_recording,
    owned_reference_storage_paths,
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
    if not is_owner_storage_path(user_id, stored_relative):
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


def resolve_linked_reference_audio(
    factory: sessionmaker[Session],
    audio_dir: Path,
    user_id: str,
    reference_recording_id: str | None,
) -> str:
    """The absolute file behind a version's link, or "" for none.

    The job user's own row is required: a missing or foreign row is rejected.
    """
    if reference_recording_id is None:
        return ""
    with factory() as session:
        recording = get_owned_reference_recording(session, user_id, reference_recording_id)
        if recording is None:
            raise ReferenceAudioRejected(REFERENCE_AUDIO_NOT_OWNED_DETAIL)
        storage_path = recording.storage_path
    return str(resolve_owned_reference_audio(audio_dir, user_id, storage_path))


REFERENCE_AUDIO_QUOTA_DETAIL: Final = "Reference audio storage limit reached."
REFERENCE_AUDIO_STORAGE_DETAIL: Final = "Reference audio storage could not be checked."
_REFERENCE_LOCK_NAMESPACE: Final = "songmaker.reference-audio:"
log = logging.getLogger(__name__)


@dataclass(frozen=True)
class StoredReference:
    id: str
    storage_path: str


class ReferenceAudioQuotaExceeded(ValueError):
    pass


class ReferenceAudioStorageError(OSError):
    pass


def _lock_reference_owner(session: Session, user_id: str) -> None:
    """Serializes one owner's reference work: upload admission and remnant reconciliation.

    The lock lasts until the caller commits or rolls back.
    """
    digest = hashlib.sha256((_REFERENCE_LOCK_NAMESPACE + user_id).encode()).digest()
    lock_id = int.from_bytes(digest[:8], "big", signed=True)
    _begin_exclusive(session, lock_id)
    if session.get(User, user_id) is None:
        raise ReferenceAudioStorageError("missing owner")


def _open_component(stack: ExitStack, parent: int, part: str, *, create: bool) -> int:
    """Opens one directory below ``parent`` without following a symlink."""
    if create:
        with suppress(FileExistsError):
            os.mkdir(part, dir_fd=parent)
    try:
        descriptor = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
    except FileNotFoundError:
        raise
    except OSError:
        mode = os.stat(part, dir_fd=parent, follow_symlinks=False).st_mode
        if stat.S_ISDIR(mode):
            raise
        kind = "symlink ancestor" if stat.S_ISLNK(mode) else "non-directory ancestor"
        raise ReferenceAudioStorageError(kind) from None
    stack.callback(os.close, descriptor)
    return descriptor


def _walk_reference_directory(
    stack: ExitStack, audio_dir: Path, user_id: str, *, create: bool,
) -> int:
    if Path(user_id).name != user_id or user_id in {"", ".", ".."}:
        raise ReferenceAudioStorageError("invalid owner")
    root = owner_reference_audio_root(audio_dir.absolute(), user_id)
    descriptor = os.open(root.anchor, os.O_RDONLY | os.O_DIRECTORY)
    stack.callback(os.close, descriptor)
    for part in root.parts[1:]:
        descriptor = _open_component(stack, descriptor, part, create=create)
    return descriptor


def _reference_directory(stack: ExitStack, audio_dir: Path, user_id: str) -> int:
    return _walk_reference_directory(stack, audio_dir, user_id, create=True)


def _existing_reference_directory(stack: ExitStack, audio_dir: Path, user_id: str) -> int | None:
    try:
        return _walk_reference_directory(stack, audio_dir, user_id, create=False)
    except FileNotFoundError:
        return None


def _remove_unrecorded_file(directory: int, name: str, user_id: str) -> None:
    """Best effort: a file that stays is a remnant, which counts nowhere until the daily run."""
    failure_kind = None
    try:
        os.unlink(name, dir_fd=directory)
    except OSError as exc:
        failure_kind = type(exc).__name__
    if failure_kind is not None:
        log.error("Reference audio remnant stays for user %s: %s", user_id, failure_kind)


def _storage_path(user_id: str, name: str) -> str:
    return str(Path(user_id) / REFERENCE_AUDIO_DIR / name)


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
) -> StoredReference:
    """Insert the row for the file just written; a failure before the commit removes the file."""
    storage_path = _storage_path(user_id, name)
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
        _log_commit_failure(user_id, exc)
        raise
    log.info(
        "Reference audio stored for user %s: reference %s, %d bytes",
        user_id, recording.id, size_bytes,
    )
    return StoredReference(id=recording.id, storage_path=storage_path)


def _log_commit_failure(user_id: str, failure: BaseException) -> None:
    """Log the user and the error kind only: the message and traceback can carry paths."""
    log.error("Reference audio commit failed for user %s: %s", user_id, type(failure).__name__)


def store_reference_audio(
    factory: sessionmaker[Session],
    audio_dir: Path,
    user_id: str,
    extension: str,
    content: bytes,
    settings: Settings,
    original_filename: str,
) -> StoredReference:
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
        except (OSError, SQLAlchemyError) as exc:
            if isinstance(exc, ReferenceAudioStorageError):
                kind = str(exc)
            elif isinstance(exc, SQLAlchemyError):
                kind = f"database: {type(exc).__name__}"
            else:
                kind = f"{entry_kind}: {type(exc).__name__}"
            log.error("Reference audio storage refused for user %s: %s", user_id, kind)
            raise ReferenceAudioStorageError(REFERENCE_AUDIO_STORAGE_DETAIL) from exc


@dataclass(frozen=True)
class RemnantReport:
    removed: int = 0
    refused: int = 0
    failed_owners: int = 0

    def __add__(self, other: RemnantReport) -> RemnantReport:
        return RemnantReport(
            self.removed + other.removed,
            self.refused + other.refused,
            self.failed_owners + other.failed_owners,
        )


def is_owner_storage_path(user_id: str, storage_path: str) -> bool:
    """True for exactly ``{user}/refs/{one name}``, the only path an upload ever stores."""
    parts = PurePosixPath(storage_path).parts
    return (
        len(parts) == 3 and parts[2] != ".." and _storage_path(user_id, parts[2]) == storage_path
    )


class RemovalOutcome(StrEnum):
    REMOVED = "removed"
    ALREADY_GONE = "already_gone"
    FAILED = "failed"


def remove_reference_file(audio_dir: Path, user_id: str, storage_path: str) -> RemovalOutcome:
    """Unlink the owner's file through the ``O_NOFOLLOW`` walk, by descriptor.

    A symlinked ancestor, an invalid owner and any other ``OSError`` are ``FAILED``; the
    daily reconciliation removes what stays.
    """
    if not is_owner_storage_path(user_id, storage_path):
        return RemovalOutcome.FAILED
    try:
        with ExitStack() as stack:
            directory = _walk_reference_directory(stack, audio_dir, user_id, create=False)
            os.unlink(PurePosixPath(storage_path).name, dir_fd=directory)
    except FileNotFoundError:
        return RemovalOutcome.ALREADY_GONE
    except OSError:
        return RemovalOutcome.FAILED
    return RemovalOutcome.REMOVED


def _remove_if_remnant(
    directory: int, user_id: str, name: str, named_paths: set[str],
) -> RemnantReport:
    try:
        mode = os.stat(name, dir_fd=directory, follow_symlinks=False).st_mode
        if not stat.S_ISREG(mode):
            return RemnantReport(refused=1)
        if _storage_path(user_id, name) in named_paths:
            return RemnantReport()
        os.unlink(name, dir_fd=directory)
    except FileNotFoundError:
        return RemnantReport()
    return RemnantReport(removed=1)


def _remove_owner_remnants(session: Session, audio_dir: Path, user_id: str) -> RemnantReport:
    named_paths = owned_reference_storage_paths(session, user_id)
    if not all(is_owner_storage_path(user_id, path) for path in named_paths):
        raise ReferenceAudioStorageError("non-conforming row path")
    report = RemnantReport()
    with ExitStack() as stack:
        directory = _existing_reference_directory(stack, audio_dir, user_id)
        if directory is None:
            return report
        try:
            for name in os.listdir(directory):
                report += _remove_if_remnant(directory, user_id, name, named_paths)
        except OSError as exc:
            _log_owner_failure(user_id, exc)
            return report + RemnantReport(failed_owners=1)
    return report


def _log_owner_failure(user_id: str, exc: Exception) -> None:
    kind = str(exc) if isinstance(exc, ReferenceAudioStorageError) else type(exc).__name__
    log.error("Reference audio reconciliation failed for user %s: %s", user_id, kind)


def _reconcile_owner(
    factory: sessionmaker[Session], audio_dir: Path, user_id: str,
) -> RemnantReport:
    """Holds the owner lock from the membership read through the last unlink."""
    try:
        with factory() as session:
            _lock_reference_owner(session, user_id)
            report = _remove_owner_remnants(session, audio_dir, user_id)
            session.commit()
    except (OSError, SQLAlchemyError) as exc:
        _log_owner_failure(user_id, exc)
        return RemnantReport(failed_owners=1)
    if report.refused:
        log.warning(
            "Reference audio reconciliation refused %d entries for user %s",
            report.refused, user_id,
        )
    return report


def reconcile_reference_remnants(factory: sessionmaker[Session], audio_dir: Path) -> RemnantReport:
    """Removes every regular file under an owner's refs directory that no row of the owner names.

    One owner's failure is logged and leaves the other owners running; a failure to list the
    owners ends the run.
    """
    with factory() as session:
        user_ids = list_user_ids(session)
    report = RemnantReport()
    for user_id in user_ids:
        report += _reconcile_owner(factory, audio_dir, user_id)
    log.info(
        "Reference audio reconciliation: %d removed, %d refused, %d owners failed",
        report.removed, report.refused, report.failed_owners,
    )
    return report
