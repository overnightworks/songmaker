"""The one owner that derives the database connection URL.

Constructs no ``Settings``: alembic's ``env.py`` uses it too and must not need
the application configuration; it reads only the secret-file location constants
and the password its caller hands it.
``Settings`` cannot own the derivation because the layer contract keeps
``settings`` below ``db``.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Final

from sqlalchemy.engine import URL, make_url

from songmaker_cli.settings import DATABASE_PASSWORD_SECRET_FILE, SECRETS_DIRECTORY

if TYPE_CHECKING:
    from songmaker_cli.settings import Settings

BARE_POSTGRESQL_DRIVERNAME: Final = "postgresql"
# SQLAlchemy 2.1 reads a bare ``postgresql://`` as psycopg 3, which is not installed.
POSTGRESQL_PSYCOPG2_DRIVERNAME: Final = "postgresql+psycopg2"


def database_url_with_password(base_url: URL | str, password: str | None) -> URL:
    """Return ``base_url`` as a ``URL``, with ``password`` set when one is given.

    A bare ``postgresql`` URL names the psycopg2 driver; any other driver stays.
    The password is set on the ``URL`` object, so it needs no escaping, and it
    is never part of an error message.
    """
    url = make_url(base_url)
    if url.drivername == BARE_POSTGRESQL_DRIVERNAME:
        url = url.set(drivername=POSTGRESQL_PSYCOPG2_DRIVERNAME)
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


def password_from_secret_file(directory: Path = SECRETS_DIRECTORY) -> str | None:
    """Return the password stored in ``directory``'s secret file, or ``None`` when none is mounted.

    An empty file is refused, naming the path and never a value.
    """
    path = directory / DATABASE_PASSWORD_SECRET_FILE
    if not path.is_file():
        return None
    password = path.read_text().strip()
    if not password:
        raise RuntimeError(f"{path} is empty")
    return password


def database_url_from_environment(
    base_url: str,
    variable_password: str | None,
) -> URL:
    """Return ``base_url`` joined with the password, as ``env.py`` needs it.

    ``variable_password`` (``POSTGRES_PASSWORD``, read by the caller) wins over the
    secret file, as ``Settings.postgres_password`` does for the app. ``Settings``
    cannot be built here: it also requires ``REDIS_URL``, ``SESSION_SECRET`` and
    ``SONGMAKER_INTERNAL_TOKEN``, which a hand-run alembic does not have.
    """
    if variable_password == "":
        raise RuntimeError("POSTGRES_PASSWORD is empty")
    if variable_password is None:
        variable_password = password_from_secret_file()
    return database_url_with_password(base_url, variable_password)
