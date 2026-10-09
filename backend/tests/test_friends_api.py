"""The friends endpoints, over real HTTP and a real session cookie.

`test_friends.py` covers the rules; this covers what a caller can observe -
which is deliberately less. The two assertions that matter most here are
negative: a guest is told why they cannot, and everybody else is told the same
thing whether or not their request went anywhere.
"""
from __future__ import annotations

from uuid import UUID

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.friends import ACCOUNT_REQUIRED_HEADER, create_friends_router
from app.api.inbox import create_inbox_router
from app.api.user_blocks import create_user_blocks_router
from app.auth.blocks import BlockService
from app.auth.middleware import SessionAuthMiddleware
from app.auth.routes import create_auth_router
from app.db.models import UserBlock
from app.domain_values import FriendshipState
from app.repositories.sqlalchemy import SqlAlchemyUserRepository
from app.services.friends import FriendService, friendship_key

from tests.dbfixtures import create_test_db

PASSWORD = "a-good-password"


@pytest_asyncio.fixture
async def env(monkeypatch):
    monkeypatch.setenv("IP_HASH_SECRET", "friends-test-secret")
    factory, engine = await create_test_db()
    users = SqlAlchemyUserRepository(factory)
    friends = FriendService(factory)
    blocks = BlockService(factory)
    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware, session_factory=factory)
    app.include_router(create_auth_router(users, factory))
    app.include_router(create_friends_router(factory, friends))
    app.include_router(create_user_blocks_router(factory, blocks, friends))
    app.include_router(create_inbox_router(factory))
    clients: list[AsyncClient] = []

    def new_client() -> AsyncClient:
        client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        clients.append(client)
        return client

    try:
        yield new_client, factory, friends
    finally:
        for client in clients:
            await client.aclose()
        await engine.dispose()


async def name_a_guest(client: AsyncClient, name: str) -> None:
    assert (await client.get("/api/auth/me")).status_code == 200
    assert (
        await client.post("/api/auth/display-name", json={"displayName": name})
    ).status_code == 200


async def register(client: AsyncClient, username: str) -> dict:
    await name_a_guest(client, username)
    response = await client.post(
        "/api/auth/register", json={"username": username, "password": PASSWORD}
    )
    assert response.status_code == 200
    return response.json()


async def test_a_request_and_its_acceptance_show_on_both_sides(env):
    new_client, _, _ = env
    ada_http, bob_http = new_client(), new_client()
    ada = await register(ada_http, "Ada")
    bob = await register(bob_http, "Bob")

    sent = await ada_http.post("/api/users/me/friends", json={"userId": bob["id"]})
    assert sent.status_code == 200
    assert sent.json()["status"] == FriendshipState.PENDING.value

    # Waiting at the right end, and named as such at each.
    assert [
        entry["userId"] for entry in (await ada_http.get("/api/users/me/friends")).json()["outgoing"]
    ] == [bob["id"]]
    incoming = (await bob_http.get("/api/users/me/friends")).json()["incoming"]
    assert [entry["userId"] for entry in incoming] == [ada["id"]]
    assert incoming[0]["requestedByMe"] is False
    assert incoming[0]["displayName"] == "Ada"

    accepted = await bob_http.post(f"/api/users/me/friends/{ada['id']}/accept")
    assert accepted.status_code == 200
    assert accepted.json()["status"] == FriendshipState.ACCEPTED.value

    for http, other in ((ada_http, bob), (bob_http, ada)):
        listing = (await http.get("/api/users/me/friends")).json()
        assert [entry["userId"] for entry in listing["friends"]] == [other["id"]]
        assert listing["incoming"] == [] and listing["outgoing"] == []


async def test_a_guest_is_told_why_rather_than_refused_silently(env):
    """The one refusal here that names its reason: it is the caller's own."""
    new_client, _, _ = env
    guest_http, registered_http = new_client(), new_client()
    await name_a_guest(guest_http, "Guesty")
    registered = await register(registered_http, "Ada")

    refused = await guest_http.post(
        "/api/users/me/friends", json={"userId": registered["id"]}
    )
    assert refused.status_code == 403
    assert "Create an account" in refused.json()["detail"]
    assert (await guest_http.get("/api/users/me/friends")).status_code == 403


