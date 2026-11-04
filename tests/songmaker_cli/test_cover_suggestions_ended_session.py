"""A cover request whose asking session has ended is refused and leaves no trace of the id."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from support.web_app import make_authenticated_user, make_test_app, seed_session

from songmaker_cli.cover_suggestions import (
    CoverSuggestionSessionEndedError,
    request_cover_suggestions,
)
from songmaker_cli.db.models import Album, Job, User, UserSession


def _seed_alice_with_an_album(session) -> None:
    alice = User(username="alice", role="user")
    session.add(alice)
    session.flush()
    session.add(Album(id="alice-album", title="Alice", artist="Alice", created_by=alice.id))


@pytest.fixture
def alice_app(tmp_path: Path) -> tuple[TestClient, object]:
    client, factory = make_test_app(tmp_path, seed_db=_seed_alice_with_an_album)
    seed_session(client, "alice")
    return client, factory


def _alice(session):
    return make_authenticated_user(session.query(User).filter_by(username="alice").one().id)


_ENDED_SESSION_ID = "e" * 43


def test_cover_suggestion_request_owner_refuses_an_ended_session_without_job_or_log_trace(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    _client, factory = make_test_app(tmp_path, seed_db=_seed_alice_with_an_album)
    caplog.set_level(logging.DEBUG)

    with factory() as session:
        with pytest.raises(CoverSuggestionSessionEndedError) as refusal:
            request_cover_suggestions(
                session, "alice-album", _alice(session), session_id=_ENDED_SESSION_ID,
            )
        session.rollback()

    assert refusal.value.status_code == 401
    assert str(refusal.value) == "Log in again to suggest covers."
    assert refusal.value.__cause__ is None and refusal.value.__suppress_context__
    with factory() as session:
        assert session.query(Job).count() == 0
    assert _ENDED_SESSION_ID not in caplog.text


def test_suggest_answers_401_when_the_session_ends_during_the_request(
    alice_app: tuple[TestClient, object], monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, factory = alice_app
    caplog.set_level(logging.DEBUG)
    with factory() as session:
        [live_session_id] = [row.id for row in session.query(UserSession)]

    def logout_before_the_job_is_written(*_args, **_kwargs) -> str:
        with factory() as other:
            other.query(UserSession).filter_by(id=live_session_id).delete()
            other.commit()
        return live_session_id

    monkeypatch.setattr(
        "songmaker_cli.album_api.session_id_from_request", logout_before_the_job_is_written,
    )

    response = client.post("/api/albums/alice-album/cover-suggestions")

    assert response.status_code == 401
    assert response.json()["detail"] == "Log in again to suggest covers."
    assert live_session_id not in response.text + caplog.text
    with factory() as session:
        assert session.query(Job).count() == 0


def test_the_co_writer_tool_reports_an_ended_session_as_a_tool_error(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    from songmaker_cli.cowriter.tools import execute_cowriter_tool

    _client, factory = make_test_app(tmp_path, seed_db=_seed_alice_with_an_album)
    caplog.set_level(logging.DEBUG)

    with factory() as session:
        outcome = execute_cowriter_tool(
            session, _alice(session), "suggest_album_cover",
            {"album_id": "alice-album"}, session_id=_ENDED_SESSION_ID,
        )

    assert outcome.is_error is True
    assert outcome.content == "Log in again to suggest covers."
    assert _ENDED_SESSION_ID not in caplog.text
    with factory() as session:
        assert session.query(Job).count() == 0
