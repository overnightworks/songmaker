"""An HTTPS issuer stand-in a child web process reaches by URL.

``FakeIssuer``'s key set and token answers sit behind a self-signed certificate made here. A
child trusts it only through ``SSL_CERT_FILE``, which the production HTTPS client honours, so
the refresh runs the production transport and verification end to end.
"""

from __future__ import annotations

import datetime
import ipaddress
import ssl
import threading
import urllib.parse
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Final

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from pydantic import SecretStr
from support.fake_oidc_issuer import FakeIssuer
from webauth.oidc import TokenRequest

LOOPBACK: Final = "127.0.0.1"
REALM_PATH: Final = "/realms/test"
_CERTIFICATE_DAYS: Final = 1
_KEY_SET_PATH: Final = f"{REALM_PATH}/protocol/openid-connect/certs"
_TOKEN_PATH: Final = f"{REALM_PATH}/protocol/openid-connect/token"
_NOT_FOUND: Final = 404


@dataclass(frozen=True)
class HttpsIssuer:
    """The stand-in's issuer URL, the certificate to trust, and the realm it answers for."""

    url: str
    ca_file: Path
    realm: FakeIssuer


def _write_self_signed_certificate(directory: Path) -> tuple[Path, Path]:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, LOOPBACK)])
    now = datetime.datetime.now(datetime.timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(days=_CERTIFICATE_DAYS))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(LOOPBACK))]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    certificate_file = directory / "issuer.pem"
    key_file = directory / "issuer.key"
    certificate_file.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
    )
    return certificate_file, key_file


class _RealmServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, handler_class: type[BaseHTTPRequestHandler]) -> None:
        super().__init__((LOOPBACK, 0), handler_class)
        self.realm: FakeIssuer


def _realm_handler() -> type[BaseHTTPRequestHandler]:
    class IssuerRequestHandler(BaseHTTPRequestHandler):
        server: _RealmServer

        def do_GET(self) -> None:  # noqa: N802 - the name http.server dispatches on
            if self.path == _KEY_SET_PATH:
                self._answer(200, self.server.realm.key_set(self.path))
            else:
                self._answer(_NOT_FOUND, b"")

        def do_POST(self) -> None:  # noqa: N802 - the name http.server dispatches on
            if self.path != _TOKEN_PATH:
                self._answer(_NOT_FOUND, b"")
                return
            body = self.rfile.read(int(self.headers.get("content-length", 0))).decode()
            form = {
                name: values[0] for name, values in urllib.parse.parse_qs(body).items()
            }
            request = TokenRequest(
                self.path, form, SecretStr(self.headers.get("authorization", "")),
            )
            answer = self.server.realm.token_answer(request)
            self._answer(answer.status, answer.body)

        def _answer(self, status: int, body: bytes) -> None:
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            """Keep the test output free of per-request lines."""

    return IssuerRequestHandler


@contextmanager
def serve_issuer(directory: Path, *, client_id: str) -> Iterator[HttpsIssuer]:
    """Serve a realm over HTTPS on a free loopback port; stop it on exit."""
    certificate_file, key_file = _write_self_signed_certificate(directory)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificate_file, key_file)
    server = _RealmServer(_realm_handler())
    server.socket = context.wrap_socket(server.socket, server_side=True)
    url = f"https://{LOOPBACK}:{server.server_address[1]}{REALM_PATH}"
    server.realm = FakeIssuer(url, client_id)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield HttpsIssuer(url, certificate_file, server.realm)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
