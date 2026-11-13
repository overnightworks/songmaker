"""References and jobs refuse with a catalog key, and a foreign resource reads as a missing one."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from support import reference_api_world
from support.reference_api_world import (
    REFERENCES_PATH,
    post_reference,
    seed_reference,
    signed_in_as,
)
from support.web_app import make_test_app, refusal_body, seed_session

from songmaker_cli.db.models import User
from songmaker_cli.db.queries.jobs import JobStatusUpdate, create_job, update_job_status
from songmaker_cli.job_types import JobStatus, JobType
from songmaker_cli.words import Key

signed_in = reference_api_world.signed_in

MISSING_ID = "no-such-id"
OWNER = "owner-id"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", f"{REFERENCES_PATH}/{{}}/uses"),
        ("delete", f"{REFERENCES_PATH}/{{}}"),
        ("post", f"{REFERENCES_PATH}/{{}}/keep"),
        ("post", f"{REFERENCES_PATH}/{{}}/unkeep"),
    ],
    ids=["uses", "delete", "keep", "unkeep"],
)
def test_a_foreign_reference_answers_the_body_of_a_missing_one(
    signed_in: TestClient, method: str, path: str,
) -> None:
    reference_id = seed_reference(signed_in, OWNER, "ref.wav")
    stranger = signed_in_as(signed_in, "other")

    foreign = getattr(stranger, method)(path.format(reference_id))
    missing = getattr(stranger, method)(path.format(MISSING_ID))

    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json() == refusal_body("referenceRefusal.notFound")
    assert foreign.json()["detail"] == "Not Found"


@pytest.mark.parametrize(
    ("name", "payload", "key", "values"),
    [
        ("a" * 300 + ".wav", b"x" * 200, "referenceRefusal.filenameTooLong", {"max": "255"}),
        ("ref.txt", b"x" * 200, "referenceRefusal.formatUnsupported", {
            "extension": ".txt", "accepted": ".flac, .mp3, .ogg, .wav",
        }),
        ("ref.wav", b"x" * 99, "referenceRefusal.fileTooSmall", {}),
    ],
    ids=["name-too-long", "format-unsupported", "file-too-small"],
)
def test_an_upload_that_cannot_be_stored_is_refused_with_its_key(
    signed_in: TestClient, name: str, payload: bytes, key: Key, values: dict[str, str],
) -> None:
    response = post_reference(signed_in, payload, name)

    assert response.status_code == 400
    assert response.json() == refusal_body(key, **values)


@pytest.fixture
def member_client(tmp_path, pg_factory) -> tuple[TestClient, dict[str, str]]:
    """A signed-in member and the ids of a foreign job, an admin-only job and a finished job."""
    jobs: dict[str, str] = {}

    def seed(session) -> None:
        session.add_all([
            User(id="member-id", username="member", role="user"),
            User(id="other-id", username="other", role="user"),
        ])
        session.flush()
        jobs["foreign"] = create_job(session, JobType.GENERATE, user_id="other-id").id
        jobs["admin-only"] = create_job(
            session, JobType.LOAD_MODEL_ON_WORKER, user_id="member-id",
        ).id
        jobs["finished"] = create_job(session, JobType.GENERATE, user_id="member-id").id
        update_job_status(
            session, jobs["finished"], JobStatusUpdate(JobStatus.COMPLETED, progress=1.0),
        )

    client, _ = make_test_app(tmp_path, factory=pg_factory, seed_db=seed)
    seed_session(client, "member")
    return client, jobs


@pytest.mark.parametrize("which", ["foreign", "admin-only"])
@pytest.mark.parametrize("method", ["get", "post"])
def test_a_job_the_member_may_not_reach_answers_the_body_of_a_missing_one(
    member_client: tuple[TestClient, dict[str, str]], which: str, method: str,
) -> None:
    client, jobs = member_client
    suffix = "" if method == "get" else "/cancel"

    unreachable = getattr(client, method)(f"/api/jobs/{jobs[which]}{suffix}")
    missing = getattr(client, method)(f"/api/jobs/{MISSING_ID}{suffix}")

    assert unreachable.status_code == missing.status_code == 404
    assert unreachable.json() == missing.json() == refusal_body("jobRefusal.notFound")


def test_cancelling_a_finished_job_is_refused_with_its_key(
    member_client: tuple[TestClient, dict[str, str]],
) -> None:
    client, jobs = member_client

    response = client.post(f"/api/jobs/{jobs['finished']}/cancel")

    assert response.status_code == 409
    assert response.json() == refusal_body("jobRefusal.notCancellable")
