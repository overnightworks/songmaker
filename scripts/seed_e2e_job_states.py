# ruff: noqa: E402
"""Seed a song and its generate-job states directly against the database.

``frontend/e2e/song-phone.spec.ts`` (issue #995) proves the phone song page's
Takes list, its in-progress generation and a failed one -- but CI's e2e stack
(``docker-compose.ci.yml``) runs no ACE-Step worker, so none of those states
can come from a real generation. Reaching a song already at version 7 through
``take_count`` individual saves, or a running job through a real generate
call with no worker to advance it, would either cost requests the flow never
needs (the exact mistake issue #344 already found and fixed for the rail's
filler albums and the kinetic-strip takes) or simply never finish. This
writes the same rows a real editor session and a real worker would, through
the app's own query functions (``update_song``'s ``force_new_version`` path,
``create_generation``, ``create_job``, ``update_job_status``) -- never a
hand-built row shape.

Run inside the web container, where ``DATABASE_URL`` and the audio volume are
mounted. Use the venv's Python directly:

    docker compose exec -T songmaker-web /app/.venv/bin/python \\
        scripts/seed_e2e_job_states.py create-song \\
        --album-id e2e-album-mtizek8x --title "Song Phone Takes" \\
        --version-number 7 --take-count 2 --owner-username e2e-ci-admin \\
        < frontend/e2e/fixtures/take.mp3

    docker compose exec -T songmaker-web /app/.venv/bin/python \\
        scripts/seed_e2e_job_states.py set-running \\
        --song-id <id> --progress 0.36 --take-index 1 --take-count 2 \\
        --running-since-offset 64

    docker compose exec -T songmaker-web /app/.venv/bin/python \\
        scripts/seed_e2e_job_states.py set-failed \\
        --job-id <id> --error "ACE-Step worker: CUDA out of memory on device 0"

``create-song`` prints the created song's id on stdout, ``set-running`` the
created job's id -- both mirroring ``scripts/seed_e2e_song_takes.py``'s own
convention. ``set-failed`` prints nothing. Connects to the database only --
never runs schema migrations, even implicitly, matching every other one-off
script here (see ``connect_db()`` in ``db/engine.py``).
"""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from _repo_path import prepend_own_checkout_src
from sqlalchemy.orm import Session

prepend_own_checkout_src(__file__)

from songmaker_cli.api_helpers import unique_song_slug
from songmaker_cli.config import audio_file_path, find_project_root
from songmaker_cli.constants import MODEL_DEFAULT_MODE, JobStatus, JobType
from songmaker_cli.db.engine import connect_db, resolve_database_url
from songmaker_cli.db.models import Job
from songmaker_cli.db.queries import (
    create_generation,
    create_generation_created_event,
    create_job,
    create_song,
    get_user_by_username,
    update_job_status,
    update_song,
)
from songmaker_cli.settings import get_settings


def _resolve_audio_dir() -> Path:
    project_root = find_project_root(Path.cwd()) or Path.cwd()
    return project_root / get_settings().audio_dir


