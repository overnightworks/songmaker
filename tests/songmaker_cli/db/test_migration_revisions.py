"""What single alembic revisions do to existing rows, upgrading and downgrading, on PostgreSQL."""

from __future__ import annotations

import importlib
import logging
from datetime import datetime, timezone

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from support.migration_chain import column_names
from support.reference_link_migration import execute

from songmaker_cli.constants import MODEL_AVAILABLE_MODES
from songmaker_cli.db.engine import init_db
from songmaker_cli.db.models import (
    PLAYLIST_SLUG_MAX_LENGTH,
    SONG_SLUG_MAX_LENGTH,
    Base,
)

VERSIONS = "songmaker_cli.db.migrations.versions."
SONG_SLUG_REVISION = "b8e3f1c07a25"
SONG_SLUG_UNIQUE_REVISION = "c9d4a2f18e37"
PLAYLIST_SLUG_REVISION = "d5f8a3b21c46"


@pytest.fixture
def database(reference_link_database):
    """The alembic config and an engine on an empty database."""
    return reference_link_database


def _migration(name: str):
    return importlib.import_module(VERSIONS + name)


def _upgrade_to_previous_of(database, migration) -> sa.Engine:
    config, engine = database
    command.upgrade(config, migration.down_revision)
    return engine


def _columns(engine: sa.Engine, table: str) -> dict[str, dict]:
    return {column["name"]: column for column in inspect(engine).get_columns(table)}


def _seed_accounts(engine: sa.Engine, *ids: str, role: str = "user") -> None:
    """Insert users with the columns the revision's table has; the password era needs more."""
    present = column_names(engine, "users")
    password_era = {
        name: value
        for name, value in (("password_hash", "'h'"), ("is_active", "true"))
        if name in present
    }
    names = ", ".join(["id", "username", "role", "created_at", "updated_at", *password_era])
    values = ", ".join(
        [":id", ":id", ":role", "CURRENT_TIMESTAMP", "CURRENT_TIMESTAMP", *password_era.values()],
    )
    for user_id in ids:
        execute(engine, f"INSERT INTO users ({names}) VALUES ({values})", id=user_id, role=role)


def _seed_album_with_song(engine: sa.Engine, song_id: str = "s1") -> None:
    execute(
        engine,
        "INSERT INTO albums (id, title, artist, subtitle, year, colors, created_at) "
        "VALUES ('a1', 'A', 'X', '', '', '[]', CURRENT_TIMESTAMP)",
    )
    execute(
        engine,
        "INSERT INTO songs "
        "(id, title, album_id, vocal_language, track_number, created_at, updated_at, slug) "
        f"VALUES ('{song_id}', 'Thunder', 'a1', '', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, "
        "'thunder')",
    )


def _run_on(monkeypatch: pytest.MonkeyPatch, migration, engine: sa.Engine, step) -> None:
    """Run one migration helper on a connection of its own, the way alembic hands it one."""
    with engine.begin() as connection:
        monkeypatch.setattr(migration.op, "get_bind", lambda: connection)
        step()


def test_init_db_fresh_creates_all_tables(empty_postgresql_url) -> None:
    init_db(empty_postgresql_url)

    engine = create_engine(empty_postgresql_url)
    tables = set(inspect(engine).get_table_names())
    engine.dispose()

    expected = {
        "albums",
        "album_cover_suggestions",
        "songs",
        "versions",
        "generations",
        "scores",
        "ratings",
        "jobs",
        "users",
        "user_sessions",
        "audit_log",
        "generation_presets",
        "rate_limit_settings",
        "available_models",
        "playlists",
        "playlist_entries",
        "chat_messages",
        "conversations",
        "conversation_summaries",
        "cowriter_user_memories",
        "cowriter_song_memories",
        "cowriter_album_memories",
        "acestep_workers",
        "user_loras",
        "user_lora_samples",
        "resource_event_cursors",
        "resource_events",
        "user_song_work", "reference_recordings",
        "alembic_version",
    }
    assert tables == expected


