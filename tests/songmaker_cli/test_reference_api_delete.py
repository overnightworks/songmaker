"""DELETE /api/references/{id}: an unused reference goes, a used one stays."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.exc import OperationalError
from support import reference_api_world
from support.reference_api_world import (
    AUDIO_BYTES,
    LINKS,
    NOT_FOUND,
    REFERENCES_PATH,
    SECRET_FILENAME,
    link_reference,
    post_reference,
    reference_files,
    reference_rows,
    seed_playable,
    signed_in_as,
)
from support.reference_rows import a_reference
from support.token_world import TokenWorld, make_token_world
from support.web_app import web_client

from songmaker_cli.db.models import AuditLog, ReferenceRecording

signed_in = reference_api_world.signed_in


def _delete(client: TestClient, reference_id: str):
    return client.delete(f"{REFERENCES_PATH}/{reference_id}")


def _audit_records(client: TestClient) -> list[AuditLog]:
    with client.app.state.ctx.db() as session:
        return session.query(AuditLog).filter_by(action="delete", resource_type="reference").all()


def test_d1_the_owner_deletes_an_unused_reference_row_and_file(signed_in: TestClient) -> None:
    reference_id = seed_playable(signed_in)
    other_id = seed_playable(signed_in, name="stays.wav")

    response = _delete(signed_in, reference_id)

    assert response.status_code == 204
    assert response.content == b""
    assert [row.id for row in reference_rows(signed_in)] == [other_id]
    assert [path.name for path in reference_files(signed_in)] == ["stays.wav"]


def test_d2_a_delete_writes_one_audit_record_without_a_filename(signed_in: TestClient) -> None:
    reference_id = seed_playable(signed_in)

    _delete(signed_in, reference_id)

    [record] = _audit_records(signed_in)
    assert record.user_id == "owner-id"
    assert record.resource_id == reference_id
    assert SECRET_FILENAME not in f"{record.detail}{record.resource_id}"


@pytest.mark.parametrize("who", ["other", "boss", "nobody"])
def test_d3_a_foreign_or_missing_reference_answers_the_global_404_and_stays(
    signed_in: TestClient, who: str,
) -> None:
    reference_id = seed_playable(signed_in)
    target = "no-such-id" if who == "nobody" else reference_id
    caller = signed_in if who == "nobody" else signed_in_as(signed_in, who)

    response = _delete(caller, target)

    assert response.status_code == 404
    assert response.json() == NOT_FOUND
    assert len(reference_rows(signed_in)) == 1
    assert len(reference_files(signed_in)) == 1
    assert _audit_records(signed_in) == []


def test_d4_a_repeated_delete_answers_404_and_unlinks_nothing(signed_in: TestClient) -> None:
    reference_id = seed_playable(signed_in)
    _delete(signed_in, reference_id)
    replacement = signed_in.app.state.ctx.audio_dir / "owner-id" / "refs" / SECRET_FILENAME
    replacement.write_bytes(AUDIO_BYTES)

    response = _delete(signed_in, reference_id)

    assert response.status_code == 404
    assert replacement.exists()


@pytest.mark.parametrize("link", LINKS)
def test_d5_a_linked_reference_answers_409_and_stays(signed_in: TestClient, link: dict) -> None:
    reference_id = seed_playable(signed_in)
    link_reference(signed_in, reference_id, **link)

    response = _delete(signed_in, reference_id)

    assert response.status_code == 409
    assert response.json() == {"detail": "Reference audio is in use."}
    assert [row.id for row in reference_rows(signed_in)] == [reference_id]
    assert len(reference_files(signed_in)) == 1
    assert _audit_records(signed_in) == []


def test_d6_a_failed_unlink_answers_204_leaves_the_file_and_logs_no_path(
    signed_in: TestClient, tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    reference_id = seed_playable(signed_in)
    audio_dir = signed_in.app.state.ctx.audio_dir
    refs = audio_dir / "owner-id" / "refs"
    moved = tmp_path / "elsewhere"
    refs.rename(moved)
    refs.symlink_to(moved)

    with caplog.at_level(logging.INFO):
        response = _delete(signed_in, reference_id)

    assert response.status_code == 204
    assert reference_rows(signed_in) == []
    assert (moved / SECRET_FILENAME).exists()
    logged = caplog.text
    assert SECRET_FILENAME not in logged
    assert str(tmp_path) not in logged
    assert reference_id in logged
    assert "owner-id" in logged


def test_d7_a_failed_commit_unlinks_nothing(signed_in: TestClient) -> None:
    reference_id = seed_playable(signed_in)
    factory = signed_in.app.state.ctx.db

    def refuse_commit_with_the_audit_record(session) -> None:
        if session.execute(select(func.count(AuditLog.id))).scalar_one():
            raise OperationalError("COMMIT", {}, Exception("commit refused"))

    event.listen(factory, "before_commit", refuse_commit_with_the_audit_record)
    try:
        client = web_client(
            signed_in.app, cookies=signed_in.cookies, raise_server_exceptions=False,
        )
        response = _delete(client, reference_id)
    finally:
        event.remove(factory, "before_commit", refuse_commit_with_the_audit_record)

    assert response.status_code == 500
    assert len(reference_files(signed_in)) == 1
    assert [row.id for row in reference_rows(signed_in)] == [reference_id]


@pytest.mark.parametrize(
    "stored_path",
    ["owner-id/refs/sub/nested.wav", "other-id/refs/theirs.wav", "owner-id/refs/../escape.wav"],
)
def test_d8_a_row_with_a_corrupt_path_answers_500_and_keeps_the_row_and_the_file(
    signed_in: TestClient, caplog: pytest.LogCaptureFixture, stored_path: str,
) -> None:
    audio_dir = signed_in.app.state.ctx.audio_dir
    target = audio_dir / stored_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(AUDIO_BYTES)
    with signed_in.app.state.ctx.db() as session:
        row = a_reference(
            session, "owner-id", name="x.wav", storage_path=stored_path,
        )
        session.commit()
        reference_id = row.id

    with caplog.at_level(logging.INFO):
        response = _delete(signed_in, reference_id)

    assert response.status_code == 500
    assert response.json() == {
        "detail": "Reference audio storage could not be checked.",
        "message": {"key": "referenceRefusal.storage", "values": {}},
    }
    assert [row.id for row in reference_rows(signed_in)] == [reference_id]
    assert target.exists()
    assert stored_path not in caplog.text
    assert _audit_records(signed_in) == []


def test_d9_a_persons_token_deletes_that_persons_reference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pg_factory,
) -> None:
    monkeypatch.setenv("TOKEN_CLIENTS", TokenWorld.HAL)
    world = make_token_world(tmp_path, factory=pg_factory)
    uploaded = post_reference(
        world.client, AUDIO_BYTES, "mine.wav", headers=world.bearer(TokenWorld.ALICE),
    )

    response = world.client.delete(
        f"{REFERENCES_PATH}/{uploaded.json()['id']}", headers=world.bearer(TokenWorld.ALICE),
    )

    assert response.status_code == 204
    assert world.rows(ReferenceRecording, "user_id") == []


def test_d10_without_a_session_the_delete_is_unauthenticated(signed_in: TestClient) -> None:
    reference_id = seed_playable(signed_in)
    anonymous = web_client(signed_in.app, raise_server_exceptions=False)

    assert _delete(anonymous, reference_id).status_code == 401
    assert len(reference_rows(signed_in)) == 1

