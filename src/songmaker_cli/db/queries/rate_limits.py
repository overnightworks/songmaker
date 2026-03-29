"""Query functions for rate limit settings."""

from __future__ import annotations

from sqlalchemy.orm import Session

from songmaker_cli.db.models import RateLimitSetting


def get_rate_limit_setting(
    session: Session, setting_key: str, user_id: str | None = None,
) -> RateLimitSetting | None:
    user_filter = (
        RateLimitSetting.user_id == user_id
        if user_id is not None
        else RateLimitSetting.user_id.is_(None)
    )
    return (
        session.query(RateLimitSetting)
        .filter(RateLimitSetting.setting_key == setting_key, user_filter)
        .first()
    )


def resolve_rate_limit(
    session: Session, user_id: str, setting_key: str, env_fallback: int,
) -> int:
    user_override = get_rate_limit_setting(session, setting_key, user_id)
    if user_override is not None:
        return user_override.value
    global_default = get_rate_limit_setting(session, setting_key)
    if global_default is not None:
        return global_default.value
    return env_fallback


def upsert_rate_limit_setting(
    session: Session, setting_key: str, value: int,
    user_id: str | None = None,
) -> RateLimitSetting:
    existing = get_rate_limit_setting(session, setting_key, user_id)
    if existing:
        existing.value = value
        session.flush()
        return existing
    setting = RateLimitSetting(
        setting_key=setting_key, value=value, user_id=user_id,
    )
    session.add(setting)
    session.flush()
    return setting


def delete_rate_limit_setting(
    session: Session, setting_key: str, user_id: str | None = None,
) -> bool:
    existing = get_rate_limit_setting(session, setting_key, user_id)
    if not existing:
        return False
    session.delete(existing)
    session.flush()
    return True


def get_all_global_rate_limits(session: Session) -> list[RateLimitSetting]:
    return (
        session.query(RateLimitSetting)
        .filter(RateLimitSetting.user_id.is_(None))
        .all()
    )


def get_user_rate_limits(
    session: Session, user_id: str,
) -> list[RateLimitSetting]:
    return (
        session.query(RateLimitSetting)
        .filter(RateLimitSetting.user_id == user_id)
        .all()
    )


def delete_all_user_rate_limits(session: Session, user_id: str) -> int:
    count = (
        session.query(RateLimitSetting)
        .filter(RateLimitSetting.user_id == user_id)
        .delete()
    )
    session.flush()
    return count
