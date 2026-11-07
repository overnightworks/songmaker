"""The countdown the reference list hands out and the acknowledgement that publishes it."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from support import reference_api_world
from support.reference_api_world import (
    REFERENCES_PATH,
    link_reference,
    seed_reference,
    signed_in_as,
)
from support.web_app import TEST_ORIGIN

from songmaker_cli import reference_api
from songmaker_cli.cleanup import DAILY_CLEANUP_HOUR_UTC
from songmaker_cli.constants import SETTING_REFERENCE_COUNTDOWN_VISIBLE_SINCE
from songmaker_cli.db.engine import init_test_db
from songmaker_cli.db.models import RateLimitSetting, ReferenceRecording
from songmaker_cli.reference_api import STALE_COUNTDOWN_EPOCH_DETAIL
from songmaker_cli.reference_audio import reference_deletes_at
from songmaker_cli.settings import get_settings

signed_in = reference_api_world.signed_in

SHOWN_PATH = f"{REFERENCES_PATH}/countdown-shown"


def _utc(*parts: int) -> datetime:
    return datetime(*parts, tzinfo=timezone.utc)


def _countdown_rows(client: TestClient) -> list[RateLimitSetting]:
    with client.app.state.ctx.db() as session:
        return list(session.scalars(select(RateLimitSetting).where(
            RateLimitSetting.setting_key == SETTING_REFERENCE_COUNTDOWN_VISIBLE_SINCE,
        )))


def _epoch(client: TestClient) -> str:
    [row] = _countdown_rows(client)
    return row.id


def _published_text(client: TestClient) -> str | None:
    [row] = _countdown_rows(client)
    return row.value_text


def _set_published_text(client: TestClient, value_text: str | None) -> None:
    with client.app.state.ctx.db() as session:
        session.execute(
            RateLimitSetting.__table__.update()
            .where(RateLimitSetting.setting_key == SETTING_REFERENCE_COUNTDOWN_VISIBLE_SINCE)
            .values(value_text=value_text),
        )
        session.commit()


def _set_unused_since(
    client: TestClient, reference_id: str, *, unused_since: datetime | None, is_kept: bool = False,
) -> None:
    with client.app.state.ctx.db() as session:
        row = session.get(ReferenceRecording, reference_id)
        row.unused_since = unused_since
        row.is_kept = is_kept
        session.commit()


def _listing(client: TestClient) -> dict:
    response = client.get(REFERENCES_PATH)
    assert response.status_code == 200, response.text
    return response.json()


def _post_epoch(client: TestClient, epoch: str):
    return client.post(SHOWN_PATH, json={"epoch": epoch})


# the formula

@pytest.mark.parametrize(
    ("unused_since", "published", "now", "days", "hour", "expected"),
    [
        pytest.param(
            _utc(2026, 11, 1), None, _utc(2026, 11, 7, 10), 30, 3, _utc(2026, 12, 8, 3),
            id="unpublished-counts-from-now",
        ),
        pytest.param(
            _utc(2026, 11, 9, 1), None, _utc(2026, 11, 7, 10), 30, 3, _utc(2026, 12, 9, 3),
            id="unpublished-unused-later-than-now-counts-from-the-stamp",
        ),
        pytest.param(
            _utc(2026, 11, 1), _utc(2026, 11, 5, 10), _utc(2026, 11, 7), 30, 3,
            _utc(2026, 12, 6, 3), id="published-after-the-stamp-counts-from-publication",
        ),
        pytest.param(
            _utc(2026, 11, 3, 12), _utc(2026, 11, 1), _utc(2026, 11, 7), 30, 3,
            _utc(2026, 12, 4, 3), id="stamped-after-publication-counts-from-the-stamp",
        ),
        pytest.param(
            _utc(2026, 11, 1, 3), _utc(2026, 11, 1, 3), _utc(2026, 11, 7), 30, 3,
            _utc(2026, 12, 1, 3), id="an-instant-at-the-hour-rounds-to-that-run",
        ),
        pytest.param(
            _utc(2026, 11, 1, 3, 0, 1), _utc(2026, 11, 1), _utc(2026, 11, 7), 30, 3,
            _utc(2026, 12, 2, 3), id="a-second-past-the-hour-rounds-to-the-next-day",
        ),
        pytest.param(
            _utc(2026, 11, 1), _utc(2026, 11, 1, 10), _utc(2026, 11, 7), 7, 3,
            _utc(2026, 11, 9, 3), id="the-days-follow-the-setting",
        ),
        pytest.param(
            _utc(2026, 11, 1), _utc(2026, 11, 1, 10), _utc(2026, 11, 7), 30, 5,
            _utc(2026, 12, 2, 5), id="the-hour-follows-the-daily-run",
        ),
        pytest.param(
            _utc(2026, 11, 1), None, _utc(2026, 11, 7, 10), 0, 3, _utc(2026, 11, 8, 3),
            id="zero-days-still-wait-for-the-next-run",
        ),
    ],
)
def test_deletes_at_is_the_next_daily_run_after_the_later_instant_plus_the_days(
    unused_since, published, now, days, hour, expected,
) -> None:
    assert reference_deletes_at(unused_since, published, now, days, hour) == expected


def test_a_reference_without_a_stamp_has_no_deletion_date() -> None:
    assert reference_deletes_at(None, None, _utc(2026, 11, 7), 30, 3) is None


# the list

def test_unpublished_the_date_slides_with_now_and_the_epoch_is_the_rows_id(
    signed_in: TestClient,
) -> None:
    seed_reference(signed_in, "owner-id", "old.wav")
    _set_unused_since(signed_in, _only_reference_id(signed_in), unused_since=_utc(2026, 1, 1))
    before = datetime.now(timezone.utc)

    body = _listing(signed_in)

    after = datetime.now(timezone.utc)
    [item] = body["references"]
    deletes_at = datetime.fromisoformat(item["deletes_at"])
    assert deletes_at.utcoffset() == timedelta(0)
    assert (deletes_at.hour, deletes_at.minute, deletes_at.second) == (DAILY_CLEANUP_HOUR_UTC, 0, 0)
    days = timedelta(days=get_settings().final_deletion_days)
    assert before + days <= deletes_at < after + days + timedelta(days=1)
    assert body["countdown_epoch"] == _epoch(signed_in)


def _only_reference_id(client: TestClient) -> str:
    with client.app.state.ctx.db() as session:
        return session.scalars(select(ReferenceRecording.id)).one()


def test_a_kept_or_used_reference_has_no_date_and_no_date_means_no_epoch(
    signed_in: TestClient,
) -> None:
    kept_id = seed_reference(signed_in, "owner-id", "kept.wav")
    used_id = seed_reference(signed_in, "owner-id", "used.wav")
    _set_unused_since(signed_in, kept_id, unused_since=None, is_kept=True)
    _set_unused_since(signed_in, used_id, unused_since=None)

    body = _listing(signed_in)

    assert {item["filename"]: item["deletes_at"] for item in body["references"]} == {
        "kept.wav": None, "used.wav": None,
    }
    assert body["countdown_epoch"] is None


def test_a_reference_linked_between_the_stamp_read_and_the_counts_read_carries_no_date(
    signed_in: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference_id = seed_reference(signed_in, "owner-id", "racing.wav")
    _set_unused_since(signed_in, reference_id, unused_since=_utc(2026, 1, 1))
    real_counts = reference_api.reference_link_counts

    def counts_after_an_attachment(session, reference_ids):
        link_reference(signed_in, reference_id, via="version")
        return real_counts(session, reference_ids)

    monkeypatch.setattr(reference_api, "reference_link_counts", counts_after_an_attachment)

    body = _listing(signed_in)

    [item] = body["references"]
    assert item["in_use"] is True
    assert item["deletes_at"] is None
    assert body["countdown_epoch"] is None


def test_an_empty_list_carries_no_epoch(signed_in: TestClient) -> None:
    body = _listing(signed_in)

    assert body["references"] == []
    assert body["countdown_epoch"] is None


@pytest.mark.parametrize(
    ("unused_since", "published", "expected"),
    [
        pytest.param(
            _utc(2026, 11, 1), "2026-11-05T10:00:00+00:00", "2026-12-06T03:00:00Z",
            id="published-after-the-stamp",
        ),
        pytest.param(
            _utc(2026, 11, 8, 12), "2026-11-05T10:00:00+00:00", "2026-12-09T03:00:00Z",
            id="stamped-after-publication",
        ),
    ],
)
def test_after_publication_the_date_is_fixed_and_does_not_slide_with_now(
    signed_in: TestClient, unused_since: datetime, published: str, expected: str,
) -> None:
    reference_id = seed_reference(signed_in, "owner-id", "ref.wav")
    _set_unused_since(signed_in, reference_id, unused_since=unused_since)
    _set_published_text(signed_in, published)

    first = _listing(signed_in)["references"][0]["deletes_at"]
    second = _listing(signed_in)["references"][0]["deletes_at"]

    assert datetime.fromisoformat(first) == datetime.fromisoformat(expected)
    assert second == first


def test_the_deletion_days_setting_moves_the_date(
    signed_in: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference_id = seed_reference(signed_in, "owner-id", "ref.wav")
    _set_unused_since(signed_in, reference_id, unused_since=_utc(2026, 11, 1))
    _set_published_text(signed_in, "2026-11-05T10:00:00+00:00")
    monkeypatch.setenv("FINAL_DELETION_DAYS", "7")
    get_settings.cache_clear()

    [item] = _listing(signed_in)["references"]

    assert datetime.fromisoformat(item["deletes_at"]) == _utc(2026, 11, 13, 3)


@pytest.mark.parametrize(
    "damage",
    [
        pytest.param(lambda client: _delete_countdown_rows(client), id="missing-row"),
        pytest.param(lambda client: _duplicate_countdown_row(client), id="duplicate-row"),
        pytest.param(
            lambda client: _set_published_text(client, "last-tuesday-ish"), id="malformed-value",
        ),
        pytest.param(
            lambda client: _set_published_text(client, "2026-11-05T10:00:00"),
            id="instant-without-an-offset",
        ),
        pytest.param(
            lambda client: _set_published_text(client, "2026-11-05T10:00:00+02:00"),
            id="instant-in-another-zone",
        ),
    ],
)
def test_an_unusable_countdown_row_fails_the_list_without_logging_content(
    signed_in: TestClient, caplog: pytest.LogCaptureFixture, damage,
) -> None:
    reference_id = seed_reference(signed_in, "owner-id", "secret-take-name.wav")
    _set_unused_since(signed_in, reference_id, unused_since=_utc(2026, 11, 1))
    damage(signed_in)
    owner = signed_in_as(signed_in, "owner")

    with caplog.at_level(logging.ERROR):
        response = owner.get(REFERENCES_PATH)

    assert response.status_code == 500
    logged = " ".join(record.getMessage() for record in caplog.records)
    assert "secret-take-name" not in logged
    assert "last-tuesday-ish" not in logged


def _delete_countdown_rows(client: TestClient) -> None:
    with client.app.state.ctx.db() as session:
        for row in session.scalars(select(RateLimitSetting).where(
            RateLimitSetting.setting_key == SETTING_REFERENCE_COUNTDOWN_VISIBLE_SINCE,
        )):
            session.delete(row)
        session.commit()


def _duplicate_countdown_row(client: TestClient) -> None:
    with client.app.state.ctx.db() as session:
        session.add(RateLimitSetting(
            setting_key=SETTING_REFERENCE_COUNTDOWN_VISIBLE_SINCE, value=0,
        ))
        session.commit()


# the test schema

def test_the_sqlite_test_schema_carries_exactly_one_countdown_row(tmp_path) -> None:
    factory = init_test_db(tmp_path / "schema.db")

    with factory() as session:
        rows = session.scalars(select(RateLimitSetting).where(
            RateLimitSetting.setting_key == SETTING_REFERENCE_COUNTDOWN_VISIBLE_SINCE,
        )).all()

    assert len(rows) == 1
    assert (rows[0].user_id, rows[0].value, rows[0].value_text) == (None, 0, None)


# the acknowledgement

def test_the_first_acknowledgement_publishes_the_servers_instant(signed_in: TestClient) -> None:
    before = datetime.now(timezone.utc)

    response = _post_epoch(signed_in, _epoch(signed_in))

    after = datetime.now(timezone.utc)
    assert response.status_code == 204
    shown = datetime.fromisoformat(_published_text(signed_in))
    assert shown.utcoffset() == timedelta(0)
    assert before <= shown <= after


def test_a_repeated_acknowledgement_answers_204_and_changes_nothing(
    signed_in: TestClient,
) -> None:
    epoch = _epoch(signed_in)
    _post_epoch(signed_in, epoch)
    published = _published_text(signed_in)

    response = _post_epoch(signed_in, epoch)

    assert response.status_code == 204
    assert _published_text(signed_in) == published


def test_a_stale_epoch_answers_409_with_the_named_body_and_writes_nothing(
    signed_in: TestClient,
) -> None:
    response = _post_epoch(signed_in, "an-epoch-from-before-a-rollback")

    assert response.status_code == 409
    assert response.json() == {"detail": STALE_COUNTDOWN_EPOCH_DETAIL}
    assert _published_text(signed_in) is None


def test_an_acknowledgement_without_a_session_is_unauthenticated_and_writes_nothing(
    signed_in: TestClient,
) -> None:
    anonymous = TestClient(signed_in.app, base_url=TEST_ORIGIN, raise_server_exceptions=False)

    response = anonymous.post(
        SHOWN_PATH, json={"epoch": _epoch(signed_in)}, headers={"Sec-Fetch-Site": "same-origin"},
    )

    assert response.status_code == 401
    assert _published_text(signed_in) is None
