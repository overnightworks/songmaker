from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import issue_claim  # noqa: E402
from issue_claim import (  # noqa: E402
    LEDGER_ISSUE,
    MAX_COMMENT_BYTES,
    ActiveClaim,
    ClaimantRelease,
    ClaimError,
    ClaimRequest,
    ClaimUnavailable,
    GitHubIssueComments,
    InvalidClaimMarker,
    IssueComment,
    LedgerSupersede,
    LedgerSuperseded,
    _repository,
    _status,
    acquire_claim,
    active_claims,
    claim_comment,
    claim_label,
    claims_conflict,
    is_protocol_candidate,
    parse_claim_event,
    reconcile_all_labels,
    reconcile_issue_label,
    release_claim,
    release_comment,
    supersede_comment,
    supersede_ledger,
)

BASE = "a" * 40


def comment(
    identifier: int,
    body: str,
    *,
    created_at: str | None = None,
    association: str = "OWNER",
) -> IssueComment:
    return IssueComment(
        identifier=identifier,
        created_at=created_at or f"2026-08-21T00:00:{identifier:02d}Z",
        updated_at=created_at or f"2026-08-21T00:00:{identifier:02d}Z",
        body=body,
        author_association=association,
        url=f"https://github.com/FlexOr2/songmaker/issues/71#issuecomment-{identifier}",
    )


def request(
    claim_id: str = "claim-a",
    agent: str = "Codex Sol",
    *,
    issue: int = 71,
    scope: tuple[str, ...] = ("docs/COORDINATION.md", "scripts/issue_claim.py"),
) -> ClaimRequest:
    return ClaimRequest(
        issue=issue,
        agent=agent,
        role="builder",
        base=BASE,
        branch=f"codex/issue-{issue}-claims",
        scope=scope,
        claim_id=claim_id,
    )


