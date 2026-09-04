from __future__ import annotations

import base64
import hashlib
import http.client
import json
import os
import re
import ssl
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from requirement_contract import (
    DIGEST,
    EXPECTED_OPERATOR_ID,
    EXPECTED_REPOSITORY_FULL_NAME,
    EXPECTED_REPOSITORY_ID,
    ApprovalWitness,
    RequirementShelf,
    approval_bytes,
    read_approval_witness,
    read_requirement_shelf,
)

API_HOST = "api.github.com"
API_ORIGIN = f"https://{API_HOST}"
HTML_ORIGIN = "https://github.com"
API_VERSION = "2022-11-28"
MAX_API_RESPONSE_BYTES = 256 * 1024
READ_CHUNK_BYTES = 8192
REQUEST_TIMEOUT_SECONDS = 15.0
LIVE_DEADLINE_SECONDS = 120.0
ROUTE = re.compile(
    r"/repos/FlexOr2/songmaker(?:|/issues/[1-9][0-9]*|/issues/comments/[1-9][0-9]*)"
)


class LiveWitnessError(Exception):
    pass


class GitHubClient(Protocol):
    def repository(self, deadline: float) -> dict[str, Any]: ...

    def issue(self, issue_number: int, deadline: float) -> dict[str, Any]: ...

    def comment(self, comment_id: int, deadline: float) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    document: str
    content_sha256: str
    issue_number: int
    comment_id: int

    def __post_init__(self) -> None:
        if re.fullmatch(r"[0-9]{4}", self.document) is None:
            raise LiveWitnessError("approval request has an invalid document id")
        if DIGEST.fullmatch(self.content_sha256) is None:
            raise LiveWitnessError("approval request has an invalid content digest")
        _positive_identifier(self.issue_number, "issue number")
        _positive_identifier(self.comment_id, "comment id")

    @property
    def body(self) -> bytes:
        return approval_bytes(self.document, self.content_sha256)


@dataclass(frozen=True, slots=True)
class CapturedApproval:
    repository_id: int
    repository_full_name: str
    issue_id: int
    issue_number: int
    comment_id: int
    author_id: int
    created_at: str
    updated_at: str
    body: bytes
    body_sha256: str


def canonical_witness_bytes(captured: CapturedApproval) -> bytes:
    payload = {
        "schema_version": 1,
        "repository_id": captured.repository_id,
        "repository_full_name": captured.repository_full_name,
        "issue_id": captured.issue_id,
        "issue_number": captured.issue_number,
        "comment_id": captured.comment_id,
        "author_id": captured.author_id,
        "created_at": captured.created_at,
        "updated_at": captured.updated_at,
        "body_base64": base64.b64encode(captured.body).decode("ascii"),
        "body_sha256": captured.body_sha256,
    }
    try:
        rendered = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (UnicodeEncodeError, ValueError, TypeError) as error:
        raise LiveWitnessError("approval witness cannot be serialized canonically") from error
    return rendered + b"\n"


