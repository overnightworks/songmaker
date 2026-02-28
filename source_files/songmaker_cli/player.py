"""Generate a universal HTML player for all albums."""

from __future__ import annotations

import json
import re
from pathlib import Path


def _parse_srt(path: Path) -> list[dict]:
    """Parse an SRT file into [{time: float, text: str}, ...]."""
    lines = []
    text = path.read_text(encoding="utf-8", errors="replace")
    blocks = re.split(r"\n\n+", text.strip())
    for block in blocks:
        parts = block.strip().split("\n")
        if len(parts) < 3:
            continue
        # Parse timestamp: 00:01:23,456 --> 00:01:27,890
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
    """Minimal YAML parser for album.yaml (key: value pairs only)."""
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r'^(\w+):\s*"?([^"]*)"?\s*$', line)
        if match:
            result[match.group(1)] = match.group(2).strip()
    return result


def _find_lyrics_for_track(track_stem: str, lyrics_dir: Path) -> str | None:
    """Find lyrics from a markdown file matching the track stem."""
    # Try exact match first (e.g., 01_still_here)
    for md_file in lyrics_dir.glob("*.md"):
        if md_file.stem == track_stem:
            return _extract_lyrics(md_file)
    # Try partial match (strip version suffix like _v1)
    base = re.sub(r"_v\d+$", "", track_stem)
    for md_file in lyrics_dir.glob("*.md"):
        if md_file.stem == base:
            return _extract_lyrics(md_file)
    return None


