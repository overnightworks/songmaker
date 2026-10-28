"""Loopback ACE-Step boundary shared by client and worker integration tests."""

from __future__ import annotations

import json
import wave
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from threading import Thread


def audio_fixture() -> bytes:
    buffer = BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\x01\x00" * 80)
    return buffer.getvalue()


@dataclass
class AceStepHttp:
    result: str = "[]"
    status: int = 2
    submission_status: str | None = None
    port: int = 0
    wav_bytes: bytes = field(default_factory=audio_fixture)

    def succeed(self) -> None:
        self.status = 1
        self.result = json.dumps([{"file": "/v1/audio?path=test.wav", "seed_value": "42"}])


@contextmanager
def acestep_http(
    result: str = "[]", *, submission_status: str | None = None,
) -> Iterator[AceStepHttp]:
    boundary = AceStepHttp(result=result, submission_status=submission_status)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            self.rfile.read(int(self.headers["Content-Length"]))
            if self.path == "/release_task":
                data = (
                    {"status": boundary.submission_status}
                    if boundary.submission_status is not None
                    else {"task_id": "test-task", "status": "queued"}
                )
                payload = {"data": data, "code": 200}
            elif self.path == "/query_result":
                payload = {"data": [{
                    "task_id": "test-task", "status": boundary.status,
                    "result": boundary.result,
                }]}
            else:
                self.send_error(404)
                return
            self.send_payload(json.dumps(payload).encode(), "application/json")

        def do_GET(self) -> None:
            if self.path == "/v1/audio?path=test.wav":
                self.send_payload(boundary.wav_bytes, "audio/wav")
            else:
                self.send_error(404)

        def send_payload(self, payload: bytes, content_type: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: object) -> None:
            """Keep HTTP access logs out of the client's diagnostic assertions."""

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        boundary.port = server.server_port
        thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
        thread.start()
        try:
            yield boundary
        finally:
            server.shutdown()
            thread.join()
