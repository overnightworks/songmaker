"""Automated lyrics sync pipeline for Songmaker.

Transcribes MP3s with Whisper, generates LRC files, HTML player, and booklet.
Works for any album folder. LRC files are the single source of truth.

Usage:
    # Full pipeline: transcribe + generate HTML for a folder
    .venv/Scripts/python scripts/sync_lyrics.py _output/apologiez/final/

    # Re-transcribe a single song
    .venv/Scripts/python scripts/sync_lyrics.py _output/apologiez/final/05_bruder.mp3

    # Force re-transcribe all (even if .lrc exists)
    .venv/Scripts/python scripts/sync_lyrics.py _output/apologiez/final/ --force

    # Only regenerate HTML from existing LRC files (no Whisper, fast)
    .venv/Scripts/python scripts/sync_lyrics.py _output/apologiez/final/ --html-only
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Whisper cleanup: common transcription errors → correct text
# Extend this dict per album / globally as needed.
# ---------------------------------------------------------------------------
CLEANUP: dict[str, str] = {
    "Kai ": "KI ",
    "Kei ": "KI ",
    " Kai,": " KI,",
    " Kai.": " KI.",
    "Kaising": "KI singt",
    "Kailz": "KI",
    "Herbster": "Napster",
    "Epster": "Napster",
    "Bodyfall": "Spotify",
    "Partyfights": "Spotify",
    "Gigi WP": "GG WP",
    "Tavish": "Tobbisch",
    "Torbisch": "Tobbisch",
    "tall bitch": "Tobbisch",
    "Talbisch": "Tobbisch",
    "Tobish": "Tobbisch",
    "tovisch": "Tobbisch",
    "Topisch": "Tobbisch",
    "K.I.": "KI",
    "K.U.": "KI",
    "Juli Kende": "du Legende",
    "Midlight": "Mitleid",
    "Abster": "Napster",
    "Torbjeg": "Tobbisch",
    "Tobisch": "Tobbisch",
    "die Langung": "Erlangen",
    "der Langung": "Erlangen",
    "der Lange": "Erlangen",
    "in der Langung": "in Erlangen",
    "Diegle": "Deagle",
    "Biegle": "Deagle",
    "Niegel": "Deagle",
}


# ---------------------------------------------------------------------------
# LRC parsing / generation
# ---------------------------------------------------------------------------

def parse_lrc(path: Path) -> list[tuple[float, str]]:
    """Parse an LRC file into a list of (seconds, text) tuples."""
    lines: list[tuple[float, str]] = []
    pattern = re.compile(r"\[(\d+):(\d+)(?:\.(\d+))?\]\s*(.*)")
    for raw in path.read_text(encoding="utf-8").splitlines():
        m = pattern.match(raw)
        if not m:
            continue
        mins, secs = int(m.group(1)), int(m.group(2))
        centis = int(m.group(3)) if m.group(3) else 0
        text = m.group(4).strip()
        if not text:
            continue
        lines.append((mins * 60 + secs + centis / 100, text))
    return lines


def write_lrc(path: Path, title: str, artist: str, album: str,
              lines: list[tuple[float, str]]) -> None:
    """Write an LRC file from (seconds, text) tuples."""
    out = [
        f"[ti:{title}]",
        f"[ar:{artist}]",
        f"[al:{album}]",
        "",
    ]
    for secs, text in lines:
        mins = int(secs) // 60
        s = int(secs) % 60
        centis = int((secs - int(secs)) * 100)
        out.append(f"[{mins:02d}:{s:02d}.{centis:02d}] {text}")
    path.write_text("\n".join(out), encoding="utf-8")


# ---------------------------------------------------------------------------
# Whisper transcription
# ---------------------------------------------------------------------------

def transcribe_to_lrc(mp3_path: Path, album_meta: dict, force: bool = False) -> bool:
    """Transcribe an MP3 with Whisper medium and write an LRC file.

    Uses initial_prompt from album.json track entry or a .prompt file
    next to the MP3 to help Whisper recognize lyrics over instrumentals.

    Returns True if transcription was performed, False if skipped.
    """
    lrc_path = mp3_path.with_suffix(".lrc")
    if lrc_path.exists() and not force:
        print(f"  skip (LRC exists): {mp3_path.name}")
        return False

    print(f"  transcribing: {mp3_path.name} ...")
    import whisper

    # Lazy-load model (cached after first call)
    if not hasattr(transcribe_to_lrc, "_model"):
        print("  loading Whisper medium model...")
        transcribe_to_lrc._model = whisper.load_model("medium")

    # Build initial_prompt from: album.json track hints, .prompt file, or lyrics .md
    initial_prompt = _get_lyrics_hint(mp3_path, album_meta)
    if initial_prompt:
        print(f"  using lyrics hint ({len(initial_prompt)} chars)")

    model = transcribe_to_lrc._model
    kwargs: dict = dict(
        language="de",
        fp16=False,
        word_timestamps=True,
        condition_on_previous_text=True,
    )
    if initial_prompt:
        kwargs["initial_prompt"] = initial_prompt

    result = model.transcribe(str(mp3_path), **kwargs)

    # Build lines from segments
    lines: list[tuple[float, str]] = []
    for seg in result["segments"]:
        text = seg["text"].strip()
        if not text:
            continue
        # Apply cleanup substitutions
        for old, new in CLEANUP.items():
            text = text.replace(old, new)
        lines.append((seg["start"], text))

    # Fuzzy-correct against original lyrics (fix Whisper misrecognitions)
    if initial_prompt:
        lines = _fuzzy_correct(lines, initial_prompt)

    # Derive title from track metadata or filename
    title = _title_from_filename(mp3_path.stem)
    artist = album_meta.get("artist", "Flex0r & ACE-Step")
    album_name = album_meta.get("title", "Songmaker")

    write_lrc(lrc_path, title, artist, album_name, lines)
    print(f"  wrote: {lrc_path.name} ({len(lines)} lines)")
    return True


def _get_lyrics_hint(mp3_path: Path, album_meta: dict) -> str:
    """Find lyrics hint text to prime Whisper's initial_prompt.

    Sources (in priority order):
    1. "lyrics_hint" field in album.json track entry
    2. A .prompt file next to the MP3 (e.g. 03_rap_battle_part_2.prompt)
    3. Corresponding lyrics .md file from albums/<album>/lyrics/
    """
    mp3_name = mp3_path.name

    # 1. Check album.json track entry
    for track in album_meta.get("tracks", []):
        if track.get("file") == mp3_name and track.get("lyrics_hint"):
            return track["lyrics_hint"]

    # 2. Check for .prompt file next to MP3
    prompt_path = mp3_path.with_suffix(".prompt")
    if prompt_path.exists():
        return prompt_path.read_text(encoding="utf-8").strip()

    # 3. Try to find lyrics .md from album source
    # _output/<album>/final/<file>.mp3 → albums/<album>/lyrics/<file>.md
    try:
        album_dir = mp3_path.parent.parent.parent  # up from final/
        # Map output folder name to album folder name
        album_name = mp3_path.parent.parent.name
        lyrics_dir = Path("albums") / album_name / "lyrics"
        if lyrics_dir.exists():
            # Try matching by track number prefix
            stem = mp3_path.stem
            for md_file in lyrics_dir.glob("*.md"):
                if md_file.stem.split("_")[0] == stem.split("_")[0]:
                    return md_file.read_text(encoding="utf-8").strip()[:2000]
    except (IndexError, ValueError):
        pass

    return ""


def _fuzzy_correct(
    lines: list[tuple[float, str]],
    hint_text: str,
    threshold: float = 0.70,
    min_word_len: int = 5,
) -> list[tuple[float, str]]:
    """Fix Whisper misrecognitions by comparing against original lyrics.

    Builds a vocabulary from the original lyrics, then for each Whisper word
    that ISN'T in that vocabulary, finds the closest match.  If the similarity
    ratio exceeds *threshold* the word is replaced.

    Short words (< min_word_len) are skipped to avoid false positives on
    common function words like 'die/sie/und/Mann'.
    Words in the SAFE_WORDS set are never replaced (common German/English words
    that Whisper transcribes correctly).
    """
    from difflib import SequenceMatcher

    # Common words that Whisper gets right — never replace these
    SAFE_WORDS = {
        # German function words & pronouns
        "meine", "deine", "seine", "keine", "meinen", "deinen", "seinen",
        "keinen", "meiner", "deiner", "seiner", "keiner", "diese", "dieser",
        "dieses", "diesem", "diesen", "jeder", "jedes", "jedem", "jeden",
        "mutter", "vater", "bruder", "kinder", "alter", "erste", "ersten",
        "erstes", "erster", "zweite", "dritte", "immer", "nicht", "nichts",
        "hatte", "haben", "habe", "waren", "wurde", "wirst", "durch",
        "unter", "neben", "gegen", "hinter", "zwischen", "Jahre",
        "Jahre", "jahre", "sagen", "gehen", "kommen", "stehen", "liegen",
        "machen", "lassen", "geben", "nehmen", "finden", "wissen",
        "kennen", "kennt", "kenne", "singt", "singst", "singen",
        "schickt", "schickst", "schicken", "stimme", "stimmen",
        "leben", "leute", "leuten", "freund", "freunde",
        # English common words
        "every", "never", "after", "before", "still", "about", "which",
        "their", "there", "where", "right", "night", "light",
        "stream", "battle", "songs", "start", "stand",
    }

    # Build vocabulary: lowercased key -> original-cased word
    clean = re.sub(r"\[.*?\]", "", hint_text)          # strip [verse] etc.
    clean = clean.replace("\\n", " ")                   # handle literal \n
    orig_vocab: dict[str, str] = {}
    for word in re.findall(r"[A-Za-z\u00C0-\u024F0-9'-]+", clean):
        key = word.lower()
        if key not in orig_vocab:
            orig_vocab[key] = word

    if not orig_vocab:
        return lines

    corrections: dict[str, str | None] = {}   # cache: whisper_lower -> replacement
    stats = {"checked": 0, "replaced": 0}

    def _best_replacement(w: str) -> str | None:
        """Find best vocabulary match for a single word, or None."""
        key = w.lower()

        # Already in original vocab — correct
        if key in orig_vocab:
            return None

        # Too short — skip to avoid false positives
        if len(key) < min_word_len:
            return None

        # Safe word — Whisper gets these right, never replace
        if key in SAFE_WORDS:
            return None

        # Check cache
        if key in corrections:
            return corrections[key]

        best_word: str | None = None
        best_ratio = 0.0
        for orig_key, orig_word in orig_vocab.items():
            if len(orig_key) < min_word_len:
                continue
            # Skip if lengths differ too much (unlikely phonetic match)
            if abs(len(key) - len(orig_key)) > max(3, len(key) // 2):
                continue
            ratio = SequenceMatcher(None, key, orig_key).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_word = orig_word

        result = best_word if best_ratio >= threshold else None
        corrections[key] = result
        return result

    # Word-splitting pattern: keeps punctuation attached for reconstruction
    word_re = re.compile(r"([A-Za-z\u00C0-\u024F0-9'-]+)")

    corrected: list[tuple[float, str]] = []
    for time, text in lines:
        parts = word_re.split(text)  # alternating [sep, word, sep, word, ...]
        new_parts: list[str] = []
        for part in parts:
            if word_re.fullmatch(part):
                stats["checked"] += 1
                repl = _best_replacement(part)
                if repl is not None:
                    stats["replaced"] += 1
                    new_parts.append(repl)
                else:
                    new_parts.append(part)
            else:
                new_parts.append(part)
        corrected.append((time, "".join(new_parts)))

    if stats["replaced"]:
        print(f"  fuzzy-corrected {stats['replaced']}/{stats['checked']} words")

    return corrected


# ---------------------------------------------------------------------------
# album.json metadata
# ---------------------------------------------------------------------------

def ensure_album_json(folder: Path) -> dict:
    """Read or auto-create album.json in the given folder."""
    meta_path = folder / "album.json"
    if meta_path.exists():
        return json.loads(meta_path.read_text(encoding="utf-8"))

    # Auto-generate from MP3 filenames
    mp3s = sorted(folder.glob("*.mp3"))
    tracks = []
    for mp3 in mp3s:
        number, title = _parse_filename(mp3.stem)
        tracks.append({
            "file": mp3.name,
            "title": title,
            "number": number,
        })

    # Guess album name from folder structure: _output/<album>/final/
    album_name = folder.parent.name if folder.name == "final" else folder.name
    album_name = album_name.replace("_", " ").title()

    meta = {
        "title": album_name,
        "artist": "Flex0r",
        "for": "MC Tobbisch",
        "year": 2026,
        "tracks": tracks,
    }

    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  created: {meta_path.name}")
    return meta


def _parse_filename(stem: str) -> tuple[str, str]:
    """Parse '01_happy_birthday_tobbisch' into ('01', 'Happy Birthday Tobbisch')."""
    # Try to split on first underscore for track number
    m = re.match(r"^(\d+)_(.+)$", stem)
    if m:
        number = m.group(1)
        title = m.group(2).replace("_", " ").title()
        return number, title
    # Bonus track or no number
    m = re.match(r"^(bonus)_(.+)$", stem, re.IGNORECASE)
    if m:
        return "BONUS", m.group(2).replace("_", " ").title()
    return "", stem.replace("_", " ").title()


def _title_from_filename(stem: str) -> str:
    """Get just the title part from a filename stem."""
    _, title = _parse_filename(stem)
    return title


# ---------------------------------------------------------------------------
# HTML Player generation
# ---------------------------------------------------------------------------

def generate_player_html(folder: Path, meta: dict, tracks_data: list[dict]) -> None:
    """Generate lyrics_player.html from album metadata and parsed LRC data."""
    album_title = meta.get("title", "Album")
    artist = meta.get("artist", "")
    for_whom = meta.get("for", "")
    subtitle = f"{artist} &rarr; {for_whom} &bull; Lyrics Player" if for_whom else f"{artist} &bull; Lyrics Player"

    # Build JS track data
    tracks_js_parts = []
    for t in tracks_data:
        lines_js = []
        for secs, text in t["lines"]:
            escaped = text.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')
            lines_js.append(f'        {{time: {secs:.1f}, text: "{escaped}"}}')
        tracks_js_parts.append(
            f'    {{\n'
            f'      file: "{t["file"]}",\n'
            f'      title: "{t["title"]}",\n'
            f'      number: "{t["number"]}",\n'
            f'      lines: [\n' + ",\n".join(lines_js) + "\n      ]\n"
            f'    }}'
        )
    tracks_js = "[\n" + ",\n".join(tracks_js_parts) + "\n  ]"

    html = _PLAYER_TEMPLATE.format(
        album_title=album_title,
        subtitle=subtitle,
        tracks_js=tracks_js,
        year=meta.get("year", 2026),
    )

    out_path = folder / "lyrics_player.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"  wrote: {out_path.name}")


_PLAYER_TEMPLATE = """\
<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{album_title} — Lyrics Player</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Oswald:wght@400;700&family=Open+Sans:wght@400;600&display=swap');

  * {{ margin: 0; padding: 0; box-sizing: border-box; }}

  html, body {{
    background: #0d0d0d;
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
    padding: 15px 20px 10px;
    border-bottom: 2px solid #ff3220;
    flex-shrink: 0;
  }}

  .header h1 {{
    font-family: 'Oswald', Impact, sans-serif;
    font-size: 36px;
    color: #ff3220;
    letter-spacing: 4px;
    text-transform: uppercase;
  }}

  .header .subtitle {{
    color: #888;
    font-size: 13px;
    margin-top: 3px;
  }}

  .track-nav {{
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    gap: 6px;
    padding: 10px 20px;
    background: #111;
    flex-shrink: 0;
  }}

  .track-btn {{
    background: #1a1a1a;
    border: 2px solid #333;
    color: #aaa;
    padding: 6px 14px;
    font-family: 'Oswald', sans-serif;
    font-size: 13px;
    cursor: pointer;
    transition: all 0.2s;
    text-transform: uppercase;
    letter-spacing: 1px;
  }}

  .track-btn:hover {{
    border-color: #ff3220;
    color: #fff;
  }}

  .track-btn.active {{
    background: #ff3220;
    border-color: #ff3220;
    color: #fff;
  }}

  .player-area {{
    max-width: 800px;
    margin: 0 auto;
    padding: 10px 20px;
    flex: 1;
    display: flex;
    flex-direction: column;
    min-height: 0;
    width: 100%;
  }}

  .now-playing {{
    text-align: center;
    margin-bottom: 8px;
    flex-shrink: 0;
  }}

  .now-playing .track-number {{
    font-family: 'Oswald', sans-serif;
    color: #ff3220;
    font-size: 18px;
  }}

  .now-playing .track-title {{
    font-family: 'Oswald', sans-serif;
    color: #fff;
    font-size: 26px;
    text-transform: uppercase;
    letter-spacing: 2px;
  }}

  .audio-player {{
    width: 100%;
    margin: 8px 0;
    flex-shrink: 0;
    filter: hue-rotate(340deg) saturate(2);
  }}

  .lyrics-container {{
    padding: 10px 0;
    flex: 1;
    overflow-y: auto;
    scroll-behavior: smooth;
    min-height: 0;
  }}

  .lyric-line {{
    padding: 8px 16px;
    margin: 4px 0;
    font-size: 18px;
    line-height: 1.6;
    color: #555;
    transition: all 0.3s ease;
    border-left: 3px solid transparent;
    cursor: pointer;
  }}

  .lyric-line:hover {{
    color: #999;
  }}

  .lyric-line.active {{
    color: #fff;
    font-size: 20px;
    border-left-color: #ff3220;
    background: rgba(255, 50, 32, 0.05);
  }}

  .lyric-line.past {{
    color: #777;
  }}

  .lyric-line .timestamp {{
    font-family: 'Oswald', sans-serif;
    font-size: 12px;
    color: #ff3220;
    margin-right: 10px;
    opacity: 0.6;
  }}

  .footer {{
    text-align: center;
    padding: 8px;
    color: #333;
    font-size: 11px;
    flex-shrink: 0;
    border-top: 1px solid #222;
  }}

  .lyrics-container::-webkit-scrollbar {{ width: 6px; }}
  .lyrics-container::-webkit-scrollbar-track {{ background: #111; }}
  .lyrics-container::-webkit-scrollbar-thumb {{ background: #ff3220; border-radius: 3px; }}
</style>
</head>
<body>

<div class="header">
  <h1>{album_title}</h1>
  <div class="subtitle">{subtitle}</div>
</div>

<div class="track-nav" id="trackNav"></div>

<div class="player-area">
  <div class="now-playing">
    <div class="track-number" id="trackNumber"></div>
    <div class="track-title" id="trackTitle"></div>
  </div>

  <audio id="audioPlayer" class="audio-player" controls preload="metadata">
    <source id="audioSource" type="audio/mpeg">
  </audio>

  <div class="lyrics-container" id="lyricsContainer"></div>
</div>

<div class="footer">
  AI Generated &bull; {year}
</div>

<script>
const TRACKS = {tracks_js};

let currentTrack = 0;
const audio = document.getElementById('audioPlayer');
const source = document.getElementById('audioSource');
const lyricsContainer = document.getElementById('lyricsContainer');
const trackNumber = document.getElementById('trackNumber');
const trackTitle = document.getElementById('trackTitle');
const trackNav = document.getElementById('trackNav');

TRACKS.forEach((t, i) => {{
  const btn = document.createElement('button');
  btn.className = 'track-btn' + (i === 0 ? ' active' : '');
  btn.textContent = t.number + ' ' + t.title;
  btn.onclick = () => loadTrack(i);
  btn.id = 'btn-' + i;
  trackNav.appendChild(btn);
}});

function formatTime(secs) {{
  const m = Math.floor(secs / 60);
  const s = Math.floor(secs % 60);
  return m + ':' + String(s).padStart(2, '0');
}}

function loadTrack(index) {{
  currentTrack = index;
  const t = TRACKS[index];

  document.querySelectorAll('.track-btn').forEach((btn, i) => {{
    btn.className = 'track-btn' + (i === index ? ' active' : '');
  }});

  trackNumber.textContent = t.number;
  trackTitle.textContent = t.title;

  source.src = t.file;
  audio.load();

  lyricsContainer.innerHTML = '';
  t.lines.forEach((line, i) => {{
    const div = document.createElement('div');
    div.className = 'lyric-line';
    div.id = 'line-' + i;
    div.innerHTML = '<span class="timestamp">' + formatTime(line.time) + '</span>' + line.text;
    div.onclick = () => {{
      audio.currentTime = line.time;
      audio.play();
    }};
    lyricsContainer.appendChild(div);
  }});
  lyricsContainer.scrollTop = 0;
}}

audio.addEventListener('timeupdate', () => {{
  const time = audio.currentTime;
  const lines = TRACKS[currentTrack].lines;
  let activeIndex = -1;

  for (let i = lines.length - 1; i >= 0; i--) {{
    if (time >= lines[i].time) {{
      activeIndex = i;
      break;
    }}
  }}

  document.querySelectorAll('.lyric-line').forEach((el, i) => {{
    if (i === activeIndex) {{
      el.className = 'lyric-line active';
    }} else if (i < activeIndex) {{
      el.className = 'lyric-line past';
    }} else {{
      el.className = 'lyric-line';
    }}
  }});

  if (activeIndex >= 0) {{
    const activeLine = document.getElementById('line-' + activeIndex);
    if (activeLine) {{
      const container = lyricsContainer;
      const lineTop = activeLine.offsetTop - container.offsetTop;
      const scrollTarget = lineTop - container.clientHeight / 3;
      container.scrollTop = scrollTarget;
    }}
  }}
}});

audio.addEventListener('ended', () => {{
  if (currentTrack < TRACKS.length - 1) {{
    loadTrack(currentTrack + 1);
    audio.addEventListener('canplay', function onCanPlay() {{
      audio.removeEventListener('canplay', onCanPlay);
      audio.play();
    }});
  }}
}});

loadTrack(0);
</script>

</body>
</html>"""


# ---------------------------------------------------------------------------
# HTML Booklet generation
# ---------------------------------------------------------------------------

def generate_booklet_html(folder: Path, meta: dict, tracks_data: list[dict]) -> None:
    """Generate lyrics_booklet.html from album metadata and parsed LRC data."""
    album_title = meta.get("title", "Album")
    artist = meta.get("artist", "")
    for_whom = meta.get("for", "")
    year = meta.get("year", 2026)

    # Cover tracklist
    tracklist_lines = []
    for t in tracks_data:
        tracklist_lines.append(
            f'    <div><span class="track-num">{t["number"]}</span>{t["title"]}</div>'
        )
    tracklist_html = "\n".join(tracklist_lines)

    # Track pages — lyrics from LRC (plain text, no section tags)
    track_pages = []
    for t in tracks_data:
        lyrics_html = "\n".join(text for _, text in t["lines"])
        # Escape HTML
        lyrics_html = lyrics_html.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        subtitle = t.get("subtitle", "")
        subtitle_html = f'<div class="track-subtitle">{subtitle}</div>' if subtitle else ""
        track_pages.append(f"""\
<div class="track-page">
  <div class="track-header">
    <div class="track-number">{t["number"]}</div>
    <div class="track-title">{t["title"]}</div>
    {subtitle_html}
  </div>
  <div class="lyrics">
{lyrics_html}
  </div>
</div>
""")
    tracks_html = "\n".join(track_pages)

    html = _BOOKLET_TEMPLATE.format(
        album_title=album_title,
        artist=artist,
        for_whom=for_whom,
        year=year,
        tracklist_html=tracklist_html,
        tracks_html=tracks_html,
    )

    out_path = folder / "lyrics_booklet.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"  wrote: {out_path.name}")


_BOOKLET_TEMPLATE = """\
<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{album_title} — Lyrics Booklet</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Oswald:wght@400;700&family=Open+Sans:wght@400;600&display=swap');

  * {{ margin: 0; padding: 0; box-sizing: border-box; }}

  body {{
    background: #1a1a1a;
    color: #e0e0e0;
    font-family: 'Open Sans', Arial, sans-serif;
    font-size: 15px;
    line-height: 1.6;
  }}

  .cover-page {{
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    text-align: center;
    background: linear-gradient(180deg, #0d0d0d 0%, #1a1a1a 50%, #0d0d0d 100%);
    padding: 60px 40px;
    page-break-after: always;
  }}

  .cover-title {{
    font-family: 'Oswald', Impact, sans-serif;
    font-size: 96px;
    font-weight: 700;
    color: #ff3220;
    text-transform: uppercase;
    letter-spacing: 8px;
    text-shadow: 4px 4px 0 #000, 6px 6px 0 rgba(255,50,30,0.3);
    margin-bottom: 20px;
  }}

  .cover-subtitle {{
    font-family: 'Oswald', Impact, sans-serif;
    font-size: 36px;
    color: #ffdc00;
    letter-spacing: 4px;
    margin-bottom: 30px;
  }}

  .cover-tagline {{
    font-style: italic;
    color: #888;
    font-size: 20px;
    margin-bottom: 60px;
  }}

  .cover-tracklist {{
    text-align: left;
    color: #999;
    font-size: 16px;
    line-height: 2.2;
  }}

  .cover-tracklist span.track-num {{
    color: #ff3220;
    font-family: 'Oswald', Impact, sans-serif;
    font-weight: 700;
    margin-right: 12px;
  }}

  .cover-footer {{
    margin-top: 60px;
    color: #555;
    font-size: 13px;
  }}

  .track-page {{
    max-width: 800px;
    margin: 0 auto;
    padding: 60px 40px;
    page-break-after: always;
  }}

  .track-header {{
    border-bottom: 3px solid #ff3220;
    padding-bottom: 20px;
    margin-bottom: 30px;
  }}

  .track-number {{
    font-family: 'Oswald', Impact, sans-serif;
    font-size: 48px;
    font-weight: 700;
    color: #ff3220;
    line-height: 1;
  }}

  .track-title {{
    font-family: 'Oswald', Impact, sans-serif;
    font-size: 36px;
    font-weight: 700;
    color: #fff;
    text-transform: uppercase;
    letter-spacing: 2px;
    margin-top: 5px;
  }}

  .track-subtitle {{
    color: #888;
    font-size: 14px;
    margin-top: 8px;
    font-style: italic;
  }}

  .lyrics {{
    white-space: pre-wrap;
    font-size: 16px;
    line-height: 1.8;
  }}

  .credits-page {{
    max-width: 800px;
    margin: 0 auto;
    padding: 60px 40px;
    text-align: center;
  }}

  .credits-page h2 {{
    font-family: 'Oswald', Impact, sans-serif;
    font-size: 36px;
    color: #ff3220;
    margin-bottom: 40px;
  }}

  .credits-page p {{
    color: #aaa;
    font-size: 16px;
    line-height: 2;
    margin-bottom: 10px;
  }}

  .credits-page .gg {{
    margin-top: 40px;
    font-family: 'Oswald', Impact, sans-serif;
    font-size: 24px;
    color: #ffdc00;
  }}

  @media print {{
    body {{ background: #fff; color: #222; }}
    .cover-page {{ background: #fff; }}
    .cover-title {{ color: #cc0000; text-shadow: none; }}
    .cover-subtitle {{ color: #cc8800; }}
    .track-page {{ padding: 40px 20px; }}
    .lyrics {{ font-size: 14px; }}
  }}
</style>
</head>
<body>

<div class="cover-page">
  <div class="cover-title">{album_title}</div>
  <div class="cover-subtitle">{artist} &rarr; {for_whom}</div>
  <div class="cover-tagline">"what the AI actually sang"</div>
  <div class="cover-tracklist">
{tracklist_html}
  </div>
  <div class="cover-footer">
    AI Generated &bull; {year}
  </div>
</div>

{tracks_html}

<div class="credits-page">
  <h2>CREDITS</h2>
  <p><strong>Written by</strong>: {artist} &amp; Claude Code</p>
  <p><strong>Produced by</strong>: ACE-Step 1.5</p>
  <p><strong>Mastered by</strong>: Songmaker Engine</p>
  <p><strong>For</strong>: {for_whom}</p>
  <div class="gg">GG WP</div>
</div>

</body>
</html>"""


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

def collect_tracks(folder: Path, meta: dict) -> list[dict]:
    """Collect track data by matching album.json entries with LRC files."""
    tracks_data = []
    for track_info in meta.get("tracks", []):
        mp3_name = track_info["file"]
        lrc_path = folder / Path(mp3_name).with_suffix(".lrc").name
        if not lrc_path.exists():
            print(f"  warning: no LRC for {mp3_name}, skipping")
            continue
        lines = parse_lrc(lrc_path)
        tracks_data.append({
            "file": mp3_name,
            "title": track_info.get("title", _title_from_filename(Path(mp3_name).stem)),
            "number": track_info.get("number", ""),
            "subtitle": track_info.get("subtitle", ""),
            "lines": lines,
        })
    return tracks_data


# ---------------------------------------------------------------------------
# Embed lyrics into MP3 ID3 tags
# ---------------------------------------------------------------------------

def embed_lyrics_in_mp3(folder: Path, tracks_data: list[dict]) -> None:
    """Embed LRC lyrics into MP3 files as ID3 tags (USLT + SYLT).

    USLT = unsynchronized lyrics (plain text) — supported by nearly all players.
    SYLT = synchronized lyrics (timestamped) — supported by some players.
    """
    from mutagen.id3 import ID3, ID3NoHeaderError, USLT, SYLT, Encoding

    for t in tracks_data:
        mp3_path = folder / t["file"]
        if not mp3_path.exists():
            continue

        lines = t.get("lines", [])
        if not lines:
            continue

        # Build plain text lyrics (for USLT)
        plain_text = "\n".join(line[1] for line in lines)

        # Build synced lyrics (for SYLT): list of (text, timestamp_ms)
        sylt_data = [(line[1], int(line[0] * 1000)) for line in lines]

        try:
            tags = ID3(str(mp3_path))
        except ID3NoHeaderError:
            tags = ID3()

        # Remove existing lyrics tags
        tags.delall("USLT")
        tags.delall("SYLT")

        # Add unsynchronized lyrics (plain text — universal support)
        tags.add(USLT(
            encoding=Encoding.UTF8,
            lang="deu",
            desc="",
            text=plain_text,
        ))

        # Add synchronized lyrics (timestamped — for players that support it)
        tags.add(SYLT(
            encoding=Encoding.UTF8,
            lang="deu",
            desc="",
            format=2,  # milliseconds
            type=1,    # lyrics
            text=sylt_data,
        ))

        tags.save(str(mp3_path))
        print(f"  embedded lyrics: {mp3_path.name}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync lyrics: transcribe → LRC → HTML")
    parser.add_argument("path", help="Album folder or single MP3 file")
    parser.add_argument("--force", action="store_true", help="Re-transcribe even if LRC exists")
    parser.add_argument("--html-only", action="store_true", help="Only regenerate HTML from existing LRC")
    args = parser.parse_args()

    target = Path(args.path)

    # Determine folder and MP3 list
    if target.is_file() and target.suffix == ".mp3":
        folder = target.parent
        mp3s = [target]
    elif target.is_dir():
        folder = target
        mp3s = sorted(folder.glob("*.mp3"))
    else:
        print(f"Error: {target} is not an MP3 file or directory")
        sys.exit(1)

    if not mp3s:
        print(f"No MP3 files found in {folder}")
        sys.exit(1)

    print(f"\nSync Lyrics: {folder}")
    print(f"  {len(mp3s)} MP3 file(s)\n")

    # Step 0: Ensure album.json
    meta = ensure_album_json(folder)

    # Step 1: Transcribe
    if not args.html_only:
        print("Step 1: Whisper transcription -> LRC")
        for mp3 in mp3s:
            transcribe_to_lrc(mp3, meta, force=args.force)
        print()

    # Step 2+3: Generate HTML
    print("Step 2: Collecting LRC data...")
    tracks_data = collect_tracks(folder, meta)
    if not tracks_data:
        print("  No tracks with LRC files found!")
        sys.exit(1)
    print(f"  {len(tracks_data)} tracks with lyrics\n")

    print("Step 3: Generating HTML...")
    generate_player_html(folder, meta, tracks_data)
    generate_booklet_html(folder, meta, tracks_data)

    print("\nStep 4: Embedding lyrics into MP3s...")
    embed_lyrics_in_mp3(folder, tracks_data)

    print(f"\nDone! Generated:")
    print(f"  LRC files: {sum(1 for _ in folder.glob('*.lrc'))}")
    print(f"  lyrics_player.html")
    print(f"  lyrics_booklet.html")
    print(f"  MP3 lyrics embedded: {len(tracks_data)} tracks")


if __name__ == "__main__":
    main()
