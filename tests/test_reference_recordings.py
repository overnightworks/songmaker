"""Every reference upload is a ReferenceRecording row and its file is the row's storage_path."""

from __future__ import annotations

import logging
import stat
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from support.wav_files import write_wav
from support.web_app import make_authenticated_user, make_router_app, make_router_ctx

from songmaker_cli.db.models import ReferenceRecording, User
from songmaker_cli.reference_audio import (
    REFERENCE_AUDIO_STORAGE_DETAIL,
    ReferenceAudioStorageError,
    owner_reference_audio_root,
    store_reference_audio,
)
from songmaker_cli.settings import Settings


@pytest.fixture
def ctx(tmp_path):
    return make_router_ctx(
        tmp_path, seed_db=lambda session: session.add(User(id="owner", username="owner")),
    )


def _store(ctx, content=b"a" * 100, filename="ref.wav"):
    return store_reference_audio(
        ctx.db, ctx.audio_dir, "owner", ".wav", content, Settings(), filename,
    )


def _rows(ctx):
    with ctx.db() as session:
        return session.query(ReferenceRecording).order_by(ReferenceRecording.created_at).all()


def _files(ctx):
    root = owner_reference_audio_root(ctx.audio_dir, "owner")
    return sorted(root.iterdir()) if root.exists() else []


def _wav_bytes(tmp_path: Path, seconds: float) -> bytes:
    path = tmp_path / "tone.wav"
    write_wav(path, np.zeros(int(8000 * seconds), dtype=np.float32), 8000)
    return path.read_bytes()


def test_an_upload_creates_one_complete_row_for_its_0600_file(ctx, tmp_path):
    """Q1."""
    content = _wav_bytes(tmp_path, 2.0)
    stored = _store(ctx, content, "my song.wav")
    [row] = _rows(ctx)
    assert row.user_id == "owner"
    assert row.storage_path == stored
    assert (ctx.audio_dir / row.storage_path).read_bytes() == content
    assert stat.S_IMODE((ctx.audio_dir / stored).stat().st_mode) == 0o600
    assert row.original_filename == "my song.wav"
    assert row.size_bytes == len(content)
    assert row.duration_sec == pytest.approx(2.0, abs=0.01)
    assert row.created_at is not None
    assert row.id


def test_unparseable_audio_still_creates_a_row_without_duration(ctx):
    """Q12."""
    _store(ctx, b"not audio" * 20)
    [row] = _rows(ctx)
    assert row.duration_sec is None


def _database_error(detail: str) -> OperationalError:
    return OperationalError("INSERT INTO reference_recordings", {}, Exception(detail))


@pytest.fixture
def failing_insert(ctx):
    """The insert of the next upload fails once its file exists, after the hooks ran."""
    hooks = []

    def fail(session, flush_context, instances):
        if _files(ctx):
            for hook in hooks:
                hook()
            raise _database_error("secret-detail /private/path")

    event.listen(ctx.db, "before_flush", fail)
    yield hooks
    event.remove(ctx.db, "before_flush", fail)


def test_a_failed_insert_removes_its_file_and_answers_with_the_storage_error(ctx, failing_insert):
    """Q10a."""
    with pytest.raises(ReferenceAudioStorageError) as raised:
        _store(ctx)
    assert str(raised.value) == REFERENCE_AUDIO_STORAGE_DETAIL
    assert _rows(ctx) == []
    assert _files(ctx) == []


def test_a_failed_unlink_leaves_an_uncounted_remnant_and_logs_only_ids_and_error_kind(
    ctx, failing_insert, caplog
):
    """Q11 and L1 for the failure path."""
    refs = owner_reference_audio_root(ctx.audio_dir, "owner")
    failing_insert.append(lambda: refs.chmod(0o500))
    try:
        with caplog.at_level(logging.INFO, logger="songmaker_cli.reference_audio"):
            with pytest.raises(ReferenceAudioStorageError):
                _store(ctx, filename="private-name.wav")
        assert len(_files(ctx)) == 1
    finally:
        refs.chmod(0o700)
    assert _rows(ctx) == []
    assert "user owner" in caplog.text
    assert "OperationalError" in caplog.text
    assert "PermissionError" in caplog.text
    for forbidden in ("secret-detail", "/private/path", "private-name", "refs/", ".wav"):
        assert forbidden not in caplog.text


