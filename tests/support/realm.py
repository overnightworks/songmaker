"""The realm names the test suite's web app reads from its ``REALM_`` keys."""

from __future__ import annotations

from typing import Final

CLIENT_ID: Final = "songmaker-test"
LOGIN_GROUP: Final = "/apps/songmaker"
ADMIN_GROUP: Final = "/apps/songmaker/admin"
MCP_GROUP: Final = "/apps/songmaker/mcp"
AGENT_GROUP: Final = "/agents"

# The keys every web app of the suite needs; the MCP endpoint stays off without its own.
REALM_ENVIRONMENT: Final = {
    "REALM_CLIENT_ID": CLIENT_ID,
    "REALM_LOGIN_GROUP": LOGIN_GROUP,
    "REALM_ADMIN_GROUP": ADMIN_GROUP,
    "REALM_MCP_GROUP": MCP_GROUP,
}
