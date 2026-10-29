"""Scoring jobs: a scoring run calls no provider."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from conftest import (
    override_provider_runtime,
)

from songmaker_cli.db.engine import init_test_db as init_db
from songmaker_cli.db.models import Album, Generation, Job, Song, User, Version
from songmaker_cli.db.queries.settings import set_claude_model
from songmaker_cli.jobs.scoring import run_scoring_job
from songmaker_cli.scoring.models import (
    EmotionalDynamicsScore,
    ScorerOutcome,
    ScorerRun,
    SongScores,
    TextAccuracyScore,
)
from songmaker_cli.whisper_cues import WhisperCue

# ── import boundary ─────────────────────────────────────────────────


def test_scoring_job_is_importable_without_the_mcp_package() -> None:
    """The scoring worker container never installs the ``mcp`` extra (it
    ships only ``server``, ``scoring``, ``whisper``). A fresh interpreter
    with ``mcp`` poisoned in ``sys.modules`` proves the whole chain that
    ``songmaker_cli.jobs.scoring`` pulls in stays importable without it.
    """
    script = (
        "import sys\n"
        "sys.modules['mcp'] = None\n"
        "import songmaker_cli.jobs.scoring\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr


# ── run_scoring_job wiring ───────────────────────────────────────────


def _seeded_generation(tmp_path: Path, lyrics: str | None = "Hello world") -> tuple:
    factory = init_db(tmp_path / "scoring.db")
    with factory() as session:
        session.add(User(id="u1", username="user1", role="user"))
        session.flush()
        session.add(Album(id="alb1", title="Rock", artist="Band", created_by="u1"))
        session.add(Song(id="s1", title="Song One", album_id="alb1", track_number=1))
        session.add(Version(
            id="v1", song_id="s1", version_number=1,
            lyrics=lyrics, prompt="rock style", bpm=120,
        ))
        session.add(Generation(
            id="g1", song_id="s1", version_id="v1", generation_number=1,
            mp3_path="user1/g1.mp3", seed=42,
        ))
        session.add(Job(id="j-score", type="score", status="queued"))
        session.commit()

    audio_dir = tmp_path / "audio"
    mp3 = audio_dir / "user1" / "g1.mp3"
    mp3.parent.mkdir(parents=True, exist_ok=True)
    mp3.write_bytes(b"fake-mp3")
    return factory, audio_dir


def _scoring_result_with_transcript(*, silent: bool = False) -> SongScores:
    return SongScores(
        emotional_dynamics=EmotionalDynamicsScore(
            pitch_cv=0.3, rms_contrast=2.0, onset_rate_cv=0.2,
            overall_expressiveness=0.55,
        ),
        text_accuracy=TextAccuracyScore(
            similarity_ratio=0.9,
            intended_line_texts=("hello", "world"),
            transcribed_line_texts=() if silent else ("hello", "world"),
            whisper_cues=() if silent else (
                WhisperCue(start=0.0, end=0.8, text="hello world"),
            ),
        ),
        runs=(
            ScorerRun(scorer="emotional_dynamics", outcome=ScorerOutcome.OK),
            ScorerRun(scorer="text_accuracy", outcome=ScorerOutcome.OK),
        ),
    )


def test_scoring_run_calls_no_provider_and_writes_no_verdict_key(tmp_path: Path) -> None:
    """Whatever judge rows are left stored, a scoring run completes without
    reaching a provider and leaves a stored verdict pair exactly as it is
    (#1976, the operator's ruling of 28.10.2026)."""
    from songmaker_cli.db.models import Score

    factory, audio_dir = _seeded_generation(tmp_path)
    stored_pair = {"lyrical_coherence": 8, "lyrical_summary": "stored verdict"}
    with factory() as session:
        for key, value in (
            ("judge_provider", "grok"), ("judge_route", "api"), ("judge_model", "grok-4.6"),
        ):
            set_claude_model(session, key, value)
        session.add(Score(generation_id="g1", scorer="batch", value=dict(stored_pair)))
        session.commit()
    override_provider_runtime(anthropic_api_key=None, xai_api_key=None)

    with (
        patch(
            "songmaker_cli.jobs.get_scorer_process",
            return_value=MagicMock(score=MagicMock(
                return_value=_scoring_result_with_transcript(),
            )),
        ),
        patch(
            "agent_providers.dispatch.call_openai_compatible_once",
            side_effect=AssertionError("a scoring run reached a provider"),
        ),
        patch(
            "agent_providers.claude.adapter.call_claude",
            side_effect=AssertionError("a scoring run reached a provider"),
        ),
    ):
        run_scoring_job("j-score", "g1", None, db_factory=factory, audio_dir=audio_dir)

    with factory() as session:
        job = session.query(Job).filter_by(id="j-score").one()
        stored = session.query(Score).filter_by(generation_id="g1").one()
        assert job.status == "completed"
        assert job.error_type is None
        assert {key: stored.value[key] for key in stored_pair} == stored_pair
        assert "text_accuracy" in stored.value


def test_scoring_run_asks_the_child_for_exactly_the_requested_scorers(
    tmp_path: Path,
) -> None:
    factory, audio_dir = _seeded_generation(tmp_path)
    scorer = MagicMock(score=MagicMock(return_value=_scoring_result_with_transcript()))

    with patch("songmaker_cli.jobs.get_scorer_process", return_value=scorer):
        run_scoring_job(
            "j-score", "g1", ["silence"], db_factory=factory, audio_dir=audio_dir,
        )

    assert scorer.score.call_args.kwargs["scorers"] == ["silence"]


@pytest.mark.parametrize(
    ("lyrics", "silent"),
    [("Hello world", False), ("Hello world", True), (None, False)],
    ids=["lyrics-and-transcript", "lyrics-empty-transcript", "no-lyrics"],
)
def test_scoring_run_for_a_take_without_a_score_row_writes_no_verdict_key(
    tmp_path: Path, lyrics: str | None, silent: bool,
) -> None:
    from songmaker_cli.db.models import Score

    factory, audio_dir = _seeded_generation(tmp_path, lyrics)
    with patch(
        "songmaker_cli.jobs.get_scorer_process",
        return_value=MagicMock(score=MagicMock(
            return_value=_scoring_result_with_transcript(silent=silent),
        )),
    ):
        run_scoring_job("j-score", "g1", None, db_factory=factory, audio_dir=audio_dir)

    with factory() as session:
        assert session.query(Job).filter_by(id="j-score").one().status == "completed"
        stored = session.query(Score).filter_by(generation_id="g1").one()
        assert "lyrical_coherence" not in stored.value
        assert "lyrical_summary" not in stored.value


def test_child_scorer_timeout_leaves_the_job_completed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A child scorer timing out remains isolated: the job still completes."""
    factory, audio_dir = _seeded_generation(tmp_path)
    child_timeout = SongScores(runs=(ScorerRun(
        scorer="silence",
        outcome=ScorerOutcome.TIMED_OUT,
        detail="scorer_timeout",
    ),))
    scorer = MagicMock(score=MagicMock(return_value=child_timeout))

    with patch("songmaker_cli.jobs.get_scorer_process", return_value=scorer):
        run_scoring_job(
            "j-score", "g1", ["silence"], db_factory=factory, audio_dir=audio_dir,
        )

    with factory() as session:
        job = session.query(Job).filter_by(id="j-score").one()
        assert job.status == "completed"
