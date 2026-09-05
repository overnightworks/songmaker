"""Integration tests for the REST API endpoints."""

from __future__ import annotations

import asyncio
import logging
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from conftest import TEST_SECRET, make_fake_redis
from fastapi import FastAPI
from fastapi.testclient import TestClient

from songmaker_cli.app_context import AppContext
from songmaker_cli.constants import GZIP_COMPRESS_LEVEL, GZIP_MINIMUM_SIZE_BYTES
from songmaker_cli.db.engine import init_test_db as init_db
from songmaker_cli.db.models import (
    SONG_SLUG_MAX_LENGTH,
    Album,
    AvailableModel,
    Generation,
    Job,
    Score,
    Song,
    User,
    Version,
)
from songmaker_cli.middleware import (
    SESSION_COOKIE,
    AuthenticatedUser,
    SelectiveGZipMiddleware,
    get_current_user,
)

_DEFAULT_USER_ID = "u-test"


def _fake_user(user_id: str, username: str, role: str):
    """Return a dependency override for get_current_user."""
    user = AuthenticatedUser(id=user_id, username=username, role=role, is_active=True)
    return lambda: user


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    factory = init_db(tmp_path / "test.db")
    with factory() as session:
        session.add(User(
            id=_DEFAULT_USER_ID, username="test_user",
            password_hash="unused", role="user",
        ))
        session.flush()
        _seed_db(session, owner_id=_DEFAULT_USER_ID)

    audio_dir = tmp_path / "audio"
    wav_dir = audio_dir / "u-test"
    wav_dir.mkdir(parents=True, exist_ok=True)
    (wav_dir / "g1.wav").write_bytes(b"RIFF" + b"\x00" * 40)

    ctx = AppContext(
        db=factory,
        audio_dir=audio_dir,
        data_dir=tmp_path / "data",
        session_secret=TEST_SECRET,
        redis=make_fake_redis(),
    )
    from songmaker_cli.api import router
    app = FastAPI()
    app.state.ctx = ctx
    app.dependency_overrides[get_current_user] = _fake_user(
        _DEFAULT_USER_ID, "test_user", "user",
    )
    app.include_router(router)
    yield TestClient(app)


@pytest.fixture
def unauthed_client(tmp_path: Path) -> TestClient:
    factory = init_db(tmp_path / "test.db")
    with factory() as session:
        _seed_db(session)

    ctx = AppContext(
        db=factory,
        audio_dir=tmp_path / "audio",
        data_dir=tmp_path / "data",
        session_secret=TEST_SECRET,
        redis=make_fake_redis(),
    )
    from songmaker_cli.api import router
    app = FastAPI()
    app.state.ctx = ctx
    app.include_router(router)
    yield TestClient(app)


def _whisper_cues_payload(word_count: int) -> list[dict]:
    """A realistic word-level Whisper transcript, sized like a real take.

    Mirrors the shape ACE-Step scoring actually stores: one segment per line,
    each carrying its own word timestamps -- this is the field issue #172
    measured at ~22 KB raw per take.
    """
    words = [
        {"start": i * 0.4, "end": i * 0.4 + 0.35, "text": f"word{i}"}
        for i in range(word_count)
    ]
    segment_size = 8
    return [
        {
            "start": segment[0]["start"],
            "end": segment[-1]["end"],
            "text": " ".join(w["text"] for w in segment),
            "words": segment,
        }
        for segment in (
            words[i:i + segment_size] for i in range(0, len(words), segment_size)
        )
    ]


@pytest.fixture
def gzip_client(tmp_path: Path) -> TestClient:
    """Same wiring as `client`, plus the real gzip middleware under test.

    Seeds gen1's `whisper_cues` with a realistic-size transcript so the
    `/api/songs/s1` payload matches the share-page scenario issue #172
    measured (~22 KB raw per take of word-level Whisper cues).
    """
    factory = init_db(tmp_path / "test.db")
    with factory() as session:
        session.add(User(
            id=_DEFAULT_USER_ID, username="test_user",
            password_hash="unused", role="user",
        ))
        session.flush()
        _seed_db(session, owner_id=_DEFAULT_USER_ID)
        gen1 = session.get(Generation, "g1")
        gen1.whisper_text = " ".join(f"word{i}" for i in range(300))
        gen1.whisper_cues = _whisper_cues_payload(300)
        session.commit()

    ctx = AppContext(
        db=factory,
        audio_dir=tmp_path / "audio",
        data_dir=tmp_path / "data",
        session_secret=TEST_SECRET,
        redis=make_fake_redis(),
    )
    from songmaker_cli.api import router
    app = FastAPI()
    app.state.ctx = ctx
    app.dependency_overrides[get_current_user] = _fake_user(
        _DEFAULT_USER_ID, "test_user", "user",
    )
    app.include_router(router)
    app.add_middleware(
        SelectiveGZipMiddleware,
        minimum_size=GZIP_MINIMUM_SIZE_BYTES,
        compresslevel=GZIP_COMPRESS_LEVEL,
    )
    yield TestClient(app)


def test_song_detail_response_is_gzip_compressed(gzip_client: TestClient) -> None:
    resp = gzip_client.get("/api/songs/s1", headers={"Accept-Encoding": "gzip"})
    assert resp.status_code == 200
    assert resp.headers.get("content-encoding") == "gzip"
    compressed_bytes = int(resp.headers["content-length"])
    decompressed_bytes = len(resp.content)
    assert compressed_bytes < decompressed_bytes


def test_song_detail_response_uncompressed_without_client_support(
    gzip_client: TestClient,
) -> None:
    resp = gzip_client.get("/api/songs/s1", headers={"Accept-Encoding": "identity"})
    assert resp.status_code == 200
    assert "content-encoding" not in resp.headers


def _make_authed_client(
    tmp_path: Path, role: str = "user", user_id: str = "u-test",
) -> TestClient:
    """Create a TestClient with a fake authenticated user injected."""
    factory = init_db(tmp_path / "test.db")
    with factory() as session:
        session.add(User(
            id=user_id, username=f"test_{role}",
            password_hash="unused", role=role,
        ))
        session.flush()
        _seed_db(session, owner_id=user_id if role != "admin" else None)

    ctx = AppContext(
        db=factory,
        audio_dir=tmp_path / "audio",
        data_dir=tmp_path / "data",
        session_secret=TEST_SECRET,
        redis=make_fake_redis(),
    )
    from songmaker_cli.api import router

    app = FastAPI()
    app.state.ctx = ctx
    app.dependency_overrides[get_current_user] = _fake_user(
        user_id, f"test_{role}", role,
    )
    app.include_router(router)
    return TestClient(app)


def _seed_db(session, owner_id: str | None = None) -> None:
    album = Album(id="rock", title="Rock Album", artist="TestBand", created_by=owner_id)
    session.add(album)
    song = Song(id="s1", title="Thunder", album_id="rock", track_number=1, slug="thunder")
    session.add(song)
    ver = Version(id="v1", song_id="s1", version_number=1, lyrics="boom", prompt="hard rock")
    session.add(ver)
    gen1 = Generation(
        id="g1", song_id="s1", version_id="v1", generation_number=1,
        mp3_path="u-test/g1.mp3", wav_path="u-test/g1.wav", seed=42,
        generation_params={"bpm": 140},
    )
    gen2 = Generation(
        id="g2", song_id="s1", version_id="v1", generation_number=2,
        mp3_path="u-test/g2.mp3", seed=77,
    )
    session.add_all([gen1, gen2])
    session.query(AvailableModel).filter(
        AvailableModel.id.in_(["turbo", "sft"]),
    ).update({"is_active": True}, synchronize_session=False)
    score = Score(id="sc1", generation_id="g1", scorer="batch", value={"dynamics": 65.0})
    session.add(score)
    session.commit()


def test_list_albums(client: TestClient) -> None:
    resp = client.get("/api/albums")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1
    assert data["total"] == 1
    assert data["offset"] == 0


def test_list_songs(client: TestClient) -> None:
    resp = client.get("/api/songs")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["generation_count"] == 2
    assert data["total"] == 1


def test_get_song(client: TestClient) -> None:
    resp = client.get("/api/songs/s1")
    assert resp.status_code == 200
    d = resp.json()
    assert d["title"] == "Thunder"
    assert len(d["generations"]) == 2


def test_get_song_includes_source_take_version_for_provenance(client: TestClient) -> None:
    with client.app.state.ctx.db() as session:
        session.add(Generation(
            id="g3", song_id="s1", version_id="v1", generation_number=3,
            mp3_path="u-test/g3.mp3", src_generation_id="g1",
        ))
        session.commit()

    response = client.get("/api/songs/s1")

    assert response.status_code == 200
    generation = next(item for item in response.json()["generations"] if item["id"] == "g3")
    assert generation["src_generation_id"] == "g1"
    assert generation["src_generation_number"] == 1
    assert generation["src_generation_version_number"] == 1


def test_create_song(client: TestClient) -> None:
    resp = client.post("/api/songs", json={
        "title": "Lightning", "album_id": "rock", "lyrics": "flash", "bpm": 160,
    })
    assert resp.status_code == 200
    assert resp.json()["title"] == "Lightning"


def test_update_song(client: TestClient) -> None:
    resp = client.put("/api/songs/s1", json={"lyrics": "kaboom"})
    assert resp.status_code == 200
    assert resp.json()["version_count"] == 2


def test_rename_song(client: TestClient) -> None:
    resp = client.put("/api/songs/s1/title", json={"title": "Storm"})
    assert resp.status_code == 200
    assert resp.json()["title"] == "Storm"
    after = client.get("/api/songs/s1")
    assert after.json()["title"] == "Storm"
    assert after.json()["version_count"] == 2


def test_rename_song_strips_whitespace(client: TestClient) -> None:
    resp = client.put("/api/songs/s1/title", json={"title": "  Storm  "})
    assert resp.status_code == 200
    assert resp.json()["title"] == "Storm"


def test_rename_song_rejects_empty(client: TestClient) -> None:
    resp = client.put("/api/songs/s1/title", json={"title": ""})
    assert resp.status_code == 422


def test_rename_song_rejects_whitespace_only(client: TestClient) -> None:
    resp = client.put("/api/songs/s1/title", json={"title": "   "})
    assert resp.status_code == 422


def test_rename_song_rejects_too_long(client: TestClient) -> None:
    resp = client.put("/api/songs/s1/title", json={"title": "x" * 201})
    assert resp.status_code == 422


def test_rename_song_not_found(client: TestClient) -> None:
    resp = client.put("/api/songs/nonexistent/title", json={"title": "Storm"})
    assert resp.status_code == 404


def _song_slug(client: TestClient, song_id: str) -> str:
    with client.app.state.ctx.db() as session:
        return session.query(Song).filter_by(id=song_id).one().slug


def _post_song(client: TestClient, title: str, album_id: str = "rock") -> str:
    resp = client.post("/api/songs", json={"title": title, "album_id": album_id})
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def _post_album(client: TestClient, title: str) -> str:
    resp = client.post("/api/albums", json={"title": title, "artist": "TestBand"})
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def test_new_song_gets_a_slug_from_its_title(client: TestClient) -> None:
    song_id = _post_song(client, "Stadion Lauf A!")
    assert _song_slug(client, song_id) == "stadion-lauf-a"


def test_two_songs_titled_alike_in_one_album_get_distinct_slugs(
    client: TestClient,
) -> None:
    first = _post_song(client, "Intro")
    second = _post_song(client, "Intro")
    assert _song_slug(client, first) == "intro"
    assert _song_slug(client, second) == "intro-2"


def test_another_album_may_carry_the_same_song_slug(client: TestClient) -> None:
    other_album = _post_album(client, "Pop Album")
    here = _post_song(client, "Intro")
    there = _post_song(client, "Intro", album_id=other_album)
    assert _song_slug(client, here) == "intro"
    assert _song_slug(client, there) == "intro"


def test_renaming_a_song_pulls_its_slug_along(client: TestClient) -> None:
    song_id = _post_song(client, "Intro")
    resp = client.put(f"/api/songs/{song_id}/title", json={"title": "Outro Reprise"})
    assert resp.status_code == 200
    assert _song_slug(client, song_id) == "outro-reprise"


def test_renaming_a_song_to_its_own_title_keeps_its_slug(client: TestClient) -> None:
    song_id = _post_song(client, "Intro")
    resp = client.put(f"/api/songs/{song_id}/title", json={"title": "Intro"})
    assert resp.status_code == 200
    assert _song_slug(client, song_id) == "intro"


def test_renaming_onto_a_taken_title_yields_a_distinct_slug(client: TestClient) -> None:
    _post_song(client, "Intro")
    latecomer = _post_song(client, "Bridge")
    resp = client.put(f"/api/songs/{latecomer}/title", json={"title": "Intro"})
    assert resp.status_code == 200
    assert _song_slug(client, latecomer) == "intro-2"


def test_moving_a_song_reslugs_it_inside_the_target_album(client: TestClient) -> None:
    target_album = _post_album(client, "Pop Album")
    _post_song(client, "Intro", album_id=target_album)
    travelling = _post_song(client, "Intro")
    assert _song_slug(client, travelling) == "intro"

    resp = client.put(
        f"/api/songs/{travelling}/album", json={"album_id": target_album},
    )
    assert resp.status_code == 200
    assert _song_slug(client, travelling) == "intro-2"


def test_a_soft_deleted_song_keeps_holding_its_slug(client: TestClient) -> None:
    deleted = _post_song(client, "Intro")
    assert client.delete(f"/api/songs/{deleted}").status_code == 200

    successor = _post_song(client, "Intro")
    assert _song_slug(client, successor) == "intro-2"

    assert client.post(f"/api/songs/{deleted}/restore").status_code == 200
    assert _song_slug(client, deleted) == "intro"


def test_a_title_that_transliterates_long_still_fits_the_column(
    client: TestClient,
) -> None:
    """A 200-character CJK title expands to ~800 ASCII characters unslugged."""
    song_id = _post_song(client, "音" * 200)
    slug = _song_slug(client, song_id)
    assert slug.startswith("yin-yin")
    assert len(slug) <= SONG_SLUG_MAX_LENGTH


def test_rename_album(client: TestClient) -> None:
    resp = client.put("/api/albums/rock", json={"title": "Metal Album"})
    assert resp.status_code == 200
    assert resp.json()["title"] == "Metal Album"
    after = client.get("/api/albums/rock")
    assert after.json()["title"] == "Metal Album"


def test_rename_album_strips_whitespace(client: TestClient) -> None:
    resp = client.put("/api/albums/rock", json={"title": "  Metal  "})
    assert resp.status_code == 200
    assert resp.json()["title"] == "Metal"


def test_rename_album_rejects_empty(client: TestClient) -> None:
    resp = client.put("/api/albums/rock", json={"title": ""})
    assert resp.status_code == 422


def test_rename_album_rejects_whitespace_only(client: TestClient) -> None:
    resp = client.put("/api/albums/rock", json={"title": "   "})
    assert resp.status_code == 422


def test_rename_album_rejects_too_long(client: TestClient) -> None:
    resp = client.put("/api/albums/rock", json={"title": "x" * 201})
    assert resp.status_code == 422


def test_rename_album_not_found(client: TestClient) -> None:
    resp = client.put("/api/albums/nonexistent", json={"title": "Metal"})
    assert resp.status_code == 404


def test_rename_song_other_user_blocked(tmp_path: Path) -> None:
    factory = init_db(tmp_path / "test.db")
    with factory() as session:
        session.add(User(
            id="u-test", username="test_user",
            password_hash="unused", role="user",
        ))
        session.add(User(
            id="u-other", username="other_user",
            password_hash="unused", role="user",
        ))
        session.flush()
        session.add(Album(
            id="other", title="Other Album", artist="Them", created_by="u-other",
        ))
        session.add(Song(id="s-other", title="Their Song", album_id="other", track_number=1))
        session.commit()

    ctx = AppContext(
        db=factory,
        audio_dir=tmp_path / "audio",
        data_dir=tmp_path / "data",
        session_secret=TEST_SECRET,
        redis=make_fake_redis(),
    )
    from songmaker_cli.api import router

    app = FastAPI()
    app.state.ctx = ctx
    app.dependency_overrides[get_current_user] = _fake_user("u-test", "test_user", "user")
    app.include_router(router)
    tc = TestClient(app)

    resp = tc.put("/api/songs/s-other/title", json={"title": "Hijacked"})
    assert resp.status_code == 404
    with factory() as session:
        assert session.query(Song).filter_by(id="s-other").first().title == "Their Song"


def test_listen_song_persists_server_timestamp(client: TestClient) -> None:
    with client.app.state.ctx.db() as session:
        song = session.get(Song, "s1")
        assert song is not None
        updated_at_before_listen = song.updated_at

    before = datetime.now(timezone.utc)

    resp = client.post("/api/songs/s1/listen")

    after = datetime.now(timezone.utc)
    assert resp.status_code == 200
    with client.app.state.ctx.db() as session:
        song = session.get(Song, "s1")
        assert song is not None
        assert song.last_played_at is not None
        played_at = song.last_played_at.replace(tzinfo=timezone.utc)
        assert before <= played_at <= after
        assert song.updated_at == updated_at_before_listen


def test_listen_song_rejects_an_unplayable_song(client: TestClient) -> None:
    with client.app.state.ctx.db() as session:
        for generation in session.query(Generation).filter_by(song_id="s1"):
            generation.mp3_path = ""
        session.commit()

    resp = client.post("/api/songs/s1/listen")

    assert resp.status_code == 422
    assert resp.json()["detail"] == "Song is not playable"
    with client.app.state.ctx.db() as session:
        song = session.get(Song, "s1")
        assert song is not None
        assert song.last_played_at is None


