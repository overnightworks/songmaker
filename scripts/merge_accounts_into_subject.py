# ruff: noqa: E402
"""Fold every account into the operator's one Keycloak subject (one-shot).

Writers are stopped and the paired backup (``scripts/backup.sh``) is taken
before the run. Run inside the web container, where ``DATABASE_URL`` is set,
with the venv's Python:

    docker compose run --rm --no-deps --entrypoint /app/.venv/bin/python \
        songmaker-web scripts/merge_accounts_into_subject.py \
        --from <operator-old-id> --subject <S> [--apply]

* no flag: dry run. Counts per owner column and account, the planned file
  moves and path rewrites, and every refusal. Writes nothing.
* ``--apply``: refusals again, then the files move, then one database
  transaction, then the queue-stream cache is cleared, then V1-V5 run.

Any refusal, error or failed check means ``scripts/restore.sh <backup>``;
there is no resume. The script runs before the sign-in migration drops the
password columns, so it reads the live schema by reflection rather than the
current models. It reads and writes through SQLAlchemy Core so soft-deleted
rows are included. It never prints a password hash.
"""

from __future__ import annotations

import argparse
import os
import secrets
import shutil
import sys
import uuid
from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Final

from _repo_path import prepend_own_checkout_src
from sqlalchemy import (
    JSON,
    Column,
    Engine,
    MetaData,
    String,
    Text,
    cast,
    delete,
    func,
    insert,
    or_,
    select,
    update,
)
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError

prepend_own_checkout_src(__file__)

from songmaker_cli.config import find_project_root
from songmaker_cli.constants import JOB_ACTIVE_STATUSES, ROLE_ADMIN, USER_LORAS_DIRNAME
from songmaker_cli.db.engine import connect_db, resolve_database_url
from songmaker_cli.queue_streams import QUEUE_STREAM_DIRNAME
from songmaker_cli.settings import get_settings
from songmaker_cli.timestamps import utcnow

RESTORE_HINT: Final = "Restore with scripts/restore.sh <backup>; there is no resume."
USERS_ID_TARGET: Final = "users.id"
# The users columns the sign-in migration drops; the folded account copies one of them.
PASSWORD_ERA_USER_COLUMNS: Final = ("password_hash", "is_active")
NO_OWNER: Final = None


class Mode(StrEnum):
    DRY_RUN = "dry-run"
    APPLY = "apply"


class OwnerPolicy(StrEnum):
    REPOINT_ALL = "repoint-all"
    OPERATOR_ONLY = "operator-only"
    DELETE_ALL = "delete-all"


# Every foreign key to users.id needs a line here; a column without one refuses.
OWNER_POLICIES: Final[dict[str, OwnerPolicy]] = {
    "albums.created_by": OwnerPolicy.REPOINT_ALL,
    "generations.created_by": OwnerPolicy.REPOINT_ALL,
    "playlists.created_by": OwnerPolicy.REPOINT_ALL,
    "jobs.user_id": OwnerPolicy.REPOINT_ALL,
    "audit_log.user_id": OwnerPolicy.REPOINT_ALL,
    "generation_presets.created_by": OwnerPolicy.REPOINT_ALL,
    "user_loras.user_id": OwnerPolicy.REPOINT_ALL,
    "conversations.user_id": OwnerPolicy.REPOINT_ALL,
    "user_song_work.user_id": OwnerPolicy.OPERATOR_ONLY,
    "cowriter_user_memories.user_id": OwnerPolicy.OPERATOR_ONLY,
    "resource_event_cursors.user_id": OwnerPolicy.OPERATOR_ONLY,
    "resource_events.user_id": OwnerPolicy.OPERATOR_ONLY,
    "rate_limit_settings.user_id": OwnerPolicy.OPERATOR_ONLY,
    "user_sessions.user_id": OwnerPolicy.DELETE_ALL,
}


@dataclass(frozen=True)
class PathColumn:
    label: str
    namespace: str
    holds_json: bool = False
    is_directory: bool = False


