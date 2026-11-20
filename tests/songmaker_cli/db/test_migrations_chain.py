"""The alembic revision chain is one line from base to a single head."""

from __future__ import annotations

from alembic.config import Config
from alembic.script import ScriptDirectory
from support.repository_root import REPOSITORY_ROOT


def test_every_revision_is_an_ancestor_of_the_one_head():
    scripts = ScriptDirectory.from_config(Config(str(REPOSITORY_ROOT / "alembic.ini")))
    heads = scripts.get_heads()
    assert len(heads) == 1
    ancestors = {script.revision for script in scripts.iterate_revisions(heads[0], "base")}
    assert ancestors == {script.revision for script in scripts.walk_revisions()}
