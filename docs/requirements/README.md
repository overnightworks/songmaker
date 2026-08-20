# Requirements

Audience: the operator deciding intent, and the engineer or agent changing the
product. This page owns the offline document contract;
[`revisions.toml`](revisions.toml) owns active revision history.

Songmaker is currently a greenfield requirement shelf: there are no numbered
requirement documents and therefore no approved normative product claims. The
non-normative [vision](../VISION.md) is only an overview of existing repository
descriptions.

## Information owners

- GitHub issues own drafts, discussion, candidates, and `DECISION_REQUIRED`.
- An active registry tip owns approved normative product intent.
- [`acceptance.toml`](../acceptance/acceptance.toml) owns each
  Acceptance→Requirement edge.
- Tests and executed reports will own Test→Acceptance proof under issue #42.
- Architecture, security, API schemas, and test documentation retain their
  existing technical ownership.
- [PRODUCT](../PRODUCT.md) is an exact derived count view and currently makes no
  implementation claim.

No reverse lists copy these facts into requirement documents.

## Strict document contract

A numbered document is a regular, non-symlink UTF-8 file directly under this
directory. Its name starts with a four-digit document ID and it has exactly this
shape:

```markdown
# <nonempty title>

## Intent

<nonempty intent>

## Rules

### REQ-<AREA>-<nn>: <nonempty, atomic, testable, solution-independent sentence>
Quelle: OPERATOR|DESK — <nonempty source pointer>

## Non-goals

<optional, but nonempty when present>
```

Only `Intent`, `Rules`, and optional `Non-goals` are valid. Rule IDs are global
and never reused. `OPERATOR` identifies an exact operator statement;
interpretation and engineering consequence are `DESK`. Review judges meaning;
the offline gate judges only structure and byte bindings.

## Revision lifecycle

Each future revision records one document path, the SHA-256 of its exact bytes,
a positive globally unique approval-comment ID, the SHA-256 of the exact ASCII
line `APPROVE REQUIREMENT REVISION NNNN sha256:<content-digest>`, and either
`GENESIS` or its predecessor digest. A document has one fixed path, a complete
unbranched lineage, and exactly one tip whose digest matches the current file.

Approval is a procedural human STOP ritual for this single-operator repository.
This offline foundation does not call GitHub and cannot prove that the recorded
comment exists, is unedited, belongs to the configured account, or was authored
by a human. Live binding and witness verification require a separate
security-reviewed slice before the first active revision.

Pull-request and push runs compare against the exact event base commit with full
Git history. Existing revision-record fields remain identical while history
grows by a valid successor. TOML whitespace is not an owned fact. There is no
`HEAD^` fallback. Local snapshot checks must explicitly pass `--current-only`.
`workflow_dispatch` performs an explicitly current-only check. The separate
workflow is visible but is not an enforced merge gate while issue #31 remains
open.

## Acceptance boundary

The acceptance manifest may declare `ACC-<AREA>-<nn>`, one observable sentence,
one or more active REQ IDs, a proof kind (`unit`, `integration`, `browser`, or
`operator`), and whether it is critical. This foundation validates the schema
and Acceptance→Requirement edges only. It does not scan tests, consume run
reports, or claim proof; those capabilities belong to issue #42.

<!-- requirement-gate-bound:start -->
```text
proves: every numbered requirement is a regular UTF-8 file whose exact bytes match its sole active registry tip
proves: every revision lineage is predecessor-complete, unbranched, and has exactly one tip on one fixed path
proves: with an exact VCS base, existing revision fields cannot be changed, deleted, or restarted
proves: every acceptance edge names an active requirement rule
proves: PRODUCT is the exact derived count view of the current offline contract
does not prove: that a configured approval comment exists, is unedited, or came from a human
does not prove: that an acceptance sentence is meaningful or that any test ran
does not fetch: GitHub or another live authority
```
<!-- requirement-gate-bound:end -->
