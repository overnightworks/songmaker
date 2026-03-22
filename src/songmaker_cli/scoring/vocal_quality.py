"""Vocal quality scorer — uses Claude API to judge transcription quality.

Sends intended lyrics + Whisper transcription to Claude and asks for
a 1-10 rating with specific issues found. This is the most accurate
scorer because the LLM understands context, intent, and language.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

from songmaker_cli.parser import SongMeta
from songmaker_cli.scoring.models import VocalQualityScore
from songmaker_cli.scoring.pipeline import AudioData, PipelineConfig, register

log = logging.getLogger(__name__)

JUDGE_PROMPT = """You are a music quality judge. Compare the intended lyrics to what was actually sung (Whisper transcription).

INTENDED LYRICS:
{intended}

WHISPER TRANSCRIPTION (what was actually sung):
{transcribed}

Rate the vocal performance on these criteria:
1. Are real words being sung? (not gibberish like "blkjdf shmaaa")
2. Do the sung sentences make sense in context?
3. How closely does it follow the intended lyrics?
4. Are there parts that sound broken, nonsensical, or like wrong words?

Note: Minor differences are OK (e.g. "streetlights" vs "street lights", "oh oh oh" intros/outros).
Whisper may merge or split lines differently — that's a transcription artifact, not a singing error.

Respond with ONLY valid JSON (no markdown, no explanation):
{{"score": <1-10>, "issues": ["issue 1", "issue 2"], "summary": "one sentence"}}

Score guide: 10=perfect, 8=minor issues, 5=significant problems, 3=mostly gibberish, 1=nothing recognizable"""


@register("vocal_quality", needs_audio=False)
def score_vocal_quality(
    mp3_path: Path, meta: SongMeta | None = None, audio_data: AudioData | None = None,
    config: PipelineConfig | None = None,
) -> VocalQualityScore:
    """Judge vocal quality using Claude API."""
    if meta is None or not meta.lyrics:
        raise ValueError("No lyrics metadata — cannot judge vocal quality")

    whisper_path = mp3_path.with_suffix(".whisper")
    if not whisper_path.exists():
        raise ValueError(f"No Whisper transcription found: {whisper_path.name}. Run text_accuracy first.")

    transcribed = whisper_path.read_text(encoding="utf-8").strip()
    intended = "\n".join(
        line.strip() for line in meta.lyrics.splitlines()
        if line.strip() and not line.strip().startswith("[")
    )

    prompt = JUDGE_PROMPT.format(intended=intended, transcribed=transcribed)
    result = _call_claude(prompt)

    log.info(
        "Vocal quality: %d/10 — %s",
        result.score, result.summary,
    )
    return result


def _find_claude_binary() -> str:
    """Find the Claude CLI binary."""
    import shutil
    from pathlib import Path

    found = shutil.which("claude")
    if found:
        return found

    ext_dir = Path.home() / ".vscode" / "extensions"
    if ext_dir.is_dir():
        for ext in sorted(ext_dir.glob("anthropic.claude-code-*"), reverse=True):
            candidate = ext / "resources" / "native-binary" / "claude"
            if candidate.is_file():
                return str(candidate)

    raise RuntimeError("Claude CLI not found. Install Claude Code or set PATH.")


def _call_claude(prompt: str) -> VocalQualityScore:
    """Call Claude CLI and parse the JSON response."""
    claude_bin = _find_claude_binary()
    try:
        proc = subprocess.run(
            [claude_bin, "-p", prompt, "--output-format", "json"],
            capture_output=True, text=True, timeout=60,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("Claude CLI timed out after 60s")

    if proc.returncode != 0:
        raise RuntimeError(f"Claude CLI error: {proc.stderr[:200]}")

    try:
        outer = json.loads(proc.stdout)
        response_text = outer.get("result", proc.stdout)
    except json.JSONDecodeError:
        response_text = proc.stdout

    # Extract JSON from response (might have markdown wrapping)
    json_str = response_text.strip()
    if "```" in json_str:
        json_str = json_str.split("```")[1]
        if json_str.startswith("json"):
            json_str = json_str[4:]
        json_str = json_str.strip()

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        raise RuntimeError(f"Claude returned invalid JSON: {json_str[:200]}")

    return VocalQualityScore(
        score=int(data.get("score", 0)),
        issues=tuple(data.get("issues", [])),
        summary=data.get("summary", ""),
    )
