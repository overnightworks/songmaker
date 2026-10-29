"""Statement budgets for routes, measured on the SQL a request issued."""

from __future__ import annotations

from collections.abc import Sequence


def queries_without_session_auth(statements: Sequence[str]) -> list[str]:
    """defect:#1590: route budgets exclude DB session lookup and touch SQL.

    Session authentication owns this per-request cost independently of the
    route's row count; all other statements remain in the route budget.
    """
    session_prefixes = ("select user_sessions.", "update user_sessions set ")
    removed, kept = [], []
    for statement in statements:
        normalized = " ".join(statement.lower().split())
        if normalized.startswith(session_prefixes):
            removed.append(normalized)
        else:
            kept.append(statement)
    expected = ("select user_sessions.", "update user_sessions set expires_at")
    assert len(removed) == 2 and all(
        sum(statement.startswith(prefix) for statement in removed) == 1 for prefix in expected
    ), f"Expected exactly one {expected[0]!r} and one {expected[1]!r}; removed: {removed!r}"
    return kept
