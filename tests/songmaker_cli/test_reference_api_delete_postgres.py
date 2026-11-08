"""Deleting a reference through the route against a take being saved and a second delete."""

from __future__ import annotations

from pathlib import Path

import pytest
from support.postgres_lock_harness import CommitPause, race, wrote_to_tables
from support.reference_rows import a_reference
from support.reference_take_world import persist_take_linking, seed_owner_song_and_running_job
from support.web_app import make_test_app, seed_session

from songmaker_cli import reference_api
from songmaker_cli.constants import REFERENCE_AUDIO_DIR
from songmaker_cli.db.models import Generation, ReferenceRecording
from songmaker_cli.jobs._runtime import (
    JOB_ERROR_REFERENCE_DELETED_DURING_TAKE,
)
from songmaker_cli.reference_audio import RemovalOutcome

OWNER = "u1"
REFERENCE_ID = "reference-1"
STORED_NAME = "F.wav"
IN_USE = {"detail": "Reference audio is in use."}
NOT_FOUND = {"detail": "Not Found"}


def _seed_take_and_reference(session) -> None:
    seed_owner_song_and_running_job(session, OWNER)
    a_reference(session, OWNER, name=STORED_NAME, reference_id=REFERENCE_ID)


class _World:
    """The real delete route and the real take persistence on PostgreSQL."""

    def __init__(self, pg_factory, tmp_path: Path) -> None:
        self.pg_factory = pg_factory
        self.client, _ = make_test_app(
            tmp_path, factory=pg_factory, seed_db=_seed_take_and_reference,
        )
        seed_session(self.client, "owner")
        self.audio_dir = self.client.app.state.ctx.audio_dir
        self.stored_file = self.audio_dir / OWNER / REFERENCE_AUDIO_DIR / STORED_NAME
        self.stored_file.parent.mkdir(parents=True)
        self.stored_file.write_bytes(b"RIFF")

    def delete_reference(self):
        return self.client.delete(f"/api/references/{REFERENCE_ID}")

    def persist_take(self):
        """The take's persistence; the message that ends the job is its answer."""
        return persist_take_linking(self.pg_factory, self.audio_dir, OWNER, REFERENCE_ID)

    def reference_rows(self) -> int:
        with self.pg_factory() as session:
            return session.query(ReferenceRecording).count()

    def take_rows(self) -> int:
        with self.pg_factory() as session:
            return session.query(Generation).count()


def test_a_delete_waits_for_a_take_that_links_the_row_and_then_answers_in_use(
    pg_factory, tmp_path,
) -> None:
    world = _World(pg_factory, tmp_path)
    take_pause = CommitPause(lambda session: wrote_to_tables(session, "generations"))

    answers = race(pg_factory, world.persist_take, world.delete_reference, take_pause)

    assert answers["first"] is not None
    assert answers["second"].status_code == 409
    assert answers["second"].json() == IN_USE
    assert world.reference_rows() == 1
    assert world.take_rows() == 1
    assert world.stored_file.exists()


def test_a_take_waits_for_a_delete_of_the_row_and_then_fails_with_the_deleted_message(
    pg_factory, tmp_path,
) -> None:
    world = _World(pg_factory, tmp_path)
    delete_pause = CommitPause(lambda session: wrote_to_tables(session, "reference_recordings"))

    answers = race(pg_factory, world.delete_reference, world.persist_take, delete_pause)

    assert answers["first"].status_code == 204
    assert answers["second"] == JOB_ERROR_REFERENCE_DELETED_DURING_TAKE
    assert world.reference_rows() == 0
    assert world.take_rows() == 0


def test_two_concurrent_deletes_answer_204_and_404_and_unlink_the_file_once(
    pg_factory, tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _World(pg_factory, tmp_path)
    delete_pause = CommitPause(lambda session: wrote_to_tables(session, "reference_recordings"))
    outcomes: list[RemovalOutcome] = []
    real_remove = reference_api.remove_reference_file

    def recording_remove(*arguments) -> RemovalOutcome:
        outcomes.append(real_remove(*arguments))
        return outcomes[-1]

    monkeypatch.setattr(reference_api, "remove_reference_file", recording_remove)

    answers = race(pg_factory, world.delete_reference, world.delete_reference, delete_pause)

    assert answers["first"].status_code == 204
    assert answers["second"].status_code == 404
    assert answers["second"].json() == NOT_FOUND
    assert outcomes == [RemovalOutcome.REMOVED]
    assert not world.stored_file.exists()
    assert world.reference_rows() == 0
