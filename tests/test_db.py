"""Tests for the database layer — models, engine, queries."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from songmaker_cli.db.engine import init_db, reset_engine
from songmaker_cli.db.models import Album, Generation, Rating, Score, Song, Version
from songmaker_cli.db.queries import (
    _UNSET,
    album_to_dict,
    cleanup_album,
    create_generation,
    create_job,
    create_song,
    delete_generation,
    delete_version,
    generation_to_dict,
    get_album,
    get_generation,
    get_generation_by_path,
    get_job,
    get_song,
    job_to_dict,
    list_albums,
    list_songs,
    pick_generation,
    save_rating,
    save_scores,
    song_to_dict,
    unpick_generation,
    update_job_status,
    update_song,
    version_to_dict,
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
    d = generation_to_dict(gen)
    assert d["seed"] == 42
    assert d["scores"]["dynamics"] == 55.0
    assert d["scores"]["user_rating"] == 82.5


def test_song_to_dict(seeded_session: Session) -> None:
    song = get_song(seeded_session, "s1")
    d = song_to_dict(song)
    assert d["title"] == "Song One"
    assert d["generation_count"] == 2
    assert d["best_rating"] == 82.5
    assert len(d["generations"]) == 2


def test_album_to_dict(seeded_session: Session) -> None:
    album = get_album(seeded_session, "test")
    d = album_to_dict(album)
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
    d = job_to_dict(job)
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
    d = generation_to_dict(gen)
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
    d = version_to_dict(song.latest_version)
    assert d["generation_params"] == params


def test_song_to_dict_includes_generation_params(seeded_session: Session) -> None:
    params = {"lm_temperature": 0.5}
    update_song(seeded_session, "s1", generation_params=params)
    seeded_session.commit()
    song = get_song(seeded_session, "s1")
    d = song_to_dict(song)
    assert d["generation_params"] == params