def _extract_lyrics(md_path: Path) -> str | None:
    """Extract lyrics section from a markdown song file."""
    text = md_path.read_text(encoding="utf-8")
    match = re.search(r"## Lyrics\s*\n(.*?)(?=\n## |\Z)", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return None


def _lyrics_to_lines(lyrics: str) -> list[dict]:
    """Convert raw lyrics text to simple display lines (no timestamps)."""
    lines = []
    for line in lyrics.splitlines():
        line = line.strip()
        if not line:
            continue
        # Section tags become labels
        if re.match(r"^\[.+\]$", line):
            lines.append({"time": -1, "text": line.upper(), "section": True})
        else:
            lines.append({"time": -1, "text": line, "section": False})
    return lines


# Album theme colors
ALBUM_COLORS = {
    "apologiez": {"primary": "#ff3220", "bg": "#0d0d0d"},
    "feelings": {"primary": "#6a9fd8", "bg": "#0a0a14"},
    "midnight_frequency": {"primary": "#9b59b6", "bg": "#0d0a14"},
    "download_days": {"primary": "#e67e22", "bg": "#0d0d0a"},
}
DEFAULT_COLOR = {"primary": "#ff3220", "bg": "#0d0d0d"}


def generate_player(output_dir: Path, project_root: Path | None = None) -> Path:
    """Scan all albums and generate a unified HTML player.

    Args:
        output_dir: Where to write player.html (usually _output/).
        project_root: Project root for finding album.yaml and lyrics.
                      Defaults to output_dir.parent.

    Returns:
        Path to the generated player.html.
    """
    if project_root is None:
        project_root = output_dir.parent

    albums_data = []

    # Scan each album directory in _output/
    for album_dir in sorted(output_dir.iterdir()):
        if not album_dir.is_dir():
            continue

        album_name = album_dir.name

        # Find MP3 files (check final/ subdir first, then root)
        final_dir = album_dir / "final"
        if final_dir.exists():
            mp3s = sorted(final_dir.glob("*.mp3"))
            mp3_base = f"{album_name}/final"
        else:
            mp3s = sorted(album_dir.glob("*.mp3"))
            # Exclude raw WAV companion files — only keep latest version
            mp3s = _deduplicate_versions(mp3s)
            mp3_base = album_name

        if not mp3s:
            continue

        # Read album metadata
        album_yaml = project_root / "albums" / album_name / "album.yaml"
        if album_yaml.exists():
            album_meta = _parse_album_yaml(album_yaml)
        else:
            album_meta = {"title": album_name.replace("_", " ").title()}

        lyrics_dir = project_root / "albums" / album_name / "lyrics"

        tracks = []
        for mp3 in mp3s:
            stem = mp3.stem
            # Extract track number and title
            num_match = re.match(r"^(\d+)_(.+?)(?:_v\d+)?$", stem)
            bonus_match = re.match(r"^(bonus)_(.+?)(?:_v\d+)?$", stem)

            if num_match:
                number = num_match.group(1)
                title = num_match.group(2).replace("_", " ").title()
            elif bonus_match:
                number = "B"
                title = bonus_match.group(2).replace("_", " ").title()
            else:
                number = "?"
                title = stem.replace("_", " ").title()

            # Find SRT lyrics (what was actually sung, from Whisper)
            srt_path = mp3.with_suffix(".srt")
            sung_lines = _parse_srt(srt_path) if srt_path.exists() else []

            # Find intended lyrics (from markdown source)
            raw_lyrics = _find_lyrics_for_track(stem, lyrics_dir)
            intended_lines = _lyrics_to_lines(raw_lyrics) if raw_lyrics else []

            # Use SRT if available, otherwise fall back to intended
            lines = sung_lines if sung_lines else intended_lines

            tracks.append({
                "file": f"{mp3_base}/{mp3.name}",
                "title": title,
                "number": number,
                "lines": lines,
                "intended": intended_lines,
                "has_sung": bool(sung_lines),
            })

        colors = ALBUM_COLORS.get(album_name, DEFAULT_COLOR)

        albums_data.append({
            "id": album_name,
            "title": album_meta.get("title", album_name),
            "artist": album_meta.get("artist", "Flex0r"),
            "subtitle": album_meta.get("subtitle", ""),
            "year": album_meta.get("year", "2026"),
            "colors": colors,
            "tracks": tracks,
        })

    player_path = output_dir / "player.html"
    player_path.write_text(
        _render_html(albums_data), encoding="utf-8",
    )
    return player_path


def _deduplicate_versions(mp3s: list[Path]) -> list[Path]:
    """Keep only the latest version of each track (e.g., v2 over v1)."""
    by_base: dict[str, Path] = {}
    for mp3 in mp3s:
        base = re.sub(r"_v\d+$", "", mp3.stem)
        if base.endswith("_raw"):
            continue
        # Keep the one with highest version number
        if base not in by_base or mp3.stem > by_base[base].stem:
            by_base[base] = mp3
    return sorted(by_base.values())


def _render_html(albums: list[dict]) -> str:
    """Render the complete HTML player."""
    albums_json = json.dumps(albums, ensure_ascii=False, indent=2)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Flex0r — Music Player</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Oswald:wght@400;700&family=Open+Sans:wght@400;600&display=swap');

  * {{ margin: 0; padding: 0; box-sizing: border-box; }}

  :root {{
    --primary: #ff3220;
    --bg: #0d0d0d;
  }}

  html, body {{
    background: var(--bg);
    color: #e0e0e0;
    font-family: 'Open Sans', Arial, sans-serif;
    height: 100vh;
    overflow: hidden;
  }}

  body {{
    display: flex;
    flex-direction: column;
  }}

  .header {{
    text-align: center;
    padding: 12px 20px 8px;
    border-bottom: 2px solid var(--primary);
    flex-shrink: 0;
  }}

  .header h1 {{
    font-family: 'Oswald', Impact, sans-serif;
    font-size: 32px;
    color: var(--primary);
    letter-spacing: 4px;
    text-transform: uppercase;
  }}

  .header .subtitle {{
    color: #888;
    font-size: 12px;
    margin-top: 2px;
  }}

  .album-nav {{
    display: flex;
    justify-content: center;
    gap: 4px;
    padding: 8px 20px;
    background: #111;
    flex-shrink: 0;
  }}

  .album-btn {{
    background: #1a1a1a;
    border: 2px solid #333;
    color: #aaa;
    padding: 5px 16px;
    font-family: 'Oswald', sans-serif;
    font-size: 14px;
    cursor: pointer;
    transition: all 0.2s;
    text-transform: uppercase;
    letter-spacing: 1px;
  }}

  .album-btn:hover {{
    border-color: var(--primary);
    color: #fff;
  }}

  .album-btn.active {{
    background: var(--primary);
    border-color: var(--primary);
    color: #fff;
  }}

  .track-nav {{
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    gap: 4px;
    padding: 6px 20px;
    background: #0f0f0f;
    flex-shrink: 0;
  }}

  .track-btn {{
    background: #1a1a1a;
    border: 1px solid #2a2a2a;
    color: #777;
    padding: 4px 12px;
    font-family: 'Oswald', sans-serif;
    font-size: 12px;
    cursor: pointer;
    transition: all 0.2s;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }}

  .track-btn:hover {{
    border-color: var(--primary);
    color: #ccc;
  }}

  .track-btn.active {{
    background: rgba(255,255,255,0.1);
    border-color: var(--primary);
    color: #fff;
  }}

  .player-area {{
    max-width: 800px;
    margin: 0 auto;
    padding: 8px 20px;
    flex: 1;
    display: flex;
    flex-direction: column;
    min-height: 0;
    width: 100%;
  }}

  .now-playing {{
    text-align: center;
    margin-bottom: 6px;
    flex-shrink: 0;
  }}

  .now-playing .track-number {{
    font-family: 'Oswald', sans-serif;
    color: var(--primary);
    font-size: 16px;
  }}

  .now-playing .track-title {{
    font-family: 'Oswald', sans-serif;
    color: #fff;
    font-size: 24px;
    text-transform: uppercase;
    letter-spacing: 2px;
  }}

  .audio-player {{
    width: 100%;
    margin: 6px 0;
    flex-shrink: 0;
    height: 40px;
  }}

  .lyrics-container {{
    padding: 8px 0;
    flex: 1;
    overflow-y: auto;
    scroll-behavior: smooth;
    min-height: 0;
  }}

  .lyric-line {{
    padding: 6px 16px;
    margin: 3px 0;
    font-size: 17px;
    line-height: 1.5;
    color: #444;
    transition: all 0.3s ease;
    border-left: 3px solid transparent;
    cursor: pointer;
  }}

  .lyric-line:hover {{ color: #999; }}

  .lyric-line.active {{
    color: #fff;
    font-size: 19px;
    border-left-color: var(--primary);
    background: rgba(255, 255, 255, 0.03);
  }}

  .lyric-line.past {{ color: #666; }}

  .lyric-line.section-tag {{
    color: var(--primary);
    font-family: 'Oswald', sans-serif;
    font-size: 13px;
    letter-spacing: 2px;
    opacity: 0.6;
    cursor: default;
    padding: 10px 16px 2px;
  }}

  .lyric-line .timestamp {{
    font-family: 'Oswald', sans-serif;
    font-size: 11px;
    color: var(--primary);
    margin-right: 8px;
    opacity: 0.5;
  }}

  .no-lyrics {{
    text-align: center;
    color: #444;
    font-style: italic;
    padding: 40px 20px;
  }}

  .view-toggle {{
    display: flex;
    justify-content: center;
    gap: 4px;
    padding: 4px 0;
    flex-shrink: 0;
  }}

  .view-btn {{
    background: none;
    border: 1px solid #333;
    color: #666;
    padding: 2px 12px;
    font-family: 'Oswald', sans-serif;
    font-size: 11px;
    cursor: pointer;
    text-transform: uppercase;
    letter-spacing: 1px;
    transition: all 0.2s;
  }}

  .view-btn:hover {{ color: #aaa; border-color: #555; }}

  .view-btn.active {{
    color: var(--primary);
    border-color: var(--primary);
  }}

  .diff-line {{
    padding: 4px 16px;
    margin: 2px 0;
    font-size: 14px;
    line-height: 1.4;
    font-family: 'Open Sans', monospace;
  }}

  .diff-line.match {{ color: #4a4; }}
  .diff-line.intended {{ color: #888; text-decoration: line-through; }}
  .diff-line.sung {{ color: var(--primary); }}
  .diff-line.section {{ color: #555; font-family: 'Oswald', sans-serif; font-size: 12px; letter-spacing: 1px; padding-top: 8px; }}

  .footer {{
    text-align: center;
    padding: 6px;
    color: #333;
    font-size: 11px;
    flex-shrink: 0;
    border-top: 1px solid #1a1a1a;
  }}

  .lyrics-container::-webkit-scrollbar {{ width: 5px; }}
  .lyrics-container::-webkit-scrollbar-track {{ background: #111; }}
  .lyrics-container::-webkit-scrollbar-thumb {{ background: var(--primary); border-radius: 3px; }}

  @media (max-width: 600px) {{
    .header h1 {{ font-size: 24px; }}
    .now-playing .track-title {{ font-size: 18px; }}
    .lyric-line {{ font-size: 15px; padding: 5px 12px; }}
    .lyric-line.active {{ font-size: 16px; }}
    .album-btn, .track-btn {{ padding: 4px 10px; font-size: 11px; }}
  }}
</style>
</head>
<body>

<div class="header">
  <h1 id="albumTitle">Flex0r</h1>
  <div class="subtitle" id="albumSubtitle">Music Player</div>
</div>

<div class="album-nav" id="albumNav"></div>
<div class="track-nav" id="trackNav"></div>

<div class="player-area">
  <div class="now-playing">
    <div class="track-number" id="trackNumber"></div>
    <div class="track-title" id="trackTitle"></div>
  </div>

  <audio id="audioPlayer" class="audio-player" controls preload="metadata">
    <source id="audioSource" type="audio/mpeg">
  </audio>

  <div class="view-toggle" id="viewToggle" style="display:none">
    <button class="view-btn active" id="btnSung" onclick="switchView('sung')">Sung</button>
    <button class="view-btn" id="btnIntended" onclick="switchView('intended')">Intended</button>
    <button class="view-btn" id="btnDiff" onclick="switchView('diff')">Diff</button>
  </div>

  <div class="lyrics-container" id="lyricsContainer"></div>
</div>

<div class="footer">
  AI Generated &bull; Flex0r &bull; 2026
</div>

<script>
const ALBUMS = {albums_json};

let currentAlbum = 0;
let currentTrack = 0;

const audio = document.getElementById('audioPlayer');
const source = document.getElementById('audioSource');
const lyricsContainer = document.getElementById('lyricsContainer');
const trackNumber = document.getElementById('trackNumber');
const trackTitle = document.getElementById('trackTitle');
const albumTitle = document.getElementById('albumTitle');
const albumSubtitle = document.getElementById('albumSubtitle');
const albumNav = document.getElementById('albumNav');
const trackNav = document.getElementById('trackNav');

function setTheme(colors) {{
  document.documentElement.style.setProperty('--primary', colors.primary);
  document.documentElement.style.setProperty('--bg', colors.bg);
}}

function formatTime(secs) {{
  const m = Math.floor(secs / 60);
  const s = Math.floor(secs % 60);
  return m + ':' + String(s).padStart(2, '0');
}}

// Build album navigation
ALBUMS.forEach((album, i) => {{
  const btn = document.createElement('button');
  btn.className = 'album-btn' + (i === 0 ? ' active' : '');
  btn.textContent = album.title;
  btn.onclick = () => loadAlbum(i);
  btn.id = 'album-btn-' + i;
  albumNav.appendChild(btn);
}});

function buildTrackNav(album) {{
  trackNav.innerHTML = '';
  album.tracks.forEach((t, i) => {{
    const btn = document.createElement('button');
    btn.className = 'track-btn' + (i === 0 ? ' active' : '');
    btn.textContent = t.number + ' ' + t.title;
    btn.onclick = () => loadTrack(i);
    btn.id = 'track-btn-' + i;
    trackNav.appendChild(btn);
  }});
}}

function loadAlbum(index) {{
  currentAlbum = index;
  currentTrack = 0;
  const album = ALBUMS[index];

  // Update album nav
  document.querySelectorAll('.album-btn').forEach((btn, i) => {{
    btn.className = 'album-btn' + (i === index ? ' active' : '');
  }});

  // Set theme
  setTheme(album.colors);

  // Update header
  albumTitle.textContent = album.title;
  const parts = [album.artist];
  if (album.subtitle) parts.push(album.subtitle);
  albumSubtitle.textContent = parts.join(' \\u2022 ');

  // Build track nav and load first track
  buildTrackNav(album);
  loadTrack(0);
}}

function loadTrack(index) {{
  currentTrack = index;
  const album = ALBUMS[currentAlbum];
  const t = album.tracks[index];

  // Update track nav
  document.querySelectorAll('.track-btn').forEach((btn, i) => {{
    btn.className = 'track-btn' + (i === index ? ' active' : '');
  }});

  trackNumber.textContent = t.number;
  trackTitle.textContent = t.title;

  source.src = t.file;
  audio.load();

  // Show/hide view toggle (only if we have both sung and intended)
  const viewToggle = document.getElementById('viewToggle');
  if (t.has_sung && t.intended && t.intended.length > 0) {{
    viewToggle.style.display = 'flex';
  }} else {{
    viewToggle.style.display = 'none';
    currentView = 'sung';
  }}

  renderCurrentView();
}}

// Lyrics sync (only for timestamped lyrics)
audio.addEventListener('timeupdate', () => {{
  const time = audio.currentTime;
  const album = ALBUMS[currentAlbum];
  const lines = album.tracks[currentTrack].lines;
  const hasTimestamps = lines.some(l => l.time >= 0);
  if (!hasTimestamps) return;

  let activeIndex = -1;
  for (let i = lines.length - 1; i >= 0; i--) {{
    if (!lines[i].section && lines[i].time >= 0 && time >= lines[i].time) {{
      activeIndex = i;
      break;
    }}
  }}

  document.querySelectorAll('.lyric-line:not(.section-tag)').forEach(el => {{
    const idx = parseInt(el.id?.replace('line-', ''), 10);
    if (idx === activeIndex) {{
      el.className = 'lyric-line active';
    }} else if (idx < activeIndex) {{
      el.className = 'lyric-line past';
    }} else {{
      el.className = 'lyric-line';
    }}
  }});

  if (activeIndex >= 0) {{
    const activeLine = document.getElementById('line-' + activeIndex);
    if (activeLine) {{
      const lineTop = activeLine.offsetTop - lyricsContainer.offsetTop;
      const scrollTarget = lineTop - lyricsContainer.clientHeight / 3;
      lyricsContainer.scrollTop = scrollTarget;
    }}
  }}
}});

// Auto-advance to next track
audio.addEventListener('ended', () => {{
  const album = ALBUMS[currentAlbum];
  if (currentTrack < album.tracks.length - 1) {{
    loadTrack(currentTrack + 1);
    audio.addEventListener('canplay', function onCanPlay() {{
      audio.removeEventListener('canplay', onCanPlay);
      audio.play();
    }});
  }} else if (currentAlbum < ALBUMS.length - 1) {{
    // Auto-advance to next album
    loadAlbum(currentAlbum + 1);
    audio.addEventListener('canplay', function onCanPlay() {{
      audio.removeEventListener('canplay', onCanPlay);
      audio.play();
    }});
  }}
}});

let currentView = 'sung';

function switchView(view) {{
  currentView = view;
  document.querySelectorAll('.view-btn').forEach(b => b.className = 'view-btn');
  document.getElementById('btn' + view.charAt(0).toUpperCase() + view.slice(1)).className = 'view-btn active';
  renderCurrentView();
}}

function renderCurrentView() {{
  const album = ALBUMS[currentAlbum];
  const t = album.tracks[currentTrack];

  if (currentView === 'sung') {{
    renderLyrics(t.lines, true);
  }} else if (currentView === 'intended') {{
    renderLyrics(t.intended || [], false);
  }} else {{
    renderDiff(t);
  }}
}}

function renderLyrics(lines, withTimestamps) {{
  lyricsContainer.innerHTML = '';
  if (!lines || lines.length === 0) {{
    lyricsContainer.innerHTML = '<div class="no-lyrics">No lyrics available</div>';
    return;
  }}
  const hasTs = withTimestamps && lines.some(l => l.time >= 0);
  lines.forEach((line, i) => {{
    const div = document.createElement('div');
    if (line.section) {{
      div.className = 'lyric-line section-tag';
      div.textContent = line.text;
    }} else {{
      div.className = 'lyric-line';
      div.id = 'line-' + i;
      let html = '';
      if (hasTs && line.time >= 0) {{
        html += '<span class="timestamp">' + formatTime(line.time) + '</span>';
      }}
      html += line.text;
      div.innerHTML = html;
      if (hasTs && line.time >= 0) {{
        div.onclick = () => {{ audio.currentTime = line.time; audio.play(); }};
      }}
    }}
    lyricsContainer.appendChild(div);
  }});
  lyricsContainer.scrollTop = 0;
}}

function renderDiff(track) {{
  lyricsContainer.innerHTML = '';
  const intended = (track.intended || []).filter(l => !l.section).map(l => l.text);
  const sung = (track.lines || []).map(l => l.text);

  if (intended.length === 0 && sung.length === 0) {{
    lyricsContainer.innerHTML = '<div class="no-lyrics">No lyrics to compare</div>';
    return;
  }}

  // Simple line-by-line diff using longest common subsequence approach
  const maxLen = Math.max(intended.length, sung.length);
  let iIdx = 0, sIdx = 0;

  // Build pairs by matching similar lines
  const pairs = [];
  const usedSung = new Set();

  for (let i = 0; i < intended.length; i++) {{
    let bestMatch = -1;
    let bestScore = 0;
    // Search nearby sung lines for a match
    for (let s = Math.max(0, i - 5); s < Math.min(sung.length, i + 10); s++) {{
      if (usedSung.has(s)) continue;
      const score = similarity(intended[i], sung[s]);
      if (score > bestScore && score > 0.3) {{
        bestScore = score;
        bestMatch = s;
      }}
    }}
    if (bestMatch >= 0) {{
      // Add any unmatched sung lines before this match
      for (let s = (pairs.length > 0 ? pairs[pairs.length-1].sIdx + 1 : 0); s < bestMatch; s++) {{
        if (!usedSung.has(s)) {{
          pairs.push({{ type: 'sung', sung: sung[s], sIdx: s }});
          usedSung.add(s);
        }}
      }}
      pairs.push({{ type: bestScore > 0.85 ? 'match' : 'changed', intended: intended[i], sung: sung[bestMatch], score: bestScore, sIdx: bestMatch }});
      usedSung.add(bestMatch);
    }} else {{
      pairs.push({{ type: 'missing', intended: intended[i] }});
    }}
  }}
  // Add remaining unmatched sung lines
  for (let s = 0; s < sung.length; s++) {{
    if (!usedSung.has(s)) {{
      pairs.push({{ type: 'sung', sung: sung[s], sIdx: s }});
    }}
  }}

  // Render
  let matchCount = 0, totalCount = 0;
  pairs.forEach(p => {{
    const div = document.createElement('div');
    div.className = 'diff-line';
    if (p.type === 'match') {{
      div.className += ' match';
      div.textContent = '\\u2713 ' + p.intended;
      matchCount++; totalCount++;
    }} else if (p.type === 'changed') {{
      totalCount++;
      const pct = Math.round(p.score * 100);
      div.innerHTML = '<div class="diff-line intended">\\u2717 ' + escHtml(p.intended) + '</div>' +
        '<div class="diff-line sung">\\u2192 ' + escHtml(p.sung) + ' <span style="opacity:0.5">(' + pct + '%)</span></div>';
      div.className = '';
    }} else if (p.type === 'missing') {{
      div.className += ' intended';
      div.textContent = '\\u2717 ' + p.intended + ' (not sung)';
      totalCount++;
    }} else {{
      div.className += ' sung';
      div.textContent = '+ ' + p.sung + ' (added)';
    }}
    lyricsContainer.appendChild(div);
  }});

  // Summary at top
  if (totalCount > 0) {{
    const summary = document.createElement('div');
    summary.style.cssText = 'text-align:center;padding:8px;color:#888;font-size:13px;border-bottom:1px solid #222;margin-bottom:8px;';
    const pct = Math.round(matchCount / totalCount * 100);
    summary.textContent = 'Accuracy: ' + matchCount + '/' + totalCount + ' lines matched (' + pct + '%)';
    lyricsContainer.insertBefore(summary, lyricsContainer.firstChild);
  }}
  lyricsContainer.scrollTop = 0;
}}

function similarity(a, b) {{
  a = a.toLowerCase().replace(/[^a-zäöüß0-9 ]/g, '');
  b = b.toLowerCase().replace(/[^a-zäöüß0-9 ]/g, '');
  if (a === b) return 1;
  const wordsA = a.split(/\\s+/);
  const wordsB = b.split(/\\s+/);
  let matches = 0;
  wordsA.forEach(w => {{ if (wordsB.includes(w)) matches++; }});
  return matches / Math.max(wordsA.length, wordsB.length);
}}

function escHtml(s) {{
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}}

// Load first album
if (ALBUMS.length > 0) {{
  loadAlbum(0);
}}
</script>

</body>
</html>"""