LORA_NAMESPACE: Final = f"{USER_LORAS_DIRNAME}/"
PATH_COLUMNS: Final = (
    PathColumn("generations.mp3_path", ""),
    PathColumn("generations.wav_path", ""),
    PathColumn("versions.generation_params", "", holds_json=True),
    PathColumn("generations.generation_params", "", holds_json=True),
    PathColumn("generation_presets.params", "", holds_json=True),
    PathColumn("user_loras.storage_path", LORA_NAMESPACE, is_directory=True),
    PathColumn("user_loras.tensor_path", LORA_NAMESPACE),
    PathColumn("user_lora_samples.audio_path", LORA_NAMESPACE),
)
ACCOUNT_NAMESPACES: Final = ("", LORA_NAMESPACE)

# History text that deliberately keeps the old ids.
HISTORY_COLUMNS: Final = frozenset({
    "audit_log.resource_id",
    "audit_log.detail",
    "chat_messages.content",
    "conversation_summaries.summary_text",
    "jobs.error",
    "jobs.queue_reason",
    "login_attempts.username",
})


@dataclass(frozen=True)
class FileMove:
    source: Path
    destination: Path


@dataclass(frozen=True)
class PathChange:
    old: str
    new: str


@dataclass(frozen=True)
class PathRewrite:
    column: PathColumn
    key: str
    value: str | dict
    changes: tuple[PathChange, ...]


@dataclass(frozen=True)
class TreeSize:
    files: int = 0
    size_bytes: int = 0


@dataclass
class Plan:
    old_ids: tuple[str, ...]
    refusals: list[str] = field(default_factory=list)
    owner_counts: dict[str, Counter] = field(default_factory=dict)
    expected_row_counts: dict[str, int] = field(default_factory=dict)
    moves: list[FileMove] = field(default_factory=list)
    rewrites: list[PathRewrite] = field(default_factory=list)
    missing_before: frozenset[str] = frozenset()
    tree_before: TreeSize = TreeSize()


@dataclass(frozen=True)
class CheckResult:
    name: str
    problems: list[str]
    note: str = ""


def _label(column: Column) -> str:
    return f"{column.table.name}.{column.name}"


def _column(metadata: MetaData, label: str) -> Column:
    table_name, _, column_name = label.partition(".")
    return metadata.tables[table_name].c[column_name]


def owner_columns(metadata: MetaData) -> list[Column]:
    return [
        foreign_key.parent
        for table in metadata.sorted_tables
        for foreign_key in table.foreign_keys
        if foreign_key.target_fullname == USERS_ID_TARGET
    ]


def _account_root(audio_dir: Path, namespace: str, account_id: str) -> Path:
    return audio_dir / f"{namespace}{account_id}"


def _account_roots(audio_dir: Path, account_ids: tuple[str, ...]) -> list[Path]:
    return [
        _account_root(audio_dir, namespace, account_id)
        for account_id in account_ids
        for namespace in ACCOUNT_NAMESPACES
    ]


def _tree_size(roots: list[Path]) -> TreeSize:
    files = 0
    size_bytes = 0
    for root in roots:
        for directory, _, names in os.walk(root):
            for name in names:
                files += 1
                size_bytes += (Path(directory) / name).lstat().st_size
    return TreeSize(files=files, size_bytes=size_bytes)


def _is_lowercase_uuid(value: str) -> bool:
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False


def _structural_refusals(
    metadata: MetaData, account_ids: set[str], operator_id: str, subject: str,
) -> list[str]:
    refusals = [
        f"foreign key {_label(column)} to users.id has no policy"
        for column in owner_columns(metadata)
        if _label(column) not in OWNER_POLICIES
    ]
    refusals += [
        f"users.{name} is gone: the sign-in migration already ran, and this script runs before it"
        for name in PASSWORD_ERA_USER_COLUMNS
        if name not in metadata.tables["users"].c
    ]
    if not _is_lowercase_uuid(subject):
        refusals.append(f"subject {subject!r} is not a lowercase 36-character UUID")
    if subject in account_ids:
        refusals.append(f"subject {subject} equals an existing user id")
    if operator_id not in account_ids:
        refusals.append(f"--from {operator_id} is unknown")
    return refusals


