"""End-to-end tests for generation retention cleanup."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from songmaker_cli.api_models.songs import generation_expiry
from songmaker_cli.cleanup import run_generation_retention
from songmaker_cli.db.engine import init_test_db as init_db
from songmaker_cli.db.models import Album, Generation, Song, Version
from songmaker_cli.db.queries import (
    archive_generation,
    get_generation,
    keep_generation,
    pick_generation,
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
