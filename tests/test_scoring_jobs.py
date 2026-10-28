"""Scoring jobs and the judge settings layer.

A scoring run calls no provider; the judge settings stay stored until their
own removal (#1476 step 3).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from conftest import (
    make_authenticated_user,
    make_router_app,
    make_router_ctx,
    override_provider_runtime,
    refresh_provider_snapshots,
    web_client,
)

from songmaker_cli.constants import (
    CLAUDE_SCORING_MODEL_DEFAULT,
    JUDGE_DEFAULT_PROVIDER,
    SETTING_JUDGE_MODEL,
    SETTING_JUDGE_PROVIDER,
)
from songmaker_cli.db.engine import init_test_db as init_db
from songmaker_cli.db.models import Album, Generation, Job, Song, User, Version
from songmaker_cli.db.queries.settings import (
    get_judge_model,
    get_judge_provider,
    get_judge_route,
    pin_judge_route_if_unset,
    set_claude_model,
    set_judge_settings,
)
from songmaker_cli.jobs.scoring import run_scoring_job
from songmaker_cli.scoring.models import (
    EmotionalDynamicsScore,
    ScorerOutcome,
    ScorerRun,
    SongScores,
    TextAccuracyScore,
)
from songmaker_cli.whisper_cues import WhisperCue

LIVE_CATALOG = {
    "claude": ["claude-opus-4-6", "claude-sonnet-4-6"],
    "grok": ["grok-4.6", "grok-4.5"],
    "codex": ["gpt-5.4"],
}


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


# ── settings layer ───────────────────────────────────────────────────


def test_judge_defaults_to_claude_and_todays_scoring_model(tmp_path: Path) -> None:
    """Defaults stay exactly what they were before #315: nothing tips over
    for a musician who never touches the new judge settings."""
    factory = init_db(tmp_path / "settings.db")
    with factory() as session:
        assert get_judge_provider(session) == JUDGE_DEFAULT_PROVIDER == "claude"
        assert get_judge_model(session, "claude") == CLAUDE_SCORING_MODEL_DEFAULT

        set_claude_model(session, "claude_scoring_model", "claude-haiku-4-5-20251001")
        session.commit()
        assert get_judge_model(session, "claude") == "claude-haiku-4-5-20251001"


def test_judge_model_from_a_different_provider_never_leaks_to_the_default(
    tmp_path: Path,
) -> None:
    """A judge_model row with no matching judge_provider row is a foreign or
    orphaned value, not this provider's model — it must not reach the
    default provider's call (#315, review finding F3)."""
    factory = init_db(tmp_path / "settings.db")
    with factory() as session:
        set_claude_model(session, SETTING_JUDGE_MODEL, "grok-4.6")
        session.commit()
        assert get_judge_provider(session) == "claude"
        assert get_judge_model(session, "claude") == CLAUDE_SCORING_MODEL_DEFAULT


def test_judge_provider_without_a_stored_model_falls_back_cleanly(
    tmp_path: Path,
) -> None:
    """A judge_provider row with no matching judge_model row leaves the
    model empty for a non-default provider — never a stale model borrowed
    from elsewhere (#315, review finding F3)."""
    factory = init_db(tmp_path / "settings.db")
    with factory() as session:
        set_claude_model(session, SETTING_JUDGE_PROVIDER, "grok")
        session.commit()
        assert get_judge_provider(session) == "grok"
        assert get_judge_model(session, "grok") == ""


@pytest.mark.parametrize("route", ["cli", "api"])
def test_saved_judge_route_survives_repinning_and_settings_rollback(tmp_path, route):
    factory = init_db(tmp_path / "settings.db")
    with factory() as session:
        set_judge_settings(session, "grok", route, "grok-4.6")
        session.commit()
    with factory() as session:
        assert pin_judge_route_if_unset(session, anthropic_key_is_set=True) is None
        assert pin_judge_route_if_unset(session, anthropic_key_is_set=False) is None
        assert get_judge_route(session) == route
        set_judge_settings(session, "codex", "api", "gpt-5.4")
        session.rollback()
        assert get_judge_route(session) == route
        assert get_judge_provider(session) == "grok"
        assert get_judge_model(session, "grok") == "grok-4.6"


def test_judge_route_has_no_implicit_default(tmp_path):
    factory = init_db(tmp_path / "settings.db")
    with factory() as session, pytest.raises(ValueError, match="Judge route"):
        get_judge_route(session)


# ── /api/settings/judge ──────────────────────────────────────────────


@pytest.fixture
def admin_client(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "agent_providers.catalog.list_provider_models",
        lambda provider, _route: list(LIVE_CATALOG[provider]),
    )
    factory = init_db(tmp_path / "judge_api.db")
    with factory() as session:
        pin_judge_route_if_unset(session, anthropic_key_is_set=True)
        session.add(User(id="u-test", username="user-u-test", role="admin"))
        session.commit()
    app = make_router_app(
        make_router_ctx(tmp_path, db=factory),
        user=make_authenticated_user("u-test", role="admin", username="u-u-test"),
    )
    return web_client(app), factory


