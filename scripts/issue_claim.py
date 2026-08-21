"""Coordinate Songmaker build claims through a repository-wide GitHub ledger."""

from __future__ import annotations

import argparse
import json
import os
import re
import selectors
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Protocol

CLAIM_LABEL_PREFIX = "claimed:"
LEDGER_ISSUE = 71
LEGACY_MARKER_PREFIX = "<!-- songmaker-claim:v1 "
MARKER_PREFIX = "<!-- songmaker-claim:v2 "
MARKER_SUFFIX = " -->"
PROJECTION_MARKER_PREFIX = "<!-- songmaker-claim-projection:v1 ledger="
PROJECTION_MARKER_PATTERN = re.compile(
    rf"{re.escape(PROJECTION_MARKER_PREFIX)}(?P<ledger>[1-9][0-9]*){re.escape(MARKER_SUFFIX)}"
)
TRUSTED_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})
CLAIM_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
BRANCH_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,254}")
REPOSITORY_PATTERN = re.compile(
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9_.-]{1,100}"
)
TIMESTAMP_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
COMMENTS_PER_PAGE = 100
MAX_LEDGER_PAGES = 100
LEDGER_ROLLOVER_WARNING_PAGES = 80
MAX_PROTOCOL_EVENTS = 4096
MAX_PROTOCOL_BYTES = 8 * 1024 * 1024
MAX_COMMAND_OUTPUT_BYTES = 8 * 1024 * 1024
MAX_COMMENT_BYTES = 48 * 1024
MAX_SCOPE_ENTRIES = 256
MAX_SCOPE_PATH_LENGTH = 512
GH_TIMEOUT_SECONDS = 60


class ClaimError(RuntimeError):
    pass


class ClaimUnavailable(ClaimError):
    pass


class InvalidClaimMarker(ClaimError):
    pass


@dataclass(frozen=True)
class IssueComment:
    identifier: int
    created_at: str
    updated_at: str
    body: str
    author_association: str
    url: str


@dataclass(frozen=True)
class ActiveClaim:
    issue: int
    claim_id: str
    agent: str
    role: str
    base: str
    branch: str
    scope: tuple[str, ...]
    comment: IssueComment


@dataclass(frozen=True)
class ClaimantRelease:
    issue: int
    claim_id: str
    agent: str
    role: str
    reason: str
    comment: IssueComment


@dataclass(frozen=True)
class OverrideRelease:
    issue: int
    claim_id: str
    agent: str
    role: str
    reason: str
    claim_comment_id: int
    comment: IssueComment


@dataclass(frozen=True)
class LedgerSupersede:
    issue: int
    claim_id: str
    agent: str
    role: str
    reason: str
    claim_comment_id: int
    successor_issue: int
    comment: IssueComment


ClaimEvent = ActiveClaim | ClaimantRelease | OverrideRelease | LedgerSupersede


class LedgerSuperseded(ClaimError):
    def __init__(self, successor_issue: int, claim: ActiveClaim):
        self.successor_issue = successor_issue
        self.claim = claim
        super().__init__(
            f"claim ledger #{LEDGER_ISSUE} is frozen; update and use "
            f"successor #{successor_issue}"
        )


@dataclass(frozen=True)
class ClaimRequest:
    issue: int
    agent: str
    role: str
    base: str
    branch: str
    scope: tuple[str, ...]
    claim_id: str


class IssueComments(Protocol):
    def list_protocol_candidates(self, issue: int) -> tuple[IssueComment, ...]: ...

    def post_comment(self, issue: int, body: str) -> str: ...

    def add_label(self, issue: int, label: str) -> None: ...

    def remove_label(self, issue: int, label: str) -> None: ...

    def list_claimed_issues(self) -> tuple[int, ...]: ...

    def validate_successor(self, issue: int) -> None: ...

    def upsert_projection(
        self,
        issue: int,
        body: str,
        *,
        create: bool = True,
        adopt_stale: bool = False,
    ) -> bool: ...


def claim_label(ledger_issue: int | None = None) -> str:
    return f"{CLAIM_LABEL_PREFIX}{ledger_issue or LEDGER_ISSUE}"


def _projection_marker(ledger_issue: int | None = None) -> str:
    return f"{PROJECTION_MARKER_PREFIX}{ledger_issue or LEDGER_ISSUE}{MARKER_SUFFIX}"


def _projection_ledger(comment: IssueComment) -> int | None:
    match = PROJECTION_MARKER_PATTERN.fullmatch(comment.body.partition("\n")[0])
    return int(match["ledger"]) if match is not None else None


def _required_text(
    payload: dict[str, object], key: str, *, maximum: int = 512
) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise InvalidClaimMarker(f"claim marker field {key!r} must be text")
    normalized = value.strip()
    if (
        not normalized
        or normalized != value
        or len(normalized) > maximum
        or any(ord(character) < 32 or ord(character) == 127 for character in normalized)
    ):
        raise InvalidClaimMarker(
            f"claim marker field {key!r} must be one bounded non-empty line"
        )
    return normalized


