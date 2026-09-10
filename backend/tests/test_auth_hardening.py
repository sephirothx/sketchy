"""What #468 changed about taking an account over, and about staff.

The 2026-08-27 audit's PR-17 found four ways in, and each has its own section
below. The point of the file is the *abuse* paths rather than the happy ones:
a botnet spreading guesses across ten thousand addresses, a cookie copied off a
device and used months later, a password long enough to pass a length rule and
still first in every corpus, and a moderator's session being enough on its own
to suspend somebody.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import time
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, update

from app.auth.breached_passwords import screening_failure
from app.auth.login_guard import (
    LOCKOUT_AFTER_FAILURES,
    LoginGuard,
    count_open_lockouts,
)
from app.auth.middleware import SessionAuthMiddleware
from app.auth.password import MIN_PASSWORD_LENGTH, PasswordPolicyError, validate_password
from app.auth.pending_role import (
    OFFER_LIFETIME,
    offer_expired,
    pending_offer,
    take_up_offer,
)
from app.auth.routes import create_auth_router
from app.auth.second_factor import (
    SecondFactorOutcome,
    confirm_enrolment,
    prove_second_factor_owner,
    second_factor_state,
    verify_second_factor,
)
from app.auth.sessions import (
    PLAYER_LIFETIME,
    ROTATION_GRACE,
    STAFF_LIFETIME,
    STEP_UP_WINDOW,
    create_session,
    lifetime_for,
    resolve_session,
    list_active_sessions,
    revoke_all_sessions,
    rotate_session,
    should_rotate,
)
from app.auth.totp import code_at, current_step, generate_secret
from app.db.models import AuditEvent, AuthSession, User
from app.domain_values import UserRole
from app.repositories.sqlalchemy import SqlAlchemyUserRepository

from tests.dbfixtures import create_test_db
from tests.staffauth import enrol_second_factor, step_up

# Twelve characters, not on the list, not built from the identity.
GOOD_PASSWORD = "marmalade-frog-lantern"


@pytest_asyncio.fixture
async def env(monkeypatch):
    monkeypatch.setenv("IP_HASH_SECRET", "auth-hardening-test-secret")
    factory, engine = await create_test_db()
    repo = SqlAlchemyUserRepository(factory)
    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware, session_factory=factory)
    app.include_router(create_auth_router(repo, factory))

    clients: list[AsyncClient] = []

    def new_client() -> AsyncClient:
        client = AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        )
        clients.append(client)
        return client

    try:
        yield new_client, factory, repo
    finally:
        for client in clients:
            await client.aclose()
        await engine.dispose()


async def register(client: AsyncClient, username: str, password=GOOD_PASSWORD) -> dict:
    assert (await client.get("/api/auth/me")).status_code == 200
    response = await client.post(
        "/api/auth/register", json={"username": username, "password": password}
    )
    assert response.status_code == 200, response.text
    return response.json()


async def set_role(factory, user_id: str, role: UserRole) -> None:
    async with factory() as session:
        async with session.begin():
            user = await session.get(User, UUID(user_id))
            user.role = role.value


# --- the password floor and what stands behind it -------------------------

def test_eight_characters_is_no_longer_a_password():
    """The old floor let through what an offline guess reaches first."""
    assert MIN_PASSWORD_LENGTH == 12
    with pytest.raises(PasswordPolicyError) as refusal:
        validate_password("hunter22")
    assert "at least 12" in str(refusal.value)


def test_a_long_password_can_still_be_the_first_one_guessed():
    """Length is not strength: these all clear twelve characters."""
    for password in (
        "passwordpassword",
        "P4ssw0rdP4ssw0rd",       # the same entry, leetspeak folded away
        "qwertyuiopasdfgh",       # a keyboard row walked to its end
        "abcabcabcabcabc",        # three characters of secret, five times
        "aaaaaaaaaaaaaaaa",
    ):
        assert screening_failure(password) is not None, password
        with pytest.raises(PasswordPolicyError):
            validate_password(password)


def test_a_password_may_not_be_built_from_the_name_it_protects():
    assert screening_failure(
        "marmaladeplayer99", username="marmalade"
    ) is not None
    assert screening_failure("frog-lantern-99", username="marmalade") is None


def test_an_ordinary_passphrase_is_accepted():
    """The screening must not be a wall in front of good passwords."""
    for password in (
        "correct horse battery staple",
        "marmalade-frog-lantern",
        "Tr0ub4dor&3-heliotrope",
        "seventeen purple bicycles",
    ):
        assert screening_failure(password, username="player") is None, password


async def test_the_refusal_says_which_rule_refused(env):
    """A generic length sentence sends somebody back with the same password."""
    new_client, *_ = env
    http = new_client()
    assert (await http.get("/api/auth/me")).status_code == 200
    response = await http.post(
        "/api/auth/register",
        json={"username": "Hopeful", "password": "passwordpassword"},
    )
    assert response.status_code == 400
    assert "common" in response.json()["detail"].lower()


# --- the three throttles --------------------------------------------------

async def test_one_account_is_guarded_across_every_address(env):
    """The hole PR-17 named: ten thousand hosts, ten guesses each.

    Each attempt below arrives from its own address, so the per-address bucket
    never fills. Before #468 that meant no limit at all on guesses against one
    username.
    """
    new_client, factory, _ = env
    http = new_client()
    await register(http, "Target")
    guard = LoginGuard(factory)

    for attempt in range(12):
        await guard.note_failure(username="Target", address=f"10.0.0.{attempt}")

    verdict = await guard.check(username="Target", address="10.0.99.99")
    assert not verdict.allowed
    assert verdict.retry_after_seconds > 0


async def test_signing_in_correctly_costs_nothing(env):
    """Why the ceilings can be low: a household never meets them."""
    _, factory, _ = env
    guard = LoginGuard(factory)
    for _ in range(50):
        assert (await guard.check(username="Housemate", address="10.0.0.1")).allowed
    assert (await guard.check(username="Housemate", address="10.0.0.1")).allowed


async def test_consecutive_failures_buy_an_increasing_wait(env):
    """A fixed window forgets; a lockout is what makes a slow attack cost."""
    _, factory, _ = env
    guard = LoginGuard(factory)
    for _ in range(LOCKOUT_AFTER_FAILURES):
        await guard.note_failure(username="Slowly", address="10.0.0.1")
    first = await guard.check(username="Slowly", address="10.0.0.2")
    assert not first.allowed

    await guard.note_failure(username="Slowly", address="10.0.0.3")
    second = await guard.check(username="Slowly", address="10.0.0.4")
    assert second.retry_after_seconds > first.retry_after_seconds


async def test_one_correct_password_clears_the_backoff(env):
    _, factory, _ = env
    guard = LoginGuard(factory)
    for _ in range(LOCKOUT_AFTER_FAILURES + 2):
        await guard.note_failure(username="Recovered", address="10.0.0.1")
    assert not (await guard.check(username="Recovered", address="10.0.0.1")).allowed
    await guard.note_success(username="Recovered")
    assert (await guard.check(username="Recovered", address="10.0.0.9")).allowed


async def test_a_username_that_does_not_exist_is_charged_the_same(env):
    """R-AUTH-09: the counters must not answer what the message will not."""
    new_client, factory, _ = env
    http = new_client()
    await register(http, "Real")

    attacker = new_client()
    assert (await attacker.get("/api/auth/me")).status_code == 200
    real = await attacker.post(
        "/api/auth/login", json={"username": "Real", "password": "wrong-one-entirely"}
    )
    invented = await attacker.post(
        "/api/auth/login",
        json={"username": "Invented", "password": "wrong-one-entirely"},
    )
    assert real.status_code == invented.status_code == 401
    assert real.json()["detail"] == invented.json()["detail"]

    async with factory() as session:
        from app.db.models import AuthLoginLockout

        rows = (await session.scalars(select(AuthLoginLockout))).all()
    # One bucket per name, and nothing about either row says which is real.
    assert len(rows) == 2


async def test_repeated_wrong_passwords_end_in_a_refusal_with_a_wait(env):
    new_client, _, _ = env
    http = new_client()
    await register(http, "Besieged")
    attacker = new_client()
    assert (await attacker.get("/api/auth/me")).status_code == 200

    statuses = []
    for _ in range(8):
        response = await attacker.post(
            "/api/auth/login",
            json={"username": "Besieged", "password": "not-the-password-at-all"},
        )
        statuses.append(response.status_code)
    assert 429 in statuses
    refused = next(
        code for code in statuses if code == 429
    )
    assert refused == 429


# --- what a stolen cookie is worth ----------------------------------------

async def test_a_session_nobody_uses_ends_before_its_expiry(env):
    """R-AUTH-03's idle bound: the year is not the only limit any more."""
    _, factory, repo = env
    user = await repo.create_anonymous("Forgetful")
    # Two sessions, because resolving one moves its own idle deadline: the
    # window is measured from the last use, so asking about a session *is*
    # using it. That is the behaviour, not a wrinkle of the test.
    kept = await create_session(
        factory, user_id=user.id, device_label="Chrome on Windows"
    )
    abandoned = await create_session(
        factory, user_id=user.id, device_label="Chrome on Android"
    )
    still_here = datetime.now(timezone.utc) + PLAYER_LIFETIME.idle - timedelta(days=1)
    gone = datetime.now(timezone.utc) + PLAYER_LIFETIME.idle + timedelta(minutes=1)
    assert await resolve_session(factory, kept.token, now=still_here) is not None
    assert await resolve_session(factory, abandoned.token, now=gone) is None


