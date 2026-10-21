"""Tests for ``scripts/merge_accounts_into_subject.py`` (PostgreSQL only).

The script folds every account into one Keycloak subject. Each test seeds a
throwaway PostgreSQL database and a temporary audio directory in the shape the
operator's live system has: one admin, two active and three inactive accounts.
"""

from __future__ import annotations

import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, select, text, update
from sqlalchemy.exc import DBAPIError

from songmaker_cli.db.models import (
    Album,
    AuditLog,
    ChatMessage,
    Conversation,
    CowriterUserMemory,
    Generation,
    GenerationPreset,
    Job,
    Playlist,
    RateLimitSetting,
    ResourceEvent,
    ResourceEventCursor,
    Song,
    UserLora,
    UserLoraSample,
    UserSongWork,
    Version,
)
from songmaker_cli.settings import get_settings

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import merge_accounts_into_subject as merge  # noqa: E402

ARCHIVED_AT = datetime(2026, 1, 2, tzinfo=timezone.utc)
SIGN_IN_REVISION = "7c3e91d0a4b2"


@dataclass
class LiveShape:
    engine: Engine
    audio_dir: Path
    cache_dir: Path
    operator: str
    active: list[str]
    inactive: list[str]
    subject: str
    lora_id: str

    @property
    def everyone(self) -> list[str]:
        return [self.operator, *self.active, *self.inactive]

    def run(self, mode: merge.Mode = merge.Mode.APPLY, **overrides) -> int:
        arguments = {
            "audio_dir": self.audio_dir,
            "stream_cache_dir": self.cache_dir,
            "operator_id": self.operator,
            "subject": self.subject,
            "mode": mode,
        } | overrides
        return merge.run(self.engine, **arguments)

    def write(self, relative: str, content: bytes = b"audio") -> Path:
        path = self.audio_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def fingerprint(self) -> tuple[dict[str, list[str]], list[str]]:
        with self.engine.connect() as connection:
            rows = {
                table.name: sorted(
                    repr(tuple(row)) for row in connection.execute(select(table))
                )
                for table in merge.reflect_live_schema(self.engine).sorted_tables
            }
        files = sorted(
            str(path.relative_to(self.audio_dir)) for path in self.audio_dir.rglob("*")
        )
        return rows, files


def _seed_accounts(session, operator: str, active: list[str], inactive: list[str]) -> None:
    """Insert accounts and sessions in the pre-cutover shape, which the models no longer have."""
    accounts = [(operator, "felix", "admin", True)]
    accounts += [(a, f"active-{n}", "user", True) for n, a in enumerate(active)]
    accounts += [(a, f"inactive-{n}", "user", False) for n, a in enumerate(inactive)]
    for account, username, role, is_active in accounts:
        session.execute(text(
            "INSERT INTO users (id, username, password_hash, role, is_active,"
            " default_generation_config, created_at, updated_at) VALUES (:id, :username,"
            " :password_hash, :role, :is_active, 'preset-default', now(), now())"
        ), {
            "id": account, "username": username, "password_hash": f"hash-{username}",
            "role": role, "is_active": is_active,
        })
    expires = datetime(2030, 1, 1, tzinfo=timezone.utc)
    for owner in (operator, operator, active[0]):
        session.execute(text(
            "INSERT INTO user_sessions (id, user_id, created_at, expires_at, ip_address,"
            " user_agent) VALUES (:id, :user_id, now(), :expires, '', '')"
        ), {"id": uuid.uuid4().hex, "user_id": owner, "expires": expires})


