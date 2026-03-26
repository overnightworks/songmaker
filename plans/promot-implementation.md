# Implement a Plan

Read `CLAUDE.md` first — it has the conventions, check commands, and patterns. Then read the plan file the user specifies.

If the plan references things that have changed (files moved, APIs renamed, coverage numbers shifted), adapt. If something is fundamentally wrong or contradicts a design decision, flag it. Use your judgment on the difference.

Implement the plan. Ship tests with code. Run all checks from CLAUDE.md when you're done. Fix what breaks. Don't commit — the user will.

Keep changes minimal. Don't refactor surrounding code, don't add things the plan doesn't ask for, don't "improve" what's already working. If you discover something the plan didn't anticipate and the right call isn't obvious, ask.
