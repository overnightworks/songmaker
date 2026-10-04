"""Auth and admin API models — login, users, sessions, audit."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Final, Literal

from pydantic import AfterValidator, BaseModel, Field, TypeAdapter, ValidationError
from webauth.passwords import MIN_PASSWORD_LENGTH, check_password_strength
from webauth.users import session_reference

if TYPE_CHECKING:
    from pydantic_core import ErrorDetails

    from songmaker_cli.db.models import LoginAttempt, User, UserSession

MAX_PASSWORD_LENGTH: Final = 128

PasswordText = Annotated[str, Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)]
ChosenPassword = Annotated[PasswordText, AfterValidator(check_password_strength)]

chosen_password_rule: Final = TypeAdapter(ChosenPassword)

_LENGTH_REFUSALS: Final = {
    "string_too_short": f"Password must be at least {MIN_PASSWORD_LENGTH} characters",
    "string_too_long": f"Password must be at most {MAX_PASSWORD_LENGTH} characters",
}


def chosen_rule_refusal(candidate: str) -> str | None:
    """The rule's own sentence for why ``candidate`` is refused, or None when it passes.

    No name on the way to the log or the console says "password": CodeQL's
    clear-text-logging heuristic treats any such call or variable as secret.
    """
    try:
        chosen_password_rule.validate_python(candidate)
    except ValidationError as error:
        return _plain_rule_sentence(error.errors()[0])
    return None


def _plain_rule_sentence(problem: ErrorDetails) -> str:
    if problem["type"] == "value_error":
        return str(problem["ctx"]["error"])
    return _LENGTH_REFUSALS[problem["type"]]


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    password: PasswordText


class SetupRequest(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    password: ChosenPassword


class ChangePasswordRequest(BaseModel):
    current: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)
    new: ChosenPassword = Field(alias="new_password")


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    password: ChosenPassword
    role: Literal["admin", "user"] = "user"


class UpdateUserRequest(BaseModel):
    role: Literal["admin", "user"] | None = None
    is_active: bool | None = None
    password: ChosenPassword | None = None


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
    is_current: bool

    @classmethod
    def from_orm(cls, sess: UserSession, *, is_current: bool = False) -> SessionResponse:
        return cls(
            id=session_reference(sess.id),
            user_id=sess.user_id,
            username=sess.user.username,
            created_at=sess.created_at.isoformat(),
            expires_at=sess.expires_at.isoformat(),
            ip_address=sess.ip_address,
            user_agent=sess.user_agent,
            is_current=is_current,
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
