"""Signing in with something a relay cannot carry away (R-AUTH-23).

Driven through the real endpoints with a software authenticator
(`tests/softauthenticator.py`) rather than recorded fixtures, because what
these tests are about is the ceremony rather than one response: that the
challenge signed is the one this server chose, that it is worth exactly one
use, that a challenge minted to add a credential cannot be spent as a sign-in,
and that a counter going backwards is caught.
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from uuid import UUID, uuid4

import cbor2
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.auth.middleware import SessionAuthMiddleware
from app.auth.passkeys import LastFactorError, remove_passkey
from app.auth.second_factor import second_factor_state
from app.auth.totp import code_at, current_step
from app.auth.routes import create_auth_router
from app.auth.sessions import list_active_sessions
from app.db.models import IdentityAlias, User, UserPasskey, WebauthnChallenge
from app.domain_values import AccountState
from app.repositories.sqlalchemy import SqlAlchemyUserRepository

from tests.dbfixtures import create_test_db
from tests.softauthenticator import SoftAuthenticator


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


def _encoded(raw: bytes) -> str:
    from webauthn.helpers import bytes_to_base64url

    return bytes_to_base64url(raw)


def _client_data_json(challenge: str) -> str:
    from webauthn.helpers import bytes_to_base64url

    return bytes_to_base64url(
        json.dumps({"type": "webauthn.get", "challenge": challenge}).encode("utf-8")
    )


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


async def test_a_deleted_account_cannot_be_signed_back_into(env):
    """Erasure anonymises the row rather than removing it (R-PRIV-04).

    Which means `ON DELETE CASCADE` never fires, and a credential left behind
    outlives the account. It does not matter much for an authenticator app -
    the username and password go, so a code alone opens nothing - but a
    passkey needs neither, and one left behind is the front door to an account
    somebody deleted. Two answers, because either alone is a single point of
    failure: the credentials go with the account, and a credential is refused
    against anything that is not a registered account.
    """
    new_client, factory = env
    client = new_client()
    account = await register(client, "Departing")
    await offer_a_role(factory, account["id"])
    authenticator = SoftAuthenticator()
    await add_passkey(client, authenticator)

    deleted = await client.request(
        "DELETE", "/api/auth/account", json={"password": PASSWORD}
    )
    assert deleted.status_code == 200, deleted.text
    assert await _passkey_count(factory, account["id"]) == 0

    stranger = new_client()
    options = await assertion_options(stranger)
    refused = await stranger.post(
        "/api/auth/passkeys/verify",
        json={"credential": authenticator.sign(options, origin=ORIGIN)},
    )
    assert refused.status_code == 401
    assert (await stranger.get("/api/auth/me")).json() is None


async def test_a_challenge_is_spent_by_an_attempt_that_failed(env):
    """One attempt, good or bad. Anything else is a retry budget.

    The deletion used to sit inside the transaction that verified the
    signature, so a verification that raised took the deletion with it: a
    signature for the wrong origin handed the challenge back, and the next
    attempt could use it again.
    """
    new_client, factory = env
    client = new_client()
    account = await register(client, "Retried")
    await offer_a_role(factory, account["id"])
    authenticator = SoftAuthenticator()

    options = await registration_options(client)
    wrong = await client.post(
        "/api/auth/passkeys",
        json={
            "credential": authenticator.register(
                options, origin="https://not-this-server.example"
            ),
            "password": PASSWORD,
        },
    )
    assert wrong.status_code == 400

    # The same challenge, signed properly this time: it is gone.
    again = await client.post(
        "/api/auth/passkeys",
        json={
            "credential": authenticator.register(options, origin=ORIGIN),
            "password": PASSWORD,
        },
    )
    assert again.status_code == 400
    assert "expired" in again.json()["detail"].lower()
    assert await _passkey_count(factory, account["id"]) == 0


async def test_two_assertions_at_once_cannot_walk_the_counter_backwards(env):
    """The counter is the one cloning signal WebAuthn gives (R-AUTH-23).

    Verified against the value read a moment earlier and then written back,
    two assertions each pass their own check and race: the later write wins,
    and a lower counter landing last is the stored value going backwards -
    after which the clone it would have caught looks current.

    Where the concurrency is real: PostgreSQL, which the suite also runs
    against. The SQLite fixture hands every session one shared connection, so
    these two queue rather than interleave, and what this pins there is that
    the outcome is the same one either way.
    """
    new_client, factory = env
    owner = new_client()
    account = await register(owner, "Counted")
    await offer_a_role(factory, account["id"])
    authenticator = SoftAuthenticator()
    await add_passkey(owner, authenticator)

    ahead = await assertion_options(new_client())
    behind = await assertion_options(new_client())
    both = await asyncio.gather(
        new_client().post(
            "/api/auth/passkeys/verify",
            json={"credential": authenticator.sign(ahead, origin=ORIGIN, sign_count=7)},
        ),
        new_client().post(
            "/api/auth/passkeys/verify",
            json={"credential": authenticator.sign(behind, origin=ORIGIN, sign_count=3)},
        ),
    )
    accepted = [
        counter
        for counter, response in zip((7, 3), both, strict=True)
        if response.status_code == 200
    ]
    # The one carrying the lower counter cannot be accepted after the higher
    # one, and whatever was accepted is what the row holds.
    async with factory() as session:
        stored = (
            await session.scalars(
                select(UserPasskey).where(UserPasskey.user_id == UUID(account["id"]))
            )
        ).one()
    assert accepted, [response.text for response in both]
    assert stored.sign_count == max(accepted)


async def test_the_role_that_decides_the_last_credential_is_read_by_the_write(env):
    """A promotion landing while a removal is in flight has to be seen.

    The account most likely to be promoted still holds the passkey it signed
    in with, and that passkey is *why* the promotion goes through outright.
    So the two can meet: a former moderator, an ordinary player at the moment
    they press Remove, is staff by the time the deletion runs. Deciding from
    the role the request arrived with hands a brand-new moderator an account
    with nothing to sign in with.

    Read as the service sees it, which is the point: the caller passes only
    the deployment's switch, and the role comes out of the same statement
    that does the deleting.
    """
    new_client, factory = env
    client = new_client()
    account = await register(client, "Promoted")
    await offer_a_role(factory, account["id"])
    added = await add_passkey(client, SoftAuthenticator())

    # Staff now, whatever the request that is about to run believed.
    await make_staff(factory, account["id"], "moderator")
    with pytest.raises(LastFactorError):
        await remove_passkey(
            factory,
            user_id=account["id"],
            passkey_id=added["passkey"]["id"],
            required=True,
        )
    assert await _passkey_count(factory, account["id"]) == 1

    # And an ordinary player may still remove their own.
    await make_staff(factory, account["id"], "user")
    assert await remove_passkey(
        factory,
        user_id=account["id"],
        passkey_id=added["passkey"]["id"],
        required=True,
    )
    assert await _passkey_count(factory, account["id"]) == 0


async def test_two_removals_at_once_cannot_empty_a_staff_account(env):
    """An account racing itself, which is the only way this is reachable.

    Counting in one transaction and deleting in another lets both requests see
    two credentials, each conclude the other will remain, and leave a
    moderator with nothing to sign in with. The count is part of the DELETE
    for that reason, and the account row is locked for PostgreSQL's, where two
    statements deleting different rows never block each other.

    As above, the SQLite fixture serializes these on one connection; what it
    pins here is the answer, and PostgreSQL is where the interleaving is real.
    """
    new_client, factory = env
    client = new_client()
    account = await register(client, "Racing")
    await offer_a_role(factory, account["id"])
    first = await add_passkey(client, SoftAuthenticator())
    second = await add_passkey(client, SoftAuthenticator())

    both = await asyncio.gather(
        client.request(
            "DELETE",
            f"/api/auth/passkeys/{first['passkey']['id']}",
            json={"password": PASSWORD},
        ),
        client.request(
            "DELETE",
            f"/api/auth/passkeys/{second['passkey']['id']}",
            json={"password": PASSWORD},
        ),
    )
    assert sorted(response.status_code for response in both) == [200, 400]
    assert await _passkey_count(factory, account["id"]) == 1


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


@pytest.mark.parametrize(
    "client_data",
    [
        # JSON that is no object: `.get` on it raised, a 500.
        _encoded(b"[1]"),
        _encoded(b'"s"'),
        # Challenges no server minted. The NUL is behind base64, out of
        # ControlFreeModel's sight, and PostgreSQL refused it in the lookup.
        _client_data_json("\x00"),
        _client_data_json("a\x00b"),
        _client_data_json("x" * 300),
        _client_data_json("not base64url!"),
    ],
    ids=["array", "string", "nul", "embedded-nul", "over-long", "not-base64url"],
)
async def test_client_data_naming_no_minted_challenge_is_refused(env, client_data):
    """Both ceremonies read the challenge out of `clientDataJSON` before
    anything is verified, and look it up. What decodes to no challenge this
    server could have minted is a ceremony that did not check out."""
    new_client, factory = env
    client = new_client()
    account = await register(client, "Unminted")
    await offer_a_role(factory, account["id"])
    # An id, so that without the challenge guard /verify would get past its
    # rawId check to the lookup this test is about, rather than stop there.
    credential = {"id": "AAAA", "rawId": "AAAA", "response": {"clientDataJSON": client_data}}

    # Not "That request has expired.": a lookup that merely missed answers the
    # same status, so only the reason says the challenge was refused before it.
    refused = await client.post("/api/auth/passkeys/verify", json={"credential": credential})
    assert refused.status_code == 401, refused.text
    assert refused.json()["detail"] == "That response could not be read."
    refused = await client.post(
        "/api/auth/passkeys", json={"credential": credential, "password": PASSWORD}
    )
    assert refused.status_code == 400, refused.text
    assert refused.json()["detail"] == "That response could not be read."
    assert await _passkey_count(factory, account["id"]) == 0


@pytest.mark.parametrize("value", [None, 5], ids=["missing", "not-a-string"])
async def test_a_signed_challenge_with_a_malformed_body_is_refused(env, value):
    """The challenge is real and claimed; what py_webauthn then parses is not.
    Its InvalidJSONStructure is no InvalidRegistrationResponse nor
    InvalidAuthenticationResponse, so it escaped both ceremonies as a 500."""
    new_client, factory = env
    owner = new_client()
    account = await register(owner, "Misshapen")
    await offer_a_role(factory, account["id"])
    authenticator = SoftAuthenticator()

    credential = authenticator.register(await registration_options(owner), origin=ORIGIN)
    _set_or_drop(credential["response"], "attestationObject", value)
    refused = await owner.post(
        "/api/auth/passkeys", json={"credential": credential, "password": PASSWORD}
    )
    assert refused.status_code == 400, refused.text
    assert await _passkey_count(factory, account["id"]) == 0

    await add_passkey(owner, authenticator)
    stranger = new_client()
    credential = authenticator.sign(await assertion_options(stranger), origin=ORIGIN)
    _set_or_drop(credential["response"], "authenticatorData", value)
    refused = await stranger.post("/api/auth/passkeys/verify", json={"credential": credential})
    assert refused.status_code == 401, refused.text
    assert ((await stranger.get("/api/auth/me")).json() or {}).get("id") != account["id"]


def _set_or_drop(fields: dict, key: str, value) -> None:
    if value is None:
        fields.pop(key)
    else:
        fields[key] = value


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


@pytest.mark.parametrize(
    "passkey_id",
    ["%00", "a%00b", "x" * 300, "not-a-passkey"],
    ids=["nul", "embedded-nul", "over-long", "not-a-uuid"],
)
async def test_an_id_that_could_name_no_passkey_is_not_found(env, passkey_id):
    """Any path segment may arrive, and the id column is a UUID.

    An unparseable id used to raise out of the statement it was bound for:
    a 500 on every dialect, and a NUL is one PostgreSQL refuses outright.
    It names no credential, so it is answered like a stale one."""
    new_client, factory = env
    client = new_client()
    account = await register(client, "Malformed")
    await offer_a_role(factory, account["id"])
    await add_passkey(client, SoftAuthenticator())

    refused = await client.request(
        "DELETE", f"/api/auth/passkeys/{passkey_id}", json={"password": PASSWORD}
    )
    assert refused.status_code == 404, refused.text
    assert refused.json()["detail"] == "No such passkey."
    assert await _passkey_count(factory, account["id"]) == 1


async def _passkey_count(factory, user_id: str) -> int:
    async with factory() as session:
        return len(
            (
                await session.scalars(
                    select(UserPasskey).where(UserPasskey.user_id == UUID(user_id))
                )
            ).all()
        )


async def test_client_data_nested_past_the_parser_s_depth_is_refused(env):
    """`clientDataJSON` is a few hundred bytes from any browser. Two hundred
    thousand brackets behind base64 - out of ControlFreeModel's sight, under
    the body limit - made `json.loads` raise RecursionError, a 500 that needs
    no account. Refused by length before it is decoded."""
    new_client, factory = env
    client = new_client()
    account = await register(client, "Bracketed")
    await offer_a_role(factory, account["id"])
    # The bound itself, too: a well-formed object one character past it.
    padded = json.dumps({"type": "webauthn.get", "challenge": "AAAA", "pad": ""}).encode()
    at_bound = _encoded(padded[:-2] + b"x" * (3072 - len(padded)) + b'"}')
    assert len(at_bound) == 4096
    past_bound = _encoded(padded[:-2] + b"x" * (3075 - len(padded)) + b'"}')
    assert len(past_bound) > 4096
    for client_data in (_encoded(b"[" * 200_000), past_bound):
        credential = {"id": "AAAA", "rawId": "AAAA", "response": {"clientDataJSON": client_data}}
        refused = await client.post(
            "/api/auth/passkeys/verify", json={"credential": credential}
        )
        assert refused.status_code == 401, refused.text
        assert refused.json()["detail"] == "That response could not be read."
        refused = await client.post(
            "/api/auth/passkeys", json={"credential": credential, "password": PASSWORD}
        )
        assert refused.status_code == 400, refused.text
        assert refused.json()["detail"] == "That response could not be read."
    # At the bound it is read: the lookup misses, which is a different refusal.
    credential = {"id": "AAAA", "rawId": "AAAA", "response": {"clientDataJSON": at_bound}}
    refused = await client.post("/api/auth/passkeys/verify", json={"credential": credential})
    assert refused.status_code == 401, refused.text
    assert refused.json()["detail"] != "That response could not be read."


class _KeyedAuthenticator(SoftAuthenticator):
    """Signs as usual, but registers whatever public key it is given."""

    def __init__(self, key: bytes) -> None:
        super().__init__()
        self._key = key

    def _cose_public_key(self) -> bytes:
        return self._key


@pytest.mark.parametrize(
    "key",
    [
        cbor2.dumps({3: -7}),
        cbor2.dumps(5),
        cbor2.dumps({1: 2, 3: -7, -1: 1, -2: b"\x01" * 32, -3: b"\x01" * 32}),
        cbor2.dumps([1, 2]),
        cbor2.dumps("ab"),
        cbor2.dumps(b"ab"),
    ],
    ids=["no-kty", "not-a-map", "off-the-curve", "a-list", "text", "bytes"],
)
async def test_a_public_key_nothing_could_verify_with_is_not_registered(env, key):
    """A "none" attestation keeps whatever key the client sends. One that is
    no key raised KeyError, IndexError or TypeError out of the library - a
    500 - and one off the curve was stored, so every later sign-in naming it
    was a 500 too, for anybody holding the credential id. Refused at
    registration."""
    new_client, factory = env
    owner = new_client()
    account = await register(owner, "Keyless")
    await offer_a_role(factory, account["id"])
    authenticator = _KeyedAuthenticator(key)

    credential = authenticator.register(await registration_options(owner), origin=ORIGIN)
    refused = await owner.post(
        "/api/auth/passkeys", json={"credential": credential, "password": PASSWORD}
    )
    assert refused.status_code == 400, refused.text
    assert refused.json()["detail"] == "That passkey could not be verified. Please try again."
    assert await _passkey_count(factory, account["id"]) == 0


async def test_a_credential_id_longer_than_its_column_is_not_registered(env):
    """`credential_id` is 255 characters of base64url. A longer one SQLite
    kept whole, and PostgreSQL refused in the INSERT - a 500."""
    new_client, factory = env
    owner = new_client()
    account = await register(owner, "Lengthy")
    await offer_a_role(factory, account["id"])
    authenticator = SoftAuthenticator()
    authenticator.credential_id = bytes(range(256)) * 2  # 512 bytes, 683 characters

    credential = authenticator.register(await registration_options(owner), origin=ORIGIN)
    refused = await owner.post(
        "/api/auth/passkeys", json={"credential": credential, "password": PASSWORD}
    )
    assert refused.status_code == 400, refused.text
    assert refused.json()["detail"] == "That passkey could not be verified. Please try again."
    assert await _passkey_count(factory, account["id"]) == 0


async def test_a_counter_past_its_column_is_refused_at_both_ceremonies(env):
    """`sign_count` is a signed 32-bit column and the authenticator's counter
    an unsigned one. A counter of 2^31 PostgreSQL refused at bind - a 500 on
    the INSERT, and on the compare-and-swap of a later sign-in."""
    new_client, factory = env
    owner = new_client()
    account = await register(owner, "Counted")
    await offer_a_role(factory, account["id"])

    high = SoftAuthenticator()
    high.sign_count = 2**31
    credential = high.register(await registration_options(owner), origin=ORIGIN)
    refused = await owner.post(
        "/api/auth/passkeys", json={"credential": credential, "password": PASSWORD}
    )
    assert refused.status_code == 400, refused.text
    assert refused.json()["detail"] == "That passkey could not be verified. Please try again."
    assert await _passkey_count(factory, account["id"]) == 0

    authenticator = SoftAuthenticator()
    await add_passkey(owner, authenticator)
    stranger = new_client()
    credential = authenticator.sign(
        await assertion_options(stranger), origin=ORIGIN, sign_count=2**31
    )
    refused = await stranger.post("/api/auth/passkeys/verify", json={"credential": credential})
    assert refused.status_code == 401, refused.text
    assert refused.json()["detail"] == "That passkey could not be verified. Please try again."
    async with factory() as session:
        stored = await session.scalar(
            select(UserPasskey.sign_count).where(UserPasskey.user_id == UUID(account["id"]))
        )
    assert stored == 0
