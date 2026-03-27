"""Agent coordination for parallel plan execution.

Tracks which agent owns which files to prevent merge conflicts.
DB lives outside the repo so worktrees and branches all share it.

Usage:
    python scripts/coordinate.py claim <plan> <files>   Claim file ownership
    python scripts/coordinate.py release <plan>          Release all claims
    python scripts/coordinate.py check <file>            Check who owns a file
    python scripts/coordinate.py status                  Show all active work
    python scripts/coordinate.py done <plan>             Mark plan as done + release

Examples:
    python scripts/coordinate.py claim migration-redis "middleware.py,server.py:130-156"
    python scripts/coordinate.py check middleware.py
    python scripts/coordinate.py status
    python scripts/coordinate.py done migration-redis
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path.home() / ".claude" / "songmaker-coordination.db"


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS claims (
            plan TEXT NOT NULL,
            file TEXT NOT NULL,
            claimed_at TEXT NOT NULL,
            PRIMARY KEY (plan, file)
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS plans (
            plan TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'active',
            branch TEXT,
            started_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )"""
    )
    conn.commit()
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def cmd_claim(plan: str, files_str: str) -> None:
    conn = _connect()
    now = _now()
    files = [f.strip() for f in files_str.split(",") if f.strip()]

    for file in files:
        existing = conn.execute(
            "SELECT plan FROM claims WHERE file = ? AND plan != ?", (file, plan)
        ).fetchone()
        if existing:
            print(f"CONFLICT: {file} is owned by {existing[0]}")
            sys.exit(1)

    for file in files:
        conn.execute(
            "INSERT OR REPLACE INTO claims (plan, file, claimed_at) VALUES (?, ?, ?)",
            (plan, file, now),
        )

    conn.execute(
        "INSERT OR REPLACE INTO plans (plan, status, started_at, updated_at) VALUES (?, 'active', ?, ?)",
        (plan, now, now),
    )
    conn.commit()
    print(f"Claimed {len(files)} file(s) for {plan}")


def cmd_release(plan: str) -> None:
    conn = _connect()
    conn.execute("DELETE FROM claims WHERE plan = ?", (plan,))
    conn.execute(
        "UPDATE plans SET status = 'released', updated_at = ? WHERE plan = ?",
        (_now(), plan),
    )
    conn.commit()
    print(f"Released all claims for {plan}")


def cmd_check(file: str) -> None:
    conn = _connect()
    row = conn.execute("SELECT plan, claimed_at FROM claims WHERE file = ?", (file,)).fetchone()
    if row:
        print(f"{file} → owned by {row[0]} (since {row[1]})")
    else:
        print(f"{file} → unclaimed")


def cmd_status() -> None:
    conn = _connect()
    plans = conn.execute(
        "SELECT plan, status, branch, started_at, updated_at FROM plans ORDER BY started_at"
    ).fetchall()
    if not plans:
        print("No active plans.")
        return

    for plan, status, branch, started, updated in plans:
        files = conn.execute("SELECT file FROM claims WHERE plan = ?", (plan,)).fetchall()
        file_list = ", ".join(f[0] for f in files) if files else "(none)"
        branch_str = f" [{branch}]" if branch else ""
        print(f"{plan}{branch_str}: {status} (started {started[:10]})")
        print(f"  files: {file_list}")


def cmd_done(plan: str) -> None:
    conn = _connect()
    conn.execute("DELETE FROM claims WHERE plan = ?", (plan,))
    conn.execute(
        "UPDATE plans SET status = 'done', updated_at = ? WHERE plan = ?",
        (_now(), plan),
    )
    conn.commit()
    print(f"Marked {plan} as done, released all claims")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "claim" and len(sys.argv) == 4:
        cmd_claim(sys.argv[2], sys.argv[3])
    elif cmd == "release" and len(sys.argv) == 3:
        cmd_release(sys.argv[2])
    elif cmd == "check" and len(sys.argv) == 3:
        cmd_check(sys.argv[2])
    elif cmd == "status" and len(sys.argv) == 2:
        cmd_status()
    elif cmd == "done" and len(sys.argv) == 3:
        cmd_done(sys.argv[2])
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
