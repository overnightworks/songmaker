# Review an Implementation

Read `CLAUDE.md` for the project's conventions. Then read every changed file via `git diff HEAD~1` — don't skip anything.

Run all checks yourself. If they fail, that's a finding.

Look for:
- Bugs, logic errors, unhandled edge cases
- Deviations from CLAUDE.md conventions (no comments, no hardcoded strings, flush/commit pattern, ownership checks, engine isolation)
- Tests that would pass even if the implementation was wrong
- Security issues if user input is involved
- Regressions — could existing callers break?

If you find bugs, fix them and re-run checks. Don't just report problems you could solve.

If everything is clean, say so in one line. Don't manufacture issues to seem thorough. If there are real problems, be specific — file, line, what's wrong, why it matters.
