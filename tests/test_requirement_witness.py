from __future__ import annotations

import base64
import hashlib
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).parents[1]
SCRIPTS = PROJECT_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import requirement_contract as contract  # noqa: E402
import requirement_witness as live  # noqa: E402


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def document_bytes() -> bytes:
    return (
        "# Albums\n\n## Intent\n\nKeep releases coherent.\n\n## Rules\n\n"
        "### REQ-ALBUM-01: Every song belongs to one album.\n"
        "Quelle: OPERATOR — issue 41\n"
    ).encode()


def witness_bytes(
    content_digest: str,
    repository_full_name: str = contract.EXPECTED_REPOSITORY_FULL_NAME,
) -> bytes:
    body = contract.approval_bytes("0001", content_digest)
    payload = {
        "schema_version": 1,
        "repository_id": contract.EXPECTED_REPOSITORY_ID,
        "repository_full_name": repository_full_name,
        "issue_id": 2001,
        "issue_number": 41,
        "comment_id": 1001,
        "author_id": contract.EXPECTED_OPERATOR_ID,
        "created_at": "2026-08-21T12:00:00Z",
        "updated_at": "2026-08-21T12:00:00Z",
        "body_base64": base64.b64encode(body).decode("ascii"),
        "body_sha256": digest(body),
    }
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()


def project_with_witness(
    tmp_path: Path,
    repository_full_name: str = contract.EXPECTED_REPOSITORY_FULL_NAME,
) -> Path:
    project = tmp_path / "project"
    requirements = project / "docs/requirements"
    witnesses = requirements / "witnesses"
    acceptance = project / "docs/acceptance"
    witnesses.mkdir(parents=True)
    acceptance.mkdir(parents=True)
    content = document_bytes()
    content_digest = digest(content)
    witness = witness_bytes(content_digest, repository_full_name)
    (requirements / "0001-albums.md").write_bytes(content)
    (witnesses / "1001.json").write_bytes(witness)
    (requirements / "revisions.toml").write_text(
        "schema_version = 2\n\n"
        "[[revision]]\n"
        'document = "0001"\n'
        'path = "docs/requirements/0001-albums.md"\n'
        f'content_sha256 = "{content_digest}"\n'
        'witness_path = "docs/requirements/witnesses/1001.json"\n'
        f'witness_sha256 = "{digest(witness)}"\n'
        'predecessor = "GENESIS"\n',
        encoding="utf-8",
    )
    (acceptance / "acceptance.toml").write_text("schema_version = 1\n", encoding="utf-8")
    return project


def empty_project(tmp_path: Path) -> Path:
    project = tmp_path / "empty"
    (project / "docs/requirements").mkdir(parents=True)
    (project / "docs/acceptance").mkdir(parents=True)
    (project / contract.REGISTRY_LOCATION).write_text("schema_version = 2\n", encoding="utf-8")
    (project / contract.ACCEPTANCE_LOCATION).write_text(
        "schema_version = 1\n", encoding="utf-8"
    )
    return project