async def test_a_request_to_a_guest_looks_exactly_like_one_that_landed(env):
    new_client, _, service = env
    ada_http, guest_http = new_client(), new_client()
    ada = await register(ada_http, "Ada")
    await name_a_guest(guest_http, "Guesty")
    guest_id = (await guest_http.get("/api/auth/me")).json()["id"]

    answer = await ada_http.post("/api/users/me/friends", json={"userId": guest_id})
    assert answer.status_code == 200
    assert answer.json()["status"] == FriendshipState.PENDING.value
    # Nothing was written, and Ada cannot tell.
    assert await service.get(UUID(ada["id"]), UUID(guest_id)) is None
    assert (await ada_http.get("/api/users/me/friends")).json()["outgoing"] == []


async def test_a_request_into_a_block_looks_the_same_too(env):
    new_client, _, service = env
    ada_http, bob_http = new_client(), new_client()
    ada = await register(ada_http, "Ada")
    bob = await register(bob_http, "Bob")
    assert (
        await bob_http.post("/api/users/me/blocks", json={"userId": ada["id"]})
    ).status_code == 201

    answer = await ada_http.post("/api/users/me/friends", json={"userId": bob["id"]})
    assert answer.status_code == 200
    assert answer.json()["status"] == FriendshipState.PENDING.value
    assert await service.get(UUID(ada["id"]), UUID(bob["id"])) is None


async def test_blocking_a_friend_ends_the_friendship(env):
    """The block would otherwise leave a room-join capability behind (#529)."""
    new_client, _, service = env
    ada_http, bob_http = new_client(), new_client()
    ada = await register(ada_http, "Ada")
    bob = await register(bob_http, "Bob")
    await ada_http.post("/api/users/me/friends", json={"userId": bob["id"]})
    await bob_http.post(f"/api/users/me/friends/{ada['id']}/accept")
    assert await service.are_friends(UUID(ada["id"]), UUID(bob["id"]))

    assert (
        await bob_http.post("/api/users/me/blocks", json={"userId": ada["id"]})
    ).status_code == 201

    assert not await service.are_friends(UUID(ada["id"]), UUID(bob["id"]))
    assert await service.get(UUID(ada["id"]), UUID(bob["id"])) is None
    assert (await ada_http.get("/api/users/me/friends")).json()["friends"] == []


async def test_declining_leaves_a_refusal_that_a_re_request_cannot_pass(env):
    new_client, factory, service = env
    ada_http, bob_http = new_client(), new_client()
    ada = await register(ada_http, "Ada")
    bob = await register(bob_http, "Bob")
    await ada_http.post("/api/users/me/friends", json={"userId": bob["id"]})

    assert (
        await bob_http.delete(f"/api/users/me/friends/{ada['id']}")
    ).status_code == 204

    row = await service.get(UUID(ada["id"]), UUID(bob["id"]))
    assert row.status == FriendshipState.DECLINED.value
    # Neither side is asked to keep looking at it.
    assert (await ada_http.get("/api/users/me/friends")).json()["outgoing"] == []
    assert (await bob_http.get("/api/users/me/friends")).json()["incoming"] == []

    # And Ada asking again is answered as though it landed.
    again = await ada_http.post("/api/users/me/friends", json={"userId": bob["id"]})
    assert again.status_code == 200
    row = await service.get(UUID(ada["id"]), UUID(bob["id"]))
    assert row.status == FriendshipState.DECLINED.value


async def test_unfriending_leaves_nothing_and_lets_either_ask_again(env):
    new_client, _, service = env
    ada_http, bob_http = new_client(), new_client()
    ada = await register(ada_http, "Ada")
    bob = await register(bob_http, "Bob")
    await ada_http.post("/api/users/me/friends", json={"userId": bob["id"]})
    await bob_http.post(f"/api/users/me/friends/{ada['id']}/accept")

    assert (
        await ada_http.delete(f"/api/users/me/friends/{bob['id']}")
    ).status_code == 204
    assert await service.get(UUID(ada["id"]), UUID(bob["id"])) is None

    resent = await bob_http.post("/api/users/me/friends", json={"userId": ada["id"]})
    assert resent.status_code == 200


