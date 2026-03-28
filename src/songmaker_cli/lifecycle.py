"""Application lifecycle helpers -- admin auto-setup and session sync."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI

from songmaker_cli.app_context import AppContext

log = logging.getLogger(__name__)


def auto_setup_admin(ctx: AppContext) -> None:
    admin_user = os.environ.get("ADMIN_USERNAME")
    admin_pass = os.environ.get("ADMIN_PASSWORD")
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


async def session_sync_loop(app: FastAPI) -> None:
    from songmaker_cli.constants import REDIS_SESSION_SYNC_INTERVAL_SECONDS
    from songmaker_cli.db.models import User as UserModel
    from songmaker_cli.db.models import UserSession

    ctx: AppContext = app.state.ctx
    session_cache = app.state.session_cache

    while True:
        await asyncio.sleep(REDIS_SESSION_SYNC_INTERVAL_SECONDS)
        try:
            active = session_cache.get_all_sessions()
            if not active:
                continue
            synced = 0
            with ctx.db() as db:
                for session_id, ttl in active:
                    user_session = db.query(UserSession).filter_by(id=session_id).first()
                    if not user_session:
                        cached = session_cache.get(session_id)
                        if cached:
                            session_cache.delete(session_id, cached["user_id"])
                        continue
                    user = db.query(UserModel).filter_by(id=user_session.user_id).first()
                    if user and not user.is_active:
                        session_cache.delete_user_sessions(user.id)
                        continue
                    real_expires = datetime.now(timezone.utc) + timedelta(seconds=ttl)
                    user_session.expires_at = real_expires
                    synced += 1
                db.commit()
            if synced:
                log.info("Session sync: updated %d sessions", synced)
        except Exception:
            log.warning("Session sync failed", exc_info=True)
