"""The MCP child derives its own full URL; the spec carries only the base."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

from songmaker_cli.cowriter.mcp_spec import songmaker_mcp_server
from songmaker_cli.db.engine import resolve_database_url
from songmaker_cli.settings import get_settings

BASE_URL = "postgresql://app@db:5432/songs"
PASSWORD = "file-password"


@pytest.fixture
def password_file_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "postgres_password").write_text(PASSWORD)
    monkeypatch.setenv("DATABASE_URL", BASE_URL)
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    get_settings.cache_clear()
    settings_class = type(get_settings())
    monkeypatch.setattr(
        settings_class, "model_config", {**settings_class.model_config, "secrets_dir": tmp_path},
    )
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.usefixtures("password_file_settings")
def test_the_child_resolves_the_full_url_while_the_spec_holds_no_password() -> None:
    settings = get_settings()

    resolved = resolve_database_url()
    spec = songmaker_mcp_server(settings.database_url)

    assert make_url(resolved).password == PASSWORD
    carried = {key: value.get_secret_value() for key, value in spec.environment.items()}
    assert carried["DATABASE_URL"] == BASE_URL
    assert PASSWORD not in "".join(carried.values())