def test_listen_song_hides_a_foreign_song(tmp_path: Path) -> None:
    client = _make_authed_client(tmp_path)
    with client.app.state.ctx.db() as session:
        session.add(User(
            id="u-other", username="other_user", password_hash="unused", role="user",
        ))
        session.flush()
        session.add(Album(
            id="other", title="Other Album", artist="Them", created_by="u-other",
        ))
        session.add(Song(
            id="s-other", title="Their Song", album_id="other", track_number=1,
        ))
        session.add(Generation(
            id="g-other", song_id="s-other", generation_number=1,
            mp3_path="u-other/g-other.mp3",
        ))
        session.commit()

    resp = client.post("/api/songs/s-other/listen")

    assert resp.status_code == 404
    with client.app.state.ctx.db() as session:
        song = session.get(Song, "s-other")
        assert song is not None
        assert song.last_played_at is None


def test_rename_album_other_user_blocked(tmp_path: Path) -> None:
    factory = init_db(tmp_path / "test.db")
    with factory() as session:
        session.add(User(
            id="u-test", username="test_user",
            password_hash="unused", role="user",
        ))
        session.add(User(
            id="u-other", username="other_user",
            password_hash="unused", role="user",
        ))
        session.flush()
        session.add(Album(
            id="other", title="Other Album", artist="Them", created_by="u-other",
        ))
        session.commit()

    ctx = AppContext(
        db=factory,
        audio_dir=tmp_path / "audio",
        data_dir=tmp_path / "data",
        session_secret=TEST_SECRET,
        redis=make_fake_redis(),
    )
    from songmaker_cli.api import router

    app = FastAPI()
    app.state.ctx = ctx
    app.dependency_overrides[get_current_user] = _fake_user("u-test", "test_user", "user")
    app.include_router(router)
    tc = TestClient(app)

    resp = tc.put("/api/albums/other", json={"title": "Hijacked"})
    assert resp.status_code == 404
    with factory() as session:
        assert session.query(Album).filter_by(id="other").first().title == "Other Album"


def test_song_versions(client: TestClient) -> None:
    resp = client.get("/api/songs/s1/versions")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["lyrics"] == "boom"


