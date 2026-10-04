"""The reset-password escape hatch of the local CLI."""

from __future__ import annotations

from pathlib import Path

import pytest
from webauth.passwords import hash_password, verify_password

from songmaker_cli.db.engine import init_test_db
from songmaker_cli.db.models import User
from songmaker_cli.main import app

USERNAME = "alice"
OLD_PASSWORD_HASH = hash_password("old-Passw0rd")


@pytest.fixture
def local_db(tmp_path: Path, monkeypatch):
    factory = init_test_db(tmp_path / "songmaker.db")
    with factory() as session:
        session.add(User(username=USERNAME, password_hash=OLD_PASSWORD_HASH, role="admin"))
        session.commit()
    monkeypatch.setattr("songmaker_cli.db.engine.resolve_database_url", lambda: "sqlite://")
    monkeypatch.setattr("songmaker_cli.db.engine.init_db", lambda _url: factory)
    return factory


def _stored_hash(factory) -> str:
    with factory() as session:
        return session.query(User).filter_by(username=USERNAME).one().password_hash


def test_reset_password_stores_the_new_password(local_db, capsys) -> None:
    app(["reset-password", USERNAME, "fresh-Passw0rd"], result_action="return_value")

    assert verify_password("fresh-Passw0rd", _stored_hash(local_db))
    assert capsys.readouterr().out == f"Password reset for '{USERNAME}' (role=admin)\n"


@pytest.mark.parametrize(
    "password, message",
    [
        ("Ab1!xyz", "Error: password is too short (see --help for the minimum)"),
        ("password123", "Error: Password is too common — choose something less predictable"),
        ("aaaabbbb", "Error: Password must contain at least 4 unique characters"),
    ],
)
def test_reset_password_refuses_a_weak_password_without_echoing_it(
    local_db, capsys, password: str, message: str,
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        app(["reset-password", USERNAME, password], result_action="return_value")

    output = capsys.readouterr().out
    assert exit_info.value.code == 1
    assert output == f"{message}\n"
    assert password not in output
    assert _stored_hash(local_db) == OLD_PASSWORD_HASH
