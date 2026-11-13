"""A refusal that names a catalog key: the sentence for agents and the key for the page."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from songmaker_cli.api_models.refusals import RefusalMessage, RefusalResponse
from songmaker_cli.words import SOURCE_LANGUAGE, Key, text


class Refusal(HTTPException):
    """An HTTP error whose `detail` is the source-language sentence of a catalog key.

    `scripts/check_refusal_keys.py` holds every call to a plain key, with exactly its gaps.
    """

    def __init__(self, status_code: int, key: Key, /, **gaps: str) -> None:
        super().__init__(status_code, text(SOURCE_LANGUAGE, key, **gaps))
        self.key = key
        self.gaps = gaps


def refusal_handler(request: Request, exc: Refusal) -> JSONResponse:
    body = RefusalResponse(
        detail=exc.detail,
        message=RefusalMessage(key=exc.key, values=exc.gaps),
    )
    return JSONResponse(body.model_dump(), status_code=exc.status_code, headers=exc.headers)


def install_refusal_handler(app: FastAPI) -> None:
    app.add_exception_handler(Refusal, refusal_handler)
