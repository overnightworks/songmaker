from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from acestep_worker.subprocess_runner import SubprocessHandle, start_acestep_subprocess

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


class FakeUvChild:
    """Starts real ACE-Step children through a `uv` on PATH that serves a /health body."""

    def __init__(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, free_port: Callable[[], int]
    ) -> None:
        self._tmp_path = tmp_path
        self._monkeypatch = monkeypatch
        self._free_port = free_port
        self._pidfile = tmp_path / "child.pid"
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        fake_uv = bin_dir / "uv"
        fake_uv.write_text(_FAKE_UV.format(python=sys.executable))
        fake_uv.chmod(0o755)
        monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
        monkeypatch.setenv("FAKE_UV_PIDFILE", str(self._pidfile))
        monkeypatch.setenv("ACESTEP_HEALTH_POLL_SECONDS", "0.05")

    def start(
        self,
        body: bytes,
        *,
        mode: str = "sft",
        answer_once: bool = False,
        init_llm: bool = True,
    ) -> SubprocessHandle:
        self._monkeypatch.setenv("FAKE_UV_HEALTH_BODY", body.decode())
        self._monkeypatch.setenv("ACESTEP_INIT_LLM", "1" if init_llm else "0")
        if answer_once:
            self._monkeypatch.setenv("FAKE_UV_ANSWER_ONCE", "1")
        return start_acestep_subprocess(
            mode, port=self._free_port(), checkpoint_dir=self._tmp_path, vram_budget_gb=24.0
        )

    @staticmethod
    def health(*, llm_initialized: bool) -> bytes:
        data = {"models_initialized": True, "llm_initialized": llm_initialized}
        return json.dumps({"data": data}).encode()

    def pid(self) -> int:
        """The process id of the child that started last."""
        return int(self._pidfile.read_text())

    def is_alive(self) -> bool:
        return self.process_is_alive(self.pid())

    @staticmethod
    def process_is_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        return True
