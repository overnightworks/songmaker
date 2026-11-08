"""Album cover suggestion API and filesystem tests."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from support.cover_album_world import album_owner, declared_suggest_refusal, seed_cover_albums
from support.cowriter_gateway import attach_cowriter_gateway
from support.web_app import (
    make_authenticated_user,
    make_router_app,
    make_router_ctx,
    make_test_app,
    seed_session,
    seed_user,
    web_client,
)
from support.xmp_packet import read_digital_source_type

from audio_engine.constants import IPTC_TRAINED_ALGORITHMIC_MEDIA
from songmaker_cli.cleanup import run_cleanup_expired
from songmaker_cli.constants import (
    ALBUM_COVER_SUGGESTIONS_DIRNAME,
    COVER_SUGGESTION_NOT_FOUND,
    JSON_REQUEST_BODY_MAX_BYTES,
    AuditAction,
    ResourceType,
)
from songmaker_cli.cover_suggestions import (
    CoverSuggestionAlbumNotFoundError,
    CoverSuggestionAlreadyRunningError,
    CoverSuggestionDailyLimitReachedError,
    remove_album_cover_suggestion_files,
    remove_cover_suggestion_files,
    request_cover_suggestions,
)
from songmaker_cli.covers import COVER_DIRNAME
from songmaker_cli.db.models import Album, AlbumCoverSuggestion, AuditLog, Job, User, UserSession
from songmaker_cli.db.queries.albums import get_album
from songmaker_cli.db.queries.jobs import count_cover_jobs_since
from songmaker_cli.job_types import JobStatus, JobType
from songmaker_cli.settings import get_settings


def _png_bytes() -> bytes:
    from io import BytesIO

    payload = BytesIO()
    Image.new("RGB", (32, 32), (40, 80, 200)).save(payload, format="PNG")
    return payload.getvalue()


def _add_cover_job(
    factory,
    *,
    album_id: str = "alice-album",
    status: JobStatus = JobStatus.QUEUED,
    started_at: datetime | None = None,
) -> str:
    with factory() as session:
        album = session.query(Album).filter_by(id=album_id).one()
        job = Job(
            type=JobType.COVER,
            user_id=album.created_by,
            album_id=album.id,
            status=status,
            started_at=started_at or datetime.now(timezone.utc),
        )
        session.add(job)
        session.commit()
        return job.id


def _add_suggestion(
    factory,
    audio_dir: Path,
    *,
    album_id: str = "alice-album",
    suggestion_id: str = "a" * 36,
    stored_path: str | None = None,
) -> str:
    path = audio_dir / ALBUM_COVER_SUGGESTIONS_DIRNAME / album_id / f"{suggestion_id}.png"
    if stored_path is None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_png_bytes())
    with factory() as session:
        album = session.query(Album).filter_by(id=album_id).one()
        job = Job(
            type=JobType.COVER,
            user_id=album.created_by,
            album_id=album.id,
            status=JobStatus.COMPLETED,
        )
        session.add(job)
        session.flush()
        session.add(AlbumCoverSuggestion(
            id=suggestion_id,
            album_id=album.id,
            job_id=job.id,
            png_path=stored_path
            or f"{ALBUM_COVER_SUGGESTIONS_DIRNAME}/{album.id}/{suggestion_id}.png",
        ))
        session.commit()
    return suggestion_id


def test_cover_suggestion_request_owner_rejects_missing_and_foreign_albums(
    tmp_path: Path, pg_factory,
) -> None:
    _client, factory = make_test_app(tmp_path, seed_db=seed_cover_albums, factory=pg_factory)

    with factory() as session:
        alice = make_authenticated_user("alice")
        with pytest.raises(CoverSuggestionAlbumNotFoundError):
            request_cover_suggestions(session, "missing", alice, session_id=None)
        with pytest.raises(CoverSuggestionAlbumNotFoundError):
            request_cover_suggestions(session, "bob-album", alice, session_id=None)


def _add_two_pending_suggestions(factory, audio_dir: Path) -> list[str]:
    return [
        _add_suggestion(factory, audio_dir, suggestion_id=suggestion_id)
        for suggestion_id in ("a" * 36, "b" * 36)
    ]


def _suggestion_file(audio_dir: Path, suggestion_id: str) -> Path:
    return audio_dir / ALBUM_COVER_SUGGESTIONS_DIRNAME / "alice-album" / f"{suggestion_id}.png"


def test_cover_suggestion_request_owner_creates_one_job_and_keeps_pending_suggestions(
    tmp_path: Path, pg_factory,
) -> None:
    _client, factory = make_test_app(tmp_path, seed_db=seed_cover_albums, factory=pg_factory)
    pending_ids = _add_two_pending_suggestions(factory, tmp_path / "audio")

    with factory() as session:
        job = request_cover_suggestions(
            session, "alice-album", album_owner(session), session_id=None,
        )

        assert job.type == JobType.COVER
        assert job.album_id == "alice-album"
        assert sorted(
            suggestion.id for suggestion in session.query(AlbumCoverSuggestion)
        ) == pending_ids
        assert session.query(Job).filter_by(album_id="alice-album").count() == 3


def test_cover_suggestion_request_owner_rejects_active_and_daily_limited_jobs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pg_factory,
) -> None:
    """1301-F3-C1-COUNT: active work blocks; completed work consumes the limit."""
    _client, factory = make_test_app(tmp_path, seed_db=seed_cover_albums, factory=pg_factory)
    _add_cover_job(factory)

    with factory() as session:
        owner = album_owner(session)
        with pytest.raises(CoverSuggestionAlreadyRunningError):
            request_cover_suggestions(session, "alice-album", owner, session_id=None)
        session.rollback()

    with factory() as session:
        active_job = session.query(Job).filter_by(album_id="alice-album").one()
        active_job.status = JobStatus.COMPLETED
        session.commit()

    monkeypatch.setenv("COVER_SUGGESTIONS_DAILY_LIMIT", "1")
    get_settings.cache_clear()
    with factory() as session:
        owner = album_owner(session)
        with pytest.raises(CoverSuggestionDailyLimitReachedError):
            request_cover_suggestions(session, "alice-album", owner, session_id=None)


@pytest.mark.parametrize("status", [JobStatus.FAILED, JobStatus.CANCELLED])
def test_unsuccessful_cover_attempts_allow_another_request(
    tmp_path, monkeypatch, status, pg_factory,
):
    """1301-F3-C1-COUNT: failed and cancelled attempts leave the allowance free."""
    _client, factory = make_test_app(tmp_path, seed_db=seed_cover_albums, factory=pg_factory)
    _add_cover_job(factory, status=status)
    monkeypatch.setenv("COVER_SUGGESTIONS_DAILY_LIMIT", "1")
    get_settings.cache_clear()
    with factory() as session:
        job = request_cover_suggestions(
            session, "alice-album", album_owner(session), session_id=None,
        )
        assert job.status == JobStatus.QUEUED
        assert job.album_id == "alice-album"


def test_completed_cover_at_daily_limit_returns_http_429(cover_album_app, monkeypatch):
    """1301-F3-C1-COUNT: HTTP retains the daily-limit refusal contract."""
    client, factory = cover_album_app
    _add_cover_job(factory, status=JobStatus.COMPLETED)
    monkeypatch.setenv("COVER_SUGGESTIONS_DAILY_LIMIT", "1")
    get_settings.cache_clear()

    response = client.post("/api/albums/alice-album/cover-suggestions")

    assert response.status_code == 429
    assert response.json() == {"detail": "Daily cover suggestion limit reached"}


def test_create_cover_suggestions_leaves_the_job_for_the_web_runner(
    cover_album_app: tuple[TestClient, object],
) -> None:
    client, factory = cover_album_app

    response = client.post("/api/albums/alice-album/cover-suggestions")

    assert response.status_code == 200
    assert response.json()["type"] == JobType.COVER
    with factory() as session:
        job = session.get(Job, response.json()["id"])
        assert job is not None
        assert job.status == JobStatus.QUEUED


def test_create_cover_suggestions_audits_the_request_and_a_refusal_leaves_no_row(
    cover_album_app: tuple[TestClient, object],
) -> None:
    client, factory = cover_album_app

    assert client.post("/api/albums/alice-album/cover-suggestions").status_code == 200

    with factory() as session:
        entry = session.query(AuditLog).one()
        assert (entry.action, entry.resource_type, entry.resource_id) == (
            AuditAction.GENERATE, ResourceType.ALBUM, "alice-album",
        )
    assert client.post("/api/albums/alice-album/cover-suggestions").status_code == 409
    with factory() as session:
        assert session.query(AuditLog).count() == 1


def test_a_suggestion_from_a_browser_session_records_that_session_and_never_shows_it(
    cover_album_app: tuple[TestClient, object],
) -> None:
    client, factory = cover_album_app
    with factory() as session:
        [seeded_session_id] = [row.id for row in session.query(UserSession)]

    response = client.post("/api/albums/alice-album/cover-suggestions")

    assert response.status_code == 200
    assert seeded_session_id not in response.text
    with factory() as session:
        assert session.get(Job, response.json()["id"]).session_id == seeded_session_id


def test_suggest_with_a_hal_token_is_refused_and_creates_no_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pg_factory,
) -> None:
    from support.token_world import TokenWorld, make_token_world

    monkeypatch.setenv("TOKEN_CLIENTS", TokenWorld.HAL)
    world = make_token_world(tmp_path, factory=pg_factory)
    with world.factory() as session:
        seed_user(session, "alice", user_id=TokenWorld.ALICE)
        session.add(Album(id="bearer-album", title="B", artist="A", created_by=TokenWorld.ALICE))
        session.commit()
    suggestions = "/api/albums/bearer-album/cover-suggestions"
    bearer = world.bearer(TokenWorld.ALICE)

    response = world.client.post(suggestions, headers=bearer)

    assert response.status_code == 403
    assert response.json() == {"detail": "Cover suggestions need a browser login."}
    declared_suggest_refusal(403).model_validate(response.json())
    with world.factory() as session:
        assert session.query(Job).count() == 0
    assert world.client.get(suggestions, headers=bearer).json()["used_today"] == 0


def test_create_cover_suggestions_keeps_the_pending_suggestions_and_their_files(
    cover_album_app: tuple[TestClient, object],
    tmp_path: Path,
) -> None:
    client, factory = cover_album_app
    audio_dir = tmp_path / "audio"
    pending_ids = _add_two_pending_suggestions(factory, audio_dir)

    response = client.post("/api/albums/alice-album/cover-suggestions")

    assert response.status_code == 200
    listed = client.get("/api/albums/alice-album/cover-suggestions").json()["suggestions"]
    assert sorted(suggestion["id"] for suggestion in listed) == pending_ids
    assert all(_suggestion_file(audio_dir, pending_id).is_file() for pending_id in pending_ids)


def test_cover_suggestion_list_and_selection_use_the_existing_cover_writer(
    cover_album_app: tuple[TestClient, object], tmp_path: Path,
) -> None:
    """1301-F3-C1-DURABLE: removing images does not remove usage."""
    client, factory = cover_album_app
    suggestion_id = _add_suggestion(factory, tmp_path / "audio")
    latest_job_id = _add_cover_job(
        factory,
        status=JobStatus.FAILED,
        started_at=datetime.now(timezone.utc) + timedelta(seconds=1),
    )

    listed = client.get("/api/albums/alice-album/cover-suggestions")

    assert listed.status_code == 200
    body = listed.json()
    assert body["job"] is not None
    assert body["job"]["id"] == latest_job_id
    assert body["job"]["type"] == JobType.COVER
    assert body["job"]["status"] == JobStatus.FAILED
    assert body["job"]["error"] is None
    assert body["used_today"] == 1
    assert body["daily_limit"] == 10
    assert body["suggestions"] == [{
        "id": suggestion_id,
        "url": f"/api/albums/alice-album/cover-suggestions/{suggestion_id}",
    }]
    assert client.get(body["suggestions"][0]["url"]).content == _png_bytes()
    selected = client.put(
        "/api/albums/alice-album/cover", json={"suggestion_id": suggestion_id},
    )
    assert selected.status_code == 200
    assert selected.json()["cover"] is not None
    assert client.get("/api/albums/alice-album/cover-suggestions").json()["used_today"] == 1


def test_selected_cover_suggestion_carries_the_ai_mark_in_every_published_file(
    cover_album_app: tuple[TestClient, object], tmp_path: Path,
) -> None:
    client, factory = cover_album_app
    suggestion_id = _add_suggestion(factory, tmp_path / "audio")

    selected = client.put("/api/albums/alice-album/cover", json={"suggestion_id": suggestion_id})

    assert selected.status_code == 200
    published = sorted((tmp_path / "audio" / COVER_DIRNAME / "alice-album").iterdir())
    assert len(published) == 3
    for path in published:
        assert read_digital_source_type(path) == IPTC_TRAINED_ALGORITHMIC_MEDIA, path.name


def test_discard_suggestions_keeps_the_selected_cover(
    cover_album_app: tuple[TestClient, object], tmp_path: Path,
) -> None:
    """1301-F3-C1-DURABLE: removing images does not remove usage."""
    client, factory = cover_album_app
    audio_dir = tmp_path / "audio"
    suggestion_id, other_id = _add_two_pending_suggestions(factory, audio_dir)
    assert client.put(
        "/api/albums/alice-album/cover", json={"suggestion_id": suggestion_id},
    ).status_code == 200
    assert _suggestion_file(audio_dir, other_id).is_file()
    cover_dir = tmp_path / "audio" / "covers" / "alice-album"
    assert cover_dir.is_dir()

    discarded = client.delete(
        "/api/albums/alice-album/cover-suggestions",
        params={"suggestion_id": [suggestion_id, other_id]},
    )

    assert discarded.status_code == 200
    assert client.get("/api/albums/alice-album").json()["cover"] is not None
    assert cover_dir.is_dir()
    assert client.get("/api/albums/alice-album/cover-suggestions").json()["suggestions"] == []
    assert not (audio_dir / ALBUM_COVER_SUGGESTIONS_DIRNAME / "alice-album").exists()
    assert client.get("/api/albums/alice-album/cover-suggestions").json()["used_today"] == 2


def _suggestion_ids_left(factory) -> set[str]:
    with factory() as session:
        return {suggestion.id for suggestion in session.query(AlbumCoverSuggestion)}


def _job_of(factory, suggestion_id: str) -> str:
    with factory() as session:
        return session.query(AlbumCoverSuggestion).filter_by(id=suggestion_id).one().job_id


@pytest.mark.parametrize("named_by", ["suggestion_id", "job_id"])
def test_discard_deletes_only_what_it_names(
    cover_album_app: tuple[TestClient, object], tmp_path: Path, named_by: str,
) -> None:
    """A suggestion asked for after the discard, here or in another tab, survives it."""
    client, factory = cover_album_app
    audio_dir = tmp_path / "audio"
    discarded_id = _add_suggestion(factory, audio_dir, suggestion_id="a" * 36)
    later_id = _add_suggestion(factory, audio_dir, suggestion_id="b" * 36)
    named = discarded_id if named_by == "suggestion_id" else _job_of(factory, discarded_id)

    response = client.delete(
        "/api/albums/alice-album/cover-suggestions", params={named_by: named},
    )

    assert response.status_code == 200
    assert _suggestion_ids_left(factory) == {later_id}
    assert not _suggestion_file(audio_dir, discarded_id).exists()
    assert _suggestion_file(audio_dir, later_id).is_file()


@pytest.mark.parametrize("named_by", ["suggestion_id", "job_id"])
def test_discard_never_deletes_another_albums_suggestion(
    cover_album_app: tuple[TestClient, object], tmp_path: Path, named_by: str,
) -> None:
    client, factory = cover_album_app
    foreign_id = _add_suggestion(factory, tmp_path / "audio", album_id="bob-album")
    named = foreign_id if named_by == "suggestion_id" else _job_of(factory, foreign_id)

    response = client.delete(
        "/api/albums/alice-album/cover-suggestions", params={named_by: named},
    )

    assert response.status_code == 200
    assert _suggestion_ids_left(factory) == {foreign_id}


def test_discard_naming_nothing_is_refused(
    cover_album_app: tuple[TestClient, object], tmp_path: Path,
) -> None:
    client, factory = cover_album_app
    suggestion_id = _add_suggestion(factory, tmp_path / "audio")

    response = client.delete("/api/albums/alice-album/cover-suggestions")

    assert response.status_code == 422
    assert _suggestion_ids_left(factory) == {suggestion_id}


def test_delete_selected_cover_keeps_suggestions(
    cover_album_app: tuple[TestClient, object], tmp_path: Path,
) -> None:
    client, factory = cover_album_app
    suggestion_id = _add_suggestion(factory, tmp_path / "audio")
    assert client.put(
        "/api/albums/alice-album/cover", json={"suggestion_id": suggestion_id},
    ).status_code == 200

    deleted = client.delete("/api/albums/alice-album/cover")

    assert deleted.status_code == 200
    assert (
        tmp_path / "audio" / ALBUM_COVER_SUGGESTIONS_DIRNAME / "alice-album"
        / f"{suggestion_id}.png"
    ).is_file()


def test_put_cover_rejects_an_upload_without_changing_the_cover(
    cover_album_app: tuple[TestClient, object], tmp_path: Path,
) -> None:
    client, factory = cover_album_app

    response = client.put(
        "/api/albums/alice-album/cover",
        files={"file": ("cover.png", _png_bytes(), "image/png")},
    )

    assert response.status_code == 422
    with factory() as session:
        album = session.get(Album, "alice-album")
        assert album is not None
        assert album.cover_key is None
    assert not (tmp_path / "audio" / "covers" / "alice-album").exists()


def test_put_cover_keeps_json_requests_within_the_standard_body_budget(
    cover_album_app: tuple[TestClient, object],
) -> None:
    client, _ = cover_album_app
    payload = json.dumps({
        "suggestion_id": "a" * 36,
        "padding": "x" * JSON_REQUEST_BODY_MAX_BYTES,
    })

    response = client.put(
        "/api/albums/alice-album/cover",
        content=payload,
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json() == {"detail": "Request body too large"}


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("get", "/api/albums/alice-album/cover-suggestions", {}),
        ("post", "/api/albums/alice-album/cover-suggestions", {}),
        ("get", "/api/albums/alice-album/cover-suggestions/" + "a" * 36, {}),
        ("put", "/api/albums/alice-album/cover", {"json": {"suggestion_id": "a" * 36}}),
        (
            "delete",
            "/api/albums/alice-album/cover-suggestions",
            {"params": {"suggestion_id": "a" * 36}},
        ),
    ],
)
def test_foreign_cover_suggestion_routes_are_not_found(
    tmp_path: Path,
    method: str,
    path: str,
    kwargs: dict, pg_factory,
) -> None:
    client, factory = make_test_app(tmp_path, seed_db=seed_cover_albums, factory=pg_factory)
    _add_suggestion(factory, tmp_path / "audio")
    with factory() as session:
        bob_id = session.query(User).filter_by(username="bob").one().id
    attach_cowriter_gateway(client, factory, tmp_path, bob_id)

    foreign = getattr(client, method)(path, **kwargs)

    assert foreign.status_code == 404
    assert foreign.json() == {"detail": "Not Found"}


def test_cover_suggestions_have_no_public_share_route(
    cover_album_app: tuple[TestClient, object],
) -> None:
    client, _ = cover_album_app

    response = client.get("/shared/album-slug/cover-suggestions")

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


@pytest.mark.parametrize(
    ("method", "path_for", "kwargs_for"),
    [
        ("get", lambda sid: f"/api/albums/alice-album/cover-suggestions/{sid}", lambda sid: {}),
        (
            "put",
            lambda sid: "/api/albums/alice-album/cover",
            lambda sid: {"json": {"suggestion_id": sid}},
        ),
    ],
)
def test_full_app_answers_a_suggestion_outside_the_audio_root_like_a_missing_one(
    cover_album_app: tuple[TestClient, object], tmp_path: Path, method: str, path_for, kwargs_for,
) -> None:
    client, factory = cover_album_app
    audio_dir = tmp_path / "audio"
    suggestion_id = _add_suggestion(factory, audio_dir)
    album_dir = audio_dir / ALBUM_COVER_SUGGESTIONS_DIRNAME / "alice-album"
    album_dir.rename(tmp_path / "moved-album")
    album_dir.symlink_to(tmp_path / "moved-album", target_is_directory=True)
    missing_id = "b" * 36

    rejected = getattr(client, method)(path_for(suggestion_id), **kwargs_for(suggestion_id))
    missing = getattr(client, method)(path_for(missing_id), **kwargs_for(missing_id))

    assert rejected.status_code == missing.status_code == 404
    assert rejected.json() == missing.json() == {"detail": "Not Found"}


def test_owner_cannot_distinguish_missing_and_traversal_suggestions(
    cover_album_app: tuple[TestClient, object],
) -> None:
    client, factory = cover_album_app

    missing = client.get("/api/albums/alice-album/cover-suggestions/missing")
    traversal = client.get(
        "/api/albums/alice-album/cover-suggestions/%2E%2E%2Foutside.png",
    )

    assert missing.status_code == traversal.status_code == 404
    assert missing.json() == traversal.json() == {"detail": "Not Found"}
    with factory() as session:
        assert session.query(AlbumCoverSuggestion).count() == 0


ESCAPING_STORED_PATH = "../outside.png"


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("get", "/api/albums/alice-album/cover-suggestions/" + "a" * 36, {}),
        ("put", "/api/albums/alice-album/cover", {"json": {"suggestion_id": "a" * 36}}),
    ],
)
def test_a_suggestion_resolving_outside_the_audio_root_answers_like_a_missing_suggestion(
    tmp_path: Path, method: str, path: str, kwargs: dict, pg_factory,
) -> None:
    # The router app keeps the endpoint's own detail; create_app rewrites every API 404.
    with pg_factory() as session:
        seed_cover_albums(session)
        session.commit()
        owner = album_owner(session)
    audio_dir = tmp_path / "audio"
    _add_suggestion(pg_factory, audio_dir)
    album_dir = audio_dir / ALBUM_COVER_SUGGESTIONS_DIRNAME / "alice-album"
    album_dir.rename(tmp_path / "moved-album")
    album_dir.symlink_to(tmp_path / "moved-album", target_is_directory=True)
    client = web_client(make_router_app(make_router_ctx(tmp_path, db=pg_factory), user=owner))

    response = getattr(client, method)(path, **kwargs)

    assert response.status_code == 404
    assert response.json() == {"detail": COVER_SUGGESTION_NOT_FOUND}


def test_discarding_suggestions_with_a_path_outside_the_audio_root_leaves_that_file(
    cover_album_app: tuple[TestClient, object], tmp_path: Path,
) -> None:
    client, factory = cover_album_app
    audio_dir = tmp_path / "audio"
    kept_id = _add_suggestion(factory, audio_dir, suggestion_id="b" * 36)
    escaping_id = _add_suggestion(factory, audio_dir, stored_path=ESCAPING_STORED_PATH)
    outside = tmp_path / "outside.png"
    outside.write_bytes(_png_bytes())

    response = client.delete(
        "/api/albums/alice-album/cover-suggestions",
        params={"suggestion_id": [kept_id, escaping_id]},
    )

    assert response.status_code == 200
    assert outside.read_bytes() == _png_bytes()
    assert not _suggestion_file(audio_dir, kept_id).exists()
    with factory() as session:
        assert session.query(AlbumCoverSuggestion).count() == 0


def test_admin_can_list_and_read_another_users_suggestion(tmp_path: Path, pg_factory) -> None:
    client, factory = make_test_app(tmp_path, seed_db=seed_cover_albums, factory=pg_factory)
    suggestion_id = _add_suggestion(factory, tmp_path / "audio")
    seed_session(client, "admin")

    listed = client.get("/api/albums/alice-album/cover-suggestions")
    fetched = client.get(
        f"/api/albums/alice-album/cover-suggestions/{suggestion_id}",
    )

    assert listed.status_code == 200
    assert listed.json()["suggestions"][0]["id"] == suggestion_id
    assert fetched.status_code == 200
    assert fetched.content == _png_bytes()


def test_active_cover_job_blocks_a_new_request_before_unavailable_response(
    cover_album_app: tuple[TestClient, object],
) -> None:
    client, factory = cover_album_app
    _add_cover_job(factory)

    response = client.post("/api/albums/alice-album/cover-suggestions")

    assert response.status_code == 409
    assert response.json() == {"detail": "Cover suggestions are already being generated"}
    with factory() as session:
        assert session.query(Job).filter_by(album_id="alice-album").count() == 1


@pytest.mark.parametrize("status", list(JobStatus))
@pytest.mark.parametrize("offset", [-1, 0, 1])
def test_only_completed_cover_jobs_on_this_utc_day_count(
    tmp_path: Path, status: JobStatus, offset: int, pg_factory,
) -> None:
    """1301-F3-C1-COUNT: status and the start-day boundary decide usage."""
    midnight = datetime(2026, 9, 4, tzinfo=timezone.utc)
    with pg_factory() as session:
        seed_cover_albums(session)
        session.commit()
    _add_cover_job(pg_factory, status=status, started_at=midnight + timedelta(microseconds=offset))
    with pg_factory() as session:
        assert count_cover_jobs_since(session, "alice-album", midnight) == int(
            status == JobStatus.COMPLETED and offset >= 0
        )


def test_hard_delete_cleanup_removes_suggestions_from_expired_albums(
    cover_album_app: tuple[TestClient, object], tmp_path: Path,
) -> None:
    """1301-F3-C1-DURABLE: removing images does not remove usage."""
    client, factory = cover_album_app
    _add_suggestion(factory, tmp_path / "audio")
    suggestion_dir = tmp_path / "audio" / ALBUM_COVER_SUGGESTIONS_DIRNAME / "alice-album"

    assert client.delete("/api/albums/alice-album").status_code == 200
    with factory() as session:
        album = get_album(session, "alice-album", include_deleted_rows=True)
        assert album is not None
        album.deleted_at = datetime.now(timezone.utc) - timedelta(days=366)
        session.commit()

    album_count, song_count = run_cleanup_expired(factory, tmp_path / "audio")

    assert (album_count, song_count) == (1, 0)
    assert not suggestion_dir.exists()
    with factory() as session:
        job = session.query(Job).filter_by(type=JobType.COVER).one()
        assert job.album_id is None
        assert job.user_id is not None
        assert job.status == JobStatus.COMPLETED
        assert job.started_at is not None


@pytest.mark.parametrize("album_id", ["../outside", "nested/album", "..", "/abs"])
def test_album_suggestion_cleanup_skips_a_malformed_album_id(
    tmp_path: Path, album_id: str,
) -> None:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.png").write_bytes(b"keep")
    suggestions = audio_dir / ALBUM_COVER_SUGGESTIONS_DIRNAME
    (suggestions / "alice-album").mkdir(parents=True)
    (suggestions / "alice-album" / "keep.png").write_bytes(b"keep")

    remove_album_cover_suggestion_files(audio_dir, album_id)

    assert (outside / "keep.png").read_bytes() == b"keep"
    assert (suggestions / "alice-album" / "keep.png").read_bytes() == b"keep"


def test_suggestion_cleanup_refuses_paths_outside_its_private_tree(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    marker = tmp_path / "marker.png"
    marker.write_bytes(_png_bytes())

    remove_cover_suggestion_files(audio_dir, ["../marker.png", "covers/album/original.png"])

    assert marker.exists()
