"""A TCP hop between web processes and the case's Redis that can cut the line or lose every key.

The processes connect to the proxy; the proxy forwards bytes to the real server, so every
command is the real server's answer. It can also hold one reply back after the server has run
the command, so a test acts between a process's read and what the process does with it.
"""

from __future__ import annotations

import socket
import threading
from collections.abc import Iterator
from contextlib import closing, contextmanager
from urllib.parse import urlsplit, urlunsplit

from redis import Redis

LOOPBACK = "127.0.0.1"
CHUNK_BYTES = 65536
ACCEPT_POLL_SECONDS = 0.2
HELD_REPLY_LIMIT_SECONDS = 10.0


class RedisProxy:
    def __init__(self, server_url: str) -> None:
        self._server_url = server_url
        parts = urlsplit(server_url)
        self._server_address = (parts.hostname, parts.port)
        self._listener = self._listen(0)
        self._port = self._listener.getsockname()[1]
        self._lock = threading.Lock()
        self._connections: list[socket.socket] = []
        self._cut = False
        self._reply_lost = False
        self._holding_for: bytes | None = None
        self._reply_held = threading.Event()
        self._reply_released = threading.Event()
        self._closing = threading.Event()
        self._acceptor = threading.Thread(target=self._accept_until_closed, daemon=True)

    @property
    def url(self) -> str:
        """The server's URL with the proxy's address."""
        parts = urlsplit(self._server_url)
        return urlunsplit(parts._replace(netloc=f"{LOOPBACK}:{self._port}"))

    def start(self) -> None:
        self._acceptor.start()

    def cut(self) -> None:
        """Drop every connection and refuse new ones, as an unreachable server does."""
        with self._lock:
            self._cut = True
        self._drop_connections()

    def lose_next_reply(self) -> None:
        """Run the next command on the server but drop its reply and the line, as a reset does."""
        with self._lock:
            self._reply_lost = True

    def hold_next_reply_to(self, request_part: bytes) -> None:
        """Run the next command that contains ``request_part`` but hold its reply back.

        The reply goes out when ``release_held_reply`` is called. Only one reply is held.
        """
        with self._lock:
            self._holding_for = request_part
        self._reply_held.clear()
        self._reply_released.clear()

    def wait_until_a_reply_is_held(self, *, deadline_seconds: float) -> bool:
        return self._reply_held.wait(deadline_seconds)

    def release_held_reply(self) -> None:
        self._reply_released.set()

    def refuse(self) -> None:
        """Drop every connection and stop listening, as a stopped server's address does."""
        self.cut()
        self._closing.set()
        self._acceptor.join()
        self._listener.close()
        self._closing.clear()

    def restore(self) -> None:
        if self._listener.fileno() == -1:
            self._listener = self._listen(self._port)
            self._acceptor = threading.Thread(target=self._accept_until_closed, daemon=True)
            self._acceptor.start()
        with self._lock:
            self._cut = False

    def restart_empty(self) -> None:
        """Lose every key and every connection, as a server that restarted empty does."""
        with Redis.from_url(self._server_url) as server:
            server.flushdb()
        self._drop_connections()

    def close(self) -> None:
        self._reply_released.set()
        self._closing.set()
        self._acceptor.join()
        self._listener.close()
        self._drop_connections()

    @staticmethod
    def _listen(port: int) -> socket.socket:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((LOOPBACK, port))
        listener.listen()
        listener.settimeout(ACCEPT_POLL_SECONDS)
        return listener

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
            reply_is_to_hold = threading.Event()
            threading.Thread(
                target=self._pump_requests, args=(client, server, reply_is_to_hold), daemon=True,
            ).start()
            threading.Thread(
                target=self._pump_replies, args=(server, client, reply_is_to_hold), daemon=True,
            ).start()

    def _pump_requests(
        self, client: socket.socket, server: socket.socket, reply_is_to_hold: threading.Event,
    ) -> None:
        try:
            while data := client.recv(CHUNK_BYTES):
                with self._lock:
                    if self._holding_for is not None and self._holding_for in data:
                        self._holding_for = None
                        reply_is_to_hold.set()
                server.sendall(data)
        except OSError:
            pass
        finally:
            _shut(client)
            _shut(server)

    def _pump_replies(
        self, server: socket.socket, client: socket.socket, reply_is_to_hold: threading.Event,
    ) -> None:
        try:
            while data := server.recv(CHUNK_BYTES):
                with self._lock:
                    lost, self._reply_lost = self._reply_lost, False
                if lost:
                    return
                if reply_is_to_hold.is_set():
                    reply_is_to_hold.clear()
                    self._reply_held.set()
                    self._reply_released.wait(HELD_REPLY_LIMIT_SECONDS)
                client.sendall(data)
        except OSError:
            pass
        finally:
            _shut(server)
            _shut(client)


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
