"""A take job remembers its version, and a version a queued or running job uses is not deleted."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from support.generation_job_world import worker_up
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
from songmaker_cli.db.models import (
    Album,
    AvailableModel,
    Generation,
    Job,
    ReferenceRecording,
    Song,
    User,
    Version,
)
from songmaker_cli.db.queries.albums import delete_album
from songmaker_cli.db.queries.jobs import JobStatusUpdate, create_job, update_job_status
from songmaker_cli.db.queries.songs import delete_song
from songmaker_cli.mcp_server.tools import tool_rename_song, tool_update_song_lyrics

OWNER_ID = "owner"
OWNER = make_authenticated_user(OWNER_ID, username="owner")
IN_USE_DETAIL = "This version has a take rendering; wait for it to finish or cancel it."
TERMINAL_STATUSES = [
    JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.PARTIAL, JobStatus.CANCELLED,
]


def _seed(session) -> None:
    session.add(User(id=OWNER_ID, username="owner", role="user"))
    session.flush()
    session.add(ReferenceRecording(
        id="reference", user_id=OWNER_ID, storage_path="owner/reference.wav",
        original_filename="reference.wav", size_bytes=4,
    ))
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
    assert response.json()["version_id"] == _job_version(client, response.json()["id"])
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
    with _database(client) as session:
        redis = make_fake_redis()
        with pytest.raises(HTTPException) as refusal:
            create_job_with_rate_limit(
                session, OWNER, JobType.GENERATE, song_id="song", version_id=version_id,
                redis=redis,
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


CREATIVE_EDITS = {
    "lyrics": {"lyrics": "edited lyrics"},
    "prompt": {"prompt": "edited prompt"},
    "bpm": {"bpm": 120},
    "length": {"audio_duration": 90},
    "key": {"key_scale": "C major"},
}
PARAMETER_EDITS = {
    "generation params": {"generation_params": {"inference_steps": 50}},
    "reference": {"reference_recording_id": "reference"},
}
TAKE_PARAMS = {"inference_steps": 25}
VERSION_FIELDS = (
    "lyrics", "prompt", "bpm", "audio_duration", "key_scale", "generation_params",
    "reference_recording_id",
)


def _versions(client: TestClient) -> dict[int, dict]:
    """Version number to its id and content."""
    with _database(client) as session:
        return {
            version.version_number: {
                "id": version.id, **{field: getattr(version, field) for field in VERSION_FIELDS},
            }
            for version in session.query(Version).filter_by(song_id="song")
        }


def _save(client: TestClient, **body) -> None:
    assert client.put("/api/songs/song", json=body).status_code == 200


def _give_take_to_latest(client: TestClient) -> None:
    with _database(client) as session:
        session.add(Generation(
            id="latest-take", song_id="song", version_id="v2", generation_number=3,
            mp3_path="u/latest.mp3", generation_params=TAKE_PARAMS,
            reference_recording_id="reference",
        ))
        session.commit()


def _holds(version: dict, edit: dict) -> bool:
    return all(version[field] == value for field, value in edit.items())


@pytest.mark.parametrize(
    "edit", [*CREATIVE_EDITS.values(), *PARAMETER_EDITS.values()],
    ids=[*CREATIVE_EDITS, *PARAMETER_EDITS],
)
def test_v1_v2_a_latest_without_take_or_job_is_rewritten_in_place(client, edit):
    _save(client, **edit)

    versions = _versions(client)
    assert set(versions) == {1, 2}
    assert versions[2]["id"] == "v2"
    assert _holds(versions[2], edit)


@pytest.mark.parametrize("edit", CREATIVE_EDITS.values(), ids=list(CREATIVE_EDITS))
def test_v3_a_creative_edit_of_a_version_with_a_take_makes_the_next_version(client, edit):
    _give_take_to_latest(client)
    before = _versions(client)[2]

    _save(client, **edit)

    versions = _versions(client)
    assert set(versions) == {1, 2, 3}
    assert _holds(versions[3], edit)
    assert versions[2] == before


@pytest.mark.parametrize("edit", PARAMETER_EDITS.values(), ids=list(PARAMETER_EDITS))
def test_v4_a_parameters_only_edit_of_a_version_with_a_take_rewrites_it(client, edit):
    _give_take_to_latest(client)

    _save(client, **edit)

    versions = _versions(client)
    assert set(versions) == {1, 2}
    assert _holds(versions[2], edit)
    with _database(client) as session:
        take = session.get(Generation, "latest-take")
        assert (take.generation_params, take.reference_recording_id) == (TAKE_PARAMS, "reference")


@pytest.mark.parametrize("status", [JobStatus.QUEUED, JobStatus.RUNNING])
@pytest.mark.parametrize(
    "edit", [*CREATIVE_EDITS.values(), *PARAMETER_EDITS.values()],
    ids=[*CREATIVE_EDITS, *PARAMETER_EDITS],
)
@pytest.mark.parametrize("with_take", [False, True], ids=["no take", "with take"])
def test_v5_v6_v7_an_edit_during_a_render_makes_the_next_version_and_spares_the_rendered_one(
    client, status, edit, with_take,
):
    if with_take:
        _give_take_to_latest(client)
    before = _versions(client)[2]
    job_id = _add_job(client, "v2", status)

    _save(client, **edit)

    versions = _versions(client)
    assert set(versions) == {1, 2, 3}
    assert _holds(versions[3], edit)
    assert versions[2] == before
    assert _job_version(client, job_id) == "v2"


def test_v8_a_save_that_changes_nothing_during_a_render_makes_no_version(client):
    before = _versions(client)
    _add_job(client, "v2")

    _save(client, lyrics="two", prompt="rock")

    assert _versions(client) == before


@pytest.mark.parametrize(
    "job_version, status",
    [("v1", JobStatus.QUEUED), *(("v2", status) for status in TERMINAL_STATUSES)],
    ids=["older version", *TERMINAL_STATUSES],
)
def test_v9_v10_a_job_that_does_not_render_the_latest_leaves_it_rewritten_in_place(
    client, job_version, status,
):
    _add_job(client, job_version, status)

    _save(client, lyrics="edited lyrics")

    versions = _versions(client)
    assert set(versions) == {1, 2}
    assert versions[2]["lyrics"] == "edited lyrics"


def test_c1_a_co_writer_write_during_a_render_makes_a_version_and_spares_the_rendered_one(client):
    before = _versions(client)[2]
    job_id = _add_job(client, "v2")
    with _database(client) as session:
        tool_update_song_lyrics(session, OWNER, "song", "co-written")
        tool_rename_song(session, OWNER, "song", "Renamed")
        session.commit()

    versions = _versions(client)
    assert set(versions) == {1, 2, 3, 4}
    assert versions[2] == before
    assert versions[3]["lyrics"] == "co-written"
    assert _job_version(client, job_id) == "v2"
