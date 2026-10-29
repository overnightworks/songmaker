"""REQ-COWRITER-34: the co-writer stores its coherence verdict on the person's own take."""
from __future__ import annotations

import json

import pytest
from postgres_lock_harness import CommitPause, race, wrote_to_tables
from sqlalchemy.orm import Session, sessionmaker

from songmaker_cli.cowriter.tools import execute_cowriter_tool
from songmaker_cli.db.engine import init_test_db
from songmaker_cli.db.models import Album, Generation, Score, Song, User, Version
from songmaker_cli.mcp_server import auth, tools

LOCAL_SCORES = {"bpm_detected": 96.0, "text_accuracy": 86.2}
SUMMARY = "Coherent verses; the bridge loops one phrase."


def _seed(session_factory):
    with session_factory() as session:
        session.add_all([
            User(id="anna", username="anna", role="user"),
            User(id="ben", username="ben", role="user"),
        ])
        session.flush()
        session.add(Album(id="album-anna", title="Nachtzug", artist="Anna", created_by="anna"))
        session.add(Song(id="song-anna", title="Nachtzug", album_id="album-anna", track_number=1))
        session.add(Version(
            id="version-anna", song_id="song-anna", version_number=1,
            lyrics="la la", prompt="rock",
        ))
        session.commit()
    return session_factory


@pytest.fixture
def factory(tmp_path):
    return _seed(init_test_db(tmp_path / "verdict.db"))


def _take(factory, generation_id, *, whisper_text="la la", batch=None, archived=False):
    with factory() as session:
        session.add(Generation(
            id=generation_id, song_id="song-anna", version_id="version-anna",
            generation_number=1, mp3_path=f"anna/{generation_id}.mp3",
            whisper_text=whisper_text, is_archived=archived,
        ))
        if batch is not None:
            session.add(Score(generation_id=generation_id, scorer="batch", value=batch))
        session.commit()


def _stored(factory, generation_id):
    with factory() as session:
        rows = session.query(Score).filter_by(generation_id=generation_id).all()
        return [(row.scorer, dict(row.value)) for row in rows]


def _save(factory, generation_id, score, summary, user="anna"):
    with factory() as session:
        return execute_cowriter_tool(
            session, auth.load_user(session, user), "save_coherence_verdict",
            {"generation_id": generation_id, "score": score, "summary": summary},
        )


def test_verdict_joins_the_take_s_local_scores(factory):
    _take(factory, "g1", batch=dict(LOCAL_SCORES))

    outcome = _save(factory, "g1", 8, SUMMARY)

    pair = {"lyrical_coherence": 8, "lyrical_summary": SUMMARY}
    assert outcome.is_error is False
    assert _stored(factory, "g1") == [("batch", {**LOCAL_SCORES, **pair})]
    shown = json.loads(outcome.content)["scores"]
    assert shown == {**LOCAL_SCORES, **pair}
    assert type(shown["lyrical_coherence"]) is int


def test_verdict_on_a_take_without_a_batch_row_creates_exactly_one(factory):
    _take(factory, "g1")

    outcome = _save(factory, "g1", 8, SUMMARY)

    pair = {"lyrical_coherence": 8, "lyrical_summary": SUMMARY}
    assert _stored(factory, "g1") == [("batch", pair)]
    assert json.loads(outcome.content)["scores"] == pair


def test_verdict_is_stored_on_an_archived_own_take(factory):
    _take(factory, "g1", archived=True)

    assert _save(factory, "g1", 5, "ok").is_error is False
    assert _stored(factory, "g1")[0][1]["lyrical_coherence"] == 5


def test_verdict_on_an_unknown_take_is_not_found_and_creates_no_row(factory):
    outcome = _save(factory, "nope", 8, SUMMARY)

    assert (outcome.is_error, outcome.content) == (True, "Generation not found")
    with factory() as session:
        assert session.query(Score).count() == 0


def test_administrators_do_not_reach_a_foreign_take(factory):
    _take(factory, "g1", batch=dict(LOCAL_SCORES))
    with factory() as session:
        session.get(User, "ben").role = "admin"
        session.commit()

    outcome = _save(factory, "g1", 8, SUMMARY, user="ben")

    assert (outcome.is_error, outcome.content) == (True, "Generation not found")
    assert _stored(factory, "g1") == [("batch", LOCAL_SCORES)]


@pytest.mark.parametrize("score", [1, 10])
def test_the_scale_ends_are_stored(factory, score):
    _take(factory, "g1")

    assert _save(factory, "g1", score, SUMMARY).is_error is False
    assert _stored(factory, "g1")[0][1]["lyrical_coherence"] == score


@pytest.mark.parametrize("score", [0, 11, -1])
def test_a_score_outside_one_to_ten_is_refused_and_changes_nothing(factory, score):
    _take(factory, "g1", batch=dict(LOCAL_SCORES))

    outcome = _save(factory, "g1", score, SUMMARY)

    assert (outcome.is_error, outcome.content) == (True, "score must be between 1 and 10")
    assert _stored(factory, "g1") == [("batch", LOCAL_SCORES)]


