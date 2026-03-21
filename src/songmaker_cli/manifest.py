"""Manifest data model and building for the HTML player."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, TypedDict

import yaml

from songmaker_cli.constants import DEFAULT_ARTIST, default_year
from songmaker_cli.parser import extract_lyrics, find_lyrics_md, strip_version_suffix
from songmaker_cli.scanner import (
    AlbumScan,
    deduplicate_versions,
    extract_version_number,
    iter_album_scans,
)


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


class GenerationInfo(TypedDict, total=False):
    """Generation metadata from a sidecar snapshot .md."""

    seed: int
    acestep_model: str
    acestep_lm_model: str
    songmaker_version: str
    source: str
    generated_at: str
    bpm: int
    duration: int
    key: str
    guidance_scale: float
    inference_steps: int
    shift: float
    think_mode: bool
    lm_temperature: float
    infer_method: str


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


_GENERATION_KEYS = frozenset({
    "seed", "acestep_model", "acestep_lm_model", "songmaker_version",
    "source", "generated_at",
})

_FRONTMATTER_GEN_KEYS = frozenset({
    "bpm", "duration", "key", "guidance_scale", "inference_steps",
    "shift", "think_mode", "lm_temperature", "infer_method",
})


def read_generation_info(snapshot_path: Path) -> GenerationInfo | None:
    """Read generation metadata from a sidecar snapshot .md file."""
    if not snapshot_path.exists():
        return None

    text = snapshot_path.read_text(encoding="utf-8")
    info: GenerationInfo = {}

    parts = text.split("---", 2)
    if len(parts) >= 3:
        try:
            front = yaml.safe_load(parts[1]) or {}
        except yaml.YAMLError:
            front = {}
        if isinstance(front, dict):
            for key in _FRONTMATTER_GEN_KEYS:
                if key in front:
                    info[key] = front[key]  # type: ignore[literal-required]

    gen_match = re.search(r"## Generation\s*\n(.*?)(?=\n## |\Z)", text, re.DOTALL)
    if gen_match:
        for line in gen_match.group(1).splitlines():
            line = line.strip()
            if line.startswith("- ") and ": " in line:
                key, _, value = line[2:].partition(": ")
                if key in _GENERATION_KEYS:
                    info[key] = _coerce_value(value)  # type: ignore[literal-required]

    return info if info else None


def read_scores(snapshot_path: Path) -> dict[str, object] | None:
    """Read the ## Scores section from a snapshot .md file."""
    if not snapshot_path.exists():
        return None

    text = snapshot_path.read_text(encoding="utf-8")
    score_match = re.search(r"## Scores\s*\n(.*?)(?=\n## |\Z)", text, re.DOTALL)
    if not score_match:
        return None

    scores: dict[str, object] = {}
    for line in score_match.group(1).splitlines():
        line = line.strip()
        if line.startswith("- ") and ": " in line:
            key, _, value = line[2:].partition(": ")
            scores[key] = _coerce_value(value)

    return scores if scores else None


def _coerce_value(value: str) -> Any:
    """Try to parse a string value as int/float/bool."""
    if value.lower() in ("true", "false"):
        return value.lower() == "true"
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


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

        base = strip_version_suffix(stem)
        if lyrics_cache is not None and base in lyrics_cache:
            intended_lines = lyrics_cache[base]
        else:
            raw_lyrics = _find_lyrics_for_track(stem, lyrics_dir)
            intended_lines = lyrics_to_lines(raw_lyrics) if raw_lyrics else []

        lines = sung_lines if sung_lines else intended_lines

        snapshot_path = mp3.with_suffix(".md")
        generation = read_generation_info(snapshot_path)
        track_scores = read_scores(snapshot_path)

        tracks.append(TrackInfo(
            file=f"{mp3_base}/{mp3.name}",
            title=title,
            number=number,
            lines=lines,
            intended=intended_lines,
            has_sung=bool(sung_lines),
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

        snapshot_path = mp3.with_suffix(".md")
        generation = read_generation_info(snapshot_path)
        track_scores = read_scores(snapshot_path)

        track = TrackInfo(
            file=f"{scan.mp3_base}/{mp3.name}",
            title=f"{title} v{version}  [{scan.album_name}]",
            number=number,
            lines=intended_lines,
            intended=intended_lines,
            has_sung=False,
            generation=generation,
            scores=track_scores,
        )
        entries.append((mp3.stat().st_mtime, scan.album_name, track))
    return entries


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