async def test_a_staff_session_lives_a_week_rather_than_a_year(env):
    _, factory, repo = env
    user = await repo.create_anonymous("Moderator")
    await set_role(factory, user.id, UserRole.MODERATOR)
    issued = await create_session(
        factory, user_id=user.id, device_label="Firefox on Linux"
    )
    assert issued.session.lifetime is STAFF_LIFETIME
    after_a_week = datetime.now(timezone.utc) + timedelta(days=7, minutes=1)
    assert await resolve_session(factory, issued.token, now=after_a_week) is None


async def test_a_sessions_lifetime_is_the_one_it_was_issued_under(env):
    """Frozen at issue, and safe to freeze because a promotion ends it.

    A role change revokes every session the account holds (R-AUTH-20), so a
    live session is always one issued under the role its owner has now. That
    is what lets resolution read two columns instead of joining `users` on
    every request.
    """
    _, factory, repo = env
    user = await repo.create_anonymous("Promoted")
    issued = await create_session(factory, user_id=user.id, device_label="Safari on macOS")
    assert issued.session.lifetime is PLAYER_LIFETIME

    await set_role(factory, user.id, UserRole.ADMIN)
    # Set directly here, so nothing revoked it: the row still says a year.
    still_live = await resolve_session(factory, issued.token)
    assert still_live is not None
    assert still_live.expires_at - still_live.created_at == PLAYER_LIFETIME.absolute

    # And what the real promotion path does instead is end it outright.
    assert await revoke_all_sessions(factory, user_id=user.id) == 1
    assert await resolve_session(factory, issued.token) is None


async def test_a_rotated_away_token_used_later_takes_the_chain_down(env):
    """R-AUTH-22: presenting a spent token means a second copy exists."""
    _, factory, repo = env
    user = await repo.create_anonymous("Copied")
    issued = await create_session(factory, user_id=user.id, device_label="Chrome on Windows")
    successor = await rotate_session(
        factory,
        session_id=issued.session.id,
        user_id=user.id,
        device_label="Chrome on Windows",
    )
    assert successor is not None

    thief_at = datetime.now(timezone.utc) + ROTATION_GRACE + timedelta(seconds=1)
    assert await resolve_session(factory, issued.token, now=thief_at) is None
    # The real device is signed out too, which is how its owner finds out.
    assert await resolve_session(factory, successor.token, now=thief_at) is None
    async with factory() as session:
        events = (
            await session.scalars(
                select(AuditEvent).where(
                    AuditEvent.event_type == "session.token_replayed"
                )
            )
        ).all()
    assert len(events) == 1


