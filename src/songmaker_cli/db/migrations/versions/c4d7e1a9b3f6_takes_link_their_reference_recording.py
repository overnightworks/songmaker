"""Takes link their reference recording by key instead of by path.

Adds ``generations.reference_recording_id`` (ON DELETE RESTRICT), maps each take's
``generation_params.reference_audio_path`` to the recording row with that storage path
and strips the JSON key. A path that maps to no row of the take's creator stops the
upgrade before anything changes.
"""

from collections.abc import Mapping, Sequence

import sqlalchemy as sa
from alembic import op

revision = "c4d7e1a9b3f6"
down_revision = "ea28bf0de7cc"
branch_labels = None
depends_on = None

PATH_KEY = "reference_audio_path"
COLUMN = "reference_recording_id"
INDEX = "ix_generations_reference_recording_id"
FOREIGN_KEY = "fk_generations_reference_recording_id_reference_recordings"

generations = sa.table(
    "generations",
    sa.column("id", sa.String),
    sa.column("created_by", sa.String),
    sa.column("generation_params", sa.JSON(none_as_null=True)),
    sa.column(COLUMN, sa.String),
)
recordings = sa.table(
    "reference_recordings",
    sa.column("id", sa.String),
    sa.column("user_id", sa.String),
    sa.column("storage_path", sa.Text),
)


def _linked_path(params: object) -> str | None:
    """The non-empty path a JSON parameter object names, or None for absent, null and ""."""
    if not isinstance(params, dict):
        return None
    value = params.get(PATH_KEY)
    return None if value in (None, "") else str(value)


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
        path = _linked_path(params)
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


def _refuse_unmappable(failures: Mapping[str, Sequence[str]]) -> None:
    if not failures:
        return
    detail = "; ".join(
        f"{kind}: {len(ids)} (ids {', '.join(ids)})" for kind, ids in failures.items()
    )
    msg = f"Reference paths cannot be linked by key, nothing was changed. {detail}"
    raise RuntimeError(msg)


def upgrade() -> None:
    bind = op.get_bind()
    links, failures = _take_links(bind)
    _refuse_unmappable(failures)
    with op.batch_alter_table("generations") as batch:
        batch.add_column(sa.Column(COLUMN, sa.String(length=36), nullable=True))
        batch.create_index(INDEX, [COLUMN])
        batch.create_foreign_key(
            FOREIGN_KEY, "reference_recordings", [COLUMN], ["id"], ondelete="RESTRICT",
        )
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
    bind = op.get_bind()
    linked = bind.execute(
        sa.select(generations.c.id, generations.c.generation_params, recordings.c.storage_path)
        .select_from(generations.join(recordings, generations.c[COLUMN] == recordings.c.id))
    ).all()
    for take_id, params, storage_path in linked:
        bind.execute(
            sa.update(generations)
            .where(generations.c.id == take_id)
            .values(generation_params={**(params or {}), PATH_KEY: storage_path})
        )
    with op.batch_alter_table("generations") as batch:
        batch.drop_constraint(FOREIGN_KEY, type_="foreignkey")
        batch.drop_index(INDEX)
        batch.drop_column(COLUMN)
