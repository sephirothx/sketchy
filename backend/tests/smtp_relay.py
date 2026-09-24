"""A tiny SMTP relay on a thread, speaking just enough of the protocol for
`SmtpTransport`: EHLO, STARTTLS, AUTH PLAIN, MAIL/RCPT/DATA and QUIT.

Real TLS with a certificate made per test, so what is proved is the handshake
smtplib actually performs - a relay with a certificate nobody trusts must
fail the send, and one whose authority the client was told about must not.
"""
from __future__ import annotations

import base64
import datetime
import ipaddress
import smtplib
import socket
import ssl
import threading
from dataclasses import dataclass, field
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

HOST = "127.0.0.1"


def skip_fqdn_lookup(monkeypatch) -> None:
    """`smtplib.SMTP` asks `socket.getfqdn()` for its EHLO name after the
    greeting, and on a machine whose reverse lookup goes to mDNS that takes
    seconds - longer than a relay waiting for the EHLO. Not the behaviour
    under test."""
    monkeypatch.setattr(smtplib.socket, "getfqdn", lambda name="": "client.test")


def self_signed_certificate(directory: Path) -> tuple[Path, Path]:
    """A certificate for 127.0.0.1 signed by its own key: `(cert, key)`."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "sketchy test relay")])
    now = datetime.datetime.now(datetime.timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(hours=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(HOST))]),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_path = directory / "relay.pem"
    key_path = directory / "relay.key"
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return cert_path, key_path


@dataclass
class FakeRelay:
    """`implicit_tls` wraps the connection before the greeting (port 465);
    otherwise STARTTLS is offered unless `offer_starttls` is false."""

    cert_path: Path
    key_path: Path
    implicit_tls: bool = False
    offer_starttls: bool = True
    # What reached the relay: (username, password) pairs, whether each
    # arrived over TLS, and message bodies.
    logins: list[tuple[str, str, bool]] = field(default_factory=list)
    messages: list[bytes] = field(default_factory=list)
    errors: list[BaseException] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self._server_context.load_cert_chain(self.cert_path, self.key_path)
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.bind((HOST, 0))
        self._listener.listen()
        self._listener.settimeout(0.2)
        self.port = self._listener.getsockname()[1]
        self._stopping = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def trusting_context(self) -> ssl.SSLContext:
        """What a client that knows this relay's authority would build."""
        context = ssl.create_default_context(cafile=str(self.cert_path))
        return context

    def __enter__(self) -> "FakeRelay":
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stopping.set()
        self._thread.join(timeout=5)
        self._listener.close()

    def _serve(self) -> None:
        while not self._stopping.is_set():
            try:
                connection, _ = self._listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            try:
                connection.settimeout(30)
                self._converse(connection)
            except (OSError, ssl.SSLError) as error:
                # A client refusing the certificate aborts the handshake;
                # recorded rather than raised so a test can see it happened.
                self.errors.append(error)
            finally:
                connection.close()

    def _converse(self, connection: socket.socket) -> None:
        secure = False
        if self.implicit_tls:
            connection = self._server_context.wrap_socket(connection, server_side=True)
            secure = True
        reader = connection.makefile("rb")

        def reply(line: str) -> None:
            connection.sendall(line.encode("ascii") + b"\r\n")

        reply("220 relay.test ESMTP")
        while True:
            raw = reader.readline()
            if not raw:
                return
            command = raw.decode("ascii").rstrip("\r\n")
            verb = command.split(" ", 1)[0].upper()
            if verb in {"EHLO", "HELO"}:
                capabilities = ["relay.test", "AUTH PLAIN"]
                if self.offer_starttls and not secure:
                    capabilities.append("STARTTLS")
                for line in capabilities[:-1]:
                    reply(f"250-{line}")
                reply(f"250 {capabilities[-1]}")
            elif verb == "STARTTLS":
                reply("220 go ahead")
                connection = self._server_context.wrap_socket(
                    connection, server_side=True
                )
                reader = connection.makefile("rb")
                secure = True
            elif verb == "AUTH":
                _, _, encoded = command.split(" ", 2)
                _, username, password = base64.b64decode(encoded).split(b"\0")
                self.logins.append((username.decode(), password.decode(), secure))
                reply("235 accepted")
            elif verb in {"MAIL", "RCPT"}:
                reply("250 ok")
            elif verb == "DATA":
                reply("354 go on")
                body = b""
                while not body.endswith(b"\r\n.\r\n"):
                    chunk = reader.readline()
                    if not chunk:
                        return
                    body += chunk
                self.messages.append(body)
                reply("250 queued")
            elif verb == "QUIT":
                reply("221 bye")
                return
            else:
                reply("502 not implemented")