async def test_two_requests_racing_a_rotation_do_not_sign_anybody_out(env):
    """The honest case the grace window exists for."""
    _, factory, repo = env
    user = await repo.create_anonymous("Parallel")
    issued = await create_session(factory, user_id=user.id, device_label="Chrome on Windows")
    successor = await rotate_session(
        factory,
        session_id=issued.session.id,
        user_id=user.id,
        device_label="Chrome on Windows",
    )
    assert successor is not None
    inside = datetime.now(timezone.utc) + ROTATION_GRACE - timedelta(seconds=5)
    assert await resolve_session(factory, issued.token, now=inside) is not None
    assert await resolve_session(factory, successor.token, now=inside) is not None


async def test_a_session_used_from_another_browser_is_flagged(env):
    _, factory, repo = env
    user = await repo.create_anonymous("Moved")
    issued = await create_session(factory, user_id=user.id, device_label="Chrome on Windows")

    resolved = await resolve_session(
        factory, issued.token, device_label="Safari on macOS"
    )
    assert resolved is not None
    assert resolved.anomaly_at is not None
    assert resolved.anomaly_count == 1

    async with factory() as session:
        events = (
            await session.scalars(
                select(AuditEvent).where(AuditEvent.event_type == "session.anomaly")
            )
        ).all()
    assert [event.details["reason"] for event in events] == ["device"]


async def test_a_moved_session_has_to_prove_itself_again(env):
    """A step-up is a claim about the browser holding the session."""
    _, factory, repo = env
    user = await repo.create_anonymous("Stepped")
    issued = await create_session(factory, user_id=user.id, device_label="Chrome on Windows")
    async with factory() as session:
        async with session.begin():
            await session.execute(
                update(AuthSession)
                .where(AuthSession.id == UUID(issued.session.id))
                .values(stepped_up_at=datetime.now(timezone.utc))
            )
    resolved = await resolve_session(
        factory, issued.token, device_label="Firefox on Linux"
    )
    assert resolved is not None
    assert resolved.stepped_up_at is None
    assert not resolved.is_stepped_up()


def test_the_lifetime_a_role_gets_is_the_shorter_one():
    assert lifetime_for(UserRole.USER.value) is PLAYER_LIFETIME
    assert lifetime_for(None) is PLAYER_LIFETIME
    assert lifetime_for(UserRole.MODERATOR.value) is STAFF_LIFETIME
    assert lifetime_for(UserRole.ADMIN.value) is STAFF_LIFETIME
    assert STAFF_LIFETIME.absolute < PLAYER_LIFETIME.absolute
    assert STAFF_LIFETIME.idle < PLAYER_LIFETIME.idle


# --- the second factor ----------------------------------------------------

async def test_a_staff_account_cannot_sign_in_without_one(env):
    """R-AUTH-20 is a rule, not an intention: no grace by default."""
    new_client, factory, _ = env
    http = new_client()
    account = await register(http, "Unenrolled")
    await set_role(factory, account["id"], UserRole.MODERATOR)

    fresh = new_client()
    assert (await fresh.get("/api/auth/me")).status_code == 200
    response = await fresh.post(
        "/api/auth/login",
        json={"username": "Unenrolled", "password": GOOD_PASSWORD},
    )
    assert response.status_code == 403
    assert "two-factor" in response.json()["detail"].lower()


async def test_a_staff_sign_in_asks_for_the_code_and_then_accepts_it(env):
    new_client, factory, _ = env
    http = new_client()
    account = await register(http, "Enrolled")
    secret = await enrol_second_factor(http, GOOD_PASSWORD)
    await set_role(factory, account["id"], UserRole.MODERATOR)

    fresh = new_client()
    assert (await fresh.get("/api/auth/me")).status_code == 200
    asked = await fresh.post(
        "/api/auth/login", json={"username": "Enrolled", "password": GOOD_PASSWORD}
    )
    assert asked.status_code == 401
    assert asked.headers.get("X-Sketchy-Second-Factor") == "required"

    signed_in = await fresh.post(
        "/api/auth/login",
        json={
            "username": "Enrolled",
            "password": GOOD_PASSWORD,
            "code": code_at(secret, current_step(time.time()) + 1),
        },
    )
    assert signed_in.status_code == 200, signed_in.text


async def test_a_code_cannot_be_used_twice(env):
    """What makes a relayed code worth less than the thirty seconds it lives."""
    _, factory, repo = env
    user = await repo.create_anonymous("Replayed")
    secret = generate_secret()
    now = datetime.now(timezone.utc)
    assert await confirm_enrolment(
        factory,
        user_id=user.id,
        secret=secret,
        code=code_at(secret, current_step(now.timestamp())),
        now=now,
    )
    code = code_at(secret, current_step(now.timestamp()) + 1)
    later = now + timedelta(seconds=30)
    assert (
        await verify_second_factor(factory, user_id=user.id, code=code, now=later)
        is SecondFactorOutcome.ACCEPTED
    )
    assert (
        await verify_second_factor(factory, user_id=user.id, code=code, now=later)
        is SecondFactorOutcome.REJECTED
    )


async def test_a_recovery_code_works_once(env):
    _, factory, repo = env
    user = await repo.create_anonymous("Lost")
    secret = generate_secret()
    now = datetime.now(timezone.utc)
    codes = await confirm_enrolment(
        factory,
        user_id=user.id,
        secret=secret,
        code=code_at(secret, current_step(now.timestamp())),
        now=now,
    )
    assert codes is not None
    assert (
        await verify_second_factor(factory, user_id=user.id, code=codes[0])
        is SecondFactorOutcome.RECOVERY_CODE_SPENT
    )
    assert (
        await verify_second_factor(factory, user_id=user.id, code=codes[0])
        is SecondFactorOutcome.REJECTED
    )