def _data_refusals(conn: Connection, metadata: MetaData) -> list[str]:
    jobs = metadata.tables["jobs"]
    active_jobs = conn.execute(
        select(func.count()).select_from(jobs)
        .where(jobs.c.status.in_([status.value for status in JOB_ACTIVE_STATUSES])),
    ).scalar_one()
    refusals = [f"{active_jobs} job(s) are queued or running"] if active_jobs else []
    slug = metadata.tables["user_loras"].c.slug
    refusals += [
        f"LoRA slug {name!r} is used by several accounts"
        for name, in conn.execute(
            select(slug).group_by(slug).having(func.count() > 1),
        )
    ]
    return refusals


def _plan_file_moves(
    audio_dir: Path, old_ids: tuple[str, ...], subject: str,
) -> tuple[list[FileMove], list[str]]:
    moves: list[FileMove] = []
    refusals: list[str] = []
    for old_id in old_ids:
        for namespace in ACCOUNT_NAMESPACES:
            root = _account_root(audio_dir, namespace, old_id)
            new_root = _account_root(audio_dir, namespace, subject)
            if root.is_symlink() or (root.exists() and not root.is_dir()):
                refusals.append(f"{root} is not a plain directory")
                continue
            for directory, directory_names, file_names in os.walk(root):
                directory_names.sort()
                for name in (*directory_names, *sorted(file_names)):
                    entry = Path(directory) / name
                    if entry.is_symlink() or not (entry.is_dir() or entry.is_file()):
                        refusals.append(
                            f"{entry} is a symlink or not a regular file; if it sits in a "
                            "LoRA dataset it is an artefact to clear through the LoRA "
                            "owner, then retry",
                        )
                    elif entry.is_file():
                        moves.append(FileMove(
                            entry, new_root / entry.relative_to(root),
                        ))
    destinations = Counter(move.destination for move in moves)
    for destination, uses in sorted(destinations.items()):
        if os.path.lexists(destination):
            refusals.append(f"target {destination} already exists")
        if uses > 1:
            refusals.append(f"target {destination} is wanted by {uses} files")
    return moves, refusals


def _resolves(path: Path, is_directory: bool) -> bool:
    return path.is_dir() if is_directory else path.is_file()


def _rewritten(value: str, namespace: str, old_ids: tuple[str, ...], subject: str) -> str | None:
    for old_id in old_ids:
        prefix = f"{namespace}{old_id}/"
        if value.startswith(prefix):
            return f"{namespace}{subject}/{value[len(prefix):]}"
    return None


def _plan_rewrites(
    conn: Connection, metadata: MetaData, old_ids: tuple[str, ...], subject: str,
) -> list[PathRewrite]:
    rewrites: list[PathRewrite] = []
    for path_column in PATH_COLUMNS:
        column = _column(metadata, path_column.label)
        for key, value in conn.execute(select(column.table.c.id, column)):
            texts = value if path_column.holds_json and isinstance(value, dict) else {"": value}
            changes: dict[str, PathChange] = {}
            for field_name, text_value in texts.items():
                if isinstance(text_value, str):
                    new = _rewritten(text_value, path_column.namespace, old_ids, subject)
                    if new is not None:
                        changes[field_name] = PathChange(text_value, new)
            if changes:
                new_value = (
                    {name: changes[name].new if name in changes else item
                     for name, item in texts.items()}
                    if path_column.holds_json else changes[""].new
                )
                rewrites.append(
                    PathRewrite(path_column, key, new_value, tuple(changes.values())),
                )
    return rewrites


def _expected_row_counts(
    row_counts: dict[str, int], owner_counts: dict[str, Counter], operator_id: str,
) -> dict[str, int]:
    expected = dict(row_counts)
    expected["users"] = 1
    for label, policy in OWNER_POLICIES.items():
        table_name = label.partition(".")[0]
        counts = owner_counts[label]
        if policy is OwnerPolicy.DELETE_ALL:
            expected[table_name] = 0
        elif policy is OwnerPolicy.OPERATOR_ONLY:
            others = sum(
                count for owner, count in counts.items()
                if owner not in {operator_id, NO_OWNER}
            )
            expected[table_name] -= others
    return expected


