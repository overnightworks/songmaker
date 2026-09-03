"""Tests for the database layer — models, engine, queries."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError
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
    WhisperCue,
)
from songmaker_cli.db.engine import init_test_db as init_db
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
    UNSET,
    archive_generation,
    cleanup_album,
    cleanup_song,
    count_recent_failed_attempts,
    count_total_queued_jobs,
    count_user_active_jobs,
    count_user_jobs_in_window,
    create_generation,
    create_job,
    create_session,
    create_song,
    create_user,
    delete_album,
    delete_expired_sessions,
    delete_generation,
    delete_generation_files,
    delete_session,
    delete_version,
    enable_generation_sharing,
    enable_song_sharing,
    get_album,
    get_generation,
    get_job,
    get_session_with_user,
    get_song,
    get_user,
    get_user_by_username,
    keep_generation,
    list_active_sessions,
    list_albums,
    list_generations_expired_for_archive,
    list_generations_expired_for_delete,
    list_login_attempts,
    list_songs,
    list_users,
    measure_generation_audio_duration,
    move_song,
    pick_generation,
    prune_overflow_sessions,
    record_login_attempt,
    recover_stale_jobs,
    recover_stale_jobs_by_age_and_type,
    save_rating,
    save_scores,
    unarchive_generation,
    unkeep_generation,
    unpick_generation,
    update_job_heartbeat,
    update_job_status,
    update_song,
    update_user,
    user_count,
)


@pytest.fixture()
def db_session(tmp_path: Path) -> Session:
    factory = init_db(tmp_path / "test.db")
    session = factory()
    yield session
    session.close()


@pytest.fixture()
def seeded_session(db_session: Session) -> Session:
    album = Album(id="test", title="Test Album", artist="TestArtist")
    db_session.add(album)

    song = Song(
        id="s1", title="Song One", album_id="test", track_number=1, slug="song-one",
    )
    db_session.add(song)

    ver = Version(id="v1", song_id="s1", version_number=1, lyrics="verse one", prompt="rock")
    db_session.add(ver)

    gen1 = Generation(
        id="g1",
        song_id="s1",
        version_id="v1",
        generation_number=1,
        mp3_path="test/01_song_one_v1.mp3",
        seed=42,
        generation_params={"bpm": 120, "key_scale": "Am"},
    )
    gen2 = Generation(
        id="g2",
        song_id="s1",
        version_id="v1",
        generation_number=2,
        mp3_path="test/01_song_one_v2.mp3",
        seed=99,
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
    assert [a.id for a in list_albums(db_session, user_id=u1.id, q="album a")] == ["a1"]
    titled = list_albums(db_session, user_id=u1.id, sort="title")
    assert [a.id for a in titled] == ["a1", "a3"]


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


def test_list_songs_with_full_details(seeded_session: Session) -> None:
    songs = list_songs(seeded_session, light=False)
    assert len(songs) == 1
    assert songs[0].title == "Song One"


def test_get_song(seeded_session: Session) -> None:
    song = get_song(seeded_session, "s1")
    assert song is not None
    assert len(song.generations) == 2


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
    song = create_song(
        seeded_session, "Song Two", "test", slug="song-two", lyrics="hello", bpm=140,
    )
    seeded_session.commit()
    assert song.track_number == 2
    assert song.latest_version.lyrics == "hello"


def test_create_song_first_in_album_uses_initial_track_number(
    db_session: Session,
) -> None:
    from songmaker_cli.db.queries.songs import INITIAL_TRACK_NUMBER

    db_session.add(Album(id="empty", title="E", artist="X"))
    db_session.flush()
    song = create_song(db_session, "First Song", "empty", slug="first-song")
    db_session.commit()
    assert song.track_number == INITIAL_TRACK_NUMBER


def test_create_generation_first_for_song_uses_initial_number(
    seeded_session: Session,
) -> None:
    from songmaker_cli.db.queries import create_generation
    from songmaker_cli.db.queries.generations import INITIAL_GENERATION_NUMBER

    seeded_session.add(Album(id="a2", title="A2", artist="X"))
    seeded_session.add(Song(id="s2", title="S2", album_id="a2", track_number=1))
    seeded_session.flush()
    gen = create_generation(
        seeded_session,
        song_id="s2",
        version_id=None,
        mp3_path="x.mp3",
        model_mode="sft",
    )
    seeded_session.commit()
    assert gen.generation_number == INITIAL_GENERATION_NUMBER


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
    assert d["whisper_cues"] is None
    assert d["version_lyrics"] == "verse one"


def test_generation_version_lyrics_stay_on_the_producing_version(
    seeded_session: Session,
) -> None:
    update_song(seeded_session, "s1", lyrics="latest draft")
    seeded_session.commit()
    gen = get_generation(seeded_session, "g1")
    song = get_song(seeded_session, "s1")
    assert GenerationResponse.from_orm(gen).version_lyrics == "verse one"
    assert SongResponse.from_orm(song).lyrics == "latest draft"


def test_generation_missing_version_lyrics_is_null(seeded_session: Session) -> None:
    gen = create_generation(
        seeded_session,
        song_id="s1",
        version_id=None,
        mp3_path="test/no_version.mp3",
        model_mode="sft",
    )
    seeded_session.commit()
    loaded = get_generation(seeded_session, gen.id)
    assert GenerationResponse.from_orm(loaded).version_lyrics is None


def test_generation_empty_version_lyrics_is_null(seeded_session: Session) -> None:
    empty = Version(
        id="v-empty",
        song_id="s1",
        version_number=99,
        lyrics="",
        prompt="empty",
    )
    seeded_session.add(empty)
    seeded_session.flush()
    gen = create_generation(
        seeded_session,
        song_id="s1",
        version_id=empty.id,
        mp3_path="test/empty_lyrics.mp3",
        model_mode="sft",
    )
    seeded_session.commit()
    loaded = get_generation(seeded_session, gen.id)
    assert GenerationResponse.from_orm(loaded).version_lyrics is None


def test_song_to_dict(seeded_session: Session) -> None:
    song = get_song(seeded_session, "s1")
    d = SongResponse.from_orm(song).model_dump()
    assert d["title"] == "Song One"
    assert d["generation_count"] == 2
    assert d["best_rating"] == 82.5
    assert len(d["generations"]) == 2


def test_album_to_dict(seeded_session: Session) -> None:
    album = get_album(seeded_session, "test")
    d = AlbumResponse.from_orm(album, song_count=1).model_dump()
    assert d["song_count"] == 1
    assert d["created_at"] == album.created_at.isoformat()


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
    count, paths = cleanup_album(seeded_session, "test")
    seeded_session.commit()
    assert count == 1
    assert get_generation(seeded_session, "g1") is not None
    assert get_generation(seeded_session, "g2") is None


def test_cleanup_album_no_picks_deletes_all(seeded_session: Session) -> None:
    count, _paths = cleanup_album(seeded_session, "test")
    seeded_session.commit()
    assert count == 2


# ── Keep tests ──────────────────────────────────────────────────────


def test_keep_generation(seeded_session: Session) -> None:
    keep_generation(seeded_session, "g1")
    seeded_session.commit()
    assert get_generation(seeded_session, "g1").is_kept is True


def test_unkeep_generation(seeded_session: Session) -> None:
    keep_generation(seeded_session, "g1")
    seeded_session.commit()
    unkeep_generation(seeded_session, "g1")
    seeded_session.commit()
    assert get_generation(seeded_session, "g1").is_kept is False


def test_keep_generation_not_found(seeded_session: Session) -> None:
    with pytest.raises(ValueError, match="Generation not found"):
        keep_generation(seeded_session, "nonexistent")


def test_unkeep_generation_not_found(seeded_session: Session) -> None:
    with pytest.raises(ValueError, match="Generation not found"):
        unkeep_generation(seeded_session, "nonexistent")


def test_cleanup_album_skips_kept(seeded_session: Session) -> None:
    keep_generation(seeded_session, "g2")
    seeded_session.commit()
    count, paths = cleanup_album(seeded_session, "test")
    seeded_session.commit()
    assert count == 1
    assert get_generation(seeded_session, "g1") is None
    assert get_generation(seeded_session, "g2") is not None


def test_cleanup_album_skips_picked_and_kept(seeded_session: Session) -> None:
    pick_generation(seeded_session, "g1")
    keep_generation(seeded_session, "g2")
    seeded_session.commit()
    count, paths = cleanup_album(seeded_session, "test")
    seeded_session.commit()
    assert count == 0
    assert get_generation(seeded_session, "g1") is not None
    assert get_generation(seeded_session, "g2") is not None


def test_cleanup_song_deletes_unpicked(seeded_session: Session) -> None:
    pick_generation(seeded_session, "g1")
    seeded_session.commit()
    count, paths = cleanup_song(seeded_session, "s1")
    seeded_session.commit()
    assert count == 1
    assert get_generation(seeded_session, "g1") is not None
    assert get_generation(seeded_session, "g2") is None


def test_cleanup_song_skips_kept(seeded_session: Session) -> None:
    keep_generation(seeded_session, "g2")
    seeded_session.commit()
    count, paths = cleanup_song(seeded_session, "s1")
    seeded_session.commit()
    assert count == 1
    assert get_generation(seeded_session, "g1") is None
    assert get_generation(seeded_session, "g2") is not None


def test_sharing_generation_auto_sets_kept(seeded_session: Session) -> None:
    assert get_generation(seeded_session, "g1").is_kept is False
    enable_generation_sharing(seeded_session, "g1")
    seeded_session.commit()
    assert get_generation(seeded_session, "g1").is_kept is True


def test_sharing_song_auto_sets_kept_on_picked(seeded_session: Session) -> None:
    pick_generation(seeded_session, "g1")
    seeded_session.commit()
    assert get_generation(seeded_session, "g1").is_kept is False
    enable_song_sharing(seeded_session, "s1")
    seeded_session.commit()
    assert get_generation(seeded_session, "g1").is_kept is True


def test_delete_album(seeded_session: Session) -> None:
    delete_album(seeded_session, "test")
    seeded_session.commit()
    assert get_album(seeded_session, "test") is None
    assert get_song(seeded_session, "s1") is None
    assert get_generation(seeded_session, "g1") is None
    assert get_generation(seeded_session, "g2") is None


def test_delete_album_not_found(seeded_session: Session) -> None:
    with pytest.raises(ValueError, match="Album not found"):
        delete_album(seeded_session, "nonexistent")


def test_delete_album_returns_paths(seeded_session: Session) -> None:
    paths = delete_album(seeded_session, "test")
    seeded_session.commit()
    assert isinstance(paths, list)
    assert all(isinstance(p, str) for p in paths)


def test_move_song(seeded_session: Session) -> None:
    seeded_session.add(Album(id="other", title="Other Album", artist="A"))
    seeded_session.commit()

    song = move_song(seeded_session, "s1", "other", slug="song-one")
    seeded_session.commit()
    assert song.album_id == "other"
    assert get_song(seeded_session, "s1").album_id == "other"


def test_move_song_same_album(seeded_session: Session) -> None:
    song = move_song(seeded_session, "s1", "test", slug="song-one")
    assert song.album_id == "test"


def test_move_song_not_found(seeded_session: Session) -> None:
    with pytest.raises(ValueError, match="Song not found"):
        move_song(seeded_session, "nonexistent", "test", slug="song-one")


def test_move_song_target_not_found(seeded_session: Session) -> None:
    with pytest.raises(ValueError, match="Album not found"):
        move_song(seeded_session, "s1", "nonexistent", slug="song-one")


def test_move_song_updates_album(seeded_session: Session) -> None:
    seeded_session.add(Album(id="other", title="Other", artist="A"))
    seeded_session.commit()

    move_song(seeded_session, "s1", "other", slug="song-one")
    seeded_session.commit()

    gen = get_generation(seeded_session, "g1")
    assert gen.song.album_id == "other"


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


@pytest.mark.parametrize("terminal", ["cancelled", "completed", "failed", "partial"])
def test_update_job_status_does_not_overwrite_terminal(
    seeded_session: Session,
    terminal: str,
) -> None:
    job = create_job(seeded_session, "generate")
    seeded_session.commit()
    applied = update_job_status(seeded_session, job.id, terminal, progress=0.4)
    seeded_session.commit()
    assert applied is True

    applied = update_job_status(seeded_session, job.id, "running", progress=0.9)
    seeded_session.commit()
    assert applied is False
    fetched = get_job(seeded_session, job.id)
    assert fetched.status == terminal
    assert fetched.progress == 0.4


def test_update_job_status_cancelled_sets_completed_at(seeded_session: Session) -> None:
    job = create_job(seeded_session, "generate")
    seeded_session.commit()
    update_job_status(seeded_session, job.id, "cancelled")
    seeded_session.commit()
    fetched = get_job(seeded_session, job.id)
    assert fetched.status == "cancelled"
    assert fetched.completed_at is not None

    completed_at = fetched.completed_at
    update_job_status(seeded_session, job.id, "completed", progress=1.0)
    update_job_status(seeded_session, job.id, "failed", error="late")
    seeded_session.commit()
    fetched = get_job(seeded_session, job.id)
    assert fetched.status == "cancelled"
    assert fetched.completed_at == completed_at
    assert fetched.error is None


def test_update_job_heartbeat_skips_terminal(seeded_session: Session) -> None:
    from datetime import datetime, timedelta, timezone

    job = create_job(seeded_session, "generate")
    seeded_session.commit()
    stale = datetime.now(timezone.utc) - timedelta(hours=1)
    job.heartbeat_at = stale
    seeded_session.flush()
    update_job_status(seeded_session, job.id, "cancelled")
    seeded_session.commit()

    before = get_job(seeded_session, job.id).heartbeat_at
    update_job_heartbeat(seeded_session, job.id)
    seeded_session.commit()
    fetched = get_job(seeded_session, job.id)
    assert fetched.status == "cancelled"
    assert fetched.heartbeat_at == before


def test_update_job_heartbeat_updates_running(seeded_session: Session) -> None:
    from datetime import datetime, timedelta, timezone

    job = create_job(seeded_session, "generate")
    seeded_session.commit()
    update_job_status(seeded_session, job.id, "running")
    stale = datetime.now(timezone.utc) - timedelta(hours=1)
    job.heartbeat_at = stale
    seeded_session.flush()

    update_job_heartbeat(seeded_session, job.id)
    seeded_session.commit()
    fetched = get_job(seeded_session, job.id)
    heartbeat = fetched.heartbeat_at
    if heartbeat.tzinfo is None:
        heartbeat = heartbeat.replace(tzinfo=timezone.utc)
    assert heartbeat > stale


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
        seeded_session,
        "s1",
        "v1",
        "test/new_gen.mp3",
        model_mode="sft",
        seed=123,
        generation_params={"bpm": 140},
    )
    seeded_session.commit()
    assert gen.generation_number == 3
    assert gen.seed == 123
    assert gen.mp3_path == "test/new_gen.mp3"


def test_create_generation_with_model_mode(seeded_session: Session) -> None:
    gen = create_generation(
        seeded_session,
        "s1",
        "v1",
        "test/gen.mp3",
        model_mode="turbo",
        seed=1,
    )
    seeded_session.commit()
    assert gen.model_mode == "turbo"


def test_create_generation_with_wav_path(seeded_session: Session) -> None:
    gen = create_generation(
        seeded_session,
        "s1",
        "v1",
        "test/gen.mp3",
        model_mode="sft",
        seed=1,
        wav_path="test/gen.wav",
    )
    seeded_session.commit()
    assert gen.wav_path == "test/gen.wav"


def test_create_generation_measures_duration_even_when_requested_zero(
    seeded_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The take's own length is measured, not copied from the "auto" (0)
    request parameter it was generated with (#258)."""
    import songmaker_cli.queue_streams as qs

    probed: list[Path] = []

    def _read(path: Path) -> float:
        probed.append(path)
        return 188.0

    monkeypatch.setattr(qs, "read_audio_duration", _read)

    gen = create_generation(
        seeded_session,
        "s1",
        "v1",
        "test/gen.mp3",
        model_mode="sft",
        seed=1,
        generation_params={"audio_duration": 0},
        audio_dir=tmp_path,
    )
    seeded_session.commit()

    assert gen.audio_duration_sec == 188.0
    assert gen.generation_params["audio_duration"] == 0
    assert probed == [tmp_path / "test/gen.mp3"]


