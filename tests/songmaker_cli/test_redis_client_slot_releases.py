"""A stream slot release left pending on one application's loop leaves another application alone."""

import asyncio
from pathlib import Path

from support.web_app import BUILT_SHELL, make_app_context, make_fake_redis, web_client

from songmaker_cli.server import create_app


def _end_loop_as_asyncio_run_does(loop: asyncio.AbstractEventLoop) -> None:
    pending = asyncio.all_tasks(loop)
    for task in pending:
        task.cancel()
    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
    loop.close()


def test_an_app_starts_and_stops_after_another_apps_loop_ended_with_a_release_pending(
    tmp_path: Path, pg_factory, no_task_left_pending: None,
) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    audio_dir = tmp_path / "audio"
    data_dir = tmp_path / "data"
    audio_dir.mkdir()
    data_dir.mkdir()
    (tmp_path / "frontend" / "build").mkdir(parents=True)
    (tmp_path / "frontend" / "build" / "index.html").write_text(BUILT_SHELL)

    class _NeverReleasingSlots:
        async def release(self, _token: str) -> bool:
            await asyncio.Future()
            return True

    first_ctx = make_app_context(
        db=pg_factory, audio_dir=audio_dir, data_dir=data_dir, redis=make_fake_redis(),
    )
    first_loop = asyncio.new_event_loop()

    async def _leave_a_release_pending(ctx) -> None:
        ctx.slot_releases.release_in_background(
            _NeverReleasingSlots(), "slot-token", subject="Test",
        )
        await asyncio.sleep(0)

    first_loop.run_until_complete(_leave_a_release_pending(first_ctx))

    second_ctx = make_app_context(
        db=pg_factory, audio_dir=audio_dir, data_dir=data_dir, redis=make_fake_redis(),
    )
    second_app = create_app(audio_dir, data_dir, tmp_path, ctx=second_ctx)
    try:
        with web_client(second_app) as client:
            assert client.get("/api/health").status_code < 500
    finally:
        _end_loop_as_asyncio_run_does(first_loop)
