"""The relay connection: encrypted, and only to a relay whose certificate
verifies (#1013).

`smtplib.starttls()` with no context builds one that accepts any certificate,
so a man in the middle presented their own and received the relay password on
the `AUTH` that followed. Every case here runs real TLS against a relay on a
thread (`tests/smtp_relay.py`); the certificate is made per test.
"""
from __future__ import annotations

import smtplib
import ssl

import pytest

from app.auth.mail import (
    OutgoingMessage,
    SmtpSecurity,
    SmtpTransport,
    transport_from_environment,
)
from app.deployment import validate_mail_configuration
from tests.smtp_relay import HOST, FakeRelay, self_signed_certificate, skip_fqdn_lookup

MESSAGE = OutgoingMessage(
    to_address="player@example.test",
    subject="Reset your Sketchy password",
    body="https://sketchy.example/reset-password?token=abc123",
)


@pytest.fixture(autouse=True)
def _no_fqdn_lookup(monkeypatch):
    skip_fqdn_lookup(monkeypatch)


@pytest.fixture
def certificate(tmp_path):
    return self_signed_certificate(tmp_path)


def transport(relay: FakeRelay, security: SmtpSecurity, *, trust: bool) -> SmtpTransport:
    options = {"tls_context": relay.trusting_context} if trust else {}
    return SmtpTransport(
        host=HOST,
        port=relay.port,
        username="relay-user",
        password="relay-secret",
        security=security,
        sender="sketchy@example.test",
        timeout=5,
        **options,
    )


@pytest.mark.parametrize(
    ("security", "implicit_tls"),
    [(SmtpSecurity.STARTTLS, False), (SmtpSecurity.TLS, True)],
)
async def test_a_relay_whose_certificate_does_not_verify_gets_nothing(
    certificate, security, implicit_tls
):
    """The default context: the self-signed relay is exactly what an attacker
    on the path would present. The send fails before the password or the
    message is written."""
    with FakeRelay(*certificate, implicit_tls=implicit_tls) as relay:
        with pytest.raises(ssl.SSLCertVerificationError):
            await transport(relay, security, trust=False).send(MESSAGE)
    assert relay.logins == []
    assert relay.messages == []


@pytest.mark.parametrize(
    ("security", "implicit_tls"),
    [(SmtpSecurity.STARTTLS, False), (SmtpSecurity.TLS, True)],
)
async def test_a_relay_whose_certificate_verifies_is_sent_to_over_tls(
    certificate, security, implicit_tls
):
    with FakeRelay(*certificate, implicit_tls=implicit_tls) as relay:
        await transport(relay, security, trust=True).send(MESSAGE)
    assert relay.logins == [("relay-user", "relay-secret", True)]
    assert len(relay.messages) == 1
    assert b"token=abc123" in relay.messages[0]


async def test_a_trusted_certificate_for_another_host_is_refused(certificate):
    """Trusting the authority is half of it; the certificate must also name
    the host asked for. The relay's names 127.0.0.1 only."""
    with FakeRelay(*certificate) as relay:
        carrier = SmtpTransport(
            host="localhost",
            port=relay.port,
            username="relay-user",
            password="relay-secret",
            security=SmtpSecurity.STARTTLS,
            sender="sketchy@example.test",
            timeout=5,
            tls_context=relay.trusting_context,
        )
        with pytest.raises(ssl.SSLCertVerificationError, match="match|mismatch"):
            await carrier.send(MESSAGE)
    assert relay.logins == []


async def test_a_relay_that_does_not_offer_starttls_is_not_spoken_to_in_the_clear(
    certificate,
):
    """Stripping STARTTLS from the EHLO answer is the other way to sit in the
    middle; the send refuses rather than carrying on unencrypted."""
    with FakeRelay(*certificate, offer_starttls=False) as relay:
        with pytest.raises(smtplib.SMTPNotSupportedError):
            await transport(relay, SmtpSecurity.STARTTLS, trust=True).send(MESSAGE)
    assert relay.logins == []
    assert relay.messages == []


async def test_none_sends_in_the_clear_when_asked_to(certificate):
    with FakeRelay(*certificate, offer_starttls=False) as relay:
        await transport(relay, SmtpSecurity.NONE, trust=False).send(MESSAGE)
    assert relay.logins == [("relay-user", "relay-secret", False)]


@pytest.mark.parametrize(
    ("environ", "security", "port"),
    [
        ({}, SmtpSecurity.STARTTLS, 587),
        ({"SMTP_SECURITY": "tls"}, SmtpSecurity.TLS, 465),
        ({"SMTP_SECURITY": " TLS "}, SmtpSecurity.TLS, 465),
        ({"SMTP_SECURITY": "none"}, SmtpSecurity.NONE, 587),
        ({"SMTP_SECURITY": "tls", "SMTP_PORT": "2465"}, SmtpSecurity.TLS, 2465),
    ],
)
def test_the_mode_picks_the_default_port(environ, security, port):
    carrier = transport_from_environment({"SMTP_HOST": "relay.example", **environ})
    assert isinstance(carrier, SmtpTransport)
    assert carrier._security is security
    assert carrier._port == port


def test_an_unknown_mode_is_refused_at_startup_in_every_environment():
    """A typo read as a default would be harmless one way and not the other."""
    for env in ("development", "test", "production"):
        with pytest.raises(RuntimeError, match="SMTP_SECURITY must be one of"):
            validate_mail_configuration(
                {"SKETCHY_ENV": env, "SMTP_HOST": "relay.example", "SMTP_SECURITY": "ssl"}
            )


def test_the_retired_starttls_switch_is_refused_rather_than_ignored():
    with pytest.raises(RuntimeError, match="replaced by SMTP_SECURITY"):
        validate_mail_configuration(
            {"SKETCHY_ENV": "development", "SMTP_HOST": "relay.example", "SMTP_STARTTLS": "0"}
        )


def test_production_refuses_an_unencrypted_relay_with_a_password():
    with pytest.raises(RuntimeError, match="in the clear"):
        validate_mail_configuration(
            {
                "SKETCHY_ENV": "production",
                "SMTP_HOST": "relay.example",
                "SMTP_SECURITY": "none",
                "SMTP_PASSWORD": "secret",
            }
        )
    # A relay on the same host needs no password, and is allowed.
    validate_mail_configuration(
        {"SKETCHY_ENV": "production", "SMTP_HOST": "localhost", "SMTP_SECURITY": "none"}
    )
    # Outside production the choice is the operator's.
    validate_mail_configuration(
        {
            "SKETCHY_ENV": "development",
            "SMTP_HOST": "relay.example",
            "SMTP_SECURITY": "none",
            "SMTP_PASSWORD": "secret",
        }
    )