def _outbound_text(value: object, field: str, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise ClaimError(f"{field} must be text")
    normalized = value.strip()
    if (
        not normalized
        or normalized != value
        or len(normalized) > maximum
        or any(ord(character) < 32 or ord(character) == 127 for character in normalized)
    ):
        raise ClaimError(f"{field} must be one bounded non-empty line")
    return normalized


def _required_issue(payload: dict[str, object]) -> int:
    issue = payload.get("issue")
    if isinstance(issue, bool) or not isinstance(issue, int) or issue < 1:
        raise InvalidClaimMarker("claim marker issue must be a positive integer")
    return issue


def _valid_branch(payload: dict[str, object]) -> str:
    branch = _required_text(payload, "branch", maximum=255)
    segments = branch.split("/")
    if (
        BRANCH_PATTERN.fullmatch(branch) is None
        or branch.startswith("-")
        or branch.endswith(("/", "."))
        or ".." in branch
        or "//" in branch
        or "@{" in branch
        or any(
            not segment
            or segment.startswith(".")
            or segment.endswith((".", ".lock"))
            for segment in segments
        )
    ):
        raise InvalidClaimMarker(f"claim marker branch is not a safe Git ref: {branch!r}")
    return branch


def _valid_scope(scope: object) -> tuple[str, ...]:
    if not isinstance(scope, list) or not scope:
        raise InvalidClaimMarker("claim marker scope must be a non-empty list")
    if len(scope) > MAX_SCOPE_ENTRIES:
        raise InvalidClaimMarker(
            f"claim marker scope exceeds {MAX_SCOPE_ENTRIES} entries"
        )
    result: list[str] = []
    for raw_path in scope:
        if not isinstance(raw_path, str):
            raise InvalidClaimMarker("claim scope entries must be text")
        path = raw_path.strip()
        if (
            not path
            or path != raw_path
            or len(path) > MAX_SCOPE_PATH_LENGTH
            or "\\" in path
            or any(ord(character) < 32 or ord(character) == 127 for character in path)
        ):
            raise InvalidClaimMarker("claim scope entries must be canonical bounded paths")
        parsed = PurePosixPath(path)
        windows_path = PureWindowsPath(path)
        if (
            path == "."
            or parsed.is_absolute()
            or windows_path.drive
            or windows_path.root
            or ".." in parsed.parts
            or path.startswith("~")
            or not parsed.parts
            or parsed.parts[0] == ".git"
            or str(parsed) != path
        ):
            raise InvalidClaimMarker(f"claim scope must be repository-relative: {path!r}")
        result.append(path)
    if len(set(result)) != len(result):
        raise InvalidClaimMarker("claim scope contains duplicate paths")
    return tuple(result)


def _strict_keys(
    payload: dict[str, object], expected: frozenset[str], comment: IssueComment
) -> None:
    observed = frozenset(payload)
    if observed != expected:
        raise InvalidClaimMarker(
            f"trusted comment {comment.url} claim fields differ: "
            f"expected {sorted(expected)}, got {sorted(observed)}"
        )


def is_protocol_candidate(comment: IssueComment) -> bool:
    first_line = comment.body.partition("\n")[0]
    return comment.author_association in TRUSTED_ASSOCIATIONS and first_line.startswith(
        (LEGACY_MARKER_PREFIX, MARKER_PREFIX)
    )


def _marker_payload(comment: IssueComment) -> tuple[dict[str, object], bool] | None:
    if not is_protocol_candidate(comment):
        return None
    first_line = comment.body.partition("\n")[0]
    legacy = first_line.startswith(LEGACY_MARKER_PREFIX)
    prefix = LEGACY_MARKER_PREFIX if legacy else MARKER_PREFIX
    if not first_line.startswith(prefix):
        return None
    if comment.created_at != comment.updated_at:
        raise InvalidClaimMarker(
            f"trusted protocol comment {comment.url} was edited after publication"
        )
    if not first_line.endswith(MARKER_SUFFIX):
        raise InvalidClaimMarker(
            f"trusted comment {comment.url} has an unterminated claim marker"
        )
    encoded = first_line[len(prefix) : -len(MARKER_SUFFIX)]
    try:
        payload = json.loads(encoded)
    except json.JSONDecodeError as error:
        raise InvalidClaimMarker(
            f"trusted comment {comment.url} has invalid claim JSON"
        ) from error
    if not isinstance(payload, dict):
        raise InvalidClaimMarker(
            f"trusted comment {comment.url} claim payload must be an object"
        )
    return payload, legacy


def _event_identity(
    payload: dict[str, object], comment: IssueComment
) -> tuple[str, str, str]:
    claim_id = _required_text(payload, "claim_id", maximum=128)
    agent = _required_text(payload, "agent", maximum=128)
    role = _required_text(payload, "role", maximum=64)
    visible_lines = [line for line in comment.body.splitlines() if line.strip()]
    if not visible_lines or visible_lines[-1] != f"Agent: {agent} ({role})":
        raise InvalidClaimMarker(
            f"trusted protocol comment {comment.url} lacks its exact agent attribution"
        )
    if CLAIM_ID_PATTERN.fullmatch(claim_id) is None:
        raise InvalidClaimMarker(f"trusted comment {comment.url} has an invalid claim id")
    return claim_id, agent, role


def _parse_active_claim(
    payload: dict[str, object], comment: IssueComment, issue: int, *, legacy: bool
) -> ActiveClaim:
    expected = {"action", "agent", "base", "branch", "claim_id", "role", "scope"}
    if not legacy:
        expected.add("issue")
    _strict_keys(payload, frozenset(expected), comment)
    claim_id, agent, role = _event_identity(payload, comment)
    base = _required_text(payload, "base", maximum=40)
    if COMMIT_PATTERN.fullmatch(base) is None:
        raise InvalidClaimMarker(
            f"trusted comment {comment.url} base must be a full lowercase commit SHA"
        )
    return ActiveClaim(
        issue=issue,
        claim_id=claim_id,
        agent=agent,
        role=role,
        base=base,
        branch=_valid_branch(payload),
        scope=_valid_scope(payload.get("scope")),
        comment=comment,
    )


def _parse_claimant_release(
    payload: dict[str, object], comment: IssueComment, issue: int, *, legacy: bool
) -> ClaimantRelease:
    expected = {"action", "agent", "claim_id", "reason", "role"}
    if not legacy:
        expected.add("issue")
    _strict_keys(payload, frozenset(expected), comment)
    claim_id, agent, role = _event_identity(payload, comment)
    return ClaimantRelease(
        issue=issue,
        claim_id=claim_id,
        agent=agent,
        role=role,
        reason=_required_text(payload, "reason", maximum=512),
        comment=comment,
    )


def _required_comment_id(payload: dict[str, object], *, action: str) -> int:
    raw_comment_id = payload.get("claim_comment_id")
    if (
        isinstance(raw_comment_id, bool)
        or not isinstance(raw_comment_id, int)
        or raw_comment_id < 1
    ):
        raise InvalidClaimMarker(f"{action} requires a positive claim comment id")
    return raw_comment_id


def _parse_override_release(
    payload: dict[str, object], comment: IssueComment, issue: int
) -> OverrideRelease:
    _strict_keys(
        payload,
        frozenset(
            {
                "action",
                "agent",
                "claim_comment_id",
                "claim_id",
                "issue",
                "reason",
                "role",
            }
        ),
        comment,
    )
    claim_id, agent, role = _event_identity(payload, comment)
    if role != "coordinator":
        raise InvalidClaimMarker("override releases require coordinator role")
    return OverrideRelease(
        issue=issue,
        claim_id=claim_id,
        agent=agent,
        role=role,
        reason=_required_text(payload, "reason", maximum=512),
        claim_comment_id=_required_comment_id(payload, action="override releases"),
        comment=comment,
    )


def _parse_ledger_supersede(
    payload: dict[str, object], comment: IssueComment, issue: int
) -> LedgerSupersede:
    _strict_keys(
        payload,
        frozenset(
            {
                "action",
                "agent",
                "claim_comment_id",
                "claim_id",
                "issue",
                "reason",
                "role",
                "successor_issue",
            }
        ),
        comment,
    )
    claim_id, agent, role = _event_identity(payload, comment)
    if role != "coordinator":
        raise InvalidClaimMarker("ledger supersede requires coordinator role")
    successor_issue = payload.get("successor_issue")
    if (
        isinstance(successor_issue, bool)
        or not isinstance(successor_issue, int)
        or successor_issue < 1
        or successor_issue <= LEDGER_ISSUE
    ):
        raise InvalidClaimMarker("ledger successor must be greater than the current ledger")
    return LedgerSupersede(
        issue=issue,
        claim_id=claim_id,
        agent=agent,
        role=role,
        reason=_required_text(payload, "reason", maximum=512),
        claim_comment_id=_required_comment_id(payload, action="ledger supersede"),
        successor_issue=successor_issue,
        comment=comment,
    )


def parse_claim_event(comment: IssueComment) -> ClaimEvent | None:
    parsed_marker = _marker_payload(comment)
    if parsed_marker is None:
        return None
    payload, legacy = parsed_marker
    action = _required_text(payload, "action", maximum=32)
    if action not in {"claim", "release", "override_release", "supersede"}:
        raise InvalidClaimMarker(
            f"trusted comment {comment.url} has unknown action {action!r}"
        )

    if legacy:
        if action not in {"claim", "release"}:
            raise InvalidClaimMarker("legacy claim markers cannot use this action")
        issue = LEDGER_ISSUE
    else:
        issue = _required_issue(payload)
    if action == "claim":
        return _parse_active_claim(payload, comment, issue, legacy=legacy)
    if action == "release":
        return _parse_claimant_release(payload, comment, issue, legacy=legacy)
    if action == "override_release":
        return _parse_override_release(payload, comment, issue)
    return _parse_ledger_supersede(payload, comment, issue)


def _apply_terminal_event(
    event: ClaimantRelease | OverrideRelease | LedgerSupersede,
    active: dict[str, ActiveClaim],
    acquired: dict[str, ActiveClaim],
) -> None:
    claimed = acquired.get(event.claim_id)
    if isinstance(event, LedgerSupersede):
        if (
            claimed is None
            or claimed.issue != event.issue
            or claimed.issue != LEDGER_ISSUE
            or event.claim_comment_id != claimed.comment.identifier
            or set(active) != {claimed.claim_id}
        ):
            return
        raise LedgerSuperseded(event.successor_issue, claimed)
    if claimed is None:
        raise InvalidClaimMarker(
            f"claim id {event.claim_id!r} was released before it was acquired"
        )
    if claimed.issue != event.issue:
        raise InvalidClaimMarker(
            f"claim id {event.claim_id!r} release targets the wrong issue"
        )
    if isinstance(event, ClaimantRelease):
        if (claimed.agent, claimed.role) != (event.agent, event.role):
            raise InvalidClaimMarker(
                f"claim id {event.claim_id!r} can only be released by its claimant"
            )
    elif event.claim_comment_id != claimed.comment.identifier:
        raise InvalidClaimMarker(
            f"claim id {event.claim_id!r} terminal event targets the wrong claim comment"
        )
    active.pop(event.claim_id, None)


def active_claims(comments: tuple[IssueComment, ...]) -> tuple[ActiveClaim, ...]:
    active: dict[str, ActiveClaim] = {}
    acquired: dict[str, ActiveClaim] = {}
    seen_claim_ids: set[str] = set()
    ordered = sorted(comments, key=lambda comment: (comment.created_at, comment.identifier))
    for comment in ordered:
        event = parse_claim_event(comment)
        if event is None:
            continue
        if isinstance(event, ActiveClaim):
            if event.claim_id in seen_claim_ids:
                raise InvalidClaimMarker(f"claim id {event.claim_id!r} was reused")
            seen_claim_ids.add(event.claim_id)
            acquired[event.claim_id] = event
            active[event.claim_id] = event
            continue
        _apply_terminal_event(event, active, acquired)

    return tuple(
        sorted(
            active.values(),
            key=lambda event: (event.comment.created_at, event.comment.identifier),
        )
    )


def _scope_prefixes(paths: tuple[str, ...]) -> set[tuple[str, ...]]:
    prefixes: set[tuple[str, ...]] = set()
    for path in paths:
        parts = PurePosixPath(path).parts
        prefixes.update(parts[:length] for length in range(1, len(parts) + 1))
    return prefixes


def _scopes_overlap(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
    left_paths = {PurePosixPath(path).parts for path in left}
    right_paths = {PurePosixPath(path).parts for path in right}
    return bool(
        left_paths.intersection(_scope_prefixes(right))
        or right_paths.intersection(_scope_prefixes(left))
    )


def claims_conflict(left: ActiveClaim | ClaimRequest, right: ActiveClaim | ClaimRequest) -> bool:
    if left.issue == right.issue:
        return True
    return _scopes_overlap(left.scope, right.scope)


def conflicting_claims(
    claims: tuple[ActiveClaim, ...], candidate: ActiveClaim | ClaimRequest
) -> tuple[ActiveClaim, ...]:
    return tuple(
        claim
        for claim in claims
        if claim.claim_id != candidate.claim_id and claims_conflict(claim, candidate)
    )


@dataclass(frozen=True)
class ClaimConflictIndex:
    conflict_ids: set[str]
    claims_by_issue: dict[int, set[str]]
    complete_paths: dict[tuple[str, ...], set[str]]
    descendant_paths: dict[tuple[str, ...], set[str]]


def _claim_conflict_index(claims: tuple[ActiveClaim, ...]) -> ClaimConflictIndex:
    """Index active-claim paths once for conflict status and targeted lookup."""
    conflict_ids: set[str] = set()
    claims_by_issue: dict[int, set[str]] = {}
    complete_paths: dict[tuple[str, ...], set[str]] = {}
    descendant_paths: dict[tuple[str, ...], set[str]] = {}

    for claim in claims:
        same_issue = claims_by_issue.setdefault(claim.issue, set())
        if same_issue:
            conflict_ids.add(claim.claim_id)
            conflict_ids.update(same_issue)
        same_issue.add(claim.claim_id)

        for path in claim.scope:
            parts = PurePosixPath(path).parts
            matches = set(descendant_paths.get(parts, ()))
            for length in range(1, len(parts) + 1):
                matches.update(complete_paths.get(parts[:length], ()))
            matches.discard(claim.claim_id)
            if matches:
                conflict_ids.add(claim.claim_id)
                conflict_ids.update(matches)

            complete_paths.setdefault(parts, set()).add(claim.claim_id)
            for length in range(1, len(parts) + 1):
                descendant_paths.setdefault(parts[:length], set()).add(claim.claim_id)

    return ClaimConflictIndex(
        conflict_ids,
        claims_by_issue,
        complete_paths,
        descendant_paths,
    )


def _related_claim_ids(
    index: ClaimConflictIndex, selected: tuple[ActiveClaim, ...]
) -> set[str]:
    related = {claim.claim_id for claim in selected}
    for claim in selected:
        related.update(index.claims_by_issue[claim.issue])
        for path in claim.scope:
            parts = PurePosixPath(path).parts
            related.update(index.descendant_paths.get(parts, ()))
            for length in range(1, len(parts) + 1):
                related.update(index.complete_paths.get(parts[:length], ()))
    return related


def _marker(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return f"{MARKER_PREFIX}{encoded}{MARKER_SUFFIX}"


def _validated_comment(body: str) -> str:
    if "\x00" in body:
        raise ClaimError("GitHub comment body contains a NUL byte")
    size = len(body.encode("utf-8"))
    if size > MAX_COMMENT_BYTES:
        raise ClaimError(
            f"GitHub comment body exceeds the {MAX_COMMENT_BYTES}-byte safety limit"
        )
    return body


def claim_comment(request: ClaimRequest) -> str:
    agent = _outbound_text(request.agent, "agent", maximum=128)
    role = _outbound_text(request.role, "role", maximum=64)
    payload: dict[str, object] = {
        "action": "claim",
        "agent": agent,
        "base": request.base,
        "branch": request.branch,
        "claim_id": request.claim_id,
        "issue": request.issue,
        "role": role,
        "scope": list(request.scope),
    }
    scope = "\n".join(f"- `{path}`" for path in request.scope)
    return _validated_comment(
        f"{_marker(payload)}\n"
        "## CLAIM — exclusive build lane\n\n"
        f"- Issue: #{request.issue}\n"
        f"- Owner: {agent} ({role})\n"
        f"- Base: `{request.base}`\n"
        f"- Branch: `{request.branch}`\n"
        f"- Claim ID: `{request.claim_id}`\n"
        "- Write scope:\n"
        f"{scope}\n\n"
        "Repository-wide ledger event. No edit starts before this claim is re-read live. "
        "Read-only review remains parallel. No Auto-Runner.\n\n"
        f"Agent: {agent} ({role})"
    )


def release_comment(
    claim: ActiveClaim,
    agent: str,
    role: str,
    reason: str,
    *,
    coordinator_override: bool = False,
) -> str:
    validated_agent = _outbound_text(agent, "agent", maximum=128)
    validated_role = _outbound_text(role, "role", maximum=64)
    validated_reason = _outbound_text(reason, "reason", maximum=512)
    action = "override_release" if coordinator_override else "release"
    payload: dict[str, object] = {
        "action": action,
        "agent": validated_agent,
        "claim_id": claim.claim_id,
        "issue": claim.issue,
        "reason": validated_reason,
        "role": validated_role,
    }
    if coordinator_override:
        payload["claim_comment_id"] = claim.comment.identifier
    return _validated_comment(
        f"{_marker(payload)}\n"
        "## RELEASE — build lane\n\n"
        f"- Issue: #{claim.issue}\n"
        f"- Claim ID: `{claim.claim_id}`\n"
        f"- Previous owner: {claim.agent} ({claim.role})\n"
        f"- Released by: {validated_agent} ({validated_role})\n"
        f"- Reason: {validated_reason}\n\n"
        f"Agent: {validated_agent} ({validated_role})"
    )


def supersede_comment(
    claim: ActiveClaim,
    successor_issue: int,
    agent: str,
    role: str,
    reason: str,
) -> str:
    if successor_issue <= LEDGER_ISSUE:
        raise ClaimError("ledger successor must be greater than the current ledger")
    validated_agent = _outbound_text(agent, "agent", maximum=128)
    validated_role = _outbound_text(role, "role", maximum=64)
    validated_reason = _outbound_text(reason, "reason", maximum=512)
    payload: dict[str, object] = {
        "action": "supersede",
        "agent": validated_agent,
        "claim_comment_id": claim.comment.identifier,
        "claim_id": claim.claim_id,
        "issue": claim.issue,
        "reason": validated_reason,
        "role": validated_role,
        "successor_issue": successor_issue,
    }
    return _validated_comment(
        f"{_marker(payload)}\n"
        "## SUPERSEDE — claim ledger frozen\n\n"
        f"- Ledger: #{LEDGER_ISSUE}\n"
        f"- Successor: #{successor_issue}\n"
        f"- Rollover claim: `{claim.claim_id}`\n"
        f"- Frozen by: {validated_agent} ({validated_role})\n"
        f"- Reason: {validated_reason}\n\n"
        "This terminal event rejects every later operation through helpers that still "
        "target this ledger. Update before coordinating more work.\n\n"
        f"Agent: {validated_agent} ({validated_role})"
    )


def _active_projection(claim: ActiveClaim) -> str:
    return _validated_comment(
        f"{_projection_marker()}\n"
        f"🔒 **Claimed** · {claim.agent} ({claim.role}) · `{claim.branch}`\n\n"
        f"[Ledger details]({claim.comment.url})"
    )


def _unclaimed_projection(
    ledger_url: str | None = None, reason: str | None = None
) -> str:
    detail = f" · {reason}" if reason else ""
    ledger = f"[Ledger]({ledger_url})" if ledger_url else f"Ledger: #{LEDGER_ISSUE}"
    return _validated_comment(
        f"{_projection_marker()}\n"
        f"🔓 **Unclaimed**{detail}\n\n"
        f"{ledger}"
    )


def _ledger_claims(client: IssueComments) -> tuple[ActiveClaim, ...]:
    return active_claims(client.list_protocol_candidates(LEDGER_ISSUE))


def _issue_claim(claims: tuple[ActiveClaim, ...], issue: int) -> ActiveClaim | None:
    matching = tuple(claim for claim in claims if claim.issue == issue)
    if not matching:
        return None
    return min(
        matching,
        key=lambda claim: (claim.comment.created_at, claim.comment.identifier),
    )


def _apply_issue_projection(
    client: IssueComments,
    issue: int,
    claim: ActiveClaim | None,
    *,
    unclaimed_body: str | None = None,
) -> None:
    if issue == LEDGER_ISSUE:
        return
    if claim is None:
        client.upsert_projection(
            issue,
            unclaimed_body or _unclaimed_projection(),
            create=False,
        )
        return
    client.upsert_projection(
        issue,
        _active_projection(claim),
        adopt_stale=True,
    )


def reconcile_issue_label(
    client: IssueComments,
    issue: int,
    *,
    unclaimed_body: str | None = None,
) -> None:
    for _ in range(3):
        try:
            expected = _issue_claim(_ledger_claims(client), issue)
        except LedgerSuperseded:
            client.remove_label(issue, claim_label())
            raise
        _apply_issue_projection(
            client,
            issue,
            expected,
            unclaimed_body=unclaimed_body,
        )
        if expected is not None:
            client.add_label(issue, claim_label())
        else:
            client.remove_label(issue, claim_label())
        try:
            observed = _issue_claim(_ledger_claims(client), issue)
        except LedgerSuperseded:
            client.remove_label(issue, claim_label())
            raise
        if (observed.claim_id if observed else None) == (
            expected.claim_id if expected else None
        ):
            return
    raise ClaimError(f"issue #{issue} claim label changed repeatedly during reconciliation")


def reconcile_all_labels(client: IssueComments) -> tuple[int, ...]:
    try:
        active_issues = {claim.issue for claim in _ledger_claims(client)}
    except LedgerSuperseded:
        for issue in client.list_claimed_issues():
            client.remove_label(issue, claim_label())
        raise
    known_issues = active_issues | set(client.list_claimed_issues())
    for issue in sorted(known_issues):
        reconcile_issue_label(client, issue)
    return tuple(sorted(active_issues))


def acquire_claim(client: IssueComments, request: ClaimRequest) -> ActiveClaim:
    standing = _ledger_claims(client)
    blocked_by = conflicting_claims(standing, request)
    if blocked_by:
        owner = blocked_by[0]
        raise ClaimUnavailable(
            f"issue #{request.issue} or its scope is claimed by {owner.agent} "
            f"({owner.role}) on issue #{owner.issue} branch {owner.branch}"
        )

    client.post_comment(LEDGER_ISSUE, claim_comment(request))
    observed = _ledger_claims(client)
    own = next((claim for claim in observed if claim.claim_id == request.claim_id), None)
    if own is None:
        raise ClaimError(f"issue #{request.issue} did not expose the posted claim id")
    competitors = conflicting_claims(observed, own)
    winner = min(
        (own, *competitors),
        key=lambda claim: (claim.comment.created_at, claim.comment.identifier),
    )
    if winner.claim_id != request.claim_id:
        client.post_comment(
            LEDGER_ISSUE,
            release_comment(own, request.agent, request.role, "claim race lost"),
        )
        reconcile_issue_label(client, request.issue)
        reconcile_issue_label(client, winner.issue)
        raise ClaimUnavailable(
            f"issue #{request.issue} claim race lost to {winner.agent} "
            f"({winner.role}) on issue #{winner.issue} branch {winner.branch}"
        )

    reconcile_issue_label(client, request.issue)
    return own


def release_claim(
    client: IssueComments,
    issue: int,
    agent: str,
    role: str,
    reason: str,
    claim_id: str | None,
    *,
    coordinator_override: bool = False,
) -> ActiveClaim:
    standing = tuple(claim for claim in _ledger_claims(client) if claim.issue == issue)
    if not standing:
        raise ClaimUnavailable(f"issue #{issue} has no active build claim")
    if claim_id is None and len(standing) != 1:
        raise ClaimUnavailable(f"issue #{issue} has conflicting claims; pass --claim-id")
    selected = next(
        (claim for claim in standing if claim.claim_id == (claim_id or standing[0].claim_id)),
        None,
    )
    if selected is None:
        raise ClaimUnavailable(f"issue #{issue} has no active claim {claim_id!r}")
    if coordinator_override:
        if role != "coordinator":
            raise ClaimUnavailable("a coordinator override requires --role coordinator")
    elif (agent, role) != (selected.agent, selected.role):
        raise ClaimUnavailable(
            "only the original claimant may release; use an explicit coordinator override"
        )

    ledger_url = client.post_comment(
        LEDGER_ISSUE,
        release_comment(
            selected,
            agent,
            role,
            reason,
            coordinator_override=coordinator_override,
        ),
    )
    reconcile_issue_label(
        client,
        issue,
        unclaimed_body=_unclaimed_projection(ledger_url, reason),
    )
    return selected


def supersede_ledger(
    client: IssueComments,
    successor_issue: int,
    agent: str,
    role: str,
    reason: str,
    claim_id: str,
) -> ActiveClaim:
    if role != "coordinator":
        raise ClaimUnavailable("ledger supersede requires --role coordinator")
    if successor_issue <= LEDGER_ISSUE:
        raise ClaimUnavailable("successor issue must be greater than the current ledger")
    try:
        standing = _ledger_claims(client)
    except LedgerSuperseded as error:
        if error.successor_issue != successor_issue or error.claim.claim_id != claim_id:
            raise
        client.remove_label(LEDGER_ISSUE, claim_label())
        return error.claim
    selected = next((claim for claim in standing if claim.claim_id == claim_id), None)
    if (
        selected is None
        or selected.issue != LEDGER_ISSUE
        or len(standing) != 1
    ):
        raise ClaimUnavailable(
            "ledger supersede requires the named claim to be the only active claim "
            "and to own the ledger issue"
        )
    client.validate_successor(successor_issue)
    client.post_comment(
        LEDGER_ISSUE,
        supersede_comment(selected, successor_issue, agent, role, reason),
    )
    try:
        _ledger_claims(client)
    except LedgerSuperseded as error:
        if error.successor_issue == successor_issue and error.claim == selected:
            client.remove_label(LEDGER_ISSUE, claim_label())
            return selected
        raise
    raise ClaimError("ledger supersede event was not observed after publication")


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=1)


def _close_process_streams(process: subprocess.Popen[bytes]) -> None:
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream is None or stream.closed:
            continue
        try:
            stream.close()
        except (OSError, ValueError):
            pass


def _bounded_command(
    command: list[str], *, purpose: str, input_data: bytes | None = None
) -> str:
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE if input_data is not None else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
    except OSError as error:
        if isinstance(error, FileNotFoundError):
            raise ClaimError(f"{command[0]} is required for issue claims") from error
        raise ClaimError(f"cannot start {purpose}: {error}") from error
    selector: selectors.BaseSelector | None = None
    try:
        assert process.stdout is not None
        deadline = time.monotonic() + GH_TIMEOUT_SECONDS
        output = bytearray()
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
        pending_input = memoryview(input_data) if input_data is not None else None
        if pending_input is not None:
            assert process.stdin is not None
            os.set_blocking(process.stdin.fileno(), False)
            selector.register(process.stdin, selectors.EVENT_WRITE, "stdin")
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _stop_process(process)
                raise ClaimError(f"{purpose} timed out")
            try:
                events = selector.select(remaining)
            except OSError as error:
                raise ClaimError(f"{purpose} failed while waiting for I/O: {error}") from error
            if not events:
                _stop_process(process)
                raise ClaimError(f"{purpose} timed out")
            for key, _ in events:
                if key.data == "stdin":
                    assert pending_input is not None
                    try:
                        written = os.write(key.fileobj.fileno(), pending_input)
                    except BrokenPipeError:
                        written = len(pending_input)
                    except OSError as error:
                        _stop_process(process)
                        raise ClaimError(
                            f"{purpose} failed while sending bounded input: {error}"
                        ) from error
                    pending_input = pending_input[written:]
                    if not pending_input:
                        selector.unregister(key.fileobj)
                        key.fileobj.close()
                    continue
                try:
                    chunk = os.read(key.fileobj.fileno(), 64 * 1024)
                except OSError as error:
                    raise ClaimError(f"{purpose} failed while reading output: {error}") from error
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                output.extend(chunk)
                if len(output) > MAX_COMMAND_OUTPUT_BYTES:
                    _stop_process(process)
                    raise ClaimError(f"{purpose} exceeded its output limit")
        try:
            return_code = process.wait(timeout=1)
        except subprocess.TimeoutExpired as error:
            _stop_process(process)
            raise ClaimError(f"{purpose} did not exit after closing its output") from error
    except OSError as error:
        raise ClaimError(f"{purpose} failed while coordinating I/O: {error}") from error
    finally:
        try:
            if selector is not None:
                selector.close()
        except OSError:
            pass
        finally:
            _close_process_streams(process)
            if process.poll() is None:
                _stop_process(process)
    try:
        decoded = output.decode("utf-8").strip()
    except UnicodeDecodeError as error:
        raise ClaimError(f"{purpose} returned non-UTF-8 output") from error
    if return_code != 0:
        raise ClaimError(decoded or f"{purpose} failed with exit {return_code}")
    return decoded


class GitHubIssueComments:
    def __init__(self, repository: str):
        if REPOSITORY_PATTERN.fullmatch(repository) is None:
            raise ClaimError("repository must be OWNER/REPO")
        self.repository = repository
        self._rollover_warning_printed = False

    def _run(self, arguments: list[str], *, input_data: bytes | None = None) -> str:
        return _bounded_command(
            ["gh", *arguments],
            purpose="GitHub issue coordination",
            input_data=input_data,
        )

    def _json_lines(self, raw: str, description: str) -> tuple[object, ...]:
        values: list[object] = []
        try:
            for line in raw.splitlines():
                if line.strip():
                    values.append(json.loads(line))
        except json.JSONDecodeError as error:
            raise ClaimError(f"GitHub returned invalid {description} JSON") from error
        return tuple(values)

    def _comment_page(self, issue: int, page: int) -> tuple[IssueComment, ...]:
        raw = self._run(
            [
                "api",
                f"repos/{self.repository}/issues/{issue}/comments"
                f"?per_page={COMMENTS_PER_PAGE}&page={page}",
                "--jq",
                ".[] | {id,created_at,updated_at,body,author_association,html_url}",
            ]
        )
        return tuple(
            self._parse_comment(value)
            for value in self._json_lines(raw, "issue-comment")
        )

    def list_protocol_candidates(self, issue: int) -> tuple[IssueComment, ...]:
        comments: list[IssueComment] = []
        protocol_bytes = 0
        total_comments = 0
        for page in range(1, MAX_LEDGER_PAGES + 1):
            page_comments = self._comment_page(issue, page)
            total_comments += len(page_comments)
            for parsed in page_comments:
                if not is_protocol_candidate(parsed):
                    continue
                protocol_bytes += len(parsed.body.encode("utf-8"))
                if (
                    len(comments) >= MAX_PROTOCOL_EVENTS
                    or protocol_bytes > MAX_PROTOCOL_BYTES
                ):
                    raise ClaimError(
                        "claim ledger protocol limit reached; perform the "
                        "documented ledger rollover"
                    )
                comments.append(parsed)
            if len(page_comments) < COMMENTS_PER_PAGE:
                if (
                    page >= LEDGER_ROLLOVER_WARNING_PAGES
                    and not self._rollover_warning_printed
                ):
                    print(
                        f"WARNING: claim ledger has {total_comments} comments; "
                        "schedule the documented rollover",
                        file=sys.stderr,
                    )
                    self._rollover_warning_printed = True
                return tuple(comments)
        raise ClaimError(
            "claim ledger page limit reached; perform the documented ledger rollover"
        )

    def _projection_comments(self, issue: int) -> tuple[IssueComment, ...]:
        projections: list[IssueComment] = []
        for page in range(1, MAX_LEDGER_PAGES + 1):
            page_comments = self._comment_page(issue, page)
            projections.extend(
                comment
                for comment in page_comments
                if comment.author_association in TRUSTED_ASSOCIATIONS
                and PROJECTION_MARKER_PATTERN.fullmatch(
                    comment.body.partition("\n")[0]
                )
                is not None
            )
            if len(page_comments) < COMMENTS_PER_PAGE:
                return tuple(projections)
        raise ClaimError("owning issue comment limit reached during projection update")

    def _parse_comment(self, value: object) -> IssueComment:
        if not isinstance(value, dict):
            raise ClaimError("GitHub issue-comment entry must be an object")
        identifier = value.get("id")
        created_at = value.get("created_at")
        updated_at = value.get("updated_at")
        body = value.get("body")
        association = value.get("author_association")
        url = value.get("html_url")
        if (
            isinstance(identifier, bool)
            or not isinstance(identifier, int)
            or identifier < 1
            or not isinstance(created_at, str)
            or TIMESTAMP_PATTERN.fullmatch(created_at) is None
            or not isinstance(updated_at, str)
            or TIMESTAMP_PATTERN.fullmatch(updated_at) is None
            or not isinstance(body, str)
            or not isinstance(association, str)
            or not isinstance(url, str)
            or not url.startswith("https://github.com/")
        ):
            raise ClaimError("GitHub returned a malformed issue-comment entry")
        return IssueComment(identifier, created_at, updated_at, body, association, url)

    def list_claimed_issues(self) -> tuple[int, ...]:
        raw = self._run(
            [
                "api",
                "--paginate",
                f"repos/{self.repository}/issues?state=all&labels={claim_label()}&per_page=100",
                "--jq",
                ".[] | select(has(\"pull_request\") | not) | .number",
            ]
        )
        issues: list[int] = []
        for value in self._json_lines(raw, "claimed-issue"):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ClaimError("GitHub returned a malformed claimed-issue entry")
            issues.append(value)
        return tuple(issues)

    def validate_successor(self, issue: int) -> None:
        raw = self._run(
            [
                "api",
                f"repos/{self.repository}/issues/{issue}",
                "--jq",
                '{number,state,locked,comments,is_pull_request:has("pull_request")}',
            ]
        )
        values = self._json_lines(raw, "successor-issue")
        if len(values) != 1 or not isinstance(values[0], dict):
            raise ClaimError("GitHub returned a malformed successor issue")
        successor = values[0]
        number = successor.get("number")
        comments = successor.get("comments")
        if (
            isinstance(number, bool)
            or number != issue
            or successor.get("state") != "open"
            or successor.get("locked") is not True
            or isinstance(comments, bool)
            or comments != 0
            or successor.get("is_pull_request") is not False
        ):
            raise ClaimUnavailable(
                f"successor #{issue} must be an open, empty, collaborator-locked issue"
            )

    def upsert_projection(
        self,
        issue: int,
        body: str,
        *,
        create: bool = True,
        adopt_stale: bool = False,
    ) -> bool:
        validated = _validated_comment(body)
        all_projections = self._projection_comments(issue)
        current_marker = _projection_marker()
        projections = tuple(
            comment
            for comment in all_projections
            if comment.body.partition("\n")[0] == current_marker
        )
        adoptable_projections = tuple(
            comment
            for comment in all_projections
            if (_projection_ledger(comment) or 0) <= LEDGER_ISSUE
        )
        has_newer_projection = any(
            (_projection_ledger(comment) or 0) > LEDGER_ISSUE
            for comment in all_projections
        )
        if adopt_stale and adoptable_projections:
            projections = adoptable_projections
        if not projections:
            if has_newer_projection:
                raise ClaimError(
                    "owning issue has a projection from a newer ledger generation"
                )
            if not create:
                return False
            self.post_comment(issue, validated)
            projections = tuple(
                comment
                for comment in self._projection_comments(issue)
                if comment.body.partition("\n")[0] == current_marker
            )
        if not projections:
            raise ClaimError(f"issue #{issue} did not expose its posted claim projection")
        ordered = sorted(
            projections,
            key=lambda comment: (comment.created_at, comment.identifier),
        )
        owner, *duplicates = ordered
        if owner.body != validated:
            self._run(
                [
                    "api",
                    "--method",
                    "PATCH",
                    f"repos/{self.repository}/issues/comments/{owner.identifier}",
                    "--input",
                    "-",
                ],
                input_data=json.dumps({"body": validated}).encode("utf-8"),
            )
        for duplicate in duplicates:
            self._run(
                [
                    "api",
                    "--method",
                    "DELETE",
                    f"repos/{self.repository}/issues/comments/{duplicate.identifier}",
                ]
            )
        return True

    def post_comment(self, issue: int, body: str) -> str:
        encoded = _validated_comment(body).encode("utf-8")
        return self._run(
            ["issue", "comment", str(issue), "--repo", self.repository, "--body-file", "-"],
            input_data=encoded,
        )

    def add_label(self, issue: int, label: str) -> None:
        self._run(["issue", "edit", str(issue), "--repo", self.repository, "--add-label", label])

    def remove_label(self, issue: int, label: str) -> None:
        self._run(
            ["issue", "edit", str(issue), "--repo", self.repository, "--remove-label", label]
        )


def _repository(explicit: str | None) -> str:
    if explicit:
        repository = explicit
    else:
        try:
            result = subprocess.run(
                ["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"],
                check=False,
                capture_output=True,
                text=True,
                timeout=GH_TIMEOUT_SECONDS,
            )
        except FileNotFoundError as error:
            raise ClaimError("gh is required for issue claims") from error
        except subprocess.TimeoutExpired as error:
            raise ClaimError("gh timed out while resolving the repository") from error
        if result.returncode != 0 or not result.stdout.strip():
            raise ClaimError("cannot resolve GitHub repository; pass --repo OWNER/REPO")
        repository = result.stdout.strip()
    if REPOSITORY_PATTERN.fullmatch(repository) is None:
        raise ClaimError("repository must be OWNER/REPO")
    return repository


def _git_output(arguments: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=GH_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as error:
        raise ClaimError("git is required for issue claims") from error
    except subprocess.TimeoutExpired as error:
        raise ClaimError("git timed out while validating the build checkout") from error
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown git failure"
        raise ClaimError(detail)
    return result.stdout.strip()


def _validate_checkout(request: ClaimRequest) -> None:
    if request.branch in {"main", "master"}:
        raise ClaimError("build claims require an isolated non-main worktree branch")
    head = _git_output(["rev-parse", "HEAD"])
    branch = _git_output(["branch", "--show-current"])
    git_directory = Path(_git_output(["rev-parse", "--git-dir"])).resolve()
    common_directory = Path(_git_output(["rev-parse", "--git-common-dir"])).resolve()
    dirty = _git_output(["status", "--porcelain"])
    if head != request.base:
        raise ClaimError(
            f"claim base {request.base} does not match checkout HEAD {head}"
        )
    if branch != request.branch:
        raise ClaimError(
            f"claim branch {request.branch!r} does not match checkout branch {branch!r}"
        )
    if git_directory == common_directory:
        raise ClaimError("build claims require a linked isolated worktree checkout")
    if dirty:
        raise ClaimError("claim must be acquired before the first worktree edit")


def _request(arguments: argparse.Namespace) -> ClaimRequest:
    payload: dict[str, object] = {
        "action": "claim",
        "agent": arguments.agent,
        "base": arguments.base,
        "branch": arguments.branch,
        "claim_id": arguments.claim_id or uuid.uuid4().hex,
        "issue": arguments.issue,
        "role": arguments.role,
        "scope": arguments.scope,
    }
    synthetic = IssueComment(
        1,
        "2026-01-01T00:00:00Z",
        "2026-01-01T00:00:00Z",
        f"{_marker(payload)}\n\nAgent: {arguments.agent} ({arguments.role})",
        "OWNER",
        "https://github.com/local/request",
    )
    parsed = parse_claim_event(synthetic)
    if not isinstance(parsed, ActiveClaim):
        raise ClaimError("claim request did not produce a marker")
    request = ClaimRequest(
        issue=parsed.issue,
        agent=parsed.agent,
        role=parsed.role,
        base=parsed.base,
        branch=parsed.branch,
        scope=parsed.scope,
        claim_id=parsed.claim_id,
    )
    _validate_checkout(request)
    return request


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", help="GitHub repository as OWNER/REPO")
    commands = parser.add_subparsers(dest="command", required=True)

    status = commands.add_parser("status", help="show repository-wide build claims")
    status.add_argument("issue", type=int, nargs="?")

    claim = commands.add_parser("claim", help="claim an issue and scope before editing")
    claim.add_argument("issue", type=int)
    claim.add_argument("--agent", required=True)
    claim.add_argument("--role", required=True)
    claim.add_argument("--base", required=True)
    claim.add_argument("--branch", required=True)
    claim.add_argument("--scope", action="append", required=True)
    claim.add_argument("--claim-id")

    release = commands.add_parser("release", help="release a landed or abandoned claim")
    release.add_argument("issue", type=int)
    release.add_argument("--agent", required=True)
    release.add_argument("--role", required=True)
    release.add_argument("--reason", required=True)
    release.add_argument("--claim-id")
    release.add_argument("--coordinator-override", action="store_true")

    reconcile = commands.add_parser("reconcile", help="repair claimed-label projections")
    reconcile.add_argument("issue", type=int, nargs="?")

    supersede = commands.add_parser(
        "supersede", help="atomically freeze a drained ledger for its successor"
    )
    supersede.add_argument("successor_issue", type=int)
    supersede.add_argument("--agent", required=True)
    supersede.add_argument("--role", required=True)
    supersede.add_argument("--reason", required=True)
    supersede.add_argument("--claim-id", required=True)
    return parser


def _status(claims: tuple[ActiveClaim, ...], issue: int | None) -> int:
    selected = tuple(claim for claim in claims if issue is None or claim.issue == issue)
    if not selected:
        subject = "repository" if issue is None else f"issue #{issue}"
        print(f"UNCLAIMED {subject}")
        return 0
    index = _claim_conflict_index(claims)
    related_ids = (
        {claim.claim_id for claim in claims}
        if issue is None
        else _related_claim_ids(index, selected)
    )
    related = tuple(
        claim
        for claim in claims
        if claim.claim_id in related_ids
    )
    for claim in related:
        state = "CONFLICT" if claim.claim_id in index.conflict_ids else "CLAIMED"
        print(
            f"{state} issue #{claim.issue}: {claim.agent} ({claim.role}) "
            f"base={claim.base} branch={claim.branch} claim={claim.claim_id}"
        )
        for path in claim.scope:
            print(f"  {path}")
    return 2 if any(claim.claim_id in index.conflict_ids for claim in related) else 0


def main(arguments: list[str] | None = None) -> int:
    parsed = _parser().parse_args(arguments)
    try:
        client = GitHubIssueComments(_repository(parsed.repo))
        if parsed.command == "status":
            return _status(_ledger_claims(client), parsed.issue)
        if parsed.command == "claim":
            claimed = acquire_claim(client, _request(parsed))
            print(f"CLAIMED issue #{parsed.issue}: {claimed.claim_id} {claimed.comment.url}")
            return 0
        if parsed.command == "release":
            released = release_claim(
                client,
                parsed.issue,
                parsed.agent,
                parsed.role,
                parsed.reason,
                parsed.claim_id,
                coordinator_override=parsed.coordinator_override,
            )
            print(f"RELEASED issue #{parsed.issue}: {released.claim_id}")
            return 0
        if parsed.command == "supersede":
            rollover = supersede_ledger(
                client,
                parsed.successor_issue,
                parsed.agent,
                parsed.role,
                parsed.reason,
                parsed.claim_id,
            )
            print(
                f"SUPERSEDED ledger #{LEDGER_ISSUE} with #{parsed.successor_issue}: "
                f"{rollover.claim_id}"
            )
            return 0
        if parsed.issue is None:
            reconciled = reconcile_all_labels(client)
        else:
            reconcile_issue_label(client, parsed.issue)
            reconciled = tuple(
                claim.issue for claim in _ledger_claims(client) if claim.issue == parsed.issue
            )
        print("RECONCILED " + (", ".join(f"#{issue}" for issue in reconciled) or "no claims"))
        return 0
    except ClaimError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
