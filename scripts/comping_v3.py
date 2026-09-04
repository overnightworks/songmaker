"""Experimental: comp multiple AI generations into one track using stem-aware splicing.

NOT a production feature — one-off experiment. Delete after we decide whether
comping is worth building as a real feature.

Pipeline:
  1. For each unique source WAV: detect BPM (librosa), separate stems (Demucs)
  2. Pick a target BPM (CLI arg or median of detected)
  3. For each segment: slice each stem, time-stretch to target BPM
  4. Per stem type: equal-power crossfade concat with stem-tuned crossfade lengths
     (drums: short, vocals: long, bass/other: medium)
  5. Optional onset snap on drum boundaries (within +/- 100ms)
  6. Remix the 4 stems to one stereo file
  7. LUFS normalize via ffmpeg

Usage:
  python scripts/comping_v3.py \\
      --segment GEN13.wav 0:00 0:47 \\
      --segment GEN5.wav  0:39 1:24 \\
      --segment GEN12.wav 0:50 1:22 \\
      --segment GEN13.wav 1:21 1:46 \\
      --segment GEN12.wav 1:40 3:00 \\
      --output /tmp/this_summer_comp_v3.wav

Optional:
  --target-bpm INT       Master BPM (default: median of detected)
  --no-snap              Disable drum onset snapping
  --xfade-drums MS       Drum crossfade ms (default 30)
  --xfade-vocals MS      Vocal crossfade ms (default 600)
  --xfade-other MS       Bass/other crossfade ms (default 200)
  --keep-stems DIR       Keep separated stems in this dir (cache for re-runs)

Dependencies (install in a temp venv, NOT into the main project):
  pip install demucs pyrubberband soundfile librosa numpy
  apt: ffmpeg, rubberband-cli
"""

from __future__ import annotations

import argparse
import logging
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import librosa
import numpy as np
import pyrubberband
import soundfile as sf

log = logging.getLogger("comping_v3")

STEM_NAMES = ("drums", "bass", "vocals", "other")

DEFAULT_XFADE_MS = {
    "drums": 30,
    "bass": 200,
    "vocals": 600,
    "other": 200,
}

DRUM_SNAP_WINDOW_SEC = 0.1
LUFS_TARGET = -14.0
LUFS_TRUE_PEAK = -1.5
LUFS_RANGE = 11.0
DEMUCS_MODEL = "htdemucs"


@dataclass(frozen=True)
class Segment:
    source: Path
    start_sec: float
    end_sec: float

    @property
    def duration(self) -> float:
        return self.end_sec - self.start_sec


def parse_timecode(tc: str) -> float:
    """Accept '0:47', '47', '1:23.5', or '83.5'."""
    if ":" in tc:
        parts = tc.split(":")
        if len(parts) != 2:
            raise ValueError(f"bad timecode: {tc}")
        return int(parts[0]) * 60 + float(parts[1])
    return float(tc)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--segment", action="append", nargs=3, metavar=("WAV", "START", "END"),
        required=True, help="repeatable; START and END are M:SS or seconds",
    )
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--target-bpm", type=int, default=0, help="0 = median of detected")
    p.add_argument("--no-snap", action="store_true")
    p.add_argument("--xfade-drums", type=int, default=DEFAULT_XFADE_MS["drums"])
    p.add_argument("--xfade-vocals", type=int, default=DEFAULT_XFADE_MS["vocals"])
    p.add_argument("--xfade-other", type=int, default=DEFAULT_XFADE_MS["other"])
    p.add_argument("--keep-stems", type=Path, default=None, help="cache stems here")
    p.add_argument("--verbose", action="store_true")
    return p.parse_args()


def detect_bpm(audio: np.ndarray, sr: int) -> float:
    tempo = librosa.feature.tempo(y=audio.mean(axis=0) if audio.ndim > 1 else audio, sr=sr)
    return float(tempo[0])


