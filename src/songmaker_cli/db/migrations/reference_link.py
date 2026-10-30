"""Shared body of the two frozen reference-link migrations.

Serves only ``ea28bf0de7cc`` (versions) and ``c4d7e1a9b3f6`` (takes), whose recorded
behaviour must not drift; it changes only together with both.
"""

from collections.abc import Mapping, Sequence

import sqlalchemy as sa
from alembic import op

PATH_KEY = "reference_audio_path"
COLUMN = "reference_recording_id"

recordings = sa.table(
    "reference_recordings",
    sa.column("id", sa.String),
    sa.column("user_id", sa.String),
    sa.column("storage_path", sa.Text),
)


def linked_path(params: object) -> str | None:
    """The non-empty path a JSON parameter object names, or None for absent, null and ""."""
    if not isinstance(params, dict):
        return None
    value = params.get(PATH_KEY)
    return None if value in (None, "") else str(value)


def refuse_unmappable(failures: Mapping[str, Sequence[str]]) -> None:
    """Stop the upgrade with failing row ids by kind; never a path."""
    if not failures:
        return
    detail = "; ".join(
        f"{kind}: {len(ids)} (ids {', '.join(ids)})" for kind, ids in failures.items()
    )
    msg = f"Reference paths cannot be linked by key, nothing was changed. {detail}"
    raise RuntimeError(msg)


def restore_paths(bind: sa.Connection, table: sa.TableClause, params_column: str) -> None:
    """Write each linked row's recording path back into its JSON parameters."""
    linked = bind.execute(
        sa.select(table.c.id, table.c[params_column], recordings.c.storage_path).select_from(
            table.join(recordings, table.c[COLUMN] == recordings.c.id)
        )
    ).all()
    for row_id, params, storage_path in linked:
        bind.execute(
            sa.update(table)
            .where(table.c.id == row_id)
            .values({params_column: {**(params or {}), PATH_KEY: storage_path}})
        )


def add_link_column(table_name: str) -> None:
    """Add the nullable key, its index and the foreign key that restricts recording deletion."""
    with op.batch_alter_table(table_name) as batch:
        batch.add_column(sa.Column(COLUMN, sa.String(length=36), nullable=True))
        batch.create_index(f"ix_{table_name}_{COLUMN}", [COLUMN])
        batch.create_foreign_key(
            f"fk_{table_name}_{COLUMN}_reference_recordings",
            "reference_recordings",
            [COLUMN],
            ["id"],
            ondelete="RESTRICT",
        )


def remove_link_column(table: sa.TableClause, params_column: str) -> None:
    """Write the paths back, then drop the key with its foreign key and index."""
    restore_paths(op.get_bind(), table, params_column)
    with op.batch_alter_table(table.name) as batch:
        batch.drop_constraint(f"fk_{table.name}_{COLUMN}_reference_recordings", type_="foreignkey")
        batch.drop_index(f"ix_{table.name}_{COLUMN}")
        batch.drop_column(COLUMN)
