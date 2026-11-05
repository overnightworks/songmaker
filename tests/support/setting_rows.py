"""Global setting rows as an earlier release stored them, for tests that read or keep them."""

from __future__ import annotations

from songmaker_cli.db.models import RateLimitSetting


def store_setting_row(session, setting_key: str, value: str) -> None:
    """Write or overwrite the global text setting ``setting_key``."""
    row = (
        session.query(RateLimitSetting)
        .filter(RateLimitSetting.setting_key == setting_key, RateLimitSetting.user_id.is_(None))
        .first()
    )
    if row is None:
        session.add(RateLimitSetting(setting_key=setting_key, value=0, value_text=value))
    else:
        row.value_text = value
    session.flush()