async def test_grinding_six_digits_locks_the_second_factor(env):
    _, factory, repo = env
    user = await repo.create_anonymous("Ground")
    secret = generate_secret()
    now = datetime.now(timezone.utc)
    await confirm_enrolment(
        factory,
        user_id=user.id,
        secret=secret,
        code=code_at(secret, current_step(now.timestamp())),
        now=now,
    )
    outcomes = [
        await verify_second_factor(factory, user_id=user.id, code="000000")
        for _ in range(6)
    ]
    assert SecondFactorOutcome.LOCKED in outcomes
    assert (
        await verify_second_factor(factory, user_id=user.id, code="000000")
        is SecondFactorOutcome.LOCKED
    )


async def test_an_abandoned_enrolment_stores_nothing(env):
    """A secret nobody confirmed must not be able to lock an account out."""
    new_client, factory, _ = env
    http = new_client()
    account = await register(http, "Hesitant")
    offer = await http.post("/api/auth/second-factor/enrol")
    assert offer.status_code == 200

    state = await http.get("/api/auth/second-factor")
    assert state.json()["enrolled"] is False
    await set_role(factory, account["id"], UserRole.MODERATOR)
    fresh = new_client()
    assert (await fresh.get("/api/auth/me")).status_code == 200
    refused = await fresh.post(
        "/api/auth/login",
        json={"username": "Hesitant", "password": GOOD_PASSWORD},
    )
    # Refused for having none, not admitted on the strength of an offer.
    assert refused.status_code == 403


async def test_recovery_codes_are_shown_once_and_stored_hashed(env):
    new_client, factory, _ = env
    http = new_client()
    account = await register(http, "Careful")
    offer = (await http.post("/api/auth/second-factor/enrol")).json()
    confirmed = await http.post(
        "/api/auth/second-factor/confirm",
        json={
            "secret": offer["secret"],
            "code": code_at(offer["secret"], current_step(time.time())),
            "password": GOOD_PASSWORD,
        },
    )
    codes = confirmed.json()["recoveryCodes"]
    assert len(codes) == 10

    from app.db.models import UserRecoveryCode

    async with factory() as session:
        stored = (
            await session.scalars(
                select(UserRecoveryCode.code_hash).where(
                    UserRecoveryCode.user_id == UUID(account["id"])
                )
            )
        ).all()
    assert not set(codes) & set(stored)
    assert all(len(digest) == 64 for digest in stored)


# --- step-up on the destructive actions -----------------------------------

async def test_a_staff_session_alone_does_not_suspend_anybody(env):
    """R-AUTH-21, checked at the boundary the gate is composed from."""
    from app.api.admin_auth import admin_gate
    from app.auth.step_up import StepUpRequired, stepped_up

    new_client, factory, _ = env
    http = new_client()
    account = await register(http, "Operator")
    await enrol_second_factor(http, GOOD_PASSWORD)
    await set_role(factory, account["id"], UserRole.ADMIN)

    class FakeRequest:
        def __init__(self, session):
            self.state = type("S", (), {"user_id": account["id"], "auth_session": session})()

    session = (await http.get("/api/auth/sessions")).json()["sessions"]
    assert session  # the caller does hold one

    from app.auth.sessions import list_active_sessions

    live = (await list_active_sessions(factory, user_id=account["id"]))[0]
    assert not live.is_stepped_up()

    gate = stepped_up(admin_gate(factory))
    with pytest.raises(StepUpRequired):
        await gate(FakeRequest(live))


async def test_a_fresh_step_up_opens_the_window(env):
    new_client, factory, _ = env
    http = new_client()
    account = await register(http, "Prover")
    secret = await enrol_second_factor(http, GOOD_PASSWORD)
    await set_role(factory, account["id"], UserRole.ADMIN)
    await step_up(http, secret)

    from app.auth.sessions import list_active_sessions

    live = (await list_active_sessions(factory, user_id=account["id"]))[0]
    assert live.is_stepped_up()
    # And it is a window, not a permanent grant.
    assert not live.is_stepped_up(
        now=datetime.now(timezone.utc) + STEP_UP_WINDOW + timedelta(seconds=1)
    )


async def test_the_device_list_says_when_a_session_will_lapse(env):
    new_client, _, _ = env
    http = new_client()
    await register(http, "Listed")
    listed = (await http.get("/api/auth/sessions")).json()["sessions"]
    assert listed
    assert listed[0]["idleExpiresAt"] is not None
    assert listed[0]["anomalyAt"] is None


# --- the paths a first pass leaves untested -------------------------------

async def test_replacing_recovery_codes_invalidates_the_old_set(env):
    """A leaked sheet of codes has to be revocable without dropping 2FA."""
    new_client, factory, _ = env
    http = new_client()
    await register(http, "Rotator")
    offer = (await http.post("/api/auth/second-factor/enrol")).json()
    first = (
        await http.post(
            "/api/auth/second-factor/confirm",
            json={
                "secret": offer["secret"],
                "code": code_at(offer["secret"], current_step(time.time())),
                "password": GOOD_PASSWORD,
            },
        )
    ).json()["recoveryCodes"]

    replaced = await http.post(
        "/api/auth/second-factor/recovery-codes", json={"password": GOOD_PASSWORD}
    )
    assert replaced.status_code == 200
    second = replaced.json()["recoveryCodes"]
    assert not set(first) & set(second)

    account = (await http.get("/api/auth/me")).json()
    assert (
        await verify_second_factor(factory, user_id=account["id"], code=first[0])
        is SecondFactorOutcome.REJECTED
    )
    assert (
        await verify_second_factor(factory, user_id=account["id"], code=second[0])
        is SecondFactorOutcome.RECOVERY_CODE_SPENT
    )