def test_available_models_seed_idempotent(empty_postgresql_url) -> None:
    def seeded_models() -> list[str]:
        engine = create_engine(empty_postgresql_url)
        with engine.connect() as connection:
            rows = connection.execute(text("SELECT id FROM available_models")).scalars().all()
        engine.dispose()
        return rows

    init_db(empty_postgresql_url).kw["bind"].dispose()
    count_before = len(seeded_models())
    assert set(seeded_models()) == MODEL_AVAILABLE_MODES

    init_db(empty_postgresql_url).kw["bind"].dispose()
    assert set(seeded_models()) == MODEL_AVAILABLE_MODES
    assert len(seeded_models()) == count_before


def test_init_db_stamps_existing_db(empty_postgresql_url) -> None:
    engine = create_engine(empty_postgresql_url)
    Base.metadata.create_all(engine)
    engine.dispose()

    init_db(empty_postgresql_url).kw["bind"].dispose()

    engine = create_engine(empty_postgresql_url)
    tables = set(inspect(engine).get_table_names())
    assert "alembic_version" in tables
    with engine.connect() as conn:
        row = conn.execute(text("SELECT version_num FROM alembic_version")).fetchone()
        assert row is not None
    engine.dispose()


def test_generation_progress_migration_preserves_existing_jobs(database) -> None:
    migration = _migration("d52826563268_add_generation_progress_timing_to_jobs")
    config, _ = database
    engine = _upgrade_to_previous_of(database, migration)
    execute(
        engine,
        "INSERT INTO jobs (id, type, status, progress, started_at, heartbeat_at) "
        "VALUES ('existing', 'generate', 'running', 0.25, CURRENT_TIMESTAMP, "
        "CURRENT_TIMESTAMP)",
    )

    command.upgrade(config, migration.revision)

    columns = _columns(engine, "jobs")
    new_columns = {"running_since", "take_index", "take_count"}
    assert all(columns[name]["nullable"] for name in new_columns)
    with engine.begin() as connection:
        assert connection.execute(text(
            "SELECT progress, running_since, take_index, take_count FROM jobs WHERE id = 'existing'"
        )).one() == (0.25, None, None, None)

    command.downgrade(config, migration.down_revision)

    assert not new_columns & column_names(engine, "jobs")
    with engine.begin() as connection:
        assert connection.execute(text(
            "SELECT progress FROM jobs WHERE id = 'existing'"
        )).scalar_one() == 0.25


def test_generation_phase_migration_keeps_the_estimate_anchor_both_ways(database) -> None:
    migration = _migration("98acbb42010e_add_generation_phase_to_jobs")
    config, _ = database
    engine = _upgrade_to_previous_of(database, migration)
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO jobs (id, type, status, progress, started_at, heartbeat_at, "
            "running_since) "
            "VALUES ('existing', 'generate', 'running', 0.36, CURRENT_TIMESTAMP, "
            "CURRENT_TIMESTAMP, '2030-01-01 00:00:00')"
        ))
        anchor = connection.execute(text(
            "SELECT running_since FROM jobs WHERE id = 'existing'"
        )).scalar_one()

    command.upgrade(config, migration.revision)

    columns = column_names(engine, "jobs")
    assert {"phase", "generation_started_at"} <= columns
    assert "running_since" not in columns
    with engine.begin() as connection:
        assert connection.execute(text(
            "SELECT generation_started_at, phase FROM jobs WHERE id = 'existing'"
        )).one() == (anchor, None)

    command.downgrade(config, migration.down_revision)

    assert not {"phase", "generation_started_at"} & column_names(engine, "jobs")
    with engine.begin() as connection:
        assert connection.execute(text(
            "SELECT running_since FROM jobs WHERE id = 'existing'"
        )).scalar_one() == anchor


def test_training_epoch_migration_up_and_down(
    database,
    caplog: pytest.LogCaptureFixture,
    isolated_logging,
) -> None:
    from songmaker_cli.db.migration_logging import _MigrationLogHandler

    migration = _migration("a8c4d1e9f275_add_training_epochs_to_jobs")
    config, engine = database

    command.upgrade(config, migration.revision)
    logging.getLogger("migration.test").warning("capture remains attached")
    assert "capture remains attached" in caplog.text
    assert {"current_epoch", "train_epochs", "training_started_at"} <= column_names(
        engine, "jobs",
    )

    command.downgrade(config, migration.down_revision)

    root = logging.getLogger()
    assert caplog.handler in root.handlers
    assert sum(isinstance(handler, _MigrationLogHandler) for handler in root.handlers) == 1
    assert not {"current_epoch", "train_epochs", "training_started_at"} & column_names(
        engine, "jobs",
    )