def seed_song_at_version(
    session: Session,
    audio_dir: Path,
    mp3_bytes: bytes,
    *,
    album_id: str,
    title: str,
    version_number: int,
    take_count: int,
    owner_id: str,
) -> str:
    """Create a song whose latest version is ``version_number``, with ``take_count`` takes on it.

    Each version bump beyond the song's first goes through ``update_song``'s
    own ``force_new_version`` path -- the same numbering a real editor save
    produces -- rather than writing ``Version.version_number`` by hand.
    Returns the song's id.
    """
    slug = unique_song_slug(session, album_id, title)
    # Real lyrics and a style prompt, carried forward by every later
    # force_new_version bump (update_song only replaces a field it is given):
    # without them the Generate button reads as "content missing" once its
    # job goes terminal, which outranks the failed-generation state the
    # song-phone flow needs to prove.
    song = create_song(
        session, title, album_id, slug,
        lyrics="Song Phone Takes seeded lyrics", prompt="calm test tone",
    )
    version = song.latest_version
    for _ in range(version_number - version.version_number):
        version = update_song(session, song.id, force_new_version=True)

    for _ in range(take_count):
        generation_id = str(uuid.uuid4())
        dst = audio_file_path(audio_dir, owner_id, generation_id, ".mp3")
        dst.write_bytes(mp3_bytes)  # NOSONAR Uses validated audio path.
        gen = create_generation(
            session,
            song_id=song.id,
            version_id=version.id,
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


def cmd_create_song(session: Session, args: argparse.Namespace) -> None:
    owner = get_user_by_username(session, args.owner_username)
    if owner is None:
        raise SystemExit(f"No user named {args.owner_username!r}")
    mp3_bytes = sys.stdin.buffer.read()
    if not mp3_bytes:
        raise SystemExit("No MP3 bytes received on stdin")
    song_id = seed_song_at_version(
        session,
        _resolve_audio_dir(),
        mp3_bytes,
        album_id=args.album_id,
        title=args.title,
        version_number=args.version_number,
        take_count=args.take_count,
        owner_id=owner.id,
    )
    print(song_id)


def cmd_set_running(session: Session, args: argparse.Namespace) -> None:
    """Attach a fresh running generate job to a song.

    ``update_job_status(..., JobStatus.RUNNING, ...)`` sets ``heartbeat_at``
    to now itself, so the job starts well inside
    ``GENERATE_JOB_HEARTBEAT_STALE_THRESHOLD_SECONDS`` with no further work
    here. ``running_since`` is backdated separately, by
    ``running_since_offset`` seconds, so the remaining-time estimate
    (``_remaining_time_estimate`` in ``api_models/jobs.py``) has real elapsed
    time to divide the remaining progress by.
    """
    job = create_job(session, JobType.GENERATE, user_id=None, song_id=args.song_id)
    update_job_status(
        session,
        job.id,
        JobStatus.RUNNING,
        progress=args.progress,
        take_index=args.take_index,
        take_count=args.take_count,
    )
    running_since = datetime.now(timezone.utc) - timedelta(seconds=args.running_since_offset)
    session.query(Job).filter_by(id=job.id).update({Job.running_since: running_since})
    session.commit()
    print(job.id)


def cmd_set_failed(session: Session, args: argparse.Namespace) -> None:
    """Fail an existing job in place.

    Transitioning a still-open job (rather than creating a new, already-failed
    one) is deliberate: ``/api/jobs/{id}/stream`` polls the row and pushes the
    change to any client still watching it, the same way a real worker crash
    would report it.
    """
    updated = update_job_status(
        session, args.job_id, JobStatus.FAILED, error=args.error, error_type="generation_failed",
    )
    if not updated:
        raise SystemExit(f"Job {args.job_id} was already terminal or does not exist")
    session.commit()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_song = sub.add_parser(
        "create-song", help="Seed a song already at a given version, with real takes on it.",
    )
    p_song.add_argument("--album-id", required=True)
    p_song.add_argument("--title", required=True)
    p_song.add_argument("--version-number", type=int, required=True)
    p_song.add_argument("--take-count", type=int, required=True)
    p_song.add_argument("--owner-username", required=True)
    p_song.set_defaults(func=cmd_create_song)

    p_running = sub.add_parser("set-running", help="Attach a running generate job to a song.")
    p_running.add_argument("--song-id", required=True)
    p_running.add_argument("--progress", type=float, required=True)
    p_running.add_argument("--take-index", type=int, required=True)
    p_running.add_argument("--take-count", type=int, required=True)
    p_running.add_argument("--running-since-offset", type=float, required=True)
    p_running.set_defaults(func=cmd_set_running)

    p_failed = sub.add_parser(
        "set-failed", help="Fail an existing job with a literal worker sentence.",
    )
    p_failed.add_argument("--job-id", required=True)
    p_failed.add_argument("--error", required=True)
    p_failed.set_defaults(func=cmd_set_failed)

    args = parser.parse_args(argv)

    factory = connect_db(resolve_database_url())
    with factory() as session:
        args.func(session, args)

    return 0


if __name__ == "__main__":
    sys.exit(main())
