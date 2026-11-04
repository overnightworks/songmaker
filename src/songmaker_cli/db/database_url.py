"""The one owner that derives the database connection URL.

Imports no ``Settings`` at run time: alembic's ``env.py`` uses it too and must
not need the application configuration. ``Settings`` cannot own the derivation
because the layer contract keeps ``settings`` below ``db``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.engine import URL, make_url

if TYPE_CHECKING:
    from songmaker_cli.settings import Settings


def database_url_with_password(base_url: str, password: str | None) -> URL:
    """Return ``base_url`` as a ``URL``, with ``password`` set when one is given.

    The password is set on the ``URL`` object, so it needs no escaping, and it
    is never part of an error message.
    """
    url = make_url(base_url)
    if password is None:
        return url
    if url.password is not None:
        raise ValueError(
            "DATABASE_URL already carries a password and the postgres_password "
            "secret is also set; keep the password in one place only",
        )
    return url.set(password=password)


def connection_url_from_settings(settings: Settings) -> URL:
    """Return the full connection URL for ``settings``: its base plus its password secret."""
    password = settings.postgres_password
    return database_url_with_password(
        settings.database_url, password.get_secret_value() if password else None,
    )