async def test_you_cannot_friend_or_unfriend_yourself(env):
    new_client, _, service = env
    ada_http = new_client()
    ada = await register(ada_http, "Ada")

    # The request path answers as it does for any id that goes nowhere.
    answer = await ada_http.post("/api/users/me/friends", json={"userId": ada["id"]})
    assert answer.status_code == 200
    # The addressed paths say so plainly - there is no third party to protect.
    assert (
        await ada_http.post(f"/api/users/me/friends/{ada['id']}/accept")
    ).status_code == 422
    assert (
        await ada_http.delete(f"/api/users/me/friends/{ada['id']}")
    ).status_code == 422


@pytest.mark.parametrize("probe_lands", [True, False])
async def test_the_request_limit_cannot_tell_whether_a_request_landed(
    env, monkeypatch, probe_lands
):
    """#1062: the bucket was refunded for an attempt that wrote nothing and
    spent for one that landed, so with one attempt left, asking X and then Y
    answered 429 for Y exactly when X had landed - R-FRIEND-04's question
    answered by the limit. Every attempt now costs one."""
    from app.auth.rate_limit import PersistentRateLimiter

    new_client, factory, service = env
    limit = 3
    monkeypatch.setattr(
        service,
        "_request_limiter",
        PersistentRateLimiter(
            factory, scope="friend_request", limit=limit, window_seconds=3600
        ),
    )
    ada_http, bob_http, cid_http = new_client(), new_client(), new_client()
    ada = await register(ada_http, "Ada")
    bob = await register(bob_http, "Bob")
    cid = await register(cid_http, "Cid")
    guest_http = new_client()
    await name_a_guest(guest_http, "Guesty")
    guest_id = (await guest_http.get("/api/auth/me")).json()["id"]

    # One attempt left, spent on a probe that lands nowhere...
    for _ in range(limit - 1):
        answer = await ada_http.post("/api/users/me/friends", json={"userId": guest_id})
        assert answer.status_code == 200, answer.text
    if not probe_lands:
        # Bob has blocked Ada: the probe goes nowhere, and says so to nobody.
        assert (
            await bob_http.post("/api/users/me/blocks", json={"userId": ada["id"]})
        ).status_code in (200, 201)
    probe = await ada_http.post("/api/users/me/friends", json={"userId": bob["id"]})
    assert probe.status_code == 200
    # ...and the next is refused whether or not the probe landed.
    after = await ada_http.post("/api/users/me/friends", json={"userId": cid["id"]})
    assert after.status_code == 429


async def test_an_unknown_or_malformed_target_is_refused_without_a_stack_trace(env):
    new_client, _, _ = env
    ada_http = new_client()
    await register(ada_http, "Ada")

    stranger = "0199a000-0000-7000-8000-0000000000ff"
    answer = await ada_http.post("/api/users/me/friends", json={"userId": stranger})
    assert answer.status_code == 200

    assert (
        await ada_http.post("/api/users/me/friends", json={"userId": "not-a-uuid"})
    ).status_code == 422
    assert (
        await ada_http.post(
            "/api/users/me/friends", json={"userId": stranger, "extra": 1}
        )
    ).status_code == 422


async def test_the_pair_is_stored_once_whichever_side_asks(env):
    new_client, factory, service = env
    ada_http, bob_http = new_client(), new_client()
    ada = await register(ada_http, "Ada")
    bob = await register(bob_http, "Bob")

    await ada_http.post("/api/users/me/friends", json={"userId": bob["id"]})
    # A crossing request: Bob asking back is how he says yes.
    crossed = await bob_http.post("/api/users/me/friends", json={"userId": ada["id"]})
    assert crossed.json()["status"] == FriendshipState.ACCEPTED.value

    low, high = friendship_key(UUID(ada["id"]), UUID(bob["id"]))
    async with factory() as session:
        from sqlalchemy import func, select

        from app.db.models import Friendship

        total = await session.scalar(select(func.count()).select_from(Friendship))
    assert total == 1
    assert low < high