def test_a_commit_that_raises_before_committing_keeps_the_file_as_an_uncounted_remnant(
    ctx, caplog
):
    """Q10b, no row; the log carries the user id and error kind only."""
    def refuse(session):
        raise _database_error("refs/owner/private-name.wav unreachable")

    event.listen(ctx.db, "before_commit", refuse)
    with caplog.at_level(logging.INFO, logger="songmaker_cli.reference_audio"):
        with pytest.raises(ReferenceAudioStorageError):
            _store(ctx, filename="private-name.wav")
    assert "user owner" in caplog.text
    assert "OperationalError" in caplog.text
    for forbidden in ("unreachable", "private-name", "refs/", ".wav"):
        assert forbidden not in caplog.text
    event.remove(ctx.db, "before_commit", refuse)
    assert _rows(ctx) == []
    assert len(_files(ctx)) == 1


def test_a_commit_whose_confirmation_is_lost_leaves_row_and_file_in_agreement(ctx):
    """Q10b, row committed."""
    def lose_confirmation(session):
        raise _database_error("connection lost")

    event.listen(ctx.db, "after_commit", lose_confirmation)
    with pytest.raises(ReferenceAudioStorageError):
        _store(ctx)
    event.remove(ctx.db, "after_commit", lose_confirmation)
    [row] = _rows(ctx)
    assert [str(path.relative_to(ctx.audio_dir)) for path in _files(ctx)] == [row.storage_path]


@pytest.mark.parametrize(
    "client_name,stored_name",
    [
        pytest.param("../../etc/dir/song.wav", "song.wav", id="N1-directory-part"),
        pytest.param("a" * 251 + ".wav", "a" * 251 + ".wav", id="N2-255-characters"),
        pytest.param("Süße Träume – 夜.wav", "Süße Träume – 夜.wav", id="N4-non-ascii"),
    ],
)
def test_the_stored_filename_is_the_basename_of_the_client_name(ctx, client_name, stored_name):
    with TestClient(make_router_app(ctx, user=make_authenticated_user("owner"))) as client:
        response = client.post("/api/audio/upload", files={"file": (client_name, b"a" * 100)})
    assert response.status_code == 200
    [row] = _rows(ctx)
    assert row.original_filename == stored_name


def test_a_filename_of_256_characters_is_refused_and_adds_nothing(ctx):
    """N3."""
    with TestClient(make_router_app(ctx, user=make_authenticated_user("owner"))) as client:
        response = client.post(
            "/api/audio/upload", files={"file": ("a" * 252 + ".wav", b"a" * 100)},
        )
    assert response.status_code == 400
    assert _rows(ctx) == []
    assert _files(ctx) == []


def test_a_successful_upload_logs_user_reference_and_bytes_only(ctx, caplog):
    """L1."""
    with caplog.at_level(logging.INFO), TestClient(
        make_router_app(ctx, user=make_authenticated_user("owner"))
    ) as client:
        response = client.post(
            "/api/audio/upload", files={"file": ("private-name.wav", b"a" * 100)},
        )
    [row] = _rows(ctx)
    assert response.json() == {"path": row.storage_path, "filename": "private-name.wav"}
    message = next(
        r.getMessage() for r in caplog.records if r.name == "songmaker_cli.reference_audio"
    )
    assert all(fact in message for fact in ("owner", row.id, "100 bytes"))
    assert "private-name" not in caplog.text
    assert row.storage_path not in caplog.text
