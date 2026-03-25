"""Tests for the database layer — models, engine, queries."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from songmaker_cli.api_models import (
    AlbumResponse,
    GenerationResponse,
    JobResponse,
    LoginAttemptResponse,
    SessionResponse,
    SongResponse,
    UserResponse,
    VersionResponse,
)
from songmaker_cli.db.engine import init_db, reset_engine
from songmaker_cli.db.models import (
    Album,
    Generation,
    LoginAttempt,
    Rating,
    Score,
    Song,
    User,
    Version,
)
from songmaker_cli.db.queries import (
    _UNSET,
    _delete_generation_files,
    cleanup_album,
    count_recent_failed_attempts,
    count_total_queued_jobs,
    count_user_active_jobs,
    count_user_jobs_in_window,
    create_generation,
    create_job,
    create_session,
    create_song,
    create_user,
    delete_expired_sessions,
    delete_generation,
    delete_session,
    delete_version,
    get_album,
    get_generation,
    get_generation_by_path,
    get_job,
    get_session_with_user,
    get_song,
    get_user,
    get_user_by_username,
    list_active_sessions,
    list_albums,
    list_login_attempts,
    list_songs,
    list_users,
    pick_generation,
    record_login_attempt,
    recover_stale_jobs,
    save_rating,
    save_scores,
    unpick_generation,
    update_job_status,
    update_song,
    update_user,
    user_count,
)


@pytest.fixture()
def db_session(tmp_path: Path) -> Session:
    reset_engine()
    factory = init_db(tmp_path / "test.db")
    session = factory()
    yield session
    session.close()
    reset_engine()


@pytest.fixture()
def seeded_session(db_session: Session) -> Session:
    album = Album(id="test", title="Test Album", artist="TestArtist")
    db_session.add(album)

    song = Song(id="s1", title="Song One", album_id="test", track_number=1)
    db_session.add(song)

    ver = Version(id="v1", song_id="s1", version_number=1, lyrics="verse one", prompt="rock")
    db_session.add(ver)

    gen1 = Generation(
        id="g1", song_id="s1", version_id="v1", generation_number=1,
        mp3_path="test/01_song_one_v1.mp3", seed=42,
        generation_params={"bpm": 120, "key": "Am"},
    )
    gen2 = Generation(
        id="g2", song_id="s1", version_id="v1", generation_number=2,
        mp3_path="test/01_song_one_v2.mp3", seed=99,
    )
    db_session.add_all([gen1, gen2])

    score = Score(id="sc1", generation_id="g1", scorer="batch", value={"dynamics": 55.0})
    db_session.add(score)

    rating = Rating(id="r1", generation_id="g1", rating=82.5, notes="great groove")
    db_session.add(rating)

    db_session.commit()
    return db_session


def test_song_latest_version(seeded_session: Session) -> None:
    song = seeded_session.query(Song).filter_by(id="s1").one()
    assert song.latest_version is not None
    assert song.latest_version.lyrics == "verse one"


def test_generation_scores(seeded_session: Session) -> None:
    gen = get_generation(seeded_session, "g1")
    assert gen is not None
    assert len(gen.scores) == 1
    assert gen.scores[0].value["dynamics"] == 55.0


def test_generation_rating(seeded_session: Session) -> None:
    gen = get_generation(seeded_session, "g1")
    assert gen is not None
    assert gen.rating is not None
    assert gen.rating.rating == 82.5


def test_list_albums(seeded_session: Session) -> None:
    assert len(list_albums(seeded_session)) == 1


def test_list_albums_filtered_by_user(db_session: Session) -> None:
    from songmaker_cli.db.queries import create_album, list_albums

    u1 = create_user(db_session, "alice", "h", role="user")
    u2 = create_user(db_session, "bob", "h", role="user")
    db_session.flush()
    create_album(db_session, "a1", "Album A", created_by=u1.id)
    create_album(db_session, "a2", "Album B", created_by=u2.id)
    create_album(db_session, "a3", "Album C", created_by=u1.id)
    db_session.commit()

    assert len(list_albums(db_session)) == 3
    assert len(list_albums(db_session, user_id=u1.id)) == 2
    assert len(list_albums(db_session, user_id=u2.id)) == 1


def test_create_album(db_session: Session) -> None:
    from songmaker_cli.db.queries import create_album, get_album

    album = create_album(db_session, "my-album", "My Album", artist="Artist")
    db_session.commit()
    assert album.id == "my-album"
    assert album.title == "My Album"
    assert album.artist == "Artist"
    assert get_album(db_session, "my-album") is not None


def test_create_album_with_owner(db_session: Session) -> None:
    from songmaker_cli.db.queries import create_album

    user = create_user(db_session, "owner", "h", role="user")
    db_session.flush()
    album = create_album(db_session, "owned", "Owned", created_by=user.id)
    db_session.commit()
    assert album.created_by == user.id


def test_list_songs(seeded_session: Session) -> None:
    songs = list_songs(seeded_session)
    assert len(songs) == 1
    assert songs[0].title == "Song One"


def test_get_song(seeded_session: Session) -> None:
    song = get_song(seeded_session, "s1")
    assert song is not None
    assert len(song.generations) == 2


def test_get_generation_by_path(seeded_session: Session) -> None:
    gen = get_generation_by_path(seeded_session, "test/01_song_one_v1.mp3")
    assert gen is not None
    assert gen.id == "g1"


def test_save_rating_create(seeded_session: Session) -> None:
    save_rating(seeded_session, "g2", 75.0, "decent")
    seeded_session.commit()
    gen = get_generation(seeded_session, "g2")
    assert gen.rating.rating == 75.0


def test_save_rating_update(seeded_session: Session) -> None:
    save_rating(seeded_session, "g1", 90.0, "updated")
    seeded_session.commit()
    gen = get_generation(seeded_session, "g1")
    assert gen.rating.rating == 90.0


def test_create_song(seeded_session: Session) -> None:
    song = create_song(seeded_session, "Song Two", "test", lyrics="hello", bpm=140)
    seeded_session.commit()
    assert song.track_number == 2
    assert song.latest_version.lyrics == "hello"


def test_update_song(seeded_session: Session) -> None:
    ver = update_song(seeded_session, "s1", lyrics="new lyrics")
    seeded_session.commit()
    assert ver.version_number == 2
    assert ver.lyrics == "new lyrics"


def test_generation_to_dict(seeded_session: Session) -> None:
    gen = get_generation(seeded_session, "g1")
    d = GenerationResponse.from_orm(gen).model_dump()
    assert d["seed"] == 42
    assert d["scores"]["dynamics"] == 55.0
    assert d["scores"]["user_rating"] == 82.5


def test_song_to_dict(seeded_session: Session) -> None:
    song = get_song(seeded_session, "s1")
    d = SongResponse.from_orm(song).model_dump()
    assert d["title"] == "Song One"
    assert d["generation_count"] == 2
    assert d["best_rating"] == 82.5
    assert len(d["generations"]) == 2


def test_album_to_dict(seeded_session: Session) -> None:
    album = get_album(seeded_session, "test")
    d = AlbumResponse.from_orm(album).model_dump()
    assert d["song_count"] == 1


# ── Delete tests ─────────────────────────────────────────────────────


def test_delete_generation(seeded_session: Session) -> None:
    delete_generation(seeded_session, "g2")
    seeded_session.commit()
    assert get_generation(seeded_session, "g2") is None
    song = get_song(seeded_session, "s1")
    assert len(song.generations) == 1


def test_delete_generation_not_found(seeded_session: Session) -> None:
    with pytest.raises(ValueError, match="not found"):
        delete_generation(seeded_session, "nonexistent")


def test_delete_version_keep_generations(seeded_session: Session) -> None:
    delete_version(seeded_session, "v1", delete_generations=False)
    seeded_session.commit()
    gen = get_generation(seeded_session, "g1")
    assert gen is not None
    assert gen.version_id is None


def test_delete_version_with_generations(seeded_session: Session) -> None:
    delete_version(seeded_session, "v1", delete_generations=True)
    seeded_session.commit()
    assert get_generation(seeded_session, "g1") is None
    assert get_generation(seeded_session, "g2") is None


def test_delete_version_not_found(seeded_session: Session) -> None:
    with pytest.raises(ValueError, match="not found"):
        delete_version(seeded_session, "nonexistent")


# ── Pick tests ───────────────────────────────────────────────────────


def test_pick_generation(seeded_session: Session) -> None:
    pick_generation(seeded_session, "g1")
    seeded_session.commit()
    gen = get_generation(seeded_session, "g1")
    assert gen.is_picked is True


def test_pick_unpicks_previous(seeded_session: Session) -> None:
    pick_generation(seeded_session, "g1")
    seeded_session.commit()
    pick_generation(seeded_session, "g2")
    seeded_session.commit()
    assert get_generation(seeded_session, "g1").is_picked is False
    assert get_generation(seeded_session, "g2").is_picked is True


def test_unpick_generation(seeded_session: Session) -> None:
    pick_generation(seeded_session, "g1")
    seeded_session.commit()
    unpick_generation(seeded_session, "g1")
    seeded_session.commit()
    assert get_generation(seeded_session, "g1").is_picked is False


def test_cleanup_album_deletes_unpicked(seeded_session: Session) -> None:
    pick_generation(seeded_session, "g1")
    seeded_session.commit()
    deleted = cleanup_album(seeded_session, "test")
    seeded_session.commit()
    assert deleted == 1
    assert get_generation(seeded_session, "g1") is not None
    assert get_generation(seeded_session, "g2") is None


def test_cleanup_album_no_picks_deletes_all(seeded_session: Session) -> None:
    deleted = cleanup_album(seeded_session, "test")
    seeded_session.commit()
    assert deleted == 2


# ── Job tests ────────────────────────────────────────────────────────


def test_create_job(seeded_session: Session) -> None:
    job = create_job(seeded_session, "generate")
    seeded_session.commit()
    assert job.type == "generate"
    assert job.status == "queued"
    assert job.progress == 0.0


def test_update_job_status(seeded_session: Session) -> None:
    job = create_job(seeded_session, "score")
    seeded_session.commit()
    update_job_status(seeded_session, job.id, "running", progress=0.5)
    seeded_session.commit()
    fetched = get_job(seeded_session, job.id)
    assert fetched.status == "running"
    assert fetched.progress == 0.5


def test_update_job_completed(seeded_session: Session) -> None:
    job = create_job(seeded_session, "score")
    seeded_session.commit()
    update_job_status(seeded_session, job.id, "completed", progress=1.0)
    seeded_session.commit()
    fetched = get_job(seeded_session, job.id)
    assert fetched.status == "completed"
    assert fetched.completed_at is not None


def test_update_job_failed(seeded_session: Session) -> None:
    job = create_job(seeded_session, "generate")
    seeded_session.commit()
    update_job_status(seeded_session, job.id, "failed", error="ACE-Step down")
    seeded_session.commit()
    fetched = get_job(seeded_session, job.id)
    assert fetched.status == "failed"
    assert fetched.error == "ACE-Step down"


def test_job_to_dict(seeded_session: Session) -> None:
    job = create_job(seeded_session, "generate")
    seeded_session.commit()
    d = JobResponse.from_orm(job).model_dump()
    assert d["type"] == "generate"
    assert d["status"] == "queued"
    assert "id" in d


# ── Create generation + scores tests ─────────────────────────────────


def test_create_generation(seeded_session: Session) -> None:
    gen = create_generation(
        seeded_session, "s1", "v1", "test/new_gen.mp3", seed=123,
        generation_params={"bpm": 140},
    )
    seeded_session.commit()
    assert gen.generation_number == 3
    assert gen.seed == 123
    assert gen.mp3_path == "test/new_gen.mp3"


def test_save_scores_create(seeded_session: Session) -> None:
    save_scores(seeded_session, "g2", {"dynamics": 77.0, "enjoyment": 8.5})
    seeded_session.commit()
    gen = get_generation(seeded_session, "g2")
    scores = {s.scorer: s.value for s in gen.scores}
    assert scores["batch"]["dynamics"] == 77.0


def test_save_scores_upsert(seeded_session: Session) -> None:
    save_scores(seeded_session, "g1", {"dynamics": 99.0})
    seeded_session.commit()
    gen = get_generation(seeded_session, "g1")
    batch_scores = [s for s in gen.scores if s.scorer == "batch"]
    assert len(batch_scores) == 1
    assert batch_scores[0].value["dynamics"] == 99.0


def test_save_scores_upsert_persists(db_session: Session) -> None:
    """Verify score upsert actually persists to DB (not just in-memory)."""
    from songmaker_cli.db.engine import get_session_factory

    album = Album(id="t2", title="T2", artist="A")
    db_session.add(album)
    song = Song(id="s2", title="S2", album_id="t2", track_number=1)
    db_session.add(song)
    ver = Version(id="v2", song_id="s2", version_number=1, lyrics="x", prompt="y")
    db_session.add(ver)
    gen = Generation(
        id="gx", song_id="s2", version_id="v2", generation_number=1,
        mp3_path="t2/test.mp3",
    )
    db_session.add(gen)
    score = Score(id="scx", generation_id="gx", scorer="batch", value={"old": 1.0})
    db_session.add(score)
    db_session.commit()
    db_session.close()

    factory = get_session_factory()
    with factory() as s2:
        save_scores(s2, "gx", {"new": 99.0})
        s2.commit()

    with factory() as s3:
        reloaded = get_generation(s3, "gx")
        batch = [s for s in reloaded.scores if s.scorer == "batch"]
        assert len(batch) == 1
        assert batch[0].value == {"new": 99.0}


def test_generation_to_dict_has_is_picked(seeded_session: Session) -> None:
    gen = get_generation(seeded_session, "g1")
    d = GenerationResponse.from_orm(gen).model_dump()
    assert d["is_picked"] is False
    assert "version_number" in d


# ── Generation params on Version ────────────────────────────────────


def test_create_song_with_generation_params(db_session: Session) -> None:
    db_session.add(Album(id="a1", title="A", artist="X"))
    db_session.flush()
    params = {"inference_steps": 50, "guidance_scale": 5.5}
    song = create_song(db_session, "S", "a1", generation_params=params)
    db_session.commit()
    ver = song.latest_version
    assert ver.generation_params == params


def test_create_song_without_generation_params(db_session: Session) -> None:
    db_session.add(Album(id="a1", title="A", artist="X"))
    db_session.flush()
    song = create_song(db_session, "S", "a1")
    db_session.commit()
    assert song.latest_version.generation_params is None


def test_update_song_sets_generation_params(seeded_session: Session) -> None:
    params = {"inference_steps": 25, "shift": 2.0}
    update_song(seeded_session, "s1", generation_params=params)
    seeded_session.commit()
    song = get_song(seeded_session, "s1")
    assert song.latest_version.generation_params == params


def test_update_song_carries_forward_params(seeded_session: Session) -> None:
    params = {"inference_steps": 25}
    update_song(seeded_session, "s1", generation_params=params)
    seeded_session.commit()
    update_song(seeded_session, "s1", lyrics="new lyrics")
    seeded_session.commit()
    song = get_song(seeded_session, "s1")
    assert song.latest_version.generation_params == params
    assert song.latest_version.lyrics == "new lyrics"


def test_update_song_clears_generation_params(seeded_session: Session) -> None:
    update_song(seeded_session, "s1", generation_params={"inference_steps": 25})
    seeded_session.commit()
    update_song(seeded_session, "s1", generation_params=None)
    seeded_session.commit()
    song = get_song(seeded_session, "s1")
    assert song.latest_version.generation_params is None


def test_update_song_unset_keeps_previous(seeded_session: Session) -> None:
    update_song(seeded_session, "s1", generation_params={"shift": 5.0})
    seeded_session.commit()
    update_song(seeded_session, "s1", lyrics="changed", generation_params=_UNSET)
    seeded_session.commit()
    song = get_song(seeded_session, "s1")
    assert song.latest_version.generation_params == {"shift": 5.0}


def test_version_to_dict_includes_generation_params(seeded_session: Session) -> None:
    params = {"guidance_scale": 3.0}
    update_song(seeded_session, "s1", generation_params=params)
    seeded_session.commit()
    song = get_song(seeded_session, "s1")
    d = VersionResponse.from_orm(song.latest_version).model_dump()
    assert d["generation_params"] == params


def test_song_to_dict_includes_generation_params(seeded_session: Session) -> None:
    params = {"lm_temperature": 0.5}
    update_song(seeded_session, "s1", generation_params=params)
    seeded_session.commit()
    song = get_song(seeded_session, "s1")
    d = SongResponse.from_orm(song).model_dump()
    assert d["generation_params"] == params


# ── Engine: init_db ─────────────────────────────────────────────────


def test_init_db_idempotent(tmp_path: Path) -> None:
    reset_engine()
    f1 = init_db(tmp_path / "test.db")
    f2 = init_db(tmp_path / "test.db")
    assert f1 is f2
    reset_engine()


def test_get_session_factory_before_init() -> None:
    from songmaker_cli.db.engine import get_session_factory
    reset_engine()
    with pytest.raises(RuntimeError, match="not initialized"):
        get_session_factory()
    reset_engine()


def test_init_db_different_path_raises(tmp_path: Path) -> None:
    reset_engine()
    init_db(tmp_path / "a.db")
    with pytest.raises(RuntimeError, match="already initialized"):
        init_db(tmp_path / "b.db")
    reset_engine()


# ── queries.py gap coverage ─────────────────────────────────────────


def test_list_songs_with_album_filter(seeded_session: Session) -> None:
    result = list_songs(seeded_session, album_id="test")
    assert len(result) >= 1
    assert all(s.album_id == "test" for s in result)


def test_list_songs_with_unknown_album_filter(seeded_session: Session) -> None:
    result = list_songs(seeded_session, album_id="nonexistent")
    assert result == []


def test_create_song_album_not_found(db_session: Session) -> None:
    with pytest.raises(ValueError, match="Album not found"):
        create_song(db_session, "Test", "nonexistent")


def test_update_song_not_found(db_session: Session) -> None:
    with pytest.raises(ValueError, match="Song not found"):
        update_song(db_session, "nonexistent", lyrics="x")


def test_update_job_status_missing_job(db_session: Session) -> None:
    update_job_status(db_session, "nonexistent", "running")


def test_pick_generation_not_found(db_session: Session) -> None:
    with pytest.raises(ValueError, match="Generation not found"):
        pick_generation(db_session, "nonexistent")


def test_unpick_generation_not_found(db_session: Session) -> None:
    with pytest.raises(ValueError, match="Generation not found"):
        unpick_generation(db_session, "nonexistent")


def test_delete_generation_files_exist(seeded_session: Session, tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    album_dir = output_dir / "test"
    album_dir.mkdir(parents=True)
    mp3 = album_dir / "01_song_one_v1.mp3"
    mp3.write_bytes(b"fake")
    md = album_dir / "01_song_one_v1.md"
    md.write_text("snapshot")

    delete_generation(seeded_session, "g1", output_dir=output_dir)
    seeded_session.commit()

    assert not mp3.exists()
    assert not md.exists()


def test_delete_generation_files_path_traversal_blocked(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    sentinel = tmp_path / "etc" / "passwd"
    sentinel.parent.mkdir()
    sentinel.write_text("secret")

    _delete_generation_files(output_dir, "../../etc/passwd")

    assert sentinel.exists()


# ── User queries ────────────────────────────────────────────────────


def test_create_user(db_session: Session) -> None:
    user = create_user(db_session, "alice", "hash123", role="admin")
    db_session.commit()
    assert user.username == "alice"
    assert user.role == "admin"
    assert user.is_active is True
    assert user.created_at is not None


def test_get_user_by_username(db_session: Session) -> None:
    create_user(db_session, "bob", "hash456")
    db_session.commit()
    user = get_user_by_username(db_session, "bob")
    assert user is not None
    assert user.username == "bob"


def test_get_user_by_username_not_found(db_session: Session) -> None:
    assert get_user_by_username(db_session, "nobody") is None


def test_get_user(db_session: Session) -> None:
    user = create_user(db_session, "carol", "hash789")
    db_session.commit()
    fetched = get_user(db_session, user.id)
    assert fetched is not None
    assert fetched.username == "carol"


def test_get_user_not_found(db_session: Session) -> None:
    assert get_user(db_session, "nonexistent") is None


def test_list_users(db_session: Session) -> None:
    create_user(db_session, "alice", "h1", role="admin")
    create_user(db_session, "bob", "h2")
    db_session.commit()
    users = list_users(db_session)
    assert len(users) == 2
    assert users[0].username == "alice"
    assert users[1].username == "bob"


def test_user_count(db_session: Session) -> None:
    assert user_count(db_session) == 0
    create_user(db_session, "alice", "h1")
    db_session.flush()
    assert user_count(db_session) == 1


def test_update_user_role(db_session: Session) -> None:
    user = create_user(db_session, "alice", "h1")
    db_session.commit()
    updated = update_user(db_session, user.id, role="admin")
    db_session.commit()
    assert updated.role == "admin"


def test_update_user_deactivate(db_session: Session) -> None:
    user = create_user(db_session, "alice", "h1")
    db_session.commit()
    updated = update_user(db_session, user.id, is_active=False)
    db_session.commit()
    assert updated.is_active is False


def test_update_user_password(db_session: Session) -> None:
    user = create_user(db_session, "alice", "old_hash")
    db_session.commit()
    updated = update_user(db_session, user.id, password_hash="new_hash")
    db_session.commit()
    assert updated.password_hash == "new_hash"


def test_update_user_not_found(db_session: Session) -> None:
    with pytest.raises(ValueError, match="User not found"):
        update_user(db_session, "nonexistent", role="admin")


# ── Session queries ─────────────────────────────────────────────────


def _make_user(db_session: Session, username: str = "testuser") -> User:
    user = create_user(db_session, username, "hash")
    db_session.flush()
    return user


def test_create_and_get_session(db_session: Session) -> None:
    from datetime import datetime, timedelta, timezone

    user = _make_user(db_session)
    expires = datetime.now(timezone.utc) + timedelta(days=30)
    sess = create_session(db_session, user.id, expires, ip_address="127.0.0.1", user_agent="test")
    db_session.commit()

    fetched = get_session_with_user(db_session, sess.id)
    assert fetched is not None
    assert fetched.user.username == "testuser"
    assert fetched.ip_address == "127.0.0.1"


def test_get_session_not_found(db_session: Session) -> None:
    assert get_session_with_user(db_session, "nonexistent") is None


def test_delete_session(db_session: Session) -> None:
    from datetime import datetime, timedelta, timezone

    user = _make_user(db_session)
    expires = datetime.now(timezone.utc) + timedelta(days=30)
    sess = create_session(db_session, user.id, expires)
    db_session.commit()

    delete_session(db_session, sess.id)
    db_session.commit()
    assert get_session_with_user(db_session, sess.id) is None


def test_delete_session_not_found(db_session: Session) -> None:
    delete_session(db_session, "nonexistent")


def test_list_active_sessions(db_session: Session) -> None:
    from datetime import datetime, timedelta, timezone

    user = _make_user(db_session)
    now = datetime.now(timezone.utc)
    create_session(db_session, user.id, now + timedelta(days=30))
    create_session(db_session, user.id, now - timedelta(days=1))
    db_session.commit()

    active = list_active_sessions(db_session)
    assert len(active) == 1


def test_delete_expired_sessions(db_session: Session) -> None:
    from datetime import datetime, timedelta, timezone

    user = _make_user(db_session)
    now = datetime.now(timezone.utc)
    create_session(db_session, user.id, now + timedelta(days=30))
    create_session(db_session, user.id, now - timedelta(days=1))
    db_session.commit()

    deleted = delete_expired_sessions(db_session)
    db_session.commit()
    assert deleted == 1


# ── Login attempt queries ───────────────────────────────────────────


def test_record_login_attempt(db_session: Session) -> None:
    attempt = record_login_attempt(db_session, "192.168.1.1", "alice", success=True)
    db_session.commit()
    assert attempt.ip_address == "192.168.1.1"
    assert attempt.success is True


def test_count_recent_failed_attempts(db_session: Session) -> None:
    record_login_attempt(db_session, "10.0.0.1", "alice", success=False)
    record_login_attempt(db_session, "10.0.0.1", "alice", success=False)
    record_login_attempt(db_session, "10.0.0.1", "alice", success=True)
    record_login_attempt(db_session, "10.0.0.2", "bob", success=False)
    db_session.commit()

    count = count_recent_failed_attempts(db_session, "10.0.0.1")
    assert count == 2


def test_count_recent_failed_attempts_outside_window(db_session: Session) -> None:
    from datetime import datetime, timedelta, timezone

    old = LoginAttempt(
        ip_address="10.0.0.1", username="alice", success=False,
        attempted_at=datetime.now(timezone.utc) - timedelta(seconds=600),
    )
    db_session.add(old)
    db_session.commit()

    count = count_recent_failed_attempts(db_session, "10.0.0.1", window_seconds=300)
    assert count == 0


def test_list_login_attempts(db_session: Session) -> None:
    record_login_attempt(db_session, "10.0.0.1", "alice", success=False)
    record_login_attempt(db_session, "10.0.0.1", "alice", success=True)
    db_session.commit()

    attempts = list_login_attempts(db_session, limit=10)
    assert len(attempts) == 2
    assert attempts[0].attempted_at >= attempts[1].attempted_at


def test_list_login_attempts_limit(db_session: Session) -> None:
    for i in range(5):
        record_login_attempt(db_session, "10.0.0.1", f"user{i}", success=False)
    db_session.commit()

    attempts = list_login_attempts(db_session, limit=3)
    assert len(attempts) == 3


# ── Auth API models ─────────────────────────────────────────────────


def test_user_response_from_orm(db_session: Session) -> None:
    user = create_user(db_session, "alice", "hash", role="admin")
    db_session.commit()
    resp = UserResponse.from_orm(user)
    assert resp.id == user.id
    assert resp.username == "alice"
    assert resp.role == "admin"
    assert resp.is_active is True
    assert resp.created_at is not None


def test_session_response_from_orm(db_session: Session) -> None:
    from datetime import datetime, timedelta, timezone

    user = _make_user(db_session, "alice")
    expires = datetime.now(timezone.utc) + timedelta(days=30)
    sess = create_session(
        db_session, user.id, expires, ip_address="127.0.0.1", user_agent="Mozilla/5.0",
    )
    db_session.commit()

    fetched = get_session_with_user(db_session, sess.id)
    resp = SessionResponse.from_orm(fetched)
    assert resp.user_id == user.id
    assert resp.username == "alice"
    assert resp.ip_address == "127.0.0.1"
    assert resp.user_agent == "Mozilla/5.0"


def test_login_attempt_response_from_orm(db_session: Session) -> None:
    attempt = record_login_attempt(db_session, "10.0.0.1", "alice", success=False)
    db_session.commit()
    resp = LoginAttemptResponse.from_orm(attempt)
    assert resp.ip_address == "10.0.0.1"
    assert resp.username == "alice"
    assert resp.success is False
    assert resp.attempted_at is not None


# ── User model cascade ──────────────────────────────────────────────


def test_delete_user_cascades_sessions(db_session: Session) -> None:
    from datetime import datetime, timedelta, timezone

    user = _make_user(db_session)
    expires = datetime.now(timezone.utc) + timedelta(days=30)
    sess = create_session(db_session, user.id, expires)
    db_session.commit()

    db_session.delete(user)
    db_session.commit()
    assert get_session_with_user(db_session, sess.id) is None


# ── Rate limit queries ──────────────────────────────────────────────


def test_create_job_with_user_id(db_session: Session) -> None:
    user = create_user(db_session, "testuser", "hash", role="user")
    db_session.flush()
    job = create_job(db_session, "generate", user_id=user.id)
    db_session.commit()
    assert job.user_id == user.id


def test_create_job_without_user_id(db_session: Session) -> None:
    job = create_job(db_session, "generate")
    db_session.commit()
    assert job.user_id is None


def test_count_user_jobs_in_window(db_session: Session) -> None:
    u1 = create_user(db_session, "user1", "hash", role="user")
    u2 = create_user(db_session, "user2", "hash", role="user")
    db_session.flush()
    create_job(db_session, "generate", user_id=u1.id)
    create_job(db_session, "generate", user_id=u1.id)
    create_job(db_session, "score", user_id=u1.id)
    create_job(db_session, "generate", user_id=u2.id)
    db_session.commit()

    assert count_user_jobs_in_window(db_session, u1.id, "generate") == 2
    assert count_user_jobs_in_window(db_session, u1.id, "score") == 1
    assert count_user_jobs_in_window(db_session, u2.id, "generate") == 1


def test_count_user_jobs_outside_window(db_session: Session) -> None:
    from datetime import datetime, timedelta, timezone

    from songmaker_cli.db.models import Job

    user = create_user(db_session, "testuser", "hash", role="user")
    db_session.flush()
    old_job = Job(
        type="generate", user_id=user.id,
        started_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    db_session.add(old_job)
    db_session.commit()

    assert count_user_jobs_in_window(db_session, user.id, "generate", window_seconds=3600) == 0


def test_count_user_active_jobs(db_session: Session) -> None:
    from songmaker_cli.db.queries import update_job_status

    user = create_user(db_session, "testuser", "hash", role="user")
    db_session.flush()
    create_job(db_session, "generate", user_id=user.id)
    j2 = create_job(db_session, "generate", user_id=user.id)
    create_job(db_session, "generate", user_id=user.id)
    db_session.commit()

    update_job_status(db_session, j2.id, "completed", progress=1.0)
    db_session.commit()

    assert count_user_active_jobs(db_session, user.id) == 2


def test_count_total_queued_jobs(db_session: Session) -> None:
    from songmaker_cli.db.queries import update_job_status

    u1 = create_user(db_session, "user1", "hash", role="user")
    u2 = create_user(db_session, "user2", "hash", role="user")
    db_session.flush()
    create_job(db_session, "generate", user_id=u1.id)
    create_job(db_session, "score", user_id=u2.id)
    j3 = create_job(db_session, "generate")
    db_session.commit()

    update_job_status(db_session, j3.id, "completed", progress=1.0)
    db_session.commit()

    assert count_total_queued_jobs(db_session) == 2


def test_recover_stale_jobs(db_session: Session) -> None:
    from songmaker_cli.db.queries import update_job_status

    j1 = create_job(db_session, "generate")
    j2 = create_job(db_session, "score")
    j3 = create_job(db_session, "generate")
    db_session.commit()

    update_job_status(db_session, j1.id, "running", progress=0.5)
    update_job_status(db_session, j3.id, "completed", progress=1.0)
    db_session.commit()

    count = recover_stale_jobs(db_session)
    db_session.commit()

    assert count == 2

    j1_after = get_job(db_session, j1.id)
    assert j1_after.status == "failed"
    assert j1_after.error_type == "server_restart"
    assert j1_after.completed_at is not None

    j2_after = get_job(db_session, j2.id)
    assert j2_after.status == "failed"

    j3_after = get_job(db_session, j3.id)
    assert j3_after.status == "completed"


def test_recover_stale_jobs_none(db_session: Session) -> None:
    j1 = create_job(db_session, "generate")
    db_session.commit()

    from songmaker_cli.db.queries import update_job_status
    update_job_status(db_session, j1.id, "completed", progress=1.0)
    db_session.commit()

    assert recover_stale_jobs(db_session) == 0
