"""A TCP hop between web processes and the case's Redis that can cut the line or pose as a
Redis server that has just restarted empty.

The processes connect to the proxy; the proxy forwards bytes to the real server, so every
command is the real server's answer except the uptime a restarted server reports.
"""

from __future__ import annotations

import re
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import closing, contextmanager
from urllib.parse import urlsplit, urlunsplit

from redis import Redis

LOOPBACK = "127.0.0.1"
CHUNK_BYTES = 65536
UPTIME_FIELD = re.compile(rb"uptime_in_seconds:(\d+)")
ACCEPT_POLL_SECONDS = 0.2


class RedisProxy:
    def __init__(self, server_url: str) -> None:
        self._server_url = server_url
        parts = urlsplit(server_url)
        self._server_address = (parts.hostname, parts.port)
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.bind((LOOPBACK, 0))
        self._listener.listen()
        self._listener.settimeout(ACCEPT_POLL_SECONDS)
        self._lock = threading.Lock()
        self._connections: list[socket.socket] = []
        self._cut = False
        self._restarted_at: float | None = None
        self._closing = threading.Event()
        self._acceptor = threading.Thread(target=self._accept_until_closed, daemon=True)

    @property
    def url(self) -> str:
        """The server's URL with the proxy's address."""
        parts = urlsplit(self._server_url)
        return urlunsplit(parts._replace(netloc=f"{LOOPBACK}:{self._listener.getsockname()[1]}"))

    def start(self) -> None:
        self._acceptor.start()

    def cut(self) -> None:
        """Drop every connection and refuse new ones, as an unreachable server does."""
        with self._lock:
            self._cut = True
        self._drop_connections()

    def restore(self) -> None:
        with self._lock:
            self._cut = False

    def restart_empty(self) -> None:
        """Lose every key and report an uptime counted from now, as a restarted server does.

        The young uptime is reported before the keys go, so no reader sees the empty
        server with its old age.
        """
        with self._lock:
            self._restarted_at = time.monotonic()
        with Redis.from_url(self._server_url) as server:
            server.flushdb()
        self._drop_connections()

    def close(self) -> None:
        self._closing.set()
        self._acceptor.join()
        self._listener.close()
        self._drop_connections()

    def _uptime_seconds(self) -> int | None:
        with self._lock:
            if self._restarted_at is None:
                return None
            return int(time.monotonic() - self._restarted_at)

    def _drop_connections(self) -> None:
        with self._lock:
            connections, self._connections = self._connections, []
        for connection in connections:
            _shut(connection)

    def _accept_until_closed(self) -> None:
        while not self._closing.is_set():
            try:
                client, _ = self._listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            with self._lock:
                cut = self._cut
            if cut:
                client.close()
                continue
            server = socket.create_connection(self._server_address)
            with self._lock:
                self._connections.extend((client, server))
            threading.Thread(target=self._pump, args=(client, server, False), daemon=True).start()
            threading.Thread(target=self._pump, args=(server, client, True), daemon=True).start()

    def _pump(self, source: socket.socket, sink: socket.socket, from_server: bool) -> None:
        try:
            while data := source.recv(CHUNK_BYTES):
                sink.sendall(self._restarted_reply(data) if from_server else data)
        except OSError:
            pass
        finally:
            _shut(source)
            _shut(sink)

    def _restarted_reply(self, data: bytes) -> bytes:
        """A reply that carries the server's uptime says the restarted server's, same width."""
        uptime = self._uptime_seconds()
        if uptime is None:
            return data

        def restarted(match: re.Match[bytes]) -> bytes:
            width = len(match.group(1))
            return b"uptime_in_seconds:" + str(uptime).rjust(width, "0").encode()[-width:]

        return UPTIME_FIELD.sub(restarted, data)


def _shut(connection: socket.socket) -> None:
    with closing(connection):
        try:
            connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass


@contextmanager
def redis_proxy(server_url: str) -> Iterator[RedisProxy]:
    proxy = RedisProxy(server_url)
    proxy.start()
    try:
        yield proxy
    finally:
        proxy.close()