@dataclass
class FakeComments:
    comments: dict[int, list[IssueComment]] = field(default_factory=dict)
    labels: set[int] = field(default_factory=set)
    other_labels: dict[str, set[int]] = field(default_factory=dict)
    valid_successors: set[int] = field(default_factory=set)
    inject_before_next_ledger_post: IssueComment | None = None
    inject_after_next_ledger_post: IssueComment | None = None
    inject_during_next_add: IssueComment | None = None
    inject_during_next_remove: IssueComment | None = None
    fail_add_label: bool = False
    fail_remove_label: bool = False

    def list_protocol_candidates(self, issue: int) -> tuple[IssueComment, ...]:
        return tuple(
            entry for entry in self.comments.get(issue, []) if is_protocol_candidate(entry)
        )

    def post_comment(self, issue: int, body: str) -> str:
        if issue == LEDGER_ISSUE and self.inject_before_next_ledger_post is not None:
            self.comments.setdefault(LEDGER_ISSUE, []).append(
                self.inject_before_next_ledger_post
            )
            self.inject_before_next_ledger_post = None
        identifier = max(
            (
                entry.identifier
                for entries in self.comments.values()
                for entry in entries
            ),
            default=0,
        ) + 1
        posted = comment(identifier, body)
        self.comments.setdefault(issue, []).append(posted)
        if issue == LEDGER_ISSUE and self.inject_after_next_ledger_post is not None:
            self.comments.setdefault(LEDGER_ISSUE, []).append(
                self.inject_after_next_ledger_post
            )
            self.inject_after_next_ledger_post = None
        return posted.url

    def add_label(self, issue: int, label: str) -> None:
        assert label == claim_label()
        if self.fail_add_label:
            raise ClaimError("label add failed")
        if self.inject_during_next_add is not None:
            self.comments.setdefault(LEDGER_ISSUE, []).append(self.inject_during_next_add)
            self.inject_during_next_add = None
        self.labels.add(issue)

    def remove_label(self, issue: int, label: str) -> None:
        assert label == claim_label()
        if self.fail_remove_label:
            raise ClaimError("label remove failed")
        if self.inject_during_next_remove is not None:
            self.comments.setdefault(LEDGER_ISSUE, []).append(
                self.inject_during_next_remove
            )
            self.labels.add(self.inject_during_next_remove_event.issue)
            self.inject_during_next_remove = None
        self.labels.discard(issue)

    @property
    def inject_during_next_remove_event(self):
        assert self.inject_during_next_remove is not None
        event = parse_claim_event(self.inject_during_next_remove)
        assert event is not None
        return event

    def list_claimed_issues(self) -> tuple[int, ...]:
        return tuple(sorted(self.labels))

    def validate_successor(self, issue: int) -> None:
        if issue not in self.valid_successors:
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
        entries = self.comments.setdefault(issue, [])
        all_projections = [
            entry
            for entry in entries
            if issue_claim.PROJECTION_MARKER_PATTERN.fullmatch(
                entry.body.partition("\n")[0]
            )
            is not None
        ]
        projections = [
            entry
            for entry in all_projections
            if entry.body.partition("\n")[0] == issue_claim._projection_marker()
        ]
        adoptable_projections = [
            entry
            for entry in all_projections
            if (issue_claim._projection_ledger(entry) or 0) <= issue_claim.LEDGER_ISSUE
        ]
        has_newer_projection = any(
            (issue_claim._projection_ledger(entry) or 0) > issue_claim.LEDGER_ISSUE
            for entry in all_projections
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
            self.post_comment(issue, body)
            projections = [self.comments[issue][-1]]
        owner, *duplicates = sorted(
            projections,
            key=lambda entry: (entry.created_at, entry.identifier),
        )
        owner_index = entries.index(owner)
        entries[owner_index] = replace(owner, body=body, updated_at=owner.created_at)
        duplicate_ids = {entry.identifier for entry in duplicates}
        entries[:] = [entry for entry in entries if entry.identifier not in duplicate_ids]
        return True


def marker(
    payload: dict[str, object], *, legacy: bool = False, attributed: bool = True
) -> str:
    version = "v1" if legacy else "v2"
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    body = f"<!-- songmaker-claim:{version} {encoded} -->"
    agent = payload.get("agent")
    role = payload.get("role")
    if attributed and isinstance(agent, str) and isinstance(role, str):
        body += f"\n\nAgent: {agent} ({role})"
    return body


def release_event(claim, *, agent: str | None = None, role: str | None = None) -> str:
    return release_comment(
        claim,
        agent or claim.agent,
        role or claim.role,
        "landed",
    )


def test_claim_marker_round_trips_visible_contract() -> None:
    body = claim_comment(request())
    parsed = parse_claim_event(comment(1, body))

    assert parsed is not None
    assert parsed.issue == 71
    assert parsed.claim_id == "claim-a"
    assert parsed.base == BASE
    assert parsed.branch == "codex/issue-71-claims"
    assert parsed.scope == ("docs/COORDINATION.md", "scripts/issue_claim.py")
    assert "Agent: Codex Sol (builder)" in body
    assert "Auto-Runner" in body


def test_protocol_parser_returns_action_specific_types() -> None:
    claimed = parse_claim_event(comment(1, claim_comment(request())))
    assert isinstance(claimed, ActiveClaim)

    released = parse_claim_event(comment(2, release_event(claimed)))
    assert isinstance(released, ClaimantRelease)
    assert released.reason == "landed"


def test_untrusted_claim_and_release_markers_are_ignored() -> None:
    claimed = parse_claim_event(comment(1, claim_comment(request())))
    assert claimed is not None
    release = release_event(claimed)

    comments = (
        comment(1, claim_comment(request()), association="NONE"),
        comment(2, release, association="NONE"),
    )

    assert [parse_claim_event(entry) for entry in comments] == [None, None]
    assert active_claims(comments) == ()

    still_active = active_claims(
        (
            comment(1, claim_comment(request())),
            comment(2, release, association="NONE"),
        )
    )
    assert [claim.claim_id for claim in still_active] == ["claim-a"]


@pytest.mark.parametrize(
    "body",
    [
        "Review quotes <!-- songmaker-claim:v1 … --> as evidence.",
        "> <!-- songmaker-claim:v2 {} -->",
        "```html\n<!-- songmaker-claim:v2 {} -->\n```",
        "ordinary first line\n<!-- songmaker-claim:v2 {} -->",
    ],
)
def test_marker_is_protocol_only_as_the_exact_first_line(body: str) -> None:
    assert parse_claim_event(comment(1, body)) is None


def test_edited_protocol_comment_fails_loud() -> None:
    edited = comment(1, claim_comment(request()))
    edited = IssueComment(
        edited.identifier,
        edited.created_at,
        "2026-08-21T00:01:00Z",
        edited.body,
        edited.author_association,
        edited.url,
    )

    with pytest.raises(InvalidClaimMarker, match="edited after publication"):
        parse_claim_event(edited)


@pytest.mark.parametrize(
    "attribution",
    [None, "Agent: Other (builder)", "Agent: Codex Sol (reviewer)"],
)
def test_protocol_event_requires_exact_final_agent_attribution(
    attribution: str | None,
) -> None:
    payload = {
        "action": "claim",
        "agent": "Codex Sol",
        "base": BASE,
        "branch": "codex/issue-71-claims",
        "claim_id": "claim-a",
        "issue": 71,
        "role": "builder",
        "scope": ["AGENTS.md"],
    }
    body = marker(payload, attributed=False)
    if attribution is not None:
        body += f"\n\n{attribution}"

    with pytest.raises(InvalidClaimMarker, match="exact agent attribution"):
        parse_claim_event(comment(1, body))


@pytest.mark.parametrize(
    "invalid",
    ["Codex\nSol", "Codex\x1fSol", " ", "x" * 129],
)
def test_outbound_comment_constructors_reject_controlled_identity_fields(
    invalid: str,
) -> None:
    claimed = parse_claim_event(comment(1, claim_comment(request())))
    assert isinstance(claimed, ActiveClaim)

    with pytest.raises(ClaimError, match="agent must be one bounded non-empty line"):
        claim_comment(replace(request(), agent=invalid))
    with pytest.raises(ClaimError, match="agent must be one bounded non-empty line"):
        release_comment(claimed, invalid, "builder", "landed")
    with pytest.raises(ClaimError, match="agent must be one bounded non-empty line"):
        supersede_comment(claimed, 170, invalid, "coordinator", "rollover")

    with pytest.raises(ClaimError, match="role must be one bounded non-empty line"):
        claim_comment(replace(request(), role=invalid))
    with pytest.raises(ClaimError, match="role must be one bounded non-empty line"):
        release_comment(claimed, "Codex Sol", invalid, "landed")
    with pytest.raises(ClaimError, match="role must be one bounded non-empty line"):
        supersede_comment(claimed, 170, "Codex Sol", invalid, "rollover")


@pytest.mark.parametrize(
    "invalid",
    ["landed\nwith detail", "landed\x1fdetail", " ", "x" * 513],
)
def test_outbound_comment_constructors_reject_controlled_reasons(invalid: str) -> None:
    claimed = parse_claim_event(comment(1, claim_comment(request())))
    assert isinstance(claimed, ActiveClaim)

    with pytest.raises(ClaimError, match="reason must be one bounded non-empty line"):
        release_comment(claimed, "Codex Sol", "builder", invalid)
    with pytest.raises(ClaimError, match="reason must be one bounded non-empty line"):
        supersede_comment(claimed, 170, "Codex Sol", "coordinator", invalid)


def test_legacy_bootstrap_claim_is_read_only_when_marker_is_first_line() -> None:
    legacy = marker(
        {
            "action": "claim",
            "agent": "Codex Sol",
            "base": BASE,
            "branch": "codex/issue-71-claims",
            "claim_id": "bootstrap",
            "role": "builder",
            "scope": ["AGENTS.md"],
        },
        legacy=True,
    )

    parsed = parse_claim_event(comment(1, legacy))

    assert parsed is not None
    assert parsed.issue == LEDGER_ISSUE
    assert parsed.claim_id == "bootstrap"


@pytest.mark.parametrize(
    ("branch", "scope"),
    [
        ("../not-a-branch", ["src"]),
        ("topic//double", ["src"]),
        ("topic.lock", ["src"]),
        ("topic", ["/home/operator/repo"]),
        ("topic", ["C:\\Users\\operator\\secret.txt"]),
        ("topic", ["C:/Users/operator/secret.txt"]),
        ("topic", ["\\\\server\\share\\secret.txt"]),
        ("topic", ["../other-repo"]),
        ("topic", ["."]),
        ("topic", ["./src"]),
        ("topic", ["src//file.py"]),
        ("topic", [".git/config"]),
    ],
)
def test_invalid_branch_and_private_or_noncanonical_scope_fail_loud(
    branch: str, scope: list[str]
) -> None:
    payload = {
        "action": "claim",
        "agent": "Codex Sol",
        "base": BASE,
        "branch": branch,
        "claim_id": "claim-a",
        "issue": 71,
        "role": "builder",
        "scope": scope,
    }

    with pytest.raises(InvalidClaimMarker):
        parse_claim_event(comment(1, marker(payload)))


def test_unknown_or_missing_marker_fields_fail_loud() -> None:
    unknown = {
        "action": "claim",
        "agent": "Codex Sol",
        "base": BASE,
        "branch": "topic",
        "claim_id": "claim-a",
        "issue": 71,
        "role": "builder",
        "scope": ["src"],
        "surprise": True,
    }

    with pytest.raises(InvalidClaimMarker, match="fields differ"):
        parse_claim_event(comment(1, marker(unknown)))
    with pytest.raises(InvalidClaimMarker):
        parse_claim_event(comment(2, marker({"action": "claim"})))


def test_release_must_come_from_original_claimant() -> None:
    claimed_body = claim_comment(request())
    claimed = parse_claim_event(comment(1, claimed_body))
    assert claimed is not None
    foreign_release = release_event(claimed, agent="Other", role="builder")

    with pytest.raises(InvalidClaimMarker, match="only be released by its claimant"):
        active_claims((comment(1, claimed_body), comment(2, foreign_release)))


def test_coordinator_override_is_explicit_and_bound_to_claim_comment() -> None:
    claimed_body = claim_comment(request())
    claimed = parse_claim_event(comment(1, claimed_body))
    assert claimed is not None
    override = release_comment(
        claimed,
        "Codex Commissioner",
        "coordinator",
        "verified abandoned",
        coordinator_override=True,
    )

    assert active_claims((comment(1, claimed_body), comment(2, override))) == ()

    first_line = override.partition("\n")[0]
    payload = json.loads(
        first_line.removeprefix("<!-- songmaker-claim:v2 ").removesuffix(" -->")
    )
    payload["claim_comment_id"] = 999
    with pytest.raises(InvalidClaimMarker, match="wrong claim comment"):
        active_claims((comment(1, claimed_body), comment(2, marker(payload))))


def test_claim_ids_are_never_reused_and_releases_require_active_claim() -> None:
    claimed_body = claim_comment(request())
    claimed = parse_claim_event(comment(1, claimed_body))
    assert claimed is not None
    released = release_event(claimed)

    with pytest.raises(InvalidClaimMarker, match="was reused"):
        active_claims(
            (
                comment(1, claimed_body),
                comment(2, released),
                comment(3, claimed_body),
            )
        )
    with pytest.raises(InvalidClaimMarker, match="before it was acquired"):
        active_claims((comment(1, released),))


def test_duplicate_claimant_releases_are_idempotent() -> None:
    claimed_body = claim_comment(request())
    claimed = parse_claim_event(comment(1, claimed_body))
    assert claimed is not None
    first_release = release_comment(claimed, "Codex Sol", "builder", "landed")
    second_release = release_comment(claimed, "Codex Sol", "builder", "landed retry")

    assert active_claims(
        (
            comment(1, claimed_body),
            comment(2, first_release),
            comment(3, second_release),
        )
    ) == ()


@pytest.mark.parametrize("override_first", [False, True])
def test_claimant_and_coordinator_release_race_is_idempotent(
    override_first: bool,
) -> None:
    claimed_body = claim_comment(request())
    claimed = parse_claim_event(comment(1, claimed_body))
    assert claimed is not None
    claimant = release_comment(claimed, "Codex Sol", "builder", "landed")
    coordinator = release_comment(
        claimed,
        "Fleet Coordinator",
        "coordinator",
        "verified handoff",
        coordinator_override=True,
    )
    releases = (coordinator, claimant) if override_first else (claimant, coordinator)

    assert active_claims(
        (
            comment(1, claimed_body),
            comment(2, releases[0]),
            comment(3, releases[1]),
        )
    ) == ()


def test_supersede_atomically_terminates_the_only_ledger_claim() -> None:
    claimed_body = claim_comment(request(issue=LEDGER_ISSUE))
    claimed = parse_claim_event(comment(1, claimed_body))
    assert isinstance(claimed, ActiveClaim)
    frozen = supersede_comment(
        claimed,
        170,
        "Fleet Coordinator",
        "coordinator",
        "reviewed rollover ready to land",
    )
    parsed = parse_claim_event(comment(2, frozen))
    assert isinstance(parsed, LedgerSupersede)
    assert parsed.successor_issue == 170

    with pytest.raises(LedgerSuperseded, match="successor #170"):
        active_claims((comment(1, claimed_body), comment(2, frozen)))
    late_claim = comment(
        3,
        claim_comment(request("late", issue=72, scope=("frontend",))),
    )
    with pytest.raises(LedgerSuperseded, match="successor #170"):
        active_claims((comment(1, claimed_body), comment(2, frozen), late_claim))


def test_supersede_is_an_inert_rejected_event_while_another_lane_is_active() -> None:
    rollover_body = claim_comment(request(issue=LEDGER_ISSUE, scope=("docs",)))
    rollover = parse_claim_event(comment(1, rollover_body))
    assert isinstance(rollover, ActiveClaim)
    other = comment(
        2,
        claim_comment(request("other", issue=72, scope=("frontend",))),
    )
    frozen = comment(
        3,
        supersede_comment(
            rollover,
            170,
            "Fleet Coordinator",
            "coordinator",
            "not actually drained",
        ),
    )

    observed = active_claims((comment(1, rollover_body), other, frozen))

    assert [claim.claim_id for claim in observed] == [rollover.claim_id, "other"]


def test_supersede_command_posts_terminal_event_and_observes_freeze() -> None:
    client = FakeComments(valid_successors={170})
    acquired = acquire_claim(client, request(issue=LEDGER_ISSUE))

    selected = supersede_ledger(
        client,
        170,
        "Fleet Coordinator",
        "coordinator",
        "reviewed successor ready",
        acquired.claim_id,
    )

    assert selected == acquired
    assert LEDGER_ISSUE not in client.labels
    with pytest.raises(LedgerSuperseded, match="successor #170"):
        active_claims(client.list_protocol_candidates(LEDGER_ISSUE))


def test_supersede_race_loses_cleanly_without_poisoning_the_ledger() -> None:
    client = FakeComments(valid_successors={170})
    acquired = acquire_claim(
        client,
        request(issue=LEDGER_ISSUE, scope=("docs",)),
    )
    competitor = comment(
        50,
        claim_comment(request("other", issue=72, scope=("frontend",))),
        created_at="2026-08-21T00:00:01Z",
    )
    client.inject_before_next_ledger_post = competitor

    with pytest.raises(ClaimError, match="not observed"):
        supersede_ledger(
            client,
            170,
            "Fleet Coordinator",
            "coordinator",
            "race should reject",
            acquired.claim_id,
        )

    observed = active_claims(client.list_protocol_candidates(LEDGER_ISSUE))
    assert {claim.claim_id for claim in observed} == {acquired.claim_id, "other"}


def test_supersede_label_failure_can_be_retried_without_reposting_event() -> None:
    client = FakeComments(valid_successors={170}, fail_remove_label=True)
    acquired = acquire_claim(client, request(issue=LEDGER_ISSUE))

    with pytest.raises(ClaimError, match="label remove failed"):
        supersede_ledger(
            client,
            170,
            "Fleet Coordinator",
            "coordinator",
            "reviewed successor ready",
            acquired.claim_id,
        )
    protocol_count = len(client.list_protocol_candidates(LEDGER_ISSUE))
    assert LEDGER_ISSUE in client.labels

    client.fail_remove_label = False
    client.valid_successors.clear()  # The successor may already have accepted new claims.
    supersede_ledger(
        client,
        170,
        "Fleet Coordinator",
        "coordinator",
        "reviewed successor ready",
        acquired.claim_id,
    )

    assert len(client.list_protocol_candidates(LEDGER_ISSUE)) == protocol_count
    assert LEDGER_ISSUE not in client.labels


def test_supersede_refuses_an_unverified_successor_before_posting() -> None:
    client = FakeComments()
    acquired = acquire_claim(client, request(issue=LEDGER_ISSUE))
    protocol_count = len(client.list_protocol_candidates(LEDGER_ISSUE))

    with pytest.raises(ClaimUnavailable, match="open, empty, collaborator-locked"):
        supersede_ledger(
            client,
            999999,
            "Fleet Coordinator",
            "coordinator",
            "invalid successor",
            acquired.claim_id,
        )

    assert len(client.list_protocol_candidates(LEDGER_ISSUE)) == protocol_count


def test_supersede_requires_a_higher_numbered_successor() -> None:
    client = FakeComments(valid_successors={70})
    acquired = acquire_claim(client, request(issue=LEDGER_ISSUE))
    protocol_count = len(client.list_protocol_candidates(LEDGER_ISSUE))

    with pytest.raises(ClaimError, match="greater than the current ledger"):
        supersede_comment(
            acquired,
            70,
            "Fleet Coordinator",
            "coordinator",
            "invalid rollover",
        )
    with pytest.raises(ClaimUnavailable, match="greater than the current ledger"):
        supersede_ledger(
            client,
            70,
            "Fleet Coordinator",
            "coordinator",
            "invalid rollover",
            acquired.claim_id,
        )

    with pytest.raises(InvalidClaimMarker, match="greater than the current ledger"):
        parse_claim_event(
            comment(
                2,
                marker(
                    {
                        "action": "supersede",
                        "agent": "Fleet Coordinator",
                        "claim_comment_id": acquired.comment.identifier,
                        "claim_id": acquired.claim_id,
                        "issue": LEDGER_ISSUE,
                        "reason": "invalid rollover",
                        "role": "coordinator",
                        "successor_issue": 70,
                    }
                ),
            )
        )

    assert len(client.list_protocol_candidates(LEDGER_ISSUE)) == protocol_count


def test_scope_overlap_is_repository_wide_and_path_aware() -> None:
    left = request(issue=71, scope=("frontend/src",))
    nested = request("claim-b", issue=72, scope=("frontend/src/lib/player.ts",))
    sibling = request("claim-c", issue=73, scope=("frontend/tests",))

    assert claims_conflict(left, nested)
    assert not claims_conflict(left, sibling)


def test_status_scope_index_never_rescans_scope_pairs(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    claims: list[ActiveClaim] = []
    for claim_index in range(50):
        parsed = parse_claim_event(
            comment(
                claim_index + 1,
                claim_comment(
                    request(
                        f"claim-{claim_index}",
                        issue=claim_index + 100,
                        scope=tuple(
                            f"area-{claim_index}/path-{scope_index}"
                            for scope_index in range(32)
                        ),
                    )
                ),
                created_at="2026-08-21T00:00:00Z",
            )
        )
        assert isinstance(parsed, ActiveClaim)
        claims.append(parsed)

    def scope_pair_scan(*args, **kwargs):
        pytest.fail("status must use its single scope index")

    monkeypatch.setattr(issue_claim, "claims_conflict", scope_pair_scan)

    assert _status(tuple(claims), None) == 0
    assert capsys.readouterr().out.count("CLAIMED") == 50
    assert _status(tuple(claims), 100) == 0
    assert capsys.readouterr().out.count("CLAIMED") == 1


def test_existing_scope_on_another_issue_refuses_before_posting() -> None:
    incumbent = comment(1, claim_comment(request(issue=71, scope=("shared",))))
    client = FakeComments({LEDGER_ISSUE: [incumbent]}, {71})

    with pytest.raises(ClaimUnavailable, match="on issue #71"):
        acquire_claim(
            client,
            request("challenger", "Grok 4.6", issue=72, scope=("shared/file.py",)),
        )

    assert len(client.comments[LEDGER_ISSUE]) == 1


def test_disjoint_issues_can_be_claimed_and_are_projected() -> None:
    client = FakeComments()

    first = acquire_claim(client, request(issue=72, scope=("frontend",)))
    second = acquire_claim(
        client,
        request("claim-b", "Grok 4.6", issue=73, scope=("src",)),
    )

    assert {first.issue, second.issue} == {72, 73}
    assert client.labels == {72, 73}
    assert "🔒 **Claimed**" in client.comments[72][0].body
    assert "🔒 **Claimed**" in client.comments[73][0].body


def test_owning_issue_projection_uses_the_configured_ledger_number(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claimed = parse_claim_event(comment(1, claim_comment(request(issue=72))))
    assert isinstance(claimed, ActiveClaim)
    monkeypatch.setattr(issue_claim, "LEDGER_ISSUE", 170)

    projection = issue_claim._active_projection(claimed)

    assert "ledger=170" in projection.partition("\n")[0]
    assert "ledger=71" not in projection.partition("\n")[0]
    assert claim_label() == "claimed:170"


def test_same_issue_refuses_a_second_claim_even_with_disjoint_scope() -> None:
    incumbent = comment(1, claim_comment(request(issue=72, scope=("frontend",))))
    client = FakeComments({LEDGER_ISSUE: [incumbent]}, {72})

    with pytest.raises(ClaimUnavailable, match="issue #72"):
        acquire_claim(
            client,
            request("claim-b", "Grok 4.6", issue=72, scope=("src",)),
        )


def test_earlier_ledger_comment_wins_cross_issue_scope_race_and_label_survives() -> None:
    client = FakeComments()
    earlier = comment(
        100,
        claim_comment(
            request("earlier", "Grok 4.6", issue=72, scope=("shared/file.py",))
        ),
        created_at="2026-08-20T23:59:59Z",
    )
    client.inject_after_next_ledger_post = earlier

    with pytest.raises(ClaimUnavailable, match="race lost to Grok 4.6"):
        acquire_claim(
            client,
            request("later", "Codex Sol", issue=73, scope=("shared",)),
        )

    standing = active_claims(tuple(client.comments[LEDGER_ISSUE]))
    assert [claim.claim_id for claim in standing] == ["earlier"]
    assert client.labels == {72}


def test_release_removes_projection_only_after_claim_is_gone() -> None:
    client = FakeComments()
    acquired = acquire_claim(client, request(issue=72))
    projection_id = client.comments[72][0].identifier

    released = release_claim(
        client,
        72,
        "Codex Sol",
        "builder",
        "landed",
        acquired.claim_id,
    )

    assert released.claim_id == "claim-a"
    assert active_claims(tuple(client.comments[LEDGER_ISSUE])) == ()
    assert client.labels == set()
    assert len(client.comments[72]) == 1
    assert client.comments[72][0].identifier == projection_id
    assert "🔓 **Unclaimed** · landed" in client.comments[72][0].body


def test_release_reconciliation_keeps_a_successor_claim_projection_active() -> None:
    client = FakeComments()
    acquired = acquire_claim(client, request(issue=72, scope=("old",)))
    successor = comment(
        4,
        claim_comment(request("successor", "Grok 4.6", issue=72, scope=("new",))),
    )
    client.inject_during_next_remove = successor

    release_claim(
        client,
        72,
        "Codex Sol",
        "builder",
        "landed",
        acquired.claim_id,
    )

    projection = client.comments[72][0]
    assert len(client.comments[72]) == 1
    assert "🔒 **Claimed**" in projection.body
    assert "Grok 4.6" in projection.body
    assert "codex/issue-72-claims" in projection.body
    assert "🔓 **Unclaimed**" not in projection.body
    assert client.labels == {72}


def test_projection_is_minimal_and_reuses_one_trusted_comment() -> None:
    client = FakeComments()
    acquired = acquire_claim(client, request(issue=72, scope=("private/path",)))
    first_projection = client.comments[72][0]
    duplicate = replace(first_projection, identifier=first_projection.identifier + 100)
    client.comments[72].append(duplicate)

    client.upsert_projection(72, issue_claim._active_projection(acquired))

    assert len(client.comments[72]) == 1
    projection = client.comments[72][0]
    assert projection.identifier == first_projection.identifier
    assert "private/path" not in projection.body
    assert acquired.base not in projection.body
    assert acquired.branch in projection.body


def test_reconcile_does_not_create_projection_for_never_claimed_issue() -> None:
    client = FakeComments()

    reconcile_issue_label(client, 999)

    assert client.comments.get(999, []) == []
    assert client.labels == set()


def test_claim_labels_are_isolated_by_ledger_generation() -> None:
    assert claim_label(71) == "claimed:71"
    assert claim_label(170) == "claimed:170"
    assert claim_label(71) != claim_label(170)


def test_successor_adopts_old_projection_but_old_helper_cannot_mutate_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(issue_claim, "LEDGER_ISSUE", 71)
    old_projection = comment(1, issue_claim._unclaimed_projection())
    old_duplicate = replace(old_projection, identifier=2)
    client = FakeComments({72: [old_projection, old_duplicate]})

    monkeypatch.setattr(issue_claim, "LEDGER_ISSUE", 170)
    successor_body = issue_claim._active_projection(
        ActiveClaim(
            72,
            "successor",
            "Codex Sol",
            "builder",
            BASE,
            "codex/issue-72-claims",
            ("scripts/issue_claim.py",),
            comment(3, claim_comment(request("successor", issue=72))),
        )
    )
    assert client.upsert_projection(72, successor_body, adopt_stale=True)
    assert len(client.comments[72]) == 1
    assert "ledger=170" in client.comments[72][0].body.partition("\n")[0]

    monkeypatch.setattr(issue_claim, "LEDGER_ISSUE", 71)
    with pytest.raises(ClaimError, match="newer ledger generation"):
        client.upsert_projection(72, issue_claim._unclaimed_projection(), create=False)
    assert len(client.comments[72]) == 1
    assert "ledger=170" in client.comments[72][0].body.partition("\n")[0]


def test_release_refuses_foreign_actor_without_explicit_override() -> None:
    client = FakeComments()
    acquired = acquire_claim(client, request(issue=72))

    with pytest.raises(ClaimUnavailable, match="original claimant"):
        release_claim(
            client,
            72,
            "Other",
            "builder",
            "takeover",
            acquired.claim_id,
        )


def test_label_reconciliation_heals_claim_posted_during_release_remove() -> None:
    old_claim_body = claim_comment(request("old", issue=72, scope=("old",)))
    old_claim = parse_claim_event(comment(1, old_claim_body))
    assert old_claim is not None
    release_body = release_event(old_claim)
    new_claim_comment = comment(
        3,
        claim_comment(request("new", issue=72, scope=("new",))),
    )
    client = FakeComments(
        {LEDGER_ISSUE: [comment(1, old_claim_body), comment(2, release_body)]},
        {72},
        inject_during_next_remove=new_claim_comment,
    )

    reconcile_issue_label(client, 72)

    assert [
        claim.claim_id
        for claim in active_claims(client.list_protocol_candidates(LEDGER_ISSUE))
    ] == ["new"]
    assert client.labels == {72}


def test_label_failure_is_loud_while_comment_truth_remains() -> None:
    client = FakeComments(fail_add_label=True)

    with pytest.raises(ClaimError, match="label add failed"):
        acquire_claim(client, request(issue=72))

    assert [
        claim.issue
        for claim in active_claims(client.list_protocol_candidates(LEDGER_ISSUE))
    ] == [72]


def test_reconcile_all_repairs_active_and_stale_labels() -> None:
    active = comment(1, claim_comment(request(issue=72)))
    client = FakeComments({LEDGER_ISSUE: [active]}, {73})

    observed = reconcile_all_labels(client)

    assert observed == (72,)
    assert client.labels == {72}


def test_stale_reconcile_removes_label_when_supersede_wins_midflight() -> None:
    claimed_body = claim_comment(request(issue=LEDGER_ISSUE))
    claimed = parse_claim_event(comment(1, claimed_body))
    assert isinstance(claimed, ActiveClaim)
    frozen = comment(
        2,
        supersede_comment(
            claimed,
            170,
            "Fleet Coordinator",
            "coordinator",
            "reviewed rollover ready",
        ),
    )
    client = FakeComments(
        {LEDGER_ISSUE: [comment(1, claimed_body)]},
        inject_during_next_add=frozen,
    )

    with pytest.raises(LedgerSuperseded):
        reconcile_issue_label(client, LEDGER_ISSUE)

    assert LEDGER_ISSUE not in client.labels
    with pytest.raises(LedgerSuperseded):
        active_claims(client.list_protocol_candidates(LEDGER_ISSUE))


def test_old_reconcile_clears_only_its_generation_label_after_freeze() -> None:
    claimed_body = claim_comment(request(issue=LEDGER_ISSUE))
    claimed = parse_claim_event(comment(1, claimed_body))
    assert isinstance(claimed, ActiveClaim)
    frozen = supersede_comment(
        claimed,
        170,
        "Fleet Coordinator",
        "coordinator",
        "reviewed rollover ready",
    )
    client = FakeComments(
        {LEDGER_ISSUE: [comment(1, claimed_body), comment(2, frozen)]},
        {LEDGER_ISSUE, 72},
        {claim_label(170): {170}},
    )

    with pytest.raises(LedgerSuperseded):
        reconcile_all_labels(client)
    assert client.labels == set()
    assert client.other_labels == {claim_label(170): {170}}

    client.labels.update({LEDGER_ISSUE, 170})
    with pytest.raises(LedgerSuperseded):
        reconcile_issue_label(client, 170)
    assert client.labels == {LEDGER_ISSUE}
    assert client.other_labels == {claim_label(170): {170}}


def test_paused_old_release_fails_frozen_without_mutating_successor_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(issue_claim, "LEDGER_ISSUE", 71)
    client = FakeComments(valid_successors={170})
    old_claim = acquire_claim(client, request("old", issue=72, scope=("old",)))
    client.post_comment(
        71,
        release_comment(old_claim, "Codex Sol", "builder", "landed"),
    )
    rollover = acquire_claim(
        client,
        request("rollover", issue=71, scope=("docs/COORDINATION.md",)),
    )
    supersede_ledger(
        client,
        170,
        "Fleet Coordinator",
        "coordinator",
        "reviewed successor ready",
        rollover.claim_id,
    )

    monkeypatch.setattr(issue_claim, "LEDGER_ISSUE", 170)
    acquire_claim(
        client,
        request("successor", "Grok 4.6", issue=72, scope=("new",)),
    )
    successor_projection = client.comments[72][0].body
    client.other_labels[claim_label(170)] = set(client.labels)
    client.labels.clear()

    monkeypatch.setattr(issue_claim, "LEDGER_ISSUE", 71)
    with pytest.raises(LedgerSuperseded, match="successor #170"):
        reconcile_issue_label(client, 72)

    assert client.comments[72][0].body == successor_projection
    assert client.other_labels == {claim_label(170): {72}}


def test_status_reports_repository_scope_conflicts(capsys: pytest.CaptureFixture[str]) -> None:
    first = parse_claim_event(
        comment(1, claim_comment(request(issue=72, scope=("shared",))))
    )
    second = parse_claim_event(
        comment(
            2,
            claim_comment(request("claim-b", issue=73, scope=("shared/file.py",))),
        )
    )
    assert first is not None and second is not None

    exit_code = _status((first, second), None)

    assert exit_code == 2
    assert capsys.readouterr().out.count("CONFLICT") == 2
    assert _status((first, second), 72) == 2
    assert capsys.readouterr().out.count("CONFLICT") == 2


def test_status_detects_a_scope_that_is_claimed_after_its_descendant(
    capsys: pytest.CaptureFixture[str],
) -> None:
    descendant = parse_claim_event(
        comment(1, claim_comment(request(issue=72, scope=("shared/file.py",))))
    )
    parent = parse_claim_event(
        comment(2, claim_comment(request("claim-b", issue=73, scope=("shared",))))
    )
    assert descendant is not None and parent is not None

    assert _status((descendant, parent), None) == 2
    assert capsys.readouterr().out.count("CONFLICT") == 2


def test_github_comment_reader_accepts_paginated_json_lines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ordinary_rows = [
        {
            "id": 10,
            "created_at": "2026-08-21T01:00:00Z",
            "updated_at": "2026-08-21T01:00:00Z",
            "body": "ordinary prose",
            "author_association": "OWNER",
            "html_url": "https://github.com/FlexOr2/songmaker/issues/71#issuecomment-10",
        },
        {
            "id": 11,
            "created_at": "2026-08-21T02:00:00Z",
            "updated_at": "2026-08-21T02:00:00Z",
            "body": "more ordinary prose",
            "author_association": "MEMBER",
            "html_url": "https://github.com/FlexOr2/songmaker/issues/71#issuecomment-11",
        },
    ]
    protocol_row = {
        "id": 12,
        "created_at": "2026-08-21T03:00:00Z",
        "updated_at": "2026-08-21T03:00:00Z",
        "body": claim_comment(request()),
        "author_association": "OWNER",
        "html_url": "https://github.com/FlexOr2/songmaker/issues/71#issuecomment-12",
    }
    client = GitHubIssueComments("FlexOr2/songmaker")
    monkeypatch.setattr(issue_claim, "COMMENTS_PER_PAGE", 2)

    def page(arguments: list[str]) -> str:
        endpoint = arguments[1]
        rows = ordinary_rows if "page=1" in endpoint else [protocol_row]
        return "\n".join(map(json.dumps, rows))

    monkeypatch.setattr(client, "_run", page)

    observed = client.list_protocol_candidates(71)

    assert [entry.identifier for entry in observed] == [12]
    assert observed[0].body == protocol_row["body"]


def test_fake_and_github_adapters_expose_only_common_protocol_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trusted = comment(1, claim_comment(request()))
    prose = comment(2, "ordinary prose")
    untrusted = comment(3, claim_comment(request("untrusted")), association="NONE")
    fake = FakeComments({LEDGER_ISSUE: [trusted, prose, untrusted]})
    assert fake.list_protocol_candidates(LEDGER_ISSUE) == (trusted,)

    rows = [
        {
            "id": entry.identifier,
            "created_at": entry.created_at,
            "updated_at": entry.updated_at,
            "body": entry.body,
            "author_association": entry.author_association,
            "html_url": entry.url,
        }
        for entry in (trusted, prose, untrusted)
    ]
    github = GitHubIssueComments("FlexOr2/songmaker")
    monkeypatch.setattr(github, "_run", lambda arguments: "\n".join(map(json.dumps, rows)))

    assert github.list_protocol_candidates(LEDGER_ISSUE) == (trusted,)


def test_comment_size_is_bounded_before_any_adapter_post() -> None:
    widest_scope = tuple(f"p{index:03d}-" + "x" * 507 for index in range(256))

    with pytest.raises(ClaimError, match=str(MAX_COMMENT_BYTES)):
        claim_comment(request(scope=widest_scope))


def test_github_comment_body_uses_stdin_instead_of_process_argument(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = GitHubIssueComments("FlexOr2/songmaker")
    observed: dict[str, object] = {}

    def run(arguments: list[str], *, input_data: bytes | None = None) -> str:
        observed["arguments"] = arguments
        observed["input"] = input_data
        return "https://github.com/FlexOr2/songmaker/issues/71#issuecomment-1"

    monkeypatch.setattr(client, "_run", run)
    body = claim_comment(request())

    client.post_comment(LEDGER_ISSUE, body)

    arguments = observed["arguments"]
    assert isinstance(arguments, list)
    assert body not in arguments
    assert arguments[-2:] == ["--body-file", "-"]
    assert observed["input"] == body.encode()


def test_github_projection_update_patches_one_comment_and_deletes_duplicates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = GitHubIssueComments("FlexOr2/songmaker")
    first = comment(10, issue_claim._unclaimed_projection())
    duplicate = replace(first, identifier=11)
    monkeypatch.setattr(client, "_projection_comments", lambda issue: (first, duplicate))
    observed: list[tuple[list[str], bytes | None]] = []

    def run(arguments: list[str], *, input_data: bytes | None = None) -> str:
        observed.append((arguments, input_data))
        return ""

    monkeypatch.setattr(client, "_run", run)
    body = issue_claim._active_projection(
        ActiveClaim(
            72,
            "claim-a",
            "Codex Sol",
            "builder",
            BASE,
            "codex/issue-72-claims",
            ("scripts/issue_claim.py",),
            comment(9, claim_comment(request(issue=72))),
        )
    )

    assert client.upsert_projection(72, body)
    assert observed[0][0] == [
        "api",
        "--method",
        "PATCH",
        "repos/FlexOr2/songmaker/issues/comments/10",
        "--input",
        "-",
    ]
    assert observed[0][1] == json.dumps({"body": body}).encode("utf-8")
    assert observed[1] == (
        [
            "api",
            "--method",
            "DELETE",
            "repos/FlexOr2/songmaker/issues/comments/11",
        ],
        None,
    )


def test_github_projection_update_does_not_create_on_a_never_claimed_issue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = GitHubIssueComments("FlexOr2/songmaker")
    monkeypatch.setattr(client, "_projection_comments", lambda issue: ())
    monkeypatch.setattr(
        client,
        "post_comment",
        lambda issue, body: pytest.fail("reconcile must not create a projection"),
    )

    assert not client.upsert_projection(999, issue_claim._unclaimed_projection(), create=False)


def test_github_successor_adopts_stale_projection_but_old_generation_skips_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = GitHubIssueComments("FlexOr2/songmaker")
    monkeypatch.setattr(issue_claim, "LEDGER_ISSUE", 71)
    stale = comment(10, issue_claim._unclaimed_projection())
    monkeypatch.setattr(issue_claim, "LEDGER_ISSUE", 171)
    future = comment(11, issue_claim._unclaimed_projection())
    monkeypatch.setattr(client, "_projection_comments", lambda issue: (stale, future))
    observed: list[tuple[list[str], bytes | None]] = []

    def run(arguments: list[str], *, input_data: bytes | None = None) -> str:
        observed.append((arguments, input_data))
        return ""

    monkeypatch.setattr(client, "_run", run)
    monkeypatch.setattr(issue_claim, "LEDGER_ISSUE", 170)
    successor_body = issue_claim._unclaimed_projection()

    assert client.upsert_projection(72, successor_body, adopt_stale=True)
    assert observed == [
        (
            [
                "api",
                "--method",
                "PATCH",
                "repos/FlexOr2/songmaker/issues/comments/10",
                "--input",
                "-",
            ],
            json.dumps({"body": successor_body}).encode("utf-8"),
        )
    ]

    monkeypatch.setattr(issue_claim, "LEDGER_ISSUE", 71)
    successor = replace(stale, body=successor_body)
    monkeypatch.setattr(client, "_projection_comments", lambda issue: (successor,))
    observed.clear()
    with pytest.raises(ClaimError, match="newer ledger generation"):
        client.upsert_projection(72, issue_claim._unclaimed_projection(), create=False)
    assert observed == []


def test_github_claimed_issue_query_is_scoped_to_this_ledger_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = GitHubIssueComments("FlexOr2/songmaker")
    observed: list[str] = []

    def run(arguments: list[str], *, input_data: bytes | None = None) -> str:
        assert input_data is None
        observed.extend(arguments)
        return "72\n73"

    monkeypatch.setattr(client, "_run", run)

    assert client.list_claimed_issues() == (72, 73)
    assert (
        f"repos/FlexOr2/songmaker/issues?state=all&labels={claim_label()}&per_page=100"
        in observed
    )
    assert "--paginate" in observed


def test_github_successor_must_exist_open_empty_locked_and_not_be_a_pr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = GitHubIssueComments("FlexOr2/songmaker")
    valid = {
        "number": 170,
        "state": "open",
        "locked": True,
        "comments": 0,
        "is_pull_request": False,
    }
    monkeypatch.setattr(client, "_run", lambda arguments: json.dumps(valid))

    client.validate_successor(170)

    for key, value in (
        ("number", 999999),
        ("state", "closed"),
        ("locked", False),
        ("comments", 1),
        ("is_pull_request", True),
    ):
        invalid = {**valid, key: value}
        monkeypatch.setattr(client, "_run", lambda arguments, row=invalid: json.dumps(row))
        with pytest.raises(ClaimUnavailable, match="open, empty, collaborator-locked"):
            client.validate_successor(170)


@pytest.mark.parametrize(
    "raw",
    [
        "not-json",
        json.dumps([]),
        json.dumps({"id": "wrong"}),
        json.dumps(
            {
                "id": 1,
                "created_at": "not-time",
                "updated_at": "not-time",
                "body": "body",
                "author_association": "OWNER",
                "html_url": "https://github.com/example",
            }
        ),
    ],
)
def test_github_comment_reader_wraps_invalid_json_and_schema(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    client = GitHubIssueComments("FlexOr2/songmaker")
    monkeypatch.setattr(client, "_run", lambda arguments: raw)

    with pytest.raises(ClaimError):
        client.list_protocol_candidates(71)


def test_missing_gh_repository_resolution_is_a_controlled_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", missing)

    with pytest.raises(ClaimError, match="gh is required"):
        _repository(None)


def test_bounded_command_stops_before_unbounded_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(issue_claim, "MAX_COMMAND_OUTPUT_BYTES", 32)

    with pytest.raises(ClaimError, match="output limit"):
        issue_claim._bounded_command(
            [sys.executable, "-c", "print('x' * 1000)"],
            purpose="test command",
        )


def test_bounded_command_streams_stdin_without_putting_it_in_argv() -> None:
    observed = issue_claim._bounded_command(
        [sys.executable, "-c", "import sys; print(sys.stdin.buffer.read().decode())"],
        purpose="stdin probe",
        input_data=b"bounded body",
    )

    assert observed == "bounded body"


def test_bounded_command_wraps_process_argument_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def cannot_start(*args, **kwargs):
        raise OSError(7, "Argument list too long")

    monkeypatch.setattr(subprocess, "Popen", cannot_start)

    with pytest.raises(ClaimError, match="cannot start test command"):
        issue_claim._bounded_command(["gh", "issue"], purpose="test command")


def test_bounded_command_wraps_stdin_write_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def cannot_write(*args, **kwargs):
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(issue_claim.os, "write", cannot_write)

    with pytest.raises(ClaimError, match="failed while sending bounded input"):
        issue_claim._bounded_command(
            [sys.executable, "-c", "import sys; sys.stdin.buffer.read()"],
            purpose="stdin write probe",
            input_data=b"body",
        )


def test_bounded_command_reaps_child_when_selector_setup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, subprocess.Popen[bytes]] = {}
    original_popen = subprocess.Popen

    def start(*arguments, **kwargs):
        process = original_popen(*arguments, **kwargs)
        observed["process"] = process
        return process

    def cannot_select():
        raise OSError(5, "selector failed")

    monkeypatch.setattr(subprocess, "Popen", start)
    monkeypatch.setattr(issue_claim.selectors, "DefaultSelector", cannot_select)

    with pytest.raises(ClaimError, match="failed while coordinating I/O"):
        issue_claim._bounded_command(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            purpose="selector setup probe",
        )

    assert observed["process"].poll() is not None
    assert observed["process"].stdout is not None
    assert observed["process"].stdout.closed


def test_bounded_command_reaps_child_when_select_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, subprocess.Popen[bytes]] = {}
    original_popen = subprocess.Popen

    def start(*arguments, **kwargs):
        process = original_popen(*arguments, **kwargs)
        observed["process"] = process
        return process

    class FailingSelector:
        instance: FailingSelector | None = None

        def __init__(self) -> None:
            self.closed = False
            FailingSelector.instance = self

        def register(self, fileobj, events, data) -> None:
            pass

        def get_map(self):
            return {"stdout": object()}

        def select(self, timeout):
            raise OSError(5, "select failed")

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(subprocess, "Popen", start)
    monkeypatch.setattr(issue_claim.selectors, "DefaultSelector", FailingSelector)

    with pytest.raises(ClaimError, match="failed while waiting for I/O"):
        issue_claim._bounded_command(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            purpose="select probe",
        )

    process = observed["process"]
    assert process.poll() is not None
    assert process.stdout is not None and process.stdout.closed
    assert FailingSelector.instance is not None and FailingSelector.instance.closed


def test_bounded_command_reaps_child_when_output_read_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, subprocess.Popen[bytes]] = {}
    original_popen = subprocess.Popen
    original_read = issue_claim.os.read

    def start(*arguments, **kwargs):
        process = original_popen(*arguments, **kwargs)
        observed["process"] = process
        return process

    def cannot_read(file_descriptor: int, count: int) -> bytes:
        process = observed.get("process")
        if (
            process is not None
            and process.stdout is not None
            and file_descriptor == process.stdout.fileno()
        ):
            raise OSError(5, "read failed")
        return original_read(file_descriptor, count)

    monkeypatch.setattr(subprocess, "Popen", start)
    monkeypatch.setattr(issue_claim.os, "read", cannot_read)

    with pytest.raises(ClaimError, match="failed while reading output"):
        issue_claim._bounded_command(
            [
                sys.executable,
                "-u",
                "-c",
                "import time; print('ready'); time.sleep(30)",
            ],
            purpose="read probe",
        )

    assert observed["process"].poll() is not None
    assert observed["process"].stdout is not None
    assert observed["process"].stdout.closed


def test_bounded_command_reaps_child_on_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, subprocess.Popen[bytes]] = {}
    original_popen = subprocess.Popen

    def start(*arguments, **kwargs):
        process = original_popen(*arguments, **kwargs)
        observed["process"] = process
        return process

    class CancellationSentinel(BaseException):
        pass

    class CancellingSelector:
        def register(self, fileobj, events, data) -> None:
            pass

        def get_map(self):
            return {"stdout": object()}

        def select(self, timeout):
            raise CancellationSentinel

        def close(self) -> None:
            pass

    monkeypatch.setattr(subprocess, "Popen", start)
    monkeypatch.setattr(issue_claim.selectors, "DefaultSelector", CancellingSelector)

    with pytest.raises(CancellationSentinel):
        issue_claim._bounded_command(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            purpose="cancellation probe",
        )

    assert observed["process"].poll() is not None
    assert observed["process"].stdout is not None
    assert observed["process"].stdout.closed


def test_checkout_validation_binds_clean_head_and_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = {
        ("rev-parse", "HEAD"): BASE,
        ("branch", "--show-current"): "codex/issue-71-claims",
        ("rev-parse", "--git-dir"): "/repo/.git/worktrees/issue-71",
        ("rev-parse", "--git-common-dir"): "/repo/.git",
        ("status", "--porcelain"): "",
    }
    monkeypatch.setattr(issue_claim, "_git_output", lambda arguments: values[tuple(arguments)])

    issue_claim._validate_checkout(request())


@pytest.mark.parametrize(
    ("candidate", "values", "message"),
    [
        (
            request(),
            {
                ("rev-parse", "HEAD"): "b" * 40,
                ("branch", "--show-current"): "codex/issue-71-claims",
                ("rev-parse", "--git-dir"): "/repo/.git/worktrees/issue-71",
                ("rev-parse", "--git-common-dir"): "/repo/.git",
                ("status", "--porcelain"): "",
            },
            "does not match checkout HEAD",
        ),
        (
            request(),
            {
                ("rev-parse", "HEAD"): BASE,
                ("branch", "--show-current"): "other",
                ("rev-parse", "--git-dir"): "/repo/.git/worktrees/issue-71",
                ("rev-parse", "--git-common-dir"): "/repo/.git",
                ("status", "--porcelain"): "",
            },
            "does not match checkout branch",
        ),
        (
            request(),
            {
                ("rev-parse", "HEAD"): BASE,
                ("branch", "--show-current"): "codex/issue-71-claims",
                ("rev-parse", "--git-dir"): "/repo/.git",
                ("rev-parse", "--git-common-dir"): "/repo/.git",
                ("status", "--porcelain"): "",
            },
            "linked isolated worktree",
        ),
        (
            request(),
            {
                ("rev-parse", "HEAD"): BASE,
                ("branch", "--show-current"): "codex/issue-71-claims",
                ("rev-parse", "--git-dir"): "/repo/.git/worktrees/issue-71",
                ("rev-parse", "--git-common-dir"): "/repo/.git",
                ("status", "--porcelain"): " M file",
            },
            "before the first worktree edit",
        ),
    ],
)
def test_checkout_validation_rejects_false_or_late_claims(
    monkeypatch: pytest.MonkeyPatch,
    candidate: ClaimRequest,
    values: dict[tuple[str, str], str],
    message: str,
) -> None:
    monkeypatch.setattr(issue_claim, "_git_output", lambda arguments: values[tuple(arguments)])

    with pytest.raises(ClaimError, match=message):
        issue_claim._validate_checkout(candidate)


def test_cli_status_claim_release_and_adapter_error_exit_codes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = FakeComments()
    monkeypatch.setattr(issue_claim, "GitHubIssueComments", lambda repository: client)
    monkeypatch.setattr(issue_claim, "_validate_checkout", lambda request: None)

    claimed = issue_claim.main(
        [
            "--repo",
            "FlexOr2/songmaker",
            "claim",
            "72",
            "--agent",
            "Codex Sol",
            "--role",
            "builder",
            "--base",
            BASE,
            "--branch",
            "codex/issue-72",
            "--scope",
            "src",
            "--claim-id",
            "cli-claim",
        ]
    )
    status = issue_claim.main(["--repo", "FlexOr2/songmaker", "status", "72"])
    released = issue_claim.main(
        [
            "--repo",
            "FlexOr2/songmaker",
            "release",
            "72",
            "--agent",
            "Codex Sol",
            "--role",
            "builder",
            "--reason",
            "landed",
            "--claim-id",
            "cli-claim",
        ]
    )

    assert (claimed, status, released) == (0, 0, 0)
    assert "CLAIMED issue #72" in capsys.readouterr().out

    monkeypatch.setattr(
        issue_claim,
        "GitHubIssueComments",
        lambda repository: (_ for _ in ()).throw(ClaimError("adapter failed")),
    )
    assert issue_claim.main(["--repo", "FlexOr2/songmaker", "status"]) == 2
    assert "ERROR: adapter failed" in capsys.readouterr().err


def test_cli_supersede_freezes_ledger_and_clears_projection(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = FakeComments(valid_successors={170})
    monkeypatch.setattr(issue_claim, "GitHubIssueComments", lambda repository: client)
    monkeypatch.setattr(issue_claim, "_validate_checkout", lambda request: None)
    claimed = issue_claim.main(
        [
            "--repo",
            "FlexOr2/songmaker",
            "claim",
            str(LEDGER_ISSUE),
            "--agent",
            "Fleet Coordinator",
            "--role",
            "coordinator",
            "--base",
            BASE,
            "--branch",
            "codex/ledger-rollover",
            "--scope",
            "docs/COORDINATION.md",
            "--claim-id",
            "rollover",
        ]
    )

    frozen = issue_claim.main(
        [
            "--repo",
            "FlexOr2/songmaker",
            "supersede",
            "170",
            "--agent",
            "Fleet Coordinator",
            "--role",
            "coordinator",
            "--reason",
            "reviewed successor ready",
            "--claim-id",
            "rollover",
        ]
    )

    assert (claimed, frozen) == (0, 0)
    assert LEDGER_ISSUE not in client.labels
    assert "SUPERSEDED ledger #71 with #170" in capsys.readouterr().out
