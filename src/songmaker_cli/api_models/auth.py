"""Auth API models — the signed-in account and the sign-out answer."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class AuthMeResponse(BaseModel):
    id: str
    username: str
    role: Literal["admin", "user"]
    # The identity provider's account console; null where no issuer is configured.
    account_console_url: str | None = None


class LogoutResponse(BaseModel):
    logout_url: str