class Notifications:
    """Stands in for the socket emit `main.py` wires to these routers."""

    def __init__(self):
        self.told: list[str] = []

    async def __call__(self, user_id: str) -> None:
        self.told.append(user_id)


@pytest_asyncio.fixture
async def wired(monkeypatch):
    """The same app, with the friends-changed hook captured."""
    monkeypatch.setenv("IP_HASH_SECRET", "friends-notify-secret")
    factory, engine = await create_test_db()
    told = Notifications()
    # The announcement is the service's now, so both routers get it from one
    # place rather than each being handed its own.
    friends = FriendService(factory, announce=told)
    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware, session_factory=factory)
    app.include_router(create_auth_router(SqlAlchemyUserRepository(factory), factory))
    app.include_router(create_friends_router(factory, friends))
    app.include_router(
        create_user_blocks_router(factory, BlockService(factory), friends)
    )
    clients: list[AsyncClient] = []

    def new_client() -> AsyncClient:
        client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        clients.append(client)
        return client

    try:
        yield new_client, told
    finally:
        for client in clients:
            await client.aclose()
        await engine.dispose()


async def test_every_change_to_either_list_reaches_both_accounts(wired):
    """Add, accept, decline and unfriend all move both people's lists.

    Including the caller's. The REST answer refreshes the tab that made the
    call and nothing else; every other socket of that account learns about it
    the same way the counterparty does, or not at all.
    """
    new_client, told = wired
    ada_http, bob_http = new_client(), new_client()
    ada = await register(ada_http, "Ada")
    bob = await register(bob_http, "Bob")
    both = sorted([ada["id"], bob["id"]])

    await ada_http.post("/api/users/me/friends", json={"userId": bob["id"]})
    assert sorted(told.told) == both

    told.told.clear()
    await bob_http.post(f"/api/users/me/friends/{ada['id']}/accept")
    assert sorted(told.told) == both

    # Unfriending takes it off the other person's list too.
    told.told.clear()
    await ada_http.delete(f"/api/users/me/friends/{bob['id']}")
    assert sorted(told.told) == both

    # And so does declining a request.
    await ada_http.post("/api/users/me/friends", json={"userId": bob["id"]})
    told.told.clear()
    await bob_http.delete(f"/api/users/me/friends/{ada['id']}")
    assert sorted(told.told) == both


async def test_nothing_is_said_when_nothing_moved(wired):
    """Or the endpoints become a way to ask what a stranger's list holds."""
    new_client, told = wired
    ada_http, bob_http = new_client(), new_client()
    ada = await register(ada_http, "Ada")
    bob = await register(bob_http, "Bob")

    # Removing a friendship that is not there.
    await ada_http.delete(f"/api/users/me/friends/{bob['id']}")
    assert told.told == []

    # A request that was quietly dropped.
    await bob_http.post("/api/users/me/blocks", json={"userId": ada["id"]})
    told.told.clear()
    await ada_http.post("/api/users/me/friends", json={"userId": bob["id"]})
    assert told.told == []


async def test_a_block_that_revokes_a_friendship_tells_both_sides(wired):
    new_client, told = wired
    ada_http, bob_http = new_client(), new_client()
    ada = await register(ada_http, "Ada")
    bob = await register(bob_http, "Bob")
    await ada_http.post("/api/users/me/friends", json={"userId": bob["id"]})
    await bob_http.post(f"/api/users/me/friends/{ada['id']}/accept")

    told.told.clear()
    await bob_http.post("/api/users/me/blocks", json={"userId": ada["id"]})

    # Both, because both lists lost a row - and the blocked side especially,
    # since they did nothing to cause it.
    assert sorted(told.told) == sorted([ada["id"], bob["id"]])