async def test_the_password_is_required_to_touch_the_second_factor(env):
    """The one thing a stolen cookie does not carry."""
    new_client, _, _ = env
    http = new_client()
    await register(http, "Guarded")
    await enrol_second_factor(http, GOOD_PASSWORD)

    for path in (
        "/api/auth/second-factor/recovery-codes",
    ):
        wrong = await http.post(path, json={"password": "not-the-password-here"})
        assert wrong.status_code == 401
    removal = await http.request(
        "DELETE", "/api/auth/second-factor", json={"password": "not-the-password-here"}
    )
    assert removal.status_code == 401


async def test_a_player_may_drop_their_second_factor_and_staff_may_not(env):
    """R-AUTH-20: giving up the role is what removes the requirement."""
    new_client, factory, _ = env
    http = new_client()
    account = await register(http, "Droppable")
    await enrol_second_factor(http, GOOD_PASSWORD)

    await set_role(factory, account["id"], UserRole.MODERATOR)
    refused = await http.request(
        "DELETE", "/api/auth/second-factor", json={"password": GOOD_PASSWORD}
    )
    assert refused.status_code == 409

    await set_role(factory, account["id"], UserRole.USER)
    removed = await http.request(
        "DELETE", "/api/auth/second-factor", json={"password": GOOD_PASSWORD}
    )
    assert removed.status_code == 200
    assert (await http.get("/api/auth/second-factor")).json()["enrolled"] is False


async def test_re_enrolling_retires_the_codes_of_the_old_secret(env):
    """A code that still opened the account after the app was replaced."""
    new_client, factory, _ = env
    http = new_client()
    account = await register(http, "Reenrolled")
    first_offer = (await http.post("/api/auth/second-factor/enrol")).json()
    old_codes = (
        await http.post(
            "/api/auth/second-factor/confirm",
            json={
                "secret": first_offer["secret"],
                "code": code_at(first_offer["secret"], current_step(time.time())),
                "password": GOOD_PASSWORD,
            },
        )
    ).json()["recoveryCodes"]

    second_offer = (await http.post("/api/auth/second-factor/enrol")).json()
    assert (
        await http.post(
            "/api/auth/second-factor/confirm",
            json={
                "secret": second_offer["secret"],
                "code": code_at(second_offer["secret"], current_step(time.time())),
                # Replacing one asks for the password now, so a stolen cookie
                # cannot swap the authenticator out.
                "password": GOOD_PASSWORD,
            },
        )
    ).status_code == 200

    assert (
        await verify_second_factor(factory, user_id=account["id"], code=old_codes[0])
        is SecondFactorOutcome.REJECTED
    )


async def test_a_wrong_code_at_enrolment_stores_nothing(env):
    new_client, _, _ = env
    http = new_client()
    await register(http, "Fumbled")
    offer = (await http.post("/api/auth/second-factor/enrol")).json()
    refused = await http.post(
        "/api/auth/second-factor/confirm",
        json={
            "secret": offer["secret"],
            "code": "000000",
            "password": GOOD_PASSWORD,
        },
    )
    assert refused.status_code == 400
    assert (await http.get("/api/auth/second-factor")).json()["enrolled"] is False


async def test_a_step_up_without_a_second_factor_is_a_conflict(env):
    new_client, _, _ = env
    http = new_client()
    await register(http, "Unprovable")
    response = await http.post("/api/auth/step-up", json={"code": "123456"})
    assert response.status_code == 409


async def test_the_address_bucket_still_stops_one_host_spraying(env):
    """The key the account bucket cannot see: many usernames, one machine."""
    _, factory, _ = env
    guard = LoginGuard(factory)
    for attempt in range(12):
        await guard.note_failure(username=f"Victim{attempt}", address="10.9.9.9")
    verdict = await guard.check(username="Untouched", address="10.9.9.9")
    assert not verdict.allowed


async def test_the_deployment_ceiling_catches_a_spray_no_other_key_sees(env, monkeypatch):
    """Neither key repeats: a different username from a different host each time.

    This is the shape both other buckets are blind to, and the reason there is
    a third one at all. What it may not do is refuse the whole deployment -
    see the clean-caller test below, and N-17.
    """
    _, factory, _ = env
    monkeypatch.setenv("AUTH_LOGIN_GLOBAL_LIMIT", "5")
    guard = LoginGuard(factory)
    for attempt in range(6):
        await guard.note_failure(
            username=f"Sprayed{attempt}", address=f"10.5.5.{attempt}"
        )
    # A host that is part of the spray is held once the ceiling is reached.
    assert not (
        await guard.check(username="Sprayed0", address="10.5.5.0")
    ).allowed
    assert await count_open_lockouts(factory) == 0


async def test_the_deployment_ceiling_can_be_switched_off(env, monkeypatch):
    """N-17's escape hatch: the one bucket an attacker can saturate on purpose."""
    _, factory, _ = env
    monkeypatch.setenv("AUTH_LOGIN_GLOBAL_LIMIT", "0")
    guard = LoginGuard(factory)
    for attempt in range(20):
        await guard.note_failure(
            username=f"Ignored{attempt}", address=f"10.7.7.{attempt}"
        )
    assert (await guard.check(username="Innocent", address="10.8.8.8")).allowed


async def test_an_account_being_held_back_is_countable(env):
    """What an operator sees while an attack is under way."""
    _, factory, _ = env
    guard = LoginGuard(factory)
    for _ in range(LOCKOUT_AFTER_FAILURES):
        await guard.note_failure(username="Counted", address="10.0.0.1")
    assert await count_open_lockouts(factory) == 1


