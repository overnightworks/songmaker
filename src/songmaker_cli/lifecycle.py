"""Application lifecycle helpers -- admin auto-setup and session sync."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI

from songmaker_cli.app_context import AppContext
from songmaker_cli.settings import get_settings

log = logging.getLogger(__name__)


def auto_setup_admin(ctx: AppContext) -> None:
    settings = get_settings()
    admin_user = settings.admin_username
    admin_pass = (
        settings.admin_password.get_secret_value() if settings.admin_password else None
    )
    if not admin_user or not admin_pass:
        return

    from sqlalchemy.exc import IntegrityError

    from songmaker_cli.auth import ROLE_ADMIN, check_password_strength, hash_password
    from songmaker_cli.db.queries import create_user, user_count

    with ctx.db() as session:
        if user_count(session) > 0:
            return
        try:
            check_password_strength(admin_pass)
        except ValueError:
            log.error("ADMIN_PASSWORD does not meet strength requirements -- skipping auto-setup")
            return
        try:
            create_user(session, admin_user, hash_password(admin_pass), role=ROLE_ADMIN)
            session.commit()
        except IntegrityError:
            session.rollback()
            log.info("Auto-setup: admin user already exists (concurrent startup)")
            return
        log.info("Auto-setup: admin user '%s' created from env vars", admin_user)


def _sync_sessions(ctx: AppContext, session_cache) -> int:
    """Sync Redis session TTLs to the database. Returns count of synced sessions.

    Removes cached sessions for inactive users or sessions missing from the DB.
    Also purges expired sessions from the database (they accumulate because Redis
    evicts them on TTL but the DB rows stay forever).
    """
    from songmaker_cli.db.models import User as UserModel
    from songmaker_cli.db.models import UserSession
    from songmaker_cli.db.queries import delete_expired_sessions

    active = session_cache.get_all_sessions()

    with ctx.db() as db:
        purged = delete_expired_sessions(db)
        if purged:
            log.info("Session sync: purged %d expired sessions from DB", purged)

        if not active:
            db.commit()
            return 0

        session_ids = [sid for sid, _ in active]
        ttl_by_id = {sid: ttl for sid, ttl in active}
        synced = 0

        db_sessions = (
            db.query(UserSession)
            .filter(UserSession.id.in_(session_ids))
            .all()
        )
        db_session_by_id = {s.id: s for s in db_sessions}
        found_user_ids = {s.user_id for s in db_sessions}

        inactive_user_ids: set[str] = set()
        if found_user_ids:
            inactive_users = (
                db.query(UserModel.id)
                .filter(
                    UserModel.id.in_(found_user_ids),
                    UserModel.is_active.is_(False),
                )
                .all()
            )
            inactive_user_ids = {u.id for u in inactive_users}

        for session_id in session_ids:
            user_session = db_session_by_id.get(session_id)
            if not user_session:
                cached = session_cache.get(session_id)
                if cached:
                    session_cache.delete(session_id, cached.user_id)
                continue
            if user_session.user_id in inactive_user_ids:
                session_cache.delete_user_sessions(user_session.user_id)
                continue
            ttl = ttl_by_id[session_id]
            real_expires = datetime.now(timezone.utc) + timedelta(seconds=ttl)
            user_session.expires_at = real_expires
            synced += 1
        db.commit()

    return synced


async def session_sync_loop(app: FastAPI) -> None:
    from songmaker_cli.constants import (
        REDIS_SESSION_SYNC_INTERVAL_SECONDS,
        SESSION_SYNC_LOCK_KEY,
        SESSION_SYNC_LOCK_TTL_SECONDS,
    )

    ctx: AppContext = app.state.ctx
    session_cache = app.state.session_cache

    consecutive_failures = 0
    while True:
        await asyncio.sleep(REDIS_SESSION_SYNC_INTERVAL_SECONDS)
        try:
            acquired = await asyncio.to_thread(
                ctx.redis.set,
                SESSION_SYNC_LOCK_KEY, "1",
                ex=SESSION_SYNC_LOCK_TTL_SECONDS, nx=True,
            )
            if not acquired:
                continue
            try:
                synced = await asyncio.to_thread(_sync_sessions, ctx, session_cache)
                consecutive_failures = 0
                if synced:
                    log.info("Session sync: updated %d sessions", synced)
            finally:
                await asyncio.to_thread(ctx.redis.delete, SESSION_SYNC_LOCK_KEY)
        except Exception:
            consecutive_failures += 1
            if consecutive_failures >= 3:
                log.error(
                    "Session sync failed %d consecutive times",
                    consecutive_failures, exc_info=True,
                )
            else:
                log.warning("Session sync failed", exc_info=True)
