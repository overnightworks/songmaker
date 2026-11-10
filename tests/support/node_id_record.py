"""Records in the junit report the node id of every case left after the selection.

A junit record names a case only by class name and name, which cannot be mapped back to a node
id with certainty; the backend shards' reports are compared with the collected tests by this record.
"""

from __future__ import annotations

import pytest

NODE_ID_PROPERTY = "node_id"


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        item.user_properties.append((NODE_ID_PROPERTY, item.nodeid))
