"""The one owner that derives the connection URL from a base and a separate password."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

from songmaker_cli.db.database_url import (
    POSTGRESQL_PSYCOPG2_DRIVERNAME,
    database_url_with_password,
    password_from_secret_file,
)
from songmaker_cli.settings import DATABASE_PASSWORD_SECRET_FILE

PASSWORD_WITH_SPECIALS = "p%a@s/s:w ord"


def test_a_base_with_its_own_password_comes_back_unchanged_when_no_password_file_is_given() -> None:
    url = database_url_with_password("postgresql://app:today@db:5432/songs", None)

    assert url.render_as_string(hide_password=False) == (
        f"{POSTGRESQL_PSYCOPG2_DRIVERNAME}://app:today@db:5432/songs"
    )


def test_a_given_password_joins_a_password_less_base() -> None:
    url = database_url_with_password("postgresql://app@db:5432/songs", "apart")

    assert url.password == "apart"
    assert url.username == "app"
    assert url.render_as_string(hide_password=False) == (
        f"{POSTGRESQL_PSYCOPG2_DRIVERNAME}://app:apart@db:5432/songs"
    )


@pytest.mark.parametrize("password", [None, "apart"])
def test_a_bare_postgresql_base_gets_the_named_driver(password: str | None) -> None:
    url = database_url_with_password("postgresql://app@db/songs", password)

    assert url.drivername == POSTGRESQL_PSYCOPG2_DRIVERNAME


@pytest.mark.parametrize("base_url", [
    "postgresql+asyncpg://app@db/songs",
    "postgresql+psycopg://app@db/songs",
    "sqlite:///songs.db",
])
@pytest.mark.parametrize("password", [None, "apart"])
def test_a_base_that_names_another_driver_keeps_it(base_url: str, password: str | None) -> None:
    url = database_url_with_password(base_url, password)

    assert url.drivername == make_url(base_url).drivername


def test_a_password_with_url_special_characters_round_trips() -> None:
    url = database_url_with_password("postgresql://app@db/songs", PASSWORD_WITH_SPECIALS)

    assert url.password == PASSWORD_WITH_SPECIALS
    assert url.host == "db"
    assert url.database == "songs"


def test_a_base_with_a_password_and_a_given_password_is_refused_without_showing_either() -> None:
    with pytest.raises(ValueError, match="DATABASE_URL") as refusal:
        database_url_with_password("postgresql://app:inline-secret@db/songs", "apart-secret")

    message = str(refusal.value)
    assert "postgres_password" in message
    assert "inline-secret" not in message
    assert "apart-secret" not in message


def test_no_secret_file_gives_no_password(tmp_path: Path) -> None:
    assert password_from_secret_file(tmp_path) is None


def test_a_secret_file_password_is_stripped_of_surrounding_whitespace(tmp_path: Path) -> None:
    (tmp_path / DATABASE_PASSWORD_SECRET_FILE).write_text("  apart\n")

    assert password_from_secret_file(tmp_path) == "apart"


@pytest.mark.parametrize("content", ["", " \n\t "])
def test_an_empty_secret_file_is_refused_naming_the_path(tmp_path: Path, content: str) -> None:
    secret_file = tmp_path / DATABASE_PASSWORD_SECRET_FILE
    secret_file.write_text(content)

    with pytest.raises(RuntimeError, match="is empty") as raised:
        password_from_secret_file(tmp_path)

    assert str(secret_file) in str(raised.value)
