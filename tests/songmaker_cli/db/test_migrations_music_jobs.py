"""The migration that refuses to run while a music job's arguments live only in Redis."""

from __future__ import annotations

import importlib

import pytest
from alembic import command
from alembic.runtime.migration import MigrationContext
from support.migration_chain import insert_bare_job, job_count

MIGRATION = importlib.import_module(
    "songmaker_cli.db.migrations.versions.b8d3f6a2c915_music_jobs_wait_only_in_postgresql"
)


def _revision_of(engine) -> str | None:
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def _database_at_previous_revision_holding(database, job_type: str, status: str):
    config, engine = database
    command.upgrade(config, MIGRATION.down_revision)
    insert_bare_job(engine, job_type=job_type, status=status)
    return config, engine


@pytest.mark.parametrize(
    "job_type", ["generate", "lora_training", "load_model_on_worker", "download_model_on_worker"],
)
def test_upgrade_refuses_while_a_queued_music_job_has_no_payload_and_stays_at_the_old_revision(
    reference_link_database, job_type,
):
    config, engine = _database_at_previous_revision_holding(
        reference_link_database, job_type, "queued",
    )

    with pytest.raises(RuntimeError, match="queued music jobs"):
        command.upgrade(config, MIGRATION.revision)

    assert (_revision_of(engine), job_count(engine)) == (MIGRATION.down_revision, 1)


@pytest.mark.parametrize(
    ("job_type", "status"),
    [
        ("generate", "completed"),
        ("generate", "running"),
        ("cover", "queued"),
        ("score", "queued"),
    ],
)
def test_upgrade_keeps_a_job_that_waits_on_no_redis_message_of_the_music_worker(
    reference_link_database, job_type, status,
):
    config, engine = _database_at_previous_revision_holding(
        reference_link_database, job_type, status,
    )

    command.upgrade(config, MIGRATION.revision)

    assert (_revision_of(engine), job_count(engine)) == (MIGRATION.revision, 1)
