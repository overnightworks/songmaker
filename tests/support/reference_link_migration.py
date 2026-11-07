"""Databases and the seed-then-upgrade arrangement of the reference-link migration tests."""

from __future__ import annotations

import importlib
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, Engine
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
def reference_link_database(
    empty_postgresql_url, isolated_logging,
) -> Iterator[tuple[Config, Engine]]:
    """Yield (config, engine) of an empty database."""
    engine = create_engine(empty_postgresql_url)
    yield _config_for(empty_postgresql_url), engine
    engine.dispose()


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
