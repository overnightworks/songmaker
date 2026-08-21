# Repository agent guidance

- Before any repository edit, read `docs/COORDINATION.md`, search open and
  closed GitHub issues, and acquire then re-check the repository-wide build
  claim. Read-only exploration and independent review remain parallel.
- Work autonomously within the operator-authorized scope. Prefer the clean,
  maintainable long-term result, exhaust safe executable work before asking,
  and keep blocked lanes from stopping unrelated claimed work.
- Keep the shared `main` checkout clean. Build in an isolated external worktree
  and never touch another head's claimed scope.
- The Atelier Auto-Runner is deprecated legacy. Never enable, arm, restore,
  recommend, or use it for fleet coordination.
