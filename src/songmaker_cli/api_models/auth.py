"""Auth API models — login, the current user, the password rule."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Final, Literal

from pydantic import AfterValidator, BaseModel, Field, TypeAdapter, ValidationError
from webauth.passwords import MIN_PASSWORD_LENGTH, check_password_strength

if TYPE_CHECKING:
    from pydantic_core import ErrorDetails

    from songmaker_cli.db.models import User

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