async def test_blocking_a_stranger_says_nothing_at_all(wired):
    """Otherwise a block is a way to ask whether somebody was a friend."""
    new_client, told = wired
    ada_http, bob_http = new_client(), new_client()
    ada = await register(ada_http, "Ada")
    await register(bob_http, "Bob")

    told.told.clear()
    await bob_http.post("/api/users/me/blocks", json={"userId": ada["id"]})

    assert told.told == []


async def test_accepting_says_what_actually_happened(env):
    """The vagueness on POST / protects a stranger; here there is none to protect.

    The caller is answering a request already on their own list, so reporting
    `pending` when the row has just been declined by a block - or was never
    there - leaves a client showing a request that is gone.

    The block is written straight to the table rather than through its own
    endpoint: that endpoint deletes the friendship in the same transaction, so
    going through it leaves nothing to accept and never reaches this branch.
    What is left is the belt-and-braces case - a block that exists while the
    row somehow does - which is exactly what `accept` re-checks for.
    """
    new_client, factory, _ = env
    ada_http, bob_http = new_client(), new_client()
    ada = await register(ada_http, "Ada")
    bob = await register(bob_http, "Bob")

    # Nothing to accept at all.
    nothing = await bob_http.post(f"/api/users/me/friends/{ada['id']}/accept")
    assert nothing.json()["status"] == "unchanged"

    # A real acceptance reads as one.
    await ada_http.post("/api/users/me/friends", json={"userId": bob["id"]})
    accepted = await bob_http.post(f"/api/users/me/friends/{ada['id']}/accept")
    assert accepted.json()["status"] == FriendshipState.ACCEPTED.value

    # And a block that outlived its row turns the answer into a refusal.
    cleo_http = new_client()
    cleo = await register(cleo_http, "Cleo")
    await cleo_http.post("/api/users/me/friends", json={"userId": bob["id"]})
    async with factory() as session:
        async with session.begin():
            session.add(
                UserBlock(
                    blocker_user_id=UUID(bob["id"]),
                    blocked_user_id=UUID(cleo["id"]),
                )
            )
    blocked = await bob_http.post(f"/api/users/me/friends/{cleo['id']}/accept")
    assert blocked.json()["status"] == FriendshipState.DECLINED.value


async def test_a_request_is_still_answered_vaguely(env):
    """The contract that protects a stranger has not moved."""
    new_client, _, _ = env
    ada_http, bob_http = new_client(), new_client()
    ada = await register(ada_http, "Ada")
    bob = await register(bob_http, "Bob")
    await bob_http.post("/api/users/me/blocks", json={"userId": ada["id"]})

    blocked = await ada_http.post("/api/users/me/friends", json={"userId": bob["id"]})
    assert blocked.status_code == 200
    assert blocked.json()["status"] == FriendshipState.PENDING.value


async def test_the_guest_refusal_names_itself_so_a_403_is_not_guessed_at(env):
    """A status is not a reason, and this one is acted on hard.

    The client shows an empty friends list on the strength of it. A suspended
    account is refused with a 403 too, by the middleware and before any of
    this runs - so reading "403" as "this caller is a guest" would wipe a real
    account's lists off the screen.
    """
    new_client, _, _ = env
    guest_http = new_client()
    await name_a_guest(guest_http, "Guesty")

    refused = await guest_http.get("/api/users/me/friends")
    assert refused.status_code == 403
    assert refused.headers.get(ACCOUNT_REQUIRED_HEADER)

    # And a refusal that is *not* about having an account does not carry it,
    # which is the half that makes the header worth reading.
    signed_out = new_client()
    anonymous = await signed_out.get("/api/users/me/friends")
    assert anonymous.status_code == 401
    assert ACCOUNT_REQUIRED_HEADER not in anonymous.headers


async def _inbox(client) -> list[tuple[str, str, str]]:
    """Each friend entry: its kind, whom it names, and where it stands now."""
    return [
        (entry["kind"], entry["person"]["displayName"], entry["state"])
        for entry in (await client.get("/api/inbox")).json()["entries"]
        if entry["kind"] in ("friend_request", "friend_accepted")
    ]