def build_plan(
    conn: Connection, metadata: MetaData, audio_dir: Path, operator_id: str, subject: str,
) -> Plan:
    users = metadata.tables["users"]
    old_ids = tuple(sorted(conn.execute(select(users.c.id)).scalars()))
    plan = Plan(old_ids=old_ids)
    plan.refusals = _structural_refusals(metadata, set(old_ids), operator_id, subject)
    if plan.refusals:
        return plan
    plan.refusals = _data_refusals(conn, metadata)
    plan.moves, move_refusals = _plan_file_moves(audio_dir, old_ids, subject)
    plan.refusals += move_refusals
    row_counts = {
        table.name: conn.execute(select(func.count()).select_from(table)).scalar_one()
        for table in metadata.sorted_tables
    }
    for column in owner_columns(metadata):
        plan.owner_counts[_label(column)] = Counter(dict(
            conn.execute(select(column, func.count()).group_by(column)).all(),
        ))
    plan.expected_row_counts = _expected_row_counts(
        row_counts, plan.owner_counts, operator_id,
    )
    plan.rewrites = _plan_rewrites(conn, metadata, old_ids, subject)
    plan.missing_before = frozenset(
        change.new
        for rewrite in plan.rewrites for change in rewrite.changes
        if not _resolves(audio_dir / change.old, rewrite.column.is_directory)
    )
    plan.tree_before = _tree_size(
        [root for root in _account_roots(audio_dir, (*old_ids, subject)) if root.is_dir()],
    )
    return plan


def print_plan(plan: Plan, operator_id: str, subject: str, mode: Mode) -> None:
    print(f"Mode {mode}: fold {len(plan.old_ids)} account(s) into {subject}")
    print(f"Operator's old id: {operator_id}")
    for label, counts in plan.owner_counts.items():
        owners = ", ".join(
            f"{owner or 'NULL'}={count}" for owner, count in sorted(
                counts.items(), key=lambda item: str(item[0]),
            )
        )
        print(f"  {label} [{OWNER_POLICIES[label]}]: {owners or 'no rows'}")
    size = sum(move.source.stat().st_size for move in plan.moves)
    print(f"Files to move: {len(plan.moves)} ({size} bytes)")
    rewrites = Counter(rewrite.column.label for rewrite in plan.rewrites)
    for label, count in sorted(rewrites.items()):
        print(f"  path rewrites {label}: {count}")
    print(f"Rewritten paths whose file is missing already: {len(plan.missing_before)}")
    for refusal in plan.refusals:
        print(f"REFUSED: {refusal}")


def _clear_directory(directory: Path) -> None:
    for entry in directory.iterdir():
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink()


def _clear_stream_cache(cache_dir: Path) -> None:
    if not cache_dir.is_dir():
        print(
            f"Queue-stream cache {cache_dir} is not mounted here; "
            "clear that volume in the switch run.",
        )
        return
    _clear_directory(cache_dir)
    print(f"Cleared the queue-stream cache {cache_dir}")


def _move_files(plan: Plan, audio_dir: Path) -> None:
    for move in plan.moves:
        move.destination.parent.mkdir(parents=True, exist_ok=True)
        os.rename(move.source, move.destination)
    for root in _account_roots(audio_dir, plan.old_ids):
        if root.is_dir():
            for directory, _, _ in os.walk(root, topdown=False):
                os.rmdir(directory)


def _merge_database(
    conn: Connection, metadata: MetaData, plan: Plan, operator_id: str, subject: str,
) -> None:
    users = metadata.tables["users"]
    others = [account for account in plan.old_ids if account != operator_id]
    operator = conn.execute(select(users).where(users.c.id == operator_id)).one()
    policies = {_column(metadata, label): policy for label, policy in OWNER_POLICIES.items()}
    for column, policy in policies.items():
        if policy is OwnerPolicy.DELETE_ALL:
            conn.execute(delete(column.table))
    conn.execute(
        update(users).where(users.c.id == operator_id)
        .values(username=f"merged-{operator_id}-{secrets.token_hex(4)}"),
    )
    conn.execute(insert(users).values(
        id=subject, username=operator.username, password_hash=operator.password_hash,
        role=ROLE_ADMIN, is_active=True,
        default_generation_config=operator.default_generation_config,
        created_at=operator.created_at, updated_at=operator.updated_at,
    ))
    for column, policy in policies.items():
        if policy is OwnerPolicy.OPERATOR_ONLY:
            conn.execute(
                update(column.table).where(column == operator_id).values({column: subject}),
            )
    presets = metadata.tables["generation_presets"]
    conn.execute(
        update(presets).where(presets.c.created_by.in_(others)).values(is_default=False),
    )
    conversations = metadata.tables["conversations"]
    conn.execute(
        update(conversations)
        .where(conversations.c.user_id.in_(others), conversations.c.archived_at.is_(None))
        .values(archived_at=utcnow()),
    )
    for column, policy in policies.items():
        if policy is OwnerPolicy.REPOINT_ALL:
            conn.execute(
                update(column.table).where(column.in_(plan.old_ids)).values({column: subject}),
            )
    for rewrite in plan.rewrites:
        column = _column(metadata, rewrite.column.label)
        conn.execute(
            update(column.table).where(column.table.c.id == rewrite.key)
            .values({column: rewrite.value}),
        )
    for column, policy in policies.items():
        if policy is OwnerPolicy.OPERATOR_ONLY:
            conn.execute(delete(column.table).where(column.in_(others)))
    conn.execute(delete(users).where(users.c.id.in_(plan.old_ids)))


