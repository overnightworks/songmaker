#!/usr/bin/env bash
# Prints a TCP port on 127.0.0.1 that no process holds right now, for a probe stack's
# WEB_PORT: the kernel picks it, so two stacks started at once do not share a fixed one.
# Another process can still take the port before Compose binds it; that start then fails
# loudly on the bind.
# Usage: PORT="$(scripts/free_loopback_port.sh)"

set -euo pipefail

exec python3 -I -c '
import socket

with socket.socket() as probe:
    probe.bind(("127.0.0.1", 0))
    print(probe.getsockname()[1])
'
