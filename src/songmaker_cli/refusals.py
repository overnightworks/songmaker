"""A refusal that names a catalog key: the sentence for agents and the key for the page."""

from __future__ import annotations

from collections.abc import Mapping

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from songmaker_cli.api_models.refusals import RefusalMessage, RefusalResponse
from songmaker_cli.words import SOURCE_LANGUAGE, Key, text


class Refusal(HTTPException):
    """An HTTP error whose `detail` is the source-language sentence of a catalog key.

    `scripts/check_refusal_keys.py` holds every call to a plain key, with exactly its gaps.
    """

    def __init__(
        self,
        status_code: int,
        key: Key,
        /,
        *,
        headers: Mapping[str, str] | None = None,
        **gaps: str,
    ) -> None:
        super().__init__(
            status_code,
            text(SOURCE_LANGUAGE, key, **gaps),
            headers=None if headers is None else dict(headers),
        )
        self.key = key
        self.gaps = gaps


def refusal_handler(request: Request, exc: Refusal) -> JSONResponse:
    body = RefusalResponse(
        detail=exc.detail,
        message=RefusalMessage(key=exc.key, values=exc.gaps),
    )
    return JSONResponse(body.model_dump(), status_code=exc.status_code, headers=exc.headers)


def not_found_response(request: Request, exc: HTTPException) -> JSONResponse:
    """Answer a 404 with the sentence its route raised; a path with no route says "Not Found".

    A status handler runs before a class handler, so a 404 `Refusal` reaches this function
    and keeps its message.
    """
    if isinstance(exc, Refusal):
        return refusal_handler(request, exc)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)


def install_refusal_handler(app: FastAPI) -> None:
    """Register the refusal and 404 handlers.

    A handler registered later for 404 replaces this one; the SPA fallback in ``create_app``
    does and hands every /api/ and /audio/ 404 back to ``not_found_response``.
    """
    app.add_exception_handler(Refusal, refusal_handler)
    app.add_exception_handler(404, not_found_response)
