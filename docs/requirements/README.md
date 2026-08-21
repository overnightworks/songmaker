# Requirements

Audience: the operator deciding intent, and the engineer or agent changing the
product. This page owns the offline document contract;
[`revisions.toml`](revisions.toml) owns active revision history, and the
`witnesses/` directory owns the exact captured GitHub approval evidence.

Songmaker's requirement shelf contains approved normative product claims. The
active registry tips, not this page, state their exact current set. The
non-normative [vision](../VISION.md) remains an overview of product direction.

## Information owners

- GitHub issues own drafts, discussion, candidates, and `DECISION_REQUIRED`.
- An active registry tip owns approved normative product intent.
- [`acceptance.toml`](../acceptance/acceptance.toml) owns each
  Acceptance→Requirement edge.
- #42-A1 owns one Test→Acceptance integration claim and its point-in-time CI
  report; browser and E2E evidence remain separately approved future work.
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
one `docs/requirements/witnesses/<comment-id>.json` path, the SHA-256 of that
exact witness file, and either `GENESIS` or its predecessor digest. A document
has one fixed path, a complete unbranched lineage, and exactly one tip whose
digest matches the current file. One comment can bind only one revision.

A witness is a strict, size-bounded JSON object. It binds the numeric repository,
issue, comment, and operator-account identities; repository full name; exact
GitHub creation/update timestamps; and base64 plus SHA-256 of the exact ASCII
line `APPROVE REQUIREMENT REVISION NNNN sha256:<content-digest>`. Creation and
update timestamps must be identical. Unknown, missing, duplicate, malformed,
oversized, noncanonical, symlinked, or unregistered data fail closed.

The offline gate does not call GitHub. The separate live witness gate re-fetches
the fixed repository, issue, and comment resources over verified TLS from fixed
GitHub API routes and cross-checks their numeric identities, URLs, author,
timestamps, and body against every witness. That result is point-in-time proof:
an approval can be edited or deleted later. Edited/deleted comment events,
pushes, same-repository pull requests, a weekly schedule, and manual dispatch
rerun the live check. Fork pull requests deliberately skip the token-bearing
job while the offline pull-request gate still runs.

Approval is an account-bound authorization step, not proof of a human action.
The repository operator may post it directly or explicitly delegate it to the
coordinating agent. Under delegation, the exact candidate bytes first require
independent semantic and trace reviews; a neighboring issue comment discloses
the delegation, agent, digest, and review results before the coordinator posts
the exact authorization line. This procedural disclosure is reviewable but not
machine-enforced. The local binder revalidates GitHub immediately before
writing, and a pushed commit still must pass the live check. This repository
contains account-bound approval witnesses and active revisions. Those artifacts
prove authorization, not human authorship or implementation.

## Binding ritual

Use an isolated worktree whose HEAD has a green offline contract. Create a
Genesis candidate, or edit the existing fixed path for a successor, as the only
worktree delta. The binder accepts the narrower safe filename subset
`docs/requirements/NNNN-[a-z0-9][a-z0-9-]*.md`; the Git index must remain exactly
HEAD. This candidate-only window is deliberately red locally and must never be
committed by itself.

Review the exact candidate bytes and calculate their SHA-256. Obtain the
independent reviews required by the owning issue. When approval is delegated,
first post the disclosure described above. Then post one GitHub issue comment
from the configured authorization account containing only:

```text
APPROVE REQUIREMENT REVISION NNNN sha256:<content-digest>
```

Then run:

```bash
GITHUB_TOKEN=... python scripts/bind_requirement_revision.py \
  --path docs/requirements/NNNN-slug.md \
  --issue-number <issue-number> \
  --comment-id <approval-comment-id>
```

The command derives `GENESIS` or the sole predecessor itself. It validates the
green HEAD baseline; exact candidate-only Git state; requirement grammar; fresh
repository, issue, and unedited comment evidence; the complete planned contract;
Acceptance edges; and derived PRODUCT bytes. It performs no GitHub write,
comment, commit, push, or merge. Success means only `local binding prepared`:
review the complete four-file-or-smaller diff, commit and push it, and wait for
the point-in-time `Requirement witnesses` check before treating it as landed.

The binder holds a worktree-local lock through its prepared-success output and
has a 120-second parent/worker wall guard. A private inherited pipe terminates
the worker group if its supervisor disappears. It installs a new witness without
clobbering an existing path, preserves
the concrete Registry/PRODUCT mode bits, and rolls ordinary failures back to the
original candidate-only snapshot. Its cooperative concurrency boundary does not
claim protection from a hostile process running as the same OS user. A forced
kill can leave the original candidate-only state, a partial fail-closed red
state, or the fully prevalidated green state. Exit code 2 or a recovery message
means do not retry blindly: inspect `git status`, the candidate, Registry,
PRODUCT, Witness directory, and offline gate result first. A wall timeout also
returns exit code 2 because interruption can leave a partial state. The binder never
overwrites bytes it no longer recognizes as its own.

Pull-request and push runs compare against the exact event base commit with full
Git history. Existing revision-record fields remain identical while history
grows by a valid successor. TOML whitespace is not an owned fact. There is no
`HEAD^` fallback. Local snapshot checks must explicitly pass `--current-only`.
`workflow_dispatch` performs an explicitly current-only check. The separate
workflow is visible but is not an enforced merge gate. Branch protection must
require it before documentation may describe it that way.

## Acceptance boundary

The acceptance manifest may declare `ACC-<AREA>-<nn>`, one observable sentence,
one or more active REQ IDs, a proof kind (`unit`, `integration`, `browser`, or
`operator`), and whether it is critical. This foundation validates the schema
and Acceptance→Requirement edges only. It does not scan tests, consume run
reports, or claim proof. #42-A1 separately validates one literal Pytest
integration claim and publishes its point-in-time CI report; it does not imply
browser, E2E, or whole-product evidence.

<!-- requirement-gate-bound:start -->
```text
proves: every numbered requirement is a regular UTF-8 file whose exact bytes match its sole active registry tip
proves: every revision lineage is predecessor-complete, unbranched, and has exactly one tip on one fixed path
proves: with an exact VCS base, existing revision fields cannot be changed, deleted, or restarted
proves: every revision points to exact offline witness bytes for its approval line
proves: every acceptance edge names an active requirement rule
proves: PRODUCT is the exact derived count view of the current offline contract
does not prove: that a configured approval comment still exists or remains unedited on GitHub
does not prove: that the GitHub account action came from a human
does not prove: that an acceptance sentence is meaningful or that any test ran
does not fetch: GitHub or another live authority
```
<!-- requirement-gate-bound:end -->