class HttpsGitHubClient:
    def __init__(
        self,
        token: str,
        *,
        connection_factory: Callable[..., Any] = http.client.HTTPSConnection,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not token:
            raise LiveWitnessError("GITHUB_TOKEN is required for live witness verification")
        self._token = token
        self._connection_factory = connection_factory
        self._clock = clock
        self._context = ssl.create_default_context()
        self._context.check_hostname = True
        self._context.verify_mode = ssl.CERT_REQUIRED

    @classmethod
    def from_environment(cls) -> HttpsGitHubClient:
        return cls(os.environ.get("GITHUB_TOKEN", ""))

    def repository(self, deadline: float) -> dict[str, Any]:
        return self._request("/repos/FlexOr2/songmaker", deadline)

    def issue(self, issue_number: int, deadline: float) -> dict[str, Any]:
        _positive_identifier(issue_number, "issue number")
        return self._request(f"/repos/FlexOr2/songmaker/issues/{issue_number}", deadline)

    def comment(self, comment_id: int, deadline: float) -> dict[str, Any]:
        _positive_identifier(comment_id, "comment id")
        return self._request(f"/repos/FlexOr2/songmaker/issues/comments/{comment_id}", deadline)

    def _request(self, route: str, deadline: float) -> dict[str, Any]:
        if ROUTE.fullmatch(route) is None:
            raise LiveWitnessError("GitHub API route is outside the fixed repository boundary")
        timeout = self._remaining_timeout(deadline)
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self._token}",
            "User-Agent": "songmaker-requirement-witness",
            "X-GitHub-Api-Version": API_VERSION,
        }
        connection = None
        try:
            connection = self._connection_factory(
                API_HOST,
                timeout=timeout,
                context=self._context,
            )
            connection.request("GET", route, headers=headers)
            self._set_socket_timeout(connection, deadline)
            response = connection.getresponse()
            self._set_socket_timeout(connection, deadline)
            if response.status != 200:
                raise LiveWitnessError("GitHub API request failed")
            length = response.getheader("Content-Length")
            if length is not None:
                try:
                    declared_length = int(length)
                except ValueError as error:
                    raise LiveWitnessError(
                        "GitHub API returned an invalid Content-Length"
                    ) from error
                if declared_length < 0 or declared_length > MAX_API_RESPONSE_BYTES:
                    raise LiveWitnessError("GitHub API response exceeds the size limit")
            payload = bytearray()
            while True:
                self._set_socket_timeout(connection, deadline)
                chunk = response.read(
                    min(READ_CHUNK_BYTES, MAX_API_RESPONSE_BYTES + 1 - len(payload))
                )
                if not chunk:
                    break
                payload.extend(chunk)
                if len(payload) > MAX_API_RESPONSE_BYTES:
                    raise LiveWitnessError("GitHub API response exceeds the size limit")
        except LiveWitnessError:
            raise
        except Exception as error:
            raise LiveWitnessError("GitHub API request failed") from error
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception as error:
                    raise LiveWitnessError("GitHub API request failed") from error
        return _api_json(bytes(payload))

    def _remaining_timeout(self, deadline: float) -> float:
        remaining = deadline - self._clock()
        if remaining <= 0:
            raise LiveWitnessError("live witness verification exceeded its total deadline")
        return min(REQUEST_TIMEOUT_SECONDS, remaining)

    def _set_socket_timeout(self, connection: Any, deadline: float) -> None:
        timeout = self._remaining_timeout(deadline)
        if connection.sock is not None:
            connection.sock.settimeout(timeout)


class LiveApprovalCapture:
    def __init__(self, client: GitHubClient, deadline: float) -> None:
        self._client = client
        self._deadline = deadline
        self._repository: dict[str, Any] | None = None
        self._issues: dict[int, dict[str, Any]] = {}

    def capture(self, request: ApprovalRequest) -> CapturedApproval:
        if self._repository is None:
            self._repository = self._client.repository(self._deadline)
            _verify_repository(self._repository)
        issue = self._issues.get(request.issue_number)
        if issue is None:
            issue = self._client.issue(request.issue_number, self._deadline)
            self._issues[request.issue_number] = issue
        comment = self._client.comment(request.comment_id, self._deadline)
        return _capture_approval(issue, comment, request)


def capture_live_approval(
    client: GitHubClient, request: ApprovalRequest, deadline: float
) -> CapturedApproval:
    return LiveApprovalCapture(client, deadline).capture(request)