def _check_accounts(conn: Connection, metadata: MetaData, subject: str) -> CheckResult:
    users = metadata.tables["users"]
    rows = conn.execute(select(users.c.id, users.c.role, users.c.is_active)).all()
    problems = []
    if [row.id for row in rows] != [subject]:
        problems.append(f"users hold {len(rows)} row(s), not exactly the subject")
    problems += [f"user {row.id} is not an active admin" for row in rows if (
        row.role != ROLE_ADMIN or not row.is_active
    )]
    sessions = conn.execute(
        select(func.count()).select_from(metadata.tables["user_sessions"]),
    ).scalar_one()
    if sessions:
        problems.append(f"{sessions} user session(s) remain")
    return CheckResult("V1", problems, f"users are {subject} as admin, no sessions")


def _check_row_counts(conn: Connection, metadata: MetaData, plan: Plan) -> CheckResult:
    problems = []
    for table in metadata.sorted_tables:
        actual = conn.execute(select(func.count()).select_from(table)).scalar_one()
        expected = plan.expected_row_counts[table.name]
        if actual != expected:
            problems.append(f"{table.name} has {actual} row(s), expected {expected}")
    return CheckResult("V2", problems, "row counts match the plan")


def _check_owners(
    conn: Connection, metadata: MetaData, plan: Plan, subject: str,
) -> CheckResult:
    problems = []
    for column in owner_columns(metadata):
        label = _label(column)
        stray = conn.execute(
            select(func.count()).select_from(column.table)
            .where(column.is_not(None), column != subject),
        ).scalar_one()
        if stray:
            problems.append(f"{label} has {stray} row(s) owned by someone else")
        if OWNER_POLICIES[label] is not OwnerPolicy.DELETE_ALL:
            nulls = conn.execute(
                select(func.count()).select_from(column.table).where(column.is_(None)),
            ).scalar_one()
            was = plan.owner_counts[label][NO_OWNER]
            if nulls != was:
                problems.append(f"{label} has {nulls} NULL row(s), was {was}")
    return CheckResult("V3", problems, "every owner column is the subject or NULL")


def _stored_paths(conn: Connection, metadata: MetaData, subject: str) -> dict[str, bool]:
    stored: dict[str, bool] = {}
    for path_column in PATH_COLUMNS:
        column = _column(metadata, path_column.label)
        prefix = f"{path_column.namespace}{subject}/"
        for value in conn.execute(select(column)).scalars():
            candidates = value.values() if isinstance(value, dict) else [value]
            stored.update(
                (item, path_column.is_directory) for item in candidates
                if isinstance(item, str) and item.startswith(prefix)
            )
    return stored


def _check_paths(
    conn: Connection, metadata: MetaData, plan: Plan, audio_dir: Path,
    old_ids: tuple[str, ...], subject: str,
) -> CheckResult:
    problems = [
        f"old directory {root} remains" for root in _account_roots(audio_dir, old_ids)
        if root.exists()
    ]
    stored = _stored_paths(conn, metadata, subject)
    missing = {
        path for path, is_directory in stored.items()
        if not _resolves(audio_dir / path, is_directory)
    }
    expected = {change.new for rewrite in plan.rewrites for change in rewrite.changes}
    problems += [f"rewritten path {path} is not stored" for path in sorted(expected - set(stored))]
    problems += [
        f"path {path} does not resolve" for path in sorted(missing - plan.missing_before)
    ]
    after = _tree_size(_account_roots(audio_dir, (subject,)))
    if after != plan.tree_before:
        problems.append(f"files under the subject are {after}, expected {plan.tree_before}")
    return CheckResult("V4", problems, f"{len(expected)} rewritten path(s) resolve")


