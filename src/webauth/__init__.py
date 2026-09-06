"""The future auth library extracted per #825.

Will own sessions with Redis-backed expiry, HMAC cookies, admin/owner checks,
rate limits, and audit — the authentication machinery a host application
should not rebuild. Application concerns — the user model, first-run setup,
roles, and login routes with their advisory lock and commit-then-raise — stay
with the application, which supplies them through ports.

Independent of `songmaker_cli` and of `agent_providers` so it can be released
as its own distribution; the boundary is enforced by the `.importlinter`
contract.
"""

__version__ = "0.0.0"
