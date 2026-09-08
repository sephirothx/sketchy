"""Signing in with something a relay cannot carry away (R-AUTH-23).

Driven through the real endpoints with a software authenticator
(`tests/softauthenticator.py`) rather than recorded fixtures, because what
these tests are about is the ceremony rather than one response: that the
challenge signed is the one this server chose, that it is worth exactly one
use, that a challenge minted to add a credential cannot be spent as a sign-in,
and that a counter going backwards is caught.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.auth.middleware import SessionAuthMiddleware
from app.auth.second_factor import second_factor_state
from app.auth.totp import code_at, current_step
from app.auth.routes import create_auth_router
from app.auth.sessions import list_active_sessions
from app.db.models import IdentityAlias, User, UserPasskey, WebauthnChallenge
from app.domain_values import AccountState
from app.repositories.sqlalchemy import SqlAlchemyUserRepository

from tests.dbfixtures import create_test_db
from tests.softauthenticator import SoftAuthenticator

pytestmark = pytest.mark.asyncio

PASSWORD = "a-good-password"
ORIGIN = "http://localhost:8000"


@pytest_asyncio.fixture
async def env(monkeypatch):
    monkeypatch.setenv("IP_HASH_SECRET", "passkey-test-secret")
    factory, engine = await create_test_db()
    repo = SqlAlchemyUserRepository(factory)
    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware, session_factory=factory)
    app.include_router(create_auth_router(repo, factory))

    clients: list[AsyncClient] = []

    def new_client() -> AsyncClient:
        client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        clients.append(client)
        return client

    try:
        yield new_client, factory
    finally:
        for client in clients:
            await client.aclose()
        await engine.dispose()


async def register(client: AsyncClient, username: str) -> dict:
    assert (await client.get("/api/auth/me")).status_code == 200
    response = await client.post(
        "/api/auth/register", json={"username": username, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    return response.json()


async def offer_a_role(factory, user_id: str, role: str = "moderator") -> None:
    """What an administrator's grant leaves behind (R-AUTH-20)."""
    async with factory() as session:
        async with session.begin():
            account = await session.get(User, UUID(user_id))
            account.pending_role = role
            account.pending_role_at = datetime.now(timezone.utc)


async def make_staff(factory, user_id: str, role: str = "moderator") -> None:
    async with factory() as session:
        async with session.begin():
            (await session.get(User, UUID(user_id))).role = role


async def registration_options(client: AsyncClient) -> dict:
    response = await client.post("/api/auth/passkeys/options")
    assert response.status_code == 200, response.text
    return json.loads(response.json()["options"])


async def assertion_options(client: AsyncClient) -> dict:
    response = await client.post("/api/auth/passkeys/challenge")
    assert response.status_code == 200, response.text
    return json.loads(response.json()["options"])


async def add_passkey(client: AsyncClient, authenticator: SoftAuthenticator) -> dict:
    options = await registration_options(client)
    return (
        await client.post(
            "/api/auth/passkeys",
            json={
                "credential": authenticator.register(options, origin=ORIGIN),
                "password": PASSWORD,
            },
        )
    ).json()


async def test_a_player_with_no_role_waiting_is_offered_nothing(env):
    """Passkeys are a staff control, and are not put in front of anybody else.

    The same rule the second factor follows (R-AUTH-20): a credential that
    gates nothing for an ordinary player, and cannot be recovered the way a
    password can, is not something to offer them.
    """
    new_client, _ = env
    client = new_client()
    await register(client, "Ordinary")
    refused = await client.post("/api/auth/passkeys/options")
    assert refused.status_code == 403
    assert (await client.get("/api/auth/passkeys")).json() == {
        "passkeys": [],
        "canHold": False,
    }


async def test_registering_a_passkey_takes_up_a_waiting_role(env):
    """The offer flow, with a passkey where the authenticator app was.

    Both proofs, for R-AUTH-20's reason: the assertion says an authenticator
    is present, the password says whose account it is being bound to.
    """
    new_client, factory = env
    client = new_client()
    account = await register(client, "Offered")
    await offer_a_role(factory, account["id"])

    body = await add_passkey(client, SoftAuthenticator())
    assert body["roleGranted"] == "moderator"
    assert body["passkey"]["backedUp"] is True

    async with factory() as session:
        stored = await session.get(User, UUID(account["id"]))
        assert stored.role == "moderator"
        assert stored.pending_role is None
    # Signed in throughout, on a session minted for the role it now holds.
    assert (await client.get("/api/auth/me")).json()["role"] == "moderator"


