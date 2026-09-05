# ruff: noqa: E402
"""Bulk-seed a song with many reimported-style takes directly against the database.

``frontend/e2e/kinetic-strip.spec.ts`` (issue #358) needs a song with dozens
of takes to genuinely overflow the take strip's scrollable container, in
both its row and column layouts — a real render, not an assumption, showed
that fewer than ~14 takes never overflow either at DESKTOP_VIEWPORT (the
column container simply grows to fit them). Seeding that many takes through
``POST /api/songs/{id}/reimport`` one at a time would repeat the exact
mistake issue #344 already found and fixed for the rail's filler albums:
the server's IP rate limiter counts every request it receives regardless of
which Playwright context sent it, and each of those calls exercises no API
semantics worth spending that budget on — they only need the rows and files
to exist. This does the same inserts (and the same file write) in one
process instead, mirroring ``songmaker_cli.reimport.reimport_files()``
field-for-field so the resulting rows are indistinguishable from a real
reimport.

The take audio has no fixture inside this container (``frontend/e2e/`` is
not part of the backend image), so it is read once from stdin — the caller
pipes ``frontend/e2e/fixtures/take.mp3`` in rather than this script owning
a copy of it.

Run inside the web container, where ``DATABASE_URL`` and the audio volume
are mounted. Use the venv's Python directly:

    docker compose exec -T songmaker-web /app/.venv/bin/python \\
        scripts/seed_e2e_song_takes.py \\
        --album-id e2e-album-mtizek8x --title "Kinetic Strip Takes" \\
        --take-count 25 --owner-username e2e-ci-admin \\
        < frontend/e2e/fixtures/take.mp3

Prints the created song's id on stdout. Connects to the database only —
never runs schema migrations, even implicitly, matching every other one-off
script here (see ``connect_db()`` in ``db/engine.py``).
"""

from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

from _repo_path import prepend_own_checkout_src
from sqlalchemy.orm import Session

prepend_own_checkout_src(__file__)

from songmaker_cli.api_helpers import unique_song_slug
from songmaker_cli.config import audio_file_path, find_project_root
from songmaker_cli.constants import MODEL_DEFAULT_MODE
from songmaker_cli.db.engine import connect_db, resolve_database_url
from songmaker_cli.db.queries import (
    create_generation,
    create_generation_created_event,
    create_song,
    get_user_by_username,
)
from songmaker_cli.settings import get_settings


def _resolve_audio_dir() -> Path:
    project_root = find_project_root(Path.cwd()) or Path.cwd()
    return project_root / get_settings().audio_dir


def seed_song_takes(
    session: Session,
    audio_dir: Path,
    mp3_bytes: bytes,
    *,
    album_id: str,
    title: str,
    take_count: int,
    owner_id: str,
) -> str:
    """Create one song under ``album_id`` with ``take_count`` takes.

    Mirrors ``reimport_files()`` field-for-field (same generated-id scheme,
    same per-user audio path, the same ``generation.created`` event) so the
    result is indistinguishable from ``take_count`` real reimports. Returns
    the created song's id.
    """
    slug = unique_song_slug(session, album_id, title)
    song = create_song(session, title, album_id, slug)

    for _ in range(take_count):
        generation_id = str(uuid.uuid4())
        dst = audio_file_path(audio_dir, owner_id, generation_id, ".mp3")
        dst.write_bytes(mp3_bytes)  # NOSONAR Uses validated audio path.
        gen = create_generation(
            session,
            song_id=song.id,
            version_id=None,
            mp3_path=f"{owner_id}/{generation_id}.mp3",
            model_mode=MODEL_DEFAULT_MODE,
            generation_id=generation_id,
            audio_dir=audio_dir,
        )
        create_generation_created_event(
            session, user_id=owner_id, song_id=song.id, generation_id=gen.id,
        )

    session.commit()
    return song.id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--album-id", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--take-count", type=int, required=True)
    parser.add_argument("--owner-username", required=True)
    args = parser.parse_args(argv)

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
        song_id = seed_song_takes(
            session,
            _resolve_audio_dir(),
            mp3_bytes,
            album_id=args.album_id,
            title=args.title,
            take_count=args.take_count,
            owner_id=owner.id,
        )

    print(song_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
