"""The rate-limit update refuses an unknown key or a negative value and saves nothing."""

from __future__ import annotations

import pytest
from support.signed_in_people import sign_in_people

from songmaker_cli.constants import SETTING_GENERATION_RATE_LIMIT, SETTING_SCORING_RATE_LIMIT
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
            {SETTING_GENERATION_RATE_LIMIT: 5, "chat_rate_limit": 1},
            "Unknown setting keys: ['chat_rate_limit']",
        ),
        (
            {SETTING_GENERATION_RATE_LIMIT: 5, SETTING_SCORING_RATE_LIMIT: -1},
            f"Value for {SETTING_SCORING_RATE_LIMIT} must be non-negative",
        ),
    ],
    ids=["unknown-key", "removed-chat-key", "negative-value-after-a-valid-key"],
)
def test_a_refused_rate_limit_update_saves_none_of_its_keys(admin, settings, detail):
    client, factory = admin
    before = _stored_limits(factory)

    response = client.put(RATE_LIMITS_URL, json={"settings": settings})

    assert (response.status_code, response.json()["detail"]) == (400, detail)
    assert _stored_limits(factory) == before


def test_the_listing_names_no_chat_key_and_the_remaining_keys_save(admin):
    client, factory = admin

    listed = {item["setting_key"] for item in client.get(RATE_LIMITS_URL).json()["settings"]}
    saved = client.put(RATE_LIMITS_URL, json={"settings": {SETTING_GENERATION_RATE_LIMIT: 7}})

    assert "chat_rate_limit" not in listed
    assert SETTING_GENERATION_RATE_LIMIT in listed
    assert saved.status_code == 200
    assert _stored_limits(factory)[SETTING_GENERATION_RATE_LIMIT] == 7
