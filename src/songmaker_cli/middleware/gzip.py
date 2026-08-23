"""Raw ASGI middleware: gzip-compress JSON/text/JS responses only.

Starlette's `GZipMiddleware` decides purely from the `Accept-Encoding`
request header and the response size -- it has no notion of `Content-Type`,
status code, byte-range headers, or `Accept-Encoding` q-values, and it isn't
instance-configurable beyond that. Left unguarded (or guarded only by
request path), it would:

  - re-compress already-lossy-compressed binary media (audio, cover
    images, icons, fonts) for zero size benefit and wasted CPU/latency;
  - gzip a 206 Partial Content response, or any response carrying
    `Content-Range`, producing a `Content-Length` that no longer describes
    the byte range the client actually asked for;
  - compress for a client that explicitly opted out with `gzip;q=0`, since
    a naive `"gzip" in header` substring check can't see q-values.

So this module reimplements just enough of Starlette's streaming-safe
compression algorithm to decide from the *response*, not the request path:

  - Content-Type: an explicit allowlist (JSON, text/* except
    `text/event-stream`, JS, the web app manifest). Everything else --
    audio/*, image/*, video/*, font/*, application/octet-stream, PDFs,
    binary blobs of any kind -- passes through untouched. This also covers
    the SvelteKit static bundle under `/_app` (JS/CSS, both allowlisted).
  - Status code: only 200. Redirects, errors, and 206 Partial Content
    never reach the compression path.
  - `Content-Range`: skip if present, so a byte-range response's
    `Content-Length` always matches the bytes it actually sent. This is
    deliberately *not* gated on `Accept-Ranges` -- every `FileResponse` in
    this app (including the static frontend bundle) sets that header by
    default, and it says nothing about *this* response being a range;
    excluding on its presence would silently stop compressing the entire
    frontend bundle. When a response IS compressed, `Accept-Ranges` is
    instead deleted (matching nginx's gzip behavior), since byte offsets
    into the compressed stream no longer correspond to the original file.
  - `Accept-Encoding` negotiation: a real q-value parse (RFC 9110 -- a
    coding is usable unless its q-value is explicitly 0), not a substring
    check, so `gzip;q=0` is honored.
  - `Vary: Accept-Encoding` is added to every response whose bytes *could*
    vary by encoding (content-type/status/range-eligible), regardless of
    whether this particular request's client asked for gzip -- otherwise a
    downstream cache could serve one client's uncompressed copy to another
    client that does support gzip, or vice versa.

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

`_CompressionResponder` deliberately mirrors the message-buffering shape of
`starlette.middleware.gzip`'s own responder -- diff against that module on
a Starlette upgrade to catch any shape changes worth adopting here too.
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
_GZIP_CODING: Final[str] = "gzip"
_WILDCARD_CODING: Final[str] = "*"
_QVALUE_PARAM_PREFIX: Final[str] = "q="
_DEFAULT_QVALUE: Final[float] = 1.0
_REJECTED_QVALUE: Final[float] = 0.0


def _is_compressible_content_type(content_type: str) -> bool:
    if content_type.startswith(_NEVER_COMPRESS_CONTENT_TYPE_PREFIXES):
        return False
    return content_type.startswith(_COMPRESSIBLE_CONTENT_TYPE_PREFIXES)


def _is_variable_by_encoding(status: int, headers: Headers) -> bool:
    """True when this response's bytes could differ by `Accept-Encoding`.

    Independent of whether *this* request's client actually asked for
    gzip -- see the module docstring's `Vary` note.
    """
    if status != _HTTP_OK:
        return False
    if "content-encoding" in headers:
        return False
    if "content-range" in headers:
        return False
    return _is_compressible_content_type(headers.get("content-type", ""))


def _qvalue(param: str) -> float:
    try:
        return float(param)
    except ValueError:
        return _REJECTED_QVALUE


def _accepts_gzip(accept_encoding: str) -> bool:
    """RFC 9110 `Accept-Encoding` negotiation for the `gzip` coding.

    A coding is usable unless its q-value is explicitly 0 -- `gzip;q=0`
    must not be compressed even though `"gzip" in header` would say yes.
    An explicit `gzip` entry always wins over a `*` wildcard entry.
    """
    gzip_qvalue: float | None = None
    wildcard_qvalue: float | None = None
    for entry in accept_encoding.split(","):
        parts = [part.strip() for part in entry.split(";")]
        coding = parts[0].lower()
        if not coding:
            continue
        qvalue = _DEFAULT_QVALUE
        for param in parts[1:]:
            if param.startswith(_QVALUE_PARAM_PREFIX):
                qvalue = _qvalue(param[len(_QVALUE_PARAM_PREFIX):])
        if coding == _GZIP_CODING:
            gzip_qvalue = qvalue
        elif coding == _WILDCARD_CODING:
            wildcard_qvalue = qvalue
    if gzip_qvalue is not None:
        return gzip_qvalue > _REJECTED_QVALUE
    if wildcard_qvalue is not None:
        return wildcard_qvalue > _REJECTED_QVALUE
    return False


class SelectiveGZipMiddleware:
    """Gzip JSON/text/JS responses; never binary media or byte-range responses."""

    def __init__(self, app: ASGIApp, minimum_size: int, compresslevel: int) -> None:
        self.app = app
        self.minimum_size = minimum_size
        self.compresslevel = compresslevel

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        accepts_gzip = _accepts_gzip(Headers(scope=scope).get("accept-encoding", ""))
        responder = _CompressionResponder(
            self.app, self.minimum_size, self.compresslevel, accepts_gzip=accepts_gzip,
        )
        await responder(scope, receive, send)


class _CompressionResponder:
    """Buffers just enough of one response to decide, then streams the rest.

    Mirrors Starlette's own `GZipMiddleware` responder shape (defer the
    `http.response.start` message until the first body chunk decides
    compress-or-passthrough), generalized from a hardcoded content-type
    exclusion to the status/header-aware `_is_variable_by_encoding` check
    above, and split from the per-request `accepts_gzip` decision so
    `Vary: Accept-Encoding` can be added even when this particular
    request's client didn't ask for gzip.
    """

    def __init__(
        self, app: ASGIApp, minimum_size: int, compresslevel: int, *, accepts_gzip: bool,
    ) -> None:
        self.app = app
        self.minimum_size = minimum_size
        self.accepts_gzip = accepts_gzip
        self.send: Send = _unattached_send
        self.initial_message: Message = {}
        self.started = False
        self.is_variable = False
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
            self.is_variable = _is_variable_by_encoding(self.initial_message["status"], headers)
            self.should_compress = self.is_variable and self.accepts_gzip
            return

        if message_type != "http.response.body" or not self.should_compress:
            await self._forward_uncompressed(message)
            return

        if not self.started:
            self.started = True
            body = message.get("body", b"")
            more_body = message.get("more_body", False)
            if len(body) >= self.minimum_size or more_body:
                self._apply_compression(message, more_body=more_body)
            await self._send_initial_message()
            await self.send(message)
            return

        more_body = message.get("more_body", False)
        message["body"] = self._compress_chunk(message.get("body", b""), more_body=more_body)
        await self.send(message)

    async def _forward_uncompressed(self, message: Message) -> None:
        if not self.started:
            self.started = True
            await self._send_initial_message()
        await self.send(message)

    async def _send_initial_message(self) -> None:
        if self.is_variable:
            headers = MutableHeaders(raw=self.initial_message["headers"])
            headers.add_vary_header("Accept-Encoding")
        await self.send(self.initial_message)

    def _apply_compression(self, message: Message, *, more_body: bool) -> None:
        compressed = self._compress_chunk(message.get("body", b""), more_body=more_body)
        headers = MutableHeaders(raw=self.initial_message["headers"])
        headers["Content-Encoding"] = "gzip"
        del headers["Accept-Ranges"]
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