def _seed_live_shape_library(session, shape: LiveShape) -> None:
    operator, first_active = shape.operator, shape.active[0]
    inactive_owner = shape.inactive[0]
    session.add_all([
        Album(id="album-live", title="Live", artist="F", created_by=operator),
        Album(
            id="album-trashed", title="Trashed", artist="F", created_by=operator,
            deleted_at=ARCHIVED_AT,
        ),
        Album(id="album-inactive", title="Inactive", artist="X", created_by=inactive_owner),
        Album(id="album-ownerless", title="Ownerless", artist="X", created_by=None),
        Song(id="song-live", title="One", album_id="album-live", slug="one"),
        Song(id="song-inactive", title="Two", album_id="album-inactive", slug="two"),
    ])
    session.flush()
    session.add_all([
        Version(
            id="version-live", song_id="song-live",
            generation_params={"reference_audio_path": f"{operator}/refs/ref.wav"},
        ),
        Generation(
            id="gen-operator", song_id="song-live", version_id="version-live",
            generation_number=1, created_by=operator,
            mp3_path=f"{operator}/gen-operator.mp3", wav_path=f"{operator}/gen-operator.wav",
            generation_params={"reference_audio_path": f"{operator}/refs/ref.wav"},
        ),
        Generation(
            id="gen-active", song_id="song-live", generation_number=2,
            created_by=first_active, mp3_path=f"{first_active}/gen-active.mp3",
        ),
        Generation(
            id="gen-missing", song_id="song-inactive", generation_number=1,
            created_by=inactive_owner, mp3_path=f"{inactive_owner}/gen-missing.mp3",
        ),
        Generation(
            id="gen-ownerless", song_id="song-inactive", generation_number=2,
            created_by=None, mp3_path="legacy/gen-ownerless.mp3",
        ),
        Playlist(id="playlist-live", title="Faves", slug="faves", created_by=operator),
        GenerationPreset(
            id="preset-operator", name="Mine", model_mode="turbo", is_default=True,
            created_by=operator,
        ),
        GenerationPreset(
            id="preset-active", name="Theirs", model_mode="turbo", is_default=True,
            created_by=first_active,
            params={"reference_audio_path": f"{first_active}/refs/preset.wav"},
        ),
    ])
    for relative in (
        f"{operator}/gen-operator.mp3", f"{operator}/gen-operator.wav",
        f"{operator}/refs/ref.wav", f"{operator}/.hidden",
        f"{first_active}/gen-active.mp3", f"{first_active}/refs/preset.wav",
        f"{inactive_owner}/unrelated.txt", "legacy/gen-ownerless.mp3",
    ):
        shape.write(relative)


def _seed_lora(session, shape: LiveShape) -> None:
    root = f"user_loras/{shape.operator}/{shape.lora_id}"
    session.add_all([
        UserLora(
            id=shape.lora_id, user_id=shape.operator, name="Voice", slug="voice",
            storage_path=f"{root}/out", tensor_path=f"{root}/out/adapter.safetensors",
        ),
        UserLora(id=str(uuid.uuid4()), user_id=shape.active[0], name="Other", slug="other"),
    ])
    session.flush()
    session.add(UserLoraSample(
        user_lora_id=shape.lora_id, audio_path=f"{root}/dataset/take.wav",
    ))
    shape.write(f"{root}/out/adapter.safetensors")
    shape.write(f"{root}/dataset/take.wav")


def _seed_ownership_tables(session, shape: LiveShape) -> None:
    operator, first_active, second_active = shape.operator, *shape.active
    session.add_all([
        UserSongWork(user_id=operator, song_id="song-live", edited_at=ARCHIVED_AT),
        UserSongWork(user_id=first_active, song_id="song-live", played_at=ARCHIVED_AT),
        UserSongWork(user_id=second_active, song_id="song-inactive"),
        CowriterUserMemory(user_id=operator, body="likes minor keys"),
        CowriterUserMemory(user_id=first_active, body="likes brass"),
        ResourceEventCursor(user_id=operator, high_water_mark=1),
        ResourceEventCursor(user_id=first_active, high_water_mark=1),
        ResourceEvent(
            user_id=operator, sequence=1, kind="a", resource_type="song",
            resource_id="song-live", generation_id="g-a",
        ),
        ResourceEvent(
            user_id=first_active, sequence=1, kind="a", resource_type="song",
            resource_id="song-live", generation_id="g-b",
        ),
        RateLimitSetting(user_id=operator, setting_key="jobs", value=5),
        RateLimitSetting(user_id=first_active, setting_key="jobs", value=9),
        RateLimitSetting(user_id=None, setting_key="jobs", value=1),
    ])
    conversations = [
        Conversation(id="conv-operator", user_id=operator),
        Conversation(id="conv-active", user_id=first_active),
        Conversation(id="conv-archived", user_id=first_active, archived_at=ARCHIVED_AT),
    ]
    session.add_all(conversations)
    session.flush()
    session.add_all([
        ChatMessage(conversation_id="conv-operator", role="user", content=f"I am {operator}"),
        Job(id="job-done", type="generate", status="completed", user_id=operator,
            error=f"owner {operator} left"),
        AuditLog(user_id=operator, action="login", resource_type="user", resource_id=operator,
                 detail=f"user {operator} signed in"),
    ])


