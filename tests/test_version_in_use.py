"""A take job remembers its version, and a version a queued or running job uses is not deleted."""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from support.web_app import (
    make_authenticated_user,
    make_fake_redis,
    make_router_app,
    make_router_ctx,
    web_client,
)

from songmaker_cli.api_helpers import create_job_with_rate_limit
from songmaker_cli.constants import JobStatus, JobType
from songmaker_cli.db.engine import init_test_db
from songmaker_cli.db.models import Album, AvailableModel, Generation, Job, Song, User, Version
from songmaker_cli.db.queries.albums import delete_album
from songmaker_cli.db.queries.jobs import JobStatusUpdate, create_job, update_job_status
from songmaker_cli.db.queries.songs import delete_song

OWNER_ID = "owner"
OWNER = make_authenticated_user(OWNER_ID, username="owner")
IN_USE_DETAIL = "This version has a take rendering; wait for it to finish or cancel it."
TERMINAL_STATUSES = [
    JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.PARTIAL, JobStatus.CANCELLED,
]


def _seed(session) -> None:
    session.add(User(id=OWNER_ID, username="owner", role="user"))
    session.flush()
    session.add(Album(id="album", title="A", artist="B", created_by=OWNER_ID))
    session.add(Song(id="song", title="S", album_id="album", track_number=1, slug="s"))
    session.add(Song(id="other-song", title="O", album_id="album", track_number=2, slug="o"))
    session.flush()
    session.add_all([
        Version(id="v1", song_id="song", version_number=1, lyrics="one", prompt="rock"),
        Version(id="v2", song_id="song", version_number=2, lyrics="two", prompt="rock"),
        Version(
            id="other-version", song_id="other-song", version_number=1, lyrics="x", prompt="y",
        ),
    ])
    session.flush()
    session.add_all([
        Generation(
            id="take", song_id="song", version_id="v1", generation_number=1,
            mp3_path="u/take.mp3", wav_path="u/take.wav",
        ),
        Generation(
            id="take-two", song_id="song", version_id="v1", generation_number=2,
            mp3_path="u/take-two.mp3",
        ),
    ])
    session.query(AvailableModel).filter(AvailableModel.id.in_(["sft"])).update(
        {"is_active": True}, synchronize_session=False,
    )


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    factory = init_test_db(tmp_path / "test.db")
    ctx = make_router_ctx(tmp_path, db=factory, seed_db=_seed)
    wav = tmp_path / "audio" / "u" / "take.wav"
    wav.parent.mkdir(parents=True)
    wav.write_bytes(b"RIFF" + b"\x00" * 40)
    return web_client(make_router_app(ctx, user=OWNER))


def _database(client: TestClient):
    return client.app.state.ctx.db()


def _add_job(client: TestClient, version_id: str | None, status: str = JobStatus.QUEUED) -> str:
    with _database(client) as session:
        job = create_job(
            session, JobType.GENERATE, user_id=OWNER_ID, song_id="song", version_id=version_id,
        )
        if status != JobStatus.QUEUED:
            update_job_status(session, job.id, JobStatusUpdate(status))
        session.commit()
        return job.id


def _job_version(client: TestClient, job_id: str) -> str | None:
    with _database(client) as session:
        return session.get(Job, job_id).version_id


def _version_ids(client: TestClient) -> set[str]:
    with _database(client) as session:
        return {version.id for version in session.query(Version).filter_by(song_id="song")}


def worker_up() -> ExitStack:
    stack = ExitStack()
    stack.enter_context(
        patch("songmaker_cli.generation_api.get_arq_pool", return_value=AsyncMock()),
    )
    for health in (
        "is_music_worker_healthy", "is_scoring_worker_healthy", "_has_online_acestep_worker",
    ):
        stack.enter_context(
            patch(f"songmaker_cli.generation_api.{health}", AsyncMock(return_value=True)),
        )
    return stack