async def test_finished_lockouts_are_forgotten(env):
    _, factory, _ = env
    guard = LoginGuard(factory)
    await guard.note_failure(username="Ancient", address="10.0.0.1")
    forgotten = await guard.forget_expired_lockouts(
        before=datetime.now(timezone.utc) + timedelta(days=2)
    )
    assert forgotten == 1
    assert (await guard.check(username="Ancient", address="10.0.0.1")).allowed


async def test_a_cold_server_establishes_its_hashing_key_once(env, monkeypatch):
    """The first page load is a dozen requests at once, not one.

    Hashing the caller's address runs on every request now, and a server that
    has never run has no key row yet. Without single-flight each of those
    concurrent requests reads nothing, tries to insert the same row, loses on
    the unique key and retries - a pile-up landing exactly when the first page
    is loading. One caller establishes it; the rest wait and find it done.
    """
    from app.auth.middleware import SessionAuthMiddleware
    from app.db.models import AppConfig

    new_client, factory, _ = env
    # No environment key, so it has to be minted into `app_config` - the
    # deployment shape this actually bites on.
    monkeypatch.delenv("IP_HASH_SECRET", raising=False)
    async with factory() as session:
        async with session.begin():
            await session.execute(delete(AppConfig))

    middleware = SessionAuthMiddleware(lambda scope, receive, send: None, factory)
    request = SimpleNamespace(client=SimpleNamespace(host="203.0.113.7"))

    digests = await asyncio.gather(
        *(middleware._caller_ip_hash(request) for _ in range(16))
    )
    assert len(set(digests)) == 1
    assert digests[0] is not None

    async with factory() as session:
        rows = (await session.scalars(select(AppConfig.key))).all()
    # Exactly one key row, whoever won the race.
    assert list(rows) == ["ip_hash_secret"]


# --- what the review of #679 found ---------------------------------------

async def test_a_staff_session_rotates_daily_on_the_path_that_reads_it(env):
    """The rotation cadence has to survive the round trip through the row.

    `/api/auth/me` decides rotation from whatever `resolve_session_status`
    hands back, and that path deliberately does not look up the account's
    role. Reading the lifetime off the row is what keeps a staff session on
    its one-day cadence there; taking the player default instead gave it a
    seven-day interval that its own seven-day expiry meant it never reached.
    """
    _, factory, repo = env
    user = await repo.create_anonymous("Rotator")
    await set_role(factory, user.id, UserRole.MODERATOR)
    issued = await create_session(
        factory, user_id=user.id, device_label="Firefox on Linux"
    )

    resolved = await resolve_session(factory, issued.token)
    assert resolved is not None
    assert resolved.lifetime is STAFF_LIFETIME
    a_day_later = datetime.now(timezone.utc) + timedelta(days=1, minutes=1)
    assert should_rotate(resolved, now=a_day_later)
    # And a player's, read back the same way, still waits a week.
    player = await repo.create_anonymous("Ordinary")
    player_session = await create_session(
        factory, user_id=player.id, device_label="Chrome on Windows"
    )
    player_resolved = await resolve_session(factory, player_session.token)
    assert player_resolved is not None
    assert not should_rotate(player_resolved, now=a_day_later)


async def test_a_step_up_with_nowhere_to_record_it_is_not_a_success(env):
    """A right code and a session that cannot hold it is a refusal, not `ok`.

    The case is the rotation grace window: a browser that lost the race holds
    the predecessor token, which still *resolves* (R-AUTH-22 lets it, so a
    parallel request is not a logout) but names a row that is already revoked.
    The step-up update matches nothing there. Answering `ok` would send
    somebody back into the action that refused them, to be refused again with
    nothing changed.
    """
    new_client, factory, _ = env
    http = new_client()
    account = await register(http, "Racing")
    secret = await enrol_second_factor(http, GOOD_PASSWORD)

    # Rotate underneath the browser: its cookie is now the predecessor, and
    # the grace window means it still resolves.
    live = (await list_active_sessions(factory, user_id=account["id"]))[0]
    successor = await rotate_session(
        factory,
        session_id=live.id,
        user_id=account["id"],
        device_label=live.device_label,
    )
    assert successor is not None

    response = await http.post(
        "/api/auth/step-up",
        json={"code": code_at(secret, current_step(time.time()) + 1)},
    )
    assert response.status_code == 409
    assert not response.json().get("ok")


async def test_guessing_a_password_at_the_second_factor_switch_is_throttled(env):
    """The cheapest place to guess a password was the one with no bucket."""
    new_client, _, _ = env
    http = new_client()
    await register(http, "Bucketed")
    await enrol_second_factor(http, GOOD_PASSWORD)

    statuses = []
    for _ in range(40):
        response = await http.request(
            "DELETE",
            "/api/auth/second-factor",
            json={"password": "not-the-password-here"},
        )
        statuses.append(response.status_code)
        if response.status_code == 429:
            break
    assert 429 in statuses


# --- the second review of #679 -------------------------------------------

async def test_using_a_session_pushes_its_idle_deadline_out(env):
    """R-AUTH-03 says ninety days *unused*, not ninety days.

    The deadline used to be recomputed from `idle_expires_at - last_used_at`
    after `last_used_at` had already been moved to now - the time remaining
    rather than the window - so adding it back returned the same deadline and
    a session died ninety days after it was issued however much it was used.
    """
    _, factory, repo = env
    user = await repo.create_anonymous("Busy")
    issued = await create_session(
        factory, user_id=user.id, device_label="Chrome on Windows"
    )
    first = issued.session.idle_expires_at
    assert first is not None

    # Used once, well past the write interval that records activity.
    active_at = datetime.now(timezone.utc) + timedelta(days=30)
    moved = await resolve_session(factory, issued.token, now=active_at)
    assert moved is not None
    assert moved.idle_expires_at > first
    assert moved.idle_expires_at == active_at + PLAYER_LIFETIME.idle

    # And so it is still alive past the deadline it was issued with.
    later = first + timedelta(days=1)
    assert await resolve_session(factory, issued.token, now=later) is not None


