# Coordination

Audience: every agent head that plans, builds, reviews, or lands work in this
repository. GitHub Issues are the live queue and the durable handoff surface.
This file owns the working agreement. Standing issue #71 is the serialized
repository-wide claim ledger; each owning issue has one minimal status comment
that the helper updates in place.

## Before work

Search open and closed issues before creating an item. One product subject has
one owning issue; sharpen that issue or add a dependency instead of creating a
twin.

Read-only exploration, planning, and independent review may run in parallel.
Any repository edit requires an exclusive build claim on the owning issue and
its repository-relative write scope before the first write. Immediately before
building, read the repository-wide live claim state again.

Use the helper from the repository root:

```bash
python scripts/issue_claim.py status
python scripts/issue_claim.py status 71
python scripts/issue_claim.py claim 71 \
  --agent "Codex Sol" \
  --role builder \
  --base "$(git rev-parse HEAD)" \
  --branch codex/issue-71-github-claims \
  --scope docs/COORDINATION.md \
  --scope CLAUDE.md
python scripts/issue_claim.py release 71 \
  --agent "Codex Sol" \
  --role builder \
  --reason "landed"
```

`supersede` is reserved for the reviewed ledger-rollover procedure below; it is
not a normal release or handoff command.

The helper refuses a claim unless the current checkout is clean, its `HEAD`
equals the supplied base, and its non-main branch equals the supplied branch.
The claim records that base, branch, and allowed write scope. Never put an
absolute local path, secret, credential, process detail, or private machine fact
in a public comment. A branch is not a claim and an assigned issue is not a
claim. `status` without an issue shows every active repository claim and exits
nonzero on overlapping scopes.

## While claimed

- One issue has at most one active build claim. Claims on different issues may
  coexist only when their write scopes do not overlap by path or parent path.
- The claimant works in an isolated worktree outside the shared `main`
  checkout. Check `git worktree list` before creating it.
- No other builder edits the claimed scope. An overlapping task waits, narrows
  its scope on another issue, or reviews the active candidate read-only.
- The claim stays active through implementation, review, CI, and landing. A
  frozen candidate is still claimed.
- Reviewers bind verdicts to the exact candidate commit or frozen digest. A
  reviewer does not take the build claim and does not write the candidate.
- New scope requires a visible full claim replacement before touching it. A
  surprising owner or product decision stops the build and returns to the
  issue.

Concurrent claim attempts are serialized on #71 and resolved by GitHub order:
the earlier trusted ledger comment wins. The losing helper posts its own
release, reconciles the issue projection, and refuses to build. Protocol
markers are recognized only as the exact first line of a trusted repository
owner, member, or collaborator comment; quoted examples and untrusted comments
are inert. Edited or malformed trusted protocol events fail loud.

## Release and handoff

Release only after the work landed, was explicitly abandoned, or was handed
off in a visible issue comment. Claims do not expire silently. A normal release
must name the same agent and role as the claim. Before taking over an apparently
abandoned claim, a coordinator checks the issue, PRs, remote branch, and listed
worktrees, then uses `--role coordinator --coordinator-override`; that event is
bound to the original claim-comment id and records the reason.

Changing scope is a new precedence decision: release the old claim and acquire
a new full claim before touching the additional path. Do not publish an
informal scope addendum that the helper cannot enforce.

The ledger-specific `claimed:71` label and the owning issue's single status
comment are projections. The status comment contains only lock state, owner,
role, branch, and a ledger link; release updates that same comment instead of
adding another. Exact first-line events on #71 retain full scope and history as
the source of truth. If a projection mutation fails, the command fails loud
while the ledger remains authoritative; run `issue_claim.py reconcile [issue]`
after resolving the GitHub failure. Every ledger event ends with an honest
`Agent: <model> (<role>)` attribution. It is procedural authorship, not a
cryptographic signature: the operator and all agent heads use one GitHub
account.

## Ledger lifecycle

After this helper lands, lock #71 to collaborators so public prose cannot grow
the operational ledger. The helper reads one 100-comment page at a time through
a hard 8 MiB process-output bound; it retains only trusted first-line protocol
events. It refuses beyond 100 pages, 4,096 protocol events, or 8 MiB of protocol
bytes and warns from page 80 onward. Outgoing comment bodies have a separate
48 KiB bound and travel over stdin, never as a command-line argument.

Board hygiene checks this size before the warning boundary. Rollover is an
explicit reviewed change, never silent compaction or an in-flight lane transfer:

1. Drain every active build lane, then acquire the only remaining claim on the
   current ledger for its own rollover. Dirty lanes are not frozen or migrated.
2. Create and collaborator-lock a successor whose issue number is greater than
   the current ledger. Change the one `LEDGER_ISSUE` constant plus this document
   under the rollover claim; this also selects a distinct `claimed:<successor>`
   projection label. Complete independent review and required CI. The helper
   verifies immediately before publication that the successor exists, is open,
   has no comments, is not a pull request, and is locked.
3. Immediately before landing, run `supersede` as coordinator. Its terminal
   event is bound to the rollover claim and successor issue, is valid only while
   that is the sole active claim, and atomically freezes the old ledger. Every
   helper still targeting it then fails closed with the successor number.
4. Land the already-reviewed change. New work claims only the empty successor.

The old issue remains a locked immutable archive; no history is copied or
rewritten and no old/new ledger accepts work concurrently. Labels are scoped
to their ledger generation, so a stale old helper cannot remove a successor's
valid projection. Status comments carry the same monotone generation marker. A
current successor helper may adopt one trusted old-generation status comment by
updating its marker, then removes duplicate status comments; it never adopts or
deletes a future-generation marker. An old helper matches only its own marker
and fails closed after the terminal event before it can alter the successor
view. If removing the old generation label fails after the terminal event
landed, rerun the identical `supersede` command: it recognizes the same event,
retries only that projection, and does not post another terminal event. A
competing claim ordered before the terminal event makes that attempt an inert
rejected event; the command fails without poisoning normal use of the old
ledger.

## Landing

Product work lands through a pull request after targeted local verification,
an independent exact-object review, and required remote CI. The builder does
not approve its own object. Update the owning issue with the landed commit and
remaining gates, then release the claim and remove its worktree when safe.

The Atelier Auto-Runner is deprecated legacy. It is never enabled, restored,
recommended, or used for Songmaker coordination. Claims coordinate humans and
agent heads; they do not allocate or execute work automatically.
