"""A gateway stand-in a child web process reaches by origin.

The scripting is ``FakeGateway``'s (or a subclass such as ``HeldGateway``): this server only
carries each HTTP request into the gateway's transport and writes its answer back, so a test
scripts held, released, raising and stopped turns here as it does in-process.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Final

import httpx2
from agents.backend.fake_gateway import FakeGateway

LOOPBACK: Final = "127.0.0.1"
_HEADERS_OF_THE_TRANSPORT: Final = frozenset({"content-length", "transfer-encoding"})


def _gateway_handler(gateway: FakeGateway) -> type[BaseHTTPRequestHandler]:
    class GatewayRequestHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - the name http.server dispatches on
            self._answer()

        def do_POST(self) -> None:  # noqa: N802 - the name http.server dispatches on
            self._answer()

        def _answer(self) -> None:
            body = self.rfile.read(int(self.headers.get("content-length", 0)))
            request = httpx2.Request(
                self.command,
                f"http://{self.headers['host']}{self.path}",
                headers=dict(self.headers.items()),
                content=body,
            )
            response = asyncio.run(gateway.handle_async_request(request))
            self.send_response(response.status_code)
            for name, value in response.headers.items():
                if name.lower() not in _HEADERS_OF_THE_TRANSPORT:
                    self.send_header(name, value)
            self.send_header("content-length", str(len(response.content)))
            self.end_headers()
            self.wfile.write(response.content)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            """Keep the test output free of per-request lines."""

    return GatewayRequestHandler


@contextmanager
def serve_gateway(gateway: FakeGateway) -> Iterator[str]:
    """Serve ``gateway`` on a free loopback port and yield its origin; stop it on exit."""
    server = ThreadingHTTPServer((LOOPBACK, 0), _gateway_handler(gateway))
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://{LOOPBACK}:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