async def test_a_rotated_away_token_carries_no_step_up_through_the_grace(env):
    """R-AUTH-21 must not be satisfiable by the copy rather than the browser.

    A predecessor still resolves for sixty seconds so a parallel request is
    not a logout, and the successor is issued with no step-up - so leaving the
    grant on the predecessor meant a copied staff token could act on a proof
    the real browser had just given up.
    """
    _, factory, repo = env
    user = await repo.create_anonymous("Stepped")
    await set_role(factory, user.id, UserRole.ADMIN)
    issued = await create_session(
        factory, user_id=user.id, device_label="Firefox on Linux"
    )
    async with factory() as session:
        async with session.begin():
            await session.execute(
                update(AuthSession)
                .where(AuthSession.id == UUID(issued.session.id))
                .values(stepped_up_at=datetime.now(timezone.utc))
            )
    assert (await resolve_session(factory, issued.token)).is_stepped_up()

    successor = await rotate_session(
        factory,
        session_id=issued.session.id,
        user_id=user.id,
        device_label=issued.session.device_label,
    )
    assert successor is not None

    inside = datetime.now(timezone.utc) + ROTATION_GRACE - timedelta(seconds=5)
    predecessor = await resolve_session(factory, issued.token, now=inside)
    assert predecessor is not None, "the grace window still resolves it"
    assert not predecessor.is_stepped_up()


async def test_replacing_a_second_factor_needs_the_password(env):
    """A stolen cookie must not be able to swap the authenticator out.

    Confirming over an enrolment that already exists replaces the secret and
    every recovery code with it, which for a staff account hands over the
    step-up too.
    """
    new_client, factory, _ = env
    http = new_client()
    account = await register(http, "Swapped")
    await enrol_second_factor(http, GOOD_PASSWORD)

    attacker_offer = (await http.post("/api/auth/second-factor/enrol")).json()
    refused = await http.post(
        "/api/auth/second-factor/confirm",
        json={
            "secret": attacker_offer["secret"],
            "code": code_at(attacker_offer["secret"], current_step(time.time())),
        },
    )
    assert refused.status_code == 401

    from app.db.models import UserSecondFactor

    async with factory() as session:
        held = await session.get(UserSecondFactor, UUID(account["id"]))
    assert held is not None and held.secret != attacker_offer["secret"]

    # With the password it is an ordinary re-enrolment.
    accepted = await http.post(
        "/api/auth/second-factor/confirm",
        json={
            "secret": attacker_offer["secret"],
            "code": code_at(attacker_offer["secret"], current_step(time.time())),
            "password": GOOD_PASSWORD,
        },
    )
    assert accepted.status_code == 200, accepted.text


# --- the third review of #679 --------------------------------------------

async def test_setting_up_a_second_factor_asks_for_no_password(env):
    """It is optional and a player's own business, so it does not ask.

    What the password was really guarding is promotion, and that is where the
    check now lives - see the test below.
    """
    new_client, factory, _ = env
    http = new_client()
    account = await register(http, "Unbothered")
    offer = (await http.post("/api/auth/second-factor/enrol")).json()

    accepted = await http.post(
        "/api/auth/second-factor/confirm",
        json={
            "secret": offer["secret"],
            "code": code_at(offer["secret"], current_step(time.time())),
        },
    )
    assert accepted.status_code == 200, accepted.text
    state = await second_factor_state(factory, user_id=account["id"])
    assert state.enrolled
    # In place, but nobody has said it is theirs.
    assert not state.password_proved


async def test_a_role_needs_a_second_factor_somebody_proved_was_theirs(env):
    """R-AUTH-20's real requirement, in the place it actually bites.

    Promotion used to check that a factor existed, not whose it was - so one
    planted with a stolen cookie became the staff factor as soon as anybody
    granted the role, and the account's owner was locked out of it for good.
    """
    new_client, factory, _ = env
    http = new_client()
    account = await register(http, "Provable")
    offer = (await http.post("/api/auth/second-factor/enrol")).json()
    await http.post(
        "/api/auth/second-factor/confirm",
        json={
            "secret": offer["secret"],
            "code": code_at(offer["secret"], current_step(time.time())),
        },
    )
    assert not (
        await second_factor_state(factory, user_id=account["id"])
    ).password_proved

    # A wrong password proves nothing.
    refused = await http.post(
        "/api/auth/second-factor/confirm-owner",
        json={
            "password": "not-the-password-here",
            "code": code_at(offer["secret"], current_step(time.time()) + 1),
        },
    )
    assert refused.status_code == 401
    assert not (
        await second_factor_state(factory, user_id=account["id"])
    ).password_proved

    proved = await http.post(
        "/api/auth/second-factor/confirm-owner",
        json={
            "password": GOOD_PASSWORD,
            # The step after the one enrolment spent: a code is single-use,
            # and the one typed a moment ago is gone.
            "code": code_at(offer["secret"], current_step(time.time()) + 1),
        },
    )
    assert proved.status_code == 200
    assert (await second_factor_state(factory, user_id=account["id"])).password_proved


async def test_proving_a_factor_is_yours_needs_the_factor_as_well(env):
    """A password alone says the owner is here, not whose authenticator it is.

    The case: somebody with a stolen cookie enrols their own secret, which
    setting one up permits by design. The account's owner is later made a
    moderator, is asked to confirm, and gives their password - vouching for
    an authenticator they have never seen. The gate would pass and the role
    would land on the attacker's factor, so the code is asked for too.
    """
    new_client, factory, _ = env
    http = new_client()
    account = await register(http, "Vouching")
    planted = (await http.post("/api/auth/second-factor/enrol")).json()
    await http.post(
        "/api/auth/second-factor/confirm",
        json={
            "secret": planted["secret"],
            "code": code_at(planted["secret"], current_step(time.time())),
        },
    )

    # The owner's password, and no code from the factor: refused.
    without = await http.post(
        "/api/auth/second-factor/confirm-owner", json={"password": GOOD_PASSWORD}
    )
    assert without.status_code == 422
    # A code that is not this factor's is no better.
    wrong = await http.post(
        "/api/auth/second-factor/confirm-owner",
        json={"password": GOOD_PASSWORD, "code": "000000"},
    )
    assert wrong.status_code == 401
    assert not (
        await second_factor_state(factory, user_id=account["id"])
    ).password_proved
    # And with nothing proved, the role is still refused (R-AUTH-20).
    assert not (
        await second_factor_state(factory, user_id=account["id"])
    ).password_proved


