"""Takes link their reference recording by key instead of by path.

Adds ``generations.reference_recording_id`` (ON DELETE RESTRICT), maps each take's
``generation_params.reference_audio_path`` to the recording row with that storage path
and strips the JSON key. A path that maps to no row of the take's creator stops the
upgrade before anything changes.
"""

from collections.abc import Mapping

import sqlalchemy as sa
from alembic import op

from songmaker_cli.db.migrations.reference_link import (
    COLUMN,
    PATH_KEY,
    add_link_column,
    linked_path,
    recordings,
    refuse_unmappable,
    remove_link_column,
)

revision = "c4d7e1a9b3f6"
down_revision = "ea28bf0de7cc"
branch_labels = None
depends_on = None


generations = sa.table(
    "generations",
    sa.column("id", sa.String),
    sa.column("created_by", sa.String),
    sa.column("generation_params", sa.JSON(none_as_null=True)),
    sa.column(COLUMN, sa.String),
)


def _without_path(params: Mapping[str, object]) -> dict[str, object] | None:
    return {key: value for key, value in params.items() if key != PATH_KEY} or None


def _take_links(bind: sa.Connection) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Take id to recording id, plus the failing take ids by kind; never a path."""
    recording_by_path = {
        storage_path: (recording_id, user_id)
        for recording_id, user_id, storage_path in bind.execute(
            sa.select(recordings.c.id, recordings.c.user_id, recordings.c.storage_path)
        )
    }
    links: dict[str, str] = {}
    failures: dict[str, list[str]] = {
        kind: [] for kind in ("unmapped path", "owner mismatch", "NULL owner")
    }
    rows = bind.execute(
        sa.select(generations.c.id, generations.c.created_by, generations.c.generation_params)
    )
    for take_id, owner, params in rows:
        path = linked_path(params)
        if path is None:
            continue
        recording = recording_by_path.get(path)
        if owner is None:
            failures["NULL owner"].append(take_id)
        elif recording is None:
            failures["unmapped path"].append(take_id)
        elif recording[1] != owner or path.split("/", 1)[0] != owner:
            failures["owner mismatch"].append(take_id)
        else:
            links[take_id] = recording[0]
    return links, {kind: ids for kind, ids in failures.items() if ids}


def upgrade() -> None:
    bind = op.get_bind()
    links, failures = _take_links(bind)
    refuse_unmappable(failures)
    add_link_column("generations")
    for take_id, recording_id in links.items():
        bind.execute(
            sa.update(generations).where(generations.c.id == take_id).values({COLUMN: recording_id})
        )
    for take_id, params in bind.execute(
        sa.select(generations.c.id, generations.c.generation_params)
    ).all():
        if isinstance(params, dict) and PATH_KEY in params:
            bind.execute(
                sa.update(generations)
                .where(generations.c.id == take_id)
                .values(generation_params=_without_path(params))
            )


def downgrade() -> None:
    remove_link_column(generations, "generation_params")
