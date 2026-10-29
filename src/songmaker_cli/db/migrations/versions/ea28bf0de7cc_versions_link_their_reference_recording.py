"""Versions link their reference recording by key instead of by path.

Adds ``versions.reference_recording_id`` (ON DELETE RESTRICT), maps each version's
``generation_params.reference_audio_path`` to the recording row with that storage
path and strips the JSON key. A path that maps to no row of the album's owner, or
a path on a preset or a global default, stops the upgrade before anything changes.
"""

from collections.abc import Mapping, Sequence

import sqlalchemy as sa
from alembic import op

revision = "ea28bf0de7cc"
down_revision = "5b2e9d4a7c31"
branch_labels = None
depends_on = None

PATH_KEY = "reference_audio_path"
COLUMN = "reference_recording_id"
INDEX = "ix_versions_reference_recording_id"
FOREIGN_KEY = "fk_versions_reference_recording_id_reference_recordings"

versions = sa.table(
    "versions",
    sa.column("id", sa.String),
    sa.column("song_id", sa.String),
    sa.column("generation_params", sa.JSON(none_as_null=True)),
    sa.column(COLUMN, sa.String),
)
songs = sa.table("songs", sa.column("id", sa.String), sa.column("album_id", sa.String))
albums = sa.table("albums", sa.column("id", sa.String), sa.column("created_by", sa.String))
presets = sa.table(
    "generation_presets",
    sa.column("id", sa.String),
    sa.column("params", sa.JSON(none_as_null=True)),
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


def _without_path(
    params: Mapping[str, object], emptied: dict[str, object] | None
) -> dict[str, object] | None:
    remaining = {key: value for key, value in params.items() if key != PATH_KEY}
    return remaining or emptied


def _owner_of_each_version(bind: sa.Connection) -> dict[str, str | None]:
    rows = bind.execute(
        sa.select(versions.c.id, albums.c.created_by)
        .select_from(
            versions.outerjoin(songs, songs.c.id == versions.c.song_id)
            .outerjoin(albums, albums.c.id == songs.c.album_id)
        )
    )
    return {version_id: owner for version_id, owner in rows}


def _version_links(
    bind: sa.Connection,
) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Version id to recording id, plus the failing row ids by kind; never a path."""
    owners = _owner_of_each_version(bind)
    recording_by_path = {
        storage_path: (recording_id, user_id)
        for recording_id, user_id, storage_path in bind.execute(
            sa.select(recordings.c.id, recordings.c.user_id, recordings.c.storage_path)
        )
    }
    links: dict[str, str] = {}
    failures: dict[str, list[str]] = {
        kind: [] for kind in ("unmapped path", "owner mismatch", "NULL owner", "preset or default")
    }
    for version_id, params in bind.execute(sa.select(versions.c.id, versions.c.generation_params)):
        path = _linked_path(params)
        if path is None:
            continue
        owner = owners[version_id]
        recording = recording_by_path.get(path)
        if owner is None:
            failures["NULL owner"].append(version_id)
        elif recording is None:
            failures["unmapped path"].append(version_id)
        elif recording[1] != owner or path.split("/", 1)[0] != owner:
            failures["owner mismatch"].append(version_id)
        else:
            links[version_id] = recording[0]
    for preset_id, params in bind.execute(sa.select(presets.c.id, presets.c.params)):
        if _linked_path(params) is not None:
            failures["preset or default"].append(preset_id)
    return links, {kind: ids for kind, ids in failures.items() if ids}


def _refuse_unmappable(failures: Mapping[str, Sequence[str]]) -> None:
    if not failures:
        return
    detail = "; ".join(
        f"{kind}: {len(ids)} (ids {', '.join(ids)})" for kind, ids in failures.items()
    )
    msg = f"Reference paths cannot be linked by key, nothing was changed. {detail}"
    raise RuntimeError(msg)


def _strip_path_key(
    bind: sa.Connection,
    table: sa.TableClause,
    column: str,
    emptied: dict[str, object] | None,
) -> None:
    """Drop the key from every JSON object that still holds it, once the link carries it.

    ``emptied`` is what a column holds when the key was its only entry: NULL for
    versions, ``{}`` for the NOT NULL preset parameters.
    """
    for row_id, params in list(bind.execute(sa.select(table.c.id, table.c[column]))):
        if isinstance(params, dict) and PATH_KEY in params:
            stripped = _without_path(params, emptied)
            bind.execute(sa.update(table).where(table.c.id == row_id).values({column: stripped}))


def upgrade() -> None:
    bind = op.get_bind()
    links, failures = _version_links(bind)
    _refuse_unmappable(failures)
    with op.batch_alter_table("versions") as batch:
        batch.add_column(sa.Column(COLUMN, sa.String(length=36), nullable=True))
        batch.create_index(INDEX, [COLUMN])
        batch.create_foreign_key(
            FOREIGN_KEY, "reference_recordings", [COLUMN], ["id"], ondelete="RESTRICT",
        )
    for version_id, recording_id in links.items():
        bind.execute(
            sa.update(versions)
            .where(versions.c.id == version_id)
            .values({COLUMN: recording_id})
        )
    _strip_path_key(bind, versions, "generation_params", None)
    _strip_path_key(bind, presets, "params", {})


def downgrade() -> None:
    bind = op.get_bind()
    linked = bind.execute(
        sa.select(versions.c.id, versions.c.generation_params, recordings.c.storage_path)
        .select_from(
            versions.join(recordings, versions.c[COLUMN] == recordings.c.id)
        )
    ).all()
    for version_id, params, storage_path in linked:
        bind.execute(
            sa.update(versions)
            .where(versions.c.id == version_id)
            .values(generation_params={**(params or {}), PATH_KEY: storage_path})
        )
    with op.batch_alter_table("versions") as batch:
        batch.drop_constraint(FOREIGN_KEY, type_="foreignkey")
        batch.drop_index(INDEX)
        batch.drop_column(COLUMN)