def verify_live_witnesses(
    project_root: Path,
    client: GitHubClient,
    *,
    shelf: RequirementShelf | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> int:
    active_shelf = shelf or read_requirement_shelf(project_root)
    if not active_shelf.revisions:
        return 0
    capture = LiveApprovalCapture(client, clock() + LIVE_DEADLINE_SECONDS)
    for revision in active_shelf.revisions:
        witness = read_approval_witness(project_root, revision)
        request = ApprovalRequest(
            revision.document,
            revision.content_sha256,
            witness.issue_number,
            witness.comment_id,
        )
        observed = capture.capture(request)
        if observed != _captured_witness(witness):
            raise LiveWitnessError(
                f"live approval {witness.comment_id} does not match its stored witness"
            )
    return len(active_shelf.revisions)


def _verify_repository(raw: dict[str, Any]) -> None:
    expected_api = f"{API_ORIGIN}/repos/{EXPECTED_REPOSITORY_FULL_NAME}"
    expected_html = f"{HTML_ORIGIN}/{EXPECTED_REPOSITORY_FULL_NAME}"
    if (
        _positive_field(raw, "id", "repository") != EXPECTED_REPOSITORY_ID
        or _text_field(raw, "full_name", "repository") != EXPECTED_REPOSITORY_FULL_NAME
        or _text_field(raw, "url", "repository") != expected_api
        or _text_field(raw, "html_url", "repository") != expected_html
    ):
        raise LiveWitnessError("live repository identity does not match the trust anchor")


def _capture_approval(
    issue: dict[str, Any], comment: dict[str, Any], request: ApprovalRequest
) -> CapturedApproval:
    api_repository = f"{API_ORIGIN}/repos/{EXPECTED_REPOSITORY_FULL_NAME}"
    api_issue = f"{api_repository}/issues/{request.issue_number}"
    html_issue = f"{HTML_ORIGIN}/{EXPECTED_REPOSITORY_FULL_NAME}/issues/{request.issue_number}"
    issue_id = _positive_field(issue, "id", "issue")
    if (
        _positive_field(issue, "number", "issue") != request.issue_number
        or _text_field(issue, "repository_url", "issue") != api_repository
        or _text_field(issue, "url", "issue") != api_issue
        or _text_field(issue, "html_url", "issue") != html_issue
    ):
        raise LiveWitnessError(
            f"live issue {request.issue_number} does not match the approval request"
        )
    api_comment = f"{api_repository}/issues/comments/{request.comment_id}"
    html_comment = (
        f"{HTML_ORIGIN}/{EXPECTED_REPOSITORY_FULL_NAME}/issues/{request.issue_number}"
        f"#issuecomment-{request.comment_id}"
    )
    user = comment.get("user")
    if not isinstance(user, dict):
        raise LiveWitnessError(f"live comment {request.comment_id} has no author object")
    body = comment.get("body")
    if not isinstance(body, str):
        raise LiveWitnessError(f"live comment {request.comment_id} has no text body")
    try:
        body_bytes = body.encode("utf-8")
    except UnicodeEncodeError as error:
        raise LiveWitnessError(
            f"live comment {request.comment_id} has an invalid text body"
        ) from error
    created_at = _timestamp_field(comment, "created_at")
    updated_at = _timestamp_field(comment, "updated_at")
    if (
        _positive_field(comment, "id", "comment") != request.comment_id
        or _positive_field(user, "id", "comment author") != EXPECTED_OPERATOR_ID
        or _text_field(comment, "issue_url", "comment") != api_issue
        or _text_field(comment, "url", "comment") != api_comment
        or _text_field(comment, "html_url", "comment") != html_comment
        or body_bytes != request.body
        or created_at != updated_at
    ):
        raise LiveWitnessError(
            f"live comment {request.comment_id} does not match the approval request"
        )
    return CapturedApproval(
        EXPECTED_REPOSITORY_ID,
        EXPECTED_REPOSITORY_FULL_NAME,
        issue_id,
        request.issue_number,
        request.comment_id,
        EXPECTED_OPERATOR_ID,
        created_at,
        updated_at,
        body_bytes,
        hashlib.sha256(body_bytes).hexdigest(),
    )


def _captured_witness(witness: ApprovalWitness) -> CapturedApproval:
    return CapturedApproval(
        witness.repository_id,
        witness.repository_full_name,
        witness.issue_id,
        witness.issue_number,
        witness.comment_id,
        witness.author_id,
        witness.created_at,
        witness.updated_at,
        witness.body,
        witness.body_sha256,
    )


def _positive_identifier(value: int, owner: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise LiveWitnessError(f"invalid {owner}")


def _positive_field(raw: dict[str, Any], field: str, owner: str) -> int:
    value = raw.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise LiveWitnessError(f"live {owner} has invalid {field}")
    return value


def _text_field(raw: dict[str, Any], field: str, owner: str) -> str:
    value = raw.get(field)
    if not isinstance(value, str):
        raise LiveWitnessError(f"live {owner} has invalid {field}")
    return value


def _timestamp_field(raw: dict[str, Any], field: str) -> str:
    value = _text_field(raw, field, "comment")
    if re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", value
    ) is None:
        raise LiveWitnessError(f"live comment has invalid {field}")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise LiveWitnessError(f"live comment has invalid {field}") from error
    return value


def _api_json(payload: bytes) -> dict[str, Any]:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise LiveWitnessError("GitHub API returned non-UTF-8 data") from error

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        parsed: dict[str, Any] = {}
        for key, value in pairs:
            if key in parsed:
                raise LiveWitnessError("GitHub API returned duplicate JSON keys")
            parsed[key] = value
        return parsed

    def reject_constant(_value: str) -> Any:
        raise LiveWitnessError("GitHub API returned an invalid JSON constant")

    try:
        parsed = json.loads(
            text,
            object_pairs_hook=unique_object,
            parse_constant=reject_constant,
        )
    except (json.JSONDecodeError, RecursionError, ValueError) as error:
        raise LiveWitnessError("GitHub API returned malformed JSON") from error
    if not isinstance(parsed, dict):
        raise LiveWitnessError("GitHub API returned a non-object JSON document")
    return parsed
