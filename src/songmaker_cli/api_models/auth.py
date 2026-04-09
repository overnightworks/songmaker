"""Auth and admin API models — login, users, sessions, audit."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field, field_validator

from songmaker_cli.auth import check_password_strength

if TYPE_CHECKING:
    from songmaker_cli.db.models import AuditLog, LoginAttempt, User, UserSession


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=8, max_length=128)


class SetupRequest(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=8, max_length=128)

    _check_strength = field_validator("password")(check_password_strength)


class ChangePasswordRequest(BaseModel):
    current: str = Field(min_length=1, max_length=128)
    new: str = Field(min_length=8, max_length=128, alias="new_password")

    _check_strength = field_validator("new")(check_password_strength)


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=8, max_length=128)
    role: Literal["admin", "user"] = "user"

    _check_strength = field_validator("password")(check_password_strength)


class UpdateUserRequest(BaseModel):
    role: Literal["admin", "user"] | None = None
    is_active: bool | None = None
    password: str | None = Field(None, min_length=8, max_length=128)

    _check_strength = field_validator("password")(check_password_strength)


class UserResponse(BaseModel):
    id: str
    username: str
    role: str
    is_active: bool
    created_at: str

    @classmethod
    def from_orm(cls, user: User) -> UserResponse:
        return cls(
            id=user.id,
            username=user.username,
            role=user.role,
            is_active=user.is_active,
            created_at=user.created_at.isoformat(),
        )


class AuthMeResponse(BaseModel):
    id: str
    username: str
    role: Literal["admin", "user"]


class SetupRequiredResponse(BaseModel):
    required: bool


class SessionResponse(BaseModel):
    id: str
    user_id: str
    username: str
    created_at: str
    expires_at: str
    ip_address: str = ""
    user_agent: str = ""

    @classmethod
    def from_orm(cls, sess: UserSession) -> SessionResponse:
        return cls(
            id=hashlib.sha256(sess.id.encode()).hexdigest(),
            user_id=sess.user_id,
            username=sess.user.username,
            created_at=sess.created_at.isoformat(),
            expires_at=sess.expires_at.isoformat(),
            ip_address=sess.ip_address,
            user_agent=sess.user_agent,
        )


class LoginAttemptResponse(BaseModel):
    id: str
    ip_address: str
    username: str
    success: bool
    attempted_at: str

    @classmethod
    def from_orm(cls, attempt: LoginAttempt) -> LoginAttemptResponse:
        return cls(
            id=attempt.id,
            ip_address=attempt.ip_address,
            username=attempt.username,
            success=attempt.success,
            attempted_at=attempt.attempted_at.isoformat(),
        )


class AuditLogResponse(BaseModel):
    id: str
    user_id: str | None
    action: str
    resource_type: str
    resource_id: str
    detail: str
    created_at: str

    @classmethod
    def from_orm(cls, entry: AuditLog) -> AuditLogResponse:
        return cls(
            id=entry.id,
            user_id=entry.user_id,
            action=entry.action,
            resource_type=entry.resource_type,
            resource_id=entry.resource_id,
            detail=entry.detail,
            created_at=entry.created_at.isoformat(),
        )
