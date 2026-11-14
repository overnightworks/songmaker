#!/usr/bin/env bash
# Registers the repository's git merge drivers once per clone; worktrees share .git/config.
set -euo pipefail
cd "$(dirname "$0")/.."
git config merge.po.name "Merge gettext catalogs entry by entry"
git config merge.po.driver "python3 scripts/merge_po.py %O %A %B"
