"""Records in the junit report which collected cases reach the PostgreSQL databases.

The decision is the case's fixture closure, so a fixture that only a support helper requests
still counts; CI reads the record instead of guessing from names.
"""

from __future__ import annotations

import pytest

DATABASE_FIXTURE = "postgresql_databases"
DATABASE_CASE_PROPERTY = "database_case"


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if DATABASE_FIXTURE in item.fixturenames:
            item.user_properties.append((DATABASE_CASE_PROPERTY, "true"))
