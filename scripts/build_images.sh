#!/usr/bin/env bash
# Build the songmaker image hierarchy in dependency order, then build the
# docker compose leaf services that depend on the bases.
#
# Usage:
#   scripts/build_images.sh           # build everything (bases + leaves)
#   scripts/build_images.sh bases     # build base images only
#   scripts/build_images.sh leaves    # build compose leaves only

set -euo pipefail

cd "$(dirname "$0")/.."

build_bases() {
    echo ">>> Building songmaker/gpu-torch-base..."
    docker build \
        -f docker/base/gpu-torch-base.Dockerfile \
        -t songmaker/gpu-torch-base:latest \
        .

    echo ">>> Building songmaker/acestep-base..."
    docker build \
        -f docker/base/acestep-base.Dockerfile \
        -t songmaker/acestep-base:latest \
        .
}

build_leaves() {
    echo ">>> Building docker compose leaf services..."
    docker compose build
}

case "${1:-all}" in
    bases)  build_bases ;;
    leaves) build_leaves ;;
    all)    build_bases && build_leaves ;;
    *)      echo "Unknown target: $1"; exit 1 ;;
esac
