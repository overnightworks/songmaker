"""Check how accurately ACE-Step sang the intended lyrics.

Uses OpenAI Whisper to transcribe a generated MP3/WAV and compares
the transcription against the expected lyrics from the track script.

Usage:
    .venv/Scripts/python scripts/check_lyrics_accuracy.py <audio_file> [--track <track_script>]

Examples:
    # Auto-detect track script from filename:
    .venv/Scripts/python scripts/check_lyrics_accuracy.py _output/apologiez/05_bruder_v7.mp3

    # Explicit track script:
    .venv/Scripts/python scripts/check_lyrics_accuracy.py _output/apologiez/05_bruder_v7.mp3 --track albums/apologiez/tracks/05_bruder.py
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
import textwrap
from difflib import SequenceMatcher
from pathlib import Path


def load_whisper_model(model_size: str = "small"):
    """Load Whisper model (supports German — don't use .en variant)."""
    import whisper

    print(f"  Loading Whisper '{model_size}' model...")
    return whisper.load_model(model_size)


def transcribe(model, audio_path: str, language: str = "de") -> str:
    """Transcribe audio file and return cleaned text."""
    print(f"  Transcribing {Path(audio_path).name}...")
    result = model.transcribe(
        audio_path,
        language=language,
        fp16=False,
        condition_on_previous_text=False,
    )
    return result["text"].strip()


def extract_lyrics_from_track(track_path: str) -> str:
    """Import a track script and extract the lyrics from ACESTEP_CONFIG."""
    path = Path(track_path)
    spec = importlib.util.spec_from_file_location("track_module", str(path))
    if spec is None or spec.loader is None:
        raise ValueError(f"Cannot load module from {track_path}")

    # We need to handle imports — add project root to path
    project_root = str(Path(__file__).resolve().parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    config = getattr(module, "ACESTEP_CONFIG", None)
    if config is None:
        raise ValueError(f"No ACESTEP_CONFIG found in {track_path}")

    return config.lyrics


def clean_lyrics(lyrics: str) -> str:
    """Remove section tags and normalize lyrics to plain words."""
    # Remove [verse], [chorus], etc.
    text = re.sub(r"\[.*?\]", "", lyrics)
    # Remove punctuation except umlauts and ß
    text = re.sub(r"[^\w\sÄäÖöÜüß]", "", text)
    # Collapse whitespace
    text = " ".join(text.split()).lower()
    return text


def clean_transcript(text: str) -> str:
    """Normalize transcription to plain words."""
    text = re.sub(r"[^\w\sÄäÖöÜüß]", "", text)
    text = " ".join(text.split()).lower()
    return text


def _fuzzy_match(word_a: str, word_b: str, threshold: float = 0.7) -> bool:
    """Check if two words are close enough to count as a match.

    Handles Whisper mishearing gaming terms, names, German words:
    - 'Tobbisch' vs 'Topisch' -> match (82% similar)
    - 'Deagle' vs 'Diegle' -> match (83% similar)
    - 'Flexx0r' vs 'Flexor' -> match (83% similar)
    - 'Bruder' vs 'Puder' -> match (83% similar)
    """
    if word_a == word_b:
        return True
    # Character-level similarity using SequenceMatcher
    ratio = SequenceMatcher(None, word_a, word_b).ratio()
    return ratio >= threshold


def word_error_rate(reference: list[str], hypothesis: list[str], fuzzy: bool = True) -> float:
    """Compute WER using Levenshtein distance on word lists.

    With fuzzy=True, words that are >70% character-similar count as matches.
    This handles Whisper mishearing names/slang while still catching real errors.
    """
    n = len(reference)
    m = len(hypothesis)
    if n == 0:
        return 0.0 if m == 0 else 1.0

    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dp[i][0] = i
    for j in range(m + 1):
        dp[0][j] = j

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if fuzzy:
                is_match = _fuzzy_match(reference[i - 1], hypothesis[j - 1])
            else:
                is_match = reference[i - 1] == hypothesis[j - 1]

            if is_match:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = 1 + min(
                    dp[i - 1][j],
                    dp[i][j - 1],
                    dp[i - 1][j - 1],
                )

    return dp[n][m] / n


def find_mismatches(reference: list[str], hypothesis: list[str], fuzzy: bool = True) -> list[str]:
    """Find specific word-level mismatches (skip fuzzy matches)."""
    mismatched = []
    matcher = SequenceMatcher(None, reference, hypothesis)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "replace":
            # With fuzzy matching, skip replacements that are close enough
            if fuzzy and (i2 - i1) == 1 and (j2 - j1) == 1:
                if _fuzzy_match(reference[i1], hypothesis[j1]):
                    continue  # Close enough — not a real error
            mismatched.append(f"  '{' '.join(reference[i1:i2])}' -> '{' '.join(hypothesis[j1:j2])}'")
        elif tag == "delete":
            mismatched.append(f"  '{' '.join(reference[i1:i2])}' -> MISSING")
        elif tag == "insert":
            mismatched.append(f"  EXTRA -> '{' '.join(hypothesis[j1:j2])}'")
    return mismatched


def guess_track_script(audio_path: str) -> str | None:
    """Try to find the track script based on the audio filename."""
    audio_name = Path(audio_path).stem
    # Remove version suffix like _v7, _v12
    base = re.sub(r"_v\d+(_raw)?$", "", audio_name)

    # Search in all album track directories
    project_root = Path(__file__).resolve().parent.parent
    for track_file in project_root.glob("albums/*/tracks/*.py"):
        if track_file.stem == base:
            return str(track_file)
    return None


def transcribe_segments(model, audio_path: str, language: str = "de") -> list[dict]:
    """Transcribe audio and return segment-level results."""
    print(f"  Transcribing {Path(audio_path).name}...")
    result = model.transcribe(
        audio_path,
        language=language,
        fp16=False,
        condition_on_previous_text=False,
    )
    return result["segments"]


def detect_nonsense(text: str) -> list[str]:
    """Detect nonsense patterns in transcribed text."""
    issues = []

    # Repeated syllables (ah ah ah, wooh wooh, la la la)
    repeated = re.findall(r'\b(\w{1,4})\s+(?:\1\s*){2,}', text.lower())
    if repeated:
        issues.append(f"Repeated syllables: {', '.join(set(repeated))}")

    # Common vocal filler sounds
    fillers = re.findall(
        r'\b(?:ah|oh|wooh|ooh|hmm|uh|eh|na na|la la|da da|sha|doo|bah)\b',
        text.lower(),
    )
    if len(fillers) > 3:
        issues.append(f"Vocal fillers ({len(fillers)}x): {', '.join(fillers[:8])}")

    # Very short words repeated (likely mumbling)
    words = text.lower().split()
    if len(words) > 5:
        single_char = sum(1 for w in words if len(w) <= 2 and w not in {
            "ich", "du", "er", "es", "in", "am", "um", "an", "im", "zu",
            "so", "da", "ja", "no", "is", "on", "up", "we", "go", "or",
            "if", "my", "me", "it", "us", "of", "at", "to", "do", "be",
        })
        if single_char > len(words) * 0.3:
            issues.append(f"High mumble ratio: {single_char}/{len(words)} tiny words")

    return issues


def reconstruct_actual_lyrics(segments: list[dict]) -> str:
    """Reconstruct what was actually sung, line by line with timestamps."""
    lines = []
    for seg in segments:
        text = seg["text"].strip()
        if not text:
            continue
        start = seg["start"]
        mins = int(start // 60)
        secs = int(start % 60)
        lines.append(f"  [{mins}:{secs:02d}] {text}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Check lyrics accuracy of generated audio")
    parser.add_argument("audio", nargs="+", help="Path(s) to MP3 or WAV file(s)")
    parser.add_argument("--track", help="Path to track .py script (auto-detected if omitted)")
    parser.add_argument("--model", default="small", help="Whisper model size (default: small)")
    parser.add_argument("--language", default="de", help="Audio language (default: de)")
    args = parser.parse_args()

    # Load model once for all files
    model = load_whisper_model(args.model)

    for audio_file in args.audio:
        audio_path = Path(audio_file)
        if not audio_path.exists():
            print(f"ERROR: Audio file not found: {audio_path}")
            continue

        # Find track script
        track_path = args.track or guess_track_script(str(audio_path))
        if track_path is None:
            print(f"ERROR: Cannot auto-detect track script for '{audio_path.stem}'")
            print("  Use --track <path> to specify it manually")
            continue

        print(f"\n{'=' * 60}")
        print(f"  Lyrics Accuracy Check")
        print(f"  Audio: {audio_path.name}")
        print(f"  Track: {Path(track_path).name}")
        print(f"{'=' * 60}")

        # Extract expected lyrics
        print("\n  Loading expected lyrics...")
        raw_lyrics = extract_lyrics_from_track(track_path)
        expected = clean_lyrics(raw_lyrics)
        expected_words = expected.split()
        print(f"  Expected: {len(expected_words)} words")

        # Transcribe with segments
        segments = transcribe_segments(model, str(audio_path), args.language)
        full_transcript = " ".join(s["text"].strip() for s in segments)
        transcript = clean_transcript(full_transcript)
        transcript_words = transcript.split()
        print(f"  Heard:    {len(transcript_words)} words")

        # Score
        wer = word_error_rate(expected_words, transcript_words)
        accuracy = max(0.0, 1.0 - wer)

        if accuracy >= 0.8:
            grade = "GOOD"
        elif accuracy >= 0.6:
            grade = "OK"
        elif accuracy >= 0.4:
            grade = "POOR"
        else:
            grade = "BAD"

        print(f"\n  ACCURACY: {accuracy:.0%} ({grade})")
        print(f"  WER:      {wer:.0%}")

        # Nonsense/coherence check
        nonsense = detect_nonsense(transcript)
        if nonsense:
            print(f"\n  COHERENCE ISSUES:")
            for issue in nonsense:
                print(f"    - {issue}")

        # Show what was different
        mismatches = find_mismatches(expected_words, transcript_words)
        if mismatches:
            print(f"\n  Word differences ({len(mismatches)}):")
            for m in mismatches[:30]:
                print(m)
            if len(mismatches) > 30:
                print(f"  ... and {len(mismatches) - 30} more")

        # Reconstructed actual lyrics (what the song REALLY says)
        print(f"\n  ACTUAL SUNG LYRICS (what Whisper heard):")
        print(f"  {'-' * 50}")
        actual = reconstruct_actual_lyrics(segments)
        print(actual)

        # Expected for comparison
        print(f"\n  INTENDED LYRICS:")
        print(f"  {'-' * 50}")
        # Show with section tags preserved
        for line in raw_lyrics.strip().split("\n"):
            line = line.strip()
            if line:
                print(f"  {line}")

        print(f"\n{'=' * 60}")

    print()


if __name__ == "__main__":
    main()