class FakeClient:
    def __init__(self, mutate: Callable[[str, dict[str, Any]], None] | None = None) -> None:
        self.calls: list[tuple[str, int | None]] = []
        self.mutate = mutate

    def repository(self, _deadline: float) -> dict[str, Any]:
        self.calls.append(("repository", None))
        result = {
            "id": contract.EXPECTED_REPOSITORY_ID,
            "full_name": contract.EXPECTED_REPOSITORY_FULL_NAME,
            "url": f"https://api.github.com/repos/{contract.EXPECTED_REPOSITORY_FULL_NAME}",
            "html_url": f"https://github.com/{contract.EXPECTED_REPOSITORY_FULL_NAME}",
        }
        return self._result("repository", result)

    def issue(self, issue_number: int, _deadline: float) -> dict[str, Any]:
        self.calls.append(("issue", issue_number))
        result = {
            "id": 2001,
            "number": 41,
            "repository_url": f"https://api.github.com/repos/{contract.EXPECTED_REPOSITORY_FULL_NAME}",
            "url": f"https://api.github.com/repos/{contract.EXPECTED_REPOSITORY_FULL_NAME}/issues/41",
            "html_url": f"https://github.com/{contract.EXPECTED_REPOSITORY_FULL_NAME}/issues/41",
        }
        return self._result("issue", result)

    def comment(self, comment_id: int, _deadline: float) -> dict[str, Any]:
        self.calls.append(("comment", comment_id))
        body = contract.approval_bytes("0001", digest(document_bytes())).decode("ascii")
        result = {
            "id": comment_id,
            "user": {"id": contract.EXPECTED_OPERATOR_ID},
            "issue_url": f"https://api.github.com/repos/{contract.EXPECTED_REPOSITORY_FULL_NAME}/issues/41",
            "url": (
                f"https://api.github.com/repos/{contract.EXPECTED_REPOSITORY_FULL_NAME}/issues/comments/"
                f"{comment_id}"
            ),
            "html_url": (
                f"https://github.com/{contract.EXPECTED_REPOSITORY_FULL_NAME}/issues/41#issuecomment-"
                f"{comment_id}"
            ),
            "body": body,
            "created_at": "2026-08-21T12:00:00Z",
            "updated_at": "2026-08-21T12:00:00Z",
        }
        return self._result("comment", result)

    def _result(self, resource: str, result: dict[str, Any]) -> dict[str, Any]:
        if self.mutate is not None:
            self.mutate(resource, result)
        return result


def test_live_verifier_checks_the_complete_identity_chain(tmp_path: Path) -> None:
    project = project_with_witness(tmp_path)
    client = FakeClient()

    assert live.verify_live_witnesses(project, client) == 1
    assert client.calls == [("repository", None), ("issue", 41), ("comment", 1001)]


def test_live_verifier_accepts_a_witness_captured_before_the_organization_rename(
    tmp_path: Path,
) -> None:
    historical_name = next(iter(contract.HISTORICAL_REPOSITORY_FULL_NAMES))

    assert live.verify_live_witnesses(
        project_with_witness(tmp_path, historical_name), FakeClient()
    ) == 1


def test_shared_capture_fetches_repository_once_and_caches_each_issue() -> None:
    client = FakeClient()
    capture = live.LiveApprovalCapture(client, 10**12)
    content_digest = digest(document_bytes())

    first = capture.capture(live.ApprovalRequest("0001", content_digest, 41, 1001))
    second = capture.capture(live.ApprovalRequest("0001", content_digest, 41, 1002))

    assert first.issue_id == second.issue_id == 2001
    assert first.comment_id == 1001
    assert second.comment_id == 1002
    assert client.calls == [
        ("repository", None),
        ("issue", 41),
        ("comment", 1001),
        ("comment", 1002),
    ]


def test_empty_shelf_never_constructs_a_network_dependency(tmp_path: Path) -> None:
    class RefusingClient:
        def __getattr__(self, _name: str) -> Any:
            raise AssertionError("network client must remain unused")

    assert live.verify_live_witnesses(empty_project(tmp_path), RefusingClient()) == 0