def run_demucs(src: Path, out_dir: Path) -> dict[str, Path]:
    """Run demucs CLI; returns {stem_name: wav_path}. Caches by source name."""
    name = src.stem
    cached = out_dir / DEMUCS_MODEL / name
    if cached.is_dir() and all((cached / f"{s}.wav").exists() for s in STEM_NAMES):
        log.info("demucs cache hit for %s", name)
        return {s: cached / f"{s}.wav" for s in STEM_NAMES}

    out_dir.mkdir(parents=True, exist_ok=True)
    log.info("running demucs on %s", src.name)
    cmd = [
        sys.executable, "-m", "demucs.separate",
        "-n", DEMUCS_MODEL,
        "-o", str(out_dir),
        "--filename", "{stem}.{ext}",
        str(src),
    ]
    subprocess.run(cmd, check=True)  # NOSONAR: fixed executable and shell-free CLI paths
    return {s: cached / f"{s}.wav" for s in STEM_NAMES}


def load_wav(path: Path) -> tuple[np.ndarray, int]:
    audio, sr = sf.read(str(path), always_2d=True)
    return audio.T, sr  # (channels, samples)


def slice_audio(audio: np.ndarray, sr: int, start: float, end: float) -> np.ndarray:
    s = max(0, int(round(start * sr)))
    e = min(audio.shape[1], int(round(end * sr)))
    return audio[:, s:e]


def time_stretch(audio: np.ndarray, sr: int, ratio: float) -> np.ndarray:
    if abs(ratio - 1.0) < 0.005:
        return audio
    out_channels = []
    for ch in audio:
        out_channels.append(pyrubberband.time_stretch(ch, sr, ratio))
    min_len = min(len(c) for c in out_channels)
    return np.stack([c[:min_len] for c in out_channels])


def equal_power_crossfade(a: np.ndarray, b: np.ndarray, sr: int, xfade_ms: int) -> np.ndarray:
    """Equal-power (qsin) crossfade. a's tail and b's head overlap by xfade_ms."""
    if a.size == 0:
        return b
    if b.size == 0:
        return a
    n = int(round(sr * xfade_ms / 1000))
    n = min(n, a.shape[1], b.shape[1])
    if n <= 0:
        return np.concatenate([a, b], axis=1)

    t = np.linspace(0, np.pi / 2, n, dtype=np.float32)
    fade_out = np.cos(t).astype(np.float32)
    fade_in = np.sin(t).astype(np.float32)

    a_tail = a[:, -n:] * fade_out
    b_head = b[:, :n] * fade_in
    overlap = a_tail + b_head
    return np.concatenate([a[:, :-n], overlap, b[:, n:]], axis=1)


def snap_to_drum_onset(slice_audio_arr: np.ndarray, sr: int, side: str) -> np.ndarray:
    """Trim slice edges to nearest drum onset within +/- DRUM_SNAP_WINDOW_SEC."""
    window = int(sr * DRUM_SNAP_WINDOW_SEC)
    if slice_audio_arr.shape[1] < 2 * window:
        return slice_audio_arr
    mono = slice_audio_arr.mean(axis=0)

    if side == "start":
        head = mono[: 2 * window]
        onsets = librosa.onset.onset_detect(y=head, sr=sr, units="samples", backtrack=False)
        if len(onsets) == 0:
            return slice_audio_arr
        snap = int(onsets[0])
        return slice_audio_arr[:, snap:]
    if side == "end":
        tail = mono[-2 * window :]
        onsets = librosa.onset.onset_detect(y=tail, sr=sr, units="samples", backtrack=False)
        if len(onsets) == 0:
            return slice_audio_arr
        last = int(onsets[-1])
        trim = (2 * window) - last
        return slice_audio_arr[:, : -trim] if trim > 0 else slice_audio_arr
    return slice_audio_arr


def stitch_stem(
    slices: Sequence[np.ndarray], sr: int, xfade_ms: int,
    stem_name: str, snap_drums: bool,
) -> np.ndarray:
    if not slices:
        return np.zeros((2, 0), dtype=np.float32)
    out = slices[0]
    if snap_drums and stem_name == "drums" and out.shape[1] > 0:
        out = snap_to_drum_onset(out, sr, "end")
    for nxt in slices[1:]:
        next_slice = nxt
        if snap_drums and stem_name == "drums":
            next_slice = snap_to_drum_onset(next_slice, sr, "start")
            out = snap_to_drum_onset(out, sr, "end")
        out = equal_power_crossfade(out, next_slice, sr, xfade_ms)
    return out


