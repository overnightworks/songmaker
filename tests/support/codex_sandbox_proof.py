"""The Codex image sandbox proof script, loaded once as a module."""

from __future__ import annotations

import importlib.util
import sys

from support.repository_root import REPOSITORY_ROOT

_SCRIPT_PATH = REPOSITORY_ROOT / "scripts" / "prove_codex_image_sandbox.py"
_SPEC = importlib.util.spec_from_file_location("prove_codex_image_sandbox", _SCRIPT_PATH)
assert _SPEC is not None
assert _SPEC.loader is not None
proof = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = proof
_SPEC.loader.exec_module(proof)
