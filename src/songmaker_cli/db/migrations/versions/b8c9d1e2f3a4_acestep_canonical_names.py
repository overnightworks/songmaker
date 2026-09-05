"""rename Version/Song columns and generation_params keys to ACE-Step canonical names

Revision ID: b8c9d1e2f3a4
Revises: a7b8c9d0e1f2
Create Date: 2026-04-08 16:00:00.000000

Schema changes:
  songs.language        -> songs.vocal_language
  versions.duration     -> versions.audio_duration
  versions.key          -> versions.key_scale

Data migration (JSON columns):
  generations.generation_params
  versions.generation_params
  generation_presets.params

  duration         -> audio_duration
  key              -> key_scale
  src_audio        -> src_audio_path
  reference_audio  -> reference_audio_path
  think_mode       -> thinking (lossy: "deep" -> True, anything else -> False)
"""
from __future__ import annotations

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b8c9d1e2f3a4"
down_revision: Union[str, Sequence[str], None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_KEY_RENAMES_FORWARD: dict[str, str] = {
    "duration": "audio_duration",
    "key": "key_scale",
    "src_audio": "src_audio_path",
    "reference_audio": "reference_audio_path",
}
_KEY_RENAMES_REVERSE: dict[str, str] = {v: k for k, v in _KEY_RENAMES_FORWARD.items()}

_JSON_TARGETS: tuple[tuple[str, str], ...] = (
    ("generations", "generation_params"),
    ("versions", "generation_params"),
    ("generation_presets", "params"),
)


def _migrate_json_column(table: str, col: str, *, forward: bool) -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text(f"SELECT id, {col} FROM {table}")).fetchall()  # nosec B608
    for row in rows:
        data = _json_mapping(row[1])
        if data is None:
            continue
        if _migrate_json_keys(data, forward=forward):
            bind.execute(
                sa.text(f"UPDATE {table} SET {col} = :p WHERE id = :id"),  # nosec B608
                {"p": json.dumps(data), "id": row[0]},
            )


def _json_mapping(raw: object) -> dict | None:
    if isinstance(raw, dict):
        return dict(raw)
    if not isinstance(raw, str):
        return None
    try:
        decoded = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    return decoded if isinstance(decoded, dict) else None


def _migrate_json_keys(data: dict, *, forward: bool) -> bool:
    renames = _KEY_RENAMES_FORWARD if forward else _KEY_RENAMES_REVERSE
    renamed = _rename_json_keys(data, renames)
    return _migrate_thinking_value(data, forward=forward) or renamed


def _rename_json_keys(data: dict, renames: dict[str, str]) -> bool:
    changed = False
    for old, new in renames.items():
        if old in data and new not in data:
            data[new] = data.pop(old)
            changed = True
    return changed


def _migrate_thinking_value(data: dict, *, forward: bool) -> bool:
    source, target = ("think_mode", "thinking") if forward else ("thinking", "think_mode")
    if source not in data:
        return False
    value = data.pop(source)
    if forward:
        data[target] = value == "deep"
    else:
        data[target] = "deep" if value else "off"
    return True


def upgrade() -> None:
    with op.batch_alter_table("songs") as batch_op:
        batch_op.alter_column("language", new_column_name="vocal_language")
    with op.batch_alter_table("versions") as batch_op:
        batch_op.alter_column("duration", new_column_name="audio_duration")
        batch_op.alter_column("key", new_column_name="key_scale")

    for table, col in _JSON_TARGETS:
        _migrate_json_column(table, col, forward=True)


def downgrade() -> None:
    for table, col in _JSON_TARGETS:
        _migrate_json_column(table, col, forward=False)

    with op.batch_alter_table("versions") as batch_op:
        batch_op.alter_column("key_scale", new_column_name="key")
        batch_op.alter_column("audio_duration", new_column_name="duration")
    with op.batch_alter_table("songs") as batch_op:
        batch_op.alter_column("vocal_language", new_column_name="language")
