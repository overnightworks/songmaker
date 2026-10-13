#!/bin/bash
set -e

echo "Starting songmaker server..."
exec uv run --no-sync --frozen --no-build songmaker server --port 8080
