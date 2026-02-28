"""Compare multiple versions of a generated song.

Transcribes each version with Whisper, scores accuracy, detects nonsense,
and generates a markdown comparison file for human review.

Usage:
    .venv/Scripts/python scripts/compare_versions.py 05_bruder
    .venv/Scripts/python scripts/compare_versions.py bonus_fire_in_the_hole --versions 7 8 9

Output:
    _output/apologiez/05_bruder_comparison.md
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from datetime import datetime
from pathlib import Path

# Reuse functions from check_lyrics_accuracy
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_lyrics_accuracy import (
    clean_lyrics,
    clean_transcript,
    detect_nonsense,
    find_mismatches,
    word_error_rate,
)


OUTPUT_DIR = Path("_output/apologiez")


def load_whisper_model(model_size: str = "small"):
    """Load Whisper model."""
    import whisper
    print(f"  Loading Whisper '{model_size}' model...")
    return whisper.load_model(model_size)


def transcribe_segments(model, audio_path: str, language: str = "de") -> list[dict]:
    """Transcribe audio and return segments."""
    print(f"  Transcribing {Path(audio_path).name}...")
    result = model.transcribe(
        audio_path,
        language=language,
        fp16=False,
        condition_on_previous_text=False,
    )
    return result["segments"]


def extract_lyrics_from_track(track_path: str) -> str:
    """Import track script and get lyrics."""
    path = Path(track_path)
    spec = importlib.util.spec_from_file_location("track_module", str(path))
    if spec is None or spec.loader is None:
        raise ValueError(f"Cannot load module from {track_path}")
    project_root = str(Path(__file__).resolve().parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    config = getattr(module, "ACESTEP_CONFIG", None)
    if config is None:
        raise ValueError(f"No ACESTEP_CONFIG found in {track_path}")
    return config.lyrics


def find_track_script(base_name: str) -> str | None:
    """Find track script by base name."""
    project_root = Path(__file__).resolve().parent.parent
    for track_file in project_root.glob("albums/*/tracks/*.py"):
        if track_file.stem == base_name:
            return str(track_file)
    return None


def format_timestamp(seconds: float) -> str:
    """Format seconds as M:SS."""
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{mins}:{secs:02d}"


def segments_to_lyrics(segments: list[dict], max_time: float = 0) -> str:
    """Convert Whisper segments to readable lyrics with timestamps."""
    lines = []
    for seg in segments:
        text = seg["text"].strip()
        if not text:
            continue
        # Skip hallucination tail (if Whisper hears gibberish after singing ends)
        if max_time > 0 and seg["start"] > max_time:
            break
        ts = format_timestamp(seg["start"])
        lines.append(f"[{ts}] {text}")
    return "\n".join(lines)


def detect_hallucination_start(segments: list[dict]) -> float:
    """Detect where Whisper starts hallucinating (gibberish after singing ends)."""
    if not segments:
        return 0
    # Look for signs of hallucination: non-German words, repeated patterns
    hallucination_markers = [
        r"vielen dank", r"danke", r"untertitel", r"subtitle",
        r"sie m.ssen", r"bitte", r"abonnieren",
    ]
    for seg in segments:
        text = seg["text"].strip().lower()
        for marker in hallucination_markers:
            if re.search(marker, text):
                return seg["start"]
    return segments[-1]["end"] if segments else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare song versions")
    parser.add_argument("track", help="Track base name (e.g., 05_bruder)")
    parser.add_argument("--versions", nargs="*", type=int, help="Specific versions to compare")
    parser.add_argument("--model", default="small", help="Whisper model size")
    parser.add_argument("--language", default="de", help="Audio language")
    args = parser.parse_args()

    base_name = args.track

    # Find all versions
    if args.versions:
        mp3_files = [OUTPUT_DIR / f"{base_name}_v{v}.mp3" for v in args.versions]
        mp3_files = [f for f in mp3_files if f.exists()]
    else:
        mp3_files = sorted(OUTPUT_DIR.glob(f"{base_name}_v*.mp3"))

    if not mp3_files:
        print(f"ERROR: No MP3 files found for {base_name}")
        sys.exit(1)

    # Find track script
    track_path = find_track_script(base_name)
    if track_path is None:
        print(f"ERROR: No track script found for {base_name}")
        sys.exit(1)

    print(f"\n{'=' * 60}")
    print(f"  Version Comparison: {base_name}")
    print(f"  Versions: {len(mp3_files)}")
    print(f"{'=' * 60}")

    # Get expected lyrics
    raw_lyrics = extract_lyrics_from_track(track_path)
    expected = clean_lyrics(raw_lyrics)
    expected_words = expected.split()

    # Load Whisper once
    model = load_whisper_model(args.model)

    # Analyze each version
    results = []
    for mp3 in mp3_files:
        version = re.search(r"_v(\d+)", mp3.stem)
        v_num = int(version.group(1)) if version else 0

        segments = transcribe_segments(model, str(mp3), args.language)
        full_text = " ".join(s["text"].strip() for s in segments)
        transcript = clean_transcript(full_text)
        transcript_words = transcript.split()

        wer = word_error_rate(expected_words, transcript_words)
        accuracy = max(0.0, 1.0 - wer)

        # Detect where real singing ends vs hallucination
        halluc_start = detect_hallucination_start(segments)
        actual_lyrics = segments_to_lyrics(segments, max_time=halluc_start)

        nonsense = detect_nonsense(transcript)
        mismatches = find_mismatches(expected_words, transcript_words)

        results.append({
            "version": v_num,
            "file": mp3.name,
            "accuracy": accuracy,
            "wer": wer,
            "word_count": len(transcript_words),
            "actual_lyrics": actual_lyrics,
            "full_transcript": transcript,
            "nonsense": nonsense,
            "mismatches": mismatches,
            "halluc_start": halluc_start,
        })

        if accuracy >= 0.8:
            grade = "GOOD"
        elif accuracy >= 0.6:
            grade = "OK"
        elif accuracy >= 0.4:
            grade = "POOR"
        else:
            grade = "BAD"
        print(f"  v{v_num}: {accuracy:.0%} ({grade}) - {len(transcript_words)} words heard")

    # Sort by accuracy
    results.sort(key=lambda r: r["accuracy"], reverse=True)

    # Generate comparison markdown
    md_path = OUTPUT_DIR / f"{base_name}_comparison.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# {base_name} - Version Comparison\n\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")

        # Summary table
        f.write("## Summary (sorted by accuracy)\n\n")
        f.write("| Version | Accuracy | Words | Nonsense | Your Rating |\n")
        f.write("|---------|----------|-------|----------|-------------|\n")
        for r in results:
            ns = "Yes" if r["nonsense"] else "No"
            f.write(f"| v{r['version']} | {r['accuracy']:.0%} | {r['word_count']} | {ns} | _______ |\n")

        f.write("\n---\n\n")

        # Intended lyrics
        f.write("## Intended Lyrics\n\n")
        f.write("```\n")
        for line in raw_lyrics.strip().split("\n"):
            f.write(f"{line.strip()}\n")
        f.write("```\n\n")
        f.write("---\n\n")

        # Each version detail
        for r in results:
            f.write(f"## Version {r['version']} - {r['accuracy']:.0%} accuracy\n\n")
            f.write(f"**File**: `{r['file']}`\n\n")

            if r["nonsense"]:
                f.write("**Coherence issues**:\n")
                for issue in r["nonsense"]:
                    f.write(f"- {issue}\n")
                f.write("\n")

            f.write("### What was actually sung:\n\n")
            f.write("```\n")
            f.write(r["actual_lyrics"])
            f.write("\n```\n\n")

            if r["mismatches"]:
                f.write(f"### Key differences ({len(r['mismatches'])}):\n\n")
                for m in r["mismatches"][:20]:
                    f.write(f"- {m.strip()}\n")
                if len(r["mismatches"]) > 20:
                    f.write(f"- ... and {len(r['mismatches']) - 20} more\n")
                f.write("\n")

            f.write("### Your notes:\n\n")
            f.write("_Write your thoughts here..._\n\n")
            f.write("---\n\n")

        # Final pick section
        f.write("## Final Pick\n\n")
        f.write("**Winner**: v___\n\n")
        f.write("**Reason**: ___\n\n")

    print(f"\n  Comparison saved: {md_path}")
    print(f"  Open it and fill in your ratings!")


if __name__ == "__main__":
    main()
