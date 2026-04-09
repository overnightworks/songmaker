"""Validate and optionally repair every stored ``generation_params`` JSON column.

Walks ``Version.generation_params``, ``Generation.generation_params`` and
``GenerationPreset.params`` and checks each row against the strict
``BaseGenerationParams`` / ``StoredGenerationParams`` Pydantic models that
landed in the no-silent-fallbacks W2 cleanup.

Modes:

* ``--dry-run`` (default) — report invalid rows, change nothing.
* ``--fix`` — drop unknown keys and write the canonical dump back. Skips rows
  whose remaining content fails validation after the drop, prints them so a
  human can decide what to do.

Run ``--dry-run`` first, review the report, then ``--fix``.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Iterable
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from songmaker_cli.api_models.generation_params import (
    BaseGenerationParams,
    StoredGenerationParams,
)
from songmaker_cli.db.engine import init_db, resolve_database_url
from songmaker_cli.db.models import Generation, GenerationPreset, Version

log = logging.getLogger("migrate_generation_params")


@dataclass
class _Issue:
    table: str
    row_id: str
    error: str


@dataclass
class _Target:
    name: str
    model_cls: type[BaseModel]
    rows: Iterable[tuple[str, dict | None]]


def _drop_unknown_keys(value: dict, model_cls: type[BaseModel]) -> dict:
    allowed = set(model_cls.model_fields.keys())
    return {k: v for k, v in value.items() if k in allowed}


def _check_one(
    table: str, row_id: str, value: dict | None, model_cls: type[BaseModel],
) -> _Issue | None:
    if value is None or value == {}:
        return None
    try:
        model_cls.model_validate(value)
    except ValidationError as exc:
        return _Issue(table=table, row_id=row_id, error=str(exc))
    return None


def _walk(session: Session) -> tuple[list[_Issue], list[_Target]]:
    targets: list[_Target] = [
        _Target(
            name="versions.generation_params",
            model_cls=BaseGenerationParams,
            rows=[
                (row.id, row.generation_params)
                for row in session.query(Version).all()
            ],
        ),
        _Target(
            name="generations.generation_params",
            model_cls=StoredGenerationParams,
            rows=[
                (row.id, row.generation_params)
                for row in session.query(Generation).all()
            ],
        ),
        _Target(
            name="generation_presets.params",
            model_cls=BaseGenerationParams,
            rows=[
                (row.id, row.params) for row in session.query(GenerationPreset).all()
            ],
        ),
    ]
    issues: list[_Issue] = []
    for target in targets:
        for row_id, value in target.rows:
            issue = _check_one(target.name, row_id, value, target.model_cls)
            if issue is not None:
                issues.append(issue)
    return issues, targets


def _fix_target(session: Session, target: _Target) -> tuple[int, list[_Issue]]:
    """Drop unknown keys on rows in this target and re-validate.

    Returns ``(fixed_count, still_broken)``. Rows with no issues are skipped.
    """
    fixed = 0
    still_broken: list[_Issue] = []
    table_name, _, column_name = target.name.partition(".")
    if table_name == "versions":
        model = Version
    elif table_name == "generations":
        model = Generation
    elif table_name == "generation_presets":
        model = GenerationPreset
    else:
        msg = f"unknown table {table_name}"
        raise RuntimeError(msg)

    for row_id, value in target.rows:
        if value is None or value == {}:
            continue
        try:
            target.model_cls.model_validate(value)
            continue
        except ValidationError:
            pass

        cleaned = _drop_unknown_keys(value, target.model_cls)
        try:
            validated = target.model_cls.model_validate(cleaned)
        except ValidationError as exc:
            still_broken.append(_Issue(target.name, row_id, str(exc)))
            continue

        row = session.query(model).filter_by(id=row_id).one()
        setattr(row, column_name, validated.model_dump(exclude_none=True))
        fixed += 1

    return fixed, still_broken


def _print_report(issues: list[_Issue]) -> None:
    if not issues:
        print("All generation_params rows validate cleanly.")
        return
    print(f"Found {len(issues)} invalid rows:")
    for issue in issues:
        print(f"  [{issue.table}] {issue.row_id}")
        for line in issue.error.splitlines()[:3]:
            print(f"      {line}")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fix", action="store_true",
        help="Drop unknown keys and rewrite rows. Without this flag, dry-run only.",
    )
    args = parser.parse_args(argv)

    factory = init_db(resolve_database_url())
    with factory() as session:
        issues, targets = _walk(session)
        _print_report(issues)

        if not args.fix:
            return 0 if not issues else 1

        if not issues:
            return 0

        total_fixed = 0
        unresolved: list[_Issue] = []
        for target in targets:
            fixed, broken = _fix_target(session, target)
            total_fixed += fixed
            unresolved.extend(broken)
        session.commit()

        print(f"\nFixed {total_fixed} rows.")
        if unresolved:
            print(f"\n{len(unresolved)} rows still broken after dropping unknown keys:")
            for issue in unresolved:
                print(f"  [{issue.table}] {issue.row_id}: {issue.error.splitlines()[0]}")
            return 1
        return 0


if __name__ == "__main__":
    sys.exit(main())
