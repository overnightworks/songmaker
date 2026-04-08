"""Experimental: blind A/B test of ACE-Step Extract vs Demucs stem separation.

NOT a production feature — one-off experiment. Delete after we decide which
separator is better for AI-generated audio.

Runs both ACE-Step Extract (requires acestep-v15-xl-base loaded on the
ACE-Step server) and HT Demucs on the same source WAV. Outputs vocal and
drum stems from each into a directory with anonymized filenames so you can
listen blind without knowing which is which. The mapping is written to a
hidden file you reveal AFTER picking.

Usage:
  python scripts/extract_ab_test.py \\
      --source /path/to/gen13.wav \\
      --output /tmp/ab \\
      --acestep-base-url http://localhost:8001

Pre-conditions:
  - ACE-Step server running with acestep-v15-xl-base loaded
    (set ACESTEP_CONFIG_PATH=acestep-v15-xl-base before starting the worker,
     or POST a model switch — out of scope for this script).
  - Demucs installed:  pip install demucs
  - ffmpeg in PATH

The script does NOT integrate with songmaker production code. It calls the
ACE-Step HTTP API directly via urllib so we don't need to extend
acestep_engine/client.py for an experiment.
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("extract_ab")

DEMUCS_MODEL = "htdemucs"
ACESTEP_POLL_INTERVAL = 2.0
ACESTEP_TIMEOUT = 600.0

EXTRACT_TRACKS = ("vocal", "drum")


@dataclass(frozen=True)
class ExtractResult:
    track: str
    wav_path: Path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", required=True, type=Path, help="source WAV (one of the generations)")
    p.add_argument("--output", required=True, type=Path, help="output dir for blind A/B")
    p.add_argument("--acestep-base-url", default="http://localhost:8001")
    p.add_argument("--skip-acestep", action="store_true", help="only run demucs (sanity check)")
    p.add_argument("--skip-demucs", action="store_true", help="only run ACE-Step Extract")
    p.add_argument("--verbose", action="store_true")
    return p.parse_args()


def run_demucs(src: Path, work_dir: Path) -> dict[str, Path]:
    """Run demucs CLI; returns {stem_name: wav_path}."""
    work_dir.mkdir(parents=True, exist_ok=True)
    log.info("demucs: separating %s", src.name)
    cmd = [
        sys.executable, "-m", "demucs.separate",
        "-n", DEMUCS_MODEL,
        "-o", str(work_dir),
        "--filename", "{stem}.{ext}",
        str(src),
    ]
    subprocess.run(cmd, check=True)
    out_dir = work_dir / DEMUCS_MODEL / src.stem
    return {
        "vocals": out_dir / "vocals.wav",
        "drums": out_dir / "drums.wav",
        "bass": out_dir / "bass.wav",
        "other": out_dir / "other.wav",
    }


def acestep_submit_extract(base_url: str, src_audio_path: str, track_name: str) -> str:
    """Submit an extract task to the ACE-Step server. Returns task_id."""
    payload = {
        "task_type": "extract",
        "src_audio_path": src_audio_path,
        "track_name": track_name,
        "audio_format": "wav",
        "use_random_seed": True,
        "thinking": False,
    }
    req = urllib.request.Request(
        f"{base_url}/release_task",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    task_id = body.get("task_id") or body.get("id")
    if not task_id:
        raise RuntimeError(f"no task_id in response: {body}")
    log.info("acestep extract submitted: track=%s task_id=%s", track_name, task_id)
    return task_id


def acestep_poll_task(base_url: str, task_id: str) -> dict:
    """Poll an ACE-Step task until done. Returns the final result dict."""
    deadline = time.monotonic() + ACESTEP_TIMEOUT
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{base_url}/get_task_result/{task_id}", timeout=15) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                time.sleep(ACESTEP_POLL_INTERVAL)
                continue
            raise
        status = body.get("status") or body.get("state")
        if status in ("completed", "success", "done"):
            return body
        if status in ("failed", "error"):
            raise RuntimeError(f"acestep task failed: {body}")
        time.sleep(ACESTEP_POLL_INTERVAL)
    raise TimeoutError(f"acestep task {task_id} timed out after {ACESTEP_TIMEOUT}s")


def acestep_extract(base_url: str, src: Path, work_dir: Path) -> dict[str, Path]:
    """Run ACE-Step Extract for vocal + drum tracks. Returns {track: wav_path}."""
    work_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, Path] = {}
    for track in EXTRACT_TRACKS:
        task_id = acestep_submit_extract(base_url, str(src), track)
        result = acestep_poll_task(base_url, task_id)
        out_path = result.get("audio_path") or result.get("output_path") or result.get("wav_path")
        if not out_path:
            raise RuntimeError(f"no output path in result: {result}")
        out_src = Path(out_path)
        out_dst = work_dir / f"{src.stem}_{track}.wav"
        if out_src.resolve() != out_dst.resolve():
            shutil.copy2(out_src, out_dst)
        results[track] = out_dst
        log.info("acestep extract done: track=%s -> %s", track, out_dst)
    return results


def ffmpeg_normalize(in_path: Path, out_path: Path) -> None:
    """LUFS-normalize so blind comparison isn't biased by loudness differences."""
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "warning",
        "-i", str(in_path),
        "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
        "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le",
        str(out_path),
    ]
    subprocess.run(cmd, check=True)


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if args.skip_acestep and args.skip_demucs:
        log.error("nothing to do (both --skip flags)")
        sys.exit(1)

    if not args.source.exists():
        log.error("source not found: %s", args.source)
        sys.exit(1)

    work_root = args.output / "_work"
    blind_dir = args.output / "blind"
    blind_dir.mkdir(parents=True, exist_ok=True)
    work_root.mkdir(parents=True, exist_ok=True)

    candidates: list[tuple[str, str, Path]] = []  # (separator, track, wav_path)

    if not args.skip_demucs:
        demucs_dir = work_root / "demucs"
        demucs_stems = run_demucs(args.source, demucs_dir)
        candidates.append(("demucs", "vocals", demucs_stems["vocals"]))
        candidates.append(("demucs", "drums", demucs_stems["drums"]))

    if not args.skip_acestep:
        ace_dir = work_root / "acestep"
        try:
            ace_stems = acestep_extract(args.acestep_base_url, args.source, ace_dir)
        except Exception as exc:
            log.error("acestep extract failed: %s", exc)
            log.error("if this is a 'wrong model loaded' error, set ACESTEP_CONFIG_PATH=acestep-v15-xl-base and restart the worker")
            sys.exit(2)
        candidates.append(("acestep", "vocals", ace_stems["vocal"]))
        candidates.append(("acestep", "drums", ace_stems["drum"]))

    if not candidates:
        log.error("no candidates produced")
        sys.exit(1)

    log.info("LUFS-normalizing all candidates for fair comparison")
    rng = random.Random(time.time_ns())
    blind_map: dict[str, dict] = {}
    for sep, track, src_wav in candidates:
        nonce = rng.randint(1000, 9999)
        blind_name = f"{track}_{nonce}.wav"
        blind_path = blind_dir / blind_name
        ffmpeg_normalize(src_wav, blind_path)
        blind_map[blind_name] = {"separator": sep, "track": track, "source": str(src_wav)}
        log.info("  %s  <-  %s/%s", blind_name, sep, track)

    answer_path = args.output / ".answer.json"
    answer_path.write_text(json.dumps(blind_map, indent=2))

    print("\n" + "=" * 60)
    print(f"BLIND A/B FILES: {blind_dir}")
    print("Listen to all the files in that directory.")
    print("Pick which you think sounds like the cleanest separation.")
    print(f"Then run:  cat {answer_path}")
    print("to see which separator produced which file.")
    print("=" * 60)


if __name__ == "__main__":
    main()
