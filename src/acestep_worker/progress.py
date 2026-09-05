"""Diffusion-step progress text parser shared by the worker runner."""

from __future__ import annotations

import re

_DIFFUSION_STEP_PATTERN = re.compile(r"(\d+)/(\d+)\s*\[")


def parse_step_fraction(progress_text: str) -> float | None:
    """Extract a 0..1 fraction from diffusion step text like '8/50 [00:02<00:13]'.

    Only matches the tqdm-style progress format with a bracket suffix to avoid
    false positives from non-progress text like 'LM chunk 1/1'.
    """
    m = _DIFFUSION_STEP_PATTERN.search(progress_text)
    if m:
        current, total = int(m.group(1)), int(m.group(2))
        if total > 0:
            return min(current / total, 1.0)
    return None
