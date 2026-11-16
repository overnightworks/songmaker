"""The ACE-Step worker as served writes one request line per request, in the caller's trace."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from logline import REQUEST_EVENT, RequestLineMiddleware
from logline.testing import configured
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from support.wrapper_deps import make_deps

from acestep_worker.__main__ import SERVICE_NAME, build_app
from songmaker_cli.scheduler import worker_request_headers

_INCOMING_TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
_INCOMING_TRACEPARENT = f"00-{_INCOMING_TRACE_ID}-00f067aa0ba902b7-01"


def _request_lines(output: str) -> list[dict[str, object]]:
    lines = [json.loads(text) for text in output.splitlines()]
    return [line for line in lines if line["event"] == REQUEST_EVENT]


def _worker_client(tmp_path: Path) -> TestClient:
    deps, _ = make_deps(tmp_path)
    return TestClient(build_app(deps))


def _web_app_sending_to_the_worker() -> Starlette:
    async def headers_for_the_worker(_: Request) -> JSONResponse:
        return JSONResponse(worker_request_headers())

    app = Starlette(routes=[Route("/headers", headers_for_the_worker)])
    app.add_middleware(RequestLineMiddleware)
    return app


def test_a_request_to_the_worker_writes_its_request_line_in_the_callers_trace(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    with configured(SERVICE_NAME):
        response = _worker_client(tmp_path).get(
            "/health", headers={"traceparent": _INCOMING_TRACEPARENT},
        )

    (request_line,) = _request_lines(capsys.readouterr().out)
    assert request_line["service"] == SERVICE_NAME
    assert request_line["status"] == response.status_code
    assert request_line["duration_ms"] is not None
    assert request_line["trace_id"] == _INCOMING_TRACE_ID


def test_a_trace_the_web_process_started_continues_in_the_worker(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    with configured("songmaker-web"):
        web_response = TestClient(_web_app_sending_to_the_worker()).get("/headers")
    (web_line,) = _request_lines(capsys.readouterr().out)

    with configured(SERVICE_NAME):
        worker_response = _worker_client(tmp_path).get("/health", headers=web_response.json())
    (worker_line,) = _request_lines(capsys.readouterr().out)

    sent_trace_id = web_response.json()["traceparent"].split("-")[1]
    assert web_line["trace_id"] == sent_trace_id
    assert worker_line["trace_id"] == sent_trace_id
    assert worker_line["status"] == worker_response.status_code
