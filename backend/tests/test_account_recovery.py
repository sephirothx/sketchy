"""Getting back into an account, and refusing to help anyone else in."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from uuid import UUID

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select

from app.auth.mail import MemoryTransport, deliver_pending
from app.auth.middleware import SessionAuthMiddleware
from app.auth.password_reset import (
    OperatorResetError,
    reset_password_as_operator,
)
from app.auth.routes import create_auth_router
from app.api.user_settings import UserSettingsSeed, seed_user_settings
from app.auth.email import EmailAddressError
from app.auth.recovery import (
    EmailAlreadyInUse,
    RecoveryError,
    _aware,
    change_password,
    email_state,
    mark_reminder_shown,
    request_email_verification,
    request_password_reset,
)
from app.auth.tokens import AuthTokenPurpose
from app.db.models import (
    AuditEvent,
    AuthSession,
    AuthToken,
    EmailOutboxEntry,
    User,
    UserSettings,
    generate_uuid,
)
from app.domain_values import AccountState, EmailOutboxState
from app.repositories.sqlalchemy import SqlAlchemyUserRepository

from tests.dbfixtures import create_test_db


PASSWORD = "a-good-password"
NEW_PASSWORD = "an-even-better-password"


@pytest.fixture
def announced() -> list[str]:
    """Every account the router said had its email state move, in order."""
    return []


@pytest_asyncio.fixture
async def env(monkeypatch, announced):
    monkeypatch.setenv("IP_HASH_SECRET", "recovery-test-secret")
    monkeypatch.delenv("SMTP_HOST", raising=False)
    factory, engine = await create_test_db()
    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware, session_factory=factory)

    async def record(user_id: str) -> None:
        announced.append(user_id)

    app.include_router(
        create_auth_router(
            SqlAlchemyUserRepository(factory),
            factory,
            on_email_state_changed=record,
        )
    )

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
    # No guest step: registering with no account creates one outright.
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
        # Not yet: the first reminder comes a week after signing up.
        "reminderDue": False,
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
        await owner.put("/api/auth/email", json={"email": "shared@example.com", "password": PASSWORD})
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
    # Signed out means holding no account at all now, rather than being handed
    # a fresh guest by the act of asking.
    assert (await phone.get("/api/auth/me")).json() is None
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


async def test_a_busy_pool_refuses_a_real_reset_and_leaves_the_link_usable(env, monkeypatch):
    """The leg of the busy-pool test that actually reaches the hash. With a
    token that names nobody the route refuses before hashing, so a `400` there
    says nothing: the silent-success mutation on this route survived every
    test (#975 fourth review).
    """
    from app.auth import routes as routes_module
    from app.auth.password import PasswordHashingBusy

    new_client, factory = env
    http = new_client()
    await register(http, "BusyReset", email="busyreset@example.com")
    await verify_via_email(http, factory)
    await http.post("/api/auth/password/forgot", json={"identifier": "BusyReset"})
    token = token_in(await drain(factory))
    real_hash = routes_module.hash_password

    async def busy(_password):
        raise PasswordHashingBusy()

    monkeypatch.setattr(routes_module, "hash_password", busy)
    refused = await http.post(
        "/api/auth/password/reset", json={"token": token, "password": NEW_PASSWORD}
    )
    assert refused.status_code == 503, refused.text

    # Nothing was spent: the old password still works, and so does the link.
    monkeypatch.setattr(routes_module, "hash_password", real_hash)
    old = await new_client().post(
        "/api/auth/login", json={"username": "BusyReset", "password": PASSWORD}
    )
    assert old.status_code == 200
    again = await new_client().post(
        "/api/auth/password/reset", json={"token": token, "password": NEW_PASSWORD}
    )
    assert again.status_code == 200, again.text


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


async def _age_the_reminder_clock(factory, days: int = 8) -> None:
    async with factory() as session:
        async with session.begin():
            settings = await session.scalar(select(UserSettings))
            settings.email_reminder_last_shown_at = datetime.now(
                timezone.utc
            ) - timedelta(days=days)


async def test_the_reminder_returns_rather_than_repeats(env):
    new_client, factory = env
    http = new_client()
    await register(http, "Forgetful")
    await _age_the_reminder_clock(factory)

    assert (await http.get("/api/auth/email")).json()["reminderDue"] is True
    assert (await http.post("/api/auth/email/reminder-seen")).status_code == 200
    assert (await http.get("/api/auth/email")).json()["reminderDue"] is False

    await _age_the_reminder_clock(factory)
    assert (await http.get("/api/auth/email")).json()["reminderDue"] is True


async def test_the_first_reminder_waits_a_week_after_signing_up(env):
    """The form has just called the address optional (R-AUTH-15).

    A banner asking for it on the very next page contradicts the form, so the
    clock starts at registration and the first reminder is due a week later.
    """
    new_client, factory = env
    http = new_client()
    await register(http, "Newcomer")

    assert (await http.get("/api/auth/email")).json()["reminderDue"] is False
    await _age_the_reminder_clock(factory, days=6)
    assert (await http.get("/api/auth/email")).json()["reminderDue"] is False
    await _age_the_reminder_clock(factory, days=7)
    assert (await http.get("/api/auth/email")).json()["reminderDue"] is True


async def test_a_claimed_guest_gets_the_same_week(env):
    """Claiming a guest is signing up too: the grace is not for fresh accounts only."""
    new_client, factory = env
    http = new_client()
    guest = await http.post("/api/auth/display-name", json={"displayName": "Lingerer"})
    assert guest.status_code == 200, guest.text
    guest_id = guest.json()["id"]

    account = await register(http, "Lingerer")
    assert account["id"] == guest_id, "registering should have claimed the guest"

    assert (await http.get("/api/auth/email")).json()["reminderDue"] is False
    await _age_the_reminder_clock(factory)
    assert (await http.get("/api/auth/email")).json()["reminderDue"] is True


async def test_a_settings_row_made_before_the_seed_still_gets_the_week(env):
    """Another tab can create the row between the claim and the seed."""
    _, factory = env
    user_id = generate_uuid()
    async with factory() as session:
        async with session.begin():
            session.add(
                User(
                    id=user_id,
                    username="Racer",
                    display_name="Racer",
                    state=AccountState.REGISTERED.value,
                    password_hash="x",
                )
            )
            await session.flush()
            session.add(UserSettings(user_id=user_id))

    # The row exists, so the insert meets the conflict rather than raising -
    # and the browser's values still become the account's (R-SET-03): the row
    # another tab made can only hold defaults.
    seeded = await seed_user_settings(
        factory,
        user_id=str(user_id),
        values=UserSettingsSeed(theme="dark", timeFormat="24h", locale="nl"),
    )
    assert (seeded["theme"], seeded["timeFormat"], seeded["locale"]) == ("dark", "24h", "nl")
    assert (await email_state(factory, user_id=user_id)).reminder_due is False

    # And a clock that is already running is left alone: seeding again never
    # pushes a due reminder back.
    await _age_the_reminder_clock(factory)
    await seed_user_settings(factory, user_id=str(user_id), values=UserSettingsSeed())
    assert (await email_state(factory, user_id=user_id)).reminder_due is True


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


async def test_every_tab_hears_when_the_address_state_moves(env, announced):
    """A standing banner reads the state once; the change comes from elsewhere.

    The confirmation link is opened from a mail client - a new tab, often one
    with no session at all - so the account has to be named from the token,
    and the tabs that were already open have to be told.
    """
    new_client, factory = env
    laptop, mail_client = new_client(), new_client()
    account = await register(laptop, "Tidy")

    offered = await laptop.put("/api/auth/email", json={"email": "tidy@example.com", "password": PASSWORD})
    assert offered.status_code == 200, offered.text
    assert announced == [account["id"]]

    assert await verify_via_email(mail_client, factory) == "tidy@example.com"
    assert announced == [account["id"], account["id"]]

    assert (await laptop.post("/api/auth/email/reminder-seen")).status_code == 200
    assert announced == [account["id"]] * 3


async def test_a_link_that_proves_nothing_announces_nothing(env, announced):
    new_client, _factory = env
    refused = await new_client().post(
        "/api/auth/email/verify", json={"token": "not-a-real-token"}
    )
    assert refused.status_code == 400
    assert announced == []


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


async def test_a_spent_link_is_known_to_be_spent_before_a_password_is_chosen(env):
    """Being told a link is dead after choosing a password is being asked to do
    the work twice."""
    new_client, factory = env
    http = new_client()
    await register(http, "SecondClick", email="second@example.com")
    await verify_via_email(http, factory)
    await http.post("/api/auth/password/forgot", json={"identifier": "SecondClick"})
    token = token_in(await drain(factory))

    good = await http.post("/api/auth/password/reset/check", json={"token": token})
    assert good.json() == {"valid": True}
    # Checking must not spend it: the person has not set a password yet.
    assert (
        await http.post("/api/auth/password/reset/check", json={"token": token})
    ).json() == {"valid": True}

    used = await http.post(
        "/api/auth/password/reset", json={"token": token, "password": NEW_PASSWORD}
    )
    assert used.status_code == 200

    assert (
        await http.post("/api/auth/password/reset/check", json={"token": token})
    ).json() == {"valid": False}
    assert (
        await http.post(
            "/api/auth/password/reset/check", json={"token": "never-existed"}
        )
    ).json() == {"valid": False}


async def test_an_expired_link_is_known_to_be_expired_before_it_is_used(env):
    new_client, factory = env
    http = new_client()
    await register(http, "SlowClicker", email="slow-click@example.com")
    await verify_via_email(http, factory)
    await http.post("/api/auth/password/forgot", json={"identifier": "SlowClicker"})
    token = token_in(await drain(factory))

    async with factory() as session:
        async with session.begin():
            record = await session.scalar(
                select(AuthToken).where(
                    AuthToken.purpose == AuthTokenPurpose.PASSWORD_RESET.value
                )
            )
            record.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)

    checked = await http.post(
        "/api/auth/password/reset/check", json={"token": token}
    )
    assert checked.json() == {"valid": False}
    # And it is still there to be refused, rather than having been swallowed by
    # the check.
    async with factory() as session:
        assert await session.scalar(select(func.count(AuthToken.token_hash))) == 1


# --- the "account does not exist" and "already taken" paths ------------------
#
# Recovery is the authentication path a stranger can reach without credentials,
# so its refusals matter more than its successes. The suite reached those
# refusals through the HTTP surface, which answers identically either way by
# design - so the branches that decide *why* nothing happened were never taken.


async def test_email_state_for_an_account_that_is_not_there_is_simply_empty(env):
    """Called with an id it did not verify itself; it must not raise."""
    _, factory = env
    state = await email_state(factory, user_id=generate_uuid())
    assert (state.address, state.verified, state.pending_address) == (None, False, None)
    assert state.reminder_due is False


async def test_adding_an_email_to_an_account_that_is_not_there_is_refused(env):
    _, factory = env
    with pytest.raises(RecoveryError):
        await request_email_verification(
            factory, user_id=generate_uuid(), email="a@b.test"
        )


async def test_an_invalid_address_is_refused_before_any_lookup(env):
    _, factory = env
    with pytest.raises(EmailAddressError):
        await request_email_verification(
            factory, user_id=generate_uuid(), email="not-an-address"
        )


async def test_a_reminder_creates_settings_for_an_account_that_has_none(env):
    """The row is made on demand; a missing one is not a reason to fail."""
    new_client, factory = env
    registered = await register(new_client(), "Reminded")
    user_id = UUID(registered["id"])

    async with factory() as session:
        await session.execute(delete(UserSettings).where(UserSettings.user_id == user_id))
        await session.commit()

    await mark_reminder_shown(factory, user_id=user_id)
    async with factory() as session:
        settings = await session.get(UserSettings, user_id)
    assert settings is not None
    assert settings.email_reminder_last_shown_at is not None


async def test_a_blank_identifier_never_reaches_the_database(env):
    """An empty form field is not a lookup that could match anything."""
    _, factory = env
    for blank in ("", "   ", "\t"):
        assert await request_password_reset(factory, identifier=blank) is False


async def test_a_reset_for_an_unknown_identifier_sends_nothing(env):
    """Answered identically to a real one at the HTTP layer; here we can look."""
    _, factory = env
    assert await request_password_reset(
        factory, identifier="nobody@nowhere.test"
    ) is False
    assert await request_password_reset(factory, identifier="no-such-player") is False


async def test_verification_is_refused_for_an_address_another_account_holds(env):
    """Two verified accounts on one address is an account-takeover primitive."""
    new_client, factory = env
    first_client = new_client()
    await register(first_client, "First", "shared@example.test")
    await verify_via_email(first_client, factory)
    second = await register(new_client(), "Second")

    with pytest.raises(EmailAlreadyInUse):
        await request_email_verification(
            factory, user_id=UUID(second["id"]), email="shared@example.test"
        )


async def test_a_naive_stored_timestamp_is_read_as_utc():
    """SQLite hands back naive datetimes; a bare one must not read as local."""
    assert _aware(None) is None
    aware = datetime(2026, 9, 1, tzinfo=timezone.utc)
    assert _aware(aware) is aware
    assert _aware(datetime(2026, 9, 1)) == aware


async def test_changing_a_password_keeps_this_device_and_evicts_the_others(env):
    """A change is also how somebody evicts a session they no longer trust."""
    new_client, factory = env
    laptop, phone = new_client(), new_client()
    account = await register(laptop, "Rekeyer", email="rekeyer@example.com")
    await verify_via_email(laptop, factory)
    assert (
        await phone.post(
            "/api/auth/login", json={"username": "Rekeyer", "password": PASSWORD}
        )
    ).status_code == 200

    changed = await laptop.post(
        "/api/auth/password/change",
        json={"currentPassword": PASSWORD, "password": NEW_PASSWORD},
    )
    assert changed.status_code == 200

    # The other device is out, the old password is dead, and the device that
    # made the change is still signed in.
    assert (await phone.get("/api/auth/me")).json() is None
    assert (
        await new_client().post(
            "/api/auth/login", json={"username": "Rekeyer", "password": PASSWORD}
        )
    ).status_code == 401
    assert (
        await new_client().post(
            "/api/auth/login", json={"username": "Rekeyer", "password": NEW_PASSWORD}
        )
    ).status_code == 200
    assert (await laptop.get("/api/auth/me")).json()["id"] == account["id"]

    async with factory() as session:
        kinds = set((await session.scalars(select(AuditEvent.event_type))).all())
        assert "account.password_changed" in kinds


async def test_a_password_change_needs_the_current_password(env):
    new_client, _ = env
    http = new_client()
    await register(http, "Careful")

    refused = await http.post(
        "/api/auth/password/change",
        json={"currentPassword": "not-the-password", "password": NEW_PASSWORD},
    )
    assert refused.status_code == 401
    # And the account still opens with the password it had.
    assert (
        await new_client().post(
            "/api/auth/login", json={"username": "Careful", "password": PASSWORD}
        )
    ).status_code == 200


async def test_a_password_change_holds_the_password_rules(env):
    new_client, _ = env
    http = new_client()
    await register(http, "Rulebound")
    weak = await http.post(
        "/api/auth/password/change",
        json={"currentPassword": PASSWORD, "password": "short"},
    )
    assert weak.status_code == 400


async def test_a_guest_has_no_password_to_change(env):
    new_client, _ = env
    http = new_client()
    await http.post("/api/auth/display-name", json={"displayName": "Passerby"})
    refused = await http.post(
        "/api/auth/password/change",
        json={"currentPassword": PASSWORD, "password": NEW_PASSWORD},
    )
    assert refused.status_code == 403


async def test_changing_the_password_of_an_account_that_is_not_there_does_nothing(env):
    """The route checks credentials first; the writer still refuses on its own."""
    _, factory = env
    assert (
        await change_password(
            factory, user_id=generate_uuid(), password_hash="argon2$not-a-real-hash"
        )
        is False
    )


async def test_a_password_change_without_a_verified_address_sends_no_mail(env):
    """The PASSWORD_CHANGED notice goes only to an address somebody has proved
    they can read (R-AUTH-07); an account without one still gets its audit row."""
    new_client, factory = env
    http = new_client()
    account = await register(http, "Quiet")
    changed = await change_password(
        factory, user_id=UUID(account["id"]), password_hash="argon2$not-a-real-hash"
    )
    assert changed is True
    async with factory() as session:
        assert (await session.scalar(select(func.count(EmailOutboxEntry.id)))) == 0
        kinds = set((await session.scalars(select(AuditEvent.event_type))).all())
        assert "account.password_changed" in kinds
    # Every session went with it, this one included: the route is what signs
    # the caller back in, and nothing here did.
    assert (await http.get("/api/auth/me")).json() is None


# --- #607: one consumer per link, one commit per credential change ---------


async def test_two_submissions_of_one_link_admit_exactly_one_consumer(env):
    """The database, not the caller, decides who spends a token.

    A select followed by an ORM delete let two transactions both read the
    row and both be told yes before either delete ran. The claim is now one
    conditional DELETE ... RETURNING: on PostgreSQL the second waits on the
    row lock and then deletes nothing; on SQLite's single connection it simply
    finds nothing.
    """
    import asyncio

    from app.auth.tokens import consume_token

    new_client, factory = env
    http = new_client()
    await register(http, "Twice", email="twice@example.com")
    await verify_via_email(http, factory)
    await http.post("/api/auth/password/forgot", json={"identifier": "Twice"})
    token = token_in(await drain(factory))

    first_claimed = asyncio.Event()
    release_first = asyncio.Event()

    async def claim(hold: bool):
        async with factory() as session:
            async with session.begin():
                record = await consume_token(
                    session, token=token, purpose=AuthTokenPurpose.PASSWORD_RESET
                )
                if hold:
                    first_claimed.set()
                    await release_first.wait()
                return record

    first = asyncio.create_task(claim(True))
    await first_claimed.wait()
    second = asyncio.create_task(claim(False))
    # On PostgreSQL the second delete is now waiting on the row the first
    # holds; there is nothing observable to wait on for that, so give it a
    # moment to be waiting before the first commits.
    await asyncio.sleep(0.2)
    release_first.set()
    results = await asyncio.gather(first, second)

    assert results[0] is not None
    assert results[1] is None
    async with factory() as session:
        assert await session.scalar(select(func.count(AuthToken.token_hash))) == 0


async def test_a_link_presented_for_another_purpose_is_refused_and_kept(env):
    """A wrong-purpose presentation spends nothing: the right one still works."""
    from app.auth.tokens import consume_token

    new_client, factory = env
    http = new_client()
    await register(http, "Purposeful", email="purposeful@example.com")
    await verify_via_email(http, factory)
    await http.post("/api/auth/password/forgot", json={"identifier": "Purposeful"})
    token = token_in(await drain(factory))

    async with factory() as session:
        async with session.begin():
            assert (
                await consume_token(
                    session, token=token, purpose=AuthTokenPurpose.EMAIL_VERIFY
                )
                is None
            )
    check = await http.post("/api/auth/password/reset/check", json={"token": token})
    assert check.json()["valid"] is True


async def test_a_failure_before_commit_leaves_the_password_the_link_and_the_devices(
    env, monkeypatch
):
    """R-AUTH-10 is one transaction: a crash between the new password and the
    revocation must leave both undone, so the same link works on retry and
    the other device is only out once the password is really changed."""
    import app.auth.recovery as recovery

    new_client, factory = env
    laptop, phone = new_client(), new_client()
    account = await register(laptop, "Fragile", email="fragile@example.com")
    await verify_via_email(laptop, factory)
    assert (
        await phone.post(
            "/api/auth/login", json={"username": "Fragile", "password": PASSWORD}
        )
    ).status_code == 200
    await laptop.post("/api/auth/password/forgot", json={"identifier": "Fragile"})
    token = token_in(await drain(factory))

    async def crash(session, **_):
        raise RuntimeError("crashed between the password and the revocation")

    monkeypatch.setattr(recovery, "revoke_sessions", crash)
    with pytest.raises(RuntimeError):
        await recovery.reset_password(factory, token=token, password_hash="new-hash")
    monkeypatch.undo()

    # Nothing moved: the phone is still in, the old password still works, and
    # the link was not spent by a transaction that did not commit.
    assert (await phone.get("/api/auth/me")).json()["id"] == account["id"]
    assert (
        await new_client().post(
            "/api/auth/login", json={"username": "Fragile", "password": PASSWORD}
        )
    ).status_code == 200
    check = await laptop.post("/api/auth/password/reset/check", json={"token": token})
    assert check.json()["valid"] is True

    retry = await laptop.post(
        "/api/auth/password/reset", json={"token": token, "password": NEW_PASSWORD}
    )
    assert retry.status_code == 200
    assert (await phone.get("/api/auth/me")).json() is None


async def test_a_failed_password_change_leaves_every_device_signed_in(env, monkeypatch):
    """R-AUTH-17 ends the way a reset does, and fails the way a reset does."""
    import app.auth.recovery as recovery

    new_client, factory = env
    laptop, phone = new_client(), new_client()
    account = await register(laptop, "Changing")
    assert (
        await phone.post(
            "/api/auth/login", json={"username": "Changing", "password": PASSWORD}
        )
    ).status_code == 200

    async def crash(session, **_):
        raise RuntimeError("crashed between the password and the revocation")

    monkeypatch.setattr(recovery, "revoke_sessions", crash)
    with pytest.raises(RuntimeError):
        await recovery.change_password(
            factory, user_id=UUID(account["id"]), password_hash="new-hash"
        )
    monkeypatch.undo()

    assert (await phone.get("/api/auth/me")).json()["id"] == account["id"]
    assert (
        await new_client().post(
            "/api/auth/login", json={"username": "Changing", "password": PASSWORD}
        )
    ).status_code == 200
    async with factory() as session:
        assert (
            await session.scalar(
                select(func.count(AuditEvent.id)).where(
                    AuditEvent.event_type == "account.password_changed"
                )
            )
            == 0
        )


async def test_a_failed_operator_reset_changes_nothing(env, monkeypatch):
    import app.auth.password_reset as operator

    new_client, factory = env
    laptop, phone = new_client(), new_client()
    account = await register(laptop, "Stranded2")
    assert (
        await phone.post(
            "/api/auth/login", json={"username": "Stranded2", "password": PASSWORD}
        )
    ).status_code == 200

    async def crash(session, **_):
        raise RuntimeError("crashed between the password and the revocation")

    monkeypatch.setattr(operator, "revoke_sessions", crash)
    with pytest.raises(RuntimeError):
        await operator.reset_password_as_operator(
            factory, username="stranded2", password=NEW_PASSWORD, reason="asked"
        )
    monkeypatch.undo()

    assert (await phone.get("/api/auth/me")).json()["id"] == account["id"]
    assert (
        await new_client().post(
            "/api/auth/login", json={"username": "Stranded2", "password": PASSWORD}
        )
    ).status_code == 200

    result = await operator.reset_password_as_operator(
        factory, username="stranded2", password=NEW_PASSWORD, reason="asked"
    )
    assert result.sessions_revoked >= 1
    assert (await phone.get("/api/auth/me")).json() is None


@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="proves row locking, which SQLite's single test connection cannot",
)
async def test_a_reset_and_a_change_racing_for_one_account_apply_in_turn(
    env, monkeypatch
):
    """Both lock the account row, so they serialise: the change waits for the
    reset to commit, then wins the password, and each revokes what stood
    before it. Two writers on SQLite's one shared connection interleave inside
    one transaction instead, so this is a PostgreSQL-only proof."""
    import asyncio

    import app.auth.recovery as recovery

    new_client, factory = env
    laptop, phone = new_client(), new_client()
    account = await register(laptop, "Racer", email="racer@example.com")
    await verify_via_email(laptop, factory)
    assert (
        await phone.post(
            "/api/auth/login", json={"username": "Racer", "password": PASSWORD}
        )
    ).status_code == 200
    await laptop.post("/api/auth/password/forgot", json={"identifier": "Racer"})
    token = token_in(await drain(factory))

    real_revoke = recovery.revoke_sessions
    reset_is_holding_the_row = asyncio.Event()
    let_the_reset_commit = asyncio.Event()
    calls: list[str] = []

    async def paused(session, *, user_id, now=None, **options):
        calls.append("revoke")
        if len(calls) == 1:
            reset_is_holding_the_row.set()
            await let_the_reset_commit.wait()
        return await real_revoke(session, user_id=user_id, now=now, **options)

    monkeypatch.setattr(recovery, "revoke_sessions", paused)
    reset = asyncio.create_task(
        recovery.reset_password(factory, token=token, password_hash="from-the-reset")
    )
    await reset_is_holding_the_row.wait()
    change = asyncio.create_task(
        recovery.change_password(
            factory, user_id=UUID(account["id"]), password_hash="from-the-change"
        )
    )
    await asyncio.sleep(0.2)
    assert not change.done(), "the change must wait for the reset's row lock"
    let_the_reset_commit.set()
    reset_user, changed = await asyncio.gather(reset, change)

    assert reset_user.user_id == UUID(account["id"]) and changed is True
    async with factory() as session:
        user = await session.get(User, UUID(account["id"]))
        assert user.password_hash == "from-the-change"
        live = await session.scalar(
            select(func.count(AuthSession.id)).where(
                AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None)
            )
        )
        assert live == 0


async def test_resetting_with_a_token_that_is_no_longer_usable_changes_nothing(env):
    """The route now refuses a link that names nobody before it hashes (#975
    review), so the consuming path is proved here instead: it is the one that
    decides under its own lock, and it must answer nothing rather than reset
    somebody."""
    from app.auth.recovery import reset_password

    _, factory = env
    assert (
        await reset_password(
            factory,
            token="not-a-real-token",
            password_hash="argon2-hash",
        )
        is None
    )


async def test_an_expired_or_spent_reset_token_is_refused_where_it_is_consumed(env):
    """The route refuses a link that names nobody before hashing (#975
    review), so these two are proved at the layer that decides: a token that
    is past its life, and one already spent."""
    from app.auth.tokens import consume_token, hash_token, token_is_usable
    from app.domain_values import AuthTokenPurpose as TokenPurpose
    from app.db.models import AuthToken, User, generate_uuid

    _, factory = env
    now = datetime.now(timezone.utc)
    account = generate_uuid()
    async with factory() as session:
        async with session.begin():
            session.add(User(id=account, display_name="Expired"))
            await session.flush()
            session.add_all([
                AuthToken(
                    token_hash=hash_token("expired-token"),
                    purpose=TokenPurpose.PASSWORD_RESET.value,
                    user_id=account,
                    expires_at=now - timedelta(hours=1),
                ),
                AuthToken(
                    token_hash=hash_token("spent-token"),
                    purpose=TokenPurpose.PASSWORD_RESET.value,
                    user_id=account,
                    expires_at=now + timedelta(hours=1),
                    consumed_at=now - timedelta(minutes=1),
                ),
            ])
    async with factory() as session:
        assert await token_is_usable(
            session, token="expired-token", purpose=TokenPurpose.PASSWORD_RESET
        ) is False
        assert await token_is_usable(
            session, token="spent-token", purpose=TokenPurpose.PASSWORD_RESET
        ) is False
        # Consuming takes the row either way, and answers nothing.
        assert await consume_token(
            session, token="expired-token", purpose=TokenPurpose.PASSWORD_RESET
        ) is None
        assert await consume_token(
            session, token="spent-token", purpose=TokenPurpose.PASSWORD_RESET
        ) is None


# --- the recovery address is a credential, and is set like one (#997) --------


async def test_setting_the_address_proves_the_password(env):
    """With a cookie alone, a thief pointed recovery at a mailbox of their
    own, confirmed it, and reset the owner out of the account."""
    new_client, factory = env
    browser = new_client()
    await register(browser, "Careful")

    unproved = await browser.put("/api/auth/email", json={"email": "me@example.com"})
    assert unproved.status_code == 422
    wrong = await browser.put(
        "/api/auth/email", json={"email": "me@example.com", "password": "not-it"}
    )
    assert wrong.status_code == 401
    assert (await drain(factory)).sent == [], "nothing was mailed for a refused ask"

    right = await browser.put(
        "/api/auth/email", json={"email": "me@example.com", "password": PASSWORD}
    )
    assert right.status_code == 200, right.text


async def test_a_staff_account_sets_its_address_only_after_stepping_up(env):
    from app.db.models import User
    from tests.staffauth import mark_staff_ready

    new_client, factory = env
    browser = new_client()
    account = await register(browser, "Moderating")
    async with factory() as session:
        async with session.begin():
            (await session.get(User, UUID(account["id"]))).role = "moderator"

    body = {"email": "mod@example.com", "password": PASSWORD}
    not_yet = await browser.put("/api/auth/email", json=body)
    assert not_yet.status_code == 403
    assert not_yet.headers.get("X-Sketchy-Step-Up") == "required"

    await mark_staff_ready(factory, account["id"])
    assert (await browser.put("/api/auth/email", json=body)).status_code == 200


async def test_a_new_password_retires_a_verification_still_in_the_post(env):
    """A link asked for before the password changed was still good for a day,
    and confirming it needs no session: the thief the change evicted could
    still point recovery at their mailbox afterwards."""
    new_client, factory = env
    browser, thief = new_client(), new_client()
    await register(browser, "Evicting")
    assert (
        await browser.put(
            "/api/auth/email", json={"email": "thief@example.com", "password": PASSWORD}
        )
    ).status_code == 200
    queued = token_in(await drain(factory))

    changed = await browser.post(
        "/api/auth/password/change",
        json={"currentPassword": PASSWORD, "password": NEW_PASSWORD},
    )
    assert changed.status_code == 200, changed.text

    late = await thief.post("/api/auth/email/verify", json={"token": queued})
    assert late.status_code == 400
    assert (await browser.get("/api/auth/email")).json()["address"] is None


async def test_a_reset_retires_a_verification_still_in_the_post(env):
    new_client, factory = env
    browser, thief = new_client(), new_client()
    await register(browser, "Resetting", email="resetting@example.com")
    await verify_via_email(browser, factory)
    assert (
        await browser.put(
            "/api/auth/email", json={"email": "thief@example.com", "password": PASSWORD}
        )
    ).status_code == 200
    queued = token_in(await drain(factory))

    await new_client().post("/api/auth/password/forgot", json={"identifier": "Resetting"})
    reset = await browser.post(
        "/api/auth/password/reset",
        json={"token": token_in(await drain(factory)), "password": NEW_PASSWORD},
    )
    assert reset.status_code == 200, reset.text

    late = await thief.post("/api/auth/email/verify", json={"token": queued})
    assert late.status_code == 400
    assert (await browser.get("/api/auth/email")).json()["address"] == "resetting@example.com"


async def test_deleting_the_account_is_a_throttled_password_proof(env):
    """The one password proof on the account surface with no bucket: a stolen
    cookie could guess at Argon2 speed, and a right guess deleted the account."""
    new_client, _factory = env
    browser = new_client()
    await register(browser, "Guessed")
    answers = []
    for _ in range(11):
        response = await browser.request(
            "DELETE", "/api/auth/account", json={"password": "not-it"}
        )
        answers.append(response.status_code)
    assert answers[:10] == [401] * 10
    assert answers[10] == 429


async def test_a_guest_is_told_to_create_an_account_not_that_a_password_is_wrong(env):
    new_client, _factory = env
    guest = new_client()
    assert (await guest.post("/api/auth/display-name", json={"displayName": "Drifter"})).status_code == 200
    refused = await guest.put("/api/auth/email", json={"email": "d@example.com", "password": "anything"})
    assert refused.status_code == 403


async def test_a_staff_reset_sets_the_password_but_signs_nobody_in(env):
    """A reset proves the mailbox; a staff sign-in needs the code as well
    (R-AUTH-20). The session the reset used to issue was a moderator signed
    in without one, holding a password that could replace the
    authenticator - the second factor reduced to mailbox control (#996)."""
    from app.db.models import User
    from tests.staffauth import mark_staff_ready

    new_client, factory = env
    browser = new_client()
    account = await register(browser, "Moderating", email="moderating@example.com")
    await verify_via_email(browser, factory)
    async with factory() as session:
        async with session.begin():
            user = await session.get(User, UUID(account["id"]))
            user.role = "moderator"
    await mark_staff_ready(factory, account["id"])

    await new_client().post("/api/auth/password/forgot", json={"identifier": "Moderating"})
    transport = await drain(factory)
    reset = await browser.post(
        "/api/auth/password/reset",
        json={"token": token_in(transport), "password": NEW_PASSWORD},
    )

    assert reset.status_code == 200, reset.text
    assert reset.json() == {"ok": True, "signedIn": False, "reason": "second_factor"}
    assert (await browser.get("/api/auth/me")).json() is None
    # The password took, and the front door still wants the code.
    login = await new_client().post(
        "/api/auth/login", json={"username": "Moderating", "password": NEW_PASSWORD}
    )
    assert login.status_code == 401
    assert login.headers.get("X-Sketchy-Second-Factor") == "required"
    async with factory() as session:
        live = await session.scalar(
            select(func.count(AuthSession.id)).where(
                AuthSession.user_id == UUID(account["id"]),
                AuthSession.revoked_at.is_(None),
            )
        )
    assert live == 0


async def test_a_mail_reset_ends_a_suspended_accounts_escape_hatch(env):
    """#1082: the ban's own revocation keeps the ban-time session for export
    (R-BAN-04); the owner's reset is what ends it, so a copied cookie cannot
    keep exporting after the owner has taken the account back."""
    from datetime import datetime, timezone

    from app.auth.sessions import revoke_all_sessions
    from app.db.models import UserBan, generate_uuid

    new_client, factory = env
    browser = new_client()
    account = await register(browser, "HatchMail", email="hatchmail@example.com")
    await verify_via_email(browser, factory)
    banned_at = datetime.now(timezone.utc)
    async with factory() as session:
        async with session.begin():
            session.add(
                UserBan(
                    id=generate_uuid(),
                    user_id=UUID(account["id"]),
                    reason="Suspended for the test",
                    created_at=banned_at,
                )
            )
    await revoke_all_sessions(factory, user_id=account["id"], now=banned_at)
    assert (await browser.get("/api/auth/data-exports")).status_code == 200

    await new_client().post("/api/auth/password/forgot", json={"identifier": "HatchMail"})
    reset = await new_client().post(
        "/api/auth/password/reset",
        json={"token": token_in(await drain(factory)), "password": NEW_PASSWORD},
    )
    assert reset.status_code == 200, reset.text
    assert (await browser.get("/api/auth/data-exports")).status_code == 401


async def test_a_suspended_reset_sets_the_password_but_signs_nobody_in(env):
    """Login and the passkey both refuse a suspended account at the door; the
    reset issued a cookie without asking (#1052). The password still takes -
    the mailbox was proved - and signing in with it is what says why."""
    from app.db.models import UserBan, generate_uuid

    new_client, factory = env
    browser = new_client()
    account = await register(browser, "Suspended", email="suspended@example.com")
    await verify_via_email(browser, factory)
    async with factory() as session:
        async with session.begin():
            session.add(
                UserBan(
                    id=generate_uuid(),
                    user_id=UUID(account["id"]),
                    reason="Suspended for the test",
                )
            )

    await new_client().post("/api/auth/password/forgot", json={"identifier": "Suspended"})
    stranger = new_client()
    reset = await stranger.post(
        "/api/auth/password/reset",
        json={"token": token_in(await drain(factory)), "password": NEW_PASSWORD},
    )

    assert reset.status_code == 200, reset.text
    assert reset.json() == {"ok": True, "signedIn": False, "reason": "suspended"}
    assert (await stranger.get("/api/auth/me")).json() is None
    async with factory() as session:
        live = await session.scalar(
            select(func.count(AuthSession.id)).where(
                AuthSession.user_id == UUID(account["id"]),
                AuthSession.revoked_at.is_(None),
            )
        )
    # No session at all, so nothing for R-BAN-04's escape hatch to ride on:
    # that stays with the session held when the ban landed.
    assert live == 0
    login = await new_client().post(
        "/api/auth/login", json={"username": "Suspended", "password": NEW_PASSWORD}
    )
    assert login.status_code == 403
    assert login.json()["detail"] == "This account is suspended."


async def test_a_suspended_moderators_reset_says_suspended_not_second_factor(env):
    """The suspension is what stands between them and signing in, so that is
    what the page says; the second-factor path would only refuse them."""
    from app.db.models import User, UserBan, generate_uuid
    from tests.staffauth import mark_staff_ready

    new_client, factory = env
    browser = new_client()
    account = await register(browser, "SuspendedMod", email="suspendedmod@example.com")
    await verify_via_email(browser, factory)
    async with factory() as session:
        async with session.begin():
            user = await session.get(User, UUID(account["id"]))
            user.role = "moderator"
            session.add(
                UserBan(id=generate_uuid(), user_id=UUID(account["id"]), reason="Test")
            )
    await mark_staff_ready(factory, account["id"])

    await new_client().post("/api/auth/password/forgot", json={"identifier": "SuspendedMod"})
    reset = await new_client().post(
        "/api/auth/password/reset",
        json={"token": token_in(await drain(factory)), "password": NEW_PASSWORD},
    )
    assert reset.status_code == 200, reset.text
    assert reset.json() == {"ok": True, "signedIn": False, "reason": "suspended"}
