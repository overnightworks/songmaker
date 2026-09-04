#!/usr/bin/env python3
"""Benchmark scoring models on CPU vs GPU.

Runs Whisper (faster-whisper) and AudioBox Aesthetics on both devices,
reporting wall-clock time and transcription quality for each.

Usage:
    python scripts/benchmark_scoring_devices.py <path_to_mp3>
    python scripts/benchmark_scoring_devices.py <path_to_mp3> --rounds 3
"""

from __future__ import annotations

import argparse
import gc
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def benchmark_whisper(mp3_path: Path, device: str, rounds: int) -> tuple[float, float, str]:
    from faster_whisper import WhisperModel

    print(f"\n{'='*60}")
    print(f"WHISPER (large-v3) on {device.upper()}")
    print(f"{'='*60}")

    compute_type = "int8_float16" if device == "cuda" else "int8"
    print(f"Loading model (compute_type={compute_type})...")
    t0 = time.perf_counter()
    model = WhisperModel("large-v3", device=device, compute_type=compute_type)
    load_time = time.perf_counter() - t0
    print(f"Model load: {load_time:.1f}s")

    durations = []
    transcript = ""
    for i in range(rounds):
        t0 = time.perf_counter()
        segments_gen, info = model.transcribe(
            str(mp3_path),
            language=None,
            condition_on_previous_text=False,
            beam_size=5,
            temperature=0.0,
        )
        segments = [seg.text.strip() for seg in segments_gen if seg.text.strip()]
        elapsed = time.perf_counter() - t0
        durations.append(elapsed)
        transcript = "\n".join(segments)
        print(f"  Round {i+1}: {elapsed:.2f}s ({len(segments)} segments)")

    avg = sum(durations) / len(durations)
    print(f"\nAvg inference: {avg:.2f}s")
    print(f"Detected language: {getattr(info, 'language', 'unknown')}")
    print(f"Transcript preview: {transcript[:200]}...")

    del model
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass

    return avg, load_time, transcript


def benchmark_audiobox(
    mp3_path: Path, device: str, rounds: int,
) -> tuple[float, float, dict[str, float]]:
    print(f"\n{'='*60}")
    print(f"AUDIOBOX AESTHETICS on {device.upper()}")
    print(f"{'='*60}")

    if device == "cpu":
        saved = os.environ.get("CUDA_VISIBLE_DEVICES")
        os.environ["CUDA_VISIBLE_DEVICES"] = ""

    from audiobox_aesthetics.infer import AesPredictor

    print("Loading model...")
    t0 = time.perf_counter()
    predictor = AesPredictor(checkpoint_pth="default")
    load_time = time.perf_counter() - t0
    print(f"Model load: {load_time:.1f}s")

    if device == "cpu":
        if saved is None:
            os.environ.pop("CUDA_VISIBLE_DEVICES", None)
        else:
            os.environ["CUDA_VISIBLE_DEVICES"] = saved

    durations = []
    scores = {}
    for i in range(rounds):
        t0 = time.perf_counter()
        result = predictor.forward([{"path": str(mp3_path)}])
        elapsed = time.perf_counter() - t0
        durations.append(elapsed)
        scores = result[0]
        print(f"  Round {i+1}: {elapsed:.2f}s")

    avg = sum(durations) / len(durations)
    print(f"\nAvg inference: {avg:.2f}s")
    print(f"Scores: CE={scores['CE']:.1f} CU={scores['CU']:.1f} "
          f"PC={scores['PC']:.1f} PQ={scores['PQ']:.1f}")

    del predictor
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass

    return avg, load_time, scores


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark scoring on CPU vs GPU")
    parser.add_argument("mp3_path", type=Path, help="Path to an MP3 file to score")
    parser.add_argument("--rounds", type=int, default=3, help="Inference rounds per device")
    parser.add_argument("--whisper-only", action="store_true")
    parser.add_argument("--audiobox-only", action="store_true")
    args = parser.parse_args()

    if not args.mp3_path.exists():
        print(f"File not found: {args.mp3_path}")
        sys.exit(1)

    has_gpu = False
    try:
        import torch
        has_gpu = torch.cuda.is_available()
        if has_gpu:
            gpu_name = torch.cuda.get_device_name(0)
            vram_gb = torch.cuda.get_device_properties(0).total_memory / 1024**3
            print(f"GPU: {gpu_name} ({vram_gb:.1f} GB VRAM)")
    except ImportError:
        pass

    if not has_gpu:
        print("No GPU available — running CPU-only benchmark")

    print(f"Audio: {args.mp3_path}")
    print(f"Rounds: {args.rounds}")

    results = {}

    if not args.audiobox_only:
        # Whisper CPU
        cpu_avg, cpu_load, _ = benchmark_whisper(args.mp3_path, "cpu", args.rounds)
        results["whisper_cpu"] = {"avg": cpu_avg, "load": cpu_load}

        if has_gpu:
            gpu_avg, gpu_load, _ = benchmark_whisper(args.mp3_path, "cuda", args.rounds)
            results["whisper_gpu"] = {"avg": gpu_avg, "load": gpu_load}

    if not args.whisper_only:
        # AudioBox CPU
        cpu_avg, cpu_load, _ = benchmark_audiobox(args.mp3_path, "cpu", args.rounds)
        results["audiobox_cpu"] = {"avg": cpu_avg, "load": cpu_load}

        if has_gpu:
            gpu_avg, gpu_load, _ = benchmark_audiobox(args.mp3_path, "cuda", args.rounds)
            results["audiobox_gpu"] = {"avg": gpu_avg, "load": gpu_load}

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"{'Model':<25} {'Device':<8} {'Load (s)':<12} {'Inference (s)':<15}")
    print("-" * 60)
    for key, val in results.items():
        model, device = key.rsplit("_", 1)
        print(f"{model:<25} {device.upper():<8} {val['load']:<12.1f} {val['avg']:<15.2f}")

    if has_gpu and not args.audiobox_only and "whisper_gpu" in results:
        ratio = results["whisper_cpu"]["avg"] / results["whisper_gpu"]["avg"]
        print(f"\nWhisper GPU speedup: {ratio:.1f}x")

    if has_gpu and not args.whisper_only and "audiobox_gpu" in results:
        ratio = results["audiobox_cpu"]["avg"] / results["audiobox_gpu"]["avg"]
        print(f"AudioBox GPU speedup: {ratio:.1f}x")


if __name__ == "__main__":
    main()