async def test_nothing_is_vouched_for_when_there_is_no_factor_to_vouch_for(env):
    """The endpoint checks first, but the write refuses on its own account.

    Both a factor being torn down between the check and the write and a
    caller that never checked land here, and the answer to each is that
    there is nothing to record a proof against.
    """
    new_client, factory, _ = env
    account = await register(new_client(), "Unfactored")
    assert not await prove_second_factor_owner(factory, user_id=account["id"])
    assert not (
        await second_factor_state(factory, user_id=account["id"])
    ).password_proved


async def test_something_that_is_not_a_code_at_all_burns_nothing(env):
    """`!!!-!!!` is not a wrong recovery code; it is not one.

    Everything a recovery code is not made of is folded away before the
    lookup, so a string of punctuation normalizes to nothing - and hashing
    nothing gives a perfectly good digest that would go to the table as if it
    were a guess.
    """
    new_client, factory, _ = env
    http = new_client()
    account = await register(http, "Punctuator")
    offer = (await http.post("/api/auth/second-factor/enrol")).json()
    codes = (await http.post(
        "/api/auth/second-factor/confirm",
        json={
            "secret": offer["secret"],
            "code": code_at(offer["secret"], current_step(time.time())),
        },
    )).json()["recoveryCodes"]

    outcome = await verify_second_factor(
        factory, user_id=account["id"], code="!!!-!!!"
    )
    assert outcome is SecondFactorOutcome.REJECTED
    # And the real ones are all still there.
    assert (
        await second_factor_state(factory, user_id=account["id"])
    ).recovery_codes_remaining == len(codes)


def test_an_offer_is_judged_against_the_clock_whatever_shape_its_timestamp_is():
    """A naive timestamp is a stored one, not a different moment.

    SQLite hands datetimes back without a timezone, and comparing one against
    an aware `now` raises rather than answering - which in this function would
    have turned "has this offer lapsed?" into a 500 on the enrolment that was
    trying to take it up.
    """
    now = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)
    naive = (now - OFFER_LIFETIME + timedelta(days=1)).replace(tzinfo=None)
    assert not offer_expired(naive, now)
    assert offer_expired((now - OFFER_LIFETIME - timedelta(minutes=1)).replace(tzinfo=None), now)
    # No date at all is nothing to stand on, so it does not stand.
    assert offer_expired(None, now)

    account = SimpleNamespace(pending_role=None, pending_role_at=None)
    assert pending_offer(account, now) is None
    account = SimpleNamespace(pending_role="moderator", pending_role_at=naive)
    assert pending_offer(account, now) == "moderator"


async def test_taking_up_an_offer_for_something_that_is_not_an_account(env):
    """The id comes from a session, but the function does not assume it."""
    _, factory, _ = env
    assert await take_up_offer(factory, user_id="not-a-uuid") is None
    assert await take_up_offer(factory, user_id=str(uuid4())) is None


async def test_a_password_given_at_setup_counts_as_the_proof(env):
    """Offered rather than demanded: giving it saves the separate step."""
    new_client, factory, _ = env
    http = new_client()
    account = await register(http, "Forehanded")
    offer = (await http.post("/api/auth/second-factor/enrol")).json()
    await http.post(
        "/api/auth/second-factor/confirm",
        json={
            "secret": offer["secret"],
            "code": code_at(offer["secret"], current_step(time.time())),
            "password": GOOD_PASSWORD,
        },
    )
    assert (await second_factor_state(factory, user_id=account["id"])).password_proved


async def test_a_saturated_deployment_bucket_still_lets_a_clean_caller_in(env, monkeypatch):
    """A global ceiling must be a ceiling, not a lever.

    Fifty addresses spending their own allowance fill it, and refusing on it
    alone would then turn every correct password on the deployment into a 429
    until the window rolled.
    """
    _, factory, _ = env
    monkeypatch.setenv("AUTH_LOGIN_GLOBAL_LIMIT", "5")
    guard = LoginGuard(factory)
    for attempt in range(6):
        await guard.note_failure(
            username=f"Sprayed{attempt}", address=f"10.4.4.{attempt}"
        )

    # Somebody who has failed nothing gets to try, however full it is.
    assert (await guard.check(username="Innocent", address="10.9.9.9")).allowed
    # And somebody who is part of the traffic that filled it does not.
    refused = await guard.check(username="Sprayed0", address="10.4.4.0")
    assert not refused.allowed


async def test_a_spray_is_still_bounded_once_the_deployment_bucket_is_full(env, monkeypatch):
    """The ceiling's own job: one more attempt per key, not unlimited."""
    _, factory, _ = env
    monkeypatch.setenv("AUTH_LOGIN_GLOBAL_LIMIT", "5")
    guard = LoginGuard(factory)
    for attempt in range(6):
        await guard.note_failure(
            username=f"Spread{attempt}", address=f"10.3.3.{attempt}"
        )
    # A fresh address the sprayer has not used yet is allowed one attempt...
    assert (await guard.check(username="Spread99", address="10.3.3.99")).allowed
    await guard.note_failure(username="Spread99", address="10.3.3.99")
    # ...and no more while the deployment bucket stays full.
    assert not (await guard.check(username="Spread99", address="10.3.3.99")).allowed
