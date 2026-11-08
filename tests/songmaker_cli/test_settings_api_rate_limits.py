"""The rate-limit update refuses an unknown key or a negative value and saves nothing."""

from __future__ import annotations

import pytest
from support.signed_in_people import sign_in_people

from songmaker_cli.constants import SETTING_CHAT_RATE_LIMIT, SETTING_GENERATION_RATE_LIMIT
from songmaker_cli.db.models import RateLimitSetting

RATE_LIMITS_URL = "/api/settings/rate-limits"


@pytest.fixture
def admin(tmp_path, pg_factory):
    return sign_in_people(tmp_path, pg_factory, {"root": "admin"})["root"], pg_factory


def _stored_limits(factory) -> dict[str, int]:
    with factory() as session:
        return {row.setting_key: row.value for row in session.query(RateLimitSetting)}


@pytest.mark.parametrize(
    ("settings", "detail"),
    [
        (
            {SETTING_GENERATION_RATE_LIMIT: 5, "bogus": 1},
            "Unknown setting keys: ['bogus']",
        ),
        (
            {SETTING_GENERATION_RATE_LIMIT: 5, SETTING_CHAT_RATE_LIMIT: -1},
            f"Value for {SETTING_CHAT_RATE_LIMIT} must be non-negative",
        ),
    ],
    ids=["unknown-key", "negative-value-after-a-valid-key"],
)
def test_a_refused_rate_limit_update_saves_none_of_its_keys(admin, settings, detail):
    client, factory = admin
    before = _stored_limits(factory)

    response = client.put(RATE_LIMITS_URL, json={"settings": settings})

    assert (response.status_code, response.json()["detail"]) == (400, detail)
    assert _stored_limits(factory) == before
