"""Diffusion-step progress text parser shared by the worker runner."""

def parse_step_fraction(progress_text: str) -> float | None:
    """Extract a 0..1 fraction from diffusion step text like '8/50 [00:02<00:13]'.

    Only matches the tqdm-style progress format with a bracket suffix to avoid
    false positives from non-progress text like 'LM chunk 1/1'.
    """
    steps = _diffusion_steps(progress_text)
    if steps is not None:
        current, total = steps
        if total > 0:
            return min(current / total, 1.0)
    return None


def _diffusion_steps(progress_text: str) -> tuple[int, int] | None:
    """Read the final numeric ``current/total`` pair before a progress bracket."""
    search_from = 0
    while (bracket_index := progress_text.find("[", search_from)) != -1:
        prefix = progress_text[:bracket_index].rstrip()
        slash_index = prefix.rfind("/")
        if slash_index != -1:
            total_text = prefix[slash_index + 1:]
            current_start = slash_index
            while current_start and prefix[current_start - 1].isdecimal():
                current_start -= 1
            current_text = prefix[current_start:slash_index]
            if current_text.isdecimal() and total_text.isdecimal():
                return int(current_text), int(total_text)
        search_from = bracket_index + 1
    return None
