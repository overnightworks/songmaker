"""The users.id foreign keys follow a changed users.id on PostgreSQL."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, inspect, select, text
from sqlalchemy.engine import make_url

from songmaker_cli.db.migrations.versions import (
    a7c3e9d1b5f2_users_fk_on_update_cascade as migration,
)
from songmaker_cli.db.models import Base

OLD_ID = "user-before"
NEW_ID = "user-after"


@pytest.fixture
def schema_url():
    url = os.environ.get("TEST_DATABASE_URL", "")
    if not url.startswith("postgresql"):
        pytest.skip("TEST_DATABASE_URL not set to PostgreSQL")
    admin = create_engine(url)
    schema = "users_fk_" + uuid.uuid4().hex
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        yield make_url(url).update_query_dict({"options": f"-csearch_path={schema}"})
    finally:
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def _config(url) -> Config:
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    rendered = url.render_as_string(hide_password=False)
    config.set_main_option("sqlalchemy.url", rendered.replace("%", "%%"))
    return config


def _user_foreign_keys(engine: Engine) -> dict[tuple[str, str], tuple[str, str | None, str | None]]:
    inspector = inspect(engine)
    return {
        (table, foreign_key["constrained_columns"][0]): (
            foreign_key["name"],
            foreign_key["options"].get("ondelete"),
            foreign_key["options"].get("onupdate"),
        )
        for table in inspector.get_table_names()
        for foreign_key in inspector.get_foreign_keys(table)
        if foreign_key["referred_table"] == "users"
    }


def _seed_rows_referencing(engine: Engine, user_id: str) -> None:
    tables = Base.metadata.tables
    with engine.begin() as connection:
        connection.execute(tables["users"].insert().values(
            id=user_id, username="mover", password_hash="hash",
        ))
        connection.execute(tables["albums"].insert().values(
            id="album-1", title="A", artist="X", created_by=user_id,
        ))
        connection.execute(tables["songs"].insert().values(
            id="song-1", title="S", album_id="album-1",
        ))
        generation = {"id": "generation-1", "song_id": "song-1", "mp3_path": "a.mp3"}
        connection.execute(tables["generations"].insert().values(
            **generation, created_by=user_id,
        ))
        referencing = {
            "user_song_work": {"user_id": user_id, "song_id": "song-1"},
            "playlists": {"title": "P", "created_by": user_id},
            "generation_presets": {
                "name": "G", "model_mode": "turbo", "created_by": user_id,
            },
            "jobs": {"type": "generate", "user_id": user_id},
            "resource_event_cursors": {"user_id": user_id},
            "resource_events": {
                "user_id": user_id, "sequence": 1, "kind": "k",
                "resource_type": "song", "resource_id": "song-1",
                "generation_id": "generation-1",
            },
            "user_sessions": {"user_id": user_id, "expires_at": "2099-01-01"},
            "rate_limit_settings": {
                "user_id": user_id, "setting_key": "k", "value": 1,
            },
            "conversations": {"user_id": user_id},
            "cowriter_user_memories": {"user_id": user_id},
            "user_loras": {"user_id": user_id, "name": "L", "slug": "l"},
            "audit_log": {"user_id": user_id, "action": "a", "resource_type": "r"},
        }
        for table, values in referencing.items():
            connection.execute(tables[table].insert().values(**values))


def _owner_of_every_user_row(engine: Engine) -> dict[str, str | None]:
    owners: dict[str, str | None] = {}
    with engine.connect() as connection:
        for (table, column) in _user_foreign_keys(engine):
            owners[f"{table}.{column}"] = connection.execute(
                text(f'SELECT "{column}" FROM "{table}"'),
            ).scalar_one()
    return owners


def test_upgrade_adds_on_update_cascade_and_downgrade_restores_old_constraints(schema_url):
    config = _config(schema_url)
    command.upgrade(config, migration.down_revision)
    engine = create_engine(schema_url)
    before = _user_foreign_keys(engine)

    command.upgrade(config, migration.revision)
    after = _user_foreign_keys(engine)
    command.downgrade(config, migration.down_revision)
    restored = _user_foreign_keys(engine)
    engine.dispose()

    assert len(before) == len(migration.USER_FOREIGN_KEYS)
    assert {key: (name, ondelete) for key, (name, ondelete, _) in after.items()} == {
        key: (name, ondelete) for key, (name, ondelete, _) in before.items()
    }
    assert {onupdate for _, _, onupdate in after.values()} == {"CASCADE"}
    assert restored == before


def test_changing_users_id_moves_every_referencing_row(schema_url):
    config = _config(schema_url)
    command.upgrade(config, migration.revision)
    engine = create_engine(schema_url)
    _seed_rows_referencing(engine, OLD_ID)

    with engine.begin() as connection:
        connection.execute(
            text("UPDATE users SET id = :new WHERE id = :old"),
            {"new": NEW_ID, "old": OLD_ID},
        )
    owners = _owner_of_every_user_row(engine)
    with engine.connect() as connection:
        remaining = connection.execute(select(Base.metadata.tables["users"].c.id)).scalars().all()
    engine.dispose()

    assert remaining == [NEW_ID]
    assert len(owners) == len(migration.USER_FOREIGN_KEYS)
    assert set(owners.values()) == {NEW_ID}
