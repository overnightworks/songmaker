"""The column type that stores a `Message`: a catalog key and the values of its gaps."""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

from songmaker_cli.messages import Message


class MessageColumn(TypeDecorator[Message]):
    """JSON column holding a `Message`; no message is SQL NULL, never JSON `null`.

    A write calls `Message.sentence()`, so a key the catalog lacks or gaps that differ from the
    sentence's raise before the row is stored. A read only checks the shape, so a row whose key a
    later catalog dropped still loads; the one reader that needs the sentence resolves it.
    """

    impl = JSON(none_as_null=True)
    cache_ok = True

    def process_bind_param(self, value: Message | None, dialect: Dialect) -> dict[str, Any] | None:
        if value is None:
            return None
        value.sentence()
        return value.model_dump()

    def process_result_value(self, value: Any, dialect: Dialect) -> Message | None:
        return None if value is None else Message.model_validate(value)
