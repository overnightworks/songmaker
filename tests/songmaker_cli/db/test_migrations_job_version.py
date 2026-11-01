"""The migration that lets a job row remember the version it renders."""

from __future__ import annotations

import importlib

from alembic import command
from sqlalchemy import inspect, text
from support.migration_chain import column_names, is_on_the_single_chain, seeded_then_upgraded
from support.reference_link_migration import execute, seed_users

MIGRATION_MODULE = "songmaker_cli.db.migrations.versions.e3a91c5d7f20_jobs_remember_their_version"
PREVIOUS_REVISION = "c4d7e1a9b3f6"
COLUMN = "version_id"
MIGRATION = importlib.import_module(MIGRATION_MODULE)


def _seed_job_at_the_previous_revision(engine) -> None:
    seed_users(engine)
    execute(
        engine,
        "INSERT INTO albums (id, title, artist, subtitle, year, colors, created_at, created_by) "
        "VALUES ('album', 'A', 'B', '', 0, '{}', CURRENT_TIMESTAMP, 'u1')",
    )
    execute(
        engine,
        "INSERT INTO songs (id, title, album_id, vocal_language, track_number, created_at, "
        "updated_at, slug) VALUES ('song', 'S', 'album', '', 1, CURRENT_TIMESTAMP, "
        "CURRENT_TIMESTAMP, 's')",
    )
    execute(
        engine,
        "INSERT INTO versions (id, song_id, version_number, lyrics, prompt, bpm, audio_duration, "
        "key_scale, created_at) VALUES ('version', 'song', 1, '', '', 0, 0, '', CURRENT_TIMESTAMP)",
    )
    # The SQLite chain builds a narrower jobs table than PostgreSQL's, so the row names
    # only the columns both have plus the timestamps where they exist.
    present = column_names(engine, "jobs")
    timestamps = [name for name in ("heartbeat_at", "started_at") if name in present]
    execute(
        engine,
        "INSERT INTO jobs (id, type, status, progress"
        + "".join(f", {name}" for name in timestamps)
        + ") VALUES ('job', 'generate', 'queued', 0.0"
        + ", CURRENT_TIMESTAMP" * len(timestamps)
        + ")",
    )


def _job_count(engine) -> int:
    with engine.connect() as connection:
        return connection.execute(text("SELECT count(*) FROM jobs")).scalar_one()


def _upgraded_with_a_job(database):
    return seeded_then_upgraded(
        database, PREVIOUS_REVISION, MIGRATION.revision, _seed_job_at_the_previous_revision
    )


def test_the_migration_follows_the_previous_revision_on_the_single_chain():
    assert MIGRATION.down_revision == PREVIOUS_REVISION
    assert is_on_the_single_chain(MIGRATION.revision)


def test_upgrade_adds_an_indexed_nullable_key_that_the_database_sets_null(
    reference_link_database,
):
    engine = _upgraded_with_a_job(reference_link_database)
    inspector = inspect(engine)
    column = next(c for c in inspector.get_columns("jobs") if c["name"] == COLUMN)
    assert column["nullable"] is True
    assert any(index["column_names"] == [COLUMN] for index in inspector.get_indexes("jobs"))
    [foreign_key] = [
        fk for fk in inspector.get_foreign_keys("jobs") if fk["constrained_columns"] == [COLUMN]
    ]
    assert foreign_key["referred_table"] == "versions"
    assert foreign_key["options"]["ondelete"].upper() == "SET NULL"


def test_upgrade_keeps_an_existing_job_without_a_version(reference_link_database):
    engine = _upgraded_with_a_job(reference_link_database)
    with engine.connect() as connection:
        assert connection.execute(text(f"SELECT {COLUMN} FROM jobs")).scalars().all() == [None]


def test_deleting_a_version_sets_its_jobs_key_to_null(reference_link_database):
    engine = _upgraded_with_a_job(reference_link_database)
    execute(engine, f"UPDATE jobs SET {COLUMN} = 'version'")
    execute(engine, "DELETE FROM versions")
    with engine.connect() as connection:
        assert connection.execute(text(f"SELECT {COLUMN} FROM jobs")).scalars().all() == [None]


def test_downgrade_drops_the_key_and_keeps_the_job(reference_link_database):
    config, _ = reference_link_database
    engine = _upgraded_with_a_job(reference_link_database)
    command.downgrade(config, PREVIOUS_REVISION)
    assert COLUMN not in column_names(engine, "jobs")
    assert not any(
        index["column_names"] == [COLUMN] for index in inspect(engine).get_indexes("jobs")
    )
    assert _job_count(engine) == 1
    command.upgrade(config, MIGRATION.revision)
    assert COLUMN in column_names(engine, "jobs")