@pytest.fixture
def pre_cutover_factory(pg_factory):
    """The database in the shape the script meets: before the sign-in migration ran."""
    url = pg_factory.kw["bind"].url.render_as_string(hide_password=False)
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.stamp(config, SIGN_IN_REVISION)
    command.downgrade(config, "-1")
    yield pg_factory
    with pg_factory.kw["bind"].begin() as connection:
        connection.execute(
            text("DROP TABLE IF EXISTS bookmarks, login_attempts, alembic_version CASCADE"),
        )


@pytest.fixture
def live_shape(pre_cutover_factory, tmp_path: Path) -> LiveShape:
    new_id = lambda: str(uuid.uuid4())  # noqa: E731
    shape = LiveShape(
        engine=pre_cutover_factory.kw["bind"], audio_dir=tmp_path / "audio",
        cache_dir=tmp_path / "queue-streams", operator=new_id(),
        active=[new_id(), new_id()], inactive=[new_id(), new_id(), new_id()],
        subject=new_id(), lora_id=new_id(),
    )
    shape.audio_dir.mkdir()
    shape.cache_dir.mkdir()
    (shape.cache_dir / "stream.mp3").write_bytes(b"cached")
    with pre_cutover_factory() as session:
        _seed_accounts(session, shape.operator, shape.active, shape.inactive)
        _seed_live_shape_library(session, shape)
        _seed_lora(session, shape)
        _seed_ownership_tables(session, shape)
        session.commit()
    return shape


def _scalar(shape: LiveShape, sql: str, **parameters):
    with shape.engine.connect() as connection:
        return connection.execute(text(sql), parameters).scalar_one()


def _column(shape: LiveShape, sql: str, **parameters) -> list:
    with shape.engine.connect() as connection:
        return list(connection.execute(text(sql), parameters).scalars())


def test_six_accounts_end_owned_by_the_subject_with_files_moved(
    live_shape: LiveShape, capsys: pytest.CaptureFixture[str],
) -> None:  # T1
    shape, subject = live_shape, live_shape.subject
    assert shape.run() == 0
    output = capsys.readouterr().out
    for check in ("V1", "V2", "V3", "V4", "V5"):
        assert f"{check} ok" in output

    # accounts
    assert _column(shape, "SELECT id FROM users") == [subject]
    assert _scalar(shape, "SELECT role FROM users") == "admin"
    assert _scalar(shape, "SELECT username FROM users") == "felix"
    assert _scalar(shape, "SELECT password_hash FROM users") == "hash-felix"
    assert "hash-felix" not in output
    assert _scalar(shape, "SELECT count(*) FROM user_sessions") == 0

    # ownership, soft-deleted rows included
    for table, column in (
        ("albums", "created_by"), ("generations", "created_by"),
        ("playlists", "created_by"), ("jobs", "user_id"), ("audit_log", "user_id"),
        ("generation_presets", "created_by"), ("user_loras", "user_id"),
        ("conversations", "user_id"),
    ):
        owners = set(_column(shape, f"SELECT DISTINCT {column} FROM {table}"))
        assert owners <= {subject, None}, table
    assert _scalar(shape, "SELECT count(*) FROM albums WHERE created_by = :s", s=subject) == 3
    assert _scalar(shape, "SELECT count(*) FROM albums WHERE created_by IS NULL") == 1

    # adjustments and singleton tables
    defaults = _column(shape, "SELECT id FROM generation_presets WHERE is_default")
    assert defaults == ["preset-operator"]
    active_conversations = _column(shape, "SELECT id FROM conversations WHERE archived_at IS NULL")
    assert active_conversations == ["conv-operator"]
    for table in (
        "user_song_work", "cowriter_user_memories", "resource_event_cursors", "resource_events",
    ):
        assert _column(shape, f"SELECT user_id FROM {table}") == [subject], table
    assert sorted(_column(shape, "SELECT value FROM rate_limit_settings")) == [1, 5]

    # paths
    assert _column(shape, "SELECT mp3_path FROM generations WHERE id = 'gen-operator'") == [
        f"{subject}/gen-operator.mp3",
    ]
    assert _scalar(
        shape, "SELECT generation_params->>'reference_audio_path' FROM generations "
        "WHERE id = 'gen-operator'",
    ) == f"{subject}/refs/ref.wav"
    assert _scalar(
        shape, "SELECT generation_params->>'reference_audio_path' FROM versions",
    ) == f"{subject}/refs/ref.wav"
    assert _scalar(
        shape, "SELECT params->>'reference_audio_path' FROM generation_presets "
        "WHERE id = 'preset-active'",
    ) == f"{subject}/refs/preset.wav"
    lora_root = f"user_loras/{subject}/{shape.lora_id}"
    stored_lora = _scalar(shape, "SELECT storage_path FROM user_loras WHERE slug = 'voice'")
    assert stored_lora == f"{lora_root}/out"
    stored_sample = _scalar(shape, "SELECT audio_path FROM user_lora_samples")
    assert stored_sample == f"{lora_root}/dataset/take.wav"

    # files
    for relative in (
        "gen-operator.mp3", "refs/ref.wav", ".hidden", "gen-active.mp3",
        "refs/preset.wav", "unrelated.txt",
    ):
        assert (shape.audio_dir / subject / relative).is_file(), relative
    assert (shape.audio_dir / lora_root / "out" / "adapter.safetensors").is_file()
    assert (shape.audio_dir / "legacy" / "gen-ownerless.mp3").is_file()
    for account in shape.everyone:
        assert not (shape.audio_dir / account).exists()
        assert not (shape.audio_dir / "user_loras" / account).exists()

    # history stays as written, and the stream cache is empty
    assert shape.operator in _scalar(shape, "SELECT detail FROM audit_log")
    assert shape.operator in _scalar(shape, "SELECT error FROM jobs")
    assert list(shape.cache_dir.iterdir()) == []

    # a repeated run refuses
    assert shape.run() == 1
    assert "unknown" in capsys.readouterr().out


