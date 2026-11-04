"""The one owner that derives the connection URL from a base and a separate password."""

from __future__ import annotations

import pytest

from songmaker_cli.db.database_url import database_url_with_password

PASSWORD_WITH_SPECIALS = "p%a@s/s:w ord"


def test_a_base_without_a_password_part_comes_back_unchanged_when_no_password_is_given() -> None:
    url = database_url_with_password("postgresql://app:today@db:5432/songs", None)

    assert url.render_as_string(hide_password=False) == "postgresql://app:today@db:5432/songs"


def test_a_given_password_joins_a_password_less_base() -> None:
    url = database_url_with_password("postgresql://app@db:5432/songs", "apart")

    assert url.password == "apart"
    assert url.username == "app"
    assert url.render_as_string(hide_password=False) == "postgresql://app:apart@db:5432/songs"


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