async def test_a_passkey_without_the_password_is_refused(env):
    """A stolen cookie must not be able to add a way in of its own."""
    new_client, factory = env
    client = new_client()
    account = await register(client, "Cookied")
    await offer_a_role(factory, account["id"])

    options = await registration_options(client)
    refused = await client.post(
        "/api/auth/passkeys",
        json={
            "credential": SoftAuthenticator().register(options, origin=ORIGIN),
            "password": "not-the-password-here",
        },
    )
    assert refused.status_code == 401
    assert await _passkey_count(factory, account["id"]) == 0


async def test_signing_in_with_a_passkey_needs_no_username_or_password(env):
    """One gesture, and the account is read from the credential.

    The point of a discoverable credential: nobody types a username, so there
    is nothing for a lookalike site to collect and nothing to relay.
    """
    new_client, factory = env
    owner = new_client()
    account = await register(owner, "Passkeyed")
    await offer_a_role(factory, account["id"])
    authenticator = SoftAuthenticator()
    await add_passkey(owner, authenticator)

    stranger = new_client()
    options = await assertion_options(stranger)
    signed_in = await stranger.post(
        "/api/auth/passkeys/verify",
        json={"credential": authenticator.sign(options, origin=ORIGIN)},
    )
    assert signed_in.status_code == 200, signed_in.text
    assert signed_in.json()["user"]["id"] == account["id"]
    # And the browser holds a session for it.
    assert (await stranger.get("/api/auth/me")).json()["id"] == account["id"]


async def test_the_assertion_counts_as_the_step_up_it_would_be_asked_for(env):
    """R-AUTH-21's proof, one request old.

    A code is not treated this way, because a code can be relayed and this
    cannot - which is the whole of why this exists.
    """
    new_client, factory = env
    owner = new_client()
    account = await register(owner, "Stepper")
    await offer_a_role(factory, account["id"])
    authenticator = SoftAuthenticator()
    await add_passkey(owner, authenticator)

    stranger = new_client()
    options = await assertion_options(stranger)
    await stranger.post(
        "/api/auth/passkeys/verify",
        json={"credential": authenticator.sign(options, origin=ORIGIN)},
    )
    sessions = await list_active_sessions(factory, user_id=account["id"])
    assert any(session.stepped_up_at is not None for session in sessions)


async def test_a_challenge_is_worth_exactly_one_use(env):
    """Replay is what the store exists to stop."""
    new_client, factory = env
    owner = new_client()
    account = await register(owner, "Replayed")
    await offer_a_role(factory, account["id"])
    authenticator = SoftAuthenticator()
    await add_passkey(owner, authenticator)

    stranger = new_client()
    options = await assertion_options(stranger)
    credential = authenticator.sign(options, origin=ORIGIN)
    first = await stranger.post("/api/auth/passkeys/verify", json={"credential": credential})
    assert first.status_code == 200, first.text

    replayed = new_client()
    again = await replayed.post("/api/auth/passkeys/verify", json={"credential": credential})
    assert again.status_code == 401
    assert "expired" in again.json()["detail"].lower()


async def test_a_challenge_nobody_handed_out_is_refused(env):
    """The challenge is the server's choice, not the caller's."""
    new_client, factory = env
    owner = new_client()
    account = await register(owner, "Forged")
    await offer_a_role(factory, account["id"])
    authenticator = SoftAuthenticator()
    await add_passkey(owner, authenticator)

    from webauthn.helpers import bytes_to_base64url

    invented = {"challenge": bytes_to_base64url(b"a" * 32)}
    refused = await new_client().post(
        "/api/auth/passkeys/verify",
        json={"credential": authenticator.sign(invented, origin=ORIGIN)},
    )
    assert refused.status_code == 401


async def test_a_registration_challenge_cannot_be_spent_as_a_sign_in(env):
    """What `purpose` is for: one pool would let the two ceremonies cross."""
    new_client, factory = env
    owner = new_client()
    account = await register(owner, "Crossed")
    await offer_a_role(factory, account["id"])
    authenticator = SoftAuthenticator()
    await add_passkey(owner, authenticator)

    # A fresh registration challenge, signed as though it were a sign-in.
    options = await registration_options(owner)
    refused = await new_client().post(
        "/api/auth/passkeys/verify",
        json={"credential": authenticator.sign(options, origin=ORIGIN)},
    )
    assert refused.status_code == 401


