from __future__ import annotations

import http.client
import json
import os
import re
import ssl
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from requirement_contract import (
    EXPECTED_OPERATOR_ID,
    EXPECTED_REPOSITORY_FULL_NAME,
    EXPECTED_REPOSITORY_ID,
    ApprovalWitness,
    RequirementShelf,
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
    deadline = clock() + LIVE_DEADLINE_SECONDS
    repository = client.repository(deadline)
    _verify_repository(repository)
    issue_cache: dict[int, dict[str, Any]] = {}
    for revision in active_shelf.revisions:
        witness = read_approval_witness(project_root, revision)
        issue = issue_cache.get(witness.issue_number)
        if issue is None:
            issue = client.issue(witness.issue_number, deadline)
            _verify_issue(issue, witness)
            issue_cache[witness.issue_number] = issue
        else:
            _verify_issue(issue, witness)
        comment = client.comment(witness.comment_id, deadline)
        _verify_comment(comment, witness)
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


def _verify_issue(raw: dict[str, Any], witness: ApprovalWitness) -> None:
    api_repository = f"{API_ORIGIN}/repos/{EXPECTED_REPOSITORY_FULL_NAME}"
    api_issue = f"{api_repository}/issues/{witness.issue_number}"
    html_issue = f"{HTML_ORIGIN}/{EXPECTED_REPOSITORY_FULL_NAME}/issues/{witness.issue_number}"
    if (
        _positive_field(raw, "id", "issue") != witness.issue_id
        or _positive_field(raw, "number", "issue") != witness.issue_number
        or _text_field(raw, "repository_url", "issue") != api_repository
        or _text_field(raw, "url", "issue") != api_issue
        or _text_field(raw, "html_url", "issue") != html_issue
    ):
        raise LiveWitnessError(
            f"live issue {witness.issue_number} does not match its witness"
        )


def _verify_comment(raw: dict[str, Any], witness: ApprovalWitness) -> None:
    api_repository = f"{API_ORIGIN}/repos/{EXPECTED_REPOSITORY_FULL_NAME}"
    api_issue = f"{api_repository}/issues/{witness.issue_number}"
    api_comment = f"{api_repository}/issues/comments/{witness.comment_id}"
    html_comment = (
        f"{HTML_ORIGIN}/{EXPECTED_REPOSITORY_FULL_NAME}/issues/{witness.issue_number}"
        f"#issuecomment-{witness.comment_id}"
    )
    user = raw.get("user")
    if not isinstance(user, dict):
        raise LiveWitnessError(f"live comment {witness.comment_id} has no author object")
    body = raw.get("body")
    if not isinstance(body, str):
        raise LiveWitnessError(f"live comment {witness.comment_id} has no text body")
    try:
        body_bytes = body.encode("utf-8")
    except UnicodeEncodeError as error:
        raise LiveWitnessError(
            f"live comment {witness.comment_id} has an invalid text body"
        ) from error
    created_at = _text_field(raw, "created_at", "comment")
    updated_at = _text_field(raw, "updated_at", "comment")
    if (
        _positive_field(raw, "id", "comment") != witness.comment_id
        or _positive_field(user, "id", "comment author") != EXPECTED_OPERATOR_ID
        or _text_field(raw, "issue_url", "comment") != api_issue
        or _text_field(raw, "url", "comment") != api_comment
        or _text_field(raw, "html_url", "comment") != html_comment
        or body_bytes != witness.body
        or created_at != witness.created_at
        or updated_at != witness.updated_at
        or created_at != updated_at
    ):
        raise LiveWitnessError(
            f"live comment {witness.comment_id} does not match its unedited witness"
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