def _insert_version(engine: sa.Engine, params: dict) -> None:
    execute(
        engine,
        "INSERT INTO versions (id, song_id, version_number, lyrics, prompt, "
        "bpm, audio_duration, key_scale, generation_params, created_at) "
        "VALUES ('v1', 's1', 1, 'l', 'p', 120, 180, 'Am', :params, CURRENT_TIMESTAMP)",
        params=params,
    )


def _seed_album_and_song(pg_factory) -> None:
    from songmaker_cli.db.models import Album, Song

    with pg_factory() as session:
        session.add(Album(id="a1", title="A", artist="X"))
        session.add(Song(id="s1", title="S", album_id="a1", vocal_language="en", track_number=1))
        session.commit()


def _generation_params_after(pg_factory, monkeypatch, old_params: dict, *, forward: bool) -> dict:
    from songmaker_cli.db.models import Version

    migration = _migration("b8c9d1e2f3a4_acestep_canonical_names")
    engine = pg_factory.kw["bind"]
    _seed_album_and_song(pg_factory)
    _insert_version(engine, old_params)

    _run_on(
        monkeypatch, migration, engine,
        lambda: migration._migrate_json_column("versions", "generation_params", forward=forward),
    )

    with pg_factory() as session:
        return session.query(Version).filter_by(id="v1").one().generation_params


def test_acestep_canonical_names_migration_renames_json_keys(pg_factory, monkeypatch) -> None:
    params = _generation_params_after(
        pg_factory, monkeypatch,
        {
            "duration": 180,
            "key": "Am",
            "src_audio": "/audio/x.wav",
            "reference_audio": "/audio/r.wav",
            "think_mode": "deep",
            "bpm": 120,
        },
        forward=True,
    )

    assert params["audio_duration"] == 180
    assert params["key_scale"] == "Am"
    assert params["src_audio_path"] == "/audio/x.wav"
    assert params["reference_audio_path"] == "/audio/r.wav"
    assert params["thinking"] is True
    assert params["bpm"] == 120
    assert "duration" not in params
    assert "key" not in params
    assert "src_audio" not in params
    assert "reference_audio" not in params
    assert "think_mode" not in params


def test_acestep_canonical_names_migration_downgrade_reverses_json_keys(
    pg_factory, monkeypatch,
) -> None:
    params = _generation_params_after(
        pg_factory, monkeypatch,
        {
            "audio_duration": 180,
            "key_scale": "Am",
            "src_audio_path": "/audio/x.wav",
            "thinking": False,
        },
        forward=False,
    )

    assert params["duration"] == 180
    assert params["key"] == "Am"
    assert params["src_audio"] == "/audio/x.wav"
    assert params["think_mode"] == "off"


def test_whisper_cues_migration_adds_nullable_column(pg_factory) -> None:
    cols = _columns(pg_factory.kw["bind"], "generations")
    assert "whisper_cues" in cols
    assert cols["whisper_cues"]["nullable"] is True


def test_last_played_at_migration_adds_and_removes_nullable_column(database) -> None:
    migration = _migration("05a349e664e2_add_last_played_at_to_songs")
    config, engine = database

    command.upgrade(config, migration.revision)
    assert _columns(engine, "songs")["last_played_at"]["nullable"] is True

    command.downgrade(config, migration.down_revision)
    assert "last_played_at" not in column_names(engine, "songs")


def test_playlist_cover_key_migration_adds_and_removes_nullable_column(database) -> None:
    migration = _migration("889dfb248896_add_playlist_cover_key")
    config, engine = database

    command.upgrade(config, migration.revision)
    assert _columns(engine, "playlists")["cover_key"]["nullable"] is True

    command.downgrade(config, migration.down_revision)
    assert "cover_key" not in column_names(engine, "playlists")