def _plant_target(shape: LiveShape) -> dict:
    shape.write(f"{shape.subject}/gen-operator.mp3", b"squatter")
    return {}


def _queue_job(shape: LiveShape) -> dict:
    with shape.engine.begin() as connection:
        connection.execute(update(Job.__table__).values(status="queued"))
    return {}


def _link_into_old_directory(shape: LiveShape) -> dict:
    (shape.audio_dir / shape.active[0] / "escape").symlink_to(shape.audio_dir / "legacy")
    return {}


def _collide_lora_slug(shape: LiveShape) -> dict:
    with shape.engine.begin() as connection:
        connection.execute(update(UserLora.__table__).values(slug="voice"))
    return {}


def _add_unpoliced_foreign_key(shape: LiveShape) -> dict:
    with shape.engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE bookmarks (id varchar(36) PRIMARY KEY,"
            " owner_id varchar(36) REFERENCES users (id))"
        ))
    return {}


def _unknown_origin(shape: LiveShape) -> dict:
    return {"operator_id": str(uuid.uuid4())}


@pytest.mark.parametrize(
    ("prepare", "subject", "expected"),
    [
        pytest.param(_plant_target, None, "already exists", id="T2-planted-target"),
        pytest.param(_queue_job, None, "job", id="T3-queued-job"),
        pytest.param(_link_into_old_directory, None, "escape", id="symlink-under-old-directory"),
        pytest.param(_collide_lora_slug, None, "voice", id="lora-slug-collision"),
        pytest.param(
            _add_unpoliced_foreign_key, None, "bookmarks.owner_id", id="T6-unpoliced-foreign-key",
        ),
        pytest.param(_unknown_origin, None, "unknown", id="unknown-from"),
        pytest.param(lambda shape: {}, "not-a-uuid", "subject", id="T7-malformed"),
        pytest.param(lambda shape: {}, "SHORT", "subject", id="T7-short"),
        pytest.param(
            lambda shape: {}, str(uuid.uuid4()).upper(), "subject", id="T7-uppercase",
        ),
        pytest.param(
            lambda shape: {"subject": shape.active[1]}, None, "subject", id="T7-existing-id",
        ),
    ],
)
def test_refusal_leaves_database_and_files_untouched(
    live_shape: LiveShape, capsys: pytest.CaptureFixture[str],
    prepare: Callable[[LiveShape], dict], subject: str | None, expected: str,
) -> None:
    overrides = prepare(live_shape)
    if subject is not None:
        overrides = {"subject": subject}
    before = live_shape.fingerprint()
    for mode in (merge.Mode.DRY_RUN, merge.Mode.APPLY):
        assert live_shape.run(mode, **overrides) == 1
        assert expected in capsys.readouterr().out
        assert live_shape.fingerprint() == before


