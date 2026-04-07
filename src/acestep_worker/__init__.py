"""ACE-Step worker: stateful peer container that manages an ACE-Step subprocess.

Self-registers with the control plane on startup, heartbeats ephemeral state to
Redis with TTL, and exposes HTTP endpoints for load_model / generate / download.
Generation runs as an async background task; clients consume progress via SSE.
"""
