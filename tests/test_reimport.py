"""Tests for reimport (core logic + API endpoint)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from songmaker_cli.app_context import AppContext
from songmaker_cli.auth import hash_password
from songmaker_cli.db.engine import init_test_db
from songmaker_cli.db.models import Album, Generation, ResourceEvent, Song, User, Version
from songmaker_cli.db.queries import get_generation
from songmaker_cli.reimport import _extract_seed, reimport_files

TEST_SECRET = b"a" * 64
USER_ID = "u-reimport"
SONG_ID = "s-reimport"
PASSWORD = "Test1234!"


def _make_fake_redis():
    import fakeredis
    return fakeredis.FakeRedis()


def _seed_db(session: Session) -> None:
    session.add(User(
        id=USER_ID, username="reimporter", password_hash=hash_password(PASSWORD), role="admin",
    ))
    session.flush()
    album = Album(id="a-reimport", title="Reimport Album", artist="Test", created_by=USER_ID)
    session.add(album)
    session.flush()
    song = Song(id=SONG_ID, title="Reimport Song", album_id="a-reimport", track_number=1)
    session.add(song)
    session.flush()
    session.add(Version(
        song_id=SONG_ID, version_number=1, lyrics="test lyrics", prompt="test prompt",
    ))
    session.flush()


@pytest.fixture
def seeded_db(tmp_path: Path):
    factory = init_test_db(tmp_path / "data" / "songmaker.db")
    with factory() as session:
        _seed_db(session)
        session.commit()
    return factory


# ── Core reimport logic ──────────────────────────────────────────────


def test_reimport_mp3(seeded_db, tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    mp3_src = tmp_path / "source.mp3"
    mp3_src.write_bytes(b"fake-mp3-data")

    with seeded_db() as session:
        gen_id = reimport_files(session, audio_dir, USER_ID, SONG_ID, mp3_file=mp3_src)
        session.commit()

    with seeded_db() as session:
        gen = get_generation(session, gen_id)
        assert gen is not None
        assert gen.song_id == SONG_ID
        assert gen.id in gen.mp3_path
        assert gen.mp3_path.startswith(f"{USER_ID}/")
        assert gen.mp3_path.endswith(".mp3")
        dst = audio_dir / gen.mp3_path
        assert dst.exists()
        assert dst.read_bytes() == b"fake-mp3-data"
        event = session.query(ResourceEvent).one()
        assert event.generation_id == gen.id
        assert event.resource_id == SONG_ID


def test_reimport_mp3_measures_audio_duration(
    seeded_db, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import songmaker_cli.queue_streams as qs

    audio_dir = tmp_path / "audio"
    mp3_src = tmp_path / "source.mp3"
    mp3_src.write_bytes(b"fake-mp3-data")

    probed: list[Path] = []

    def _read(path: Path) -> float:
        probed.append(path)
        return 188.0

    monkeypatch.setattr(qs, "read_audio_duration", _read)

    with seeded_db() as session:
        gen_id = reimport_files(session, audio_dir, USER_ID, SONG_ID, mp3_file=mp3_src)
        session.commit()

    with seeded_db() as session:
        gen = get_generation(session, gen_id)
        assert gen.audio_duration_sec == 188.0
        assert probed == [audio_dir / gen.mp3_path]


def test_reimport_wav(seeded_db, tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    wav_src = tmp_path / "source.wav"
    wav_src.write_bytes(b"fake-wav-data")

    with seeded_db() as session:
        gen_id = reimport_files(session, audio_dir, USER_ID, SONG_ID, wav_file=wav_src)
        session.commit()

    with seeded_db() as session:
        gen = get_generation(session, gen_id)
        assert gen is not None
        assert gen.wav_path.endswith(".wav")
        assert gen.mp3_path == ""


def test_reimport_both(seeded_db, tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    mp3_src = tmp_path / "source.mp3"
    mp3_src.write_bytes(b"mp3")
    wav_src = tmp_path / "source.wav"
    wav_src.write_bytes(b"wav")

    with seeded_db() as session:
        gen_id = reimport_files(
            session, audio_dir, USER_ID, SONG_ID,
            mp3_file=mp3_src, wav_file=wav_src,
        )
        session.commit()

    with seeded_db() as session:
        gen = get_generation(session, gen_id)
        assert gen.mp3_path.endswith(".mp3")
        assert gen.wav_path.endswith(".wav")
        assert (audio_dir / gen.mp3_path).exists()
        assert (audio_dir / gen.wav_path).exists()


def test_reimport_no_files_raises(seeded_db, tmp_path: Path) -> None:
    with seeded_db() as session:
        with pytest.raises(ValueError, match="At least one"):
            reimport_files(session, tmp_path / "audio", USER_ID, SONG_ID)


def test_reimport_event_failure_rolls_back_and_removes_files(
    seeded_db, tmp_path: Path,
) -> None:
    audio_dir = tmp_path / "audio"
    mp3_src = tmp_path / "source.mp3"
    mp3_src.write_bytes(b"fake-mp3")

    with (
        seeded_db() as session,
        patch(
            "songmaker_cli.reimport.create_generation_created_event",
            side_effect=RuntimeError("event write failed"),
        ),
    ):
        with pytest.raises(RuntimeError, match="event write failed"):
            reimport_files(session, audio_dir, USER_ID, SONG_ID, mp3_file=mp3_src)
        session.rollback()

    with seeded_db() as session:
        assert session.query(ResourceEvent).count() == 0
        assert session.query(Generation).count() == 0
    assert list((audio_dir / USER_ID).glob("*")) == []


def test_extract_seed_no_tags(tmp_path: Path) -> None:
    mp3 = tmp_path / "no_tags.mp3"
    mp3.write_bytes(b"not a real mp3")
    assert _extract_seed(mp3) is None


def test_extract_seed_with_mutagen(tmp_path: Path) -> None:
    from mutagen.id3 import COMM, ID3

    mp3 = tmp_path / "tagged.mp3"
    mp3.write_bytes(b"\xff\xfb\x90\x00" + b"\x00" * 1024)
    try:
        tags = ID3(str(mp3))
    except Exception:
        tags = ID3()
    tags.add(COMM(encoding=3, lang="eng", desc="", text=["seed=42"]))
    tags.save(str(mp3))

    assert _extract_seed(mp3) == 42


# ── API endpoint ─────────────────────────────────────────────────────


def _fake_user():
    from songmaker_cli.middleware import AuthenticatedUser
    return lambda: AuthenticatedUser(
        id=USER_ID, username="reimporter", role="admin", is_active=True,
    )


@pytest.fixture
def reimport_client(tmp_path: Path):
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir(parents=True)
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)

    factory = init_test_db(data_dir / "songmaker.db")
    with factory() as session:
        _seed_db(session)
        session.commit()

    ctx = AppContext(
        db=factory, audio_dir=audio_dir, data_dir=data_dir,
        session_secret=TEST_SECRET, redis=_make_fake_redis(),
    )

    from fastapi import FastAPI

    from songmaker_cli.api import router
    from songmaker_cli.middleware import get_current_user

    app = FastAPI()
    app.state.ctx = ctx
    app.dependency_overrides[get_current_user] = _fake_user()
    app.include_router(router)
    return TestClient(app)


def test_reimport_api_mp3(reimport_client: TestClient) -> None:
    resp = reimport_client.post(
        f"/api/songs/{SONG_ID}/reimport",
        files={"mp3": ("test.mp3", b"fake-mp3", "audio/mpeg")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["mp3_path"].endswith(".mp3")
    assert data["song_id"] == SONG_ID
    with reimport_client.app.state.ctx.db() as session:
        event = session.query(ResourceEvent).one()
        assert event.generation_id == data["id"]


def test_reimport_api_no_files(reimport_client: TestClient) -> None:
    resp = reimport_client.post(f"/api/songs/{SONG_ID}/reimport")
    assert resp.status_code == 422


def test_reimport_api_commit_failure_removes_files(
    reimport_client: TestClient,
) -> None:
    with (
        patch("sqlalchemy.orm.Session.commit", side_effect=RuntimeError("commit failed")),
        pytest.raises(RuntimeError, match="commit failed"),
    ):
        reimport_client.post(
            f"/api/songs/{SONG_ID}/reimport",
            files={"mp3": ("test.mp3", b"fake-mp3", "audio/mpeg")},
        )

    audio_dir = reimport_client.app.state.ctx.audio_dir
    assert list((audio_dir / USER_ID).glob("*")) == []
    with reimport_client.app.state.ctx.db() as session:
        assert session.query(Generation).count() == 0
        assert session.query(ResourceEvent).count() == 0


def test_reimport_api_wrong_song(reimport_client: TestClient) -> None:
    resp = reimport_client.post(
        "/api/songs/nonexistent/reimport",
        files={"mp3": ("test.mp3", b"fake-mp3", "audio/mpeg")},
    )
    assert resp.status_code == 404