def _check_residual_ids(
    conn: Connection, metadata: MetaData, old_ids: tuple[str, ...],
) -> CheckResult:
    problems = []
    history = []
    for table in metadata.sorted_tables:
        for column in table.columns:
            if not isinstance(column.type, (String, JSON)):
                continue
            hits = conn.execute(
                select(func.count()).select_from(table).where(or_(*[
                    cast(column, Text).contains(old_id, autoescape=True) for old_id in old_ids
                ])),
            ).scalar_one()
            if not hits:
                continue
            if _label(column) in HISTORY_COLUMNS:
                history.append(f"{_label(column)}={hits}")
            else:
                problems.append(f"{_label(column)} holds an old id in {hits} row(s)")
    return CheckResult("V5", problems, f"history keeps old ids: {', '.join(history) or 'none'}")


def verify(
    conn: Connection, metadata: MetaData, plan: Plan, audio_dir: Path,
    old_ids: tuple[str, ...], subject: str,
) -> list[CheckResult]:
    return [
        _check_accounts(conn, metadata, subject),
        _check_row_counts(conn, metadata, plan),
        _check_owners(conn, metadata, plan, subject),
        _check_paths(conn, metadata, plan, audio_dir, old_ids, subject),
        _check_residual_ids(conn, metadata, old_ids),
    ]


def _report_checks(results: list[CheckResult]) -> bool:
    for result in results:
        if result.problems:
            print(f"{result.name} FAILED: " + "; ".join(result.problems))
        else:
            print(f"{result.name} ok: {result.note}")
    return not any(result.problems for result in results)


def _one_line(error: BaseException) -> str:
    # SQLAlchemy's own text carries the statement and its parameters
    cause = error.orig if isinstance(error, DBAPIError) else error
    return (str(cause).splitlines() or [""])[0]


def reflect_live_schema(engine: Engine) -> MetaData:
    metadata = MetaData()
    metadata.reflect(bind=engine)
    return metadata


def run(
    engine: Engine, *, audio_dir: Path, stream_cache_dir: Path, operator_id: str,
    subject: str, mode: Mode,
) -> int:
    metadata = reflect_live_schema(engine)
    with engine.connect() as conn:
        plan = build_plan(conn, metadata, audio_dir, operator_id, subject)
    print_plan(plan, operator_id, subject, mode)
    if plan.refusals:
        return 1
    if mode is Mode.DRY_RUN:
        return 0
    try:
        _move_files(plan, audio_dir)
        with engine.begin() as conn:
            _merge_database(conn, metadata, plan, operator_id, subject)
        _clear_stream_cache(stream_cache_dir)
        with engine.connect() as conn:
            results = verify(conn, metadata, plan, audio_dir, plan.old_ids, subject)
    except (Exception, KeyboardInterrupt) as error:
        print(f"{type(error).__name__}: {_one_line(error)}. {RESTORE_HINT}", file=sys.stderr)
        return 1
    if _report_checks(results):
        return 0
    print(f"Verification failed. {RESTORE_HINT}")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="operator_id", required=True,
                        help="The operator's current user id.")
    parser.add_argument("--subject", required=True,
                        help="The operator's Keycloak subject, a lowercase UUID.")
    parser.add_argument("--apply", action="store_true", help="Write. Default is a dry run.")
    args = parser.parse_args(argv)
    mode = Mode.APPLY if args.apply else Mode.DRY_RUN

    settings = get_settings()
    project_root = find_project_root(Path.cwd()) or Path.cwd()
    factory = connect_db(resolve_database_url())
    return run(
        factory.kw["bind"],
        audio_dir=project_root / settings.audio_dir,
        stream_cache_dir=project_root / settings.data_dir / QUEUE_STREAM_DIRNAME,
        operator_id=args.operator_id, subject=args.subject, mode=mode,
    )


if __name__ == "__main__":
    sys.exit(main())
