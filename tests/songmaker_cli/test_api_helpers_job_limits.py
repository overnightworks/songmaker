"""A job type without a windowed rate limit is refused by the job creator, not counted."""

from __future__ import annotations

import pytest
from support.lock_owners import OWNER_ID, seed_committed_owner
from support.web_app import make_authenticated_user, make_fake_redis

from songmaker_cli.api_helpers import create_job_with_rate_limit
from songmaker_cli.db.models import Job
from songmaker_cli.job_types import JobType


@pytest.fixture
def session(pg_factory):
    with pg_factory() as db:
        seed_committed_owner(db)
        yield db


def test_a_job_type_with_no_windowed_rate_limit_is_refused_and_leaves_no_job(session) -> None:
    owner = make_authenticated_user(OWNER_ID)
    redis = make_fake_redis()

    with pytest.raises(ValueError, match="Unknown job type for rate limiting"):
        create_job_with_rate_limit(session, owner, JobType.COVER, redis=redis)

    assert session.query(Job).count() == 0
