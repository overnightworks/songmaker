# ruff: noqa: E402
"""Report legacy generation MP3 paths that are not safe and canonical.

This operator audit never changes the database. Run it once against the live
database and mounted audio directory before deploying canonical MP3 writes:

    /app/.venv/bin/python scripts/audit_generation_audio_paths.py

Every reported row needs an operator decision. Reimport a take when its source
is known, or archive it until its file identity can be established. A blind
normalization could attach an existing generation to a different recording.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from pathlib import Path

from _repo_path import prepend_own_checkout_src
from sqlalchemy.orm import Session

prepend_own_checkout_src(__file__)

from songmaker_cli.audio_paths import canonical_audio_filename
from songmaker_cli.config import find_project_root
from songmaker_cli.db.engine import connect_db, resolve_database_url
from songmaker_cli.db.models import Generation
from songmaker_cli.settings import get_settings

log = logging.getLogger("audit_generation_audio_paths")


@dataclass(frozen=True)
class AudioPathMismatch:
    generation_id: str
    stored_path: str
    canonical_path: str | None


@dataclass(frozen=True)
class AudioPathAuditReport:
    canonical: int
    wav_only: int
    mismatches: list[AudioPathMismatch]


def _resolve_audio_dir() -> Path:
    project_root = find_project_root(Path.cwd()) or Path.cwd()
    return project_root / get_settings().audio_dir


def audit_generation_audio_paths(
    session: Session,
    audio_dir: Path,
) -> AudioPathAuditReport:
    canonical = 0
    wav_only = 0
    mismatches: list[AudioPathMismatch] = []
    generations = session.query(Generation).order_by(Generation.id).all()
    for generation in generations:
        if not generation.mp3_path:
            wav_only += 1
            continue
        canonical_path = canonical_audio_filename(audio_dir, generation.mp3_path)
        if canonical_path == generation.mp3_path:
            canonical += 1
            continue
        mismatches.append(AudioPathMismatch(
            generation_id=generation.id,
            stored_path=generation.mp3_path,
            canonical_path=canonical_path,
        ))
    return AudioPathAuditReport(
        canonical=canonical,
        wav_only=wav_only,
        mismatches=mismatches,
    )


def _print_report(report: AudioPathAuditReport) -> None:
    print(f"Canonical: {report.canonical}")
    print(f"WAV-only: {report.wav_only}")
    print(f"Mismatches: {len(report.mismatches)}")
    for mismatch in report.mismatches:
        canonical_path = mismatch.canonical_path or "outside audio directory"
        print(
            f"{mismatch.generation_id}: {mismatch.stored_path!r} -> {canonical_path!r}",
        )


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    factory = connect_db(resolve_database_url())
    with factory() as session:
        report = audit_generation_audio_paths(session, _resolve_audio_dir())
    _print_report(report)
    return 1 if report.mismatches else 0


if __name__ == "__main__":
    sys.exit(main())
