"""One-time backfill of ``Generation.audio_duration_sec`` for existing takes.

Since #258, every newly generated take stores its measured audio length in
``Generation.audio_duration_sec``. Takes generated before that carry
``NULL`` there, so playlist views and the public share pages (album, song,
generation, playlist) show no duration for them at all. This script measures
the MP3 header of every such take and fills the column, reusing
``queue_streams.read_audio_duration()`` — the same probe the live app already
uses on a generation GET.

Modes:

* Dry-run (default) — probe every unmeasured row's file and report how many
  rows would be filled, how many are already measured, and how many files
  are missing or unreadable. Writes nothing.
* ``--apply`` — same probe, but stores the measured duration and commits in
  batches (``COMMIT_BATCH_SIZE`` rows at a time), so an interrupted run keeps
  whatever it already wrote instead of losing it all to a rollback. Only
  ``audio_duration_sec IS NULL`` rows are touched, so a rerun after a partial
  or complete run is harmless — already-filled rows are skipped.

This connects to the database only — it never runs schema migrations,
even implicitly. A one-time data script must not drag the schema to head
as a side effect of connecting: if a deploy migration failed or is still
pending, this script fails or reports on the schema as it finds it,
never advances it. See ``connect_db()`` in ``db/engine.py``.

Two runs racing against the same not-yet-measured row can both probe and
write it; harmless, since both read the same file on disk and write the
same value, so the final row is correct either way.

Run inside the web container, where ``DATABASE_URL`` and the audio volume
are mounted. Use the venv's Python directly — bare ``python`` on the
container's ``PATH`` is the package-less system interpreter, not the app's:

    docker compose exec songmaker-web /app/.venv/bin/python \
        scripts/backfill_audio_durations.py
    docker compose exec songmaker-web /app/.venv/bin/python \
        scripts/backfill_audio_durations.py --apply

Run the dry-run first and read the counts before passing ``--apply``.
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from sqlalchemy.orm import Session

from songmaker_cli import queue_streams
from songmaker_cli.config import find_project_root
from songmaker_cli.db.engine import connect_db, resolve_database_url
from songmaker_cli.db.models import Generation
from songmaker_cli.settings import get_settings

log = logging.getLogger("backfill_audio_durations")

COMMIT_BATCH_SIZE: Final[int] = 500


@dataclass(frozen=True)
class BackfillReport:
    filled: int
    skipped_already_measured: int
    missing_or_unreadable: int


def _resolve_audio_dir() -> Path:
    project_root = find_project_root(Path.cwd()) or Path.cwd()
    return project_root / get_settings().audio_dir


def _unmeasured_generations(session: Session) -> list[Generation]:
    return (
        session.query(Generation)
        .filter(Generation.audio_duration_sec.is_(None))
        .order_by(Generation.id)
        .all()
    )


def run_backfill(session: Session, audio_dir: Path, *, apply: bool) -> BackfillReport:
    """Probe every unmeasured generation's file and, if ``apply``, store it.

    Always probes every candidate file (even in dry-run) so the reported
    counts match exactly what ``--apply`` would do. Commits every
    ``COMMIT_BATCH_SIZE`` rows so a long run against the live database
    doesn't hold one giant transaction.
    """
    skipped_already_measured = (
        session.query(Generation)
        .filter(Generation.audio_duration_sec.isnot(None))
        .count()
    )
    candidates = _unmeasured_generations(session)

    filled = 0
    missing_or_unreadable = 0
    for index, generation in enumerate(candidates, start=1):
        duration = queue_streams.read_audio_duration(audio_dir / generation.mp3_path)
        if duration is None:
            missing_or_unreadable += 1
            log.warning("Could not measure audio duration for %s", generation.mp3_path)
            continue

        filled += 1
        if apply:
            generation.audio_duration_sec = duration
            if index % COMMIT_BATCH_SIZE == 0:
                session.commit()

    if apply:
        session.commit()

    return BackfillReport(
        filled=filled,
        skipped_already_measured=skipped_already_measured,
        missing_or_unreadable=missing_or_unreadable,
    )


def _print_report(report: BackfillReport, *, applied: bool) -> None:
    verb = "Filled" if applied else "Would fill"
    print(f"{verb}: {report.filled}")
    print(f"Skipped (already measured): {report.skipped_already_measured}")
    print(f"Missing or unreadable: {report.missing_or_unreadable}")
    if not applied:
        print("\nDry run only — nothing written. Rerun with --apply to write these values.")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true",
        help="Write measured durations. Without this flag, dry-run only (default).",
    )
    args = parser.parse_args(argv)

    audio_dir = _resolve_audio_dir()
    factory = connect_db(resolve_database_url())
    with factory() as session:
        report = run_backfill(session, audio_dir, apply=args.apply)

    _print_report(report, applied=args.apply)
    return 0


if __name__ == "__main__":
    sys.exit(main())
