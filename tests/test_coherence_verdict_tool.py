"""REQ-COWRITER-34: the co-writer stores its coherence verdict on the person's own take."""
from __future__ import annotations

import json

import pytest
from sqlalchemy.orm import Session, sessionmaker
from support.coherence_verdicts import add_take, save_verdict, seed_verdict_world, stored_scores

from songmaker_cli.db.engine import init_test_db
from songmaker_cli.db.models import Score, User
from songmaker_cli.mcp_server import tools

LOCAL_SCORES = {"bpm_detected": 96.0, "text_accuracy": 86.2}
SUMMARY = "Coherent verses; the bridge loops one phrase."


@pytest.fixture
def factory(tmp_path):
    return seed_verdict_world(init_test_db(tmp_path / "verdict.db"))


def test_verdict_joins_the_take_s_local_scores(factory):
    add_take(factory, "g1", batch=dict(LOCAL_SCORES))

    outcome = save_verdict(factory, "g1", 8, SUMMARY)

    pair = {"lyrical_coherence": 8, "lyrical_summary": SUMMARY}
    assert outcome.is_error is False
    assert stored_scores(factory, "g1") == [("batch", {**LOCAL_SCORES, **pair})]
    shown = json.loads(outcome.content)["scores"]
    assert shown == {**LOCAL_SCORES, **pair}
    assert type(shown["lyrical_coherence"]) is int


def test_verdict_on_a_take_without_a_batch_row_creates_exactly_one(factory):
    add_take(factory, "g1")

    outcome = save_verdict(factory, "g1", 8, SUMMARY)

    pair = {"lyrical_coherence": 8, "lyrical_summary": SUMMARY}
    assert stored_scores(factory, "g1") == [("batch", pair)]
    assert json.loads(outcome.content)["scores"] == pair


def test_verdict_is_stored_on_an_archived_own_take(factory):
    add_take(factory, "g1", archived=True)

    assert save_verdict(factory, "g1", 5, "ok").is_error is False
    assert stored_scores(factory, "g1")[0][1]["lyrical_coherence"] == 5


def test_verdict_on_an_unknown_take_is_not_found_and_creates_no_row(factory):
    outcome = save_verdict(factory, "nope", 8, SUMMARY)

    assert (outcome.is_error, outcome.content) == (True, "Generation not found")
    with factory() as session:
        assert session.query(Score).count() == 0


def test_administrators_do_not_reach_a_foreign_take(factory):
    add_take(factory, "g1", batch=dict(LOCAL_SCORES))
    with factory() as session:
        session.get(User, "ben").role = "admin"
        session.commit()

    outcome = save_verdict(factory, "g1", 8, SUMMARY, user="ben")

    assert (outcome.is_error, outcome.content) == (True, "Generation not found")
    assert stored_scores(factory, "g1") == [("batch", LOCAL_SCORES)]


@pytest.mark.parametrize("score", [1, 10])
def test_the_scale_ends_are_stored(factory, score):
    add_take(factory, "g1")

    assert save_verdict(factory, "g1", score, SUMMARY).is_error is False
    assert stored_scores(factory, "g1")[0][1]["lyrical_coherence"] == score


@pytest.mark.parametrize("score", [0, 11, -1])
def test_a_score_outside_one_to_ten_is_refused_and_changes_nothing(factory, score):
    add_take(factory, "g1", batch=dict(LOCAL_SCORES))

    outcome = save_verdict(factory, "g1", score, SUMMARY)

    assert (outcome.is_error, outcome.content) == (True, "score must be between 1 and 10")
    assert stored_scores(factory, "g1") == [("batch", LOCAL_SCORES)]


def test_a_summary_of_exactly_the_cap_is_stored(factory):
    add_take(factory, "g1")

    assert save_verdict(factory, "g1", 8, "a" * tools.COHERENCE_SUMMARY_MAX_CHARS).is_error is False
    assert len(stored_scores(factory, "g1")[0][1]["lyrical_summary"]) == 300


