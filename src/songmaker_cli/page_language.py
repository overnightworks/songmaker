"""The language of a page the server answers, and the one built page it is written into.

`request_language` is the one place a request's language is decided: the account's tag of the
session its cookie names, then the browser's `Accept-Language`, then the source language, in the
order of webauth's resolver. The sign-in start, the sign-out page and the page shell all ask it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from fastapi.responses import HTMLResponse
from sqlalchemy.exc import SQLAlchemyError
from webauth.config import web_auth_config
from webauth.dependencies import account_language_of_session
from webauth.languages import AppLanguages, resolve_language

from songmaker_cli.app_context import get_app_context
from songmaker_cli.auth_stores import DatabaseSessionRecordStore
from songmaker_cli.request_policies import SPA_SHELL_HEADERS
from songmaker_cli.words import LANGUAGES, SOURCE_LANGUAGE

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi import Request

log = logging.getLogger(__name__)

APP_LANGUAGES: Final = AppLanguages(offered=LANGUAGES, default=SOURCE_LANGUAGE)

_BARE_HTML_ELEMENT: Final = "<html>"


class PageShellError(ValueError):
    """The built page cannot take a language: its `<html>` element is not one bare tag."""


def request_language(request: Request) -> str:
    """One of the app's languages for this request."""
    return resolve_language(
        APP_LANGUAGES,
        account_tag=_account_language(request),
        accept_language=request.headers.get("accept-language"),
    )


def _account_language(request: Request) -> str | None:
    # A page that cannot read the session still has to open: the header decides, and the
    # failure is logged so an outage of the store does not hide behind a working page.
    try:
        with get_app_context(request).db() as session:
            return account_language_of_session(
                request,
                sessions=DatabaseSessionRecordStore(session),
                config=web_auth_config(request),
            )
    except SQLAlchemyError:
        log.exception("The session store failed; the page language follows the browser")
        return None


@dataclass(frozen=True)
class PageShell:
    """The built page, read once; every answer writes its language into `<html>`."""

    html: str

    def __post_init__(self) -> None:
        if self.html.count(_BARE_HTML_ELEMENT) != 1:
            raise PageShellError(
                f"the built page must hold exactly one bare {_BARE_HTML_ELEMENT} to take a language"
            )

    @classmethod
    def read(cls, path: Path) -> PageShell | None:
        """The shell the build wrote at `path`, or `None` where there is no build."""
        if not path.exists():
            return None
        return cls(path.read_text(encoding="utf-8"))

    def answer(self, request: Request, *, status_code: int = 200) -> HTMLResponse:
        language = request_language(request)
        html = self.html.replace(_BARE_HTML_ELEMENT, f'<html lang="{language}">', 1)
        return HTMLResponse(html, status_code=status_code, headers=SPA_SHELL_HEADERS)
