"""Generate a song with ACE-Step, transcribe with Whisper, and score.

Each generation gets its own subfolder with:
  - The MP3 file
  - Whisper transcription (actual sung lyrics)
  - Accuracy analysis (WER, differences, nonsense detection)

After generating, updates the HTML dashboard for easy comparison.

Usage:
    .venv/Scripts/python scripts/generate_and_check.py albums/apologiez/tracks/05_bruder.py
    .venv/Scripts/python scripts/generate_and_check.py albums/apologiez/tracks/05_bruder.py --count 3
    .venv/Scripts/python scripts/generate_and_check.py albums/apologiez/tracks/05_bruder.py --count 3 --cooldown 30
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

# Project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from check_lyrics_accuracy import (
    clean_lyrics,
    clean_transcript,
    detect_nonsense,
    find_mismatches,
    word_error_rate,
)


OUTPUT_BASE = PROJECT_ROOT / "_output" / "apologiez"


def load_track_module(track_path: str):
    """Load a track script as a module."""
    spec = importlib.util.spec_from_file_location("track_mod", track_path)
    if spec is None or spec.loader is None:
        raise ValueError(f"Cannot load {track_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def get_next_run_number(track_dir: Path) -> int:
    """Get next run number for a track."""
    existing = [d for d in track_dir.iterdir() if d.is_dir() and d.name.startswith("run_")]
    if not existing:
        return 1
    nums = []
    for d in existing:
        match = re.match(r"run_(\d+)", d.name)
        if match:
            nums.append(int(match.group(1)))
    return max(nums, default=0) + 1


def transcribe_audio(audio_path: str, language: str = "de") -> tuple[list[dict], str]:
    """Transcribe audio with Whisper, return segments and full text."""
    import whisper
    print("  Loading Whisper model...")
    model = whisper.load_model("small")
    print(f"  Transcribing {Path(audio_path).name}...")
    result = model.transcribe(
        audio_path,
        language=language,
        fp16=False,
        condition_on_previous_text=False,
    )
    return result["segments"], result["text"].strip()


def format_segments(segments: list[dict]) -> str:
    """Format segments as timestamped lyrics."""
    lines = []
    for seg in segments:
        text = seg["text"].strip()
        if not text:
            continue
        start = seg["start"]
        mins = int(start // 60)
        secs = int(start % 60)
        lines.append(f"[{mins}:{secs:02d}] {text}")
    return "\n".join(lines)


def generate_one(track_path: str, run_dir: Path) -> dict | None:
    """Generate one version of the song and analyze it."""
    from acestep_engine import AceStepClient, is_acestep_available
    from bark_engine.audio_io import master_to_mp3, normalize_audio, write_wav_file

    mod = load_track_module(track_path)
    config = mod.ACESTEP_CONFIG

    if not is_acestep_available():
        print("  ERROR: ACE-Step server not running!")
        return None

    print("  Generating via ACE-Step...")
    client = AceStepClient()
    result = client.generate(config)
    if result is None:
        print("  ERROR: Generation failed!")
        return None

    # Save audio
    run_dir.mkdir(parents=True, exist_ok=True)
    track_name = Path(track_path).stem
    mp3_name = f"{track_name}.mp3"
    wav_path = str(run_dir / f"{track_name}.wav")
    mp3_path = str(run_dir / mp3_name)

    samples = normalize_audio(result.samples, 0.95)
    write_wav_file(wav_path, samples)
    master_to_mp3(wav_path, mp3_path, bitrate="320k")

    # Clean up WAV (keep MP3 only)
    Path(wav_path).unlink(missing_ok=True)

    # Transcribe
    segments, raw_text = transcribe_audio(mp3_path, config.vocal_language or "de")
    actual_lyrics = format_segments(segments)
    transcript = clean_transcript(raw_text)
    transcript_words = transcript.split()

    # Score
    expected = clean_lyrics(config.lyrics)
    expected_words = expected.split()
    wer = word_error_rate(expected_words, transcript_words)
    accuracy = max(0.0, 1.0 - wer)

    nonsense = detect_nonsense(transcript)
    mismatches = find_mismatches(expected_words, transcript_words)

    # Save analysis
    analysis = {
        "track": track_name,
        "timestamp": datetime.now().isoformat(),
        "accuracy": round(accuracy, 3),
        "wer": round(wer, 3),
        "expected_words": len(expected_words),
        "heard_words": len(transcript_words),
        "nonsense_issues": nonsense,
        "mp3_file": mp3_name,
        "actual_lyrics": actual_lyrics,
        "transcript_clean": transcript,
        "mismatches": [m.strip() for m in mismatches[:30]],
        "seed": getattr(result, "seed", -1),
        "duration": getattr(result, "duration", 0),
        "intended_lyrics": config.lyrics.strip(),
    }

    with open(run_dir / "analysis.json", "w", encoding="utf-8") as f:
        json.dump(analysis, f, indent=2, ensure_ascii=False)

    # Save actual lyrics as readable text
    with open(run_dir / "actual_lyrics.txt", "w", encoding="utf-8") as f:
        f.write(f"# {track_name} - Actual Sung Lyrics\n")
        f.write(f"# Accuracy: {accuracy:.0%}\n")
        f.write(f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
        f.write(actual_lyrics)

    if accuracy >= 0.8:
        grade = "GOOD"
    elif accuracy >= 0.6:
        grade = "OK"
    elif accuracy >= 0.4:
        grade = "POOR"
    else:
        grade = "BAD"

    print(f"\n  RESULT: {accuracy:.0%} accuracy ({grade})")
    if nonsense:
        for issue in nonsense:
            print(f"  NONSENSE: {issue}")

    return analysis


def build_dashboard(output_dir: Path) -> None:
    """Build HTML dashboard from all run folders."""
    # Collect all analyses
    tracks: dict[str, list[dict]] = {}

    for track_dir in sorted(output_dir.iterdir()):
        if not track_dir.is_dir() or track_dir.name == "final":
            continue
        for run_dir in sorted(track_dir.iterdir()):
            if not run_dir.is_dir() or not run_dir.name.startswith("run_"):
                continue
            analysis_file = run_dir / "analysis.json"
            if not analysis_file.exists():
                continue
            with open(analysis_file, encoding="utf-8") as f:
                data = json.load(f)
            data["run_dir"] = str(run_dir.relative_to(output_dir))
            track_name = data.get("track", track_dir.name)
            if track_name not in tracks:
                tracks[track_name] = []
            tracks[track_name].append(data)

    if not tracks:
        print("  No runs found yet.")
        return

    # Sort each track's runs by accuracy (best first)
    for track_name in tracks:
        tracks[track_name].sort(key=lambda r: r["accuracy"], reverse=True)

    # Generate HTML
    html = _generate_html(tracks, output_dir)
    dashboard_path = output_dir / "dashboard.html"
    with open(dashboard_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  Dashboard: {dashboard_path}")


def _generate_html(tracks: dict[str, list[dict]], output_dir: Path) -> str:
    """Generate the HTML dashboard."""
    track_cards = []
    detail_sections = []

    for track_name, runs in tracks.items():
        best = runs[0] if runs else None
        best_pct = f"{best['accuracy']:.0%}" if best else "N/A"

        # Card for overview
        track_cards.append(f"""
        <div class="track-card" onclick="showTrack('{track_name}')">
            <h3>{track_name.replace('_', ' ').title()}</h3>
            <div class="stats">
                <span class="versions">{len(runs)} versions</span>
                <span class="best-score">Best: {best_pct}</span>
            </div>
        </div>""")

        # Detail section
        run_rows = []
        run_details = []
        for i, run in enumerate(runs):
            acc = run["accuracy"]
            if acc >= 0.8:
                badge = "good"
            elif acc >= 0.6:
                badge = "ok"
            elif acc >= 0.4:
                badge = "poor"
            else:
                badge = "bad"

            run_id = run["run_dir"].split("/")[-1]
            mp3_rel = f"{run['run_dir']}/{run['mp3_file']}"
            nonsense_flag = " !!!" if run.get("nonsense_issues") else ""

            run_rows.append(f"""
                <tr class="run-row" onclick="showRunDetail('{track_name}_{run_id}')">
                    <td>{run_id}</td>
                    <td><span class="badge {badge}">{acc:.0%}</span>{nonsense_flag}</td>
                    <td>{run.get('heard_words', '?')}/{run.get('expected_words', '?')}</td>
                    <td>{run.get('timestamp', '')[:16]}</td>
                    <td><audio controls preload="none" src="{mp3_rel}"></audio></td>
                </tr>""")

            # Actual lyrics with escape
            actual = run.get("actual_lyrics", "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            intended = run.get("intended_lyrics", "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            mismatches_html = ""
            for m in run.get("mismatches", []):
                m_escaped = m.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                mismatches_html += f"<li>{m_escaped}</li>\n"

            nonsense_html = ""
            for ns in run.get("nonsense_issues", []):
                nonsense_html += f"<li class='nonsense'>{ns}</li>\n"

            run_details.append(f"""
            <div id="{track_name}_{run_id}" class="run-detail" style="display:none">
                <h4>{run_id} - {acc:.0%} accuracy</h4>
                <audio controls src="{mp3_rel}" style="width:100%;margin:10px 0"></audio>
                {f'<div class="nonsense-box"><h5>Nonsense Issues</h5><ul>{nonsense_html}</ul></div>' if nonsense_html else ''}
                <div class="lyrics-compare">
                    <div class="lyrics-col">
                        <h5>What was sung:</h5>
                        <pre>{actual}</pre>
                    </div>
                    <div class="lyrics-col">
                        <h5>Intended lyrics:</h5>
                        <pre>{intended}</pre>
                    </div>
                </div>
                {f'<div class="mismatches"><h5>Differences ({len(run.get("mismatches", []))}):</h5><ul>{mismatches_html}</ul></div>' if mismatches_html else ''}
            </div>""")

        detail_sections.append(f"""
        <div id="track_{track_name}" class="track-detail" style="display:none">
            <h2>{track_name.replace('_', ' ').title()}</h2>
            <button onclick="hideTrack()" class="back-btn">&larr; Back</button>
            <table class="runs-table">
                <thead><tr>
                    <th>Run</th><th>Accuracy</th><th>Words</th><th>Time</th><th>Listen</th>
                </tr></thead>
                <tbody>{''.join(run_rows)}</tbody>
            </table>
            {''.join(run_details)}
        </div>""")

    return f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<title>Apologiez - Generation Dashboard</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #1a1a2e; color: #eee; padding: 20px; }}
h1 {{ text-align: center; color: #ff3322; font-size: 2em; margin: 20px 0; text-transform: uppercase; letter-spacing: 3px; }}
.subtitle {{ text-align: center; color: #888; margin-bottom: 30px; }}
.overview {{ display: flex; flex-wrap: wrap; gap: 15px; justify-content: center; }}
.track-card {{ background: #16213e; border: 1px solid #333; border-radius: 10px; padding: 20px; width: 280px; cursor: pointer; transition: all 0.2s; }}
.track-card:hover {{ border-color: #ff3322; transform: translateY(-2px); box-shadow: 0 4px 15px rgba(255,51,34,0.2); }}
.track-card h3 {{ color: #ffdd00; margin-bottom: 10px; }}
.stats {{ display: flex; justify-content: space-between; color: #aaa; }}
.best-score {{ color: #4caf50; font-weight: bold; }}
.back-btn {{ background: #333; color: #fff; border: none; padding: 8px 16px; border-radius: 5px; cursor: pointer; margin: 10px 0; }}
.back-btn:hover {{ background: #555; }}
.runs-table {{ width: 100%; border-collapse: collapse; margin: 15px 0; }}
.runs-table th {{ background: #16213e; padding: 10px; text-align: left; border-bottom: 2px solid #333; }}
.runs-table td {{ padding: 10px; border-bottom: 1px solid #222; }}
.run-row {{ cursor: pointer; transition: background 0.2s; }}
.run-row:hover {{ background: #16213e; }}
.badge {{ padding: 3px 10px; border-radius: 12px; font-size: 0.85em; font-weight: bold; }}
.badge.good {{ background: #1b5e20; color: #4caf50; }}
.badge.ok {{ background: #33691e; color: #8bc34a; }}
.badge.poor {{ background: #e65100; color: #ff9800; }}
.badge.bad {{ background: #b71c1c; color: #ef5350; }}
.run-detail {{ background: #16213e; border-radius: 10px; padding: 20px; margin: 15px 0; }}
.lyrics-compare {{ display: flex; gap: 20px; margin: 15px 0; }}
.lyrics-col {{ flex: 1; }}
.lyrics-col h5 {{ color: #ffdd00; margin-bottom: 8px; }}
.lyrics-col pre {{ background: #0a0a1a; padding: 15px; border-radius: 8px; white-space: pre-wrap; font-size: 0.9em; line-height: 1.6; max-height: 500px; overflow-y: auto; }}
.mismatches {{ margin: 15px 0; }}
.mismatches h5 {{ color: #ff9800; margin-bottom: 8px; }}
.mismatches ul {{ list-style: none; }}
.mismatches li {{ padding: 4px 0; color: #ccc; font-family: monospace; font-size: 0.85em; }}
.nonsense-box {{ background: #3e1010; border: 1px solid #ff3322; border-radius: 8px; padding: 15px; margin: 10px 0; }}
.nonsense-box h5 {{ color: #ff3322; }}
.nonsense {{ color: #ff6666; }}
audio {{ height: 32px; }}
</style>
</head>
<body>
<h1>APOLOGIEZ</h1>
<p class="subtitle">Generation Dashboard - {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>

<div id="overview" class="overview">
{''.join(track_cards)}
</div>

{''.join(detail_sections)}

<script>
function showTrack(name) {{
    document.getElementById('overview').style.display = 'none';
    document.querySelectorAll('.track-detail').forEach(el => el.style.display = 'none');
    document.getElementById('track_' + name).style.display = 'block';
}}
function hideTrack() {{
    document.querySelectorAll('.track-detail').forEach(el => el.style.display = 'none');
    document.getElementById('overview').style.display = 'flex';
}}
function showRunDetail(id) {{
    var el = document.getElementById(id);
    if (el.style.display === 'none') {{
        document.querySelectorAll('.run-detail').forEach(d => d.style.display = 'none');
        el.style.display = 'block';
    }} else {{
        el.style.display = 'none';
    }}
}}
</script>
</body>
</html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate, transcribe, and score a song")
    parser.add_argument("track", help="Path to track .py script")
    parser.add_argument("--count", type=int, default=1, help="Number of versions to generate")
    parser.add_argument("--cooldown", type=int, default=30, help="Seconds between generations")
    parser.add_argument("--dashboard-only", action="store_true", help="Only rebuild dashboard")
    args = parser.parse_args()

    if args.dashboard_only:
        build_dashboard(OUTPUT_BASE)
        return

    track_path = str(Path(args.track).resolve())
    track_name = Path(track_path).stem

    # Track gets its own directory
    track_dir = OUTPUT_BASE / track_name
    track_dir.mkdir(parents=True, exist_ok=True)

    for i in range(args.count):
        run_num = get_next_run_number(track_dir)
        run_dir = track_dir / f"run_{run_num:02d}"

        print(f"\n{'=' * 60}")
        print(f"  {track_name} - Run {run_num} ({i+1}/{args.count})")
        print(f"{'=' * 60}")

        result = generate_one(track_path, run_dir)

        if result is None:
            print("  Skipping (generation failed)")
            continue

        # Cooldown between generations
        if i < args.count - 1:
            print(f"\n  Cooling down {args.cooldown}s...")
            time.sleep(args.cooldown)

    # Rebuild dashboard
    print(f"\n{'=' * 60}")
    print("  Rebuilding dashboard...")
    build_dashboard(OUTPUT_BASE)


if __name__ == "__main__":
    main()
