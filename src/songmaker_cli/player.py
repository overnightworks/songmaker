"""Generate a manifest.json and static HTML player for all albums.

The player reads track metadata from manifest.json and ID3 tags from MP3 files
at runtime using jsmediatags. The HTML is written once and never needs
regeneration — only manifest.json updates when new songs are generated.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from string import Template

from songmaker_cli.constants import DEFAULT_ARTIST, DEFAULT_YEAR

_TEMPLATE_DIR = Path(__file__).parent / "templates"

DEFAULT_COLOR = {"primary": "#ff3220", "bg": "#0d0d0d"}


def _extract_version_number(stem: str) -> int:
    """Extract numeric version from a stem like '01_song_v3' -> 3. Returns 0 if none."""
    match = re.search(r"_v(\d+)$", stem)
    return int(match.group(1)) if match else 0


@dataclass
class TrackInfo:
    """A single track in the manifest."""

    file: str
    title: str
    number: str
    lines: list[dict] = field(default_factory=list)
    intended: list[dict] = field(default_factory=list)
    has_sung: bool = False


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


def _parse_srt(path: Path) -> list[dict]:
    """Parse an SRT file into [{time: float, text: str}, ...]."""
    lines = []
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


def _parse_album_yaml(path: Path) -> dict:
    """Parse album.yaml — delegates to parser module."""
    from songmaker_cli.parser import parse_album_yaml

    meta = parse_album_yaml(path)
    return {
        "title": meta.title,
        "artist": meta.artist,
        "subtitle": meta.subtitle,
        "year": meta.year,
        "colors": meta.colors,
    }


def _find_lyrics_for_track(track_stem: str, lyrics_dir: Path) -> str | None:
    """Find lyrics from a markdown file matching the track stem."""
    from songmaker_cli.parser import find_lyrics_md

    md_file = find_lyrics_md(track_stem, lyrics_dir)
    if md_file is None:
        return None
    return _extract_lyrics(md_file)


def _extract_lyrics(md_path: Path) -> str | None:
    """Extract lyrics section from a markdown song file."""
    from songmaker_cli.parser import extract_lyrics

    text = md_path.read_text(encoding="utf-8")
    return extract_lyrics(text)


def _lyrics_to_lines(lyrics: str) -> list[dict]:
    """Convert raw lyrics text to simple display lines (no timestamps)."""
    lines = []
    for line in lyrics.splitlines():
        line = line.strip()
        if not line:
            continue
        if re.match(r"^\[.+\]$", line):
            lines.append({"time": -1, "text": line.upper(), "section": True})
        else:
            lines.append({"time": -1, "text": line, "section": False})
    return lines


def _deduplicate_versions(mp3s: list[Path]) -> list[Path]:
    """Keep only the latest version of each track (e.g., v2 over v1)."""
    from songmaker_cli.parser import strip_version_suffix

    by_base: dict[str, tuple[int, Path]] = {}
    for mp3 in mp3s:
        base = strip_version_suffix(mp3.stem)
        if base.endswith("_raw"):
            continue
        version = _extract_version_number(mp3.stem)
        if base not in by_base or version > by_base[base][0]:
            by_base[base] = (version, mp3)
    return sorted(p for _, p in by_base.values())


def generate_player(output_dir: Path, project_root: Path | None = None) -> Path:
    """Scan all albums, write manifest.json, and ensure player.html exists.

    Args:
        output_dir: Where to write files (usually _output/).
        project_root: Project root for finding album.yaml and lyrics.

    Returns:
        Path to the player.html.
    """
    if project_root is None:
        project_root = output_dir.parent

    manifest = _build_manifest(output_dir, project_root)
    manifest_dict = manifest.to_dict()

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest_dict, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    player_path = output_dir / "player.html"
    manifest_json = json.dumps(manifest_dict, ensure_ascii=False)
    html = _render_static_html(manifest_json, DEFAULT_ARTIST, DEFAULT_YEAR)
    player_path.write_text(html, encoding="utf-8")

    return player_path


def _parse_track_title(stem: str) -> tuple[str, str]:
    """Extract (number, title) from an MP3 stem like '01_song_name_v3'."""
    num_match = re.match(r"^(\d+)_(.+?)(?:_v\d+)?$", stem)
    bonus_match = re.match(r"^(bonus)_(.+?)(?:_v\d+)?$", stem)
    if num_match:
        return num_match.group(1), num_match.group(2).replace("_", " ").title()
    if bonus_match:
        return "B", bonus_match.group(2).replace("_", " ").title()
    return "?", stem.replace("_", " ").title()


def _scan_album_tracks(
    mp3s: list[Path],
    mp3_base: str,
    lyrics_dir: Path,
) -> list[TrackInfo]:
    """Build track dataclasses from a list of MP3 files."""
    tracks = []
    for mp3 in mp3s:
        stem = mp3.stem
        number, title = _parse_track_title(stem)

        srt_path = mp3.with_suffix(".srt")
        sung_lines = _parse_srt(srt_path) if srt_path.exists() else []

        raw_lyrics = _find_lyrics_for_track(stem, lyrics_dir)
        intended_lines = _lyrics_to_lines(raw_lyrics) if raw_lyrics else []

        lines = sung_lines if sung_lines else intended_lines

        tracks.append(TrackInfo(
            file=f"{mp3_base}/{mp3.name}",
            title=title,
            number=number,
            lines=lines,
            intended=intended_lines,
            has_sung=bool(sung_lines),
        ))
    return tracks


def _build_manifest(output_dir: Path, project_root: Path) -> Manifest:
    """Build the manifest data structure from album directories."""
    albums_data: list[AlbumInfo] = []

    for album_dir in sorted(output_dir.iterdir()):
        if not album_dir.is_dir():
            continue

        album_name = album_dir.name

        final_dir = album_dir / "final"
        if final_dir.exists():
            mp3s = sorted(final_dir.glob("*.mp3"))
            mp3_base = f"{album_name}/final"
        else:
            mp3s = sorted(album_dir.glob("*.mp3"))
            mp3s = _deduplicate_versions(mp3s)
            mp3_base = album_name

        if not mp3s:
            continue

        album_yaml = project_root / "albums" / album_name / "album.yaml"
        if album_yaml.exists():
            album_meta = _parse_album_yaml(album_yaml)
        else:
            album_meta = {"title": album_name.replace("_", " ").title()}

        lyrics_dir = project_root / "albums" / album_name / "lyrics"
        tracks = _scan_album_tracks(mp3s, mp3_base, lyrics_dir)
        colors = album_meta.get("colors") or DEFAULT_COLOR

        albums_data.append(AlbumInfo(
            id=album_name,
            title=album_meta.get("title", album_name),
            artist=album_meta.get("artist", DEFAULT_ARTIST),
            subtitle=album_meta.get("subtitle", ""),
            year=album_meta.get("year", DEFAULT_YEAR),
            colors=colors,
            tracks=tracks,
        ))

    latest_tracks = _build_latest_tracks(output_dir, project_root)
    if latest_tracks:
        albums_data.insert(0, AlbumInfo(
            id="_latest",
            title="Latest",
            artist=DEFAULT_ARTIST,
            subtitle="All versions, newest first",
            year=DEFAULT_YEAR,
            colors={"primary": "#22cc44", "bg": "#0d0d0d"},
            tracks=latest_tracks,
        ))

    return Manifest(albums=albums_data)


def _build_latest_tracks(output_dir: Path, project_root: Path) -> list[TrackInfo]:
    """Collect all tracks across albums sorted by newest first."""
    entries: list[tuple[float, str, TrackInfo]] = []

    for album_dir in sorted(output_dir.iterdir()):
        if not album_dir.is_dir():
            continue
        album_name = album_dir.name
        lyrics_dir = project_root / "albums" / album_name / "lyrics"

        final_dir = album_dir / "final"
        scan_dir = final_dir if final_dir.exists() else album_dir
        mp3s = [mp3 for mp3 in scan_dir.glob("*.mp3") if not mp3.stem.endswith("_raw")]
        for mp3 in mp3s:
            stem = mp3.stem
            number, title = _parse_track_title(stem)
            version_match = re.search(r"_v(\d+)$", stem)
            version = version_match.group(1) if version_match else "1"

            raw_lyrics = _find_lyrics_for_track(stem, lyrics_dir)
            intended_lines = _lyrics_to_lines(raw_lyrics) if raw_lyrics else []

            track = TrackInfo(
                file=f"{album_name}/{mp3.name}",
                title=f"{title} v{version}  [{album_name}]",
                number=number,
                lines=intended_lines,
                intended=intended_lines,
                has_sung=False,
            )
            entries.append((mp3.stat().st_mtime, album_name, track))

    entries.sort(key=lambda e: e[0], reverse=True)
    return [track for _, _, track in entries]


def _render_static_html(
    manifest_json: str = "null",
    artist: str = DEFAULT_ARTIST,
    year: str = DEFAULT_YEAR,
) -> str:
    """Render the HTML player from template with variable substitution."""
    template_path = _TEMPLATE_DIR / "player.html"
    template = Template(template_path.read_text(encoding="utf-8"))
    return template.substitute(
        ARTIST=artist,
        YEAR=year,
        MANIFEST_JSON=manifest_json,
    )
