"""Score backfill (issue #222) — throttled catch-up for scoreless generations."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from songmaker_cli.constants import SCORE_BACKFILL_BATCH_SIZE
from songmaker_cli.db.engine import init_test_db
from songmaker_cli.db.models import Album, Generation, Score, Song, User, Version
from songmaker_cli.lifecycle import (
    _pick_unscored_generations,
    backfill_unscored_generations,
)


def _run(coro):
    return asyncio.run(coro)


@dataclass
class _FakeContext:
    db: object


@pytest.fixture()
def seeded_generations(tmp_path: Path):
    """Three generations on one song: g0 already scored, g1 and g2 are not."""
    factory = init_test_db(tmp_path / "test.db")
    with factory() as session:
        session.add(User(id="u1", username="user1", password_hash="h", role="user"))
        session.flush()
        session.add(Album(id="a1", title="Album", artist="Artist", created_by="u1"))
        session.add(Song(id="s1", title="Song", album_id="a1", track_number=1))
        session.add(Version(
            id="v1", song_id="s1", version_number=1, lyrics="", prompt="",
            bpm=120, audio_duration=60, key_scale="Am",
        ))
        for i in range(3):
            session.add(Generation(
                id=f"g{i}", song_id="s1", version_id="v1",
                generation_number=i + 1, mp3_path=f"g{i}.mp3",
            ))
        session.add(Score(
            id="sc0", generation_id="g0", scorer="batch",
            value={"text_accuracy": 90},
        ))
        session.commit()
    return factory


def test_pick_unscored_generations_excludes_scored_rows(seeded_generations) -> None:
    with seeded_generations() as session:
        picked = _pick_unscored_generations(session, limit=10)
    assert {gen_id for gen_id, _song_id in picked} == {"g1", "g2"}


def test_pick_unscored_generations_respects_the_limit(seeded_generations) -> None:
    with seeded_generations() as session:
        picked = _pick_unscored_generations(session, limit=1)
    assert len(picked) == 1


def test_pick_unscored_generations_reports_the_owning_song(seeded_generations) -> None:
    with seeded_generations() as session:
        picked = _pick_unscored_generations(session, limit=10)
    assert dict(picked) == {"g1": "s1", "g2": "s1"}


def test_backfill_dispatches_auto_score_for_every_unscored_generation(
    seeded_generations,
) -> None:
    ctx = _FakeContext(db=seeded_generations)
    auto_score = AsyncMock()
    with patch("songmaker_cli.jobs._auto_score_generation", auto_score):
        scored = _run(backfill_unscored_generations(ctx, redis=object()))

    assert scored == 2
    dispatched = {call.args[2] for call in auto_score.await_args_list}
    assert dispatched == {"g1", "g2"}


def test_backfill_leaves_the_already_scored_generation_alone(seeded_generations) -> None:
    ctx = _FakeContext(db=seeded_generations)
    auto_score = AsyncMock()
    with patch("songmaker_cli.jobs._auto_score_generation", auto_score):
        _run(backfill_unscored_generations(ctx, redis=object()))

    dispatched = {call.args[2] for call in auto_score.await_args_list}
    assert "g0" not in dispatched


def test_backfill_survives_one_generations_failure_and_scores_the_rest(
    seeded_generations,
) -> None:
    auto_score = AsyncMock(side_effect=[RuntimeError("boom"), None])
    ctx = _FakeContext(db=seeded_generations)
    with patch("songmaker_cli.jobs._auto_score_generation", auto_score):
        scored = _run(backfill_unscored_generations(ctx, redis=object()))

    assert scored == 1
    assert auto_score.await_count == 2


def test_backfill_respects_the_named_batch_size(tmp_path: Path) -> None:
    factory = init_test_db(tmp_path / "test.db")
    with factory() as session:
        session.add(User(id="u1", username="user1", password_hash="h", role="user"))
        session.flush()
        session.add(Album(id="a1", title="Album", artist="Artist", created_by="u1"))
        session.add(Song(id="s1", title="Song", album_id="a1", track_number=1))
        for i in range(SCORE_BACKFILL_BATCH_SIZE + 3):
            session.add(Generation(
                id=f"g{i}", song_id="s1", generation_number=i + 1, mp3_path=f"g{i}.mp3",
            ))
        session.commit()

    ctx = _FakeContext(db=factory)
    auto_score = AsyncMock()
    with patch("songmaker_cli.jobs._auto_score_generation", auto_score):
        scored = _run(backfill_unscored_generations(ctx, redis=object()))

    assert scored == SCORE_BACKFILL_BATCH_SIZE
