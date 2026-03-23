"""Migrate existing filesystem data (_output/ + snapshots) into the database.

Scans album directories, reads snapshot .md files, and populates the DB.
Idempotent — skips versions that already exist (matched by mp3_path).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from sqlalchemy.orm import Session

from songmaker_cli.db.models import Album, Rating, Score, Song, SongRevision, Version
from songmaker_cli.manifest import parse_track_title
from songmaker_cli.parser import (
    AlbumMeta,
    extract_lyrics,
    find_lyrics_md,
    strip_version_suffix,
)
from songmaker_cli.scanner import extract_version_number, iter_album_scans
from songmaker_cli.snapshot import read_generation_info, read_scores

log = logging.getLogger(__name__)

SCORE_KEYS = frozenset({
    "lyrical_coherence", "lyrical_summary", "dynamics", "text_accuracy",
    "audiobox_enjoyment", "audiobox_understanding", "audiobox_complexity",
    "audiobox_quality", "silence_gaps", "spectral_artifacts",
    "dynamics_pitch_cv", "dynamics_rms_contrast", "dynamics_onset_cv",
    "bpm_detected", "bpm_deviation",
})


def migrate_filesystem(
    session: Session, output_dir: Path, project_root: Path,
) -> dict[str, int]:
    """Scan _output/ and import all albums, songs, and versions into the DB.

    Returns a dict of counts: {albums, songs, versions, scores, ratings, skipped}.
    """
    counts = {"albums": 0, "songs": 0, "versions": 0, "scores": 0, "ratings": 0, "skipped": 0}
    scans = iter_album_scans(output_dir, project_root)

    for scan in scans:
        album = _ensure_album(session, scan.album_name, scan.meta)
        if album.id not in [a.id for a in session.query(Album).all()]:
            counts["albums"] += 1

        song_cache: dict[str, Song] = {}

        for mp3 in scan.mp3s:
            mp3_path = f"{scan.mp3_base}/{mp3.name}"
            existing = session.query(Version).filter_by(mp3_path=mp3_path).first()
            if existing:
                counts["skipped"] += 1
                continue

            stem = mp3.stem
            base = strip_version_suffix(stem)
            version_num = extract_version_number(stem) or 1
            _, title = parse_track_title(stem)

            song = song_cache.get(base)
            if not song:
                song = _ensure_song(session, base, title, album, scan.lyrics_dir)
                song_cache[base] = song
                counts["songs"] += 1

            version = _create_version(session, song, mp3, scan.mp3_base, version_num)
            counts["versions"] += 1

            snapshot_path = mp3.with_suffix(".md")
            score_counts = _import_scores_and_rating(session, version, snapshot_path)
            counts["scores"] += score_counts["scores"]
            counts["ratings"] += score_counts["ratings"]

    session.commit()
    log.info(
        "Migration complete: %d albums, %d songs, %d versions, %d scores, %d ratings (%d skipped)",
        counts["albums"], counts["songs"], counts["versions"],
        counts["scores"], counts["ratings"], counts["skipped"],
    )
    return counts


def _ensure_album(session: Session, album_name: str, meta: AlbumMeta) -> Album:
    """Get or create an album by name."""
    album = session.query(Album).filter_by(id=album_name).first()
    if album:
        return album

    album = Album(
        id=album_name,
        title=meta.title,
        artist=meta.artist,
        subtitle=meta.subtitle,
        year=meta.year or "",
        colors=meta.colors or {"primary": "#ff3220", "bg": "#0d0d0d"},
    )
    session.add(album)
    session.flush()
    return album


def _ensure_song(
    session: Session, base_stem: str, title: str, album: Album, lyrics_dir: Path,
) -> Song:
    """Get or create a song, with its initial revision from lyrics."""
    existing = session.query(Song).filter_by(album_id=album.id, title=title).first()
    if existing:
        return existing

    track_match = re.match(r"^(\d+)_", base_stem)
    track_number = int(track_match.group(1)) if track_match else 0

    song = Song(
        title=title,
        album_id=album.id,
        track_number=track_number,
    )
    session.add(song)
    session.flush()

    lyrics, prompt, bpm, duration, key = _read_lyrics_source(base_stem, lyrics_dir)
    revision = SongRevision(
        song_id=song.id,
        lyrics=lyrics,
        prompt=prompt,
        bpm=bpm,
        duration=duration,
        key=key,
    )
    session.add(revision)
    session.flush()

    return song


def _read_lyrics_source(
    stem: str, lyrics_dir: Path,
) -> tuple[str, str, int, int, str]:
    """Read lyrics and metadata from the markdown source file."""
    md_file = find_lyrics_md(stem, lyrics_dir)
    if md_file is None:
        return "", "", 0, 0, ""

    import yaml
    text = md_file.read_text(encoding="utf-8")
    lyrics = extract_lyrics(text) or ""

    parts = text.split("---", 2)
    if len(parts) < 3:
        return lyrics, "", 0, 0, ""

    try:
        front = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        front = {}

    return (
        lyrics,
        front.get("prompt", ""),
        front.get("bpm", 0),
        front.get("duration", 0),
        front.get("key", ""),
    )


def _create_version(
    session: Session, song: Song, mp3: Path, mp3_base: str, version_num: int,
) -> Version:
    """Create a Version record for an MP3 file."""
    snapshot_path = mp3.with_suffix(".md")
    gen_info = read_generation_info(snapshot_path)

    whisper_path = mp3.with_suffix(".whisper")
    whisper_text = whisper_path.read_text(encoding="utf-8") if whisper_path.exists() else None

    version = Version(
        song_id=song.id,
        revision_id=song.latest_revision.id if song.latest_revision else None,
        version_number=version_num,
        seed=gen_info.get("seed") if gen_info else None,
        mp3_path=f"{mp3_base}/{mp3.name}",
        whisper_text=whisper_text,
        generation_params=dict(gen_info) if gen_info else None,
        status="completed",
    )
    session.add(version)
    session.flush()
    return version


def _import_scores_and_rating(
    session: Session, version: Version, snapshot_path: Path,
) -> dict[str, int]:
    """Import scores and rating from a snapshot .md file."""
    counts = {"scores": 0, "ratings": 0}
    score_data = read_scores(snapshot_path)
    if not score_data:
        return counts

    score_values: dict[str, object] = {}
    for key, value in score_data.items():
        if key in SCORE_KEYS:
            score_values[key] = value

    if score_values:
        score = Score(
            version_id=version.id,
            scorer="batch",
            value=score_values,
        )
        session.add(score)
        counts["scores"] = 1

    user_rating = score_data.get("user_rating")
    if isinstance(user_rating, (int, float)) and user_rating > 0:
        rating = Rating(
            version_id=version.id,
            rating=float(user_rating),
            notes=str(score_data.get("user_notes", "")),
        )
        session.add(rating)
        counts["ratings"] = 1

    return counts
