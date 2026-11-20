"""What every migration that stores a sentence column as a message token owes.

A test module subclasses `StoredMessageMigrationContract` as `Test...`, sets the class
attributes, and provides an `upgraded` fixture that returns the alembic config and the engine
after the migration, with one row `known-<n>` seeded per known sentence.
"""

from __future__ import annotations

from collections.abc import Callable
from types import ModuleType

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from support.migration_chain import column_names, stored_values
from support.repository_root import REPOSITORY_ROOT

from songmaker_cli.words import SOURCE_LANGUAGE, text

STORED_KEYS_FILE = REPOSITORY_ROOT / "scripts" / "stored_message_keys.txt"
NOT_TOKENS = [
    pytest.param({"key": 7, "values": {}}, id="key-not-a-string"),
    pytest.param({"values": {}}, id="key-missing"),
    pytest.param({"key": "any.key", "values": []}, id="values-not-an-object"),
    pytest.param({"key": "any.key"}, id="values-missing"),
]


def committed_stored_keys() -> set[str]:
    lines = STORED_KEYS_FILE.read_text(encoding="utf-8").splitlines()
    return {line.strip() for line in lines if line.strip()}


class StoredMessageMigrationContract:
    """Subclass per migration; the subclass names its table, columns and token writer."""

    migration: ModuleType
    table: str
    old_column: str
    new_column: str
    insert_row: Callable[[Engine, str, str, object], None]
    other_stored_keys: frozenset[str] = frozenset()

    def test_a_known_sentence_becomes_the_token_that_words_it_again(self, upgraded):
        _, engine = upgraded
        stored = stored_values(engine, self.table, self.new_column)
        for number, (sentence, key) in enumerate(self.migration.STORED_MESSAGE_KEYS.items()):
            assert stored[f"known-{number}"] == {"key": key, "values": {}}
            assert text(SOURCE_LANGUAGE, key) == sentence

    def test_upgrade_replaces_the_sentence_column_by_the_token_column(self, upgraded):
        _, engine = upgraded
        names = column_names(engine, self.table)
        assert self.new_column in names
        assert self.old_column not in names

    @pytest.mark.parametrize("token", NOT_TOKENS)
    def test_the_database_refuses_a_value_that_is_not_a_token(self, upgraded, token):
        _, engine = upgraded
        with pytest.raises(IntegrityError):
            self.insert_row(engine, "bad", self.new_column, token)

    def test_the_keys_the_migration_stores_are_in_the_committed_set_of_stored_keys(self):
        stored = {*self.migration.STORED_MESSAGE_KEYS.values(), *self.other_stored_keys}
        assert stored <= committed_stored_keys()
