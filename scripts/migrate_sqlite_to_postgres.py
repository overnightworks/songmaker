#!/usr/bin/env python3
"""Migrate all data from a SQLite database to PostgreSQL.

Usage:
    python scripts/migrate_sqlite_to_postgres.py sqlite:///path/to/songmaker.db postgresql://user:pass@host/songmaker

Idempotent: truncates each PostgreSQL table before inserting.
Table order respects foreign key constraints.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from songmaker_cli.db.models import (
    Album,
    AuditLog,
    Base,
    Generation,
    GenerationPreset,
    Job,
    LoginAttempt,
    Rating,
    Score,
    Song,
    User,
    UserSession,
    Version,
)

TABLE_ORDER = [
    User,
    Album,
    Song,
    Version,
    Generation,
    Score,
    Rating,
    GenerationPreset,
    Job,
    UserSession,
    LoginAttempt,
    AuditLog,
]

TRUNCATE_ORDER = list(reversed(TABLE_ORDER))


def _parse_datetime(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    value = value.strip()
    formats = (
        "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S",
    )
    for fmt in formats:
        try:
            dt = datetime.strptime(value, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse datetime: {value!r}")


DATETIME_COLUMNS = {
    "created_at", "updated_at", "started_at", "completed_at",
    "expires_at", "attempted_at", "scored_at", "rated_at",
}


def _row_to_dict(row: object, model: type) -> dict:
    columns = [c.key for c in model.__table__.columns]
    result = {}
    for col in columns:
        value = getattr(row, col)
        if col in DATETIME_COLUMNS and isinstance(value, str):
            value = _parse_datetime(value)
        result[col] = value
    return result


def migrate(sqlite_url: str, pg_url: str) -> None:
    sqlite_engine = create_engine(sqlite_url)
    pg_engine = create_engine(pg_url)

    Base.metadata.create_all(pg_engine)

    SrcSession = sessionmaker(bind=sqlite_engine)
    DstSession = sessionmaker(bind=pg_engine)

    src: Session = SrcSession()
    dst: Session = DstSession()

    try:
        for model in TRUNCATE_ORDER:
            table_name = model.__tablename__
            dst.execute(text(f"TRUNCATE TABLE {table_name} CASCADE"))
        dst.commit()

        total = 0
        for model in TABLE_ORDER:
            table_name = model.__tablename__
            rows = src.query(model).all()
            if not rows:
                print(f"  {table_name}: 0 rows (empty)")
                continue

            for row in rows:
                data = _row_to_dict(row, model)
                dst.execute(model.__table__.insert().values(**data))

            dst.commit()
            print(f"  {table_name}: {len(rows)} rows")
            total += len(rows)

        print(f"\nMigrated {total} rows across {len(TABLE_ORDER)} tables.")

        print("\nValidation:")
        all_ok = True
        for model in TABLE_ORDER:
            table_name = model.__tablename__
            src_count = src.query(model).count()
            dst_count = dst.query(model).count()
            status = "OK" if src_count == dst_count else "MISMATCH"
            if status == "MISMATCH":
                all_ok = False
            print(f"  {table_name}: src={src_count} dst={dst_count} [{status}]")

        if not all_ok:
            print("\nWARNING: Row count mismatches detected!")
            sys.exit(1)
        print("\nAll row counts match.")

    finally:
        src.close()
        dst.close()
        sqlite_engine.dispose()
        pg_engine.dispose()


def main() -> None:
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <sqlite_url> <postgresql_url>")
        print(f"Example: {sys.argv[0]} sqlite:///data/songmaker.db postgresql://user:pass@localhost/songmaker")
        sys.exit(1)

    sqlite_url = sys.argv[1]
    pg_url = sys.argv[2]

    if not sqlite_url.startswith("sqlite"):
        print(f"Error: first argument must be a SQLite URL, got: {sqlite_url}")
        sys.exit(1)

    if not pg_url.startswith("postgresql"):
        print(f"Error: second argument must be a PostgreSQL URL, got: {pg_url}")
        sys.exit(1)

    print(f"Migrating from {sqlite_url}")
    print(f"           to   {pg_url.split('@')[-1] if '@' in pg_url else pg_url}")
    print()

    migrate(sqlite_url, pg_url)


if __name__ == "__main__":
    main()
