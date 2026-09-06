#!/bin/bash
set -e

echo "Starting songmaker server..."
exec uv run songmaker server --port 8080