def remix_stems(stems: dict[str, np.ndarray]) -> np.ndarray:
    target_len = max(s.shape[1] for s in stems.values())
    mix = np.zeros((2, target_len), dtype=np.float32)
    for s in stems.values():
        n = s.shape[1]
        if s.shape[0] == 1:
            mix[:, :n] += np.repeat(s, 2, axis=0)[:, :n]
        else:
            mix[:, :n] += s[:2, :n]
    return mix


def loudnorm_via_ffmpeg(in_path: Path, out_path: Path) -> None:
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "warning",
        "-i", str(in_path),
        "-af", f"loudnorm=I={LUFS_TARGET}:TP={LUFS_TRUE_PEAK}:LRA={LUFS_RANGE}",
        "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le",
        str(out_path),
    ]
    subprocess.run(cmd, check=True)  # NOSONAR: fixed executable and shell-free CLI paths


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    segments = [
        Segment(Path(w), parse_timecode(s), parse_timecode(e))
        for (w, s, e) in args.segment
    ]
    log.info("segments: %d", len(segments))
    for i, seg in enumerate(segments):
        log.info(
            "  [%d] %s %.2f-%.2f (%.2fs)",
            i, seg.source.name, seg.start_sec, seg.end_sec, seg.duration,
        )

    unique_sources = {seg.source for seg in segments}
    log.info("unique sources: %d", len(unique_sources))

    stem_cache_dir = args.keep_stems or Path(tempfile.mkdtemp(prefix="comp_stems_"))
    log.info("stem cache: %s", stem_cache_dir)

    detected_bpms: dict[Path, float] = {}
    stem_paths: dict[Path, dict[str, Path]] = {}
    for src in unique_sources:
        audio, sr = load_wav(src)
        bpm = detect_bpm(audio, sr)
        detected_bpms[src] = bpm
        log.info("BPM detected: %s -> %.2f", src.name, bpm)
        stem_paths[src] = run_demucs(src, stem_cache_dir)

    target_bpm = (
        float(args.target_bpm) if args.target_bpm > 0
        else float(np.median(list(detected_bpms.values())))
    )
    log.info("target BPM: %.2f", target_bpm)

    stem_audio: dict[Path, dict[str, tuple[np.ndarray, int]]] = {}
    for src in unique_sources:
        stem_audio[src] = {}
        for stem_name, p in stem_paths[src].items():
            stem_audio[src][stem_name] = load_wav(p)

    xfade_ms = {
        "drums": args.xfade_drums,
        "bass": args.xfade_other,
        "vocals": args.xfade_vocals,
        "other": args.xfade_other,
    }

    final_stems: dict[str, np.ndarray] = {}
    sr_out = next(iter(stem_audio.values()))["drums"][1]

    for stem_name in STEM_NAMES:
        slices: list[np.ndarray] = []
        for seg in segments:
            audio, sr = stem_audio[seg.source][stem_name]
            assert sr == sr_out, f"sr mismatch for {seg.source}: {sr} vs {sr_out}"
            sliced = slice_audio(audio, sr, seg.start_sec, seg.end_sec)
            ratio = detected_bpms[seg.source] / target_bpm
            stretched = time_stretch(sliced, sr, ratio)
            slices.append(stretched.astype(np.float32))
        log.info(
            "stitching %s stem (%d slices, xfade %dms)",
            stem_name, len(slices), xfade_ms[stem_name],
        )
        final_stems[stem_name] = stitch_stem(
            slices, sr_out, xfade_ms[stem_name], stem_name, snap_drums=not args.no_snap,
        )

    log.info("remixing stems")
    mix = remix_stems(final_stems)

    peak = float(np.abs(mix).max())
    if peak > 1.0:
        mix = mix / peak * 0.99

    raw_path = args.output.with_suffix(".raw.wav")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(raw_path), mix.T, sr_out, subtype="PCM_16")
    log.info("wrote raw mix: %s (%.2fs)", raw_path, mix.shape[1] / sr_out)

    log.info("loudnorm to %.1f LUFS via ffmpeg", LUFS_TARGET)
    loudnorm_via_ffmpeg(raw_path, args.output)
    raw_path.unlink()
    log.info("done: %s", args.output)

    if args.keep_stems is None:
        shutil.rmtree(stem_cache_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
