"""The catalog key of a sentence and the values of its gaps: the token a page words itself."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from types import MappingProxyType
from typing import cast

from pydantic import BaseModel, ConfigDict, field_serializer, field_validator

from songmaker_cli.words import SOURCE_LANGUAGE, Key, text

log = logging.getLogger(__name__)


class Message(BaseModel):
    """A catalog key with the values of its gaps, held immutable.

    `scripts/check_refusal_keys.py` holds every `message(...)` call to a plain key, with exactly
    its gaps.
    """

    model_config = ConfigDict(frozen=True)

    key: str
    values: Mapping[str, str]

    @field_validator("values")
    @classmethod
    def _freeze_values(cls, values: Mapping[str, str]) -> Mapping[str, str]:
        return MappingProxyType(dict(values))

    @field_serializer("values")
    def _thaw_values(self, values: Mapping[str, str]) -> dict[str, str]:
        return dict(values)

    def sentence(self) -> str:
        """The source-language sentence of the key, for agents and API clients."""
        return text(SOURCE_LANGUAGE, cast("Key", self.key), **self.values)


def message(key: Key, /, **gaps: str) -> Message:
    return Message(key=key, values=gaps)


def stored_sentence(stored: Message | None, owner: str) -> str | None:
    """The sentence of a message a row holds; a key the catalog lacks logs `owner` and fails."""
    if stored is None:
        return None
    try:
        return stored.sentence()
    except (KeyError, TypeError):
        log.exception("%s holds the message key %s, which has no sentence", owner, stored.key)
        raise
