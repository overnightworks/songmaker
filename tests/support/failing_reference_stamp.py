"""A PostgreSQL trigger that makes stamping a reference's ``unused_since`` fail."""

from __future__ import annotations

from sqlalchemy import text

_FUNCTION = "fail_stamp"


def install_failing_stamp(factory, request, reference_id: str | None = None) -> None:
    """Fail every stamp, or only the one of ``reference_id``, until the test ends.

    The per-test database reset restores tables, not triggers, so the finalizer drops them.
    """
    only_reference = f"WHEN (NEW.id = '{reference_id}') " if reference_id else ""
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
    request.addfinalizer(lambda: _drop_failing_stamp(factory))


def _drop_failing_stamp(factory) -> None:
    with factory() as session:
        session.execute(text(f"DROP TRIGGER {_FUNCTION} ON reference_recordings"))
        session.execute(text(f"DROP FUNCTION {_FUNCTION}()"))
        session.commit()
