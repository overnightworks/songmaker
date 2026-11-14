"""Session ids for tests that store a session row; webauth mints the real ones at sign-in."""

from __future__ import annotations

import uuid


def a_session_id() -> str:
    return f"session-{uuid.uuid4().hex}"
