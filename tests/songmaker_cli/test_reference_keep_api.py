"""POST /api/references/{id}/keep and /unkeep: the owner keeps a reference or lets it go."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from support import reference_api_world
from support.reference_api_world import (
    NOT_FOUND,
    REFERENCES_PATH,
    link_reference,
    reference_rows,
    seed_reference,
    signed_in_as,
)

from songmaker_cli.db.models import AuditLog, ReferenceRecording

signed_in = reference_api_world.signed_in

OLD_STAMP = datetime(2020, 1, 2, 3, 4, 5)


def _seed_kept_case(
    client: TestClient, *, kept: bool = False, stamp: datetime | None = None,
    used: bool = False, owner: str = "owner-id",
) -> str:
    reference_id = seed_reference(client, owner, "ref.wav")
    with client.app.state.ctx.db() as session:
        row = session.get(ReferenceRecording, reference_id)
        row.is_kept = kept
        row.unused_since = stamp
        session.commit()
    if used:
        link_reference(client, reference_id, via="version")
    return reference_id


def _post(client: TestClient, reference_id: str, action: str):
    return client.post(f"{REFERENCES_PATH}/{reference_id}/{action}")


def _kept_and_stamp(client: TestClient, reference_id: str) -> tuple[bool, datetime | None]:
    [row] = [row for row in reference_rows(client) if row.id == reference_id]
    return row.is_kept, row.unused_since


def test_k1_keep_marks_an_unused_stamped_row_kept_and_clears_its_stamp(
    signed_in: TestClient,
) -> None:
    reference_id = _seed_kept_case(signed_in, stamp=OLD_STAMP)

    response = _post(signed_in, reference_id, "keep")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert _kept_and_stamp(signed_in, reference_id) == (True, None)


def test_k2_keep_marks_a_used_row_kept_and_leaves_it_unstamped(signed_in: TestClient) -> None:
    reference_id = _seed_kept_case(signed_in, used=True)

    response = _post(signed_in, reference_id, "keep")

    assert response.status_code == 200
    assert _kept_and_stamp(signed_in, reference_id) == (True, None)


def test_k3_unkeep_of_a_kept_unused_row_starts_a_fresh_countdown(signed_in: TestClient) -> None:
    reference_id = _seed_kept_case(signed_in, kept=True)
    started = datetime.now(timezone.utc).replace(tzinfo=None)

    response = _post(signed_in, reference_id, "unkeep")

    kept, stamp = _kept_and_stamp(signed_in, reference_id)
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert not kept
    assert stamp.replace(tzinfo=None) >= started


def test_k4_unkeep_of_a_kept_used_row_leaves_it_unstamped(signed_in: TestClient) -> None:
    reference_id = _seed_kept_case(signed_in, kept=True, used=True)

    response = _post(signed_in, reference_id, "unkeep")

    assert response.status_code == 200
    assert _kept_and_stamp(signed_in, reference_id) == (False, None)


@pytest.mark.parametrize(
    ("action", "kept", "stamp"),
    [
        pytest.param("keep", True, None, id="keep-of-a-kept-row"),
        pytest.param("unkeep", False, OLD_STAMP, id="unkeep-of-an-unkept-row-keeps-its-stamp"),
        pytest.param("unkeep", False, None, id="unkeep-of-an-unkept-unstamped-row"),
    ],
)
def test_k5_a_repeat_changes_nothing(
    signed_in: TestClient, action: str, kept: bool, stamp: datetime | None,
) -> None:
    reference_id = _seed_kept_case(signed_in, kept=kept, stamp=stamp)

    response = _post(signed_in, reference_id, action)

    assert response.status_code == 200
    assert _kept_and_stamp(signed_in, reference_id) == (kept, stamp)


@pytest.mark.parametrize("who", ["other", "boss", "nobody"])
@pytest.mark.parametrize("action", ["keep", "unkeep"])
def test_k6_a_foreign_or_missing_reference_answers_the_global_404_and_stays(
    signed_in: TestClient, who: str, action: str,
) -> None:
    kept = action == "unkeep"
    reference_id = _seed_kept_case(signed_in, kept=kept, stamp=None if kept else OLD_STAMP)
    target = "no-such-id" if who == "nobody" else reference_id
    caller = signed_in if who == "nobody" else signed_in_as(signed_in, who)

    response = _post(caller, target, action)

    assert response.status_code == 404
    assert response.json() == NOT_FOUND
    assert _kept_and_stamp(signed_in, reference_id) == (kept, None if kept else OLD_STAMP)


@pytest.mark.parametrize("action", ["keep", "unkeep"])
def test_a_keep_or_unkeep_writes_no_audit_record(signed_in: TestClient, action: str) -> None:
    reference_id = _seed_kept_case(signed_in, kept=action == "unkeep")

    _post(signed_in, reference_id, action)

    with signed_in.app.state.ctx.db() as session:
        assert session.query(AuditLog).count() == 0