async def test_an_acceptance_is_owed_to_the_asker_however_late_they_read(env):
    """The news survives the asker not being there for it: it is an entry in
    their inbox (#1436, R-FRIEND-14), not a difference between two reads of
    the lists, which a reload during the answer could never see (#724)."""
    new_client, _, _ = env
    ada_http, bob_http = new_client(), new_client()
    ada = await register(ada_http, "AdaOwed")
    await register(bob_http, "BobOwed")
    bob_id = (await bob_http.get("/api/auth/me")).json()["id"]

    await ada_http.post("/api/users/me/friends", json={"userId": bob_id})
    # The asked account hears of the request; the asker is owed nothing yet.
    assert await _inbox(bob_http) == [("friend_request", "AdaOwed", "pending")]
    assert await _inbox(ada_http) == []

    await bob_http.post(f"/api/users/me/friends/{ada['id']}/accept")
    assert await _inbox(ada_http) == [("friend_accepted", "BobOwed", "friends")]
    # Answering the request is reading it.
    [request] = (await bob_http.get("/api/inbox")).json()["entries"]
    assert request["read"] and request["state"] == "friends"


async def test_a_declined_request_is_never_told_to_the_one_who_asked(env):
    """R-FRIEND-04: the asker's inbox says nothing about a refusal - not a
    line, not a count - while the one who declined keeps their own entry,
    which says the request is no longer waiting."""
    new_client, _, _ = env
    ada_http, bob_http = new_client(), new_client()
    ada = await register(ada_http, "AdaAsks")
    await register(bob_http, "BobDeclines")
    bob_id = (await bob_http.get("/api/auth/me")).json()["id"]

    await ada_http.post("/api/users/me/friends", json={"userId": bob_id})
    await bob_http.delete(f"/api/users/me/friends/{ada['id']}")
    assert (await ada_http.get("/api/inbox")).json() == {
        "entries": [], "unreadCount": 0, "next": None, "mustAcknowledge": None, "pendingRole": None,
    }
    assert await _inbox(bob_http) == [("friend_request", "AdaAsks", "gone")]


async def test_a_withdrawn_request_leaves_nothing_to_answer(env):
    """Cancelled before it was answered, the request is about nothing: its
    entry goes rather than offering Accept on something nobody is asking. A
    second request brings it back to the top, unread."""
    new_client, _, _ = env
    ada_http, bob_http = new_client(), new_client()
    await register(ada_http, "AdaWithdraws")
    await register(bob_http, "BobWaits")
    bob_id = (await bob_http.get("/api/auth/me")).json()["id"]

    await ada_http.post("/api/users/me/friends", json={"userId": bob_id})
    await bob_http.post("/api/inbox/read", json={"all": True})
    await ada_http.delete(f"/api/users/me/friends/{bob_id}")
    assert await _inbox(bob_http) == []

    await ada_http.post("/api/users/me/friends", json={"userId": bob_id})
    [entry] = (await bob_http.get("/api/inbox")).json()["entries"]
    assert entry["state"] == "pending" and not entry["read"]


async def test_a_request_answers_alike_whether_it_landed_was_blocked_or_named_nobody(env):
    """R-FRIEND-04: the status code was the disclosure channel - 201 when a
    request landed, 200 when it was dropped by a block, an earlier refusal or
    an id that was never an account (#1002). Now the whole response is one.
    """
    from uuid import uuid4

    new_client = env[0]
    ada, bob, cid = new_client(), new_client(), new_client()
    ada_account = await register(ada, "Ada2")
    bob_account = await register(bob, "Bob2")
    await register(cid, "Cid2")
    # Bob blocks Ada; Cid declines her.
    assert (await bob.post("/api/users/me/blocks", json={"userId": ada_account["id"]})).status_code == 201

    landed = await ada.post("/api/users/me/friends", json={"userId": (await cid.get("/api/auth/me")).json()["id"]})
    blocked = await ada.post("/api/users/me/friends", json={"userId": bob_account["id"]})
    nobody = await ada.post("/api/users/me/friends", json={"userId": str(uuid4())})

    answers = [(r.status_code, r.json()) for r in (landed, blocked, nobody)]
    assert answers == [(200, {"status": "pending"})] * 3, answers