TAKE_JOB_REQUESTS = {
    "generate the latest version": (
        "/api/songs/song/generate", {"count": 1, "model": "sft"}, "v2",
    ),
    "generate a named version": (
        "/api/songs/song/generate", {"count": 1, "model": "sft", "version_id": "v1"}, "v1",
    ),
    "repaint": (
        "/api/generations/take/repaint",
        {"src_generation_id": "take", "repainting_start": 0.0, "repainting_end": 0.5,
         "model": "sft"},
        "v1",
    ),
    "cover": (
        "/api/generations/take/cover",
        {"src_generation_id": "take", "audio_cover_strength": 0.7, "model": "sft"},
        "v1",
    ),
}


@pytest.mark.parametrize("request_name", list(TAKE_JOB_REQUESTS))
def test_m1_a_take_job_row_holds_the_version_the_endpoint_resolved(client, request_name):
    path, body, expected_version = TAKE_JOB_REQUESTS[request_name]
    with worker_up():
        response = client.post(path, json=body)
    assert response.status_code == 200
    assert _job_version(client, response.json()["id"]) == expected_version


@pytest.mark.parametrize("status", [JobStatus.QUEUED, JobStatus.RUNNING])
@pytest.mark.parametrize("version_id", ["v1", "v2"], ids=["with takes", "without takes"])
@pytest.mark.parametrize("delete_generations", [True, False])
def test_m2_a_version_an_active_job_references_answers_409_and_changes_nothing(
    client, status, version_id, delete_generations,
):
    job_id = _add_job(client, version_id, status)

    response = client.delete(
        f"/api/versions/{version_id}", params={"delete_generations": delete_generations},
    )

    assert response.status_code == 409
    assert response.json() == {"detail": IN_USE_DETAIL}
    assert version_id in _version_ids(client)
    assert _job_version(client, job_id) == version_id
    with _database(client) as session:
        assert session.query(Generation).filter_by(version_id="v1").count() == 2


@pytest.mark.parametrize("status", [JobStatus.QUEUED, JobStatus.RUNNING])
def test_m2b_a_version_deletes_while_another_version_of_the_song_has_an_active_job(
    client, status,
):
    job_id = _add_job(client, "v1", status)

    response = client.delete("/api/versions/v2")

    assert response.status_code == 200
    assert _version_ids(client) == {"v1"}
    assert _job_version(client, job_id) == "v1"


@pytest.mark.parametrize("status", TERMINAL_STATUSES)
def test_m3a_a_version_without_takes_deletes_when_its_jobs_are_terminal(client, status):
    job_id = _add_job(client, "v2", status)

    response = client.delete("/api/versions/v2")

    assert response.status_code == 200
    assert _version_ids(client) == {"v1"}
    assert _job_version(client, job_id) is None


def test_m3b_a_version_with_finished_takes_and_no_active_job_deletes_and_unlinks_its_takes(
    client,
):
    response = client.delete("/api/versions/v1")

    assert response.status_code == 200
    with _database(client) as session:
        assert {g.version_id for g in session.query(Generation)} == {None}


def test_m6_a_job_that_names_no_version_holds_none(client):
    with _database(client) as session:
        job = create_job_with_rate_limit(
            session, OWNER, JobType.SCORE, redis=make_fake_redis(),
        )
        session.commit()
        assert job.version_id is None


@pytest.mark.parametrize("version_id", ["missing", "other-version"], ids=["gone", "other song"])
def test_a_job_for_a_version_that_is_gone_or_belongs_to_another_song_answers_404_and_leaves_no_job(
    client, version_id,
):
    with _database(client) as session, pytest.raises(HTTPException) as refusal:
        create_job_with_rate_limit(
            session, OWNER, JobType.GENERATE, song_id="song", version_id=version_id,
            redis=make_fake_redis(),
        )
    assert (refusal.value.status_code, refusal.value.detail) == (404, "Version not found")
    with _database(client) as session:
        assert session.query(Job).count() == 0


def test_m8_purging_a_song_or_an_album_succeeds_with_old_jobs_on_its_versions(client):
    job_id = _add_job(client, "v1", JobStatus.COMPLETED)
    other_id = _add_job(client, "other-version", JobStatus.FAILED)

    with _database(client) as session:
        delete_song(session, "other-song")
        session.commit()
    assert _job_version(client, other_id) is None

    with _database(client) as session:
        delete_album(session, "album")
        session.commit()
    assert _job_version(client, job_id) is None
