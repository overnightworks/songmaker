"""Raw ASGI middleware: gzip-compress JSON/text/JS responses only.

Starlette's `GZipMiddleware` decides purely from the `Accept-Encoding`
request header and the response size -- it has no notion of `Content-Type`,
status code, or byte-range headers, and it isn't instance-configurable
beyond that. Left unguarded (or guarded only by request path), it would:

  - re-compress already-lossy-compressed binary media (audio, cover
    images, icons, fonts) for zero size benefit and wasted CPU/latency;
  - gzip a 206 Partial Content response, or any response carrying
    `Content-Range`/`Accept-Ranges`, producing a `Content-Length` that no
    longer describes the byte range the client actually asked for.

So this module reimplements just enough of Starlette's streaming-safe
compression algorithm to decide from the *response*, not the request path:

  - Content-Type: an explicit allowlist (JSON, text/* except
    `text/event-stream`, JS, the web app manifest). Everything else --
    audio/*, image/*, video/*, font/*, application/octet-stream, PDFs,
    binary blobs of any kind -- passes through untouched.
  - Status code: only 200. Redirects, errors, and 206 Partial Content
    never reach the compression path.
  - `Content-Range` / `Accept-Ranges`: skip if either header is present
    (every `FileResponse` in this app sets `Accept-Ranges: bytes` by
    default), so a byte-range response's `Content-Length` always matches
    the bytes it actually sent, whether or not the status happens to be 200.

`text/event-stream` (the co-writer chat and job-progress SSE endpoints) is
excluded by Content-Type like everything else non-allowlisted -- messages
for those responses are forwarded to the client one ASGI send per source
chunk, with no buffering, so live streaming latency is unaffected.

BREACH note: BREACH is a compression-oracle attack that needs a secret and
attacker-controlled input reflected together in the same compressed
response, replayed many times while the attacker observes the compressed
size. It does not apply here: this app's CSRF token lives only in a
`SameSite=Strict` cookie -- never reflected into a compressed JSON/HTML
body -- so a cross-site attacker page cannot even trigger the authenticated
request whose response this middleware would compress. The public
`/shared/*` routes carry no per-request secret to leak, and reflect no
request-controlled input back into their JSON.
"""

from __future__ import annotations

import gzip
import io
from typing import Final, NoReturn

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_COMPRESSIBLE_CONTENT_TYPE_PREFIXES: Final[tuple[str, ...]] = (
    "application/json",
    "application/javascript",
    "application/manifest+json",
    "text/",
)
_NEVER_COMPRESS_CONTENT_TYPE_PREFIXES: Final[tuple[str, ...]] = ("text/event-stream",)

_HTTP_OK: Final[int] = 200


def _is_compressible_content_type(content_type: str) -> bool:
    if content_type.startswith(_NEVER_COMPRESS_CONTENT_TYPE_PREFIXES):
        return False
    return content_type.startswith(_COMPRESSIBLE_CONTENT_TYPE_PREFIXES)


def _should_compress(status: int, headers: Headers) -> bool:
    if status != _HTTP_OK:
        return False
    if "content-encoding" in headers:
        return False
    if "content-range" in headers or "accept-ranges" in headers:
        return False
    return _is_compressible_content_type(headers.get("content-type", ""))


class SelectiveGZipMiddleware:
    """Gzip JSON/text/JS responses; never binary media or byte-range responses."""

    def __init__(self, app: ASGIApp, minimum_size: int, compresslevel: int = 9) -> None:
        self.app = app
        self.minimum_size = minimum_size
        self.compresslevel = compresslevel

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or "gzip" not in Headers(scope=scope).get("accept-encoding", ""):
            await self.app(scope, receive, send)
            return
        responder = _CompressionResponder(self.app, self.minimum_size, self.compresslevel)
        await responder(scope, receive, send)


class _CompressionResponder:
    """Buffers just enough of one response to decide, then streams the rest.

    Mirrors Starlette's own `GZipMiddleware` responder shape (defer the
    `http.response.start` message until the first body chunk decides
    compress-or-passthrough), generalized from a hardcoded content-type
    exclusion to the status/header-aware `_should_compress` check above.
    """

    def __init__(self, app: ASGIApp, minimum_size: int, compresslevel: int) -> None:
        self.app = app
        self.minimum_size = minimum_size
        self.send: Send = _unattached_send
        self.initial_message: Message = {}
        self.started = False
        self.should_compress = False
        self.gzip_buffer = io.BytesIO()
        self.gzip_file = gzip.GzipFile(
            mode="wb", fileobj=self.gzip_buffer, compresslevel=compresslevel,
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        self.send = send
        with self.gzip_buffer, self.gzip_file:
            await self.app(scope, receive, self.send_with_compression)

    async def send_with_compression(self, message: Message) -> None:
        message_type = message["type"]

        if message_type == "http.response.start":
            self.initial_message = message
            headers = Headers(raw=self.initial_message["headers"])
            self.should_compress = _should_compress(self.initial_message["status"], headers)
            return

        if message_type != "http.response.body":
            await self._flush_start_then_send(message)
            return

        if not self.should_compress:
            await self._flush_start_then_send(message)
            return

        if not self.started:
            self.started = True
            body = message.get("body", b"")
            more_body = message.get("more_body", False)
            if len(body) < self.minimum_size and not more_body:
                await self.send(self.initial_message)
                await self.send(message)
                return
            self._apply_compression(message, more_body=more_body)
            await self.send(self.initial_message)
            await self.send(message)
            return

        more_body = message.get("more_body", False)
        message["body"] = self._compress_chunk(message.get("body", b""), more_body=more_body)
        await self.send(message)

    async def _flush_start_then_send(self, message: Message) -> None:
        if not self.started:
            self.started = True
            await self.send(self.initial_message)
        await self.send(message)

    def _apply_compression(self, message: Message, *, more_body: bool) -> None:
        compressed = self._compress_chunk(message.get("body", b""), more_body=more_body)
        headers = MutableHeaders(raw=self.initial_message["headers"])
        headers.add_vary_header("Accept-Encoding")
        headers["Content-Encoding"] = "gzip"
        if more_body:
            del headers["Content-Length"]
        else:
            headers["Content-Length"] = str(len(compressed))
        message["body"] = compressed

    def _compress_chunk(self, body: bytes, *, more_body: bool) -> bytes:
        self.gzip_file.write(body)
        if not more_body:
            self.gzip_file.close()
        compressed = self.gzip_buffer.getvalue()
        self.gzip_buffer.seek(0)
        self.gzip_buffer.truncate()
        return compressed


async def _unattached_send(message: Message) -> NoReturn:
    raise RuntimeError("send awaitable not set")