async def test_a_counter_that_goes_backwards_is_refused(env):
    """The one signal WebAuthn gives that a credential has been cloned."""
    new_client, factory = env
    owner = new_client()
    account = await register(owner, "Cloned")
    await offer_a_role(factory, account["id"])
    authenticator = SoftAuthenticator()
    await add_passkey(owner, authenticator)

    stranger = new_client()
    options = await assertion_options(stranger)
    await stranger.post(
        "/api/auth/passkeys/verify",
        json={"credential": authenticator.sign(options, origin=ORIGIN, sign_count=7)},
    )
    options = await assertion_options(stranger)
    refused = await stranger.post(
        "/api/auth/passkeys/verify",
        json={"credential": authenticator.sign(options, origin=ORIGIN, sign_count=3)},
    )
    assert refused.status_code == 401


async def test_a_staff_account_may_not_remove_its_only_way_in(env):
    """The rule the authenticator app follows, for the same reason.

    Giving up the role is what removes the requirement; deleting the
    credential the role depends on is how somebody locks themselves out.
    """
    new_client, factory = env
    client = new_client()
    account = await register(client, "Soleholder")
    await offer_a_role(factory, account["id"])
    added = await add_passkey(client, SoftAuthenticator())
    only_one = added["passkey"]["id"]

    refused = await client.request(
        "DELETE",
        f"/api/auth/passkeys/{only_one}",
        json={"password": PASSWORD},
    )
    assert refused.status_code == 400
    assert "only thing" in refused.json()["detail"]

    # With a second one in place, the first may go.
    await add_passkey(client, SoftAuthenticator())
    removed = await client.request(
        "DELETE",
        f"/api/auth/passkeys/{only_one}",
        json={"password": PASSWORD},
    )
    assert removed.status_code == 200, removed.text
    assert await _passkey_count(factory, account["id"]) == 1


async def test_a_staff_password_sign_in_is_pointed_at_the_passkey(env):
    """A staff account with a passkey and no authenticator app.

    The password route cannot finish, and saying "this account needs
    two-factor authentication" would be untrue - it has one. The refusal names
    what to use instead, and the header is what the form reads.
    """
    new_client, factory = env
    owner = new_client()
    account = await register(owner, "Pointed")
    await offer_a_role(factory, account["id"])
    await add_passkey(owner, SoftAuthenticator())

    fresh = new_client()
    refused = await fresh.post(
        "/api/auth/login", json={"username": "Pointed", "password": PASSWORD}
    )
    assert refused.status_code == 401
    assert refused.headers["X-Sketchy-Second-Factor"] == "passkey"
    assert "passkey" in refused.json()["detail"].lower()
    assert account["id"]


async def test_spent_and_stale_challenges_do_not_pile_up(env):
    """Nothing sweeps these on a timer, so each ceremony clears what expired."""
    new_client, factory = env
    client = new_client()
    account = await register(client, "Tidy")
    await offer_a_role(factory, account["id"])
    await registration_options(client)

    async with factory() as session:
        async with session.begin():
            row = (await session.scalars(select(WebauthnChallenge))).one()
            row.expires_at = datetime(2020, 1, 1, tzinfo=timezone.utc)

    await registration_options(client)
    async with factory() as session:
        remaining = (await session.scalars(select(WebauthnChallenge))).all()
    assert len(remaining) == 1
    assert remaining[0].expires_at.year > 2020
    assert account["id"]


