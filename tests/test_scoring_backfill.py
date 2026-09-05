"""Score backfill (issue #222) — throttled catch-up for scoreless generations."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import fakeredis
import pytest

from songmaker_cli.constants import (
    SCORE_BACKFILL_ATTEMPT_TTL_SECONDS,
    SCORE_BACKFILL_ATTEMPTS_KEY_PREFIX,
    SCORE_BACKFILL_BATCH_SIZE,
)
from songmaker_cli.db.engine import init_test_db
from songmaker_cli.db.models import Album, Generation, Score, Song, User, Version
from songmaker_cli.lifecycle import (
    _exhausted_backfill_ids,
    _pick_unscored_generations,
    backfill_unscored_generations,
)


def _run(coro):
    return asyncio.run(coro)


def _fake_redis() -> fakeredis.FakeAsyncRedis:
    return fakeredis.FakeAsyncRedis(decode_responses=True)


def _attempt_key(gen_id: str) -> str:
    return f"{SCORE_BACKFILL_ATTEMPTS_KEY_PREFIX}:{gen_id}"


@dataclass
class _FakeContext:
    db: object


def _seed_song(factory, *, album_id: str = "a1", song_id: str = "s1") -> None:
    with factory() as session:
        session.add(User(id="u1", username="user1", password_hash="h", role="user"))
        session.flush()
        session.add(Album(id=album_id, title="Album", artist="Artist", created_by="u1"))
        session.add(Song(id=song_id, title="Song", album_id=album_id, track_number=1))
        session.commit()


@pytest.fixture
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
        result = _run(backfill_unscored_generations(ctx, redis=_fake_redis()))

    assert result.dispatched == 2
    assert result.first_error is None
    dispatched = {call.args[2] for call in auto_score.await_args_list}
    assert dispatched == {"g1", "g2"}


def test_backfill_leaves_the_already_scored_generation_alone(seeded_generations) -> None:
    ctx = _FakeContext(db=seeded_generations)
    auto_score = AsyncMock()
    with patch("songmaker_cli.jobs._auto_score_generation", auto_score):
        _run(backfill_unscored_generations(ctx, redis=_fake_redis()))

    dispatched = {call.args[2] for call in auto_score.await_args_list}
    assert "g0" not in dispatched


def test_backfill_survives_one_generations_failure_and_scores_the_rest(
    seeded_generations,
) -> None:
    auto_score = AsyncMock(side_effect=[RuntimeError("boom"), None])
    ctx = _FakeContext(db=seeded_generations)
    with patch("songmaker_cli.jobs._auto_score_generation", auto_score):
        result = _run(backfill_unscored_generations(ctx, redis=_fake_redis()))

    assert result.dispatched == 1
    assert isinstance(result.first_error, RuntimeError)
    assert auto_score.await_count == 2


def test_backfill_logs_every_failed_generation(seeded_generations, caplog) -> None:
    auto_score = AsyncMock(side_effect=[RuntimeError("first"), RuntimeError("second")])
    ctx = _FakeContext(db=seeded_generations)

    with patch("songmaker_cli.jobs._auto_score_generation", auto_score):
        result = _run(backfill_unscored_generations(ctx, redis=_fake_redis()))

    assert result.dispatched == 0
    assert isinstance(result.first_error, RuntimeError)
    failure_records = [
        record for record in caplog.records
        if record.getMessage().startswith("Score backfill failed for generation")
    ]
    assert [record.args for record in failure_records] == [("g1",), ("g2",)]


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
        result = _run(backfill_unscored_generations(ctx, redis=_fake_redis()))

    assert result.dispatched == SCORE_BACKFILL_BATCH_SIZE
    assert result.first_error is None


# ── Starvation guard (issue #222 review) ───────────────────────────


def test_backfill_stops_picking_a_chronically_unscorable_generation(tmp_path: Path) -> None:
    """A generation that never gets a Score row must not win every batch
    forever: once it hits SCORE_BACKFILL_MAX_ATTEMPTS the next-oldest
    unscored generation gets a turn instead.

    Before the attempt-tracking fix, ``_pick_unscored_generations`` alone
    decides the batch and has no memory of prior attempts — with batch
    size 1 it would return the same oldest, still-unscored generation on
    every single tick and g_good would never be reached.
    """
    factory = init_test_db(tmp_path / "test.db")
    with factory() as session:
        session.add(User(id="u1", username="user1", password_hash="h", role="user"))
        session.flush()
        session.add(Album(id="a1", title="Album", artist="Artist", created_by="u1"))
        session.add(Song(id="s1", title="Song", album_id="a1", track_number=1))
        session.add(Generation(
            id="g_bad", song_id="s1", generation_number=1, mp3_path="g_bad.mp3",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ))
        session.add(Generation(
            id="g_good", song_id="s1", generation_number=2, mp3_path="g_good.mp3",
            created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        ))
        session.commit()

    ctx = _FakeContext(db=factory)
    auto_score = AsyncMock()  # never actually creates a Score row for either

    async def _three_ticks() -> None:
        redis = _fake_redis()
        await backfill_unscored_generations(ctx, redis)
        await backfill_unscored_generations(ctx, redis)
        await backfill_unscored_generations(ctx, redis)

    with (
        patch("songmaker_cli.jobs._auto_score_generation", auto_score),
        patch("songmaker_cli.constants.SCORE_BACKFILL_BATCH_SIZE", 1),
        patch("songmaker_cli.constants.SCORE_BACKFILL_MAX_ATTEMPTS", 2),
    ):
        _run(_three_ticks())

    dispatched = [call.args[2] for call in auto_score.await_args_list]
    assert dispatched == ["g_bad", "g_bad", "g_good"]


def test_exhausted_backfill_ids_excludes_only_ids_at_or_over_the_limit() -> None:
    async def _scenario() -> set[str]:
        redis = _fake_redis()
        await redis.set(_attempt_key("g1"), "3")
        await redis.set(_attempt_key("g2"), "2")
        return await _exhausted_backfill_ids(redis, ["g1", "g2", "g3"])

    with patch("songmaker_cli.constants.SCORE_BACKFILL_MAX_ATTEMPTS", 3):
        exhausted = _run(_scenario())

    assert exhausted == {"g1"}


def test_backfill_becomes_eligible_again_once_its_attempt_key_expires(tmp_path: Path) -> None:
    """The TTL is what lets a chronically-failing generation retry later
    (e.g. after a scorer bug fix) — simulated here by deleting the counter
    key directly, the same state a lapsed TTL leaves behind."""
    factory = init_test_db(tmp_path / "test.db")
    _seed_song(factory)
    with factory() as session:
        session.add(Generation(id="g1", song_id="s1", generation_number=1, mp3_path="g1.mp3"))
        session.commit()

    ctx = _FakeContext(db=factory)
    first_attempt = AsyncMock()
    retried = AsyncMock()

    async def _scenario() -> None:
        redis = _fake_redis()
        with (
            patch("songmaker_cli.jobs._auto_score_generation", first_attempt),
            patch("songmaker_cli.constants.SCORE_BACKFILL_MAX_ATTEMPTS", 1),
        ):
            await backfill_unscored_generations(ctx, redis)  # attempt 1 — now exhausted
            await backfill_unscored_generations(ctx, redis)  # skipped: exhausted

        await redis.delete(_attempt_key("g1"))

        with (
            patch("songmaker_cli.jobs._auto_score_generation", retried),
            patch("songmaker_cli.constants.SCORE_BACKFILL_MAX_ATTEMPTS", 1),
        ):
            await backfill_unscored_generations(ctx, redis)

    _run(_scenario())

    assert first_attempt.await_count == 1
    retried.assert_awaited_once()


def test_backfill_sets_a_ttl_on_the_attempt_counter(tmp_path: Path) -> None:
    factory = init_test_db(tmp_path / "test.db")
    _seed_song(factory)
    with factory() as session:
        session.add(Generation(id="g1", song_id="s1", generation_number=1, mp3_path="g1.mp3"))
        session.commit()

    ctx = _FakeContext(db=factory)

    async def _scenario() -> int:
        redis = _fake_redis()
        await backfill_unscored_generations(ctx, redis)
        return await redis.ttl(_attempt_key("g1"))

    with patch("songmaker_cli.jobs._auto_score_generation", AsyncMock()):
        ttl = _run(_scenario())

    assert 0 < ttl <= SCORE_BACKFILL_ATTEMPT_TTL_SECONDS


def test_backfill_clears_attempt_tracking_once_a_generation_gets_scored(
    tmp_path: Path,
) -> None:
    """A tracked generation that finally has a score — however it got
    scored — has its counter actively dropped rather than left to expire,
    so it starts with a clean budget if it were ever unscored again."""
    factory = init_test_db(tmp_path / "test.db")
    _seed_song(factory)
    with factory() as session:
        session.add(Generation(id="g1", song_id="s1", generation_number=1, mp3_path="g1.mp3"))
        session.commit()

    ctx = _FakeContext(db=factory)
    second_tick = AsyncMock()

    async def _scenario() -> tuple[int, int]:
        redis = _fake_redis()
        with patch("songmaker_cli.jobs._auto_score_generation", AsyncMock()):
            await backfill_unscored_generations(ctx, redis)
        tracked_after_first_attempt = await redis.exists(_attempt_key("g1"))

        with factory() as session:
            session.add(Score(
                id="sc1", generation_id="g1", scorer="batch", value={"text_accuracy": 90},
            ))
            session.commit()

        with patch("songmaker_cli.jobs._auto_score_generation", second_tick):
            await backfill_unscored_generations(ctx, redis)
        tracked_after_scoring = await redis.exists(_attempt_key("g1"))

        return tracked_after_first_attempt, tracked_after_scoring

    tracked_after_first_attempt, tracked_after_scoring = _run(_scenario())

    assert tracked_after_first_attempt == 1
    assert tracked_after_scoring == 0
    second_tick.assert_not_awaited()