def test_playlist_last_played_migration_keeps_existing_playlists_both_ways(database) -> None:
    migration = _migration("c3e7a91f5d20_add_playlist_last_played")
    config, _ = database
    engine = _upgrade_to_previous_of(database, migration)
    execute(
        engine,
        "INSERT INTO playlists (id, title, slug, created_at, updated_at) "
        "VALUES ('existing', 'Night Drive', 'night-drive', "
        "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
    )

    command.upgrade(config, migration.revision)

    inspector = inspect(engine)
    columns = {column["name"]: column for column in inspector.get_columns("playlists")}
    assert columns["last_played_at"]["nullable"] is True
    assert columns["last_played_song_id"]["nullable"] is True
    foreign_keys = {fk["name"]: fk for fk in inspector.get_foreign_keys("playlists")}
    song_key = foreign_keys["fk_playlists_last_played_song_id_songs"]
    assert song_key["referred_table"] == "songs"
    assert song_key["options"]["ondelete"] == "SET NULL"
    assert "ix_playlists_last_played_song_id" in {
        index["name"] for index in inspector.get_indexes("playlists")
    }
    with engine.begin() as connection:
        assert connection.execute(text(
            "SELECT title, last_played_at, last_played_song_id FROM playlists"
        )).one() == ("Night Drive", None, None)

    command.downgrade(config, migration.down_revision)

    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("playlists")}
    assert not {"last_played_at", "last_played_song_id"} & columns
    assert [fk["referred_table"] for fk in inspector.get_foreign_keys("playlists")] == ["users"]
    assert "ix_playlists_last_played_song_id" not in {
        index["name"] for index in inspector.get_indexes("playlists")
    }
    with engine.begin() as connection:
        assert connection.execute(text("SELECT title FROM playlists")).scalar_one() == (
            "Night Drive"
        )


def test_user_song_work_migration_adds_and_removes_the_table_around_existing_songs(
    database,
) -> None:
    migration = _migration("d4f8b2c6a1e7_add_user_song_work")
    config, _ = database
    engine = _upgrade_to_previous_of(database, migration)
    _seed_accounts(engine, "u1")
    _seed_album_with_song(engine)

    command.upgrade(config, migration.revision)

    inspector = inspect(engine)
    assert inspector.get_pk_constraint("user_song_work")["constrained_columns"] == [
        "user_id", "song_id",
    ]
    columns = {column["name"]: column for column in inspector.get_columns("user_song_work")}
    assert columns["edited_at"]["nullable"] is True
    assert columns["played_at"]["nullable"] is True
    assert {
        (fk["referred_table"], fk["options"]["ondelete"])
        for fk in inspector.get_foreign_keys("user_song_work")
    } == {("users", "CASCADE"), ("songs", "CASCADE")}
    with engine.begin() as connection:
        assert connection.execute(text("SELECT count(*) FROM user_song_work")).scalar_one() == 0
        connection.execute(text(
            "INSERT INTO user_song_work (user_id, song_id, played_at) "
            "VALUES ('u1', 's1', CURRENT_TIMESTAMP)"
        ))

    command.downgrade(config, migration.down_revision)

    assert "user_song_work" not in inspect(engine).get_table_names()
    with engine.begin() as connection:
        assert connection.execute(text("SELECT title FROM songs")).scalar_one() == "Thunder"


def test_generation_created_by_migration_keeps_existing_takes_unattributed_both_ways(
    database,
) -> None:
    migration = _migration("e5a9c3d7b2f1_add_generation_created_by")
    config, _ = database
    engine = _upgrade_to_previous_of(database, migration)
    _seed_accounts(engine, "u1")
    _seed_album_with_song(engine)
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO generations "
            "(id, song_id, generation_number, mp3_path, model_mode, status, is_archived, "
            "is_picked, is_kept, is_shared, created_at) "
            "VALUES ('g-old', 's1', 1, 'old.mp3', 'sft', 'completed', false, false, false, "
            "false, CURRENT_TIMESTAMP)"
        ))

    command.upgrade(config, migration.revision)

    inspector = inspect(engine)
    columns = {column["name"]: column for column in inspector.get_columns("generations")}
    assert columns["created_by"]["nullable"] is True
    assert {
        (fk["referred_table"], fk["options"]["ondelete"])
        for fk in inspector.get_foreign_keys("generations")
        if fk["constrained_columns"] == ["created_by"]
    } == {("users", "SET NULL")}
    with engine.begin() as connection:
        assert connection.execute(text(
            "SELECT created_by FROM generations WHERE id = 'g-old'"
        )).scalar_one() is None
        connection.execute(text(
            "INSERT INTO generations "
            "(id, song_id, generation_number, mp3_path, model_mode, status, is_archived, "
            "is_picked, is_kept, is_shared, created_at, created_by) "
            "VALUES ('g-new', 's1', 2, 'new.mp3', 'sft', 'completed', false, false, false, "
            "false, CURRENT_TIMESTAMP, 'u1')"
        ))

    command.downgrade(config, migration.down_revision)

    assert "created_by" not in column_names(engine, "generations")
    with engine.begin() as connection:
        assert connection.execute(text(
            "SELECT id FROM generations ORDER BY generation_number"
        )).scalars().all() == ["g-old", "g-new"]


