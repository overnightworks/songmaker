"""The view `backup_required_files`: the files a restored database must find in the audio root."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import pytest
from alembic import command
from PIL import Image
from sqlalchemy import inspect, text
from support.reference_rows import a_reference

from songmaker_cli.covers import write_album_cover, write_playlist_cover, write_song_cover
from songmaker_cli.db.models import (
    Album,
    AlbumCoverSuggestion,
    Generation,
    Job,
    Playlist,
    Song,
    User,
    Version,
)
from songmaker_cli.db.queries.generations import create_generation
from songmaker_cli.db.queries.loras import (
    add_user_lora_sample,
    create_user_lora,
    update_user_lora,
)

PREVIOUS_REVISION = "c9fba1723c68"
BACKUP_REVISION = "7d41e0b9a3c5"
VIEW = "backup_required_files"
TRASHED_AT = datetime(2026, 10, 1, tzinfo=timezone.utc)


@dataclass
class World:
    audio_dir: Path
    factory: object
    left_out: dict[str, str]
    still_required: dict[str, str]

    def listed(self) -> list[str]:
        with self.factory() as session:
            return list(session.execute(text(f"SELECT path FROM {VIEW} ORDER BY path")).scalars())

    def on_disk(self) -> list[str]:
        return sorted(
            path.relative_to(self.audio_dir).as_posix()
            for path in self.audio_dir.rglob("*") if path.is_file()
        )


def _cover_image(image_format: str) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (32, 24), (40, 80, 200)).save(buffer, format=image_format)
    return buffer.getvalue()


def _write_file(audio_dir: Path, relative: str) -> str:
    path = audio_dir / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"data")
    return relative


@pytest.fixture
def world(pg_factory, tmp_path: Path) -> World:
    audio_dir = tmp_path / "audio"
    left_out: dict[str, str] = {}
    still_required: dict[str, str] = {}
    with pg_factory() as session:
        owner = User(username="owner", role="user")
        session.add(owner)
        session.flush()
        _add_covers(session, audio_dir, owner.id, still_required, left_out)
        _add_takes(session, audio_dir, owner.id, still_required, left_out)
        _add_loras(session, audio_dir, owner.id, left_out)
        a_reference(session, owner.id, name="voice.mp3")
        _write_file(audio_dir, f"{owner.id}/refs/voice.mp3")
        _add_cover_suggestion_file(session, audio_dir, owner.id)
        session.commit()
    return World(audio_dir, pg_factory, left_out, still_required)


def _add_covers(session, audio_dir: Path, owner_id: str, still_required, left_out) -> None:
    trashed = Album(
        id="album-trashed", title="T", artist="T", created_by=owner_id, deleted_at=TRASHED_AT,
    )
    keyless = Album(id="album-keyless", title="K", artist="K", created_by=owner_id)
    live = Album(id="album-live", title="L", artist="L", created_by=owner_id)
    session.add_all([trashed, keyless, live])
    session.flush()
    trashed.cover_key = write_album_cover(audio_dir, trashed.id, _cover_image("JPEG"))
    live.cover_key = write_album_cover(audio_dir, live.id, _cover_image("PNG"))
    keyless.cover_key = "nodot"
    song = Song(id="song-covered", title="S", album_id=live.id, track_number=1)
    session.add(song)
    session.flush()
    song.cover_key = write_song_cover(audio_dir, song.id, _cover_image("PNG"))
    playlist = Playlist(id="playlist-covered", title="P", slug="p", created_by=owner_id)
    session.add(playlist)
    session.flush()
    playlist.cover_key = write_playlist_cover(audio_dir, playlist.id, _cover_image("JPEG"))
    still_required["a soft-deleted album's cover"] = "covers/album-trashed/card.jpg"
    left_out["a cover key with no dot"] = _write_file(audio_dir, "covers/album-keyless/card.jpg")


def _add_takes(session, audio_dir: Path, owner_id: str, still_required, left_out) -> None:
    album = session.get(Album, "album-live")
    song = Song(id="song-taken", title="S", album_id=album.id, track_number=2, slug="taken")
    session.add(song)
    session.flush()
    version = Version(song_id=song.id, lyrics="la", prompt="p")
    session.add(version)
    session.flush()

    def take(name: str, **row) -> Generation:
        _write_file(audio_dir, f"{owner_id}/{name}.mp3")
        return create_generation(
            session, song.id, version.id, f"{owner_id}/{name}.mp3", "turbo", audio_dir,
            created_by=owner_id, **row,
        )

    take("plain")
    archived = take("archived")
    archived.is_archived = True
    still_required["an archived take"] = f"{owner_id}/archived.mp3"
    take("with-wav", wav_path=_write_file(audio_dir, f"{owner_id}/with-wav.wav"))
    left_out["a take's wav"] = f"{owner_id}/with-wav.wav"
    left_out["a take's raw wav"] = _write_file(audio_dir, f"{owner_id}/with-wav.raw.wav")
    session.add(Generation(
        song_id=song.id, version_id=version.id, generation_number=99, mp3_path="",
        created_by=owner_id,
    ))


def _add_loras(session, audio_dir: Path, owner_id: str, left_out) -> None:
    root = f"user_loras/{owner_id}"
    ready = create_user_lora(session, owner_id, "Ready", "ready")
    update_user_lora(
        session, ready.id, status="ready", storage_path=f"{root}/{ready.id}/lora",
        tensor_path=f"{root}/{ready.id}/lora/legacy.safetensors",
    )
    _write_file(audio_dir, f"{root}/{ready.id}/lora/lokr_weights.safetensors")
    sample = _write_file(audio_dir, f"{root}/{ready.id}/samples/a.wav")
    add_user_lora_sample(session, ready.id, sample)
    add_user_lora_sample(session, ready.id, "")
    create_user_lora(session, owner_id, "Pathless", "pathless").status = "ready"
    training = create_user_lora(session, owner_id, "Training", "training")
    update_user_lora(
        session, training.id, status="training", storage_path=f"{root}/{training.id}/lora",
    )
    left_out["a LoRA's tensor_path"] = _write_file(
        audio_dir, f"{root}/{ready.id}/lora/legacy.safetensors",
    )
    left_out["a LoRA that is not ready"] = _write_file(
        audio_dir, f"{root}/{training.id}/lora/lokr_weights.safetensors",
    )


def _add_cover_suggestion_file(session, audio_dir: Path, owner_id: str) -> None:
    job = Job(type="cover", user_id=owner_id, album_id="album-live")
    session.add(job)
    session.flush()
    suggestion = AlbumCoverSuggestion(album_id="album-live", job_id=job.id, png_path="")
    session.add(suggestion)
    session.flush()
    suggestion.png_path = _write_file(
        audio_dir, f"cover-suggestions/album-live/{suggestion.id}.png",
    )


def test_the_view_lists_exactly_the_required_files_that_are_on_disk(world: World) -> None:
    optional_files = set(world.left_out.values())

    assert world.listed() == sorted(set(world.on_disk()) - optional_files)


@pytest.mark.parametrize("name", [
    "a soft-deleted album's cover",
    "an archived take",
])
def test_a_file_stays_listed_while_its_row_is_soft_deleted_or_archived(
    world: World, name: str,
) -> None:
    assert world.still_required[name] in world.listed()


@pytest.mark.parametrize("name", [
    "a take's wav",
    "a take's raw wav",
    "a LoRA that is not ready",
    "a LoRA's tensor_path",
    "a cover key with no dot",
])
def test_a_file_the_app_works_without_is_not_listed(world: World, name: str) -> None:
    path = world.left_out[name]

    assert (world.audio_dir / path).is_file()
    assert path not in world.listed()


def test_rows_without_a_path_list_nothing(world: World) -> None:
    assert not {"", None} & set(world.listed())


def test_a_png_cover_lists_the_png_original(world: World) -> None:
    listed = world.listed()

    assert "covers/album-live/original.png" in listed
    assert "covers/album-live/original.jpg" not in listed


def test_the_view_comes_and_goes_with_its_revision_and_no_table_changes(
    reference_link_database,
) -> None:
    config, engine = reference_link_database

    def views() -> set[str]:
        return set(inspect(engine).get_view_names())

    def tables() -> set[str]:
        return set(inspect(engine).get_table_names())

    command.upgrade(config, BACKUP_REVISION)
    tables_with_view = tables()
    assert VIEW in views()
    command.downgrade(config, PREVIOUS_REVISION)
    assert VIEW not in views()
    assert tables() == tables_with_view
    command.upgrade(config, BACKUP_REVISION)
    assert VIEW in views()
    assert tables() == tables_with_view
