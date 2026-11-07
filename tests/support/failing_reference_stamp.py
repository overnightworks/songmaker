"""A PostgreSQL trigger that makes stamping a reference's ``unused_since`` fail."""

from __future__ import annotations

from sqlalchemy import text

_FUNCTION = "fail_stamp"
# A leaked transaction makes the drop fail loudly instead of waiting forever.
_BOUND_STATEMENTS = (
    "SET LOCAL lock_timeout = '5s'",
    "SET LOCAL statement_timeout = '10s'",
)
_DROP_STATEMENTS = (
    f"DROP TRIGGER IF EXISTS {_FUNCTION} ON reference_recordings",
    f"DROP FUNCTION IF EXISTS {_FUNCTION}()",
)


def install_failing_stamp(factory, request, reference_id: str | None = None) -> None:
    """Fail every stamp, or only the one of ``reference_id``, until the test ends.

    The per-test database reset restores tables, not triggers, so the finalizer drops them.
    """
    only_reference = f"WHEN (NEW.id = '{reference_id}') " if reference_id else ""
    request.addfinalizer(lambda: drop_with_bounded_waits(factory, _DROP_STATEMENTS))
    with factory() as session:
        session.execute(text(
            f"CREATE FUNCTION {_FUNCTION}() RETURNS trigger LANGUAGE plpgsql AS $$ "
            "BEGIN RAISE EXCEPTION 'secret.wav' USING ERRCODE = 'integrity_constraint_violation'; "
            "END $$"
        ))
        session.execute(text(
            f"CREATE TRIGGER {_FUNCTION} BEFORE UPDATE OF unused_since ON reference_recordings "
            f"FOR EACH ROW {only_reference}EXECUTE FUNCTION {_FUNCTION}()"
        ))
        session.commit()


def drop_with_bounded_waits(factory, statements: tuple[str, ...]) -> None:
    """Run drop ``statements`` in one transaction that fails instead of waiting on a lock."""
    with factory() as session:
        for statement in (*_BOUND_STATEMENTS, *statements):
            session.execute(text(statement))
        session.commit()