async def test_a_passkey_vouches_for_itself_and_for_nothing_else(env):
    """Adding one must not legitimise an authenticator app nobody proved.

    The planted-factor attack R-AUTH-20 refuses, arriving by a side door: a
    stolen cookie binds an authenticator app, the account's owner later adds a
    passkey, and if that vouched for everything on the account the planted app
    would become a way in that satisfies a promotion. This ceremony proves a
    passkey and a password, and says nothing about a code.
    """
    new_client, factory = env
    client = new_client()
    account = await register(client, "Planted")
    await offer_a_role(factory, account["id"])

    # What a stolen cookie can do: bind an app, without the password.
    offer = (await client.post("/api/auth/second-factor/enrol")).json()
    confirmed = await client.post(
        "/api/auth/second-factor/confirm",
        json={
            "secret": offer["secret"],
            "code": code_at(offer["secret"], current_step(time.time())),
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    assert not (await second_factor_state(factory, user_id=account["id"])).password_proved

    # And what the owner does next says nothing about it.
    added = await add_passkey(client, SoftAuthenticator())
    assert added["roleGranted"] == "moderator"
    assert not (await second_factor_state(factory, user_id=account["id"])).password_proved


async def test_signing_in_with_a_passkey_carries_the_guest_along(env):
    """The half a second sign-in path is most likely to lose (R-ACCT-04).

    Somebody who has been playing as a guest and then signs in has a game
    behind them; the account they sign into has to inherit it, and the guest
    identity has to stop being a separate account with sessions of its own.
    """
    new_client, factory = env
    owner = new_client()
    account = await register(owner, "Carried")
    await offer_a_role(factory, account["id"])
    authenticator = SoftAuthenticator()
    await add_passkey(owner, authenticator)

    # A different browser, playing as a guest.
    guest = new_client()
    named = await guest.post(
        "/api/auth/display-name", json={"displayName": "PassingBy"}
    )
    assert named.status_code == 200, named.text
    guest_id = named.json()["id"]
    assert guest_id != account["id"]

    options = await assertion_options(guest)
    signed_in = await guest.post(
        "/api/auth/passkeys/verify",
        json={"credential": authenticator.sign(options, origin=ORIGIN)},
    )
    assert signed_in.status_code == 200, signed_in.text

    async with factory() as session:
        source = await session.get(User, UUID(guest_id))
        alias = await session.scalar(
            select(IdentityAlias).where(IdentityAlias.source_user_id == UUID(guest_id))
        )
    assert source.state == AccountState.MERGED.value
    assert alias is not None and str(alias.target_user_id) == account["id"]
    # And the guest's own sessions are gone with it.
    assert await list_active_sessions(factory, user_id=guest_id) == []


async def test_a_stolen_session_cannot_give_itself_an_authenticator(env):
    """The hole a passkey-only staff account opened, and what closes it.

    Enrolling asks for no password on purpose - it is optional for a player
    and gates nothing of theirs. But an account that already holds a
    credential is *changing* one, and until passkeys existed that was always
    true of a staff account, so the branch was never reached with anything at
    stake. A stolen cookie could otherwise bind an authenticator app nobody
    vouched for and step up with its codes, which is exactly what R-AUTH-21
    keeps a stolen cookie away from.
    """
    new_client, factory = env
    client = new_client()
    account = await register(client, "Cookiedagain")
    await offer_a_role(factory, account["id"])
    await add_passkey(client, SoftAuthenticator())

    offer = (await client.post("/api/auth/second-factor/enrol")).json()
    planted = await client.post(
        "/api/auth/second-factor/confirm",
        json={
            "secret": offer["secret"],
            "code": code_at(offer["secret"], current_step(time.time())),
        },
    )
    assert planted.status_code == 401
    assert not (await second_factor_state(factory, user_id=account["id"])).enrolled


async def test_an_authenticator_nobody_vouched_for_cannot_step_up(env):
    """The other half, for a factor planted before the role existed.

    A player's own account is worth nothing to plant on, so the app is bound
    while they are still a player - and then a role is granted on the strength
    of a passkey, and the planted factor comes along. Signing in still needs
    the password an attacker has not got; stepping up would need only the
    session they already stole.
    """
    new_client, factory = env
    client = new_client()
    account = await register(client, "Vouchless")

    # Planted while they are an ordinary player, which asks for nothing.
    offer = (await client.post("/api/auth/second-factor/enrol")).json()
    confirmed = await client.post(
        "/api/auth/second-factor/confirm",
        json={
            "secret": offer["secret"],
            "code": code_at(offer["secret"], current_step(time.time())),
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    recovery = confirmed.json()["recoveryCodes"][0]

    # Promoted later on the strength of a passkey.
    await offer_a_role(factory, account["id"])
    await add_passkey(client, SoftAuthenticator())
    assert not (await second_factor_state(factory, user_id=account["id"])).password_proved

    refused = await client.post(
        "/api/auth/step-up",
        json={"code": code_at(offer["secret"], current_step(time.time()) + 1)},
    )
    assert refused.status_code == 403, (refused.status_code, refused.text)
    assert "not been confirmed as yours" in refused.json()["detail"]

    # And the way out is the one the dialog already offers. Proved with a
    # recovery code rather than a TOTP one, which spends no step and leaves
    # the next one for the step-up below: inside a single thirty-second
    # interval there is exactly one unspent step to go round.
    proved = await client.post(
        "/api/auth/second-factor/confirm-owner",
        json={"password": PASSWORD, "code": recovery},
    )
    assert proved.status_code == 200, proved.text
    stepped = await client.post(
        "/api/auth/step-up",
        json={"code": code_at(offer["secret"], current_step(time.time()) + 1)},
    )
    assert stepped.status_code == 200, stepped.text


async def test_a_response_that_is_not_one_is_refused_rather_than_parsed(env):
    """Everything about the credential arrives from the browser.

    Which means every field of it can be absent, the wrong type, or somebody's
    idea of a joke - and the first thing this server does with it is look up
    the challenge it names. None of that may become a traceback.
    """
    new_client, factory = env
    client = new_client()
    account = await register(client, "Malformed")
    await offer_a_role(factory, account["id"])

    for credential in (
        {},
        {"response": "not-an-object"},
        {"response": {}},
        {"response": {"clientDataJSON": "!!!not-base64!!!"}},
        {"response": {"clientDataJSON": ""}},
        {"rawId": 42, "response": {"clientDataJSON": _client_data_json("abc")}},
    ):
        refused = await client.post(
            "/api/auth/passkeys/verify", json={"credential": credential}
        )
        assert refused.status_code == 401, credential
        assert refused.json()["detail"]


async def test_the_same_authenticator_is_not_registered_twice(env):
    """`exclude_credentials` tells the browser, and the server checks anyway.

    A second row for one authenticator would be two entries nobody can tell
    apart in a list whose whole purpose is knowing what you can sign in with.
    """
    new_client, factory = env
    client = new_client()
    account = await register(client, "Doubled")
    await offer_a_role(factory, account["id"])
    authenticator = SoftAuthenticator()
    await add_passkey(client, authenticator)

    options = await registration_options(client)
    again = await client.post(
        "/api/auth/passkeys",
        json={
            "credential": authenticator.register(options, origin=ORIGIN),
            "password": PASSWORD,
        },
    )
    assert again.status_code == 400
    assert "already registered" in again.json()["detail"]
    assert await _passkey_count(factory, account["id"]) == 1


async def test_an_attestation_that_does_not_verify_is_refused(env):
    """Signed for another origin, which is the binding this all rests on."""
    new_client, factory = env
    client = new_client()
    account = await register(client, "Elsewhere")
    await offer_a_role(factory, account["id"])

    options = await registration_options(client)
    refused = await client.post(
        "/api/auth/passkeys",
        json={
            "credential": SoftAuthenticator().register(
                options, origin="https://not-this-server.example"
            ),
            "password": PASSWORD,
        },
    )
    assert refused.status_code == 400
    assert await _passkey_count(factory, account["id"]) == 0


async def test_removing_a_passkey_that_is_not_there_says_so(env):
    """A stale page, or an id from somebody else's account."""
    new_client, factory = env
    client = new_client()
    account = await register(client, "Stale")
    await offer_a_role(factory, account["id"])
    await add_passkey(client, SoftAuthenticator())
    await add_passkey(client, SoftAuthenticator())

    missing = await client.request(
        "DELETE",
        f"/api/auth/passkeys/{uuid4()}",
        json={"password": PASSWORD},
    )
    assert missing.status_code == 404
    assert await _passkey_count(factory, account["id"]) == 2


def _client_data_json(challenge: str) -> str:
    from webauthn.helpers import bytes_to_base64url

    return bytes_to_base64url(
        json.dumps({"type": "webauthn.get", "challenge": challenge}).encode("utf-8")
    )


async def _passkey_count(factory, user_id: str) -> int:
    async with factory() as session:
        return len(
            (
                await session.scalars(
                    select(UserPasskey).where(UserPasskey.user_id == UUID(user_id))
                )
            ).all()
        )