@pytest.mark.parametrize(
    ("resource", "mutation", "problem"),
    [
        ("repository", lambda raw: raw.update(id=1), "repository identity"),
        (
            "repository",
            lambda raw: raw.update(url="https://example.test/repo"),
            "repository identity",
        ),
        ("issue", lambda raw: raw.update(id=1), "stored witness"),
        (
            "issue",
            lambda raw: raw.update(repository_url="https://example.test/repo"),
            "approval request",
        ),
        ("comment", lambda raw: raw["user"].update(id=1), "approval request"),
        ("comment", lambda raw: raw.update(body="changed"), "approval request"),
        ("comment", lambda raw: raw.update(body="\ud800"), "invalid text body"),
        (
            "comment",
            lambda raw: raw.update(updated_at="2026-08-21T12:00:01Z"),
            "approval request",
        ),
        (
            "comment",
            lambda raw: raw.update(
                created_at="2026-08-21T12:00:01Z",
                updated_at="2026-08-21T12:00:01Z",
            ),
            "stored witness",
        ),
        (
            "comment",
            lambda raw: raw.update(created_at="not-a-timestamp", updated_at="not-a-timestamp"),
            "invalid created_at",
        ),
        (
            "comment",
            lambda raw: raw.update(issue_url="https://example.test/issue"),
            "approval request",
        ),
    ],
)
def test_live_identity_or_approval_mismatches_fail_closed(
    tmp_path: Path,
    resource: str,
    mutation: Callable[[dict[str, Any]], None],
    problem: str,
) -> None:
    def mutate(selected: str, raw: dict[str, Any]) -> None:
        if selected == resource:
            mutation(raw)

    client = FakeClient(mutate)
    with pytest.raises(live.LiveWitnessError, match=problem):
        live.verify_live_witnesses(project_with_witness(tmp_path), client)


class FakeSocket:
    def __init__(self) -> None:
        self.timeouts: list[float] = []

    def settimeout(self, timeout: float) -> None:
        self.timeouts.append(timeout)


class FakeResponse:
    def __init__(
        self, payload: bytes, *, status: int = 200, content_length: str | None = None
    ) -> None:
        self.status = status
        self.payload = payload
        self.offset = 0
        self.content_length = content_length

    def getheader(self, name: str) -> str | None:
        return self.content_length if name == "Content-Length" else None

    def read(self, amount: int) -> bytes:
        chunk = self.payload[self.offset : self.offset + amount]
        self.offset += len(chunk)
        return chunk


class FakeConnection:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.sock = FakeSocket()
        self.request_args: tuple[Any, ...] | None = None
        self.closed = False

    def request(self, *args: Any, **kwargs: Any) -> None:
        self.request_args = (*args, kwargs)

    def getresponse(self) -> FakeResponse:
        return self.response

    def close(self) -> None:
        self.closed = True


def client_for(
    response: FakeResponse, clock: Callable[[], float] = lambda: 1.0
) -> tuple[live.HttpsGitHubClient, FakeConnection]:
    connection = FakeConnection(response)

    def factory(*_args: Any, **_kwargs: Any) -> FakeConnection:
        return connection

    client = live.HttpsGitHubClient(
        "secret-token", connection_factory=factory, clock=clock
    )
    return client, connection


def test_https_client_uses_only_the_fixed_origin_route_and_headers() -> None:
    payload = b'{"id":1163644113}'
    client, connection = client_for(FakeResponse(payload))

    assert client.repository(10.0) == {"id": contract.EXPECTED_REPOSITORY_ID}
    assert connection.request_args is not None
    method, route, kwargs = connection.request_args
    assert method == "GET"
    assert route == f"/repos/{contract.EXPECTED_REPOSITORY_FULL_NAME}"
    assert kwargs["headers"]["Authorization"] == "Bearer secret-token"
    assert connection.closed is True

    with pytest.raises(live.LiveWitnessError, match="invalid issue number"):
        client.issue(True, 10.0)


@pytest.mark.parametrize(
    ("response", "problem"),
    [
        (FakeResponse(b"{}", status=302), "request failed"),
        (FakeResponse(b"{}", content_length="invalid"), "invalid Content-Length"),
        (
            FakeResponse(b"{}", content_length=str(live.MAX_API_RESPONSE_BYTES + 1)),
            "exceeds the size limit",
        ),
        (FakeResponse(b"x" * (live.MAX_API_RESPONSE_BYTES + 1)), "exceeds the size limit"),
        (FakeResponse(b'{"x":1,"x":2}'), "duplicate JSON keys"),
        (FakeResponse(b'{"x":NaN}'), "invalid JSON constant"),
        (FakeResponse(b"\xff"), "non-UTF-8 data"),
        (FakeResponse(b"{"), "malformed JSON"),
        (FakeResponse(b'{"x":' + b"9" * 5000 + b"}"), "malformed JSON"),
        (
            FakeResponse(b'{"x":' + b"[" * 10_000 + b"0" + b"]" * 10_000 + b"}"),
            "malformed JSON",
        ),
        (FakeResponse(b"[]"), "non-object JSON"),
    ],
)
def test_https_client_rejects_untrusted_or_unbounded_responses(
    response: FakeResponse, problem: str
) -> None:
    client, _connection = client_for(response)

    with pytest.raises(live.LiveWitnessError, match=problem):
        client.repository(10.0)


