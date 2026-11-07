"""A SQLite trigger that makes stamping a reference's ``unused_since`` fail."""

from __future__ import annotations


def failing_stamp_trigger(reference_id: str | None = None) -> str:
    """The trigger SQL; it fails every stamp, or only the one of ``reference_id``."""
    only_reference = f"WHEN NEW.id = '{reference_id}' " if reference_id else ""
    return (
        "CREATE TRIGGER fail_stamp BEFORE UPDATE OF unused_since ON reference_recordings "
        f"{only_reference}BEGIN SELECT RAISE(ABORT, 'secret.wav'); END"
    )