def test_unknown_judge_provider_rejected_at_the_settings_boundary(admin_client) -> None:
    client, _ = admin_client
    resp = client.put("/api/settings/judge", json={"provider": "bob", "model": "x"})
    assert resp.status_code == 422


def test_judge_model_must_be_in_the_live_catalog(
    admin_client, every_provider_is_configured,
) -> None:
    client, _ = admin_client
    rejected = client.put("/api/settings/judge", json={"provider": "grok", "model": "grok-4"})
    assert rejected.status_code == 422

    accepted = client.put("/api/settings/judge", json={"provider": "grok", "model": "grok-4.6"})
    assert accepted.status_code == 200
    body = accepted.json()
    assert body["provider"] == "grok"
    assert body["model"] == "grok-4.6"

    fetched = client.get("/api/settings/judge").json()
    assert fetched["provider"] == "grok"
    assert fetched["model"] == "grok-4.6"


def test_default_judge_model_is_available_for_get_and_first_save(
    admin_client, monkeypatch, every_provider_is_configured,
) -> None:
    client, _ = admin_client
    aliases = {
        "claude": ["haiku", "opus", "sonnet"],
        "grok": LIVE_CATALOG["grok"],
        "codex": LIVE_CATALOG["codex"],
    }
    monkeypatch.setattr(
        "agent_providers.catalog.list_provider_models",
        lambda provider, _route: aliases[provider],
    )
    refresh_provider_snapshots()

    fetched = client.get("/api/settings/judge")
    assert fetched.status_code == 200
    default_model = fetched.json()["model"]
    assert default_model in fetched.json()["allowed_models"]

    first_save = client.put(
        "/api/settings/judge",
        json={"provider": "claude", "model": default_model},
    )
    assert first_save.status_code == 200

    unknown = client.put(
        "/api/settings/judge",
        json={"provider": "claude", "model": "claude-nonexistent-9"},
    )
    assert unknown.status_code == 422


# ── run_scoring_job wiring ───────────────────────────────────────────


def _seeded_generation(tmp_path: Path) -> tuple:
    factory = init_db(tmp_path / "scoring.db")
    with factory() as session:
        session.add(User(id="u1", username="user1", role="user"))
        session.flush()
        session.add(Album(id="alb1", title="Rock", artist="Band", created_by="u1"))
        session.add(Song(id="s1", title="Song One", album_id="alb1", track_number=1))
        session.add(Version(
            id="v1", song_id="s1", version_number=1,
            lyrics="Hello world", prompt="rock style", bpm=120,
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


def _scoring_result_with_transcript() -> SongScores:
    return SongScores(
        emotional_dynamics=EmotionalDynamicsScore(
            pitch_cv=0.3, rms_contrast=2.0, onset_rate_cv=0.2,
            overall_expressiveness=0.55,
        ),
        text_accuracy=TextAccuracyScore(
            similarity_ratio=0.9,
            intended_line_texts=("hello", "world"),
            transcribed_line_texts=("hello", "world"),
            whisper_cues=(WhisperCue(start=0.0, end=0.8, text="hello world"),),
        ),
        runs=(
            ScorerRun(scorer="emotional_dynamics", outcome=ScorerOutcome.OK),
            ScorerRun(scorer="text_accuracy", outcome=ScorerOutcome.OK),
        ),
    )


@pytest.mark.parametrize(
    ("provider", "route", "model"),
    [("grok", "api", "grok-4.6"), ("claude", "api", "claude-sonnet-4-6")],
)
def test_scoring_run_calls_no_provider_and_writes_no_verdict_key(
    tmp_path: Path, provider: str, route: str, model: str,
) -> None:
    """Whatever the judge settings hold, a scoring run completes without
    reaching a provider and leaves a stored verdict pair exactly as it is
    (#1976, the operator's ruling of 28.10.2026)."""
    from songmaker_cli.db.models import Score

    factory, audio_dir = _seeded_generation(tmp_path)
    stored_pair = {"lyrical_coherence": 8, "lyrical_summary": "stored verdict"}
    with factory() as session:
        set_judge_settings(session, provider, route, model)
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


def test_scoring_run_for_a_take_without_a_score_row_writes_no_verdict_key(
    tmp_path: Path,
) -> None:
    from songmaker_cli.db.models import Score

    factory, audio_dir = _seeded_generation(tmp_path)
    with patch(
        "songmaker_cli.jobs.get_scorer_process",
        return_value=MagicMock(score=MagicMock(
            return_value=_scoring_result_with_transcript(),
        )),
    ):
        run_scoring_job("j-score", "g1", None, db_factory=factory, audio_dir=audio_dir)

    with factory() as session:
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