def test_https_client_enforces_the_shared_monotonic_deadline() -> None:
    client, _connection = client_for(FakeResponse(b"{}"), clock=lambda: 10.0)

    with pytest.raises(live.LiveWitnessError, match="total deadline"):
        client.repository(10.0)


def test_https_client_rechecks_the_deadline_before_each_read() -> None:
    readings = iter((1.0, 1.0, 10.0))
    client, _connection = client_for(FakeResponse(b"{}"), clock=lambda: next(readings))

    with pytest.raises(live.LiveWitnessError, match="total deadline"):
        client.repository(10.0)


def test_https_client_rechecks_the_deadline_after_sending_the_request() -> None:
    readings = iter((1.0, 10.0))
    client, _connection = client_for(FakeResponse(b"{}"), clock=lambda: next(readings))

    with pytest.raises(live.LiveWitnessError, match="total deadline"):
        client.repository(10.0)


def test_https_client_requires_a_token_without_disclosing_it() -> None:
    with pytest.raises(live.LiveWitnessError, match="GITHUB_TOKEN is required") as error:
        live.HttpsGitHubClient("")

    assert "secret" not in str(error.value)


def test_canonical_witness_has_fixed_golden_bytes_and_digest() -> None:
    body = contract.approval_bytes("0001", digest(document_bytes()))
    captured = live.CapturedApproval(
        contract.EXPECTED_REPOSITORY_ID,
        contract.EXPECTED_REPOSITORY_FULL_NAME,
        2001,
        41,
        1001,
        contract.EXPECTED_OPERATOR_ID,
        "2026-08-21T12:00:00Z",
        "2026-08-21T12:00:00Z",
        body,
        digest(body),
    )
    expected = (
        b'{"author_id":44832414,"body_base64":"QVBQUk9WRSBSRVFVSVJFTUVOVCBSRVZJU0lP'
        b'TiAwMDAxIHNoYTI1NjphMjM3YWM5YzA0MTEzNDI0NjRiZjYwMDI3MmM2OWYyNjJkZDZjYzlj'
        b'M2JlZDg1Y2ZhNjk4YTk0NDBhZjZiOTc3","body_sha256":"a4cf4e6ad66c970dbff8a0fbde0'
        b'dc929aed790c54de4d8afecfd3c75cb73a354","comment_id":1001,"created_at":"2026-08-'
        b'21T12:00:00Z","issue_id":2001,"issue_number":41,"repository_full_name":"overnightworks/'
        b'songmaker","repository_id":1163644113,"schema_version":1,"updated_at":"2026-08-'
        b'21T12:00:00Z"}\n'
    )

    rendered = live.canonical_witness_bytes(captured)

    assert rendered == expected
    assert digest(rendered) == "f09355d6f4acbd7204f11f6864c39bd9b5398617a50e5bd5c1c34c9aaee63639"
    assert live.canonical_witness_bytes(captured) == rendered


def test_https_client_sanitizes_transport_failures() -> None:
    def failing_factory(*_args: Any, **_kwargs: Any) -> FakeConnection:
        raise RuntimeError("secret-token and internal transport detail")

    client = live.HttpsGitHubClient("secret-token", connection_factory=failing_factory)

    with pytest.raises(live.LiveWitnessError, match="request failed") as error:
        client.repository(10**12)

    assert "secret-token" not in str(error.value)
