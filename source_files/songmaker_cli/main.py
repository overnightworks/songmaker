"""Songmaker CLI — generate songs from markdown, sync lyrics."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")


def next_version(output_dir: Path, base_name: str) -> int:
    """Find the next version number for a track (v1, v2, ...)."""
    existing = list(output_dir.glob(f"{base_name}_v*.mp3"))
    if not existing:
        return 1
    versions = []
    for p in existing:
        part = p.stem.replace(base_name + "_v", "")
        if part.isdigit():
            versions.append(int(part))
    return max(versions, default=0) + 1


def cmd_generate(args: argparse.Namespace) -> None:
    """Generate a song from a markdown file via ACE-Step."""
    from acestep_engine import AceStepClient, AceStepConfig, is_acestep_available
    from bark_engine.audio_io import master_to_mp3, normalize_audio, write_wav_file
    from songmaker_cli.parser import parse_song_md

    md_path = Path(args.path).resolve()
    if not md_path.exists():
        print(f"  ERROR: {md_path} not found")
        sys.exit(1)

    meta = parse_song_md(md_path)
    title = meta.get("title", md_path.stem)
    album = meta.get("album", md_path.parent.parent.name)
    prompt = meta.get("prompt", "")
    lyrics = meta.get("lyrics", "")

    if not prompt:
        print("  ERROR: No 'prompt' field in frontmatter")
        sys.exit(1)
    if not lyrics:
        print("  ERROR: No '## Lyrics' section found")
        sys.exit(1)

    # Build output path
    output_dir = Path(f"_output/{album}")
    output_dir.mkdir(parents=True, exist_ok=True)
    base_name = md_path.stem
    version = next_version(output_dir, base_name)
    versioned = f"{base_name}_v{version}"

    # Build config
    seed = args.seed if args.seed is not None else meta.get("seed", -1)
    config = AceStepConfig(
        prompt=prompt,
        lyrics=lyrics,
        bpm=meta.get("bpm", 120) or None,  # 0 = let model decide
        duration=meta.get("duration", 60),
        key=meta.get("key", "") or "",
        time_signature=meta.get("time_signature", "") or "",
        vocal_language=meta.get("language", "en"),
        seed=seed,
        inference_steps=meta.get("inference_steps", 8),
        guidance_scale=meta.get("guidance_scale", 0.0),
        shift=meta.get("shift", 3.0),
        think_mode=meta.get("think_mode", True),
        lm_temperature=meta.get("lm_temperature", 0.85),
        infer_method=meta.get("infer_method", "ode"),
    )

    print("=" * 60)
    print(f"  {title} — v{version}")
    print(f"  {config.bpm} BPM | {config.key} | {config.duration}s")
    print(f"  Album: {album}")
    print("=" * 60)

    if not is_acestep_available():
        print("  ERROR: ACE-Step server not running!")
        print("  Start it with: python scripts/start_acestep.py")
        sys.exit(1)

    print("\n  Generating via ACE-Step...")
    start_time = time.time()
    client = AceStepClient()
    result = client.generate(config)
    if result is None:
        print("  ERROR: Generation failed!")
        sys.exit(1)

    raw_wav = str(output_dir / f"{versioned}_raw.wav")
    write_wav_file(raw_wav, result.samples)

    samples = normalize_audio(result.samples, 0.95)
    wav_path = str(output_dir / f"{versioned}.wav")
    write_wav_file(wav_path, samples)

    # Read album metadata for ID3 tags
    album_yaml = Path(f"albums/{album}/album.yaml")
    album_artist = "Flex0r"
    album_title_tag = album.replace("_", " ").title()
    if album_yaml.exists():
        for line in album_yaml.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("artist:"):
                album_artist = line.split(":", 1)[1].strip().strip('"')
            elif line.strip().startswith("title:"):
                album_title_tag = line.split(":", 1)[1].strip().strip('"')

    mp3_path = str(output_dir / f"{versioned}.mp3")
    id3_metadata = {
        "title": title,
        "artist": album_artist,
        "album": album_title_tag,
        "track": str(meta.get("track", "")),
        "genre": meta.get("genre", ""),
        "lyrics": lyrics,
    }
    master_to_mp3(wav_path, mp3_path, metadata=id3_metadata)

    elapsed = time.time() - start_time
    print(f"\n{'=' * 60}")
    print(f"  Done: {mp3_path}")
    print(f"  Time: {elapsed:.0f}s | Duration: {result.duration:.1f}s | Seed: {result.seed}")
    print(f"{'=' * 60}")

    # Regenerate the unified player
    from songmaker_cli.player import generate_player
    player_root = output_dir.parent
    player_path = generate_player(player_root)
    print(f"  Player updated: {player_path}")

    if args.check:
        print(f"\n  Running lyrics check...")
        check_args = argparse.Namespace(path=str(mp3_path), source=str(md_path))
        cmd_check(check_args)

    if args.sync:
        final_dir = output_dir / "final"
        if final_dir.exists():
            print(f"\n  Running sync on {final_dir}...")
            _run_sync(str(final_dir), force=False)


def cmd_player(args: argparse.Namespace) -> None:
    """Generate the unified HTML player for all albums."""
    from songmaker_cli.player import generate_player

    output_dir = Path(args.output).resolve()
    project_root = Path(args.root).resolve() if args.root else None

    if not output_dir.exists():
        print(f"  ERROR: {output_dir} not found")
        sys.exit(1)

    player_path = generate_player(output_dir, project_root)
    print(f"  Player generated: {player_path}")


def cmd_check(args: argparse.Namespace) -> None:
    """Check lyrics accuracy: transcribe with Whisper, compare to intended."""
    from difflib import SequenceMatcher

    from songmaker_cli.parser import parse_song_md

    mp3_path = Path(args.path).resolve()
    if not mp3_path.exists():
        print(f"  ERROR: {mp3_path} not found")
        sys.exit(1)

    # Find the markdown source
    md_path = None
    if args.source:
        md_path = Path(args.source).resolve()
    else:
        # Auto-detect from filename
        stem = mp3_path.stem
        import re
        base = re.sub(r"_v\d+$", "", stem)
        for album_dir in Path("albums").iterdir():
            candidate = album_dir / "lyrics" / f"{base}.md"
            if candidate.exists():
                md_path = candidate
                break

    if not md_path or not md_path.exists():
        print(f"  ERROR: Could not find lyrics source for {mp3_path.name}")
        print("  Use --source to specify the .md file")
        sys.exit(1)

    meta = parse_song_md(md_path)
    intended = meta.get("lyrics", "")
    language = meta.get("language", "de")

    # Transcribe with Whisper
    import whisper
    print(f"  Loading Whisper model...")
    model = whisper.load_model("small")
    print(f"  Transcribing {mp3_path.name}...")
    result = model.transcribe(
        str(mp3_path), language=language, fp16=False,
        condition_on_previous_text=False,
    )
    transcribed = result["text"].strip()

    # Clean both texts for comparison
    import re
    def clean(text: str) -> str:
        text = re.sub(r"\[.*?\]", "", text)  # Remove [verse] tags
        text = re.sub(r"\s+", " ", text).strip()
        return text.lower()

    clean_intended = clean(intended)
    clean_transcribed = clean(transcribed)

    # Calculate similarity
    ratio = SequenceMatcher(None, clean_intended, clean_transcribed).ratio()

    # Line-by-line comparison
    intended_lines = [l.strip() for l in intended.splitlines() if l.strip() and not l.strip().startswith("[")]
    trans_lines = [s["text"].strip() for s in result.get("segments", []) if s["text"].strip()]

    print(f"\n{'=' * 60}")
    print(f"  Lyrics Check: {mp3_path.name}")
    print(f"  Source: {md_path.name}")
    print(f"  Overall similarity: {ratio:.0%}")
    print(f"  Intended lines: {len(intended_lines)}")
    print(f"  Transcribed segments: {len(trans_lines)}")
    print(f"{'=' * 60}")

    print(f"\n  INTENDED:")
    for line in intended_lines:
        print(f"    {line}")

    print(f"\n  TRANSCRIBED:")
    for line in trans_lines:
        print(f"    {line}")

    print(f"\n  SIMILARITY: {ratio:.0%}")
    if ratio >= 0.8:
        print("  VERDICT: Good")
    elif ratio >= 0.5:
        print("  VERDICT: Needs improvement — consider regenerating")
    else:
        print("  VERDICT: Poor — lyrics mostly not understood")


def cmd_sync(args: argparse.Namespace) -> None:
    """Run the lyrics sync pipeline on an output folder."""
    _run_sync(args.path, force=args.force, html_only=args.html_only)


def _run_sync(path: str, force: bool = False, html_only: bool = False) -> None:
    """Call sync_lyrics.py logic programmatically."""
    # Import sync_lyrics from scripts/ (add to path if needed)
    import importlib.util

    sync_path = Path("scripts/sync_lyrics.py").resolve()
    if not sync_path.exists():
        print(f"  ERROR: {sync_path} not found")
        sys.exit(1)

    spec = importlib.util.spec_from_file_location("sync_lyrics", sync_path)
    sync_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sync_mod)

    # Simulate CLI args
    sys.argv = ["sync_lyrics", path]
    if force:
        sys.argv.append("--force")
    if html_only:
        sys.argv.append("--html-only")
    sync_mod.main()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="songmaker",
        description="Generate songs from markdown files and sync lyrics.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # generate
    gen = sub.add_parser("generate", help="Generate a song from a markdown file")
    gen.add_argument("path", help="Path to song .md file")
    gen.add_argument("--seed", type=int, default=None, help="Random seed (overrides frontmatter)")
    gen.add_argument("--sync", action="store_true", help="Run sync pipeline after generation")
    gen.add_argument("--check", action="store_true", help="Run Whisper lyrics check after generation")

    # player
    pl = sub.add_parser("player", help="Generate unified HTML player for all albums")
    pl.add_argument("-o", "--output", default="_output", help="Output directory (default: _output)")
    pl.add_argument("--root", default=None, help="Project root (default: auto-detect)")

    # check
    chk = sub.add_parser("check", help="Check lyrics accuracy (Whisper vs intended)")
    chk.add_argument("path", help="MP3 file to check")
    chk.add_argument("--source", default=None, help="Lyrics .md file (auto-detected if omitted)")

    # sync
    syn = sub.add_parser("sync", help="Sync lyrics: transcribe, LRC, HTML, ID3")
    syn.add_argument("path", help="Album output folder or single MP3")
    syn.add_argument("--force", action="store_true", help="Re-transcribe even if LRC exists")
    syn.add_argument("--html-only", action="store_true", help="Only regenerate HTML from existing LRC")

    args = parser.parse_args()
    if args.command == "generate":
        cmd_generate(args)
    elif args.command == "player":
        cmd_player(args)
    elif args.command == "check":
        cmd_check(args)
    elif args.command == "sync":
        cmd_sync(args)


if __name__ == "__main__":
    main()