def test_create_generation_without_audio_dir_leaves_duration_unmeasured(
    seeded_session: Session,
) -> None:
    gen = create_generation(
        seeded_session,
        "s1",
        "v1",
        "test/gen.mp3",
        model_mode="sft",
        seed=1,
    )
    seeded_session.commit()
    assert gen.audio_duration_sec is None


def test_measure_generation_audio_duration_backfills_a_generation(
    seeded_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import songmaker_cli.queue_streams as qs

    probed: list[Path] = []

    def _read(path: Path) -> float:
        probed.append(path)
        return 42.5

    monkeypatch.setattr(qs, "read_audio_duration", _read)

    gen = get_generation(seeded_session, "g1")
    assert gen.audio_duration_sec is None

    duration = measure_generation_audio_duration(seeded_session, tmp_path, gen)

    assert duration == 42.5
    assert gen.audio_duration_sec == 42.5
    assert probed == [tmp_path / gen.mp3_path]


def test_measure_generation_audio_duration_does_not_reprobe_a_measured_generation(
    seeded_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import songmaker_cli.queue_streams as qs

    gen = get_generation(seeded_session, "g1")
    gen.audio_duration_sec = 99.0
    seeded_session.flush()

    def _fail(_path: Path) -> float:
        raise AssertionError("should not re-probe an already-measured generation")

    monkeypatch.setattr(qs, "read_audio_duration", _fail)

    duration = measure_generation_audio_duration(seeded_session, tmp_path, gen)

    assert duration == 99.0


def test_measure_generation_audio_duration_stores_none_when_file_unreadable(
    seeded_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """read_audio_duration returning None (unreadable file) must resolve to
    "unknown" on the generation, not raise or leave a stale value."""
    import songmaker_cli.queue_streams as qs

    monkeypatch.setattr(qs, "read_audio_duration", lambda _path: None)

    gen = get_generation(seeded_session, "g1")
    duration = measure_generation_audio_duration(seeded_session, tmp_path, gen)

    assert duration is None
    assert gen.audio_duration_sec is None


def test_measure_generation_audio_duration_retries_after_a_failed_probe(
    seeded_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Not idempotent across a failure: a None result isn't cached forever,
    so a later call (e.g. a second GET) gets another chance to measure it."""
    import songmaker_cli.queue_streams as qs

    gen = get_generation(seeded_session, "g1")
    monkeypatch.setattr(qs, "read_audio_duration", lambda _path: None)
    assert measure_generation_audio_duration(seeded_session, tmp_path, gen) is None

    monkeypatch.setattr(qs, "read_audio_duration", lambda _path: 77.0)
    assert measure_generation_audio_duration(seeded_session, tmp_path, gen) == 77.0


def test_generation_response_exposes_audio_duration_sec(seeded_session: Session) -> None:
    gen = get_generation(seeded_session, "g1")
    assert GenerationResponse.from_orm(gen).audio_duration_sec is None

    gen.audio_duration_sec = 12.5
    seeded_session.flush()
    assert GenerationResponse.from_orm(gen).audio_duration_sec == 12.5


def test_generations_model_mode_not_null(tmp_path: Path) -> None:
    from sqlalchemy import inspect

    from songmaker_cli.db.engine import init_test_db

    factory = init_test_db(tmp_path / "test.db")
    with factory() as session:
        insp = inspect(session.bind)
        cols = {c["name"]: c for c in insp.get_columns("generations")}
        assert cols["model_mode"]["nullable"] is False


def test_available_models_seed_idempotent(tmp_path: Path) -> None:
    from songmaker_cli.constants import MODEL_AVAILABLE_MODES
    from songmaker_cli.db.engine import init_test_db
    from songmaker_cli.db.models import AvailableModel

    db_path = tmp_path / "test.db"
    factory = init_test_db(db_path)
    with factory() as session:
        ids = {m.id for m in session.query(AvailableModel).all()}
        assert ids == MODEL_AVAILABLE_MODES
        count_before = session.query(AvailableModel).count()

    factory = init_test_db(db_path)
    with factory() as session:
        ids_after = {m.id for m in session.query(AvailableModel).all()}
        count_after = session.query(AvailableModel).count()
    assert ids_after == MODEL_AVAILABLE_MODES
    assert count_after == count_before


def test_save_scores_create(seeded_session: Session) -> None:
    save_scores(
        seeded_session, "g2", {"dynamics": 77.0, "enjoyment": 8.5},
        refreshed_keys={"dynamics", "enjoyment"},
    )
    seeded_session.commit()
    gen = get_generation(seeded_session, "g2")
    scores = {s.scorer: s.value for s in gen.scores}
    assert scores["batch"]["dynamics"] == 77.0


def test_save_scores_upsert(seeded_session: Session) -> None:
    save_scores(seeded_session, "g1", {"dynamics": 99.0}, refreshed_keys={"dynamics"})
    seeded_session.commit()
    gen = get_generation(seeded_session, "g1")
    batch_scores = [s for s in gen.scores if s.scorer == "batch"]
    assert len(batch_scores) == 1
    assert batch_scores[0].value["dynamics"] == 99.0


def test_save_scores_upsert_persists(tmp_path: Path) -> None:
    """Verify score upsert actually persists to DB (not just in-memory)."""
    factory = init_db(tmp_path / "test.db")
    with factory() as session:
        session.add(Album(id="t2", title="T2", artist="A"))
        session.add(Song(id="s2", title="S2", album_id="t2", track_number=1))
        session.add(Version(id="v2", song_id="s2", version_number=1, lyrics="x", prompt="y"))
        session.add(
            Generation(
                id="gx",
                song_id="s2",
                version_id="v2",
                generation_number=1,
                mp3_path="t2/test.mp3",
            )
        )
        session.add(Score(id="scx", generation_id="gx", scorer="batch", value={"old": 1.0}))
        session.commit()

    with factory() as s2:
        save_scores(s2, "gx", {"new": 99.0}, refreshed_keys={"old", "new"})
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


def test_generation_null_whisper_cues_serializes_as_null(
    seeded_session: Session,
) -> None:
    gen = get_generation(seeded_session, "g2")
    assert gen.whisper_cues is None
    d = GenerationResponse.from_orm(gen).model_dump()
    assert d["whisper_cues"] is None


def test_generation_whisper_cues_roundtrip(seeded_session: Session) -> None:
    gen = get_generation(seeded_session, "g1")
    gen.whisper_cues = [
        {"start": 0.0, "end": 1.25, "text": "hello world"},
        {"start": 1.25, "end": 2.5, "text": "goodbye moon"},
    ]
    seeded_session.commit()
    seeded_session.refresh(gen)
    assert gen.whisper_cues == [
        {"start": 0.0, "end": 1.25, "text": "hello world"},
        {"start": 1.25, "end": 2.5, "text": "goodbye moon"},
    ]
    d = GenerationResponse.from_orm(gen).model_dump()
    assert d["whisper_cues"] == [
        {"start": 0.0, "end": 1.25, "text": "hello world", "words": None},
        {"start": 1.25, "end": 2.5, "text": "goodbye moon", "words": None},
    ]
    assert all(isinstance(cue, dict) for cue in d["whisper_cues"])
    typed = GenerationResponse.from_orm(gen).whisper_cues
    assert typed == [
        WhisperCue(start=0.0, end=1.25, text="hello world"),
        WhisperCue(start=1.25, end=2.5, text="goodbye moon"),
    ]


def test_generation_empty_whisper_cues_serializes_as_empty_list(
    seeded_session: Session,
) -> None:
    gen = get_generation(seeded_session, "g1")
    gen.whisper_cues = []
    seeded_session.commit()
    seeded_session.refresh(gen)
    d = GenerationResponse.from_orm(gen).model_dump()
    assert d["whisper_cues"] == []


def test_whisper_cue_rejects_negative_start() -> None:
    with pytest.raises(PydanticValidationError, match="must not be negative"):
        WhisperCue(start=-0.1, end=1.0, text="hello")


def test_whisper_cue_rejects_non_finite_end() -> None:
    with pytest.raises(PydanticValidationError, match="finite number of seconds"):
        WhisperCue(start=0.0, end=float("inf"), text="hello")


def test_whisper_cue_rejects_backward_range() -> None:
    with pytest.raises(PydanticValidationError, match="end must not be before start"):
        WhisperCue(start=2.0, end=1.0, text="hello")


def test_generation_whisper_cues_validator_rejects_invalid(
    seeded_session: Session,
) -> None:
    gen = get_generation(seeded_session, "g1")
    with pytest.raises(PydanticValidationError, match="end must not be before start"):
        gen.whisper_cues = [{"start": 2.0, "end": 1.0, "text": "hello"}]


def test_generation_whisper_cues_validator_rejects_non_list(
    seeded_session: Session,
) -> None:
    gen = get_generation(seeded_session, "g1")
    with pytest.raises(TypeError, match="must be a list or None"):
        gen.whisper_cues = {"start": 0.0, "end": 1.0, "text": "hello"}


# ── Generation params on Version ────────────────────────────────────


def test_create_song_with_generation_params(db_session: Session) -> None:
    db_session.add(Album(id="a1", title="A", artist="X"))
    db_session.flush()
    params = {"inference_steps": 50, "guidance_scale": 5.5}
    song = create_song(db_session, "S", "a1", slug="s", generation_params=params)
    db_session.commit()
    ver = song.latest_version
    assert ver.generation_params == params


def test_create_song_without_generation_params(db_session: Session) -> None:
    db_session.add(Album(id="a1", title="A", artist="X"))
    db_session.flush()
    song = create_song(db_session, "S", "a1", slug="s")
    db_session.commit()
    assert song.latest_version.generation_params is None


def test_version_validator_rejects_unknown_key(db_session: Session) -> None:
    """The SQLAlchemy @validates on Version.generation_params is the
    defense-in-depth layer that catches the 2026-04-08 surface — typos
    in stored params should fail loudly, not silently round-trip."""
    from pydantic import ValidationError as PydanticValidationError

    db_session.add(Album(id="a1", title="A", artist="X"))
    db_session.flush()
    with pytest.raises(PydanticValidationError, match="not permitted|extra"):
        create_song(
            db_session,
            "S",
            "a1",
            slug="s",
            generation_params={"infrence_steps": 50},
        )


def test_generation_validator_rejects_unknown_key(seeded_session: Session) -> None:
    from pydantic import ValidationError as PydanticValidationError

    from songmaker_cli.db.models import Generation

    with pytest.raises(PydanticValidationError, match="not permitted|extra"):
        seeded_session.add(
            Generation(
                id="gx",
                song_id="s1",
                version_id="v1",
                generation_number=99,
                mp3_path="user1/gx.mp3",
                model_mode="sft",
                generation_params={"acestep_model": "sft", "bogus": True},
            )
        )


def test_preset_validator_rejects_unknown_key(db_session: Session) -> None:
    from pydantic import ValidationError as PydanticValidationError

    from songmaker_cli.db.models import GenerationPreset

    with pytest.raises(PydanticValidationError, match="not permitted|extra"):
        db_session.add(
            GenerationPreset(
                name="p",
                model_mode="sft",
                params={"shift": 2.0, "junk": 1},
            )
        )


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
    update_song(seeded_session, "s1", lyrics="changed", generation_params=UNSET)
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


# ── queries.py gap coverage ─────────────────────────────────────────


def test_list_songs_with_album_filter(seeded_session: Session) -> None:
    result = list_songs(seeded_session, album_id="test", light=False)
    assert len(result) >= 1
    assert all(s.album_id == "test" for s in result)


def test_list_songs_with_unknown_album_filter(seeded_session: Session) -> None:
    result = list_songs(seeded_session, album_id="nonexistent", light=False)
    assert result == []


def test_create_song_album_not_found(db_session: Session) -> None:
    with pytest.raises(ValueError, match="Album not found"):
        create_song(db_session, "Test", "nonexistent", slug="test")


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


def test_delete_generation_returns_paths(seeded_session: Session) -> None:
    paths = delete_generation(seeded_session, "g1")
    seeded_session.commit()
    assert isinstance(paths, list)
    assert "test/01_song_one_v1.mp3" in paths


def test_delete_generation_files_removes_all_suffixes(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    gen_dir = audio_dir / "user1"
    gen_dir.mkdir(parents=True)
    mp3 = gen_dir / "gen1.mp3"
    wav = gen_dir / "gen1.wav"
    md = gen_dir / "gen1.md"
    mp3.write_bytes(b"fake")
    wav.write_bytes(b"fake")
    md.write_text("snapshot")

    delete_generation_files(audio_dir, "user1/gen1.mp3")

    assert not mp3.exists()
    assert not wav.exists()
    assert not md.exists()


def test_delete_generation_files_path_traversal_blocked(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    sentinel = tmp_path / "etc" / "passwd"
    sentinel.parent.mkdir()
    sentinel.write_text("secret")

    delete_generation_files(audio_dir, "../../etc/passwd")

    assert sentinel.exists()


# ── User queries ────────────────────────────────────────────────────


def test_create_user(db_session: Session) -> None:
    from songmaker_cli.db.models import ResourceEventCursor

    user = create_user(db_session, "alice", "hash123", role="admin")
    db_session.commit()
    assert user.username == "alice"
    assert user.role == "admin"
    assert user.is_active is True
    assert user.created_at is not None
    assert db_session.get(ResourceEventCursor, user.id).high_water_mark == 0


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


def test_prune_overflow_sessions_deletes_oldest_above_cap(db_session: Session) -> None:
    from datetime import datetime, timedelta, timezone

    user = _make_user(db_session)
    other = _make_user(db_session, "other")
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=30)
    created = []
    for index in range(11):
        sess = create_session(db_session, user.id, expires)
        sess.created_at = now - timedelta(seconds=11 - index)
        created.append(sess)
    other_session = create_session(db_session, other.id, expires)
    db_session.flush()

    pruned = prune_overflow_sessions(db_session, user.id, 10)
    db_session.commit()

    assert pruned == [created[0].id]
    assert get_session_with_user(db_session, created[0].id) is None
    assert get_session_with_user(db_session, created[1].id) is not None
    assert get_session_with_user(db_session, created[-1].id) is not None
    assert get_session_with_user(db_session, other_session.id) is not None


def test_prune_overflow_sessions_under_cap_returns_empty(db_session: Session) -> None:
    from datetime import datetime, timedelta, timezone

    user = _make_user(db_session)
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=30)
    ids = [create_session(db_session, user.id, expires).id for _ in range(3)]
    db_session.flush()

    pruned = prune_overflow_sessions(db_session, user.id, 10)
    db_session.commit()

    assert pruned == []
    for session_id in ids:
        assert get_session_with_user(db_session, session_id) is not None


def test_prune_overflow_sessions_ignores_expired(db_session: Session) -> None:
    from datetime import datetime, timedelta, timezone

    user = _make_user(db_session)
    now = datetime.now(timezone.utc)
    expired = create_session(db_session, user.id, now - timedelta(days=1))
    active_ids = [
        create_session(db_session, user.id, now + timedelta(days=30)).id
        for _ in range(10)
    ]
    db_session.flush()

    pruned = prune_overflow_sessions(db_session, user.id, 10)
    db_session.commit()

    assert pruned == []
    assert get_session_with_user(db_session, expired.id) is not None
    for session_id in active_ids:
        assert get_session_with_user(db_session, session_id) is not None


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
        ip_address="10.0.0.1",
        username="alice",
        success=False,
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
        db_session,
        user.id,
        expires,
        ip_address="127.0.0.1",
        user_agent="Mozilla/5.0",
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
        type="generate",
        user_id=user.id,
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
    create_job(db_session, "score", user_id=user.id)
    db_session.commit()

    update_job_status(db_session, j2.id, "completed", progress=1.0)
    db_session.commit()

    assert count_user_active_jobs(db_session, user.id) == 2
    assert count_user_active_jobs(db_session, user.id, "generate") == 1
    assert count_user_active_jobs(db_session, user.id, "score") == 1
    assert count_user_active_jobs(db_session, user.id, "chat") == 0


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


# ── stale job reaper ──────────────────────────────────────────────


def test_reaper_marks_a_stale_running_job_as_heartbeat_lost(db_session: Session) -> None:
    from datetime import datetime, timedelta, timezone

    j_old = create_job(db_session, "generate")
    j_recent = create_job(db_session, "score")
    j_completed = create_job(db_session, "generate")
    db_session.commit()

    update_job_status(db_session, j_old.id, "running", progress=0.5)
    update_job_status(db_session, j_recent.id, "running", progress=0.3)
    update_job_status(db_session, j_completed.id, "completed", progress=1.0)
    db_session.commit()

    old_time = datetime.now(timezone.utc) - timedelta(seconds=3600)
    j_old.started_at = old_time
    j_old.heartbeat_at = old_time
    db_session.commit()

    count = recover_stale_jobs_by_age_and_type(db_session)
    db_session.commit()

    assert count == 1

    old_after = get_job(db_session, j_old.id)
    assert old_after.status == "failed"
    assert old_after.error_type == "heartbeat_lost"
    assert old_after.completed_at is not None

    recent_after = get_job(db_session, j_recent.id)
    assert recent_after.status == "running"

    completed_after = get_job(db_session, j_completed.id)
    assert completed_after.status == "completed"


def test_reaper_leaves_a_recent_job_alone(db_session: Session) -> None:
    j1 = create_job(db_session, "generate")
    db_session.commit()

    update_job_status(db_session, j1.id, "running")
    db_session.commit()

    assert recover_stale_jobs_by_age_and_type(db_session) == 0


def test_reaper_marks_a_stale_queued_job_as_unavailable(db_session: Session) -> None:
    from datetime import datetime, timedelta, timezone

    j_queued = create_job(db_session, "generate")
    db_session.commit()

    old = datetime.now(timezone.utc) - timedelta(seconds=3600)
    j_queued.started_at = old
    j_queued.heartbeat_at = old
    db_session.commit()

    count = recover_stale_jobs_by_age_and_type(db_session)
    db_session.commit()

    assert count == 1
    after = get_job(db_session, j_queued.id)
    assert after.status == "failed"
    assert after.error_type == "no_worker_available"
    assert "No worker available" in after.error


@pytest.mark.parametrize("job_type", ("chat", "lora_training", "score", "generate"))
def test_reaper_uses_each_types_queued_and_heartbeat_threshold(
    db_session: Session,
    job_type: str,
) -> None:
    from datetime import datetime, timedelta, timezone

    from songmaker_cli.constants import STALE_JOB_THRESHOLDS, JobStatus, JobType

    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    thresholds = STALE_JOB_THRESHOLDS[JobType(job_type)]
    queued = create_job(db_session, job_type)
    running = create_job(db_session, job_type)
    healthy = create_job(db_session, job_type)
    update_job_status(db_session, running.id, JobStatus.RUNNING)
    update_job_status(db_session, healthy.id, JobStatus.RUNNING)
    queued.started_at = now - timedelta(seconds=thresholds.queued_seconds + 1)
    running.heartbeat_at = now - timedelta(seconds=thresholds.heartbeat_seconds + 1)
    healthy.heartbeat_at = now
    db_session.commit()

    assert recover_stale_jobs_by_age_and_type(db_session, now=now) == 2
    assert get_job(db_session, queued.id).error_type == "no_worker_available"
    assert get_job(db_session, running.id).error_type == "heartbeat_lost"
    assert get_job(db_session, healthy.id).status == JobStatus.RUNNING


def test_recover_stale_jobs_by_age_and_type_distinguishes_queued_vs_running(
    db_session: Session,
) -> None:
    from datetime import datetime, timedelta, timezone

    from songmaker_cli.db.queries import recover_stale_jobs_by_age_and_type

    j_queued = create_job(db_session, "generate")
    j_running = create_job(db_session, "generate")
    j_other = create_job(db_session, "score")
    db_session.commit()

    update_job_status(db_session, j_running.id, "running", progress=0.5)
    db_session.commit()

    old = datetime.now(timezone.utc) - timedelta(seconds=3600)
    for job in (j_queued, j_running, j_other):
        job.started_at = old
        job.heartbeat_at = old
    db_session.commit()

    count = recover_stale_jobs_by_age_and_type(db_session, "generate")
    db_session.commit()

    assert count == 2
    assert get_job(db_session, j_queued.id).error_type == "no_worker_available"
    assert get_job(db_session, j_running.id).error_type == "heartbeat_lost"
    assert get_job(db_session, j_other.id).status == "queued"


def test_reaper_uses_queued_age_instead_of_queued_heartbeat(
    db_session: Session,
) -> None:
    from datetime import datetime, timedelta, timezone

    from songmaker_cli.db.queries import recover_stale_jobs_by_age_and_type

    queued = create_job(db_session, "generate")
    running = create_job(db_session, "generate")
    db_session.commit()
    update_job_status(db_session, running.id, "running", progress=0.5)
    db_session.commit()

    old = datetime.now(timezone.utc) - timedelta(days=1)
    queued.started_at = old
    queued.heartbeat_at = datetime.now(timezone.utc)
    running.started_at = old
    running.heartbeat_at = old
    db_session.commit()

    recovered = recover_stale_jobs_by_age_and_type(db_session, "generate")
    db_session.commit()

    assert recovered == 2
    assert get_job(db_session, queued.id).error_type == "no_worker_available"
    assert get_job(db_session, running.id).error_type == "heartbeat_lost"


def test_chat_recovery_reads_its_constant_table_not_settings(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import datetime, timedelta, timezone

    import songmaker_cli.settings as settings
    from songmaker_cli.constants import JobStatus, JobType
    from songmaker_cli.db.queries import recover_stale_jobs_by_age_and_type

    job = create_job(db_session, JobType.CHAT)
    db_session.commit()
    update_job_status(db_session, job.id, JobStatus.RUNNING, progress=0.5)
    db_session.commit()

    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    job.started_at = now
    job.heartbeat_at = now - timedelta(seconds=181)
    db_session.commit()

    def _unexpected_settings_read():
        raise AssertionError("fully injected chat thresholds must not read settings")

    monkeypatch.setattr(settings, "get_settings", _unexpected_settings_read)

    recovered = recover_stale_jobs_by_age_and_type(db_session, JobType.CHAT, now=now)
    db_session.commit()

    assert recovered == 1
    assert get_job(db_session, job.id).error_type == "heartbeat_lost"


def test_reaper_distinguishes_queued_vs_running(
    db_session: Session,
) -> None:
    from datetime import datetime, timedelta, timezone

    j_queued = create_job(db_session, "generate")
    j_running = create_job(db_session, "generate")
    db_session.commit()

    update_job_status(db_session, j_running.id, "running", progress=0.5)
    db_session.commit()

    old = datetime.now(timezone.utc) - timedelta(seconds=3600)
    for job in (j_queued, j_running):
        job.started_at = old
        job.heartbeat_at = old
    db_session.commit()

    count = recover_stale_jobs_by_age_and_type(db_session)
    db_session.commit()

    assert count == 2
    queued_after = get_job(db_session, j_queued.id)
    running_after = get_job(db_session, j_running.id)
    assert queued_after.error_type == "no_worker_available"
    assert running_after.error_type == "heartbeat_lost"
    assert "No worker available" in queued_after.error
    assert "Heartbeat lost" in running_after.error


# ── user-filtered stale job reaper ─────────────────────────────────


def test_user_filtered_reaper(db_session: Session) -> None:
    from datetime import datetime, timedelta, timezone

    user = create_user(db_session, "testuser", "hash", role="user")
    j_stale = create_job(db_session, "generate", user_id=user.id)
    j_recent = create_job(db_session, "generate", user_id=user.id)
    db_session.commit()

    update_job_status(db_session, j_stale.id, "running")
    update_job_status(db_session, j_recent.id, "running")
    db_session.commit()

    stale = datetime.now(timezone.utc) - timedelta(seconds=3600)
    j_stale.started_at = stale
    j_stale.heartbeat_at = stale
    db_session.commit()

    count = recover_stale_jobs_by_age_and_type(db_session, user_id=user.id)
    db_session.commit()

    assert count == 1
    assert get_job(db_session, j_stale.id).status == "failed"
    assert get_job(db_session, j_recent.id).status == "running"


def test_user_filtered_reaper_only_owns_its_jobs(db_session: Session) -> None:
    from datetime import datetime, timedelta, timezone

    user_a = create_user(db_session, "user_a", "hash", role="user")
    user_b = create_user(db_session, "user_b", "hash", role="user")
    j_a = create_job(db_session, "generate", user_id=user_a.id)
    j_b = create_job(db_session, "generate", user_id=user_b.id)
    db_session.commit()

    update_job_status(db_session, j_a.id, "running")
    update_job_status(db_session, j_b.id, "running")
    db_session.commit()

    stale = datetime.now(timezone.utc) - timedelta(seconds=3600)
    j_a.started_at = stale
    j_a.heartbeat_at = stale
    j_b.started_at = stale
    j_b.heartbeat_at = stale
    db_session.commit()

    count = recover_stale_jobs_by_age_and_type(db_session, user_id=user_a.id)
    db_session.commit()

    assert count == 1
    assert get_job(db_session, j_a.id).status == "failed"
    assert get_job(db_session, j_b.id).status == "running"


def test_user_filtered_reaper_catches_queued_jobs(db_session: Session) -> None:
    from datetime import datetime, timedelta, timezone

    user = create_user(db_session, "testuser", "hash", role="user")
    j_queued = create_job(db_session, "generate", user_id=user.id)
    db_session.commit()

    j_queued.started_at = datetime.now(timezone.utc) - timedelta(seconds=3600)
    db_session.commit()

    count = recover_stale_jobs_by_age_and_type(db_session, user_id=user.id)
    db_session.commit()

    assert count == 1
    assert get_job(db_session, j_queued.id).status == "failed"


def test_user_filtered_reaper_leaves_fresh_jobs_alone(db_session: Session) -> None:
    user = create_user(db_session, "testuser", "hash", role="user")
    j = create_job(db_session, "generate", user_id=user.id)
    db_session.commit()

    update_job_status(db_session, j.id, "running")
    db_session.commit()

    assert recover_stale_jobs_by_age_and_type(db_session, user_id=user.id) == 0


# ── queue_position ────────────────────────────────────────────────


def test_queue_position_queued_jobs(db_session: Session) -> None:
    from songmaker_cli.db.queries import get_queue_position

    j1 = create_job(db_session, "generate")
    j2 = create_job(db_session, "generate")
    j3 = create_job(db_session, "generate")
    db_session.commit()

    assert get_queue_position(db_session, j1) == 1
    assert get_queue_position(db_session, j2) == 2
    assert get_queue_position(db_session, j3) == 3


def test_queue_position_not_queued(db_session: Session) -> None:
    from songmaker_cli.db.queries import get_queue_position, update_job_status

    j1 = create_job(db_session, "generate")
    db_session.commit()

    update_job_status(db_session, j1.id, "running", progress=0.5)
    db_session.commit()

    assert get_queue_position(db_session, j1) is None


def test_queue_position_mixed_statuses(db_session: Session) -> None:
    from songmaker_cli.db.queries import get_queue_position, update_job_status

    j1 = create_job(db_session, "generate")
    j2 = create_job(db_session, "generate")
    j3 = create_job(db_session, "generate")
    db_session.commit()

    update_job_status(db_session, j1.id, "running")
    db_session.commit()

    assert get_queue_position(db_session, j1) is None
    assert get_queue_position(db_session, j2) == 1
    assert get_queue_position(db_session, j3) == 2


def test_queue_position_isolated_by_type(db_session: Session) -> None:
    from songmaker_cli.db.queries import get_queue_position

    score_first = create_job(db_session, "score")
    gen_first = create_job(db_session, "generate")
    score_second = create_job(db_session, "score")
    gen_second = create_job(db_session, "generate")
    db_session.commit()

    assert get_queue_position(db_session, gen_first) == 1
    assert get_queue_position(db_session, gen_second) == 2
    assert get_queue_position(db_session, score_first) == 1
    assert get_queue_position(db_session, score_second) == 2


# ── rate_limit_settings ───────────────────────────────────────────


def test_upsert_and_get_rate_limit_global(db_session: Session) -> None:
    from songmaker_cli.db.queries import (
        get_rate_limit_setting,
        upsert_rate_limit_setting,
    )

    setting = upsert_rate_limit_setting(db_session, "generation_rate_limit", 50)
    db_session.commit()
    assert setting.value == 50
    assert setting.user_id is None

    fetched = get_rate_limit_setting(db_session, "generation_rate_limit")
    assert fetched is not None
    assert fetched.value == 50


def test_upsert_rate_limit_updates_existing(db_session: Session) -> None:
    from songmaker_cli.db.queries import (
        get_rate_limit_setting,
        upsert_rate_limit_setting,
    )

    upsert_rate_limit_setting(db_session, "generation_rate_limit", 50)
    db_session.commit()
    upsert_rate_limit_setting(db_session, "generation_rate_limit", 100)
    db_session.commit()

    fetched = get_rate_limit_setting(db_session, "generation_rate_limit")
    assert fetched.value == 100


def test_upsert_rate_limit_per_user(db_session: Session) -> None:
    from songmaker_cli.db.queries import (
        get_rate_limit_setting,
        upsert_rate_limit_setting,
    )

    user = create_user(db_session, "testuser", "hash", role="user")
    db_session.commit()

    upsert_rate_limit_setting(db_session, "generation_rate_limit", 75, user_id=user.id)
    db_session.commit()

    per_user = get_rate_limit_setting(db_session, "generation_rate_limit", user.id)
    assert per_user is not None
    assert per_user.value == 75

    global_val = get_rate_limit_setting(db_session, "generation_rate_limit")
    assert global_val is None


def test_resolve_rate_limit_env_fallback(db_session: Session) -> None:
    from songmaker_cli.db.queries import resolve_rate_limit

    user = create_user(db_session, "testuser", "hash", role="user")
    db_session.commit()

    assert resolve_rate_limit(db_session, user.id, "generation_rate_limit", 20) == 20


def test_resolve_rate_limit_global_override(db_session: Session) -> None:
    from songmaker_cli.db.queries import resolve_rate_limit, upsert_rate_limit_setting

    user = create_user(db_session, "testuser", "hash", role="user")
    upsert_rate_limit_setting(db_session, "generation_rate_limit", 50)
    db_session.commit()

    assert resolve_rate_limit(db_session, user.id, "generation_rate_limit", 20) == 50


def test_resolve_rate_limit_user_override(db_session: Session) -> None:
    from songmaker_cli.db.queries import resolve_rate_limit, upsert_rate_limit_setting

    user = create_user(db_session, "testuser", "hash", role="user")
    upsert_rate_limit_setting(db_session, "generation_rate_limit", 50)
    upsert_rate_limit_setting(db_session, "generation_rate_limit", 100, user_id=user.id)
    db_session.commit()

    assert resolve_rate_limit(db_session, user.id, "generation_rate_limit", 20) == 100


def test_get_all_global_rate_limits(db_session: Session) -> None:
    from songmaker_cli.db.queries import get_all_global_rate_limits, upsert_rate_limit_setting

    upsert_rate_limit_setting(db_session, "generation_rate_limit", 50)
    upsert_rate_limit_setting(db_session, "scoring_rate_limit", 30)
    db_session.commit()

    results = get_all_global_rate_limits(db_session)
    assert len(results) == 2
    keys = {r.setting_key for r in results}
    assert keys == {"generation_rate_limit", "scoring_rate_limit"}


def test_get_user_rate_limits(db_session: Session) -> None:
    from songmaker_cli.db.queries import (
        get_user_rate_limits,
        upsert_rate_limit_setting,
    )

    user = create_user(db_session, "testuser", "hash", role="user")
    upsert_rate_limit_setting(db_session, "generation_rate_limit", 50)
    upsert_rate_limit_setting(db_session, "generation_rate_limit", 100, user_id=user.id)
    db_session.commit()

    results = get_user_rate_limits(db_session, user.id)
    assert len(results) == 1
    assert results[0].value == 100


def test_delete_all_user_rate_limits(db_session: Session) -> None:
    from songmaker_cli.db.queries import (
        delete_all_user_rate_limits,
        get_user_rate_limits,
        upsert_rate_limit_setting,
    )

    user = create_user(db_session, "testuser", "hash", role="user")
    upsert_rate_limit_setting(db_session, "generation_rate_limit", 100, user_id=user.id)
    upsert_rate_limit_setting(db_session, "scoring_rate_limit", 50, user_id=user.id)
    db_session.commit()

    count = delete_all_user_rate_limits(db_session, user.id)
    db_session.commit()
    assert count == 2
    assert get_user_rate_limits(db_session, user.id) == []


def test_delete_rate_limit_setting(db_session: Session) -> None:
    from songmaker_cli.db.queries import (
        delete_rate_limit_setting,
        get_rate_limit_setting,
        upsert_rate_limit_setting,
    )

    upsert_rate_limit_setting(db_session, "generation_rate_limit", 50)
    db_session.commit()

    assert delete_rate_limit_setting(db_session, "generation_rate_limit") is True
    db_session.commit()
    assert get_rate_limit_setting(db_session, "generation_rate_limit") is None
    assert delete_rate_limit_setting(db_session, "generation_rate_limit") is False


# ── Migration tests ────────────────────────────────────────────────


def test_init_db_fresh_creates_all_tables(tmp_path: Path) -> None:
    from sqlalchemy import create_engine, inspect

    from songmaker_cli.db.engine import init_db

    db_path = tmp_path / "fresh.db"
    init_db(f"sqlite:///{db_path}")

    engine = create_engine(f"sqlite:///{db_path}")
    tables = set(inspect(engine).get_table_names())
    engine.dispose()

    expected = {
        "albums",
        "songs",
        "versions",
        "generations",
        "scores",
        "ratings",
        "jobs",
        "users",
        "user_sessions",
        "login_attempts",
        "audit_log",
        "generation_presets",
        "rate_limit_settings",
        "available_models",
        "playlists",
        "playlist_entries",
        "chat_messages",
        "conversations",
        "conversation_summaries",
        "cowriter_user_memories",
        "cowriter_song_memories",
        "cowriter_album_memories",
        "acestep_workers",
        "user_loras",
        "user_lora_samples",
        "resource_event_cursors",
        "resource_events",
        "alembic_version",
    }
    assert tables == expected


def test_acestep_canonical_names_migration_renames_json_keys(tmp_path: Path) -> None:
    import json as _json

    from sqlalchemy import text as _sql_text

    from songmaker_cli.db.engine import init_db
    from songmaker_cli.db.migrations.versions import (
        b8c9d1e2f3a4_acestep_canonical_names as mig,
    )
    from songmaker_cli.db.models import Album, Song, Version

    factory = init_db(f"sqlite:///{tmp_path / 'migrate.db'}")
    old_params = {
        "duration": 180,
        "key": "Am",
        "src_audio": "/audio/x.wav",
        "reference_audio": "/audio/r.wav",
        "think_mode": "deep",
        "bpm": 120,
    }
    with factory() as session:
        session.add(Album(id="a1", title="A", artist="X"))
        session.add(
            Song(
                id="s1",
                title="S",
                album_id="a1",
                vocal_language="en",
                track_number=1,
            )
        )
        session.commit()
        session.execute(
            _sql_text(
                "INSERT INTO versions (id, song_id, version_number, lyrics, prompt, "
                "bpm, audio_duration, key_scale, generation_params, created_at) "
                "VALUES ('v1', 's1', 1, 'l', 'p', 120, 180, 'Am', :params, "
                "CURRENT_TIMESTAMP)",
            ),
            {"params": _json.dumps(old_params)},
        )
        session.commit()

    engine = factory.kw["bind"]
    with engine.begin() as conn:
        original_get_bind = mig.op.get_bind
        mig.op.get_bind = lambda: conn
        try:
            mig._migrate_json_column("versions", "generation_params", forward=True)
        finally:
            mig.op.get_bind = original_get_bind

    with factory() as session:
        ver = session.query(Version).filter_by(id="v1").one()
        params = ver.generation_params
        assert params["audio_duration"] == 180
        assert params["key_scale"] == "Am"
        assert params["src_audio_path"] == "/audio/x.wav"
        assert params["reference_audio_path"] == "/audio/r.wav"
        assert params["thinking"] is True
        assert params["bpm"] == 120
        assert "duration" not in params
        assert "key" not in params
        assert "src_audio" not in params
        assert "reference_audio" not in params
        assert "think_mode" not in params

    engine.dispose()


def test_acestep_canonical_names_migration_downgrade_reverses_json_keys(tmp_path: Path) -> None:
    import json as _json

    from sqlalchemy import text as _sql_text

    from songmaker_cli.db.engine import init_db
    from songmaker_cli.db.migrations.versions import (
        b8c9d1e2f3a4_acestep_canonical_names as mig,
    )
    from songmaker_cli.db.models import Album, Song, Version

    factory = init_db(f"sqlite:///{tmp_path / 'migrate_down.db'}")
    new_params = {
        "audio_duration": 180,
        "key_scale": "Am",
        "src_audio_path": "/audio/x.wav",
        "thinking": False,
    }
    with factory() as session:
        session.add(Album(id="a1", title="A", artist="X"))
        session.add(Song(id="s1", title="S", album_id="a1", track_number=1))
        session.commit()
        session.execute(
            _sql_text(
                "INSERT INTO versions (id, song_id, version_number, lyrics, prompt, "
                "bpm, audio_duration, key_scale, generation_params, created_at) "
                "VALUES ('v1', 's1', 1, 'l', 'p', 120, 180, 'Am', :params, "
                "CURRENT_TIMESTAMP)",
            ),
            {"params": _json.dumps(new_params)},
        )
        session.commit()

    engine = factory.kw["bind"]
    with engine.begin() as conn:
        original_get_bind = mig.op.get_bind
        mig.op.get_bind = lambda: conn
        try:
            mig._migrate_json_column("versions", "generation_params", forward=False)
        finally:
            mig.op.get_bind = original_get_bind

    with factory() as session:
        ver = session.query(Version).filter_by(id="v1").one()
        params = ver.generation_params
        assert params["duration"] == 180
        assert params["key"] == "Am"
        assert params["src_audio"] == "/audio/x.wav"
        assert params["think_mode"] == "off"

    engine.dispose()


def test_init_db_stamps_existing_db(tmp_path: Path) -> None:
    from sqlalchemy import create_engine, inspect, text

    from songmaker_cli.db.engine import init_db
    from songmaker_cli.db.models import Base

    db_path = tmp_path / "existing.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    engine.dispose()

    init_db(f"sqlite:///{db_path}")

    engine = create_engine(f"sqlite:///{db_path}")
    tables = set(inspect(engine).get_table_names())
    assert "alembic_version" in tables
    with engine.connect() as conn:
        row = conn.execute(text("SELECT version_num FROM alembic_version")).fetchone()
        assert row is not None
    engine.dispose()


def test_whisper_cues_migration_adds_nullable_column(tmp_path: Path) -> None:
    from sqlalchemy import create_engine, inspect

    from songmaker_cli.db.engine import init_db

    db_path = tmp_path / "cues.db"
    init_db(f"sqlite:///{db_path}")
    engine = create_engine(f"sqlite:///{db_path}")
    cols = {c["name"]: c for c in inspect(engine).get_columns("generations")}
    engine.dispose()
    assert "whisper_cues" in cols
    assert cols["whisper_cues"]["nullable"] is True


# ── Claude model settings ───────────────────────────────────────────


def test_get_claude_chat_model_fallback(db_session: Session) -> None:
    from songmaker_cli.db.queries.settings import get_claude_chat_model

    # No DB row → falls back to Settings default ("claude-opus-4-6")
    assert get_claude_chat_model(db_session) == "claude-opus-4-6"


def test_set_and_get_claude_chat_model(db_session: Session) -> None:
    from songmaker_cli.db.queries.settings import (
        get_claude_chat_model,
        set_claude_model,
    )

    set_claude_model(db_session, "claude_chat_model", "claude-sonnet-4-6")
    assert get_claude_chat_model(db_session) == "claude-sonnet-4-6"


def test_set_claude_chat_model_updates_existing(db_session: Session) -> None:
    from songmaker_cli.db.queries.settings import (
        get_claude_chat_model,
        set_claude_model,
    )

    set_claude_model(db_session, "claude_chat_model", "claude-sonnet-4-6")
    set_claude_model(db_session, "claude_chat_model", "claude-haiku-4-5-20251001")
    assert get_claude_chat_model(db_session) == "claude-haiku-4-5-20251001"


# ── Generation retention tests ──────────────────────────────────────


def test_archive_generation_sets_timestamp(seeded_session: Session) -> None:
    from datetime import datetime, timezone

    gen = archive_generation(seeded_session, "g1")
    seeded_session.commit()
    assert gen.is_archived is True
    assert gen.archived_at is not None
    archived = gen.archived_at
    if archived.tzinfo is None:
        archived = archived.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - archived
    assert delta.total_seconds() < 5


def test_unarchive_generation_clears_timestamp(seeded_session: Session) -> None:
    archive_generation(seeded_session, "g1")
    seeded_session.commit()
    gen = unarchive_generation(seeded_session, "g1")
    seeded_session.commit()
    assert gen.is_archived is False
    assert gen.archived_at is None


def test_archive_generation_not_found(seeded_session: Session) -> None:
    with pytest.raises(ValueError, match="Generation not found"):
        archive_generation(seeded_session, "missing")


def test_unarchive_generation_not_found(seeded_session: Session) -> None:
    with pytest.raises(ValueError, match="Generation not found"):
        unarchive_generation(seeded_session, "missing")


def _shift_created_at(session: Session, gen_id: str, days_ago: int) -> None:
    from datetime import datetime, timedelta, timezone

    gen = get_generation(session, gen_id)
    gen.created_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
    session.flush()


def _shift_archived_at(session: Session, gen_id: str, days_ago: int) -> None:
    from datetime import datetime, timedelta, timezone

    gen = get_generation(session, gen_id)
    gen.archived_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
    session.flush()


def test_list_expired_for_archive_skips_picked_and_kept(seeded_session: Session) -> None:
    from datetime import datetime, timedelta, timezone

    pick_generation(seeded_session, "g1")
    keep_generation(seeded_session, "g2")
    _shift_created_at(seeded_session, "g1", 30)
    _shift_created_at(seeded_session, "g2", 30)
    seeded_session.commit()

    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    expired = list_generations_expired_for_archive(seeded_session, cutoff)
    assert expired == []


def test_list_expired_for_archive_picks_old_unmarked(seeded_session: Session) -> None:
    from datetime import datetime, timedelta, timezone

    _shift_created_at(seeded_session, "g1", 30)
    seeded_session.commit()

    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    expired = list_generations_expired_for_archive(seeded_session, cutoff)
    ids = {g.id for g in expired}
    assert ids == {"g1"}


def test_list_expired_for_archive_skips_already_archived(seeded_session: Session) -> None:
    from datetime import datetime, timedelta, timezone

    archive_generation(seeded_session, "g1")
    _shift_created_at(seeded_session, "g1", 30)
    seeded_session.commit()

    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    expired = list_generations_expired_for_archive(seeded_session, cutoff)
    assert expired == []


def test_list_expired_for_delete_picks_old_archived(seeded_session: Session) -> None:
    from datetime import datetime, timedelta, timezone

    archive_generation(seeded_session, "g1")
    _shift_archived_at(seeded_session, "g1", 60)
    seeded_session.commit()

    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    expired = list_generations_expired_for_delete(seeded_session, cutoff)
    assert {g.id for g in expired} == {"g1"}


def test_list_expired_for_delete_skips_anchors(seeded_session: Session) -> None:
    from datetime import datetime, timedelta, timezone

    # Make g2 a child of g1
    g2 = get_generation(seeded_session, "g2")
    g2.src_generation_id = "g1"
    seeded_session.flush()

    archive_generation(seeded_session, "g1")
    _shift_archived_at(seeded_session, "g1", 60)
    seeded_session.commit()

    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    expired = list_generations_expired_for_delete(seeded_session, cutoff)
    assert expired == []


def test_list_expired_for_delete_skips_recent_archives(seeded_session: Session) -> None:
    from datetime import datetime, timedelta, timezone

    archive_generation(seeded_session, "g1")
    _shift_archived_at(seeded_session, "g1", 5)
    seeded_session.commit()

    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    expired = list_generations_expired_for_delete(seeded_session, cutoff)
    assert expired == []


def _alembic_config(url: str):
    from alembic.config import Config

    from songmaker_cli.db.engine import MIGRATIONS_DIR

    cfg = Config()
    cfg.set_main_option("script_location", MIGRATIONS_DIR)
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def test_song_slug_backfill_fills_every_song_uniquely_per_album(tmp_path: Path) -> None:
    from alembic import command
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from songmaker_cli.db.migrations.versions import (
        b8e3f1c07a25_add_slug_to_songs as mig,
    )
    from songmaker_cli.db.models import SONG_SLUG_MAX_LENGTH, Album, Song

    # Pinned to b8e3f1c07a25, the revision that introduced this backfill —
    # c9d4a2f18e37 promotes the index to UNIQUE afterwards, which the seeded
    # rows below (multiple empty slugs per album) would violate.
    url = f"sqlite:///{tmp_path / 'slugs.db'}"
    command.upgrade(_alembic_config(url), "b8e3f1c07a25")

    engine = create_engine(url)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        session.add_all([
            Album(id="a1", title="A", artist="X"),
            Album(id="a2", title="B", artist="X"),
            Song(id="s1", title="Intro", album_id="a1", track_number=1),
            Song(id="s2", title="Intro", album_id="a1", track_number=2),
            Song(id="s3", title="Intro", album_id="a2", track_number=1),
            Song(id="s4", title="!!!", album_id="a2", track_number=2),
            Song(id="s5", title="音" * 200, album_id="a2", track_number=3),
            Song(id="s6", title="???", album_id="a2", track_number=4),
        ])
        session.commit()

    with engine.begin() as conn:
        original_get_bind = mig.op.get_bind
        mig.op.get_bind = lambda: conn
        try:
            mig._backfill_song_slugs()
        finally:
            mig.op.get_bind = original_get_bind

    with factory() as session:
        slugs = {song.id: song.slug for song in session.query(Song).all()}

    assert slugs["s1"] == "intro"
    assert slugs["s2"] == "intro-2"
    assert slugs["s3"] == "intro"
    assert slugs["s4"] == "untitled"
    assert slugs["s6"] == "untitled-2"

    cjk_slug = slugs["s5"]
    assert cjk_slug.startswith("yin-yin")
    assert len(cjk_slug) <= SONG_SLUG_MAX_LENGTH
    engine.dispose()


def test_song_slug_index_promoted_to_unique_repairs_stragglers(tmp_path: Path) -> None:
    """c9d4a2f18e37: repair pre-existing slug='' rows, then enforce UNIQUE.

    Simulates a song the co-writer created or renamed before #270 landed
    (slug='' surviving next to a sibling that already has a real slug),
    proving the migration both repairs the straggler and then blocks any
    new collision. downgrade() restores the plain, non-unique index.
    """
    from alembic import command
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import sessionmaker

    from songmaker_cli.db.models import Album, Song

    url = f"sqlite:///{tmp_path / 'unique_slug.db'}"
    cfg = _alembic_config(url)
    command.upgrade(cfg, "b8e3f1c07a25")

    engine = create_engine(url)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        session.add_all([
            Album(id="a1", title="A", artist="X"),
            Song(id="s1", title="Intro", album_id="a1", track_number=1, slug="intro"),
            # Straggler: created via the co-writer MCP path before #270.
            Song(id="s2", title="Reprise", album_id="a1", track_number=2, slug=""),
        ])
        session.commit()
    engine.dispose()

    command.upgrade(cfg, "c9d4a2f18e37")

    engine = create_engine(url)
    with engine.begin() as conn:
        rows = dict(
            conn.execute(text("SELECT id, slug FROM songs")).fetchall(),
        )
    assert rows == {"s1": "intro", "s2": "reprise"}

    factory = sessionmaker(bind=engine)
    with factory() as session:
        session.add(Song(id="s3", title="Dup", album_id="a1", track_number=3, slug="intro"))
        with pytest.raises(IntegrityError):
            session.commit()
    engine.dispose()

    command.downgrade(cfg, "b8e3f1c07a25")

    engine = create_engine(url)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        session.add(Song(id="s3", title="Dup", album_id="a1", track_number=3, slug="intro"))
        session.commit()
    engine.dispose()


def test_playlist_slug_migration_backfills_dedupes_and_enforces_unique(tmp_path: Path) -> None:
    """d5f8a3b21c46: unlike the two-phase song migration (b8e3f1c07a25 then
    c9d4a2f18e37), playlists have no second write path to guard a window
    for, so backfill and UNIQUE(slug) land in one migration. Proves the
    throwaway-DB upgrade dedupes existing (pre-migration) playlists sharing
    a title, handles a wide CJK title within the length budget, then blocks
    a real collision — and that downgrade() cleanly drops the column again.
    """
    from alembic import command
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import sessionmaker

    from songmaker_cli.db.models import PLAYLIST_SLUG_MAX_LENGTH, Playlist

    url = f"sqlite:///{tmp_path / 'playlist_slugs.db'}"
    cfg = _alembic_config(url)
    # Pinned to the revision before this one: at this point 'playlists' has
    # no slug column yet, matching real pre-existing rows.
    command.upgrade(cfg, "c9d4a2f18e37")

    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO playlists (id, title, is_shared, created_at, updated_at) "
                "VALUES (:id, :title, 0, :ts, :ts)"
            ),
            [
                {"id": "p1", "title": "Favorites", "ts": "2026-01-01T00:00:00+00:00"},
                {"id": "p2", "title": "Favorites", "ts": "2026-01-02T00:00:00+00:00"},
                {"id": "p3", "title": "音" * 200, "ts": "2026-01-03T00:00:00+00:00"},
            ],
        )
    engine.dispose()

    command.upgrade(cfg, "d5f8a3b21c46")

    engine = create_engine(url)
    with engine.begin() as conn:
        rows = dict(conn.execute(text("SELECT id, slug FROM playlists")).fetchall())
    engine.dispose()

    assert rows["p1"] == "favorites"
    assert rows["p2"] == "favorites-2"
    cjk_slug = rows["p3"]
    assert cjk_slug.startswith("yin-yin")
    assert len(cjk_slug) <= PLAYLIST_SLUG_MAX_LENGTH

    engine = create_engine(url)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        session.add(Playlist(id="p4", title="Dup", slug="favorites"))
        with pytest.raises(IntegrityError):
            session.commit()
    engine.dispose()

    command.downgrade(cfg, "c9d4a2f18e37")

    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO playlists (id, title, is_shared, created_at, updated_at) "
                "VALUES ('p5', 'Dup', 0, '2026-01-04T00:00:00+00:00', '2026-01-04T00:00:00+00:00')"
            )
        )
    engine.dispose()
