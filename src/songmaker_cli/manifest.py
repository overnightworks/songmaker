"""Manifest data model and building for the HTML player."""

from __future__ import annotations

import datetime
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TypedDict

from songmaker_cli.constants import DEFAULT_ARTIST, default_year
from songmaker_cli.parser import extract_lyrics, find_lyrics_md, strip_version_suffix
from songmaker_cli.scanner import (
    AlbumScan,
    deduplicate_versions,
    extract_version_number,
    iter_album_scans,
)
from songmaker_cli.snapshot import GenerationInfo, read_generation_info, read_scores


class SrtLine(TypedDict):
    """A timed subtitle line from an SRT file."""

    time: float
    text: str


class LyricsLine(TypedDict):
    """A display line from parsed lyrics (no timestamps)."""

    time: float
    text: str
    section: bool


def _default_color() -> dict[str, str]:
    return {"primary": "#ff3220", "bg": "#0d0d0d"}


@dataclass
class TrackInfo:
    """A single track in the manifest."""

    file: str
    title: str
    number: str
    lines: list[SrtLine | LyricsLine] = field(default_factory=list)
    intended: list[LyricsLine] = field(default_factory=list)
    has_sung: bool = False
    generation: GenerationInfo | None = None
    scores: dict[str, object] | None = None


@dataclass
class AlbumInfo:
    """An album entry in the manifest."""

    id: str
    title: str
    artist: str
    subtitle: str
    year: str
    colors: dict[str, str]
    tracks: list[TrackInfo]


@dataclass
class Manifest:
    """Top-level manifest for the HTML player."""

    albums: list[AlbumInfo]

    def to_dict(self) -> dict:
        return asdict(self)


def parse_srt(path: Path) -> list[SrtLine]:
    """Parse an SRT file into [{time: float, text: str}, ...]."""
    lines: list[SrtLine] = []
    text = path.read_text(encoding="utf-8", errors="replace")
    blocks = re.split(r"\n\n+", text.strip())
    for block in blocks:
        parts = block.strip().split("\n")
        if len(parts) < 3:
            continue
        ts_match = re.match(
            r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->", parts[1],
        )
        if not ts_match:
            continue
        h, m, s, ms = ts_match.groups()
        time_sec = int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000
        txt = " ".join(parts[2:]).strip()
        if txt:
            lines.append({"time": round(time_sec, 1), "text": txt})
    return lines


def parse_track_title(stem: str) -> tuple[str, str]:
    """Extract (number, title) from an MP3 stem like '01_song_name_v3'."""
    num_match = re.match(r"^(\d+)_(.+?)(?:_v\d+)?$", stem)
    bonus_match = re.match(r"^(bonus)_(.+?)(?:_v\d+)?$", stem)
    if num_match:
        return num_match.group(1), num_match.group(2).replace("_", " ").title()
    if bonus_match:
        return "B", bonus_match.group(2).replace("_", " ").title()
    return "?", stem.replace("_", " ").title()


def lyrics_to_lines(lyrics: str) -> list[LyricsLine]:
    """Convert raw lyrics text to simple display lines (no timestamps)."""
    lines: list[LyricsLine] = []
    for line in lyrics.splitlines():
        line = line.strip()
        if not line:
            continue
        if re.match(r"^\[.+\]$", line):
            lines.append({"time": -1, "text": line.upper(), "section": True})
        else:
            lines.append({"time": -1, "text": line, "section": False})
    return lines


def _find_lyrics_for_track(track_stem: str, lyrics_dir: Path) -> str | None:
    """Find lyrics from a markdown file matching the track stem."""
    md_file = find_lyrics_md(track_stem, lyrics_dir)
    if md_file is None:
        return None
    text = md_file.read_text(encoding="utf-8")
    return extract_lyrics(text)


def scan_album_tracks(
    mp3s: list[Path],
    mp3_base: str,
    lyrics_dir: Path,
    lyrics_cache: dict[str, list[LyricsLine]] | None = None,
) -> list[TrackInfo]:
    """Build track dataclasses from a list of MP3 files."""
    tracks = []
    for mp3 in mp3s:
        stem = mp3.stem
        number, title = parse_track_title(stem)

        srt_path = mp3.with_suffix(".srt")
        sung_lines = parse_srt(srt_path) if srt_path.exists() else []

        whisper_path = mp3.with_suffix(".whisper")
        whisper_lines: list[LyricsLine] = []
        if whisper_path.exists():
            whisper_text = whisper_path.read_text(encoding="utf-8").strip()
            whisper_lines = [
                {"time": -1, "text": line.strip(), "section": False}
                for line in whisper_text.splitlines() if line.strip()
            ]

        base = strip_version_suffix(stem)
        if lyrics_cache is not None and base in lyrics_cache:
            intended_lines = lyrics_cache[base]
        else:
            raw_lyrics = _find_lyrics_for_track(stem, lyrics_dir)
            intended_lines = lyrics_to_lines(raw_lyrics) if raw_lyrics else []

        # Priority: SRT > Whisper transcription > intended lyrics
        lines = sung_lines or whisper_lines or intended_lines
        has_transcription = bool(sung_lines or whisper_lines)

        snapshot_path = mp3.with_suffix(".md")
        generation = read_generation_info(snapshot_path)
        track_scores = read_scores(snapshot_path)

        tracks.append(TrackInfo(
            file=f"{mp3_base}/{mp3.name}",
            title=title,
            number=number,
            lines=lines,
            intended=intended_lines,
            has_sung=has_transcription,
            generation=generation,
            scores=track_scores,
        ))
    return tracks


