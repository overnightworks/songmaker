from __future__ import annotations

import json
import os
import socket
import sys
from pathlib import Path

import pytest

from acestep_worker.subprocess_runner import (
    LmInitFailedError,
    SubprocessHandle,
    start_acestep_subprocess,
    stop_acestep_subprocess,
)

_FAKE_UV = """#!{python}
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

if sys.argv[1:] == ["--version"]:
    sys.exit(0)
port = int(sys.argv[sys.argv.index("--port") + 1])
with open(os.environ["FAKE_UV_PIDFILE"], "w") as pidfile:
    pidfile.write(str(os.getpid()))
body = os.environ["FAKE_UV_HEALTH_BODY"].encode()


class Health(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()
        if os.environ.get("FAKE_UV_ANSWER_ONCE"):
            os._exit(0)

    def log_message(self, *_args):
        pass


HTTPServer(("127.0.0.1", port), Health).serve_forever()
"""


def _health_body(*, llm_initialized: bool) -> bytes:
    data = {"models_initialized": True, "llm_initialized": llm_initialized}
    return json.dumps({"data": data}).encode()


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _start_against_fake_uv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    health_body: bytes,
    *,
    answer_once: bool = False,
    init_llm: bool = True,
) -> SubprocessHandle:
    """Start through a `uv` found on PATH that serves the given /health body."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_uv = bin_dir / "uv"
    fake_uv.write_text(_FAKE_UV.format(python=sys.executable))
    fake_uv.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_UV_PIDFILE", str(tmp_path / "child.pid"))
    monkeypatch.setenv("FAKE_UV_HEALTH_BODY", health_body.decode())
    monkeypatch.setenv("ACESTEP_HEALTH_POLL_SECONDS", "0.05")
    monkeypatch.setenv("ACESTEP_INIT_LLM", "1" if init_llm else "0")
    if answer_once:
        monkeypatch.setenv("FAKE_UV_ANSWER_ONCE", "1")
    return start_acestep_subprocess(
        "sft", port=_free_port(), checkpoint_dir=tmp_path, vram_budget_gb=24.0
    )


def _child_is_alive(tmp_path: Path) -> bool:
    try:
        os.kill(int((tmp_path / "child.pid").read_text()), 0)
    except ProcessLookupError:
        return False
    return True


def test_start_stops_the_child_when_its_lm_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    health_body = _health_body(llm_initialized=False)

    with pytest.raises(LmInitFailedError):
        _start_against_fake_uv(tmp_path, monkeypatch, health_body)

    assert not _child_is_alive(tmp_path)


def test_start_keeps_a_child_whose_lm_is_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    handle = _start_against_fake_uv(tmp_path, monkeypatch, _health_body(llm_initialized=True))
    try:
        assert _child_is_alive(tmp_path)
    finally:
        stop_acestep_subprocess(handle)


def test_start_does_not_read_the_lm_flag_when_the_lm_is_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    handle = _start_against_fake_uv(
        tmp_path, monkeypatch, _health_body(llm_initialized=False), init_llm=False
    )
    try:
        assert _child_is_alive(tmp_path)
    finally:
        stop_acestep_subprocess(handle)


@pytest.mark.parametrize(
    ("body", "answer_once"),
    [
        pytest.param(_health_body(llm_initialized=True), True, id="unreachable"),
        pytest.param(b"not json", False, id="unparsable"),
        pytest.param(b"[]", False, id="wrong-shape"),
        pytest.param(b'{"data": {}}', False, id="no-flag"),
        pytest.param(b'{"data": {"llm_initialized": "no"}}', False, id="non-boolean"),
    ],
)
def test_start_treats_an_unreadable_health_body_as_no_lm_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: bytes, answer_once: bool
) -> None:
    handle = _start_against_fake_uv(tmp_path, monkeypatch, body, answer_once=answer_once)
    stop_acestep_subprocess(handle)
