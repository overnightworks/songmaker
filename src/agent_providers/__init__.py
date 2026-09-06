"""Reusable provider layer for agent CLIs and APIs (Claude, Codex, Grok).

Owns the machinery a host application should not rebuild: bounded process
runs, login and catalog probes, tool-surface gating, turn transports, the tool
loop, and the sandbox building blocks. Application concerns — MCP tools,
prompts, settings storage, domain ownership — stay with the application, which
supplies them through ports.

Independent of `songmaker_cli` so it can be released as its own distribution
(issue #825); the boundary is enforced by the `.importlinter` contract.
"""

__version__ = "0.0.0"