def test_song_work_kind_migration_keeps_existing_work_unknown_both_ways(database) -> None:
    migration = _migration("5f4912bc4a31_add_user_song_work_kind_and_album_listen")
    config, _ = database
    engine = _upgrade_to_previous_of(database, migration)
    existing_work = "SELECT user_id, edited_at, played_at FROM user_song_work WHERE song_id = 's1'"
    _seed_accounts(engine, "u-old", "u-new")
    _seed_album_with_song(engine)
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO user_song_work (user_id, song_id, edited_at, played_at) "
            "VALUES ('u-old', 's1', '2026-10-01 10:00:00', '2026-10-02 11:00:00')"
        ))
        work_before = connection.execute(text(existing_work)).all()

    command.upgrade(config, migration.revision)

    columns = _columns(engine, "user_song_work")
    assert columns["edit_kind"]["nullable"] is True
    assert columns["album_played_at"]["nullable"] is True
    with engine.begin() as connection:
        assert connection.execute(text(
            "SELECT edit_kind, album_played_at FROM user_song_work WHERE user_id = 'u-old'"
        )).one() == (None, None)
        assert connection.execute(text(existing_work)).all() == work_before
        connection.execute(text(
            "INSERT INTO user_song_work "
            "(user_id, song_id, edited_at, edit_kind, played_at, album_played_at) "
            "VALUES ('u-new', 's1', CURRENT_TIMESTAMP, 'lyrics', CURRENT_TIMESTAMP, "
            "CURRENT_TIMESTAMP)"
        ))

    command.downgrade(config, migration.down_revision)

    assert not {"edit_kind", "album_played_at"} & column_names(engine, "user_song_work")
    with engine.begin() as connection:
        assert connection.execute(text(
            "SELECT user_id FROM user_song_work ORDER BY user_id"
        )).scalars().all() == ["u-new", "u-old"]
        assert connection.execute(text(
            existing_work + " AND user_id = 'u-old'"
        )).all() == work_before


def _seed_song_slug_migration_rows(engine, rows: list[tuple[str, str, str, int, str]]) -> None:
    """Seed the schema at b8e3f1c07a25 without importing the current ORM model."""
    albums = sa.Table("albums", sa.MetaData(), autoload_with=engine)
    songs = sa.Table("songs", albums.metadata, autoload_with=engine)
    album_ids = sorted({album_id for _, _, album_id, _, _ in rows})
    now = datetime.now(timezone.utc)

    with engine.begin() as conn:
        conn.execute(
            albums.insert(),
            [
                {
                    "id": album_id,
                    "title": album_id.upper(),
                    "artist": "X",
                    "subtitle": "",
                    "year": "",
                    "colors": [],
                    "created_at": now,
                }
                for album_id in album_ids
            ],
        )
        conn.execute(
            songs.insert(),
            [
                {
                    "id": song_id,
                    "title": title,
                    "album_id": album_id,
                    "vocal_language": "",
                    "track_number": track_number,
                    "created_at": now,
                    "updated_at": now,
                    "slug": slug,
                }
                for song_id, title, album_id, track_number, slug in rows
            ],
        )


