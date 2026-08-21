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