def test_a_summary_over_the_cap_is_refused_naming_the_cap(factory):
    add_take(factory, "g1", batch=dict(LOCAL_SCORES))

    outcome = save_verdict(factory, "g1", 8, "a" * 301)

    assert outcome.is_error is True
    assert "300" in outcome.content
    assert stored_scores(factory, "g1") == [("batch", LOCAL_SCORES)]


@pytest.mark.parametrize("summary", ["", "   "])
def test_an_empty_summary_is_refused(factory, summary):
    add_take(factory, "g1", batch=dict(LOCAL_SCORES))

    outcome = save_verdict(factory, "g1", 8, summary)

    assert outcome.is_error is True
    assert "empty" in outcome.content
    assert stored_scores(factory, "g1") == [("batch", LOCAL_SCORES)]


def test_a_summary_is_trimmed_before_it_is_stored(factory):
    add_take(factory, "g1")

    assert save_verdict(factory, "g1", 8, " x ").is_error is False
    assert stored_scores(factory, "g1")[0][1]["lyrical_summary"] == "x"


def test_a_two_line_summary_is_refused(factory):
    add_take(factory, "g1", batch=dict(LOCAL_SCORES))

    outcome = save_verdict(factory, "g1", 8, "a\nb")

    assert outcome.is_error is True
    assert "one line" in outcome.content
    assert stored_scores(factory, "g1") == [("batch", LOCAL_SCORES)]


def test_a_take_without_a_transcription_gets_no_verdict(factory):
    add_take(factory, "g1", whisper_text=None, batch=dict(LOCAL_SCORES))

    outcome = save_verdict(factory, "g1", 8, SUMMARY)

    assert (outcome.is_error, outcome.content) == (
        True, "this take has no transcription yet",
    )
    assert stored_scores(factory, "g1") == [("batch", LOCAL_SCORES)]


def test_a_take_without_sung_words_gets_no_verdict(factory):
    add_take(factory, "g1", whisper_text="", batch=dict(LOCAL_SCORES))

    outcome = save_verdict(factory, "g1", 8, SUMMARY)

    assert (outcome.is_error, outcome.content) == (
        True, "this take has no sung words to judge",
    )
    assert stored_scores(factory, "g1") == [("batch", LOCAL_SCORES)]


def test_a_later_verdict_replaces_the_pair_and_keeps_local_scores(factory):
    add_take(factory, "g1", batch=dict(LOCAL_SCORES))
    save_verdict(factory, "g1", 8, "a")

    save_verdict(factory, "g1", 6, "b")

    assert stored_scores(factory, "g1") == [
        ("batch", {**LOCAL_SCORES, "lyrical_coherence": 6, "lyrical_summary": "b"}),
    ]


def test_a_refused_later_verdict_keeps_the_earlier_one(factory):
    add_take(factory, "g1")
    save_verdict(factory, "g1", 8, "a")

    save_verdict(factory, "g1", 11, "b")

    assert stored_scores(factory, "g1") == [
        ("batch", {"lyrical_coherence": 8, "lyrical_summary": "a"}),
    ]


@pytest.mark.parametrize(
    ("failure", "raised"),
    [
        (tools.MCPToolError("boom"), False),
        (RuntimeError("boom"), True),
    ],
)
def test_a_failure_after_the_flush_leaves_the_stored_row_as_it_was(factory, failure, raised):
    add_take(factory, "g1", batch=dict(LOCAL_SCORES))

    class FailingAfterFlush(Session):
        def expire(self, *_args, **_kwargs):
            raise failure

    failing_factory = sessionmaker(bind=factory.kw["bind"], class_=FailingAfterFlush)

    if raised:
        with pytest.raises(RuntimeError):
            save_verdict(failing_factory, "g1", 8, SUMMARY)
    else:
        assert save_verdict(failing_factory, "g1", 8, SUMMARY).is_error is True
    assert stored_scores(factory, "g1") == [("batch", LOCAL_SCORES)]
