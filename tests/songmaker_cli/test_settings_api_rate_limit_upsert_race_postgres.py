"""Two admins saving one global rate limit at the same moment both get an answer, and the
later value is the one stored."""

from __future__ import annotations

from pathlib import Path

from support.postgres_lock_harness import CommitPause, race, wrote_to_tables
from support.web_app import make_test_app, seed_session, seed_user

from songmaker_cli.constants import SETTING_GENERATION_RATE_LIMIT
from songmaker_cli.db.models import RateLimitSetting

ADMIN = "admin-1"
RATE_LIMITS_PATH = "/api/settings/rate-limits"


def test_two_saves_of_one_global_limit_both_answer_and_the_later_value_stays(
    pg_factory, tmp_path: Path,
) -> None:
    client, _ = make_test_app(
        tmp_path, factory=pg_factory,
        seed_db=lambda session: seed_user(session, "admin", "admin", user_id=ADMIN),
    )
    seed_session(client, "admin")

    def save(value: int):
        return lambda: client.put(
            RATE_LIMITS_PATH, json={"settings": {SETTING_GENERATION_RATE_LIMIT: value}},
        )

    answers = race(
        pg_factory, save(3), save(7),
        CommitPause(lambda session: wrote_to_tables(session, "rate_limit_settings")),
    )

    assert answers["first"].status_code == 200
    assert answers["second"].status_code == 200
    with pg_factory() as session:
        stored = session.query(RateLimitSetting).filter_by(
            setting_key=SETTING_GENERATION_RATE_LIMIT, user_id=None,
        ).all()
    assert [row.value for row in stored] == [7]
