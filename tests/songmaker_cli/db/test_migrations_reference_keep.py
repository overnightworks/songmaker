"""The migration that records when a reference became unused and whether its owner keeps it."""

from __future__ import annotations

from alembic import command
from sqlalchemy import text
from support.migration_chain import column_names, is_on_the_single_chain, seeded_then_upgraded
from support.reference_link_migration import execute, seed_users

PREVIOUS_REVISION = "f71349322716"
KEEP_REVISION = "3d9a6b1e5c80"
KEEP_COLUMNS = {"is_kept", "unused_since"}
REFERENCE_IDS = (
    "unlinked",
    "by-version",
    "by-take",
    "by-archived-take",
    "by-trashed-version",
    "by-trashed-take",
)


def _seed_live_or_trashed_song(engine, song_id: str, *, trashed: bool) -> None:
    execute(
        engine,
        "INSERT INTO songs (id, title, album_id, vocal_language, track_number, created_at, "
        "updated_at, slug, deleted_at) VALUES (:id, 'S', 'album', '', :number, CURRENT_TIMESTAMP, "
        "CURRENT_TIMESTAMP, :id, CASE WHEN :trashed THEN CURRENT_TIMESTAMP END)",
        id=song_id,
        number=1 if trashed else 2,
        trashed=trashed,
    )


def _seed_version(engine, version_id: str, song_id: str, reference_id: str | None) -> None:
    execute(
        engine,
        "INSERT INTO versions (id, song_id, version_number, lyrics, prompt, bpm, audio_duration, "
        "key_scale, created_at, reference_recording_id) VALUES (:id, :song, 1, '', '', 0, 0, '', "
        "CURRENT_TIMESTAMP, :reference)",
        id=version_id,
        song=song_id,
        reference=reference_id,
    )


def _seed_linking_take(
    engine, take_id: str, version_id: str, reference_id: str, *, number: int, archived: bool,
) -> None:
    execute(
        engine,
        "INSERT INTO generations (id, song_id, version_id, generation_number, mp3_path, status, "
        "is_archived, is_picked, is_kept, model_mode, created_at, is_shared, "
        "reference_recording_id) SELECT :id, song_id, id, :number, :id, 'completed', :archived, "
        ":off, :off, 'sft', CURRENT_TIMESTAMP, :off, :reference FROM versions WHERE id = :version",
        id=take_id,
        number=number,
        version=version_id,
        reference=reference_id,
        archived=archived,
        off=False,
    )


def _seed_world(engine) -> None:
    """One reference per way a row can be linked, each song's own version left unlinked."""
    seed_users(engine)
    execute(
        engine,
        "INSERT INTO albums (id, title, artist, subtitle, year, colors, created_at, created_by) "
        "VALUES ('album', 'A', 'B', '', 0, '{}', CURRENT_TIMESTAMP, 'u1')",
    )
    for reference_id in REFERENCE_IDS:
        execute(
            engine,
            "INSERT INTO reference_recordings (id, user_id, storage_path, original_filename, "
            "size_bytes, created_at) VALUES (:id, 'u1', :id, 'a.wav', 10, CURRENT_TIMESTAMP)",
            id=reference_id,
        )
    _seed_live_or_trashed_song(engine, "live", trashed=False)
    _seed_live_or_trashed_song(engine, "trashed", trashed=True)
    _seed_version(engine, "live-linked", "live", "by-version")
    _seed_version(engine, "live-plain", "live", None)
    _seed_version(engine, "trashed-linked", "trashed", "by-trashed-version")
    _seed_version(engine, "trashed-plain", "trashed", None)
    _seed_linking_take(engine, "take", "live-plain", "by-take", number=1, archived=False)
    _seed_linking_take(
        engine, "archived-take", "live-plain", "by-archived-take", number=2, archived=True,
    )
    _seed_linking_take(
        engine, "trashed-take", "trashed-plain", "by-trashed-take", number=1, archived=False,
    )


def _upgraded(reference_link_database):
    return seeded_then_upgraded(
        reference_link_database, PREVIOUS_REVISION, KEEP_REVISION, _seed_world,
    )


def _keep_columns_by_reference(engine) -> dict[str, tuple[bool, object]]:
    with engine.connect() as connection:
        return {
            reference_id: (is_kept, unused_since)
            for reference_id, is_kept, unused_since in connection.execute(
                text("SELECT id, is_kept, unused_since FROM reference_recordings"),
            )
        }


def test_the_upgrade_stamps_exactly_the_rows_nothing_links(reference_link_database) -> None:
    rows = _keep_columns_by_reference(_upgraded(reference_link_database))

    assert {reference_id for reference_id, (_, stamp) in rows.items() if stamp is not None} == {
        "unlinked",
    }
    assert not any(is_kept for is_kept, _ in rows.values())


def test_the_downgrade_drops_both_columns_and_keeps_every_row(reference_link_database) -> None:
    config, _ = reference_link_database
    engine = _upgraded(reference_link_database)

    command.downgrade(config, PREVIOUS_REVISION)

    assert not KEEP_COLUMNS & column_names(engine, "reference_recordings")
    with engine.connect() as connection:
        remaining = connection.execute(text("SELECT count(*) FROM reference_recordings"))
    assert remaining.scalar_one() == len(REFERENCE_IDS)


def test_the_keep_revision_is_on_the_single_chain() -> None:
    assert is_on_the_single_chain(KEEP_REVISION)