def test_get_generation(client: TestClient) -> None:
    resp = client.get("/api/generations/g1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["seed"] == 42
    assert body["model_mode"] == "sft"
    assert body["whisper_cues"] is None


def test_get_generation_measures_and_persists_audio_duration(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A take that has never had its length measured gets it measured on
    view, and the measurement is persisted (#258) -- not just returned once."""
    import songmaker_cli.queue_streams as qs

    probed: list[Path] = []

    def _read(path: Path) -> float:
        probed.append(path)
        return 188.0

    monkeypatch.setattr(qs, "read_audio_duration", _read)
    resp = client.get("/api/generations/g1")
    assert resp.status_code == 200
    assert resp.json()["audio_duration_sec"] == 188.0
    assert probed == [client.app.state.ctx.audio_dir / "u-test/g1.mp3"]

    monkeypatch.undo()
    resp = client.get("/api/generations/g1")
    assert resp.status_code == 200
    assert resp.json()["audio_duration_sec"] == 188.0


def test_get_generation_reports_unmeasurable_duration_as_null(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unreadable file is reported as unknown, never as a 0-second take."""
    import songmaker_cli.queue_streams as qs

    monkeypatch.setattr(qs, "read_audio_duration", lambda _path: None)
    resp = client.get("/api/generations/g1")
    assert resp.status_code == 200
    assert resp.json()["audio_duration_sec"] is None


def test_get_generation_returns_typed_whisper_cues(client: TestClient) -> None:
    factory = client.app.state.ctx.db
    with factory() as session:
        gen = session.query(Generation).filter_by(id="g1").one()
        gen.whisper_cues = [
            {"start": 0.0, "end": 1.25, "text": "hello world"},
        ]
        gen.whisper_text = "hello world"
        session.commit()

    resp = client.get("/api/generations/g1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["whisper_text"] == "hello world"
    assert body["whisper_cues"] == [
        {"start": 0.0, "end": 1.25, "text": "hello world", "words": None},
    ]


def test_get_generation_returns_word_cues_of_a_take_scored_with_them(
    client: TestClient,
) -> None:
    factory = client.app.state.ctx.db
    with factory() as session:
        gen = session.query(Generation).filter_by(id="g1").one()
        gen.whisper_cues = [{
            "start": 0.0, "end": 1.25, "text": "hello world",
            "words": [
                {"start": 0.0, "end": 0.6, "text": "hello"},
                {"start": 0.6, "end": 1.25, "text": "world"},
            ],
        }]
        session.commit()

    resp = client.get("/api/generations/g1")
    assert resp.status_code == 200
    assert resp.json()["whisper_cues"] == [{
        "start": 0.0, "end": 1.25, "text": "hello world",
        "words": [
            {"start": 0.0, "end": 0.6, "text": "hello"},
            {"start": 0.6, "end": 1.25, "text": "world"},
        ],
    }]


def test_get_generation_whisper_cues_other_user_blocked(tmp_path: Path) -> None:
    factory = init_db(tmp_path / "test.db")
    with factory() as session:
        session.add(User(
            id="u-test", username="test_user",
            password_hash="unused", role="user",
        ))
        session.add(User(
            id="u-other", username="other_user",
            password_hash="unused", role="user",
        ))
        session.flush()
        session.add(Album(
            id="other", title="Other Album", artist="Them", created_by="u-other",
        ))
        session.add(Song(
            id="s-other", title="Their Song", album_id="other", track_number=1,
        ))
        session.add(Version(
            id="v-other", song_id="s-other", version_number=1,
            lyrics="secret", prompt="x",
        ))
        session.add(Generation(
            id="g-other", song_id="s-other", version_id="v-other",
            generation_number=1, mp3_path="u-other/g.mp3", seed=1,
            whisper_cues=[{"start": 0.0, "end": 1.0, "text": "secret"}],
        ))
        session.commit()

    ctx = AppContext(
        db=factory,
        audio_dir=tmp_path / "audio",
        data_dir=tmp_path / "data",
        session_secret=TEST_SECRET,
        redis=make_fake_redis(),
    )
    from songmaker_cli.api import router

    app = FastAPI()
    app.state.ctx = ctx
    app.dependency_overrides[get_current_user] = _fake_user(
        "u-test", "test_user", "user",
    )
    app.include_router(router)
    tc = TestClient(app)

    resp = tc.get("/api/generations/g-other")
    assert resp.status_code == 404
    assert "whisper_cues" not in resp.json()


def test_rate_generation(client: TestClient) -> None:
    resp = client.post("/api/generations/g1/rate", json={"rating": 85.0, "notes": "awesome"})
    assert resp.status_code == 200

    resp = client.get("/api/generations/g1")
    assert resp.json()["scores"]["user_rating"] == 85.0


def test_rate_not_found(client: TestClient) -> None:
    resp = client.post("/api/generations/nonexistent/rate", json={"rating": 50.0})
    assert resp.status_code == 404


def test_rate_invalid(client: TestClient) -> None:
    resp = client.post("/api/generations/g1/rate", json={"rating": 150.0})
    assert resp.status_code == 422


def test_capabilities(client: TestClient) -> None:
    resp = client.get("/api/capabilities")
    assert resp.status_code == 200
    assert "generation" in resp.json()


# ── Delete endpoints ─────────────────────────────────────────────────


def test_delete_generation_api(client: TestClient) -> None:
    resp = client.delete("/api/generations/g2")
    assert resp.status_code == 200
    resp = client.get("/api/generations/g2")
    assert resp.status_code == 404


def test_delete_generation_not_found(client: TestClient) -> None:
    resp = client.delete("/api/generations/nonexistent")
    assert resp.status_code == 404


def test_delete_version_keep_gens(client: TestClient) -> None:
    resp = client.delete("/api/versions/v1?delete_generations=false")
    assert resp.status_code == 200
    resp = client.get("/api/generations/g1")
    assert resp.status_code == 200
    assert resp.json()["version_id"] is None


def test_delete_version_with_gens(client: TestClient) -> None:
    resp = client.delete("/api/versions/v1?delete_generations=true")
    assert resp.status_code == 200
    resp = client.get("/api/generations/g1")
    assert resp.status_code == 404


# ── Pick endpoints ───────────────────────────────────────────────────


def test_pick_generation_api(client: TestClient) -> None:
    resp = client.post("/api/generations/g1/pick")
    assert resp.status_code == 200
    resp = client.get("/api/generations/g1")
    assert resp.json()["is_picked"] is True


@pytest.mark.acceptance("ACC-CURATION-02")
def test_pick_replaces_previous(client: TestClient) -> None:
    first = client.post("/api/generations/g1/pick")
    assert first.status_code == 200
    second = client.post("/api/generations/g2/pick")
    assert second.status_code == 200
    resp = client.get("/api/generations/g1")
    assert resp.json()["is_picked"] is False
    resp = client.get("/api/generations/g2")
    assert resp.json()["is_picked"] is True


def test_unpick_generation_api(client: TestClient) -> None:
    client.post("/api/generations/g1/pick")
    resp = client.post("/api/generations/g1/unpick")
    assert resp.status_code == 200
    resp = client.get("/api/generations/g1")
    assert resp.json()["is_picked"] is False


def test_keep_generation_api(client: TestClient) -> None:
    resp = client.post("/api/generations/g1/keep")
    assert resp.status_code == 200
    resp = client.get("/api/generations/g1")
    assert resp.json()["is_kept"] is True


def test_unkeep_generation_api(client: TestClient) -> None:
    client.post("/api/generations/g1/keep")
    resp = client.post("/api/generations/g1/unkeep")
    assert resp.status_code == 200
    resp = client.get("/api/generations/g1")
    assert resp.json()["is_kept"] is False


def test_unarchive_generation_api(client: TestClient) -> None:
    factory = client.app.state.ctx.db
    from songmaker_cli.db.queries import archive_generation
    with factory() as session:
        archive_generation(session, "g1")
        session.commit()

    resp = client.get("/api/generations/g1")
    assert resp.json()["is_archived"] is True

    resp = client.post("/api/generations/g1/unarchive")
    assert resp.status_code == 200
    resp = client.get("/api/generations/g1")
    body = resp.json()
    assert body["is_archived"] is False
    assert body["archived_at"] is None


def test_unarchive_generation_not_found(client: TestClient) -> None:
    resp = client.post("/api/generations/nonexistent/unarchive")
    assert resp.status_code == 404


def test_cleanup_album_skips_kept_api(client: TestClient) -> None:
    client.post("/api/generations/g1/keep")
    resp = client.post("/api/albums/rock/cleanup")
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 1
    assert client.get("/api/generations/g1").status_code == 200


def test_cleanup_album_api(client: TestClient) -> None:
    client.post("/api/generations/g1/pick")
    resp = client.post("/api/albums/rock/cleanup")
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 1


def test_cleanup_song_api(client: TestClient) -> None:
    client.post("/api/generations/g1/pick")
    resp = client.post("/api/songs/s1/cleanup")
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 1
    assert client.get("/api/generations/g1").status_code == 200
    assert client.get("/api/generations/g2").status_code == 404


def test_cleanup_song_skips_kept(client: TestClient) -> None:
    client.post("/api/generations/g1/keep")
    resp = client.post("/api/songs/s1/cleanup")
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 1
    assert client.get("/api/generations/g1").status_code == 200


def test_cleanup_song_not_found(client: TestClient) -> None:
    resp = client.post("/api/songs/nonexistent/cleanup")
    assert resp.status_code == 404


# ── Job endpoints ────────────────────────────────────────────────────


def test_get_job_not_found(client: TestClient) -> None:
    resp = client.get("/api/jobs/nonexistent")
    assert resp.status_code == 404


# ── Generation params ───────────────────────────────────────────────


def test_create_song_with_generation_params(client: TestClient) -> None:
    resp = client.post("/api/songs", json={
        "title": "Bolt", "album_id": "rock",
        "generation_params": {"inference_steps": 50, "shift": 2.0},
    })
    assert resp.status_code == 200
    assert resp.json()["generation_params"] == {"inference_steps": 50, "shift": 2.0}


def test_create_song_invalid_generation_params(client: TestClient) -> None:
    resp = client.post("/api/songs", json={
        "title": "Bad", "album_id": "rock",
        "generation_params": {"bad_key": 1},
    })
    assert resp.status_code == 422


def test_update_song_sets_generation_params(client: TestClient) -> None:
    resp = client.put("/api/songs/s1", json={
        "generation_params": {"guidance_scale": 5.5},
    })
    assert resp.status_code == 200
    assert resp.json()["generation_params"] == {"guidance_scale": 5.5}


def test_update_song_clears_generation_params(client: TestClient) -> None:
    client.put("/api/songs/s1", json={
        "generation_params": {"inference_steps": 25},
    })
    resp = client.put("/api/songs/s1", json={
        "generation_params": None,
    })
    assert resp.status_code == 200
    assert resp.json()["generation_params"] is None


def test_update_song_omit_keeps_generation_params(client: TestClient) -> None:
    client.put("/api/songs/s1", json={
        "generation_params": {"shift": 4.0},
    })
    resp = client.put("/api/songs/s1", json={"lyrics": "new lyrics"})
    assert resp.status_code == 200
    assert resp.json()["generation_params"] == {"shift": 4.0}


def test_update_song_invalid_generation_params(client: TestClient) -> None:
    resp = client.put("/api/songs/s1", json={
        "generation_params": {"typo_key": 1},
    })
    assert resp.status_code == 422


def test_params_only_update_no_new_version(client: TestClient) -> None:
    resp = client.get("/api/songs/s1/versions")
    version_count_before = len(resp.json())
    version_id_before = resp.json()[0]["id"]

    resp = client.get("/api/songs/s1")
    assert len(resp.json()["generations"]) > 0

    client.put("/api/songs/s1", json={
        "generation_params": {"inference_steps": 100},
    })
    resp = client.get("/api/songs/s1/versions")
    assert len(resp.json()) == version_count_before
    assert resp.json()[0]["id"] == version_id_before
    assert resp.json()[0]["generation_params"] == {"inference_steps": 100}


def test_version_includes_generation_params(client: TestClient) -> None:
    client.put("/api/songs/s1", json={
        "generation_params": {"lm_temperature": 0.5},
    })
    resp = client.get("/api/songs/s1/versions")
    assert resp.status_code == 200
    latest = resp.json()[0]
    assert latest["generation_params"] == {"lm_temperature": 0.5}


# ── Generation defaults ─────────────────────────────────────────────


def test_generation_defaults_roundtrip(tmp_path: Path) -> None:
    c = _make_authed_client(tmp_path, role="admin", user_id="u-admin")

    resp = c.get("/api/settings/generation-defaults")
    assert resp.status_code == 200
    assert resp.json() == {}

    resp = c.put("/api/settings/generation-defaults", json={
        "turbo": {"inference_steps": 12},
        "sft": {"inference_steps": 60},
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["turbo"] == {"inference_steps": 12}
    assert data["sft"] == {"inference_steps": 60}

    resp = c.get("/api/settings/generation-defaults")
    assert resp.json()["turbo"]["inference_steps"] == 12


def test_generation_defaults_rejects_unknown_keys(tmp_path: Path) -> None:
    c = _make_authed_client(tmp_path, role="admin", user_id="u-admin")
    resp = c.put("/api/settings/generation-defaults", json={"turbo": {"bad_key": 1}})
    assert resp.status_code == 422


# ── 404 error branches ──────────────────────────────────────────────


def test_get_album_not_found(client: TestClient) -> None:
    resp = client.get("/api/albums/nonexistent")
    assert resp.status_code == 404


def test_get_song_not_found(client: TestClient) -> None:
    resp = client.get("/api/songs/nonexistent")
    assert resp.status_code == 404


def test_update_song_not_found(client: TestClient) -> None:
    resp = client.put("/api/songs/nonexistent", json={"lyrics": "x"})
    assert resp.status_code == 404


def test_song_versions_not_found(client: TestClient) -> None:
    resp = client.get("/api/songs/nonexistent/versions")
    assert resp.status_code == 404


def test_delete_version_not_found(client: TestClient) -> None:
    resp = client.delete("/api/versions/nonexistent")
    assert resp.status_code == 404


def test_get_generation_not_found(client: TestClient) -> None:
    resp = client.get("/api/generations/nonexistent")
    assert resp.status_code == 404


def test_pick_generation_not_found(client: TestClient) -> None:
    resp = client.post("/api/generations/nonexistent/pick")
    assert resp.status_code == 404


def test_unpick_generation_not_found(client: TestClient) -> None:
    resp = client.post("/api/generations/nonexistent/unpick")
    assert resp.status_code == 404


def test_keep_generation_not_found(client: TestClient) -> None:
    resp = client.post("/api/generations/nonexistent/keep")
    assert resp.status_code == 404


def test_unkeep_generation_not_found(client: TestClient) -> None:
    resp = client.post("/api/generations/nonexistent/unkeep")
    assert resp.status_code == 404


def test_cleanup_album_not_found(client: TestClient) -> None:
    resp = client.post("/api/albums/nonexistent/cleanup")
    assert resp.status_code == 404


def test_rate_generation_not_found(client: TestClient) -> None:
    resp = client.post(
        "/api/generations/nonexistent/rate",
        json={"rating": 50},
    )
    assert resp.status_code == 404


# ── Generate + Score endpoints ──────────────────────────────────────


def test_generate_song_not_found(client: TestClient) -> None:
    resp = client.post(
        "/api/songs/nonexistent/generate",
        json={"count": 1, "model": "sft"},
    )
    assert resp.status_code == 404


def test_generate_song_no_lyrics(client: TestClient) -> None:
    from songmaker_cli.db.models import Song, Version

    ctx: AppContext = client.app.state.ctx
    with ctx.db() as session:
        session.add(Song(
            id="s_empty", title="Empty", album_id="rock", slug="empty",
        ))
        session.add(Version(
            id="v_empty", song_id="s_empty",
            version_number=1, lyrics="", prompt="",
        ))
        session.commit()

    resp = client.post(
        "/api/songs/s_empty/generate",
        json={"count": 1, "model": "sft"},
    )
    assert resp.status_code == 400


def _mock_worker(mock_pool=None):
    """Context manager that mocks arq pool and worker health for enqueue tests."""
    from contextlib import contextmanager
    from unittest.mock import AsyncMock, patch

    if mock_pool is None:
        mock_pool = AsyncMock()

    @contextmanager
    def _ctx():
        with (
            patch("songmaker_cli.generation_api.get_arq_pool", return_value=mock_pool),
            patch(
                "songmaker_cli.generation_api.is_music_worker_healthy",
                AsyncMock(return_value=True),
            ),
            patch(
                "songmaker_cli.generation_api.is_scoring_worker_healthy",
                AsyncMock(return_value=True),
            ),
            patch(
                "songmaker_cli.generation_api._has_online_acestep_worker",
                AsyncMock(return_value=True),
            ),
        ):
            yield mock_pool

    return _ctx()


def _mock_worker_process_health(mock_pool=None):
    """Like _mock_worker, but leaves _has_online_acestep_worker real — for
    tests that must exercise its own GPU-health decision rather than have
    it stubbed away."""
    from contextlib import contextmanager
    from unittest.mock import AsyncMock, patch

    if mock_pool is None:
        mock_pool = AsyncMock()

    @contextmanager
    def _ctx():
        with (
            patch("songmaker_cli.generation_api.get_arq_pool", return_value=mock_pool),
            patch(
                "songmaker_cli.generation_api.is_music_worker_healthy",
                AsyncMock(return_value=True),
            ),
            patch(
                "songmaker_cli.generation_api.is_scoring_worker_healthy",
                AsyncMock(return_value=True),
            ),
        ):
            yield mock_pool

    return _ctx()


def _register_worker_with_broken_gpu(client: TestClient, mock_pool) -> None:
    """Issue #367 finding 1: a registered worker whose only heartbeat says
    gpu_healthy: false must never look online to the generate/repaint/cover
    preflight — simulated NVML failure, not a lucky real GPU."""
    import json
    from unittest.mock import AsyncMock

    from songmaker_cli.db.queries import register_worker

    factory = client.app.state.ctx.db
    with factory() as session:
        register_worker(
            session, worker_id="broken-gpu-w", host="h", port=8001,
            gpu_id=0, vram_total_gb=24.0,
        )
        session.commit()

    mock_pool.get = AsyncMock(
        return_value=json.dumps({"loaded": ["sft"], "gpu_healthy": False}).encode(),
    )


def test_generate_song_submits_job(client: TestClient) -> None:
    with _mock_worker() as mock_pool:
        resp = client.post(
            "/api/songs/s1/generate",
            json={"count": 2, "model": "sft"},
        )

    assert resp.status_code == 200
    assert resp.json()["type"] == "generate"
    mock_pool.enqueue_job.assert_called_once()


def test_generate_song_model_accepted(client: TestClient) -> None:
    with _mock_worker() as mock_pool:
        resp = client.post(
            "/api/songs/s1/generate",
            json={"count": 1, "model": "sft"},
        )

    assert resp.status_code == 200
    mock_pool.enqueue_job.assert_called_once()
    args = mock_pool.enqueue_job.call_args
    assert args[0][-1] == "sft"


def test_generate_song_passes_model_to_worker(client: TestClient) -> None:
    with _mock_worker() as mock_pool:
        resp = client.post(
            "/api/songs/s1/generate",
            json={"count": 1, "model": "turbo"},
        )

    assert resp.status_code == 200
    args = mock_pool.enqueue_job.call_args
    assert args[0][-1] == "turbo"


def test_generate_song_missing_model_rejected(client: TestClient) -> None:
    resp = client.post(
        "/api/songs/s1/generate",
        json={"count": 1},
    )
    assert resp.status_code == 422


def test_generate_song_invalid_model(client: TestClient) -> None:
    resp = client.post(
        "/api/songs/s1/generate",
        json={"count": 1, "model": "invalid"},
    )
    assert resp.status_code == 422


def test_generate_song_seed_accepted(client: TestClient) -> None:
    with _mock_worker() as mock_pool:
        resp = client.post(
            "/api/songs/s1/generate",
            json={"count": 1, "seed": 42, "model": "turbo"},
        )
    assert resp.status_code == 200
    mock_pool.enqueue_job.assert_called_once()
    call_args = mock_pool.enqueue_job.call_args[0]
    assert call_args[-2] == 42
    assert call_args[-1] == "turbo"


def test_generate_song_seed_invalid(client: TestClient) -> None:
    resp = client.post(
        "/api/songs/s1/generate", json={"count": 1, "seed": -2, "model": "sft"},
    )
    assert resp.status_code == 422


# ── Last failed generation ───────────────────────────────────────────


def test_last_failed_generation_null_when_no_failed_job(client: TestClient) -> None:
    resp = client.get("/api/songs/s1/last-failed-generation")
    assert resp.status_code == 200
    assert resp.json()["job"] is None


def test_last_failed_generation_returns_latest_failed_job(client: TestClient) -> None:
    factory = client.app.state.ctx.db
    with factory() as session:
        # The existing takes are older than the failure below -- archive
        # them so the newest-take suppression rule doesn't hide it.
        session.query(Generation).filter(Generation.id.in_(["g1", "g2"])).update(
            {"is_archived": True}, synchronize_session=False,
        )
        session.commit()

    with _mock_worker():
        resp = client.post("/api/songs/s1/generate", json={"count": 1, "model": "sft"})
    job_id = resp.json()["id"]

    with factory() as session:
        job = session.query(Job).filter_by(id=job_id).one()
        assert job.song_id == "s1"
        job.status = "failed"
        job.error = "Insufficient free VRAM"
        job.completed_at = datetime.now(timezone.utc)
        session.commit()

    resp = client.get("/api/songs/s1/last-failed-generation")
    assert resp.status_code == 200
    body = resp.json()["job"]
    assert body["id"] == job_id
    assert body["status"] == "failed"
    assert body["error"] == "Insufficient free VRAM"


def test_last_failed_generation_returns_the_most_recent_of_several(
    client: TestClient,
) -> None:
    """Ordered by started_at -- the actual attempt order -- not completed_at."""
    factory = client.app.state.ctx.db
    with factory() as session:
        session.query(Generation).filter(Generation.id.in_(["g1", "g2"])).update(
            {"is_archived": True}, synchronize_session=False,
        )
        session.add(Job(
            id="job-older", type="generate", status="failed", song_id="s1",
            error="older failure",
            started_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
            completed_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        ))
        session.add(Job(
            id="job-newer", type="generate", status="failed", song_id="s1",
            error="newer failure",
            started_at=datetime(2025, 6, 1, tzinfo=timezone.utc),
            completed_at=datetime(2025, 6, 1, tzinfo=timezone.utc),
        ))
        session.commit()

    resp = client.get("/api/songs/s1/last-failed-generation")
    assert resp.status_code == 200
    assert resp.json()["job"]["id"] == "job-newer"


def test_last_failed_generation_suppressed_by_a_newer_non_terminal_job(
    client: TestClient,
) -> None:
    """A failure isn't the song's last word once a newer job of any outcome
    -- queued, running, or completed -- exists; that newer job supersedes it
    on its own, before the take-suppression check even runs."""
    factory = client.app.state.ctx.db
    with factory() as session:
        session.query(Generation).filter(Generation.id.in_(["g1", "g2"])).update(
            {"is_archived": True}, synchronize_session=False,
        )
        session.add(Job(
            id="job-failed", type="generate", status="failed", song_id="s1",
            error="stale failure",
            started_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
            completed_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        ))
        session.add(Job(
            id="job-queued", type="generate", status="queued", song_id="s1",
            started_at=datetime(2025, 1, 2, tzinfo=timezone.utc),
        ))
        session.commit()

    resp = client.get("/api/songs/s1/last-failed-generation")
    assert resp.status_code == 200
    assert resp.json()["job"] is None


def test_last_failed_generation_recoverable_after_repaint(client: TestClient) -> None:
    factory = client.app.state.ctx.db
    with factory() as session:
        session.query(Generation).filter(Generation.id.in_(["g1", "g2"])).update(
            {"is_archived": True}, synchronize_session=False,
        )
        session.commit()

    with _mock_worker():
        resp = client.post("/api/generations/g1/repaint", json={
            "src_generation_id": "g1",
            "repainting_start": 0.0,
            "repainting_end": 0.5,
            "model": "sft",
        })
    job_id = resp.json()["id"]

    with factory() as session:
        job = session.query(Job).filter_by(id=job_id).one()
        assert job.song_id == "s1"
        job.status = "failed"
        job.error = "repaint failed"
        job.completed_at = datetime.now(timezone.utc)
        session.commit()

    resp = client.get("/api/songs/s1/last-failed-generation")
    assert resp.status_code == 200
    body = resp.json()["job"]
    assert body["id"] == job_id
    assert body["error"] == "repaint failed"


def test_last_failed_generation_recoverable_after_cover(client: TestClient) -> None:
    factory = client.app.state.ctx.db
    with factory() as session:
        session.query(Generation).filter(Generation.id.in_(["g1", "g2"])).update(
            {"is_archived": True}, synchronize_session=False,
        )
        session.commit()

    with _mock_worker():
        resp = client.post("/api/generations/g1/cover", json={
            "src_generation_id": "g1",
            "audio_cover_strength": 0.7,
            "model": "sft",
        })
    job_id = resp.json()["id"]

    with factory() as session:
        job = session.query(Job).filter_by(id=job_id).one()
        assert job.song_id == "s1"
        job.status = "failed"
        job.error = "cover failed"
        job.completed_at = datetime.now(timezone.utc)
        session.commit()

    resp = client.get("/api/songs/s1/last-failed-generation")
    assert resp.status_code == 200
    body = resp.json()["job"]
    assert body["id"] == job_id
    assert body["error"] == "cover failed"


def test_last_failed_generation_suppressed_by_a_newer_take(client: TestClient) -> None:
    factory = client.app.state.ctx.db
    with factory() as session:
        session.add(Job(
            id="job-stale", type="generate", status="failed", song_id="s1",
            error="stale failure",
            completed_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        ))
        session.commit()

    resp = client.get("/api/songs/s1/last-failed-generation")
    assert resp.status_code == 200
    assert resp.json()["job"] is None


def test_last_failed_generation_requires_ownership(client: TestClient) -> None:
    factory = client.app.state.ctx.db
    with factory() as session:
        session.add(User(
            id="u-other", username="other_user",
            password_hash="unused", role="user",
        ))
        session.flush()
        session.add(Album(
            id="other", title="Other Album", artist="Them", created_by="u-other",
        ))
        session.add(Song(id="s-other", title="Their Song", album_id="other", track_number=1))
        session.commit()

    resp = client.get("/api/songs/s-other/last-failed-generation")
    assert resp.status_code == 404


def test_last_failed_generation_song_not_found(client: TestClient) -> None:
    resp = client.get("/api/songs/nonexistent/last-failed-generation")
    assert resp.status_code == 404


# ── Repaint ─────────────────────────────────────────────────────────


def test_repaint_submits_job(client: TestClient) -> None:
    with _mock_worker() as mock_pool:
        resp = client.post("/api/generations/g1/repaint", json={
            "src_generation_id": "g1",
            "repainting_start": 0.2,
            "repainting_end": 0.8,
            "model": "sft",
        })

    assert resp.status_code == 200
    assert resp.json()["type"] == "generate"
    mock_pool.enqueue_job.assert_called_once()
    args = mock_pool.enqueue_job.call_args[0]
    repaint = args[-1]
    assert repaint["repainting_start"] == 0.2
    assert repaint["repainting_end"] == 0.8


def test_repaint_returns_503_and_enqueues_nothing_when_worker_gpu_is_broken(
    client: TestClient,
) -> None:
    from unittest.mock import AsyncMock

    mock_pool = AsyncMock()
    _register_worker_with_broken_gpu(client, mock_pool)

    with _mock_worker_process_health(mock_pool):
        resp = client.post("/api/generations/g1/repaint", json={
            "src_generation_id": "g1",
            "repainting_start": 0.2,
            "repainting_end": 0.8,
            "model": "sft",
        })

    assert resp.status_code == 503
    assert "No worker can generate music right now" in resp.json()["detail"]
    mock_pool.enqueue_job.assert_not_called()


def test_repaint_invalid_range(client: TestClient) -> None:
    resp = client.post("/api/generations/g1/repaint", json={
        "src_generation_id": "g1",
        "repainting_start": 0.8,
        "repainting_end": 0.2,
        "model": "sft",
    })
    assert resp.status_code == 400
    assert "repainting_start" in resp.json()["detail"]


def test_repaint_no_audio(client: TestClient) -> None:
    resp = client.post("/api/generations/g2/repaint", json={
        "src_generation_id": "g2",
        "repainting_start": 0.0,
        "repainting_end": 0.5,
        "model": "sft",
    })
    assert resp.status_code == 400
    assert "no audio file" in resp.json()["detail"]


def test_repaint_converts_mp3_to_wav(client: TestClient) -> None:
    from unittest.mock import patch

    audio_dir = Path(client.app.state.ctx.audio_dir)
    mp3_file = audio_dir / "u-test" / "g2.mp3"
    mp3_file.parent.mkdir(parents=True, exist_ok=True)
    mp3_file.write_bytes(b"fake-mp3-data")

    def fake_ffmpeg(cmd, **kwargs):
        wav_out = Path(cmd[-1])
        wav_out.write_bytes(b"RIFF" + b"\x00" * 40)
        return subprocess.CompletedProcess(cmd, 0)

    with (
        _mock_worker() as mock_pool,
        patch("songmaker_cli.generation_api.shutil.which", return_value="/usr/bin/ffmpeg"),
        patch("songmaker_cli.generation_api.subprocess.run", side_effect=fake_ffmpeg),
    ):
        resp = client.post("/api/generations/g2/repaint", json={
            "src_generation_id": "g2",
            "repainting_start": 0.0,
            "repainting_end": 0.5,
            "model": "sft",
        })

    assert resp.status_code == 200
    mock_pool.enqueue_job.assert_called_once()
    repaint = mock_pool.enqueue_job.call_args[0][-1]
    assert repaint["src_wav_path"].endswith(".wav")


def test_repaint_without_ffmpeg_is_unavailable(client: TestClient) -> None:
    from unittest.mock import patch

    audio_dir = Path(client.app.state.ctx.audio_dir)
    mp3_file = audio_dir / "u-test" / "g2.mp3"
    mp3_file.parent.mkdir(parents=True, exist_ok=True)
    mp3_file.write_bytes(b"fake-mp3-data")

    with (
        _mock_worker(),
        patch("songmaker_cli.generation_api.shutil.which", return_value=None),
    ):
        resp = client.post("/api/generations/g2/repaint", json={
            "src_generation_id": "g2",
            "repainting_start": 0.0,
            "repainting_end": 0.5,
            "model": "sft",
        })

    assert resp.status_code == 503
    assert resp.json()["detail"] == "ffmpeg is not available"


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        (
            "/api/generations/g2/repaint",
            {
                "src_generation_id": "g2",
                "repainting_start": 0.0,
                "repainting_end": 0.5,
                "model": "sft",
            },
        ),
        (
            "/api/generations/g2/cover",
            {
                "src_generation_id": "g2",
                "audio_cover_strength": 0.5,
                "model": "sft",
            },
        ),
    ],
)
def test_repaint_and_cover_report_mp3_conversion_failure(
    client: TestClient,
    path: str,
    payload: dict,
) -> None:
    from unittest.mock import patch

    audio_dir = Path(client.app.state.ctx.audio_dir)
    mp3_file = audio_dir / "u-test" / "g2.mp3"
    mp3_file.parent.mkdir(parents=True, exist_ok=True)
    mp3_file.write_bytes(b"fake-mp3-data")

    with (
        patch("songmaker_cli.generation_api.shutil.which", return_value="/usr/bin/ffmpeg"),
        patch(
            "songmaker_cli.generation_api.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "ffmpeg"),
        ),
    ):
        resp = client.post(path, json=payload)

    assert resp.status_code == 500
    assert resp.json()["detail"] == "Failed to convert MP3 to WAV"


def test_repaint_not_found(client: TestClient) -> None:
    resp = client.post("/api/generations/nonexistent/repaint", json={
        "src_generation_id": "nonexistent",
        "repainting_start": 0.0,
        "repainting_end": 0.5,
        "model": "sft",
    })
    assert resp.status_code == 404


def test_repaint_with_lyrics_override(client: TestClient) -> None:
    with _mock_worker() as mock_pool:
        resp = client.post("/api/generations/g1/repaint", json={
            "src_generation_id": "g1",
            "repainting_start": 0.3,
            "repainting_end": 0.7,
            "lyrics": "new lyrics here",
            "prompt": "jazz ballad",
            "model": "sft",
        })

    assert resp.status_code == 200
    args = mock_pool.enqueue_job.call_args[0]
    repaint = args[-1]
    assert repaint["lyrics"] == "new lyrics here"
    assert repaint["prompt"] == "jazz ballad"


# ── Cover ───────────────────────────────────────────────────────────


def test_cover_submits_job(client: TestClient) -> None:
    with _mock_worker() as mock_pool:
        resp = client.post("/api/generations/g1/cover", json={
            "src_generation_id": "g1",
            "audio_cover_strength": 0.7,
            "prompt": "jazz version",
            "model": "sft",
        })

    assert resp.status_code == 200
    assert resp.json()["type"] == "generate"
    mock_pool.enqueue_job.assert_called_once()
    args = mock_pool.enqueue_job.call_args[0]
    cover = args[-1]
    assert cover["audio_cover_strength"] == 0.7
    assert cover["prompt"] == "jazz version"


def test_cover_returns_503_and_enqueues_nothing_when_worker_gpu_is_broken(
    client: TestClient,
) -> None:
    from unittest.mock import AsyncMock

    mock_pool = AsyncMock()
    _register_worker_with_broken_gpu(client, mock_pool)

    with _mock_worker_process_health(mock_pool):
        resp = client.post("/api/generations/g1/cover", json={
            "src_generation_id": "g1",
            "audio_cover_strength": 0.7,
            "prompt": "jazz version",
            "model": "sft",
        })

    assert resp.status_code == 503
    assert "No worker can generate music right now" in resp.json()["detail"]
    mock_pool.enqueue_job.assert_not_called()


def test_cover_no_audio(client: TestClient) -> None:
    resp = client.post("/api/generations/g2/cover", json={
        "src_generation_id": "g2",
        "audio_cover_strength": 0.5,
        "model": "sft",
    })
    assert resp.status_code == 400
    assert "no audio file" in resp.json()["detail"]


def test_cover_not_found(client: TestClient) -> None:
    resp = client.post("/api/generations/nonexistent/cover", json={
        "src_generation_id": "nonexistent",
        "audio_cover_strength": 0.5,
        "model": "sft",
    })
    assert resp.status_code == 404


def test_cover_default_strength(client: TestClient) -> None:
    with _mock_worker() as mock_pool:
        resp = client.post("/api/generations/g1/cover", json={
            "src_generation_id": "g1",
            "model": "sft",
        })

    assert resp.status_code == 200
    args = mock_pool.enqueue_job.call_args[0]
    cover = args[-1]
    assert cover["audio_cover_strength"] == 0.8


# ── No silent fallbacks: model required across all three endpoints ──


def _no_fallback_endpoint_payloads():
    return [
        ("/api/songs/s1/generate", {"count": 1}),
        ("/api/generations/g1/repaint", {
            "src_generation_id": "g1",
            "repainting_start": 0.1,
            "repainting_end": 0.5,
        }),
        ("/api/generations/g1/cover", {
            "src_generation_id": "g1",
            "audio_cover_strength": 0.5,
        }),
    ]


@pytest.mark.parametrize(
    ("url", "base_payload"), _no_fallback_endpoint_payloads(),
)
def test_endpoint_requires_model(
    client: TestClient, url: str, base_payload: dict,
) -> None:
    resp = client.post(url, json=base_payload)
    assert resp.status_code == 422


@pytest.mark.parametrize(
    ("url", "base_payload"), _no_fallback_endpoint_payloads(),
)
def test_endpoint_rejects_unknown_model(
    client: TestClient, url: str, base_payload: dict,
) -> None:
    resp = client.post(url, json={**base_payload, "model": "totally-fake"})
    assert resp.status_code == 422


@pytest.mark.parametrize(
    ("url", "base_payload"), _no_fallback_endpoint_payloads(),
)
def test_endpoint_rejects_inactive_model(
    client: TestClient, url: str, base_payload: dict,
) -> None:
    ctx: AppContext = client.app.state.ctx
    with ctx.db() as session:
        before = session.query(AvailableModel).filter_by(id="turbo").one()
        assert before.is_active, "fixture invariant: turbo starts active"
        session.query(AvailableModel).filter_by(id="turbo").update(
            {"is_active": False},
        )
        session.commit()
    resp = client.post(url, json={**base_payload, "model": "turbo"})
    assert resp.status_code == 400
    assert "not currently available" in resp.json()["detail"]


# ── Reference audio upload ──────────────────────────────────────────


def test_upload_reference_audio(client: TestClient) -> None:
    import io
    resp = client.post(
        "/api/audio/upload",
        files={"file": ("ref.wav", io.BytesIO(b"RIFF" + b"\x00" * 200), "audio/wav")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["filename"] == "ref.wav"
    assert data["path"].endswith(".wav")
    assert "refs/" in data["path"]


def test_upload_reference_audio_bad_format(client: TestClient) -> None:
    import io
    resp = client.post(
        "/api/audio/upload",
        files={"file": ("ref.txt", io.BytesIO(b"hello world" * 20), "text/plain")},
    )
    assert resp.status_code == 400
    assert "Unsupported format" in resp.json()["detail"]


def test_upload_reference_audio_too_small(client: TestClient) -> None:
    import io
    resp = client.post(
        "/api/audio/upload",
        files={"file": ("ref.wav", io.BytesIO(b"tiny"), "audio/wav")},
    )
    assert resp.status_code == 400
    assert "too small" in resp.json()["detail"]


def test_generate_song_returns_503_and_enqueues_nothing_when_worker_gpu_is_broken(
    client: TestClient,
) -> None:
    from unittest.mock import AsyncMock

    mock_pool = AsyncMock()
    _register_worker_with_broken_gpu(client, mock_pool)

    with _mock_worker_process_health(mock_pool):
        resp = client.post(
            "/api/songs/s1/generate",
            json={"count": 1, "model": "sft"},
        )

    assert resp.status_code == 503
    assert "No worker can generate music right now" in resp.json()["detail"]
    mock_pool.enqueue_job.assert_not_called()


def test_generate_song_redis_down(client: TestClient) -> None:
    from unittest.mock import AsyncMock, patch

    with (
        patch(
            "songmaker_cli.generation_api.is_music_worker_healthy",
            AsyncMock(return_value=True),
        ),
        patch(
            "songmaker_cli.generation_api.is_scoring_worker_healthy",
            AsyncMock(return_value=True),
        ),
        patch(
            "songmaker_cli.generation_api._has_online_acestep_worker",
            AsyncMock(return_value=True),
        ),
        patch(
            "songmaker_cli.generation_api.get_arq_pool",
            side_effect=ConnectionError("redis down"),
        ),
    ):
        resp = client.post(
            "/api/songs/s1/generate",
            json={"count": 1, "model": "sft"},
        )

    assert resp.status_code == 503
    assert "Job queue unavailable" in resp.json()["detail"]


def test_score_generation_redis_down(client: TestClient) -> None:
    from unittest.mock import AsyncMock, patch

    with (
        patch(
            "songmaker_cli.generation_api.is_music_worker_healthy",
            AsyncMock(return_value=True),
        ),
        patch(
            "songmaker_cli.generation_api.is_scoring_worker_healthy",
            AsyncMock(return_value=True),
        ),
        patch(
            "songmaker_cli.generation_api.get_arq_pool",
            side_effect=ConnectionError("redis down"),
        ),
    ):
        resp = client.post(
            "/api/generations/g1/score",
            json={},
        )

    assert resp.status_code == 503
    assert "Job queue unavailable" in resp.json()["detail"]


@pytest.mark.parametrize(
    ("path", "payload", "health_check"),
    [
        pytest.param(
            "/api/songs/s1/generate",
            {"count": 1, "model": "sft"},
            "is_music_worker_healthy",
            id="generate",
        ),
        pytest.param(
            "/api/generations/g1/repaint",
            {
                "src_generation_id": "g1",
                "repainting_start": 0.2,
                "repainting_end": 0.8,
                "model": "sft",
            },
            "is_music_worker_healthy",
            id="repaint",
        ),
        pytest.param(
            "/api/generations/g1/cover",
            {"src_generation_id": "g1", "audio_cover_strength": 0.7, "model": "sft"},
            "is_music_worker_healthy",
            id="cover",
        ),
        pytest.param(
            "/api/generations/g1/score",
            {},
            "is_scoring_worker_healthy",
            id="score",
        ),
    ],
)
def test_worker_preflight_reports_an_unavailable_worker(
    client: TestClient,
    path: str,
    payload: dict,
    health_check: str,
) -> None:
    from unittest.mock import AsyncMock, MagicMock, patch

    with (
        patch(
            f"songmaker_cli.generation_api.{health_check}",
            AsyncMock(return_value=False),
        ),
        patch("songmaker_cli.generation_api.get_arq_pool", return_value=MagicMock()),
    ):
        response = client.post(path, json=payload)

    assert response.status_code == 503
    assert response.json()["detail"] == "Worker not running"


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        pytest.param(
            "/api/generations/g1/repaint",
            {
                "src_generation_id": "g1",
                "repainting_start": 0.2,
                "repainting_end": 0.8,
                "model": "sft",
            },
            id="repaint",
        ),
        pytest.param(
            "/api/generations/g1/cover",
            {"src_generation_id": "g1", "audio_cover_strength": 0.7, "model": "sft"},
            id="cover",
        ),
    ],
)
def test_repaint_and_cover_report_an_unavailable_job_queue(
    client: TestClient,
    path: str,
    payload: dict,
) -> None:
    from unittest.mock import AsyncMock, MagicMock, patch

    pool = MagicMock()
    pool.enqueue_job = AsyncMock(side_effect=ConnectionError("redis down"))
    with (
        patch(
            "songmaker_cli.generation_api.is_music_worker_healthy",
            AsyncMock(return_value=True),
        ),
        patch(
            "songmaker_cli.generation_api._has_online_acestep_worker",
            AsyncMock(return_value=True),
        ),
        patch("songmaker_cli.generation_api.get_arq_pool", return_value=pool),
    ):
        response = client.post(path, json=payload)

    assert response.status_code == 503
    assert response.json()["detail"] == "Job queue unavailable"


def test_scoring_schema_endpoint(client: TestClient) -> None:
    from songmaker_cli.scoring.registry import SCORERS

    resp = client.get("/api/scoring/schema")
    assert resp.status_code == 200
    body = resp.json()
    assert "scorers" in body
    returned_names = {s["name"] for s in body["scorers"]}
    assert returned_names == set(SCORERS.keys())

    by_name = {s["name"]: s for s in body["scorers"]}
    assert by_name["audiobox"]["device"] == "gpu"
    assert by_name["audiobox"]["needs_audio"] is False
    assert by_name["lyrical_coherence"]["host"] == "parent"
    assert by_name["audiobox"]["host"] == "child"
    assert "audiobox_enjoyment" in by_name["audiobox"]["output_keys"]
    assert "silence_gaps" in by_name["silence"]["output_keys"]


def test_score_generation_not_found(client: TestClient) -> None:
    resp = client.post(
        "/api/generations/nonexistent/score",
        json={},
    )
    assert resp.status_code == 404


def test_score_generation_submits_job(client: TestClient) -> None:
    with _mock_worker() as mock_pool:
        resp = client.post(
            "/api/generations/g1/score",
            json={},
        )

    assert resp.status_code == 200
    assert resp.json()["type"] == "score"
    mock_pool.enqueue_job.assert_called_once()


# ── Song chat endpoint ──────────────────────────────────────────────


def _mock_acall():
    from unittest.mock import AsyncMock, MagicMock, patch

    mock_response = MagicMock()
    mock_response.text = "Hello from Claude"
    mock_fn = AsyncMock(return_value=mock_response)
    return patch("songmaker_cli.chat_api.acall_claude", mock_fn), mock_fn


def test_song_chat_send(client: TestClient) -> None:
    patcher, mock_fn = _mock_acall()
    with patcher:
        resp = client.post("/api/songs/s1/chat", json={"message": "hi"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["user_message"]["role"] == "user"
    assert data["user_message"]["content"] == "hi"
    assert data["assistant_message"]["role"] == "assistant"
    assert data["assistant_message"]["content"] == "Hello from Claude"


def test_song_chat_marks_job_cancelled_when_request_is_cancelled(
    client: TestClient,
) -> None:
    from unittest.mock import patch

    from fastapi import Request

    from songmaker_cli.api_models.settings import SendChatRequest
    from songmaker_cli.chat_api import api_song_chat
    from songmaker_cli.jobs._runtime import _stop_chat_job_heartbeat

    factory = client.app.state.ctx.db

    async def _exercise() -> tuple[asyncio.Event, asyncio.Event]:
        claude_started = asyncio.Event()
        heartbeat_started = asyncio.Event()
        heartbeat_stopped = asyncio.Event()
        heartbeat_stop_calls = 0

        async def _keep_heartbeat(*_args, **_kwargs) -> None:
            heartbeat_started.set()
            try:
                await asyncio.Future()
            finally:
                heartbeat_stopped.set()

        async def _acall(*_args, **_kwargs) -> None:
            claude_started.set()
            await asyncio.Future()

        async def _stop_heartbeat(*args, **kwargs) -> None:
            nonlocal heartbeat_stop_calls
            heartbeat_stop_calls += 1
            await _stop_chat_job_heartbeat(*args, **kwargs)

        request = Request({"type": "http", "app": client.app})
        user = AuthenticatedUser(
            id=_DEFAULT_USER_ID,
            username="test_user",
            role="user",
            is_active=True,
        )
        with factory() as session:
            with patch(
                "songmaker_cli.jobs._runtime._keep_chat_job_heartbeat",
                _keep_heartbeat,
            ), patch(
                "songmaker_cli.jobs._runtime._stop_chat_job_heartbeat",
                _stop_heartbeat,
            ), patch("songmaker_cli.chat_api.acall_claude", _acall):
                task = asyncio.create_task(api_song_chat(
                    "s1",
                    SendChatRequest(message="hi"),
                    request,
                    user,
                    session,
                ))
                await claude_started.wait()
                await heartbeat_started.wait()
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task

        assert heartbeat_stop_calls == 1
        return heartbeat_stopped, claude_started

    heartbeat_stopped, claude_started = asyncio.run(_exercise())

    assert claude_started.is_set()
    assert heartbeat_stopped.is_set()
    with factory() as session:
        job = session.query(Job).filter_by(type="chat").one()
        assert job.status == "failed"
        assert job.error_type == "cancelled"
        assert job.error == "Turn cancelled by the client."


def test_chat_heartbeat_writer_updates_an_active_job(client: TestClient) -> None:
    from songmaker_cli.constants import JobStatus
    from songmaker_cli.jobs._runtime import _write_chat_job_heartbeat

    factory = client.app.state.ctx.db
    old = datetime.now(timezone.utc) - timedelta(minutes=10)
    with factory() as session:
        session.add(
            Job(
                id="chat-heartbeat",
                type="chat",
                status=JobStatus.RUNNING,
                started_at=old,
                heartbeat_at=old,
            ),
        )
        session.commit()

    _write_chat_job_heartbeat(factory, "chat-heartbeat")

    with factory() as session:
        job = session.query(Job).filter_by(id="chat-heartbeat").one()
        assert job.heartbeat_at.replace(tzinfo=timezone.utc) > old


def test_chat_heartbeat_timer_continues_after_a_write_failure() -> None:
    from unittest.mock import patch

    from songmaker_cli.jobs import _runtime

    sleeps = 0

    async def _next_tick(_interval: float) -> None:
        nonlocal sleeps
        sleeps += 1
        if sleeps == 2:
            raise asyncio.CancelledError

    with patch.object(_runtime.asyncio, "sleep", _next_tick), patch.object(
        _runtime,
        "_write_chat_job_heartbeat",
        side_effect=RuntimeError("database unavailable"),
    ) as write:
        heartbeat = _runtime._keep_chat_job_heartbeat(
            lambda: None,
            "chat-heartbeat",
            interval_seconds=0,
        )
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(heartbeat)

    assert write.call_count == 1
    assert sleeps == 2


def test_song_chat_multi_turn(client: TestClient) -> None:
    patcher, mock_fn = _mock_acall()
    with patcher:
        client.post("/api/songs/s1/chat", json={"message": "first"})
        client.post("/api/songs/s1/chat", json={"message": "second"})

    last_call = mock_fn.call_args
    messages_arg = last_call.kwargs["messages"]
    assert len(messages_arg) == 3
    assert messages_arg[0]["role"] == "user"
    assert messages_arg[1]["role"] == "assistant"
    assert messages_arg[2]["role"] == "user"


def test_song_chat_history(client: TestClient) -> None:
    patcher, _ = _mock_acall()
    with patcher:
        client.post("/api/songs/s1/chat", json={"message": "hi"})

    resp = client.get("/api/songs/s1/chat")
    assert resp.status_code == 200
    msgs = resp.json()["messages"]
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"
    assert msgs[1]["role"] == "assistant"


def test_song_chat_clear(client: TestClient) -> None:
    patcher, _ = _mock_acall()
    with patcher:
        client.post("/api/songs/s1/chat", json={"message": "hi"})

    resp = client.delete("/api/songs/s1/chat")
    assert resp.status_code == 200

    history = client.get("/api/songs/s1/chat").json()
    assert len(history["messages"]) == 0


def test_song_chat_attaches_messages_to_active_conversation(
    client: TestClient,
) -> None:
    from songmaker_cli.db.models import ChatMessage, Conversation

    patcher, _ = _mock_acall()
    with patcher:
        r1 = client.post("/api/songs/s1/chat", json={"message": "first"})
        r2 = client.post("/api/songs/s1/chat", json={"message": "second"})
    assert r1.status_code == 200
    assert r2.status_code == 200

    factory = client.app.state.ctx.db
    with factory() as session:
        convs = session.query(Conversation).filter_by(archived_at=None).all()
        assert len(convs) == 1, "expected one active conversation after 2 turns"
        conv_id = convs[0].id
        msgs = (
            session.query(ChatMessage)
            .order_by(ChatMessage.created_at).all()
        )
        # 4 messages (2 user, 2 assistant), every one linked to the same conversation.
        assert len(msgs) == 4
        assert all(m.conversation_id == conv_id for m in msgs)
        assert [m.role for m in msgs] == ["user", "assistant", "user", "assistant"]


def test_song_chat_failure_leaves_no_empty_conversation(
    client: TestClient,
) -> None:
    """Regression guard: Claude failure must not persist an empty
    Conversation row. ``get_or_create_active_conversation`` runs on the
    success path only.
    """
    from unittest.mock import AsyncMock, patch

    from songmaker_cli.claude.provider import UnavailableError
    from songmaker_cli.db.models import Conversation

    mock_acall = AsyncMock(side_effect=UnavailableError("no backend"))
    with patch("songmaker_cli.chat_api.acall_claude", mock_acall):
        resp = client.post("/api/songs/s1/chat", json={"message": "hi"})
    assert resp.status_code == 503

    factory = client.app.state.ctx.db
    with factory() as session:
        assert session.query(Conversation).count() == 0


def test_song_chat_unavailable(client: TestClient) -> None:
    from unittest.mock import AsyncMock, patch

    from songmaker_cli.claude.provider import UnavailableError

    mock_acall = AsyncMock(side_effect=UnavailableError("no backend"))
    with patch("songmaker_cli.chat_api.acall_claude", mock_acall):
        resp = client.post("/api/songs/s1/chat", json={"message": "hi"})

    assert resp.status_code == 503


def test_song_chat_http_error_marks_job_failed_without_exception_log(
    client: TestClient,
) -> None:
    from unittest.mock import patch

    from fastapi import HTTPException

    with patch(
        "songmaker_cli.chat_api._build_song_context",
        side_effect=HTTPException(404, "Song not found"),
    ), patch("songmaker_cli.chat_api.log.exception") as log_exception:
        response = client.post("/api/songs/s1/chat", json={"message": "hi"})

    assert response.status_code == 404
    log_exception.assert_not_called()
    factory = client.app.state.ctx.db
    with factory() as session:
        job = session.query(Job).filter_by(type="chat").one()
        assert job.status == "failed"
        assert job.error_type == "chat_error"


def test_song_chat_builds_context(client: TestClient) -> None:
    from songmaker_cli.chat_api import CHAT_ROLE

    with client.app.state.ctx.db() as session:
        session.add(Song(
            id="s2", title="Rain", album_id="rock", track_number=2, slug="rain",
        ))
        session.add(Version(
            id="v2", song_id="s2", version_number=1, lyrics="drizzle", prompt="ballad",
        ))
        session.commit()

    patcher, mock_fn = _mock_acall()
    with patcher:
        resp = client.post("/api/songs/s1/chat", json={
            "message": "write a verse",
            "mentioned_song_ids": ["s2"],
            "mentioned_version_ids": ["v1"],
        })

    assert resp.status_code == 200
    system_arg = mock_fn.call_args.kwargs["system"]
    assert CHAT_ROLE in system_arg
    messages_arg = mock_fn.call_args.kwargs["messages"]
    user_msg = messages_arg[-1]["content"]
    assert "<song_context>" in user_msg
    assert "Thunder" in user_msg
    assert "Rain" in user_msg
    assert "--- Referenced versions ---" in user_msg
    assert "[Version 1]" in user_msg
    assert "Style: hard rock" in user_msg
    assert "Lyrics:\nboom" in user_msg


def test_song_chat_requires_auth(unauthed_client: TestClient) -> None:
    resp = unauthed_client.post("/api/songs/s1/chat", json={"message": "hi"})
    assert resp.status_code == 401


def test_get_album(client: TestClient) -> None:
    resp = client.get("/api/albums/rock")
    assert resp.status_code == 200
    assert resp.json()["title"] == "Rock Album"


def test_get_job_found(client: TestClient) -> None:
    with _mock_worker():
        resp = client.post(
            "/api/songs/s1/generate", json={"count": 1, "model": "sft"},
        )
    job_id = resp.json()["id"]

    resp = client.get(f"/api/jobs/{job_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == job_id


# ── Album creation ──────────────────────────────────────────────────


def test_create_album(client: TestClient) -> None:
    resp = client.post("/api/albums", json={"title": "New Album", "artist": "Me"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "new-album"
    assert data["title"] == "New Album"
    assert data["artist"] == "Me"


def test_create_album_slugifies_unicode(client: TestClient) -> None:
    resp = client.post("/api/albums", json={"title": "Über Nächte"})
    assert resp.status_code == 200
    assert resp.json()["id"] == "uber-nachte"


def test_create_album_duplicate_gets_suffix(client: TestClient) -> None:
    resp1 = client.post("/api/albums", json={"title": "Dupe"})
    assert resp1.json()["id"] == "dupe"
    resp2 = client.post("/api/albums", json={"title": "Dupe"})
    assert resp2.status_code == 200
    assert resp2.json()["id"] == "dupe-2"


def test_create_album_empty_title(client: TestClient) -> None:
    resp = client.post("/api/albums", json={"title": "  "})
    assert resp.status_code == 422


def test_create_album_slugify_special_chars(client: TestClient) -> None:
    resp = client.post("/api/albums", json={"title": "Don't Stop!"})
    assert resp.status_code == 200
    assert resp.json()["id"] == "don-t-stop"


# ── Song list (summary vs detail) ──────────────────────────────────


def test_list_songs_has_no_generations_field(client: TestClient) -> None:
    resp = client.get("/api/songs")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert "generations" not in items[0]
    assert items[0]["generation_count"] == 2


def test_get_song_has_generations(client: TestClient) -> None:
    resp = client.get("/api/songs/s1")
    assert resp.status_code == 200
    data = resp.json()
    assert "generations" in data
    assert len(data["generations"]) == 2


def test_get_song_best_scores_from_rated_gen(client: TestClient) -> None:
    from songmaker_cli.db.models import Rating

    ctx: AppContext = client.app.state.ctx
    with ctx.db() as session:
        session.add(Rating(generation_id="g1", rating=80))
        session.commit()

    resp = client.get("/api/songs/s1")
    data = resp.json()
    assert data["best_scores"] is not None
    assert "dynamics" in data["best_scores"]
    assert data["best_rating"] == 80


def test_get_song_best_scores_follow_audiobox_quality_when_unrated(
    client: TestClient,
) -> None:
    ctx: AppContext = client.app.state.ctx
    with ctx.db() as session:
        session.add(Score(id="aq1", generation_id="g1", scorer="batch",
                          value={"audiobox_quality": 7.0}))
        session.add(Score(id="aq2", generation_id="g2", scorer="batch",
                          value={"audiobox_quality": 8.5}))
        session.commit()

    resp = client.get("/api/songs/s1")
    data = resp.json()
    assert data["best_scores"]["audiobox_quality"] == 8.5


def test_get_song_user_rating_outranks_higher_quality_take(
    client: TestClient,
) -> None:
    from songmaker_cli.db.models import Rating

    ctx: AppContext = client.app.state.ctx
    with ctx.db() as session:
        session.add(Score(id="aq2", generation_id="g2", scorer="batch",
                          value={"audiobox_quality": 9.0}))
        session.add(Rating(generation_id="g1", rating=80))
        session.commit()

    resp = client.get("/api/songs/s1")
    data = resp.json()
    assert data["best_rating"] == 80
    assert "audiobox_quality" not in (data["best_scores"] or {})


# ── Ownership / access control ──────────────────────────────────────


def test_user_sees_own_album_only(tmp_path: Path) -> None:
    c = _make_authed_client(tmp_path, role="user", user_id="u-test")
    resp = c.get("/api/albums")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == "rock"


def test_user_cannot_see_other_album(tmp_path: Path) -> None:
    c = _make_authed_client(tmp_path, role="user", user_id="u-test")

    ctx: AppContext = c.app.state.ctx
    with ctx.db() as session:
        session.add(User(
            id="u-other", username="other", password_hash="x", role="user",
        ))
        session.flush()
        session.add(Album(id="other", title="Other", artist="X", created_by="u-other"))
        session.commit()
    resp = c.get("/api/albums/other")
    assert resp.status_code == 404


def test_user_cannot_see_other_song(tmp_path: Path) -> None:
    c = _make_authed_client(tmp_path, role="user", user_id="u-test")

    ctx: AppContext = c.app.state.ctx
    with ctx.db() as session:
        session.add(User(
            id="u-other", username="other", password_hash="x", role="user",
        ))
        session.flush()
        session.add(Album(id="secret", title="Secret", artist="X", created_by="u-other"))
        session.add(Song(id="s-secret", title="Hidden", album_id="secret", track_number=1))
        session.add(Version(
            id="v-secret", song_id="s-secret", version_number=1,
            lyrics="x", prompt="x",
        ))
        session.commit()
    resp = c.get("/api/songs/s-secret")
    assert resp.status_code == 404


def test_admin_product_index_is_personal_library(tmp_path: Path) -> None:
    c = _make_authed_client(tmp_path, role="admin", user_id="u-admin")
    ctx: AppContext = c.app.state.ctx
    with ctx.db() as session:
        session.add(User(
            id="u-other", username="other", password_hash="x", role="user",
        ))
        session.flush()
        session.add(Album(id="other", title="Other", artist="X", created_by="u-other"))
        session.commit()
    listed = c.get("/api/albums")
    assert listed.status_code == 200
    assert {album["id"] for album in listed.json()["items"]} >= {"other"}
    by_id = c.get("/api/albums/other")
    assert by_id.status_code == 200
    assert by_id.json()["id"] == "other"


def test_authed_user_creates_album_with_ownership(tmp_path: Path) -> None:
    c = _make_authed_client(tmp_path, role="user", user_id="u-test")
    resp = c.post("/api/albums", json={"title": "My New Album"})
    assert resp.status_code == 200
    from songmaker_cli.db.queries import get_album
    ctx: AppContext = c.app.state.ctx
    with ctx.db() as session:
        album = get_album(session, "my-new-album")
        assert album is not None
        assert album.created_by == "u-test"


def test_job_ownership_blocks_other_user(tmp_path: Path) -> None:
    from songmaker_cli.db.models import User
    from songmaker_cli.db.queries import create_job

    c = _make_authed_client(tmp_path, role="user", user_id="u-test")

    ctx: AppContext = c.app.state.ctx
    with ctx.db() as session:
        other = User(
            id="u-other", username="other", password_hash="unused", role="user",
        )
        session.add(other)
        session.flush()
        job = create_job(session, "generate", user_id="u-other")
        session.commit()
        job_id = job.id

    resp = c.get(f"/api/jobs/{job_id}")
    assert resp.status_code == 404


# ── Job cancellation ────────────────────────────────────────────────


def test_cancel_queued_job(client: TestClient) -> None:
    with _mock_worker():
        resp = client.post(
            "/api/songs/s1/generate", json={"count": 1, "model": "sft"},
        )
    job_id = resp.json()["id"]

    resp = client.post(f"/api/jobs/{job_id}/cancel")
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"
    assert resp.json()["completed_at"] is not None

    got = client.get(f"/api/jobs/{job_id}")
    assert got.status_code == 200
    assert got.json()["status"] == "cancelled"
    assert got.json()["completed_at"] is not None


def test_cancel_already_completed_job(client: TestClient) -> None:
    from songmaker_cli.db.queries import update_job_status

    with _mock_worker():
        resp = client.post(
            "/api/songs/s1/generate", json={"count": 1, "model": "sft"},
        )
    job_id = resp.json()["id"]

    ctx: AppContext = client.app.state.ctx
    with ctx.db() as session:
        update_job_status(session, job_id, "completed", progress=1.0)
        session.commit()

    resp = client.post(f"/api/jobs/{job_id}/cancel")
    assert resp.status_code == 409

    got = client.get(f"/api/jobs/{job_id}")
    assert got.status_code == 200
    assert got.json()["status"] == "completed"


def test_cancel_wins_over_progress_and_finalize(client: TestClient) -> None:
    from songmaker_cli.db.queries import update_job_status

    with _mock_worker():
        resp = client.post(
            "/api/songs/s1/generate", json={"count": 1, "model": "sft"},
        )
    job_id = resp.json()["id"]

    ctx: AppContext = client.app.state.ctx
    with ctx.db() as session:
        update_job_status(session, job_id, "running", progress=0.4)
        session.commit()

    resp = client.post(f"/api/jobs/{job_id}/cancel")
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"
    assert resp.json()["completed_at"] is not None

    with ctx.db() as session:
        assert update_job_status(session, job_id, "running", progress=0.9) is False
        assert update_job_status(session, job_id, "completed", progress=1.0) is False
        assert update_job_status(session, job_id, "failed", error="late") is False
        session.commit()

    got = client.get(f"/api/jobs/{job_id}")
    assert got.json()["status"] == "cancelled"
    assert got.json()["completed_at"] is not None
    assert got.json()["error"] is None


def test_cancel_running_cover_job_signals_the_web_runner(client: TestClient) -> None:
    from songmaker_cli.constants import JobStatus, JobType
    from songmaker_cli.cover_runner import CoverJobCancellationRegistry
    from songmaker_cli.db.queries import create_job, update_job_status

    ctx: AppContext = client.app.state.ctx
    with ctx.db() as session:
        job = create_job(session, JobType.COVER, user_id=_DEFAULT_USER_ID)
        update_job_status(session, job.id, JobStatus.RUNNING)
        session.commit()
        job_id = job.id
    registry = CoverJobCancellationRegistry()
    abort_signal = registry.register(job_id)
    client.app.state.cover_job_cancellation_registry = registry

    response = client.post(f"/api/jobs/{job_id}/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == JobStatus.CANCELLED
    assert abort_signal.is_set()


def test_cancel_job_not_found(client: TestClient) -> None:
    resp = client.post("/api/jobs/nonexistent/cancel")
    assert resp.status_code == 404


def test_cancel_job_other_user_blocked(tmp_path: Path) -> None:
    from songmaker_cli.db.models import User
    from songmaker_cli.db.queries import create_job

    c = _make_authed_client(tmp_path, role="user", user_id="u-test")

    ctx: AppContext = c.app.state.ctx
    with ctx.db() as session:
        other = User(
            id="u-other", username="other", password_hash="unused", role="user",
        )
        session.add(other)
        session.flush()
        job = create_job(session, "generate", user_id="u-other")
        session.commit()
        job_id = job.id

    resp = c.post(f"/api/jobs/{job_id}/cancel")
    assert resp.status_code == 404


# ── Job SSE streaming ─────────────────────────────────────────────────
#
# api_stream_job calls get_current_user directly rather than through
# Depends() (#331 Findings 1/2, review round 2, 2026-09-02 -- see the
# function's own comment block), matching resource_event_api.py's
# api_stream_resource_events. That means `app.dependency_overrides[
# get_current_user]`, which every other endpoint's tests in this file rely
# on, does NOT apply to it: it needs a real, signed session cookie, the
# same way test_resource_event_api.py's _authenticated_clients builds one.
# Tests that hit the real route (client.stream/.get on /jobs/{id}/stream)
# call _authenticate_job_stream_client first; tests that drive
# _job_event_generator directly never go through auth at all and don't
# need it.


def _sign_job_stream_session(ctx: AppContext, user_id: str) -> str:
    from datetime import timedelta

    from songmaker_cli.auth import sign_session_id
    from songmaker_cli.db.queries import create_session

    expires_at = datetime.now(timezone.utc) + timedelta(days=1)
    with ctx.db() as session:
        user_session = create_session(session, user_id, expires_at)
        session.commit()
        session_id = user_session.id
    return sign_session_id(session_id, ctx.session_secret)


def _authenticate_job_stream_client(
    client: TestClient, user_id: str = _DEFAULT_USER_ID,
) -> None:
    client.cookies.set(
        SESSION_COOKIE, _sign_job_stream_session(client.app.state.ctx, user_id),
    )


def test_stream_job_initial_state(client: TestClient) -> None:
    import json

    from songmaker_cli.db.queries import create_job, update_job_status

    ctx: AppContext = client.app.state.ctx
    with ctx.db() as session:
        job = create_job(session, "generate", user_id=_DEFAULT_USER_ID)
        update_job_status(session, job.id, "completed", progress=1.0)
        session.commit()
        job_id = job.id

    _authenticate_job_stream_client(client)
    events = []
    with client.stream("GET", f"/api/jobs/{job_id}/stream") as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        assert resp.headers["cache-control"] == "no-cache"
        assert resp.headers["x-accel-buffering"] == "no"
        for line in resp.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: "):]))

    assert len(events) == 1
    assert events[0]["id"] == job_id
    assert events[0]["status"] == "completed"


def test_stream_completed_job_carries_training_epochs_and_zero_eta(
    client: TestClient,
) -> None:
    import json

    from songmaker_cli.constants import JobStatus
    from songmaker_cli.db.queries import create_job

    ctx: AppContext = client.app.state.ctx
    with ctx.db() as session:
        job = create_job(session, "lora_training", user_id=_DEFAULT_USER_ID)
        job.current_epoch = 0
        job.train_epochs = 500
        job.status = JobStatus.COMPLETED
        session.commit()
        job_id = job.id

    _authenticate_job_stream_client(client)
    with client.stream("GET", f"/api/jobs/{job_id}/stream") as response:
        event = next(
            json.loads(line.removeprefix("data: "))
            for line in response.iter_lines()
            if line.startswith("data: ")
        )

    assert event["current_epoch"] == 0
    assert event["train_epochs"] == 500
    assert event["remaining_time_estimate"] == 0


def test_stream_job_sends_updates(client: TestClient) -> None:
    import asyncio
    import json

    from songmaker_cli.db.queries import create_job, update_job_status
    from songmaker_cli.jobs_api import _job_event_generator

    ctx: AppContext = client.app.state.ctx
    with ctx.db() as session:
        job = create_job(session, "generate", user_id=_DEFAULT_USER_ID)
        session.commit()
        job_id = job.id

    async def _collect_updates() -> list[dict]:
        stream = _job_event_generator(ctx, job_id)
        first = json.loads((await anext(stream)).removeprefix("data: "))
        with ctx.db() as session:
            update_job_status(session, job_id, "completed", progress=1.0)
            session.commit()
        second = json.loads((await anext(stream)).removeprefix("data: "))
        await stream.aclose()
        return [first, second]

    events = asyncio.run(_collect_updates())

    statuses = [e["status"] for e in events]
    assert "queued" in statuses
    assert "completed" in statuses


def test_stream_job_emits_queue_reason_and_position_without_a_status_change(
    client: TestClient,
) -> None:
    import asyncio
    import json

    from songmaker_cli.db.queries import create_job, update_job_status
    from songmaker_cli.jobs_api import _job_event_generator

    ctx: AppContext = client.app.state.ctx
    with ctx.db() as session:
        create_job(session, "generate", user_id=_DEFAULT_USER_ID)
        job = create_job(session, "generate", user_id=_DEFAULT_USER_ID)
        update_job_status(
            session,
            job.id,
            "queued",
            queue_reason="Waiting for LoRA training on this GPU.",
        )
        session.commit()
        job_id = job.id

    async def collect_updates() -> list[dict]:
        stream = _job_event_generator(ctx, job_id)
        first = json.loads((await anext(stream)).removeprefix("data: "))
        with ctx.db() as session:
            update_job_status(
                session,
                job_id,
                "queued",
                queue_reason="Waiting for the next GPU slot.",
            )
            session.commit()
        second = json.loads((await anext(stream)).removeprefix("data: "))
        await stream.aclose()
        return [first, second]

    first, second = asyncio.run(collect_updates())

    assert first["status"] == second["status"] == "queued"
    assert first["queue_reason"] == "Waiting for LoRA training on this GPU."
    assert second["queue_reason"] == "Waiting for the next GPU slot."
    assert first["queue_position"] == second["queue_position"] == 2


def test_stream_job_sends_heartbeat_without_status_change(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    from songmaker_cli import jobs_api
    from songmaker_cli.db.queries import create_job
    from songmaker_cli.jobs_api import _job_event_generator

    monkeypatch.setattr(jobs_api, "SSE_HEARTBEAT_SECONDS", 0)
    monkeypatch.setattr(jobs_api, "SSE_POLL_INTERVAL_SECONDS", 0)

    ctx: AppContext = client.app.state.ctx
    with ctx.db() as session:
        job = create_job(session, "generate", user_id=_DEFAULT_USER_ID)
        session.commit()
        job_id = job.id

    async def _collect_frames() -> list[str]:
        stream = _job_event_generator(ctx, job_id)
        first = await anext(stream)
        second = await anext(stream)
        await stream.aclose()
        return [first, second]

    frames = asyncio.run(_collect_frames())

    assert frames[0].startswith("data: ")
    assert frames[1] == ": heartbeat\n\n"


def test_stream_job_reraises_client_cancellation(client: TestClient) -> None:
    from songmaker_cli.db.queries import create_job
    from songmaker_cli.jobs_api import _job_event_generator

    ctx: AppContext = client.app.state.ctx
    with ctx.db() as session:
        job = create_job(session, "generate", user_id=_DEFAULT_USER_ID)
        session.commit()
        job_id = job.id

    async def _cancel_stream() -> None:
        stream = _job_event_generator(ctx, job_id)
        await anext(stream)
        next_frame = asyncio.create_task(anext(stream))
        await asyncio.sleep(0)
        next_frame.cancel()
        with pytest.raises(asyncio.CancelledError):
            await next_frame
        await stream.aclose()

    asyncio.run(_cancel_stream())


def test_stream_job_closes_on_terminal_status(client: TestClient) -> None:
    import json

    from songmaker_cli.db.queries import create_job, update_job_status

    ctx: AppContext = client.app.state.ctx
    with ctx.db() as session:
        job = create_job(session, "generate", user_id=_DEFAULT_USER_ID)
        update_job_status(session, job.id, "failed", error="test error")
        session.commit()
        job_id = job.id

    _authenticate_job_stream_client(client)
    events = []
    with client.stream("GET", f"/api/jobs/{job_id}/stream") as resp:
        for line in resp.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: "):]))

    assert len(events) == 1
    assert events[0]["status"] == "failed"
    assert events[0]["error"] == "test error"


def test_stream_job_not_found(client: TestClient) -> None:
    _authenticate_job_stream_client(client)
    resp = client.get("/api/jobs/nonexistent/stream")
    assert resp.status_code == 404


def test_stream_job_auth_required(unauthed_client: TestClient) -> None:
    resp = unauthed_client.get("/api/jobs/some-job/stream")
    assert resp.status_code in (401, 403)


# ── #331 Findings 1 & 2: no held connection, off-loop reads, a deadline,
# a lease (review 2026-09-01 corrected the original lease-sizing rationale
# for Finding 1: api_stream_job took Depends(get_db_session), which FastAPI
# keeps open for a StreamingResponse's whole body -- every open job stream
# pinned a pool connection for up to JOB_STREAM_CONNECTION_SECONDS
# regardless of how brief each poll was) ──────────────────────────────────


def _make_pool_capacity_limited_client(
    tmp_path: Path, *, pool_size: int, max_overflow: int, pool_timeout: float,
):
    """A stripped-down app like the `client` fixture, but bound to a real
    (non-test-default) QueuePool sized down to `pool_size`/`max_overflow`.

    Lets a test prove an endpoint does or doesn't pin a connection for its
    whole lifetime by actually exhausting a real pool, rather than only
    instrumenting checkout/checkin events.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from songmaker_cli.api import router
    from songmaker_cli.db.engine import _enable_sqlite_pragmas, _seed_available_models
    from songmaker_cli.db.models import Base

    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    url = f"sqlite:///{data_dir / 'songmaker.db'}"
    engine = create_engine(
        url, echo=False, connect_args={"timeout": 30},
        pool_size=pool_size, max_overflow=max_overflow, pool_timeout=pool_timeout,
    )
    _enable_sqlite_pragmas(engine)
    Base.metadata.create_all(engine)
    _seed_available_models(engine)
    factory = sessionmaker(bind=engine)

    with factory() as session:
        session.add(User(
            id=_DEFAULT_USER_ID, username="test_user", password_hash="unused", role="user",
        ))
        session.commit()

    audio_dir = tmp_path / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    ctx = AppContext(
        db=factory, audio_dir=audio_dir, data_dir=data_dir,
        session_secret=TEST_SECRET, redis=make_fake_redis(),
    )
    app = FastAPI()
    app.state.ctx = ctx
    app.include_router(router)
    # No app.dependency_overrides[get_current_user] here on purpose (#331
    # Findings 1/2, review round 2): api_stream_job calls get_current_user
    # directly, not through Depends(), so an override would never reach it
    # anyway -- and the whole point of this client is to exercise the real
    # auth path, the same one production traffic goes through.
    return TestClient(app), factory


def _job_stream_scope(job_id: str, *, cookie: str) -> dict:
    path = f"/api/jobs/{job_id}/stream"
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"testserver"),
            (b"cookie", f"{SESSION_COOKIE}={cookie}".encode()),
        ],
        "client": ("testclient", 50_000),
        "server": ("testserver", 80),
    }


def test_stream_job_does_not_pin_the_only_pool_connection_for_the_stream_lifetime(
    tmp_path: Path,
) -> None:
    """#331 Finding 1 (review 2026-09-01): api_stream_job must not hold a
    Depends(get_db_session) session open for the whole StreamingResponse --
    FastAPI keeps a yield-dependency open until the whole response finishes,
    which for a StreamingResponse is the full stream lifetime. With a real
    pool of exactly one connection and no overflow, a job stream that is
    still live (a "running" job, not yet at a terminal status) must not
    starve a second, completely unrelated request that also needs the DB --
    before the fix, the second request would have blocked for pool_timeout
    and then failed, because the still-open stream's Depends session would
    already own the pool's only connection.

    Drives the real ASGI app directly (bypassing TestClient's request/
    response cycle, which fully drains a streaming response before
    returning control -- it cannot observe an in-progress stream) so the
    two requests genuinely run concurrently on one event loop, the same
    technique test_resource_event_api.py's outer-deadline test uses."""
    import asyncio

    from songmaker_cli import jobs_api
    from songmaker_cli.db.queries import create_job, update_job_status

    client, factory = _make_pool_capacity_limited_client(
        tmp_path, pool_size=1, max_overflow=0, pool_timeout=2,
    )
    app = client.app
    ctx: AppContext = app.state.ctx
    cookie = _sign_job_stream_session(ctx, _DEFAULT_USER_ID)

    with factory() as session:
        job_a = create_job(session, "generate", user_id=_DEFAULT_USER_ID)
        update_job_status(session, job_a.id, "running", progress=0.1)
        job_b = create_job(session, "generate", user_id=_DEFAULT_USER_ID)
        session.commit()
        job_a_id, job_b_id = job_a.id, job_b.id

    async def _drive():
        first_frame_sent = asyncio.Event()
        response_status: dict[str, int] = {}

        async def _receive() -> dict:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def _send(message: dict) -> None:
            if message["type"] == "http.response.start":
                response_status["status"] = message["status"]
            elif message["type"] == "http.response.body" and message.get("body"):
                # Only a genuine 200 SSE frame counts as "the stream is live" --
                # an auth failure also sends a body, and must not be mistaken
                # for one (that was a real bug in the first version of this
                # test: it asserted nothing about response_status at all).
                if response_status.get("status") == 200:
                    first_frame_sent.set()

        stream_task = asyncio.create_task(
            app(_job_stream_scope(job_a_id, cookie=cookie), _receive, _send),
        )
        await asyncio.wait_for(first_frame_sent.wait(), timeout=5)

        # Stream A is live (first "running" frame sent, generator now
        # sleeping between polls). Job B's status must still be fetchable
        # through the same one-connection pool right now, not after A closes.
        response_b = await asyncio.wait_for(
            asyncio.to_thread(jobs_api._fetch_job_response, ctx, job_b_id),
            timeout=2,
        )

        with ctx.db() as session:
            update_job_status(session, job_a_id, "completed", progress=1.0)
            session.commit()
        await asyncio.wait_for(stream_task, timeout=5)
        return response_status["status"], response_b

    status_a, response_b = asyncio.run(_drive())

    assert status_a == 200

    assert response_b is not None
    assert response_b.status == "queued"


def test_fetch_job_response_before_bounds_a_slow_poll_to_the_remaining_deadline(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#331 Finding 2 (review 2026-09-01): a bare `await
    asyncio.to_thread(_fetch_job_response, ...)` can still run past the
    stream's own deadline if it starts right before the wall and then
    blocks (e.g. on an exhausted DB pool, up to pool_timeout -- 60s could
    become 90s). asyncio.wait_for(remaining) bounds it to the deadline
    instead, returning None (closing the stream) rather than waiting out
    the full block."""
    import asyncio
    import time
    from time import monotonic

    from songmaker_cli import jobs_api

    def _slow_fetch(_ctx: AppContext, _job_id: str):
        time.sleep(5)
        return None

    monkeypatch.setattr(jobs_api, "_fetch_job_response", _slow_fetch)
    ctx: AppContext = client.app.state.ctx

    async def _bounded_poll() -> tuple[float, object]:
        deadline = monotonic() + 0.2
        started = monotonic()
        result = await jobs_api._fetch_job_response_before(ctx, "any-job", deadline)
        return monotonic() - started, result

    elapsed, result = asyncio.run(asyncio.wait_for(_bounded_poll(), timeout=5))

    assert result is None
    assert elapsed < 1.0


def test_stream_job_fetches_status_off_the_event_loop(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The blocking DB read must run through asyncio.to_thread(), not
    directly on the loop -- proven by observing it execute on a different
    thread than the one driving the async generator."""
    import asyncio
    import threading

    from songmaker_cli import jobs_api
    from songmaker_cli.db.queries import create_job

    ctx: AppContext = client.app.state.ctx
    with ctx.db() as session:
        job = create_job(session, "generate", user_id=_DEFAULT_USER_ID)
        session.commit()
        job_id = job.id

    real_fetch = jobs_api._fetch_job_response
    observed_threads: list[int] = []

    def _observing_fetch(ctx: AppContext, job_id: str):
        observed_threads.append(threading.get_ident())
        return real_fetch(ctx, job_id)

    monkeypatch.setattr(jobs_api, "_fetch_job_response", _observing_fetch)

    async def _first_frame() -> None:
        stream = jobs_api._job_event_generator(ctx, job_id)
        await anext(stream)
        await stream.aclose()

    generator_thread = threading.get_ident()
    asyncio.run(_first_frame())

    assert observed_threads
    assert observed_threads[0] != generator_thread


def test_stream_job_deadline_closes_a_stream_that_never_reaches_terminal(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A job stuck at "running" must not be polled forever -- the stream's
    own lifetime deadline closes it, letting the frontend's already-handled
    EventSource reconnect (jobs.ts) pick it back up."""
    import asyncio

    from songmaker_cli import jobs_api
    from songmaker_cli.db.queries import create_job, update_job_status
    from songmaker_cli.jobs_api import _job_event_generator

    monkeypatch.setattr(jobs_api, "JOB_STREAM_CONNECTION_SECONDS", 0.05)
    monkeypatch.setattr(jobs_api, "SSE_POLL_INTERVAL_SECONDS", 0.01)

    ctx: AppContext = client.app.state.ctx
    with ctx.db() as session:
        job = create_job(session, "generate", user_id=_DEFAULT_USER_ID)
        update_job_status(session, job.id, "running", progress=0.1)
        session.commit()
        job_id = job.id

    async def _drain_until_closed() -> int:
        frame_count = 0
        async for _frame in _job_event_generator(ctx, job_id):
            frame_count += 1
        return frame_count

    frame_count = asyncio.run(asyncio.wait_for(_drain_until_closed(), timeout=5))

    assert frame_count >= 1


def test_stream_job_lease_is_acquired_and_released_around_the_stream(
    client: TestClient,
) -> None:
    """The lease release (`_schedule_job_stream_lease_release`) is
    intentionally fire-and-forget -- a background `asyncio.create_task`,
    off the generator's own execution path, the same way
    resource_event_api.py's `_schedule_stream_lease_release` is (see that
    module's `test_disconnect_releases_lease_off_loop_and_contains_failure`:
    release must not block the stream's own close). That makes
    TestClient.stream() the wrong tool to observe it with: TestClient never
    entered via `with TestClient(app) as client:` opens a fresh
    `anyio.from_thread` portal per call and tears it down the instant that
    call's response finishes (starlette's ASGITransport.handle_request), so
    the fire-and-forget task is racing that teardown, not the test's own
    wait -- no `released.wait(N)` duration, however generous, fixes a task
    that can be cancelled before it runs. Driving the app directly inside
    one asyncio.run() (the same technique
    test_stream_job_does_not_pin_the_only_pool_connection_for_the_stream_lifetime
    uses, and test_resource_event_api.py's outer-deadline tests) keeps the
    loop that scheduled the task alive, so the test can wait on the real
    condition -- the task's own completion, observed via
    jobs_api._LEASE_RELEASE_TASKS emptying, mirroring
    test_resource_event_api.py's _wait_for_released_lease."""
    import asyncio

    from songmaker_cli import jobs_api
    from songmaker_cli.db.queries import create_job, update_job_status

    ctx: AppContext = client.app.state.ctx
    with ctx.db() as session:
        job = create_job(session, "generate", user_id=_DEFAULT_USER_ID)
        update_job_status(session, job.id, "completed", progress=1.0)
        session.commit()
        job_id = job.id

    acquire_calls: list[str] = []
    release_calls: list[tuple[str, str]] = []

    class _Limiter:
        def acquire(self, user_id: str) -> str:
            acquire_calls.append(user_id)
            return "lease-token"

        def release(self, user_id: str, token: str) -> None:
            release_calls.append((user_id, token))

    client.app.state._job_stream_lease_limiter = _Limiter()
    cookie = _sign_job_stream_session(ctx, _DEFAULT_USER_ID)
    app = client.app

    async def _drive() -> int:
        response_status: dict[str, int] = {}

        async def _receive() -> dict:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def _send(message: dict) -> None:
            if message["type"] == "http.response.start":
                response_status["status"] = message["status"]

        await app(_job_stream_scope(job_id, cookie=cookie), _receive, _send)

        for _ in range(500):
            if not jobs_api._LEASE_RELEASE_TASKS:
                break
            await asyncio.sleep(0.01)

        return response_status["status"]

    status = asyncio.run(asyncio.wait_for(_drive(), timeout=5))

    assert status == 200
    assert not jobs_api._LEASE_RELEASE_TASKS
    assert acquire_calls == [_DEFAULT_USER_ID]
    assert release_calls == [(_DEFAULT_USER_ID, "lease-token")]


def test_stream_job_rejects_when_lease_is_exhausted(client: TestClient) -> None:
    from songmaker_cli.db.queries import create_job

    ctx: AppContext = client.app.state.ctx
    with ctx.db() as session:
        job = create_job(session, "generate", user_id=_DEFAULT_USER_ID)
        session.commit()
        job_id = job.id

    class _ExhaustedLimiter:
        def acquire(self, _user_id: str) -> str | None:
            return None

    client.app.state._job_stream_lease_limiter = _ExhaustedLimiter()

    _authenticate_job_stream_client(client)
    resp = client.get(f"/api/jobs/{job_id}/stream")
    assert resp.status_code == 429


def test_stream_job_lease_fails_closed_when_limiter_errors(client: TestClient) -> None:
    from songmaker_cli.db.queries import create_job

    ctx: AppContext = client.app.state.ctx
    with ctx.db() as session:
        job = create_job(session, "generate", user_id=_DEFAULT_USER_ID)
        session.commit()
        job_id = job.id

    class _BrokenLimiter:
        def acquire(self, _user_id: str) -> str:
            raise ConnectionError("redis unavailable")

    client.app.state._job_stream_lease_limiter = _BrokenLimiter()

    _authenticate_job_stream_client(client)
    resp = client.get(f"/api/jobs/{job_id}/stream")
    assert resp.status_code == 503


def test_stream_job_heartbeat_survives_the_lease_and_deadline_changes(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#296 regression: a running job with no status/progress change still
    emits periodic heartbeats rather than going silent, unaffected by the
    #331 Finding 2 off-loop fetch, deadline, and lease additions."""
    import asyncio

    from songmaker_cli import jobs_api
    from songmaker_cli.db.queries import create_job, update_job_status
    from songmaker_cli.jobs_api import _job_event_generator

    monkeypatch.setattr(jobs_api, "SSE_HEARTBEAT_SECONDS", 0)
    monkeypatch.setattr(jobs_api, "SSE_POLL_INTERVAL_SECONDS", 0)

    ctx: AppContext = client.app.state.ctx
    with ctx.db() as session:
        job = create_job(session, "generate", user_id=_DEFAULT_USER_ID)
        update_job_status(session, job.id, "running", progress=0.1)
        session.commit()
        job_id = job.id

    async def _collect_frames() -> list[str]:
        stream = _job_event_generator(ctx, job_id)
        first = await anext(stream)
        second = await anext(stream)
        await stream.aclose()
        return [first, second]

    frames = asyncio.run(_collect_frames())

    assert frames[0].startswith("data: ")
    assert frames[1] == ": heartbeat\n\n"


# ── Coverage gap tests ───────────────────────────────────────────────


def test_create_song_gen_param_out_of_range(client: TestClient) -> None:
    resp = client.post("/api/songs", json={
        "title": "Bad Params",
        "album_id": "rock",
        "generation_params": {"inference_steps": 500},
    })
    assert resp.status_code == 422


def test_create_song_gen_param_invalid_infer_method(client: TestClient) -> None:
    resp = client.post("/api/songs", json={
        "title": "Bad Infer",
        "album_id": "rock",
        "generation_params": {"infer_method": "euler"},
    })
    assert resp.status_code == 422


def test_create_song_gen_param_invalid_thinking(client: TestClient) -> None:
    resp = client.post("/api/songs", json={
        "title": "Bad Think",
        "album_id": "rock",
        "generation_params": {"thinking": "not-a-bool"},
    })
    assert resp.status_code == 422


def test_create_song_gen_param_thinking_accepts_bool(client: TestClient) -> None:
    resp = client.post("/api/songs", json={
        "title": "Good Think",
        "album_id": "rock",
        "generation_params": {"thinking": True},
    })
    assert resp.status_code == 200


def test_score_request_invalid_scorer_name(client: TestClient) -> None:
    import pytest
    from pydantic import ValidationError

    from songmaker_cli.api_models import ScoreRequest

    with pytest.raises(ValidationError, match="Unknown scorers"):
        ScoreRequest(scorers=["nonexistent_scorer"])


def test_generation_params_invalid_infer_method_direct() -> None:
    from pydantic import ValidationError

    from songmaker_cli.api_models import GenerationParams

    with pytest.raises(ValidationError, match="infer_method"):
        GenerationParams(infer_method="euler")


def test_generation_params_invalid_thinking_direct() -> None:
    from pydantic import ValidationError

    from songmaker_cli.api_models import GenerationParams

    with pytest.raises(ValidationError):
        GenerationParams(thinking="not-a-bool")


def test_score_request_invalid_scorer_direct() -> None:
    from pydantic import ValidationError

    from songmaker_cli.api_models import ScoreRequest

    with pytest.raises(ValidationError, match="Unknown scorers"):
        ScoreRequest(scorers=["fake_scorer"])


def test_check_song_access_ownership_denied(tmp_path: Path) -> None:
    c = _make_authed_client(tmp_path, role="user", user_id="u-test")

    ctx: AppContext = c.app.state.ctx
    with ctx.db() as session:
        session.add(User(
            id="u-other", username="other", password_hash="unused", role="user",
        ))
        session.flush()
        session.add(Album(id="private", title="Private", artist="X", created_by="u-other"))
        session.add(Song(id="s-private", title="Hidden", album_id="private", track_number=1))
        session.commit()

    resp = c.get("/api/songs/s-private/versions")
    assert resp.status_code == 404


def test_create_album_integrity_error(client: TestClient) -> None:
    from unittest.mock import patch

    with patch("songmaker_cli.album_api.unique_album_id", return_value="rock"):
        resp = client.post("/api/albums", json={"title": "Rock Album"})

    assert resp.status_code == 409
    assert "conflict" in resp.json()["detail"].lower()


def test_update_song_value_error(client: TestClient) -> None:
    from unittest.mock import patch

    with patch("songmaker_cli.song_api.update_song", side_effect=ValueError("Song not found")):
        resp = client.put("/api/songs/s1", json={"lyrics": "x"})

    assert resp.status_code == 404


@pytest.mark.parametrize(
    ("method", "path", "payload", "target", "detail"),
    [
        pytest.param(
            "put", "/api/playlists/{playlist_id}", {"title": "Renamed"},
            "songmaker_cli.playlist_api.update_playlist", "Playlist not found",
            id="playlist-update",
        ),
        pytest.param(
            "delete", "/api/playlists/{playlist_id}", None,
            "songmaker_cli.playlist_api.delete_playlist", "Playlist not found",
            id="playlist-delete",
        ),
        pytest.param(
            "post", "/api/playlists/{playlist_id}/entries/album", {"album_id": "rock"},
            "songmaker_cli.playlist_api.add_album_to_playlist", "Album not found",
            id="playlist-add-album",
        ),
        pytest.param(
            "post", "/api/playlists/{playlist_id}/share", None,
            "songmaker_cli.playlist_api.enable_playlist_sharing", "Playlist not found",
            id="playlist-share",
        ),
        pytest.param(
            "delete", "/api/playlists/{playlist_id}/share", None,
            "songmaker_cli.playlist_api.disable_playlist_sharing", "Playlist not found",
            id="playlist-unshare",
        ),
        pytest.param(
            "put", "/api/songs/s1/title", {"title": "Renamed"},
            "songmaker_cli.song_api.rename_song", "Song not found", id="song-rename",
        ),
        pytest.param(
            "put", "/api/songs/s1/album", {"album_id": "rock"},
            "songmaker_cli.song_api.move_song", "Song or album not found", id="song-move",
        ),
        pytest.param(
            "delete", "/api/songs/s1", None,
            "songmaker_cli.song_api.soft_delete_song", "Song not found", id="song-delete",
        ),
        pytest.param(
            "post", "/api/songs/s1/share", None,
            "songmaker_cli.song_api.enable_song_sharing", "Song not found", id="song-share",
        ),
        pytest.param(
            "delete", "/api/songs/s1/share", None,
            "songmaker_cli.song_api.disable_song_sharing", "Song not found", id="song-unshare",
        ),
        pytest.param(
            "post", "/api/generations/g1/share", None,
            "songmaker_cli.generation_api.enable_generation_sharing",
            "Generation not found",
            id="generation-share",
        ),
        pytest.param(
            "delete", "/api/generations/g1/share", None,
            "songmaker_cli.generation_api.disable_generation_sharing",
            "Generation not found",
            id="generation-unshare",
        ),
    ],
)
def test_mutations_hide_resources_deleted_after_the_access_check(
    client: TestClient,
    method: str,
    path: str,
    payload: dict | None,
    target: str,
    detail: str,
) -> None:
    from unittest.mock import patch

    playlist = client.post("/api/playlists", json={"title": "Test playlist"})
    playlist_id = playlist.json()["id"]

    with patch(target, side_effect=ValueError(detail)):
        response = client.request(
            method.upper(),
            path.format(playlist_id=playlist_id),
            json=payload,
        )

    assert response.status_code == 404
    assert response.json()["detail"] == detail


@pytest.mark.parametrize(
    ("case", "detail"),
    [
        pytest.param("deleted-song", "Song not found", id="restore-deleted-song"),
        pytest.param("deleted-album", "Song not found", id="restore-deleted-album"),
        pytest.param("sample-without-parent", "LoRA sample not found", id="lora-sample-parent"),
        pytest.param("foreign-private-take", "Generation not found", id="own-generation"),
    ],
)
def test_access_helpers_hide_resources_that_disappear_or_lose_ownership(
    case: str,
    detail: str,
) -> None:
    from types import SimpleNamespace
    from unittest.mock import patch

    from fastapi import HTTPException

    from songmaker_cli.api_helpers import (
        check_lora_sample_access,
        check_own_generation_access,
        check_song_access_including_deleted,
    )

    user = AuthenticatedUser(id="owner", username="owner", role="user", is_active=True)
    if case == "deleted-song":
        with patch("songmaker_cli.api_helpers.get_song", return_value=None):
            with pytest.raises(HTTPException) as exc_info:
                check_song_access_including_deleted(object(), "s1", user)
    elif case == "deleted-album":
        song = SimpleNamespace(album_id="a1")
        with (
            patch("songmaker_cli.api_helpers.get_song", return_value=song),
            patch("songmaker_cli.api_helpers.get_album", return_value=None),
        ):
            with pytest.raises(HTTPException) as exc_info:
                check_song_access_including_deleted(object(), "s1", user)
    elif case == "sample-without-parent":
        sample = SimpleNamespace(user_lora=None)
        with pytest.raises(HTTPException) as exc_info:
            check_lora_sample_access(sample, user)
    else:
        generation = SimpleNamespace(
            song=SimpleNamespace(album=SimpleNamespace(created_by="other")),
        )
        with patch("songmaker_cli.api_helpers.check_generation_access", return_value=generation):
            with pytest.raises(HTTPException) as exc_info:
                check_own_generation_access(object(), "g1", user)

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == detail


def test_delete_version_value_error(client: TestClient) -> None:
    from unittest.mock import patch

    err = ValueError("Version not found")
    with patch("songmaker_cli.song_api.delete_version", side_effect=err):
        resp = client.delete("/api/versions/v1")

    assert resp.status_code == 404


def test_delete_generation_value_error(client: TestClient) -> None:
    from unittest.mock import patch

    err = ValueError("Generation not found")
    with patch("songmaker_cli.generation_api.delete_generation", side_effect=err):
        resp = client.delete("/api/generations/g1")

    assert resp.status_code == 404


def test_pick_generation_value_error(client: TestClient) -> None:
    from unittest.mock import patch

    err = ValueError("Generation not found")
    with patch("songmaker_cli.generation_api.pick_generation", side_effect=err):
        resp = client.post("/api/generations/g1/pick")

    assert resp.status_code == 404


def test_unpick_generation_value_error(client: TestClient) -> None:
    from unittest.mock import patch

    err = ValueError("Generation not found")
    with patch("songmaker_cli.generation_api.unpick_generation", side_effect=err):
        resp = client.post("/api/generations/g1/unpick")

    assert resp.status_code == 404


def test_keep_generation_value_error(client: TestClient) -> None:
    from unittest.mock import patch

    err = ValueError("Generation not found")
    with patch("songmaker_cli.generation_api.keep_generation", side_effect=err):
        resp = client.post("/api/generations/g1/keep")

    assert resp.status_code == 404


def test_unkeep_generation_value_error(client: TestClient) -> None:
    from unittest.mock import patch

    err = ValueError("Generation not found")
    with patch("songmaker_cli.generation_api.unkeep_generation", side_effect=err):
        resp = client.post("/api/generations/g1/unkeep")

    assert resp.status_code == 404


# ── Audit trail tests ────────────────────────────────────────────────


def test_create_album_records_audit(client: TestClient) -> None:
    from songmaker_cli.db.queries import list_audit_log

    client.post("/api/albums", json={"title": "Audited"})
    ctx: AppContext = client.app.state.ctx
    with ctx.db() as session:
        entries = list_audit_log(session)
    assert any(e.action == "create" and e.resource_type == "album" for e in entries)


def test_audit_log_admin_endpoint(tmp_path: Path) -> None:
    c = _make_authed_client(tmp_path, role="admin", user_id="u-admin")
    c.post("/api/albums", json={"title": "Audit Test"})
    resp = c.get("/api/admin/audit-log")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) >= 1
    assert data["items"][0]["action"] == "create"
    assert "created_at" in data["items"][0]
    assert data["total"] >= 1


# ── Chat rate limiting ───────────────────────────────────────────────


def test_chat_rate_limit(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("CHAT_RATE_LIMIT_USER", "2")
    monkeypatch.setenv("CHAT_RATE_LIMIT_ADMIN", "300")
    from songmaker_cli.settings import get_settings
    get_settings.cache_clear()

    patcher, _ = _mock_acall()
    with patcher:
        for _ in range(2):
            r = client.post("/api/songs/s1/chat", json={"message": "hi"})
            assert r.status_code == 200

        r = client.post("/api/songs/s1/chat", json={"message": "hi"})
        assert r.status_code == 429


# ── Admin rate limits ────────────────────────────────────────────────


def test_admin_has_rate_limit(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("GENERATION_RATE_LIMIT_USER", "3")
    monkeypatch.setenv("GENERATION_RATE_LIMIT_ADMIN", "1")
    from songmaker_cli.settings import get_settings
    get_settings.cache_clear()

    c = _make_authed_client(tmp_path, role="admin", user_id="u-admin")

    with _mock_worker():
        r = c.post(
            "/api/songs/s1/generate", json={"count": 1, "model": "sft"},
        )
        assert r.status_code == 200

        r = c.post(
            "/api/songs/s1/generate", json={"count": 1, "model": "sft"},
        )
        assert r.status_code == 429


# ── Body size limit middleware ───────────────────────────────────────


def test_body_size_limit_rejects_large_request(tmp_path: Path) -> None:
    from songmaker_cli.api import router
    from songmaker_cli.middleware.body_size import BodySizeLimitMiddleware

    factory = init_db(tmp_path / "test.db")
    ctx = AppContext(
        db=factory,
        audio_dir=tmp_path / "audio",
        data_dir=tmp_path / "data",
        session_secret=TEST_SECRET,
        redis=make_fake_redis(),
    )

    app = FastAPI()
    app.state.ctx = ctx
    app.dependency_overrides[get_current_user] = _fake_user("u-test", "test", "user")
    app.add_middleware(BodySizeLimitMiddleware)
    app.include_router(router)

    tc = TestClient(app)
    large_body = b"x" * 2_000_000
    resp = tc.post(
        "/api/albums",
        content=large_body,
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 413


# ── Error sanitization ──────────────────────────────────────────────


def test_sanitize_error_known_type() -> None:
    from songmaker_cli.jobs import _sanitize_error

    assert _sanitize_error(ConnectionError("x"), "j1") == "ACE-Step server not reachable"
    assert _sanitize_error(TimeoutError("x"), "j1") == "Generation timed out"
    assert _sanitize_error(RuntimeError("x"), "j1") == "Internal error during processing"


def test_sanitize_error_unknown_type() -> None:
    from songmaker_cli.jobs import _sanitize_error

    assert _sanitize_error(KeyError("x"), "j1") == "An unexpected error occurred"


def test_sanitize_error_generation_setup() -> None:
    from songmaker_cli.jobs import GenerationSetupError, _sanitize_error

    assert _sanitize_error(GenerationSetupError("Song not found"), "j1") == "Song not found"


def test_sanitize_error_hides_unknown_generation_setup_details(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from songmaker_cli.jobs import GenerationSetupError, _sanitize_error

    raw_error = "/srv/songmaker/private.db is unavailable"
    with caplog.at_level(logging.ERROR, logger="songmaker_cli.jobs._runtime"):
        message = _sanitize_error(GenerationSetupError(raw_error), "j1")

    assert message == "An unexpected error occurred"
    assert raw_error in caplog.text


def test_chat_success_finalizes_job(client: TestClient) -> None:
    patcher, _ = _mock_acall()
    with patcher:
        resp = client.post("/api/songs/s1/chat", json={"message": "hi"})

    assert resp.status_code == 200

    factory = client.app.state.ctx.db
    with factory() as session:
        job = session.query(Job).filter_by(type="chat").first()
        assert job is not None
        assert job.status == "completed"
        assert job.completed_at is not None


def test_chat_failure_finalizes_job(client: TestClient) -> None:
    from unittest.mock import AsyncMock, patch

    from songmaker_cli.claude.provider import UnavailableError

    mock_acall = AsyncMock(side_effect=UnavailableError("down"))
    with patch("songmaker_cli.chat_api.acall_claude", mock_acall):
        resp = client.post("/api/songs/s1/chat", json={"message": "hi"})

    assert resp.status_code == 503

    factory = client.app.state.ctx.db
    with factory() as session:
        job = session.query(Job).filter_by(type="chat").first()
        assert job is not None
        assert job.status == "failed"
        assert job.completed_at is not None


def test_chat_unavailable_hides_details(client: TestClient) -> None:
    from unittest.mock import AsyncMock, patch

    from songmaker_cli.claude.provider import UnavailableError

    err = UnavailableError("Claude CLI error: /home/user/.local/bin...")
    mock_acall = AsyncMock(side_effect=err)
    with patch("songmaker_cli.chat_api.acall_claude", mock_acall):
        resp = client.post("/api/songs/s1/chat", json={"message": "hi"})

    assert resp.status_code == 503
    assert "Claude is currently unavailable" in resp.json()["detail"]
    assert "/home/" not in resp.json()["detail"]


# ── System prompt ──────────────────────────────────────────────────


def test_system_prompt_contains_role_and_structure() -> None:
    from songmaker_cli.chat_api import CHAT_ROLE, STRUCTURAL_PROMPT, SYSTEM_PROMPT

    assert CHAT_ROLE in SYSTEM_PROMPT
    assert STRUCTURAL_PROMPT in SYSTEM_PROMPT


def test_system_prompt_contains_untrusted_data_notice() -> None:
    from songmaker_cli.chat_api import SYSTEM_PROMPT, UNTRUSTED_DATA_NOTICE

    assert UNTRUSTED_DATA_NOTICE in SYSTEM_PROMPT


# ── Pagination ────────────────────────────────────────────────────


def test_list_songs_pagination_offset_limit(client: TestClient) -> None:
    resp = client.get("/api/songs?offset=0&limit=1")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1
    assert data["total"] == 1
    assert data["offset"] == 0
    assert data["limit"] == 1


def test_list_songs_offset_beyond_total(client: TestClient) -> None:
    resp = client.get("/api/songs?offset=100")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 0
    assert data["total"] == 1


def test_list_albums_pagination(client: TestClient) -> None:
    resp = client.get("/api/albums?offset=0&limit=1")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1
    assert data["total"] == 1


def test_list_songs_limit_validation(client: TestClient) -> None:
    resp = client.get("/api/songs?limit=0")
    assert resp.status_code == 422

    resp = client.get("/api/songs?limit=999")
    assert resp.status_code == 422

    resp = client.get("/api/songs?offset=-1")
    assert resp.status_code == 422


# ── Default generation config ────────────────────────────────────────


@pytest.mark.parametrize(
    ("path", "method", "error_statuses"),
    [
        pytest.param("/api/settings/presets", "post", {"400", "409"}, id="create-preset"),
        pytest.param(
            "/api/settings/presets/{preset_id}", "put", {"404", "409"}, id="update-preset",
        ),
        pytest.param(
            "/api/settings/presets/{preset_id}", "delete", {"404"}, id="delete-preset",
        ),
        pytest.param(
            "/api/settings/presets/{preset_id}/set-default", "post", {"404"},
            id="set-default-preset",
        ),
        pytest.param("/api/settings/models/{model_id}", "put", {"404"}, id="toggle-model"),
        pytest.param(
            "/api/settings/default-config", "put", {"400", "404"}, id="set-default-config",
        ),
        pytest.param("/api/settings/claude-models", "put", {"400"}, id="set-claude-models"),
        pytest.param("/api/settings/cowriter", "get", {"422"}, id="get-cowriter"),
        pytest.param("/api/settings/cowriter", "put", {"422", "503"}, id="set-cowriter"),
        pytest.param("/api/settings/judge", "get", {"422"}, id="get-judge"),
        pytest.param("/api/settings/judge", "put", {"422", "503"}, id="set-judge"),
        pytest.param("/api/settings/rate-limits", "put", {"400"}, id="set-rate-limits"),
        pytest.param(
            "/api/settings/rate-limits/user/{user_id}", "get", {"404"},
            id="get-user-rate-limits",
        ),
        pytest.param(
            "/api/settings/rate-limits/user/{user_id}", "put", {"400", "404"},
            id="set-user-rate-limits",
        ),
        pytest.param(
            "/api/settings/rate-limits/user/{user_id}", "delete", {"404"},
            id="delete-user-rate-limits",
        ),
    ],
)
def test_settings_api_documents_its_http_error_responses(
    client: TestClient,
    path: str,
    method: str,
    error_statuses: set[str],
) -> None:
    documented_responses = client.app.openapi()["paths"][path][method]["responses"]

    assert error_statuses.issubset(documented_responses)
    assert all(documented_responses[status]["description"] for status in error_statuses)


def test_default_config_get_returns_null(client: TestClient) -> None:
    resp = client.get("/api/settings/default-config")
    assert resp.status_code == 200
    assert resp.json()["config"] is None


def test_default_config_set_builtin(client: TestClient) -> None:
    resp = client.put("/api/settings/default-config", json={"config": "sft"})
    assert resp.status_code == 200
    assert resp.json()["config"] == "sft"

    resp = client.get("/api/settings/default-config")
    assert resp.json()["config"] == "sft"


def test_default_config_set_null(client: TestClient) -> None:
    client.put("/api/settings/default-config", json={"config": "turbo"})
    resp = client.put("/api/settings/default-config", json={"config": None})
    assert resp.status_code == 200
    assert resp.json()["config"] is None


def test_default_config_invalid_id(client: TestClient) -> None:
    resp = client.put("/api/settings/default-config", json={"config": "nonexistent-uuid"})
    assert resp.status_code == 400


def test_default_config_set_own_preset(client: TestClient) -> None:
    preset = client.post("/api/settings/presets", json={
        "name": "my config", "model_mode": "sft", "params": {"inference_steps": 50},
    }).json()

    resp = client.put("/api/settings/default-config", json={"config": preset["id"]})
    assert resp.status_code == 200
    assert resp.json()["config"] == preset["id"]


def test_presets_include_shared_flag(client: TestClient) -> None:
    resp = client.get("/api/settings/presets")
    assert resp.status_code == 200
    for p in resp.json():
        assert "is_shared" in p


def test_setting_a_preset_as_default_replaces_the_previous_default(client: TestClient) -> None:
    first = client.post("/api/settings/presets", json={
        "name": "first", "model_mode": "sft", "params": {"inference_steps": 50},
        "is_default": True,
    })
    second = client.post("/api/settings/presets", json={
        "name": "second", "model_mode": "sft", "params": {"inference_steps": 70},
    })
    assert first.status_code == second.status_code == 200

    selected = client.post(f"/api/settings/presets/{second.json()['id']}/set-default")

    assert selected.status_code == 200
    assert selected.json()["is_default"] is True
    presets_by_id = {preset["id"]: preset for preset in client.get("/api/settings/presets").json()}
    assert presets_by_id[first.json()["id"]]["is_default"] is False
    assert presets_by_id[second.json()["id"]]["is_default"] is True


# ── Available models ─────────────────────────────────────────────────


def test_list_active_models(client: TestClient) -> None:
    resp = client.get("/api/settings/models")
    assert resp.status_code == 200
    models = resp.json()
    active_ids = [m["id"] for m in models]
    assert "sft" in active_ids
    assert "turbo" in active_ids

    by_id = {m["id"]: m for m in models}
    turbo_caps = by_id["turbo"]["capabilities"]
    assert turbo_caps["max_inference_steps"] == 20
    assert "guidance_scale" in turbo_caps["hidden_params"]
    sft_caps = by_id["sft"]["capabilities"]
    assert sft_caps["max_inference_steps"] == 200
    assert sft_caps["hidden_params"] == []
    assert "use_adg" not in sft_caps["hidden_params"]


def test_build_model_response_raises_on_unregistered_model() -> None:
    """If a row in available_models has an id that's not in
    _BUILTIN_DEFAULTS / ACESTEP_PROFILES, that's a registration bug —
    fail loudly instead of silently returning empty defaults."""
    from types import SimpleNamespace

    from songmaker_cli.settings_api import _build_model_response

    fake_model = SimpleNamespace(id="acestep-quantum-v999", is_active=True)
    with pytest.raises(RuntimeError, match="missing from get_builtin_defaults"):
        _build_model_response(fake_model)


def test_create_preset_inactive_model_rejected(client: TestClient) -> None:
    factory = client.app.state.ctx.db
    with factory() as session:
        session.query(AvailableModel).filter_by(id="turbo").update({"is_active": False})
        session.commit()

    resp = client.post("/api/settings/presets", json={
        "name": "turbo test", "model_mode": "turbo", "params": {"inference_steps": 8},
    })
    assert resp.status_code == 400

    with factory() as session:
        session.query(AvailableModel).filter_by(id="turbo").update({"is_active": True})
        session.commit()


# ── Rate limits ───────────────────────────────────────────────────────


def test_deleting_user_rate_limits_restores_the_effective_defaults(tmp_path: Path) -> None:
    admin_client = _make_authed_client(tmp_path, role="admin")
    override_values = {"generation_rate_limit": 1, "chat_rate_limit": 2}

    saved = admin_client.put(
        "/api/settings/rate-limits/user/u-test", json={"settings": override_values},
    )
    assert saved.status_code == 200
    assert {
        item["setting_key"]: item["value"] for item in saved.json()["overrides"]
    } == override_values

    deleted = admin_client.delete("/api/settings/rate-limits/user/u-test")

    assert deleted.status_code == 200
    restored = admin_client.get("/api/settings/rate-limits/user/u-test")
    assert restored.status_code == 200
    assert restored.json()["overrides"] == []
    effective = {
        item["setting_key"]: item for item in restored.json()["effective"]
    }
    assert effective["generation_rate_limit"]["is_override"] is False
    assert effective["chat_rate_limit"]["is_override"] is False


# ── Claude model settings ───────────────────────────────────────────


def test_claude_models_get_requires_admin(client: TestClient) -> None:
    resp = client.get("/api/settings/claude-models")
    assert resp.status_code == 403


def test_claude_models_put_requires_admin(client: TestClient) -> None:
    resp = client.put("/api/settings/claude-models", json={
        "chat_model": "claude-sonnet-4-6",
        "scoring_model": "claude-sonnet-4-6",
    })
    assert resp.status_code == 403


def test_claude_models_get_defaults(tmp_path: Path) -> None:
    c = _make_authed_client(tmp_path, role="admin")
    resp = c.get("/api/settings/claude-models")
    assert resp.status_code == 200
    data = resp.json()
    assert data["chat_model"] == "claude-opus-4-6"
    assert data["scoring_model"] == "claude-opus-4-6"
    assert "claude-opus-4-6" in data["allowed_models"]
    assert "claude-sonnet-4-6" in data["allowed_models"]
    assert "claude-haiku-4-5-20251001" in data["allowed_models"]


def test_claude_models_roundtrip(tmp_path: Path) -> None:
    c = _make_authed_client(tmp_path, role="admin")
    resp = c.put("/api/settings/claude-models", json={
        "chat_model": "claude-sonnet-4-6",
        "scoring_model": "claude-haiku-4-5-20251001",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["chat_model"] == "claude-sonnet-4-6"
    assert data["scoring_model"] == "claude-haiku-4-5-20251001"

    resp = c.get("/api/settings/claude-models")
    data = resp.json()
    assert data["chat_model"] == "claude-sonnet-4-6"
    assert data["scoring_model"] == "claude-haiku-4-5-20251001"


def test_claude_models_rejects_invalid(tmp_path: Path) -> None:
    c = _make_authed_client(tmp_path, role="admin")
    resp = c.put("/api/settings/claude-models", json={
        "chat_model": "gpt-4",
        "scoring_model": "claude-opus-4-6",
    })
    assert resp.status_code == 400

    resp = c.put("/api/settings/claude-models", json={
        "chat_model": "claude-opus-4-6",
        "scoring_model": "not-a-real-model",
    })
    assert resp.status_code == 400


def test_capabilities_reflects_db_model(tmp_path: Path) -> None:
    c = _make_authed_client(tmp_path, role="admin")
    c.put("/api/settings/claude-models", json={
        "chat_model": "claude-sonnet-4-6",
        "scoring_model": "claude-haiku-4-5-20251001",
    })
    resp = c.get("/api/capabilities")
    assert resp.status_code == 200
    data = resp.json()
    assert data["chat_model"] == "claude-sonnet-4-6"
    assert data["scoring_model"] == "claude-haiku-4-5-20251001"


# ── Bulk delete generations ─────────────────────────────────────────


def test_bulk_delete_generations(client: TestClient) -> None:
    resp = client.post(
        "/api/generations/bulk-delete",
        json={"generation_ids": ["g1", "g2"]},
    )
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 2

    assert client.get("/api/generations/g1").status_code == 404
    assert client.get("/api/generations/g2").status_code == 404


def test_bulk_delete_empty_list(client: TestClient) -> None:
    resp = client.post(
        "/api/generations/bulk-delete",
        json={"generation_ids": []},
    )
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 0


def test_bulk_delete_not_found(client: TestClient) -> None:
    resp = client.post(
        "/api/generations/bulk-delete",
        json={"generation_ids": ["g1", "nonexistent"]},
    )
    assert resp.status_code == 404


def test_bulk_delete_other_user(tmp_path: Path) -> None:
    other_user_id = "u-other"

    factory = init_db(tmp_path / "test.db")
    with factory() as session:
        session.add(User(
            id="u-test", username="test_user",
            password_hash="unused", role="user",
        ))
        session.add(User(
            id=other_user_id, username="other_user",
            password_hash="unused", role="user",
        ))
        session.flush()

        album_mine = Album(id="mine", title="My Album", artist="Me", created_by="u-test")
        album_other = Album(
            id="other", title="Other Album", artist="Them", created_by=other_user_id,
        )
        session.add_all([album_mine, album_other])

        song_mine = Song(id="s-mine", title="My Song", album_id="mine", track_number=1)
        song_other = Song(id="s-other", title="Other Song", album_id="other", track_number=1)
        session.add_all([song_mine, song_other])

        ver_mine = Version(id="v-mine", song_id="s-mine", version_number=1, lyrics="a", prompt="b")
        ver_other = Version(
            id="v-other", song_id="s-other", version_number=1, lyrics="c", prompt="d",
        )
        session.add_all([ver_mine, ver_other])

        gen_mine = Generation(
            id="g-mine", song_id="s-mine", version_id="v-mine",
            generation_number=1, mp3_path="mine.mp3",
        )
        gen_other = Generation(
            id="g-other", song_id="s-other", version_id="v-other",
            generation_number=1, mp3_path="other.mp3",
        )
        session.add_all([gen_mine, gen_other])
        session.commit()

    ctx = AppContext(
        db=factory,
        audio_dir=tmp_path / "audio",
        data_dir=tmp_path / "data",
        session_secret=TEST_SECRET,
        redis=make_fake_redis(),
    )
    from songmaker_cli.api import router

    app = FastAPI()
    app.state.ctx = ctx
    app.dependency_overrides[get_current_user] = _fake_user("u-test", "test_user", "user")
    app.include_router(router)
    tc = TestClient(app)

    resp = tc.post(
        "/api/generations/bulk-delete",
        json={"generation_ids": ["g-mine", "g-other"]},
    )
    assert resp.status_code == 404

    with factory() as session:
        assert session.query(Generation).filter_by(id="g-mine").first() is not None
        assert session.query(Generation).filter_by(id="g-other").first() is not None


def test_bulk_delete_cleans_up_files(tmp_path: Path) -> None:
    factory = init_db(tmp_path / "test.db")
    with factory() as session:
        session.add(User(
            id="u-test", username="test_user",
            password_hash="unused", role="user",
        ))
        session.flush()
        _seed_db(session, owner_id="u-test")

    audio_dir = tmp_path / "audio"
    gen_dir = audio_dir / "u-test"
    gen_dir.mkdir(parents=True, exist_ok=True)
    (gen_dir / "g1.mp3").write_bytes(b"fake")
    (gen_dir / "g1.wav").write_bytes(b"fake")
    (gen_dir / "g2.mp3").write_bytes(b"fake")

    ctx = AppContext(
        db=factory,
        audio_dir=audio_dir,
        data_dir=tmp_path / "data",
        session_secret=TEST_SECRET,
        redis=make_fake_redis(),
    )
    from songmaker_cli.api import router

    app = FastAPI()
    app.state.ctx = ctx
    app.dependency_overrides[get_current_user] = _fake_user("u-test", "test_user", "user")
    app.include_router(router)
    tc = TestClient(app)

    resp = tc.post(
        "/api/generations/bulk-delete",
        json={"generation_ids": ["g1", "g2"]},
    )
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 2

    assert not (gen_dir / "g1.mp3").exists()
    assert not (gen_dir / "g1.wav").exists()
    assert not (gen_dir / "g2.mp3").exists()


def test_bulk_delete_requires_auth(unauthed_client: TestClient) -> None:
    resp = unauthed_client.post(
        "/api/generations/bulk-delete",
        json={"generation_ids": ["g1"]},
    )
    assert resp.status_code in (401, 403)
