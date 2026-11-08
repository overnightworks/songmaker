#!/bin/bash
set -e
# Starts the songmaker web server as the web image's container process.

echo "Starting songmaker server..."
exec uv run --no-sync --frozen --no-build songmaker server --port 8080