def test_song_slug_backfill_fills_every_song_uniquely_per_album(database, monkeypatch) -> None:
    migration = _migration("b8e3f1c07a25_add_slug_to_songs")
    config, engine = database
    # c9d4a2f18e37 promotes the index to UNIQUE afterwards, which the seeded rows below
    # (multiple empty slugs per album) would violate.
    command.upgrade(config, SONG_SLUG_REVISION)
    _seed_song_slug_migration_rows(
        engine,
        [
            ("s1", "Intro", "a1", 1, ""),
            ("s2", "Intro", "a1", 2, ""),
            ("s3", "Intro", "a2", 1, ""),
            ("s4", "!!!", "a2", 2, ""),
            ("s5", "音" * 200, "a2", 3, ""),
            ("s6", "???", "a2", 4, ""),
        ],
    )

    _run_on(monkeypatch, migration, engine, migration._backfill_song_slugs)

    with engine.connect() as conn:
        slugs = dict(conn.execute(text("SELECT id, slug FROM songs")).fetchall())

    assert slugs["s1"] == "intro"
    assert slugs["s2"] == "intro-2"
    assert slugs["s3"] == "intro"
    assert slugs["s4"] == "untitled"
    assert slugs["s6"] == "untitled-2"

    cjk_slug = slugs["s5"]
    assert cjk_slug.startswith("yin-yin")
    assert len(cjk_slug) <= SONG_SLUG_MAX_LENGTH


def test_song_slug_index_promoted_to_unique_repairs_stragglers(database) -> None:
    """c9d4a2f18e37: repair pre-existing slug='' rows, then enforce UNIQUE.

    Simulates a song the co-writer created or renamed before slugs existed
    (slug='' surviving next to a sibling that already has a real slug),
    proving the migration both repairs the straggler and then blocks any
    new collision. downgrade() restores the plain, non-unique index.
    """
    config, engine = database
    command.upgrade(config, SONG_SLUG_REVISION)
    _seed_song_slug_migration_rows(
        engine,
        [
            ("s1", "Intro", "a1", 1, "intro"),
            # Straggler: created via the co-writer MCP path before slugs existed.
            ("s2", "Reprise", "a1", 2, ""),
        ],
    )

    command.upgrade(config, SONG_SLUG_UNIQUE_REVISION)

    with engine.begin() as conn:
        rows = dict(
            conn.execute(text("SELECT id, slug FROM songs")).fetchall(),
        )
    assert rows == {"s1": "intro", "s2": "reprise"}

    with engine.begin() as conn:
        duplicate_song = text(
            "INSERT INTO songs "
            "(id, title, album_id, vocal_language, track_number, created_at, "
            "updated_at, slug) "
            "VALUES ('s3', 'Dup', 'a1', '', 3, CURRENT_TIMESTAMP, "
            "CURRENT_TIMESTAMP, 'intro')"
        )
        with pytest.raises(IntegrityError):
            conn.execute(duplicate_song)

    command.downgrade(config, SONG_SLUG_REVISION)

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO songs "
                "(id, title, album_id, vocal_language, track_number, created_at, "
                "updated_at, slug) "
                "VALUES ('s3', 'Dup', 'a1', '', 3, CURRENT_TIMESTAMP, "
                "CURRENT_TIMESTAMP, 'intro')",
            ),
        )


def test_playlist_slug_migration_backfills_dedupes_and_enforces_unique(database) -> None:
    """d5f8a3b21c46: unlike the two-phase song migration (b8e3f1c07a25 then
    c9d4a2f18e37), playlists have no second write path to guard a window
    for, so backfill and UNIQUE(slug) land in one migration. Proves the
    upgrade dedupes existing (pre-migration) playlists sharing
    a title, handles a wide CJK title within the length budget, then blocks
    a real collision — and that downgrade() cleanly drops the column again.
    """
    config, engine = database
    # At the revision before this one 'playlists' has no slug column yet,
    # matching real pre-existing rows.
    command.upgrade(config, SONG_SLUG_UNIQUE_REVISION)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO playlists (id, title, is_shared, created_at, updated_at) "
                "VALUES (:id, :title, false, :ts, :ts)"
            ),
            [
                {"id": "p1", "title": "Favorites", "ts": "2026-01-01T00:00:00+00:00"},
                {"id": "p2", "title": "Favorites", "ts": "2026-01-02T00:00:00+00:00"},
                {"id": "p3", "title": "音" * 200, "ts": "2026-01-03T00:00:00+00:00"},
            ],
        )

    command.upgrade(config, PLAYLIST_SLUG_REVISION)

    with engine.begin() as conn:
        rows = dict(conn.execute(text("SELECT id, slug FROM playlists")).fetchall())

    assert rows["p1"] == "favorites"
    assert rows["p2"] == "favorites-2"
    cjk_slug = rows["p3"]
    assert cjk_slug.startswith("yin-yin")
    assert len(cjk_slug) <= PLAYLIST_SLUG_MAX_LENGTH

    with engine.begin() as conn:
        duplicate_playlist = text(
            "INSERT INTO playlists "
            "(id, title, slug, is_shared, created_at, updated_at) "
            "VALUES ('p4', 'Dup', 'favorites', false, CURRENT_TIMESTAMP, "
            "CURRENT_TIMESTAMP)"
        )
        with pytest.raises(IntegrityError):
            conn.execute(duplicate_playlist)

    command.downgrade(config, SONG_SLUG_UNIQUE_REVISION)

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO playlists (id, title, is_shared, created_at, updated_at) "
                "VALUES ('p5', 'Dup', false, '2026-01-04T00:00:00+00:00', "
                "'2026-01-04T00:00:00+00:00')"
            )
        )


