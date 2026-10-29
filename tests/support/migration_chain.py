"""Questions about the alembic revision chain that no test answers by pinning the head."""

from __future__ import annotations

from alembic.config import Config
from alembic.script import ScriptDirectory
from support.repository_root import REPOSITORY_ROOT


def is_on_the_single_chain(revision: str) -> bool:
    """Whether the script directory has exactly one head and `revision` is among its ancestors."""
    scripts = ScriptDirectory.from_config(Config(str(REPOSITORY_ROOT / "alembic.ini")))
    heads = scripts.get_heads()
    if len(heads) != 1:
        return False
    return revision in {script.revision for script in scripts.iterate_revisions(heads[0], "base")}