def _build_lyrics_cache(mp3s: list[Path], lyrics_dir: Path) -> dict[str, list[LyricsLine]]:
    """Build a cache of stem -> intended_lines for all MP3s in an album."""
    cache: dict[str, list[LyricsLine]] = {}
    for mp3 in mp3s:
        stem = mp3.stem
        base = strip_version_suffix(stem)
        if base not in cache:
            raw_lyrics = _find_lyrics_for_track(stem, lyrics_dir)
            cache[base] = lyrics_to_lines(raw_lyrics) if raw_lyrics else []
    return cache


def _build_latest_entries(
    scan: AlbumScan,
    lyrics_cache: dict[str, list[LyricsLine]],
) -> list[tuple[float, str, TrackInfo]]:
    """Build "latest" view entries from all versions of an album's tracks."""
    entries: list[tuple[float, str, TrackInfo]] = []
    for mp3 in scan.mp3s:
        stem = mp3.stem
        number, title = parse_track_title(stem)
        version = extract_version_number(stem) or 1
        base = strip_version_suffix(stem)
        intended_lines = lyrics_cache.get(base, [])

        whisper_path = mp3.with_suffix(".whisper")
        whisper_lines: list[LyricsLine] = []
        if whisper_path.exists():
            whisper_text = whisper_path.read_text(encoding="utf-8").strip()
            whisper_lines = [
                {"time": -1, "text": line.strip(), "section": False}
                for line in whisper_text.splitlines() if line.strip()
            ]

        lines = whisper_lines or intended_lines
        has_transcription = bool(whisper_lines)

        snapshot_path = mp3.with_suffix(".md")
        generation = read_generation_info(snapshot_path)
        track_scores = read_scores(snapshot_path)

        track = TrackInfo(
            file=f"{scan.mp3_base}/{mp3.name}",
            title=f"{title} v{version}  [{scan.album_name}]",
            number=number,
            lines=lines,
            intended=intended_lines,
            has_sung=has_transcription,
            generation=generation,
            scores=track_scores,
        )
        sort_key = _generation_timestamp(generation) or mp3.stat().st_mtime
        entries.append((sort_key, scan.album_name, track))
    return entries


def _generation_timestamp(generation: GenerationInfo | None) -> float | None:
    """Extract a sortable timestamp from snapshot metadata, falling back to None."""
    if generation is None:
        return None
    generated_at = generation.get("generated_at")
    if not generated_at:
        return None
    try:
        return datetime.datetime.fromisoformat(str(generated_at)).timestamp()
    except (ValueError, TypeError):
        return None


def build_manifest(output_dir: Path, project_root: Path) -> Manifest:
    """Build the manifest data structure from album directories.

    Scans album directories once. Lyrics are cached per album to avoid
    redundant filesystem lookups across deduplicated and latest views.
    """
    all_scans = iter_album_scans(output_dir, project_root)
    albums_data: list[AlbumInfo] = []
    latest_entries: list[tuple[float, str, TrackInfo]] = []

    for scan in all_scans:
        lyrics_cache = _build_lyrics_cache(scan.mp3s, scan.lyrics_dir)

        deduped_mp3s = deduplicate_versions(scan.mp3s)
        deduped_tracks = scan_album_tracks(
            deduped_mp3s, scan.mp3_base, scan.lyrics_dir, lyrics_cache,
        )
        albums_data.append(AlbumInfo(
            id=scan.album_name,
            title=scan.meta.title,
            artist=scan.meta.artist,
            subtitle=scan.meta.subtitle,
            year=scan.meta.year or default_year(),
            colors=scan.meta.colors or _default_color(),
            tracks=deduped_tracks,
        ))

        latest_entries.extend(_build_latest_entries(scan, lyrics_cache))

    if latest_entries:
        latest_entries.sort(key=lambda e: e[0], reverse=True)
        albums_data.insert(0, AlbumInfo(
            id="_latest",
            title="Latest",
            artist=DEFAULT_ARTIST,
            subtitle="All versions, newest first",
            year=default_year(),
            colors={"primary": "#22cc44", "bg": "#0d0d0d"},
            tracks=[track for _, _, track in latest_entries],
        ))

    return Manifest(albums=albums_data)
