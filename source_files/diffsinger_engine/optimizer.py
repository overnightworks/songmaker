"""Self-optimizing vocal generation with pronunciation retry loop.

Generates each phrase up to N times, keeping the version with the
highest Whisper word accuracy. DiffSinger's internal diffusion noise
varies between runs, so repeated generation produces different results.

Usage:
    from diffsinger_engine.optimizer import generate_optimized

    results = generate_optimized(
        engine=engine,
        phrases=VOCAL_PHRASES,  # list of (VocalPhrase, start_beat)
        target_accuracy=0.85,
        max_retries=10,
    )
"""

from __future__ import annotations

import logging

import numpy as np

from .engine import DiffSingerEngine
from .models import VocalPhrase
from .validation import check_pronunciation

logger = logging.getLogger(__name__)


def generate_optimized(
    engine: DiffSingerEngine,
    phrases: list[tuple[VocalPhrase, float]],
    target_accuracy: float = 0.85,
    max_retries: int = 10,
) -> dict[str, np.ndarray]:
    """Generate all phrases, retrying low-scoring ones for better pronunciation.

    For each phrase:
    1. Generate audio with DiffSinger
    2. Check pronunciation with Whisper (word accuracy via WER)
    3. If below target, retry up to max_retries times, keeping the best
    4. Report improvement for each retried phrase

    Args:
        engine: Initialized DiffSingerEngine.
        phrases: List of (VocalPhrase, start_beat) tuples.
        target_accuracy: Word accuracy target per phrase (0.0-1.0).
            0.85 = 85% of words correctly recognized.
        max_retries: Max generation attempts per phrase.

    Returns:
        Dict mapping phrase_id -> best audio samples (np.ndarray).
    """
    results: dict[str, np.ndarray] = {}
    retry_stats: list[dict] = []

    total = len(phrases)
    for idx, (phrase, _beat) in enumerate(phrases):
        pid = phrase.phrase_id
        print(f"\n  [{idx+1}/{total}] Generating: {pid}")

        # First attempt
        result = engine.generate(phrase)
        best_samples = result.samples
        best_score = _quick_score(phrase, best_samples)
        attempt = 1

        if best_score is not None:
            print(f"    Attempt 1: word accuracy {best_score:.0%} | duration {result.duration:.2f}s")

        # Retry if below target
        if best_score is not None and best_score < target_accuracy:
            for retry in range(2, max_retries + 1):
                print(f"    Attempt {retry}/{max_retries}...", end="", flush=True)
                result = engine.generate(phrase)
                score = _quick_score(phrase, result.samples)

                if score is not None:
                    print(f" word accuracy {score:.0%}", end="")
                    if score > best_score:
                        improvement = score - best_score
                        print(f" (+{improvement:.0%} improvement)")
                        best_samples = result.samples
                        best_score = score
                    else:
                        print(f" (no improvement, keeping {best_score:.0%})")
                else:
                    print(" (no score)")

                if best_score >= target_accuracy:
                    print(f"    Target {target_accuracy:.0%} reached!")
                    break
                attempt = retry

            retry_stats.append({
                "phrase_id": pid,
                "attempts": attempt,
                "final_score": best_score,
                "reached_target": best_score >= target_accuracy,
            })
        elif best_score is None:
            print(f"    Duration: {result.duration:.2f}s (no lyrics to score)")

        results[pid] = best_samples

    # Print retry summary
    if retry_stats:
        print("\n=== Optimization Summary ===\n")
        reached = sum(1 for s in retry_stats if s["reached_target"])
        print(f"  Retried {len(retry_stats)} phrases, {reached} reached target {target_accuracy:.0%}")
        for s in retry_stats:
            status = "OK" if s["reached_target"] else "BELOW TARGET"
            print(f"  {s['phrase_id']}: {s['final_score']:.0%} after {s['attempts']} attempts [{status}]")

    return results


def _quick_score(phrase: VocalPhrase, samples: np.ndarray) -> float | None:
    """Run Whisper pronunciation check and return word accuracy score.

    Returns None if phrase has no lyrics (rests only).
    """
    pron = check_pronunciation(phrase, samples)
    return pron.similarity
