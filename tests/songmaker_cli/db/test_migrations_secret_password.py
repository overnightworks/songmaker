"""Alembic receives a password kept apart from the base URL, whatever it contains."""

from __future__ import annotations

import os
import runpy
import uuid
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from songmaker_cli import settings as settings_module
from songmaker_cli.db import engine as engine_module
from songmaker_cli.db.database_url import database_url_with_password

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


def test_env_py_joins_the_environment_url_and_the_password_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / settings_module.DATABASE_PASSWORD_SECRET_FILE).write_text(PASSWORD_WITH_SPECIALS)
    monkeypatch.setattr(settings_module, "SECRETS_DIRECTORY", tmp_path)
    monkeypatch.setenv("DATABASE_URL", "postgresql://app@db/songs")

    url = make_url(_url_alembic_configures(monkeypatch))

    assert url.password == PASSWORD_WITH_SPECIALS


def test_env_py_uses_the_environment_url_alone_without_a_password_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings_module, "SECRETS_DIRECTORY", tmp_path / "absent")
    monkeypatch.setenv("DATABASE_URL", "postgresql://app:today@db/songs")

    assert _url_alembic_configures(monkeypatch) == "postgresql://app:today@db/songs"


def test_init_db_connects_to_postgresql_with_the_password_kept_apart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    full_url = os.environ.get("TEST_DATABASE_URL", "")
    if not full_url.startswith("postgresql"):
        pytest.skip("TEST_DATABASE_URL not set to PostgreSQL")
    parsed = make_url(full_url)
    schema = "secret_password_" + uuid.uuid4().hex
    admin = create_engine(full_url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    base = parsed.set(password=None).update_query_dict({"options": f"-csearch_path={schema}"})
    try:
        factory = engine_module.init_db(
            database_url_with_password(
                base.render_as_string(hide_password=False), parsed.password,
            ),
        )
        assert "albums" in inspect(factory.kw["bind"]).get_table_names(schema=schema)
        factory.kw["bind"].dispose()
    finally:
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
