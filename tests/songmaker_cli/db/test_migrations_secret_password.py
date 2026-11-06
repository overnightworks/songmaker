"""Alembic receives a password kept apart from the base URL, whatever it contains."""

from __future__ import annotations

import runpy
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from songmaker_cli import settings as settings_module
from songmaker_cli.db import database_url as database_url_module
from songmaker_cli.db import engine as engine_module
from songmaker_cli.db.database_url import (
    POSTGRESQL_PSYCOPG2_DRIVERNAME,
    database_url_with_password,
    password_from_secret_file,
)

ENV_SCRIPT = Path(engine_module.MIGRATIONS_DIR) / "env.py"
PASSWORD_WITH_SPECIALS = "p%a@s/s:w ord"


def test_run_migrations_hands_alembic_a_password_with_a_percent_sign_intact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = database_url_with_password("postgresql://app@db/songs", PASSWORD_WITH_SPECIALS)
    handed_over: list[Config] = []
    monkeypatch.setattr(
        engine_module, "create_engine", lambda _url: create_engine("sqlite://"),
    )
    monkeypatch.setattr("alembic.command.upgrade", lambda cfg, _revision: handed_over.append(cfg))

    engine_module._run_migrations(url)

    (cfg,) = handed_over
    assert make_url(cfg.get_main_option("sqlalchemy.url")).password == PASSWORD_WITH_SPECIALS


def _url_alembic_configures(monkeypatch: pytest.MonkeyPatch) -> str:
    """Run alembic's env.py offline and return the URL it configures."""
    configured: dict[str, str] = {}

    @contextmanager
    def no_transaction():
        yield

    fake_context = SimpleNamespace(
        config=Config(),
        is_offline_mode=lambda: True,
        configure=lambda **kwargs: configured.update(kwargs),
        begin_transaction=no_transaction,
        run_migrations=lambda: None,
    )
    monkeypatch.setattr("alembic.context", fake_context)
    runpy.run_path(str(ENV_SCRIPT))
    return configured["url"]


def _mount_secrets_at(monkeypatch: pytest.MonkeyPatch, directory: Path) -> None:
    monkeypatch.setattr(
        database_url_module,
        "password_from_secret_file",
        lambda: password_from_secret_file(directory),
    )


def test_env_py_joins_the_environment_url_and_the_password_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / settings_module.DATABASE_PASSWORD_SECRET_FILE).write_text(PASSWORD_WITH_SPECIALS)
    _mount_secrets_at(monkeypatch, tmp_path)
    monkeypatch.setenv("DATABASE_URL", "postgresql://app@db/songs")

    url = make_url(_url_alembic_configures(monkeypatch))

    assert url.password == PASSWORD_WITH_SPECIALS


def test_env_py_uses_the_environment_url_alone_without_a_password_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mount_secrets_at(monkeypatch, tmp_path / "absent")
    monkeypatch.setenv("DATABASE_URL", "postgresql://app:today@db/songs")

    assert _url_alembic_configures(monkeypatch) == (
        f"{POSTGRESQL_PSYCOPG2_DRIVERNAME}://app:today@db/songs"
    )
