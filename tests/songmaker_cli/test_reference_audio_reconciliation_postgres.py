"""The daily run and an upload order themselves on the owner lock; neither loses a file."""

from __future__ import annotations

import pytest
from postgres_lock_harness import CommitPause, race
from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from support.web_app import make_router_ctx

from songmaker_cli.db.models import ReferenceRecording, User
from songmaker_cli.reference_audio import (
    ReferenceAudioStorageError,
    owner_reference_audio_root,
    reconcile_reference_remnants,
    store_reference_audio,
)
from songmaker_cli.settings import Settings


@pytest.fixture
def world(pg_factory, tmp_path):
    def seed(session):
        session.add(User(id="owner", username="owner"))

    ctx = make_router_ctx(tmp_path, db=pg_factory, seed_db=seed)
    refs = owner_reference_audio_root(ctx.audio_dir, "owner")
    refs.mkdir(parents=True)
    remnant = refs / "remnant.wav"
    remnant.write_bytes(b"x")
    ctx.remnant = remnant
    return ctx


def _upload_one_file(ctx):
    return store_reference_audio(
        ctx.db, ctx.audio_dir, "owner", ".wav", b"audio", Settings(), "x.wav",
    )


def _run_reconciliation(ctx):
    return reconcile_reference_remnants(ctx.db, ctx.audio_dir)


def _stored_row_count(ctx) -> int:
    with ctx.db() as session:
        return session.query(ReferenceRecording).count()


def test_a_run_waiting_behind_an_upload_reads_the_rows_after_the_commit(world):
    """The upload holds the lock to its commit, so the run sees its row and keeps its file."""
    upload, run = (lambda: _upload_one_file(world)), (lambda: _run_reconciliation(world))
    answers = race(world.db, upload, run, CommitPause())

    assert answers["second"].removed == 1
    assert not world.remnant.exists()
    assert (world.audio_dir / answers["first"].storage_path).read_bytes() == b"audio"
    assert _stored_row_count(world) == 1


def test_an_upload_waiting_behind_a_run_is_admitted_after_it_and_keeps_its_file(world):
    """The run holds the lock through its unlinks, so the upload's file never meets them."""
    upload, run = (lambda: _upload_one_file(world)), (lambda: _run_reconciliation(world))
    answers = race(world.db, run, upload, CommitPause())

    assert answers["first"].removed == 1
    assert not world.remnant.exists()
    assert (world.audio_dir / answers["second"].storage_path).read_bytes() == b"audio"
    assert _stored_row_count(world) == 1


def test_an_upload_whose_commit_raised_after_the_row_committed_keeps_its_file(world):
    def lose_the_confirmation(_session):
        raise OperationalError("COMMIT", {}, ConnectionError("lost"))

    event.listen(world.db, "after_commit", lose_the_confirmation)
    try:
        with pytest.raises(ReferenceAudioStorageError):
            _upload_one_file(world)
    finally:
        event.remove(world.db, "after_commit", lose_the_confirmation)
    [stored] = [path for path in world.remnant.parent.iterdir() if path != world.remnant]

    _run_reconciliation(world)

    assert stored.read_bytes() == b"audio"
    assert not world.remnant.exists()
    assert _stored_row_count(world) == 1
