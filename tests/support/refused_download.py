"""A download attempt that must not get to run."""

from __future__ import annotations

import pytest

from songmaker_cli.acestep_state import single_flight_download


async def attempt_download_that_must_not_run(pool, mode: str, job_id: str) -> None:
    async with single_flight_download(pool, mode, job_id):
        pytest.fail("the download must not run")
