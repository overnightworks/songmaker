# Implement a Plan

This codebase is in active use. The quality of your work directly affects a real product and a real developer's daily workflow.

## Step 1: Read context

Read `CLAUDE.md` first — it has the conventions, check commands, and patterns. Then read the plan file the user specifies.

If the plan references things that have changed (files moved, APIs renamed, coverage numbers shifted), adapt. If something is fundamentally wrong or contradicts a design decision, fix the plan and explain why. Use your judgment on the difference.

## Step 2: Implement

Implement the plan. Ship tests with code. Run all checks from CLAUDE.md when you're done. Fix what breaks.

Keep changes minimal. Don't refactor surrounding code, don't add things the plan doesn't ask for, don't "improve" what's already working. If you discover something the plan didn't anticipate and the right call isn't obvious, ask.

## Step 3: Commit

Commit your work using conventional commit messages (`feat:`, `fix:`, `refactor:`).

A second agent will review every line of your diff. If something is wrong, they'll find it — so get it right the first time rather than hoping it passes.
