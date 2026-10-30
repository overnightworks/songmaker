"""End-to-end tests for generation retention cleanup."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from songmaker_cli.api_models.songs import generation_expiry
from songmaker_cli.cleanup import run_generation_retention
from songmaker_cli.db.engine import init_test_db as init_db
from songmaker_cli.db.models import Album, Generation, Rating, Score, Song, Version
from songmaker_cli.db.queries.generations import (
    archive_generation,
    get_generation,
    keep_generation,
    pick_generation,
    unkeep_generation,
    unpick_generation,
)


@pytest.fixture
def retention_factory(tmp_path: Path):
    factory = init_db(tmp_path / "retention.db")
    with factory() as session:
        session.add(Album(id="a1", title="A", artist="X"))
        session.add(Song(id="s1", title="S", album_id="a1", track_number=1))
        session.add(Version(id="v1", song_id="s1", version_number=1, lyrics="", prompt=""))
        session.add_all(
            [
                Generation(
                    id=f"g{i}", song_id="s1", version_id="v1",
                    generation_number=i, mp3_path=f"a1/{i}.mp3",
                )
                for i in range(1, 5)
            ],
        )
        session.commit()
    return factory


def _age(factory, gen_id: str, *, created_days_ago: int = 0,
         archived_days_ago: int | None = None) -> None:
    with factory() as session:
        gen = get_generation(session, gen_id)
        gen.created_at = datetime.now(timezone.utc) - timedelta(days=created_days_ago)
        if archived_days_ago is not None:
            gen.is_archived = True
            gen.archived_at = datetime.now(timezone.utc) - timedelta(days=archived_days_ago)
        session.commit()


def test_dry_run_reports_without_writes(retention_factory, tmp_path: Path) -> None:
    _age(retention_factory, "g1", created_days_ago=30)
    _age(retention_factory, "g2", created_days_ago=60, archived_days_ago=45)

    report = run_generation_retention(
        retention_factory, tmp_path / "audio", dry_run=True,
    )

    assert report.archived_ids == ["g1"]
    assert report.deleted_ids == ["g2"]

    with retention_factory() as session:
        g1 = get_generation(session, "g1")
        g2 = get_generation(session, "g2")
        assert g1.is_archived is False
        assert g2 is not None


def test_archive_stage_sets_flag_and_timestamp(retention_factory, tmp_path: Path) -> None:
    _age(retention_factory, "g1", created_days_ago=30)

    report = run_generation_retention(retention_factory, tmp_path / "audio")

    assert report.archived_ids == ["g1"]
    with retention_factory() as session:
        gen = get_generation(session, "g1")
        assert gen.is_archived is True
        assert gen.archived_at is not None


def test_hard_delete_removes_row(retention_factory, tmp_path: Path) -> None:
    _age(retention_factory, "g1", created_days_ago=60, archived_days_ago=45)

    report = run_generation_retention(retention_factory, tmp_path / "audio")

    assert "g1" in report.deleted_ids
    with retention_factory() as session:
        assert get_generation(session, "g1") is None


def test_picked_and_kept_are_preserved(retention_factory, tmp_path: Path) -> None:
    with retention_factory() as session:
        pick_generation(session, "g1")
        keep_generation(session, "g2")
        session.commit()
    _age(retention_factory, "g1", created_days_ago=90)
    _age(retention_factory, "g2", created_days_ago=90)

    report = run_generation_retention(retention_factory, tmp_path / "audio")

    assert "g1" not in report.archived_ids
    assert "g2" not in report.archived_ids
    with retention_factory() as session:
        assert get_generation(session, "g1").is_archived is False
        assert get_generation(session, "g2").is_archived is False


def test_src_generation_anchor_not_hard_deleted(
    retention_factory, tmp_path: Path,
) -> None:
    with retention_factory() as session:
        child = get_generation(session, "g2")
        child.src_generation_id = "g1"
        session.commit()

    _age(retention_factory, "g1", created_days_ago=90, archived_days_ago=60)

    report = run_generation_retention(retention_factory, tmp_path / "audio")

    assert "g1" not in report.deleted_ids
    with retention_factory() as session:
        assert get_generation(session, "g1") is not None


def test_archived_generations_are_not_re_archived(
    retention_factory, tmp_path: Path,
) -> None:
    with retention_factory() as session:
        archive_generation(session, "g1")
        session.commit()
    _age(retention_factory, "g1", created_days_ago=30, archived_days_ago=5)

    report = run_generation_retention(retention_factory, tmp_path / "audio")

    assert "g1" not in report.archived_ids


@pytest.mark.parametrize("final_deletion_days", [30, 7])
@pytest.mark.parametrize("days_offset", [-1, 0, 1])
def test_archived_take_is_deleted_exactly_at_the_final_deletion_setting(
    retention_factory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fresh_settings,
    final_deletion_days: int, days_offset: int,
) -> None:
    monkeypatch.setenv("FINAL_DELETION_DAYS", str(final_deletion_days))
    _age(retention_factory, "g1", created_days_ago=90,
         archived_days_ago=final_deletion_days + days_offset)

    report = run_generation_retention(retention_factory, tmp_path / "audio")

    assert ("g1" in report.deleted_ids) is (days_offset >= 0)


def test_live_generation_expires_after_the_retention_window(retention_factory) -> None:
    with retention_factory() as session:
        gen = get_generation(session, "g1")
        assert generation_expiry(gen) == gen.created_at + timedelta(days=7)


def test_archived_generation_expires_after_the_hard_delete_window(
    retention_factory,
) -> None:
    _age(retention_factory, "g1", created_days_ago=30, archived_days_ago=10)

    with retention_factory() as session:
        gen = get_generation(session, "g1")
        assert generation_expiry(gen) == gen.archived_at + timedelta(days=30)


@pytest.mark.parametrize("mark_survivor", [pick_generation, keep_generation])
def test_picked_or_kept_generation_never_expires(
    retention_factory, mark_survivor,
) -> None:
    with retention_factory() as session:
        mark_survivor(session, "g1")
        session.commit()

    with retention_factory() as session:
        assert generation_expiry(get_generation(session, "g1")) is None


def _seed_audio_files(factory, audio_dir: Path, gen_id: str) -> list[Path]:
    """Real mp3 and wav files for the take, linked from its row."""
    mp3, wav = audio_dir / "a1" / f"{gen_id}.mp3", audio_dir / "a1" / f"{gen_id}.wav"
    mp3.parent.mkdir(parents=True, exist_ok=True)
    mp3.write_bytes(b"mp3")
    wav.write_bytes(b"wav")
    with factory() as session:
        gen = get_generation(session, gen_id)
        gen.mp3_path, gen.wav_path = f"a1/{gen_id}.mp3", f"a1/{gen_id}.wav"
        session.commit()
    return [mp3, wav]


def _mark_after_archiving(factory, gen_id: str, mark) -> None:
    """The take is archived long ago and marked afterwards, as the API allows."""
    _age(factory, gen_id, created_days_ago=90, archived_days_ago=60)
    with factory() as session:
        mark(session, gen_id)
        session.commit()


@pytest.mark.parametrize("mark", [keep_generation, pick_generation])
def test_an_archived_pick_or_keep_past_the_window_is_not_deleted(
    retention_factory, tmp_path: Path, mark,
) -> None:
    audio_dir = tmp_path / "audio"
    files = _seed_audio_files(retention_factory, audio_dir, "g1")
    _mark_after_archiving(retention_factory, "g1", mark)

    report = run_generation_retention(retention_factory, audio_dir)

    assert report.deleted_ids == []
    with retention_factory() as session:
        assert get_generation(session, "g1") is not None
    assert all(path.exists() for path in files)


def test_an_archived_unmarked_take_past_the_window_is_deleted_with_its_scores_ratings_and_files(
    retention_factory, tmp_path: Path,
) -> None:
    audio_dir = tmp_path / "audio"
    files = _seed_audio_files(retention_factory, audio_dir, "g1")
    _age(retention_factory, "g1", created_days_ago=90, archived_days_ago=60)
    with retention_factory() as session:
        session.add(Score(generation_id="g1", scorer="bpm", value={"score": 1}))
        session.add(Rating(generation_id="g1", rating=4))
        session.commit()

    report = run_generation_retention(retention_factory, audio_dir)

    assert report.deleted_ids == ["g1"]
    with retention_factory() as session:
        assert get_generation(session, "g1") is None
        assert session.query(Score).count() == 0
        assert session.query(Rating).count() == 0
    assert not any(path.exists() for path in files)


def test_a_dry_run_names_only_the_takes_a_real_run_would_delete(
    retention_factory, tmp_path: Path,
) -> None:
    _mark_after_archiving(retention_factory, "g1", keep_generation)
    _mark_after_archiving(retention_factory, "g2", pick_generation)
    _age(retention_factory, "g3", created_days_ago=90, archived_days_ago=60)

    report = run_generation_retention(retention_factory, tmp_path / "audio", dry_run=True)

    assert report.deleted_ids == ["g3"]
    with retention_factory() as session:
        assert {gen.id for gen in session.query(Generation)} == {"g1", "g2", "g3", "g4"}


def test_an_archived_keep_that_is_also_an_anchor_is_not_deleted(
    retention_factory, tmp_path: Path,
) -> None:
    with retention_factory() as session:
        get_generation(session, "g2").src_generation_id = "g1"
        session.commit()
    _mark_after_archiving(retention_factory, "g1", keep_generation)

    report = run_generation_retention(retention_factory, tmp_path / "audio")

    assert report.deleted_ids == []
    with retention_factory() as session:
        assert get_generation(session, "g1") is not None


def test_the_report_names_exactly_the_takes_stage_one_wrote(
    retention_factory, tmp_path: Path,
) -> None:
    _age(retention_factory, "g1", created_days_ago=30)
    _age(retention_factory, "g2", created_days_ago=30)
    with retention_factory() as session:
        keep_generation(session, "g2")
        session.commit()

    report = run_generation_retention(retention_factory, tmp_path / "audio")

    assert report.archived_ids == ["g1"]
    with retention_factory() as session:
        assert get_generation(session, "g1").is_archived is True
        assert get_generation(session, "g2").is_archived is False


@pytest.mark.parametrize("unmark", [unkeep_generation, unpick_generation])
def test_a_take_unmarked_after_long_archiving_is_deleted_at_the_next_run(
    retention_factory, tmp_path: Path, unmark,
) -> None:
    mark = keep_generation if unmark is unkeep_generation else pick_generation
    _mark_after_archiving(retention_factory, "g1", mark)
    with retention_factory() as session:
        unmark(session, "g1")
        session.commit()

    report = run_generation_retention(retention_factory, tmp_path / "audio")

    assert report.deleted_ids == ["g1"]


def test_a_failed_commit_of_the_second_deletion_keeps_the_first_deleted_and_the_second_intact(
    retention_factory, tmp_path: Path, session_commit_failure,
) -> None:
    audio_dir = tmp_path / "audio"
    first = _seed_audio_files(retention_factory, audio_dir, "g1")
    second = _seed_audio_files(retention_factory, audio_dir, "g2")
    for gen_id in ("g1", "g2"):
        _age(retention_factory, gen_id, created_days_ago=90, archived_days_ago=60)
    commits = []

    def is_second_commit(_session) -> bool:
        commits.append(None)
        return len(commits) == 2

    with session_commit_failure(retention_factory, when=is_second_commit):
        with pytest.raises(RuntimeError, match="commit failed"):
            run_generation_retention(retention_factory, audio_dir)

    with retention_factory() as session:
        assert get_generation(session, "g1") is None
        assert get_generation(session, "g2") is not None
    assert not any(path.exists() for path in first)
    assert all(path.exists() for path in second)