def test_dry_run_reports_counts_and_changes_nothing(
    live_shape: LiveShape, capsys: pytest.CaptureFixture[str],
) -> None:  # T4
    before = live_shape.fingerprint()
    assert live_shape.run(merge.Mode.DRY_RUN) == 0
    output = capsys.readouterr().out
    assert "albums.created_by" in output
    assert "REFUSED" not in output
    assert live_shape.fingerprint() == before
    assert (live_shape.cache_dir / "stream.mp3").is_file()


def test_verify_fails_on_an_old_id_planted_outside_the_inventory(
    live_shape: LiveShape, capsys: pytest.CaptureFixture[str],
) -> None:  # T5
    with live_shape.engine.begin() as connection:
        connection.execute(
            update(Album.__table__).where(Album.id == "album-live")
            .values(subtitle=f"made by {live_shape.operator}"),
        )
    assert live_shape.run() == 1
    output = capsys.readouterr().out
    assert "V5 FAILED" in output
    assert "albums.subtitle" in output
    assert "V1 ok" in output


def test_verify_fails_when_a_rewritten_path_does_not_resolve(
    live_shape: LiveShape, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    move_files = merge._move_files

    def lose_a_file_after_moving(plan, audio_dir) -> None:
        move_files(plan, audio_dir)
        (audio_dir / live_shape.subject / "gen-operator.mp3").unlink()

    monkeypatch.setattr(merge, "_move_files", lose_a_file_after_moving)
    assert live_shape.run() == 1
    output = capsys.readouterr().out
    assert "V4 FAILED" in output
    assert "restore.sh" in output


def test_missing_files_before_the_run_are_not_a_failure(
    live_shape: LiveShape, capsys: pytest.CaptureFixture[str],
) -> None:
    assert not (live_shape.audio_dir / live_shape.inactive[0] / "gen-missing.mp3").exists()
    assert live_shape.run() == 0
    assert "V4 ok" in capsys.readouterr().out
    assert _scalar(
        live_shape, "SELECT mp3_path FROM generations WHERE id = 'gen-missing'",
    ) == f"{live_shape.subject}/gen-missing.mp3"


def test_command_line_dry_runs_then_applies_with_the_configured_directories(
    live_shape: LiveShape, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", str(live_shape.engine.url.render_as_string(False)))
    monkeypatch.setenv("AUDIO_DIR", str(live_shape.audio_dir))
    monkeypatch.setenv("DATA_DIR", str(live_shape.cache_dir.parent))
    get_settings.cache_clear()
    arguments = ["--from", live_shape.operator, "--subject", live_shape.subject]
    try:
        before = live_shape.fingerprint()
        assert merge.main(arguments) == 0
        assert live_shape.fingerprint() == before
        assert merge.main([*arguments, "--apply"]) == 0
        assert "V5 ok" in capsys.readouterr().out
        assert merge.main([*arguments, "--apply"]) == 1
    finally:
        get_settings.cache_clear()
    assert list(live_shape.cache_dir.iterdir()) == []


def _database_error_carrying(password_hash: str) -> BaseException:
    return DBAPIError(
        "INSERT INTO users (password_hash) VALUES (%(password_hash)s)",
        {"password_hash": password_hash}, Exception("duplicate key\nDETAIL: more"),
    )


@pytest.mark.parametrize(
    "failure_for", [_database_error_carrying, lambda _hash: KeyboardInterrupt()],
)
def test_a_failed_apply_prints_no_traceback_and_no_password_hash(
    live_shape: LiveShape, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
    failure_for: Callable[[str], BaseException],
) -> None:
    password_hash = _scalar(
        live_shape, f"SELECT password_hash FROM users WHERE id = '{live_shape.operator}'",
    )

    def fail(*_arguments) -> None:
        raise failure_for(password_hash)

    monkeypatch.setattr(merge, "_merge_database", fail)
    assert live_shape.run() == 1
    error = capsys.readouterr().err
    assert "restore.sh" in error
    assert "Traceback" not in error
    assert password_hash not in error
