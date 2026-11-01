"""Databases and the seed-then-upgrade arrangement of the reference-link migration tests."""

from __future__ import annotations

import importlib
import os
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa
from alembic.config import Config
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import URL, Engine, make_url
from support.migration_chain import seeded_then_upgraded

RECORDING_COLUMN = "reference_recording_id"
RECORDING_PATH = "u1/refs/a.wav"


@dataclass(frozen=True)
class LinkCase:
    """One table whose rows a migration links to their reference recording."""

    table: str
    migration_module: str
    previous_revision: str
    failing_id: str
    seed: Callable[..., None]
    link_statement: str
    link_values: Mapping[str, object]

    @property
    def migration(self) -> ModuleType:
        return importlib.import_module(self.migration_module)


def _config_for(url: URL) -> Config:
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    config.set_main_option(
        "sqlalchemy.url",
        url.render_as_string(hide_password=False).replace("%", "%%"),
    )
    return config


@pytest.fixture
def reference_link_sqlite(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'reference-link.db'}")
    # Alembic's engine does not enable foreign keys; this connection does, as init_test_db does.
    event.listen(
        engine,
        "connect",
        lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
    )
    yield _config_for(engine.url), engine
    engine.dispose()


@pytest.fixture
def reference_link_postgresql():
    base_url = os.environ.get("TEST_DATABASE_URL", "")
    if not base_url.startswith("postgresql"):
        pytest.skip("TEST_DATABASE_URL not set to PostgreSQL")
    schema = "reference_link_" + uuid.uuid4().hex
    admin = create_engine(base_url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    url = make_url(base_url).update_query_dict({"options": f"-csearch_path={schema}"})
    engine = create_engine(url)
    yield _config_for(url), engine
    engine.dispose()
    with admin.begin() as connection:
        connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    admin.dispose()


@pytest.fixture(params=["reference_link_sqlite", "reference_link_postgresql"])
def reference_link_database(request, isolated_logging) -> tuple[Config, Engine]:
    """Yield (config, engine) of an empty database."""
    return request.getfixturevalue(request.param)


def execute(engine: Engine, statement: str, **values: object) -> None:
    json_values = {key for key, value in values.items() if isinstance(value, dict)}
    prepared = text(statement).bindparams(
        *(sa.bindparam(key, type_=sa.JSON(none_as_null=True)) for key in json_values)
    )
    with engine.begin() as connection:
        connection.execute(prepared, values)


def seed_users(engine: Engine) -> None:
    for user in ("u1", "u2"):
        execute(
            engine,
            "INSERT INTO users (id, username, role, created_at, updated_at) "
            "VALUES (:id, :id, 'user', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            id=user,
        )


def upgraded_after_seeding(
    database: tuple[Config, Engine],
    case: LinkCase,
    **seed: object,
) -> Engine:
    """Seed the world at the previous revision, then upgrade to the case's migration."""
    return seeded_then_upgraded(
        database,
        case.previous_revision,
        case.migration.revision,
        lambda engine: case.seed(engine, **seed),
    )
