"""A cover request whose asking session has ended is refused and leaves no trace of the id."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from support.cover_album_world import album_owner, seed_cover_albums
from support.web_app import make_test_app

from songmaker_cli.cover_suggestions import (
    CoverSuggestionSessionEndedError,
    request_cover_suggestions,
)
from songmaker_cli.db.models import Job, UserSession

_ENDED_SESSION_ID = "e" * 43


def test_cover_suggestion_request_owner_refuses_an_ended_session_without_job_or_log_trace(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, pg_factory,
) -> None:
    _client, factory = make_test_app(tmp_path, seed_db=seed_cover_albums, factory=pg_factory)
    caplog.set_level(logging.DEBUG)

    with factory() as session:
        owner = album_owner(session)
        with pytest.raises(CoverSuggestionSessionEndedError) as refusal:
            request_cover_suggestions(
                session, "alice-album", owner, session_id=_ENDED_SESSION_ID,
            )
        session.rollback()

    assert refusal.value.status_code == 401
    assert str(refusal.value) == "Log in again to suggest covers."
    assert refusal.value.__cause__ is None
    assert refusal.value.__context__ is None
    with factory() as session:
        assert session.query(Job).count() == 0
    assert _ENDED_SESSION_ID not in caplog.text


def test_suggest_answers_401_when_the_session_ends_during_the_request(
    cover_album_app: tuple[TestClient, object], monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, factory = cover_album_app
    caplog.set_level(logging.DEBUG)
    with factory() as session:
        [live_session_id] = [row.id for row in session.query(UserSession)]

    def logout_after_the_click_check(*_args, **_kwargs) -> None:
        with factory() as other:
            other.query(UserSession).filter_by(id=live_session_id).delete()
            other.commit()

    monkeypatch.setattr("songmaker_cli.album_api.cover_admission", logout_after_the_click_check)

    response = client.post("/api/albums/alice-album/cover-suggestions")

    assert response.status_code == 401
    assert response.json()["detail"] == "Log in again to suggest covers."
    assert live_session_id not in response.text + caplog.text
    with factory() as session:
        assert session.query(Job).count() == 0


def test_the_co_writer_tool_reports_an_ended_session_as_a_tool_error(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, pg_factory,
) -> None:
    from songmaker_cli.cowriter.tools import execute_cowriter_tool

    _client, factory = make_test_app(tmp_path, seed_db=seed_cover_albums, factory=pg_factory)
    caplog.set_level(logging.DEBUG)

    with factory() as session:
        outcome = execute_cowriter_tool(
            session, album_owner(session), "suggest_album_cover",
            {"album_id": "alice-album"}, session_id=_ENDED_SESSION_ID,
        )

    assert outcome.is_error is True
    assert outcome.content == "Log in again to suggest covers."
    assert _ENDED_SESSION_ID not in caplog.text
    with factory() as session:
        assert session.query(Job).count() == 0