def test_a_summary_of_exactly_the_cap_is_stored(factory):
    _take(factory, "g1")

    assert _save(factory, "g1", 8, "a" * tools.COHERENCE_SUMMARY_MAX_CHARS).is_error is False
    assert len(_stored(factory, "g1")[0][1]["lyrical_summary"]) == 300


def test_a_summary_over_the_cap_is_refused_naming_the_cap(factory):
    _take(factory, "g1", batch=dict(LOCAL_SCORES))

    outcome = _save(factory, "g1", 8, "a" * 301)

    assert outcome.is_error is True
    assert "300" in outcome.content
    assert _stored(factory, "g1") == [("batch", LOCAL_SCORES)]


@pytest.mark.parametrize("summary", ["", "   "])
def test_an_empty_summary_is_refused(factory, summary):
    _take(factory, "g1", batch=dict(LOCAL_SCORES))

    outcome = _save(factory, "g1", 8, summary)

    assert outcome.is_error is True
    assert "empty" in outcome.content
    assert _stored(factory, "g1") == [("batch", LOCAL_SCORES)]


def test_a_summary_is_trimmed_before_it_is_stored(factory):
    _take(factory, "g1")

    assert _save(factory, "g1", 8, " x ").is_error is False
    assert _stored(factory, "g1")[0][1]["lyrical_summary"] == "x"


def test_a_two_line_summary_is_refused(factory):
    _take(factory, "g1", batch=dict(LOCAL_SCORES))

    outcome = _save(factory, "g1", 8, "a\nb")

    assert outcome.is_error is True
    assert "one line" in outcome.content
    assert _stored(factory, "g1") == [("batch", LOCAL_SCORES)]


def test_a_take_without_a_transcription_gets_no_verdict(factory):
    _take(factory, "g1", whisper_text=None, batch=dict(LOCAL_SCORES))

    outcome = _save(factory, "g1", 8, SUMMARY)

    assert (outcome.is_error, outcome.content) == (
        True, "this take has no transcription yet",
    )
    assert _stored(factory, "g1") == [("batch", LOCAL_SCORES)]


def test_a_take_without_sung_words_gets_no_verdict(factory):
    _take(factory, "g1", whisper_text="", batch=dict(LOCAL_SCORES))

    outcome = _save(factory, "g1", 8, SUMMARY)

    assert (outcome.is_error, outcome.content) == (
        True, "this take has no sung words to judge",
    )
    assert _stored(factory, "g1") == [("batch", LOCAL_SCORES)]


def test_a_later_verdict_replaces_the_pair_and_keeps_local_scores(factory):
    _take(factory, "g1", batch=dict(LOCAL_SCORES))
    _save(factory, "g1", 8, "a")

    _save(factory, "g1", 6, "b")

    assert _stored(factory, "g1") == [
        ("batch", {**LOCAL_SCORES, "lyrical_coherence": 6, "lyrical_summary": "b"}),
    ]


def test_a_refused_later_verdict_keeps_the_earlier_one(factory):
    _take(factory, "g1")
    _save(factory, "g1", 8, "a")

    _save(factory, "g1", 11, "b")

    assert _stored(factory, "g1") == [
        ("batch", {"lyrical_coherence": 8, "lyrical_summary": "a"}),
    ]


def test_competing_first_verdicts_leave_one_row_holding_the_later_pair(pg_factory):
    _seed(pg_factory)
    _take(pg_factory, "g1")
    pause = CommitPause(lambda session: wrote_to_tables(session, "scores"))

    race(
        pg_factory,
        lambda: _save(pg_factory, "g1", 8, "earlier"),
        lambda: _save(pg_factory, "g1", 6, "later"),
        pause,
    )

    assert _stored(pg_factory, "g1") == [
        ("batch", {"lyrical_coherence": 6, "lyrical_summary": "later"}),
    ]


@pytest.mark.parametrize(
    ("failure", "raised"),
    [
        (tools.MCPToolError("boom"), False),
        (RuntimeError("boom"), True),
    ],
)
def test_a_failure_after_the_flush_leaves_the_stored_row_as_it_was(factory, failure, raised):
    _take(factory, "g1", batch=dict(LOCAL_SCORES))

    class FailingAfterFlush(Session):
        def expire(self, *_args, **_kwargs):
            raise failure

    failing_factory = sessionmaker(bind=factory.kw["bind"], class_=FailingAfterFlush)

    if raised:
        with pytest.raises(RuntimeError):
            _save(failing_factory, "g1", 8, SUMMARY)
    else:
        assert _save(failing_factory, "g1", 8, SUMMARY).is_error is True
    assert _stored(factory, "g1") == [("batch", LOCAL_SCORES)]