def test_keycloak_migration_drops_the_password_era_shapes_and_every_session(database) -> None:
    migration = _migration("7c3e91d0a4b2_sign_in_through_keycloak")
    config, _ = database
    engine = _upgrade_to_previous_of(database, migration)
    _seed_accounts(engine, "u1", role="admin")
    execute(
        engine,
        "INSERT INTO user_sessions (id, user_id, created_at, expires_at, ip_address, "
        "user_agent) VALUES ('s1', 'u1', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, '', '')",
    )

    command.upgrade(config, migration.revision)

    inspector = inspect(engine)
    assert "login_attempts" not in inspector.get_table_names()
    assert {c["name"] for c in inspector.get_columns("users")}.isdisjoint(
        {"password_hash", "is_active"},
    )
    assert {c["name"] for c in inspector.get_columns("user_sessions")}.isdisjoint(
        {"ip_address", "user_agent"},
    )
    assert not any(index["unique"] for index in inspector.get_indexes("users"))
    assert "refresh_token" in {c["name"] for c in inspector.get_columns("user_sessions")}
    with engine.begin() as connection:
        assert connection.execute(text("SELECT count(*) FROM user_sessions")).scalar_one() == 0
        assert connection.execute(text("SELECT role FROM users")).scalar_one() == "admin"
        connection.execute(text(
            "INSERT INTO users (id, username, role, created_at, updated_at) "
            "VALUES ('u2', 'felix', 'user', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ))

    with engine.begin() as connection:
        connection.execute(text("DELETE FROM users WHERE id = 'u2'"))
    command.downgrade(config, migration.down_revision)

    inspector = inspect(engine)
    assert "login_attempts" in inspector.get_table_names()
    assert {"password_hash", "is_active"} <= {c["name"] for c in inspector.get_columns("users")}
    assert {"ip_address", "user_agent"} <= {
        c["name"] for c in inspector.get_columns("user_sessions")
    }
    assert "refresh_token" not in {c["name"] for c in inspector.get_columns("user_sessions")}


def test_id_token_migration_adds_and_removes_nullable_column_keeping_sessions(database) -> None:
    """Upgrade keeps rows with NULL id_token; downgrade drops it."""
    migration = _migration("a1d7c5e93b60_session_row_keeps_the_id_token")
    config, _ = database
    engine = _upgrade_to_previous_of(database, migration)
    _seed_accounts(engine, "u1")
    execute(
        engine,
        "INSERT INTO user_sessions (id, user_id, created_at, expires_at) "
        "VALUES ('s1', 'u1', '2026-10-01 00:00:00', '2026-10-08 00:00:00')",
    )

    def session_state() -> tuple[dict, list]:
        with engine.connect() as connection:
            ids = [row[0] for row in connection.execute(text("SELECT id FROM user_sessions"))]
        return _columns(engine, "user_sessions"), ids

    command.upgrade(config, migration.revision)
    columns, ids = session_state()
    assert columns["id_token"]["nullable"] is True
    assert ids == ["s1"]

    command.downgrade(config, migration.down_revision)
    columns, ids = session_state()
    assert "id_token" not in columns
    assert ids == ["s1"]
