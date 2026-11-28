"""The migration that lets a job row remember the version it renders."""

from __future__ import annotations

import importlib

import sqlalchemy as sa
from sqlalchemy import inspect
from support.migration_chain import (
    assert_column_nullable_empty_and_job_kept,
    assert_downgrade_drops_indexed_column_and_keeps_job,
    insert_bare_job,
    seeded_then_upgraded,
)
from support.reference_link_migration import execute, seed_users

MIGRATION_MODULE = "songmaker_cli.db.migrations.versions.e3a91c5d7f20_jobs_remember_their_version"
PREVIOUS_REVISION = "c4d7e1a9b3f6"
COLUMN = "version_id"
JOBS_VERSION = sa.table("jobs", sa.column(COLUMN))
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
    insert_bare_job(engine)


def _job_versions(engine) -> list[str | None]:
    with engine.connect() as connection:
        return list(connection.execute(sa.select(JOBS_VERSION.c[COLUMN])).scalars())


def _upgraded_with_a_job(database):
    return seeded_then_upgraded(
        database, PREVIOUS_REVISION, MIGRATION.revision, _seed_job_at_the_previous_revision
    )


def test_the_migration_follows_the_previous_revision():
    assert MIGRATION.down_revision == PREVIOUS_REVISION


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
    assert_column_nullable_empty_and_job_kept(engine, COLUMN)


def test_deleting_a_version_sets_its_jobs_key_to_null(reference_link_database):
    engine = _upgraded_with_a_job(reference_link_database)
    with engine.begin() as connection:
        connection.execute(sa.update(JOBS_VERSION).values({COLUMN: "version"}))
    execute(engine, "DELETE FROM versions")
    assert _job_versions(engine) == [None]


def test_downgrade_drops_the_key_and_keeps_the_job(reference_link_database):
    _upgraded_with_a_job(reference_link_database)
    assert_downgrade_drops_indexed_column_and_keeps_job(
        reference_link_database, COLUMN, PREVIOUS_REVISION, MIGRATION.revision,
    )
