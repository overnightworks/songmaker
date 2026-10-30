"""Add and drop a nullable, indexed foreign-key column to a table's string id.

The index and constraint names derive from table and column, so a downgrade finds
exactly what the upgrade wrote: ``ix_<table>_<column>`` and
``fk_<table>_<column>_<referent>``.
"""

import sqlalchemy as sa
from alembic import op

ID_LENGTH = 36


def _names(table: str, column: str, referent_table: str) -> tuple[str, str]:
    return f"ix_{table}_{column}", f"fk_{table}_{column}_{referent_table}"


def add_indexed_foreign_key(table: str, column: str, referent_table: str) -> None:
    index, foreign_key = _names(table, column, referent_table)
    with op.batch_alter_table(table) as batch:
        batch.add_column(sa.Column(column, sa.String(length=ID_LENGTH), nullable=True))
        batch.create_index(index, [column])
        batch.create_foreign_key(foreign_key, referent_table, [column], ["id"], ondelete="SET NULL")


def drop_indexed_foreign_key(table: str, column: str, referent_table: str) -> None:
    index, foreign_key = _names(table, column, referent_table)
    with op.batch_alter_table(table) as batch:
        batch.drop_constraint(foreign_key, type_="foreignkey")
        batch.drop_index(index)
        batch.drop_column(column)
