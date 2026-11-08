"""The countdown publication row as the announced-deletion tests need it."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete
from sqlalchemy.orm import sessionmaker
from support.setting_rows import store_setting_row

from songmaker_cli.constants import SETTING_REFERENCE_COUNTDOWN_VISIBLE_SINCE
from songmaker_cli.db.models import RateLimitSetting
from songmaker_cli.reference_audio import owner_reference_audio_root

MALFORMED_PUBLICATION = "last-tuesday-ish"
_ROWS = (
    RateLimitSetting.setting_key == SETTING_REFERENCE_COUNTDOWN_VISIBLE_SINCE,
    RateLimitSetting.user_id.is_(None),
)


def publish_countdown(factory: sessionmaker, shown_at: datetime | str | None) -> None:
    """Set the countdown row's value: an instant, or ``None`` for a clock nobody started."""
    with factory() as session:
        if shown_at is None:
            session.query(RateLimitSetting).filter(*_ROWS).update({"value_text": None})
        else:
            stored = shown_at if isinstance(shown_at, str) else shown_at.isoformat()
            store_setting_row(session, SETTING_REFERENCE_COUNTDOWN_VISIBLE_SINCE, stored)
        session.commit()


def remove_countdown_row(factory: sessionmaker) -> None:
    with factory() as session:
        session.execute(delete(RateLimitSetting).where(*_ROWS))
        session.commit()


def stored_file(audio_dir, user_id: str, name: str):
    """The path of an owner's stored reference file, its directory made."""
    path = owner_reference_audio_root(audio_dir, user_id) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
