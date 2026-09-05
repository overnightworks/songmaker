# Repository agent guidance

- Before every repository edit, use the globally installed `agent-claim` CLI
  to check the live ledger and claim the exact write scope. Subagents remain
  within their parent's live claim and do not take overlapping claims.
- Work autonomously within the operator-authorized scope. Prefer the clean,
  maintainable long-term result, exhaust safe executable work before asking,
  and keep blocked lanes from stopping unrelated claimed work.
- Keep the shared `main` checkout clean. Build in an isolated external worktree
  and never touch another head's claimed scope.
- The Atelier Auto-Runner is deprecated legacy. Never enable, arm, restore,
  recommend, or use it for fleet coordination.
- Test albums (verify, proof, throwaway, QA runs) get a recognizable name
  prefix and are archived — not deleted — once their purpose is verified, so
  the library stays clean without discarding evidence.
- An item's kind is GitHub's native issue type from the `overnightworks`
  organization (discoverable via `gh api graphql` on
  `organization(login:"overnightworks"){ issueTypes }`): `Container` for an
  epic or distributor holding slices, `Task` for a buildable slice, `Bug` and
  `Feature` as named; the coordination ledger issue (#71) stays untyped.
  - A slice's parent is GitHub's sub-issue relation, never a line in the
    body — `Nachbarn`/"parent" prose is orientation only; a landing that
    closes a parent's last open child closes the parent, and a parentless
    slice title gets a warning.
  - Set both right after `gh issue create` via `gh api graphql`
    (`updateIssue`, `addSubIssue`) — `gh issue edit` fails here with a
    Projects-classic GraphQL error.
