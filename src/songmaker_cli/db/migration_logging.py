"""Logging configuration owned by the Alembic migration process."""

from __future__ import annotations

import logging


class _MigrationLogHandler(logging.StreamHandler):
    pass


def configure_migration_logging() -> None:
    handler = _MigrationLogHandler()
    handler.setFormatter(logging.Formatter("%(levelname)-5.5s [%(name)s] %(message)s"))
    root = logging.getLogger()
    for existing_handler in root.handlers[:]:
        if isinstance(existing_handler, _MigrationLogHandler):
            root.removeHandler(existing_handler)
            existing_handler.close()
    root.addHandler(handler)
    root.setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("alembic").setLevel(logging.INFO)
