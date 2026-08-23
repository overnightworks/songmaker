"""Scoring persistence — a scorer only overwrites what it actually produced."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from songmaker_cli.db.engine import init_test_db
from songmaker_cli.db.models import Album, Generation, Job, Score, Song, User, Version
from songmaker_cli.db.queries import save_scores
from songmaker_cli.jobs import run_scoring_job
from songmaker_cli.scoring.models import (
    ScorerOutcome,
    ScorerRun,
    SilenceScore,
    SongScores,
    TextAccuracyScore,
)

JOB_ID = "job-score"
GENERATION_ID = "gen-1"

STORED_SCORES: dict[str, object] = {
    "text_accuracy": 88.0,
    "detected_language": "de",
    "silence_gaps": 3,
    "silence_longest": 4.0,
}

FRESH_SILENCE = SilenceScore(
    total_silence_seconds=0.0, longest_gap_seconds=0.0, gap_count=0,
)


def _text_accuracy(detected_language: str | None = None) -> TextAccuracyScore:
    return TextAccuracyScore(
        similarity_ratio=0.5,
        intended_line_texts=("hello",),
        transcribed_line_texts=("hello",),
        detected_language=detected_language,
    )


def _run(scorer: str, outcome: ScorerOutcome) -> ScorerRun:
    return ScorerRun(scorer=scorer, outcome=outcome, detail="")


@pytest.fixture()
def scored_generation(tmp_path: Path):
    """A generation that already carries a full set of stored scores."""
    factory = init_test_db(tmp_path / "test.db")
    with factory() as session:
        session.add(User(id="u1", username="user1", password_hash="h", role="user"))
        session.flush()
        session.add(Album(id="a1", title="Album", artist="Band", created_by="u1"))
        session.add(Song(id="s1", title="Song", album_id="a1", track_number=1))
        session.add(Version(
            id="v1", song_id="s1", version_number=1,
            lyrics="Hello world", prompt="rock", bpm=120,
        ))
        session.add(Generation(
            id=GENERATION_ID, song_id="s1", version_id="v1", generation_number=1,
            mp3_path="user1/gen-1.mp3", seed=1,
        ))
        session.add(Score(
            generation_id=GENERATION_ID, scorer="batch", value=dict(STORED_SCORES),
        ))
        session.add(Job(id=JOB_ID, type="score", status="queued", user_id="u1"))
        session.commit()

    mp3 = tmp_path / "audio" / "user1" / "gen-1.mp3"
    mp3.parent.mkdir(parents=True)
    mp3.write_bytes(b"fake-mp3")
    return factory


def _score(db_factory, result: SongScores, audio_dir: Path) -> dict[str, object]:
    with patch(
        "songmaker_cli.jobs.get_scorer_process",
        return_value=MagicMock(score=MagicMock(return_value=result)),
    ):
        run_scoring_job(
            JOB_ID, GENERATION_ID, None, db_factory=db_factory, audio_dir=audio_dir,
        )

    with db_factory() as session:
        stored = (
            session.query(Score)
            .filter_by(generation_id=GENERATION_ID, scorer="batch")
            .one()
        )
        return dict(stored.value)


@pytest.mark.parametrize(
    "outcome",
    [ScorerOutcome.TIMED_OUT, ScorerOutcome.FAILED, ScorerOutcome.SKIPPED],
)
def test_scorer_without_a_value_keeps_the_stored_score(
    scored_generation, tmp_path: Path, outcome: ScorerOutcome,
) -> None:
    result = SongScores(
        silence=FRESH_SILENCE,
        runs=(
            _run("text_accuracy", outcome),
            _run("silence", ScorerOutcome.OK),
        ),
    )

    stored = _score(scored_generation, result, tmp_path / "audio")

    assert stored["text_accuracy"] == STORED_SCORES["text_accuracy"]
    assert stored["detected_language"] == STORED_SCORES["detected_language"]
    assert stored["silence_gaps"] == 0


def test_successful_scorer_overwrites_the_stored_score(
    scored_generation, tmp_path: Path,
) -> None:
    result = SongScores(
        text_accuracy=_text_accuracy(detected_language="en"),
        runs=(_run("text_accuracy", ScorerOutcome.OK),),
    )

    stored = _score(scored_generation, result, tmp_path / "audio")

    assert stored["text_accuracy"] == 50.0
    assert stored["detected_language"] == "en"
    assert stored["silence_gaps"] == STORED_SCORES["silence_gaps"]


def test_successful_scorer_drops_a_key_it_no_longer_emits(
    scored_generation, tmp_path: Path,
) -> None:
    """text_accuracy owns detected_language — a run without one clears it."""
    result = SongScores(
        text_accuracy=_text_accuracy(),
        runs=(_run("text_accuracy", ScorerOutcome.OK),),
    )

    stored = _score(scored_generation, result, tmp_path / "audio")

    assert "detected_language" not in stored


def test_run_where_every_scorer_failed_leaves_all_scores_intact(
    scored_generation, tmp_path: Path,
) -> None:
    result = SongScores(
        runs=(
            _run("text_accuracy", ScorerOutcome.TIMED_OUT),
            _run("lyrical_coherence", ScorerOutcome.SKIPPED),
        ),
    )

    stored = _score(scored_generation, result, tmp_path / "audio")

    assert stored == STORED_SCORES


def test_first_scoring_run_creates_the_score_row(tmp_path: Path) -> None:
    factory = init_test_db(tmp_path / "fresh.db")
    with factory() as session:
        session.add(Album(id="a1", title="Album", artist="Band"))
        session.add(Song(id="s1", title="Song", album_id="a1", track_number=1))
        session.add(Version(id="v1", song_id="s1", version_number=1, lyrics="x", prompt="y"))
        session.add(Generation(
            id=GENERATION_ID, song_id="s1", version_id="v1", generation_number=1,
            mp3_path="user1/gen-1.mp3",
        ))
        session.commit()

    with factory() as session:
        save_scores(
            session, GENERATION_ID, {"silence_gaps": 2},
            refreshed_keys={"silence_gaps", "silence_longest"},
        )
        session.commit()

    with factory() as session:
        stored = session.query(Score).filter_by(generation_id=GENERATION_ID).one()
        assert stored.value == {"silence_gaps": 2}


def test_scoring_job_logs_every_scorer_outcome(
    scored_generation, tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    result = SongScores(
        silence=FRESH_SILENCE,
        runs=(
            ScorerRun(
                scorer="text_accuracy", outcome=ScorerOutcome.TIMED_OUT,
                detail="Scorer 'text_accuracy' timed out after 300s",
            ),
            _run("silence", ScorerOutcome.OK),
        ),
    )

    with caplog.at_level(logging.INFO):
        _score(scored_generation, result, tmp_path / "audio")

    assert "text_accuracy=timed_out" in caplog.text
    assert "silence=ok" in caplog.text
