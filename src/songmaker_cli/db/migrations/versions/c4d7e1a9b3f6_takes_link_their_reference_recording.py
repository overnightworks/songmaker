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
    link_by_path,
    linked_path,
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
    rows = bind.execute(
        sa.select(generations.c.id, generations.c.created_by, generations.c.generation_params)
    )
    return link_by_path(
        bind,
        [
            (take_id, owner, path)
            for take_id, owner, params in rows
            if (path := linked_path(params))
        ],
    )


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
