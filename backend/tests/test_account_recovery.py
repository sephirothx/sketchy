"""Getting back into an account, and refusing to help anyone else in."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth.mail import MemoryTransport, deliver_pending
from app.auth.middleware import SessionAuthMiddleware
from app.auth.password_reset import (
    OperatorResetError,
    reset_password_as_operator,
)
from app.auth.routes import create_auth_router
from app.auth.tokens import AuthTokenPurpose
from app.db.models import (
    AuditEvent,
    AuthSession,
    AuthToken,
    Base,
    EmailOutboxEntry,
    User,
)
from app.domain_values import EmailOutboxState
from app.repositories.sqlalchemy import SqlAlchemyUserRepository


pytestmark = pytest.mark.asyncio
PASSWORD = "a-good-password"
NEW_PASSWORD = "an-even-better-password"


@pytest_asyncio.fixture
async def env(monkeypatch):
    monkeypatch.setenv("IP_HASH_SECRET", "recovery-test-secret")
    monkeypatch.delenv("SMTP_HOST", raising=False)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware, session_factory=factory)
    app.include_router(create_auth_router(SqlAlchemyUserRepository(factory), factory))

    clients: list[AsyncClient] = []

    def new_client() -> AsyncClient:
        client = AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        )
        clients.append(client)
        return client

    try:
        yield new_client, factory
    finally:
        for client in clients:
            await client.aclose()
        await engine.dispose()


async def register(client: AsyncClient, username: str, email: str | None = None) -> dict:
    assert (await client.get("/api/auth/me")).status_code == 200
    body = {"username": username, "password": PASSWORD}
    if email is not None:
        body["email"] = email
    response = await client.post("/api/auth/register", json=body)
    assert response.status_code == 200, response.text
    return response.json()


async def drain(factory) -> MemoryTransport:
    transport = MemoryTransport()
    await deliver_pending(factory, transport=transport, base_url="http://test")
    return transport


def token_in(transport: MemoryTransport, index: int = -1) -> str:
    body = transport.sent[index].body
    return body.split("token=")[1].split()[0].strip()


async def verify_via_email(client: AsyncClient, factory) -> str:
    transport = await drain(factory)
    response = await client.post(
        "/api/auth/email/verify", json={"token": token_in(transport)}
    )
    assert response.status_code == 200, response.text
    return response.json()["address"]


async def test_an_offered_address_is_not_recorded_until_it_is_proved(env):
    """A typo must not hand the account to whoever owns the address typed."""
    new_client, factory = env
    http = new_client()
    account = await register(http, "Claimant", email="Claimant@Example.COM ")

    async with factory() as session:
        stored = await session.get(User, UUID(account["id"]))
        assert stored is not None
        assert stored.email is None, "an unproved address reached the account"
        assert stored.email_verified_at is None
        pending = await session.scalar(select(AuthToken.email))
        # Normalized on the way in, matching ck_users_email_normalized.
        assert pending == "claimant@example.com"

    state = (await http.get("/api/auth/email")).json()
    assert state == {
        "address": None,
        "verified": False,
        "pendingAddress": "claimant@example.com",
        "reminderDue": True,
        "deliveryConfigured": False,
    }

    assert await verify_via_email(http, factory) == "claimant@example.com"

    async with factory() as session:
        stored = await session.get(User, UUID(account["id"]))
        assert stored is not None
        assert stored.email == "claimant@example.com"
        assert stored.email_verified_at is not None
        assert await session.scalar(select(func.count(AuthToken.token_hash))) == 0


async def test_an_unproved_address_reserves_nothing(env):
    """Otherwise anyone could park on a mailbox they do not control."""
    new_client, factory = env
    squatter, owner = new_client(), new_client()
    await register(squatter, "Squatter", email="shared@example.com")
    await register(owner, "RealOwner")

    # The second account may still claim it, because the first proved nothing.
    assert (
        await owner.put("/api/auth/email", json={"email": "shared@example.com"})
    ).status_code == 200
    transport = await drain(factory)
    owner_token = token_in(transport)
    assert (
        await owner.post("/api/auth/email/verify", json={"token": owner_token})
    ).status_code == 200

    # Now it is taken, and the first account's older link cannot take it back.
    squatter_token = token_in(transport, 0)
    refused = await squatter.post(
        "/api/auth/email/verify", json={"token": squatter_token}
    )
    assert refused.status_code == 409


async def test_a_reset_says_the_same_thing_whether_or_not_the_account_exists(env):
    """The response is not a place to learn which usernames are real."""
    new_client, factory = env
    http = new_client()
    await register(new_client(), "Findable", email="findable@example.com")

    real = await http.post("/api/auth/password/forgot", json={"identifier": "Findable"})
    invented = await http.post(
        "/api/auth/password/forgot", json={"identifier": "NobodyAtAll"}
    )

    assert real.status_code == invented.status_code == 200
    assert real.json() == invented.json()


async def test_a_reset_needs_a_proved_address_not_merely_a_typed_one(env):
    """An unverified address is not evidence the requester owns the account."""
    new_client, factory = env
    http = new_client()
    await register(http, "Unproved", email="unproved@example.com")
    (await drain(factory)).sent.clear()

    await http.post("/api/auth/password/forgot", json={"identifier": "Unproved"})

    assert (await drain(factory)).sent == [], "a reset link went to an unproved address"


async def test_a_completed_reset_signs_every_device_out(env):
    """A stolen session must not survive the recovery it forced."""
    new_client, factory = env
    laptop, phone, stranger = new_client(), new_client(), new_client()
    account = await register(laptop, "Recovering", email="recovering@example.com")
    await verify_via_email(laptop, factory)
    # A second signed-in device, standing in for the one that was taken.
    assert (
        await phone.post(
            "/api/auth/login", json={"username": "Recovering", "password": PASSWORD}
        )
    ).status_code == 200

    await stranger.post("/api/auth/password/forgot", json={"identifier": "Recovering"})
    transport = await drain(factory)
    assert transport.sent[-1].to_address == "recovering@example.com"

    reset = await laptop.post(
        "/api/auth/password/reset",
        json={"token": token_in(transport), "password": NEW_PASSWORD},
    )
    assert reset.status_code == 200

    # The other device is out, the old password no longer works, and the one
    # that performed the reset is signed back in.
    assert (await phone.get("/api/auth/me")).json()["id"] != account["id"]
    old = await new_client().post(
        "/api/auth/login", json={"username": "Recovering", "password": PASSWORD}
    )
    assert old.status_code == 401
    assert (await laptop.get("/api/auth/me")).json()["id"] == account["id"]

    async with factory() as session:
        live = await session.scalar(
            select(func.count(AuthSession.id)).where(
                AuthSession.user_id == UUID(account["id"]),
                AuthSession.revoked_at.is_(None),
            )
        )
        assert live == 1, "only the session issued by the reset should remain"
        kinds = set(
            (await session.scalars(select(AuditEvent.event_type))).all()
        )
        assert {"account.password_reset_requested", "account.password_reset"} <= kinds


async def test_a_reset_link_works_once(env):
    new_client, factory = env
    http = new_client()
    await register(http, "OnceOnly", email="once@example.com")
    await verify_via_email(http, factory)
    await http.post("/api/auth/password/forgot", json={"identifier": "OnceOnly"})
    token = token_in(await drain(factory))

    first = await http.post(
        "/api/auth/password/reset", json={"token": token, "password": NEW_PASSWORD}
    )
    second = await http.post(
        "/api/auth/password/reset", json={"token": token, "password": "third-password"}
    )

    assert first.status_code == 200
    assert second.status_code == 400


async def test_an_expired_link_is_refused(env):
    new_client, factory = env
    http = new_client()
    await register(http, "Slow", email="slow@example.com")
    await verify_via_email(http, factory)
    await http.post("/api/auth/password/forgot", json={"identifier": "Slow"})
    token = token_in(await drain(factory))

    async with factory() as session:
        async with session.begin():
            record = await session.scalar(
                select(AuthToken).where(
                    AuthToken.purpose == AuthTokenPurpose.PASSWORD_RESET.value
                )
            )
            record.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)

    refused = await http.post(
        "/api/auth/password/reset", json={"token": token, "password": NEW_PASSWORD}
    )
    assert refused.status_code == 400


async def test_the_reminder_returns_rather_than_repeats(env):
    new_client, factory = env
    http = new_client()
    await register(http, "Forgetful")

    assert (await http.get("/api/auth/email")).json()["reminderDue"] is True
    assert (await http.post("/api/auth/email/reminder-seen")).status_code == 200
    assert (await http.get("/api/auth/email")).json()["reminderDue"] is False

    async with factory() as session:
        async with session.begin():
            from app.db.models import UserSettings

            settings = await session.scalar(select(UserSettings))
            settings.email_reminder_last_shown_at = datetime.now(
                timezone.utc
            ) - timedelta(days=8)

    assert (await http.get("/api/auth/email")).json()["reminderDue"] is True


async def test_a_proved_address_ends_the_reminder(env):
    new_client, factory = env
    http = new_client()
    await register(http, "Prepared", email="prepared@example.com")
    await verify_via_email(http, factory)

    assert (await http.get("/api/auth/email")).json() == {
        "address": "prepared@example.com",
        "verified": True,
        "pendingAddress": None,
        "reminderDue": False,
        "deliveryConfigured": False,
    }


async def test_the_operator_can_reset_without_any_mail_server(env):
    """The deployment this game documents by default cannot send mail at all."""
    new_client, factory = env
    http, other = new_client(), new_client()
    account = await register(http, "Stranded")
    assert (
        await other.post(
            "/api/auth/login", json={"username": "Stranded", "password": PASSWORD}
        )
    ).status_code == 200

    result = await reset_password_as_operator(
        factory,
        username="stranded",
        password=NEW_PASSWORD,
        reason="Player asked in person",
    )

    assert result.user_id == account["id"]
    assert result.sessions_revoked >= 1
    assert result.notified is False
    assert (
        await new_client().post(
            "/api/auth/login", json={"username": "Stranded", "password": NEW_PASSWORD}
        )
    ).status_code == 200

    async with factory() as session:
        event = await session.scalar(
            select(AuditEvent).where(
                AuditEvent.event_type == "account.password_reset_by_operator"
            )
        )
        assert event is not None
        assert event.details["reason"] == "Player asked in person"
        assert event.target_id == account["id"]


async def test_the_operator_reset_refuses_an_unknown_or_guest_account(env):
    new_client, factory = env
    guest = new_client()
    assert (await guest.get("/api/auth/me")).status_code == 200

    with pytest.raises(OperatorResetError):
        await reset_password_as_operator(
            factory, username="nobody", password=NEW_PASSWORD, reason="test"
        )
    with pytest.raises(OperatorResetError):
        await reset_password_as_operator(
            factory, username="Somebody", password="short", reason="test"
        )


async def test_a_message_that_cannot_be_sent_is_retried_then_given_up_on(env):
    """A silent mail misconfiguration should be visible, not merely quiet."""
    new_client, factory = env
    http = new_client()
    await register(http, "Unreachable", email="unreachable@example.com")

    class BrokenTransport:
        def __init__(self):
            self.attempts = 0

        async def send(self, message):
            self.attempts += 1
            raise OSError("connection refused")

    broken = BrokenTransport()
    now = datetime.now(timezone.utc)
    for attempt in range(5):
        await deliver_pending(
            factory,
            transport=broken,
            now=now + timedelta(hours=4 * attempt),
            base_url="http://test",
        )

    assert broken.attempts == 5
    async with factory() as session:
        entry = await session.scalar(select(EmailOutboxEntry))
        assert entry.state == EmailOutboxState.FAILED.value
        assert entry.attempts == 5
        assert "connection refused" in entry.last_error


async def test_deleting_an_account_takes_its_live_links_and_queued_mail(env):
    """A reset link outliving the account is a way into something that is gone."""
    new_client, factory = env
    http = new_client()
    account = await register(http, "Departing", email="departing@example.com")
    await verify_via_email(http, factory)
    await http.post("/api/auth/password/forgot", json={"identifier": "Departing"})

    deleted = await http.request(
        "DELETE", "/api/auth/account", json={"password": PASSWORD}
    )
    assert deleted.status_code == 200, deleted.text

    async with factory() as session:
        assert await session.scalar(select(func.count(AuthToken.token_hash))) == 0
        addresses = set(
            (await session.scalars(select(EmailOutboxEntry.to_address))).all()
        )
        assert "departing@example.com" not in addresses
        assert await session.scalar(
            select(func.count(EmailOutboxEntry.id)).where(
                EmailOutboxEntry.user_id == UUID(account["id"])
            )
        ) == 0


async def test_a_server_that_cannot_send_mail_says_what_it_would_have_sent(caplog):
    """The zero-configuration deployment has no SMTP, and answers that by
    logging the message. If the log goes nowhere, recovery silently does
    nothing at all there - which is worse than failing."""
    import logging

    from app.auth.mail import ConsoleTransport, OutgoingMessage
    from app.logging_config import configure_logging

    configure_logging("info")
    # The handler sits on the tree, not on each module's logger.
    assert logging.getLogger("app").handlers, "the application's logs reach nobody"
    assert logging.getLogger("app.auth.mail").isEnabledFor(logging.INFO)

    with caplog.at_level(logging.INFO, logger="app.auth.mail"):
        await ConsoleTransport().send(
            OutgoingMessage(
                to_address="player@example.com",
                subject="Confirm your Sketchy email address",
                body="Follow this link: http://test/verify-email?token=abc123",
            )
        )

    written = caplog.text
    assert "player@example.com" in written
    # The link is the whole point: without it there is nothing to follow.
    assert "verify-email?token=abc123" in written
