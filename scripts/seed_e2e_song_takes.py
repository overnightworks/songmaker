# ruff: noqa: E402
"""Seed playable takes directly against the database for the end-to-end specs.

The specs that need a song with takes (the take folds, menu, rail and share
flows) seed them here, either on a song this script creates or on a song the
spec already created through the API (``--song-id``). Seeding takes one
request at a time would spend the server's IP rate limiter, which counts every
request regardless of which Playwright context sent it (issue #344), on calls
that exercise no API semantics.

Each take is a generation row (``created_by`` the owner, ``mp3_path`` as
``<owner id>/<generation id>.mp3``, the default model mode, no seed) with its
audio file under the audio directory and a ``generation_created`` event for
the owner. A take has no version unless the song is created here with lyrics
or a prompt, which links each take to the song's version like a generated one.

The take audio has no fixture inside this container (``frontend/e2e/`` is
not part of the backend image), so it is read once from stdin; the caller
pipes ``frontend/e2e/fixtures/take.mp3`` in rather than this script owning
a copy of it.

Run inside the web container, where ``DATABASE_URL`` and the audio volume
are mounted. Use the venv's Python directly:

    docker compose exec -T songmaker-web /app/.venv/bin/python \\
        scripts/seed_e2e_song_takes.py \\
        --album-id e2e-album-mtizek8x --title "Many Takes" \\
        --take-count 25 --owner-username e2e-ci-admin \\
        < frontend/e2e/fixtures/take.mp3

Prints the song's id on stdout. Connects to the database only; never runs
schema migrations, even implicitly, matching every other one-off script here
(see ``connect_db()`` in ``db/engine.py``).
"""
# ruff: noqa: T201 - this seed helper prints the song id its caller reads

from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path

from repo_path import prepend_own_checkout_src
from sqlalchemy.orm import Session

prepend_own_checkout_src(__file__)

from songmaker_cli.api_helpers import unique_song_slug
from songmaker_cli.config import find_project_root
from songmaker_cli.constants import MODEL_DEFAULT_MODE
from songmaker_cli.db.engine import connect_db, resolve_database_url
from songmaker_cli.db.queries.auth import get_user_by_username
from songmaker_cli.db.queries.generations import create_generation
from songmaker_cli.db.queries.resource_events import create_generation_created_event
from songmaker_cli.db.queries.songs import create_song
from songmaker_cli.settings import get_settings


def _resolve_audio_dir() -> Path:
    project_root = find_project_root(Path.cwd()) or Path.cwd()
    return project_root / get_settings().audio_dir


def _add_takes(
    session: Session,
    audio_dir: Path,
    mp3_bytes: bytes,
    song_id: str,
    version_id: str | None,
    take_count: int,
    owner_id: str,
) -> None:
    owner_directory_name = os.path.basename(owner_id)
    if owner_directory_name in ("", ".", "..") or owner_directory_name != owner_id:
        raise ValueError(f"Owner id is not a single directory name: {owner_id!r}")
    owner_directory = Path(audio_dir) / owner_directory_name
    for _ in range(take_count):
        generation_id = str(uuid.uuid4())
        owner_directory.mkdir(parents=True, exist_ok=True)
        (owner_directory / f"{generation_id}.mp3").write_bytes(mp3_bytes)
        gen = create_generation(
            session,
            song_id=song_id,
            version_id=version_id,
            mp3_path=f"{owner_id}/{generation_id}.mp3",
            model_mode=MODEL_DEFAULT_MODE,
            generation_id=generation_id,
            audio_dir=audio_dir,
            created_by=owner_id,
        )
        create_generation_created_event(
            session,
            user_id=owner_id,
            song_id=song_id,
            generation_id=gen.id,
        )


def seed_takes_into_song(
    session: Session,
    audio_dir: Path,
    mp3_bytes: bytes,
    *,
    song_id: str,
    take_count: int,
    owner_id: str,
) -> None:
    """Add ``take_count`` versionless takes to a song that already exists."""
    _add_takes(session, audio_dir, mp3_bytes, song_id, None, take_count, owner_id)
    session.commit()


def seed_song_takes(
    session: Session,
    audio_dir: Path,
    mp3_bytes: bytes,
    *,
    album_id: str,
    title: str,
    take_count: int,
    owner_id: str,
    lyrics: str = "",
    prompt: str = "",
) -> str:
    """Create one song under ``album_id`` with ``take_count`` takes.

    Passing lyrics or a prompt links each take to the song's version, so
    consumers receive the same metadata as a generated take. Returns the
    song's id.
    """
    slug = unique_song_slug(session, album_id, title)
    song = create_song(session, title, album_id, slug, lyrics=lyrics, prompt=prompt)
    version_id = song.latest_version.id if lyrics or prompt else None
    _add_takes(session, audio_dir, mp3_bytes, song.id, version_id, take_count, owner_id)
    session.commit()
    return song.id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--song-id", help="add the takes to this song instead of creating one")
    parser.add_argument("--album-id")
    parser.add_argument("--title")
    parser.add_argument("--take-count", type=int, required=True)
    parser.add_argument("--owner-username", required=True)
    parser.add_argument("--lyrics", default="")
    parser.add_argument("--prompt", default="")
    args = parser.parse_args(argv)
    if args.song_id is None and not (args.album_id and args.title):
        parser.error("--album-id and --title are required unless --song-id is given")

    mp3_bytes = sys.stdin.buffer.read()
    if not mp3_bytes:
        print("No MP3 bytes received on stdin", file=sys.stderr)
        return 1

    factory = connect_db(resolve_database_url())
    with factory() as session:
        owner = get_user_by_username(session, args.owner_username)
        if owner is None:
            print(f"No user named {args.owner_username!r}", file=sys.stderr)
            return 1
        if args.song_id is not None:
            seed_takes_into_song(
                session,
                _resolve_audio_dir(),
                mp3_bytes,
                song_id=args.song_id,
                take_count=args.take_count,
                owner_id=owner.id,
            )
            song_id = args.song_id
        else:
            song_id = seed_song_takes(
                session,
                _resolve_audio_dir(),
                mp3_bytes,
                album_id=args.album_id,
                title=args.title,
                take_count=args.take_count,
                owner_id=owner.id,
                lyrics=args.lyrics,
                prompt=args.prompt,
            )

    print(song_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
