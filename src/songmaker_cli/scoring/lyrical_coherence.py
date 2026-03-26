"""Lyrical coherence scorer — uses Claude to judge sung lyrics.

Sends intended lyrics + Whisper transcription to Claude and asks:
does the sung result make sense as a song? Creative deviations from
intended lyrics are fine as long as the output is coherent.
"""

from __future__ import annotations

import logging
from pathlib import Path

from songmaker_cli.claude.provider import call_claude, parse_json_response
from songmaker_cli.parser import SongMeta
from songmaker_cli.scoring.models import LyricalCoherenceScore
from songmaker_cli.scoring.pipeline import AudioData, PipelineConfig, register

log = logging.getLogger(__name__)

JUDGE_PROMPT = (  # noqa: E501
    "You are a vocal quality judge for AI-generated songs.\n\n"
    "You receive the INTENDED lyrics (what the AI was asked to sing) and a "
    "WHISPER TRANSCRIPTION (automatic speech recognition of what was produced). "
    "Your job is to judge the quality of the sung result AS A SONG.\n\n"
    "KEY PRINCIPLE: The intended lyrics are CONTEXT, not ground truth. "
    "If the AI sang something different from the intended lyrics but the result "
    "is coherent, meaningful, and works as a song — that is perfectly fine. "
    "A creative deviation that produces good lyrics is NOT a problem.\n\n"
    "IMPORTANT: Whisper (the transcription tool) has known inaccuracies:\n"
    '- Proper nouns are often misheard (e.g. "Ukraine" -> "your crate")\n'
    '- Minor word substitutions happen (e.g. "a morning" -> "in mourning")\n'
    "- Punctuation and line boundaries differ from the original\n"
    "- These are TRANSCRIPTION errors, not singing errors. Do NOT penalize.\n\n"
    "What makes a GOOD vocal result (high score):\n"
    "- The sung lyrics make sense and are coherent as a song\n"
    "- The song has clear structure (verses, chorus, etc.)\n"
    "- The words form meaningful sentences and tell a story or convey emotion\n"
    "- Even if different from intended, the result works on its own\n\n"
    "What you SHOULD penalize (real vocal failures):\n"
    "- Extended gibberish or nonsensical word sequences\n"
    "- Repetitive loops where the AI gets stuck repeating a phrase\n"
    "- Sections where the words form no coherent meaning\n"
    "- The song structure falling apart completely\n"
    "- Unintelligible or meaningless output\n\n"
    "<intended_lyrics>\n{intended}\n</intended_lyrics>\n\n"
    "<whisper_transcription>\n{transcribed}\n</whisper_transcription>\n\n"
    "Judge the transcription as a song. Ask: does this work as lyrics? "
    "Is the output coherent and meaningful? Differences from the intended "
    "lyrics are only a problem if the result is nonsensical.\n\n"
    "Respond with ONLY valid JSON (no markdown, no explanation):\n"
    '{{\"score\": <1-10>, \"issues\": [\"issue 1\", \"issue 2\"], '
    '\"summary\": \"one sentence\"}}\n\n'
    "Score guide:\n"
    "- 10: Coherent, meaningful lyrics throughout, clear song structure\n"
    "- 8-9: Mostly coherent, minor garbled or meaningless passages\n"
    "- 6-7: Generally makes sense but one section is incoherent or broken\n"
    "- 4-5: Multiple sections are nonsensical or meaningless\n"
    "- 1-3: Mostly unintelligible, gibberish, or no coherent meaning"
)


@register("lyrical_coherence", needs_audio=False, after_gpu=True)
def score_lyrical_coherence(
    mp3_path: Path, meta: SongMeta | None = None, audio_data: AudioData | None = None,
    config: PipelineConfig | None = None, shared_data: dict | None = None,
) -> LyricalCoherenceScore:
    """Judge lyrical coherence using Claude (CLI or API).

    Requires text_accuracy to run first — reads transcription from shared_data.
    """
    if meta is None or not meta.lyrics:
        raise ValueError("No lyrics metadata — cannot judge lyrical coherence")

    transcribed = (shared_data or {}).get("whisper_text", "")
    if not transcribed:
        raise ValueError("No Whisper transcription in pipeline. Run text_accuracy first.")
    intended = "\n".join(
        line.strip() for line in meta.lyrics.splitlines()
        if line.strip() and not line.strip().startswith("[")
    )

    prompt = JUDGE_PROMPT.format(intended=intended, transcribed=transcribed)
    n_intended = len(intended.splitlines())
    n_transcribed = len(transcribed.splitlines())
    log.debug("Sending %d intended + %d transcribed lines to Claude", n_intended, n_transcribed)
    response = call_claude(prompt)
    log.debug("Claude response: %d chars", len(response.text))
    data = parse_json_response(response.text)

    result = LyricalCoherenceScore(
        score=int(data.get("score", 0)),
        issues=tuple(data.get("issues", [])),
        summary=data.get("summary", ""),
    )
    log.info("Lyrical coherence: %d/10 — %s", result.score, result.summary)
    return result
