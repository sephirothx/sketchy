"""One guest name per person online (R-ACCT-09).

A guest's name was unique against usernames and nothing else, so two guests
could sit in the lobby as the same "asd". It is now unique among the people
online - and only among them, because guest accounts are never deleted and a
name taken for good would use up every common name.
"""
from __future__ import annotations

import contextlib

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.auth.middleware import SessionAuthMiddleware
from app.auth.routes import create_auth_router
from app.repositories.sqlalchemy import SqlAlchemyUserRepository
from app.rooms import RoomManager
from app.services.guest_names import online_guest_holding
from app.services.presence import PresenceIdentity, PresenceRegistry, build_snapshot

from tests.dbfixtures import create_test_db


@contextlib.asynccontextmanager
async def build_site():
    factory, engine = await create_test_db()
    # A clock the test moves, so "gone for longer than a reload" is a step.
    now = [0.0]
    presence = PresenceRegistry(clock=lambda: now[0])
    presence.test_now = now
    repo = SqlAlchemyUserRepository(factory)
    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware, session_factory=factory)
    app.include_router(create_auth_router(repo, factory, presence=presence))
    transport = ASGITransport(app=app)
    try:
        yield transport, presence, repo
    finally:
        await engine.dispose()


def browser(transport) -> AsyncClient:
    """A visitor with a cookie jar of their own."""
    return AsyncClient(transport=transport, base_url="http://test")


async def guest(transport, presence, name: str, *, online: bool = True):
    """A guest who chose `name`, with a socket open when `online`.

    The client is used unopened (httpx opens it on first request) and closed
    with the transport, so a test does not wrap it in `async with` again."""
    client = browser(transport)
    chosen = await client.post("/api/auth/display-name", json={"displayName": name})
    assert chosen.status_code == 200, chosen.text
    user_id = chosen.json()["id"]
    if online:
        presence.note_socket_opened(f"sid-{user_id}", user_id)
    return client, user_id


async def test_a_new_guest_cannot_choose_a_name_somebody_online_is_using():
    async with build_site() as (transport, presence, _):
        first, _ = await guest(transport, presence, "asd")
        async with browser(transport) as second:
            taken = await second.post("/api/auth/display-name", json={"displayName": "ASD"})

            assert taken.status_code == 409
            assert "already playing under that name" in taken.json()["detail"]
            # Nothing was created for the refused choice.
            assert (await second.get("/api/auth/me")).json() is None
            available = await second.get("/api/auth/nickname-available", params={"name": "Asd"})
            assert available.json()["available"] is False


async def test_the_name_comes_free_once_its_holder_has_been_gone_longer_than_a_reload():
    async with build_site() as (transport, presence, _):
        first, first_id = await guest(transport, presence, "asd")
        async with browser(transport) as second:
            presence.note_socket_closed(f"sid-{first_id}")

            # A reload's worth of absence is not leaving.
            held = await second.post("/api/auth/display-name", json={"displayName": "asd"})
            assert held.status_code == 409

            presence.test_now[0] += 60
            chosen = await second.post("/api/auth/display-name", json={"displayName": "asd"})
            assert chosen.status_code == 200


async def test_renaming_into_a_held_name_is_refused_but_keeping_your_own_is_not():
    async with build_site() as (transport, presence, _):
        holder, _ = await guest(transport, presence, "asd")
        renamer, _ = await guest(transport, presence, "qwe")
        refused = await renamer.post("/api/auth/display-name", json={"displayName": "asd"})
        assert refused.status_code == 409
        # The holder changing only the case of their own name is fine.
        recased = await holder.post("/api/auth/display-name", json={"displayName": "ASD"})
        assert recased.status_code == 200


async def test_a_guest_who_comes_back_to_a_taken_name_is_told_and_the_first_is_not():
    async with build_site() as (transport, presence, repo):
        # Chose "asd" while nobody else had it, then went away.
        returning, returning_id = await guest(transport, presence, "asd", online=False)
        # Somebody else took it meanwhile, and is still here.
        holder, holder_id = await guest(transport, presence, "asd")
        assert (await returning.get("/api/auth/me")).json()["nameInUse"] is True
        assert (await holder.get("/api/auth/me")).json()["nameInUse"] is False

        # Coming online second does not change who arrived first.
        presence.note_socket_opened(f"sid-{returning_id}", returning_id)
        assert (await returning.get("/api/auth/me")).json()["nameInUse"] is True
        assert (await holder.get("/api/auth/me")).json()["nameInUse"] is False

        # Keeping the name is refused while the first holder is here...
        kept = await returning.post("/api/auth/display-name", json={"displayName": "asd"})
        assert kept.status_code == 409
        # ...and choosing another settles it.
        renamed = await returning.post("/api/auth/display-name", json={"displayName": "asd2"})
        assert renamed.status_code == 200
        assert (await returning.get("/api/auth/me")).json()["nameInUse"] is False

        # When the first holder has left, the name is free again.
        presence.note_socket_closed(f"sid-{holder_id}")
        presence.test_now[0] += 60
        assert await online_guest_holding(
            "asd", claimant_id=None, registry=presence, user_repo=repo, choosing=True
        ) is None


async def test_a_registered_player_with_that_display_name_holds_nothing():
    """Only guests hold a guest name; an account's name is its username, and
    usernames were already refused to guests."""
    async with build_site() as (transport, presence, repo):
        async with browser(transport) as registered:
            made = await registered.post(
                "/api/auth/register", json={"username": "Stefano", "password": "a-good-password"}
            )
            assert made.status_code == 200
            user_id = made.json()["id"]
            presence.note_socket_opened("sid-registered", user_id)
            assert await online_guest_holding(
                "Stefano", claimant_id=None, registry=presence, user_repo=repo, choosing=True
            ) is None


async def test_arrival_order_decides_who_holds_a_shared_name():
    async with build_site() as (transport, presence, repo):
        first, first_id = await guest(transport, presence, "zed")
        second, second_id = await guest(transport, presence, "other")
        # Force the shared name directly, as a return would leave it.
        await repo.update_profile(second_id, display_name="zed")

        async def holder(claimant):
            return await online_guest_holding(
                "zed", claimant_id=claimant, registry=presence, user_repo=repo, choosing=False
            )

        assert await holder(first_id) is None
        assert await holder(second_id) == first_id
        # Leaving for longer than a reload and coming back puts the first at
        # the end of the line.
        presence.note_socket_closed(f"sid-{first_id}")
        presence.test_now[0] += 60
        presence.note_socket_opened(f"sid-{first_id}-again", first_id)
        assert await holder(second_id) is None
        assert await holder(first_id) == second_id


def test_the_online_list_shows_one_guest_per_name_the_first_to_arrive():
    registry = PresenceRegistry()
    for user_id in ("first", "registered", "second"):
        registry.note_socket_opened(f"sid-{user_id}", user_id)
    known = {
        "first": PresenceIdentity("first", "asd", None, True),
        "registered": PresenceIdentity("registered", "Asd", "#4f9", False),
        "second": PresenceIdentity("second", "ASD", None, True),
    }

    snapshot = build_snapshot(registry, RoomManager(), known, revision=1)

    assert sorted(entry.user_id for entry in snapshot.entries) == ["first", "registered"]
    assert snapshot.online_count == 3


def test_a_reload_keeps_a_guests_place_in_the_arrival_order():
    """The page asks who it is before its socket reopens, so a place lost on
    every close handed the name to whoever had arrived second."""
    now = [0.0]
    registry = PresenceRegistry(clock=lambda: now[0])
    registry.note_socket_opened("sid-first", "first")
    registry.note_socket_opened("sid-second", "second")
    first_arrival = registry.arrival_of("first")

    registry.note_socket_closed("sid-first")
    now[0] += 2
    assert registry.arrival_of("first") == first_arrival
    registry.note_socket_opened("sid-first-again", "first")
    assert registry.online_user_ids() == ["first", "second"]

    # Gone for longer than a reload: back of the line.
    registry.note_socket_closed("sid-first-again")
    now[0] += 60
    assert registry.arrival_of("first") is None
    registry.note_socket_opened("sid-first-later", "first")
    assert registry.online_user_ids() == ["second", "first"]


# --- from the presence cache (#900) -------------------------------------------


@contextlib.asynccontextmanager
async def counted_site():
    """`build_site`, plus the identity cache the lobby list keeps and a count
    of the statements the database is sent."""
    from sqlalchemy import event

    from app.services.presence import PresenceIdentityCache

    factory, engine = await create_test_db()
    now = [0.0]
    presence = PresenceRegistry(clock=lambda: now[0])
    presence.test_now = now
    repo = SqlAlchemyUserRepository(factory)
    identities = PresenceIdentityCache(repo)
    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware, session_factory=factory)
    app.include_router(
        create_auth_router(
            repo,
            factory,
            presence=presence,
            presence_identities=identities,
            # As app.main wires it: every name write forgets the cached row.
            on_profile_changed=identities.invalidate,
        )
    )
    statements: list[str] = []

    def count(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", count)
    try:
        yield ASGITransport(app=app), presence, repo, identities, statements
    finally:
        await engine.dispose()


async def test_a_guest_line_with_a_warm_cache_sends_the_database_nothing():
    """The lobby chat path asks this on every guest line. Every online id is
    in the cache the lobby list already keeps, so the answer - held or not -
    costs no statement at all."""
    async with counted_site() as (transport, presence, repo, identities, statements):
        holder, holder_id = await guest(transport, presence, "asd")
        speaker, speaker_id = await guest(transport, presence, "qwe")
        for index in range(50):
            _, other = await guest(transport, presence, f"crowd{index}")
            await identities.warm(other)
        await identities.warm(holder_id)
        await identities.warm(speaker_id)

        statements.clear()
        assert await online_guest_holding(
            "qwe", claimant_id=speaker_id, registry=presence, user_repo=repo,
            choosing=False, identities=identities,
        ) is None
        assert await online_guest_holding(
            "ASD", claimant_id=None, registry=presence, user_repo=repo,
            choosing=True, identities=identities,
        ) == holder_id
        assert statements == []


async def test_an_id_the_cache_cannot_answer_is_asked_of_the_database():
    """A miss is not an answer: an account online but not yet warmed, or
    evicted, is still checked - by a statement naming only the misses."""
    async with counted_site() as (transport, presence, repo, identities, statements):
        _, holder_id = await guest(transport, presence, "asd")
        _, other_id = await guest(transport, presence, "qwe")
        await identities.warm(other_id)

        statements.clear()
        assert await online_guest_holding(
            "asd", claimant_id=None, registry=presence, user_repo=repo,
            choosing=True, identities=identities,
        ) == holder_id
        assert len(statements) == 1


async def test_a_departed_holder_keeps_the_name_through_the_grace_from_the_cache():
    """R-ACCT-09's reload allowance holds when the answer comes from memory."""
    async with counted_site() as (transport, presence, repo, identities, statements):
        _, holder_id = await guest(transport, presence, "asd")
        await identities.warm(holder_id)
        presence.note_socket_closed(f"sid-{holder_id}")
        statements.clear()

        async def held():
            return await online_guest_holding(
                "asd", claimant_id=None, registry=presence, user_repo=repo,
                choosing=True, identities=identities,
            )

        assert await held() == holder_id
        presence.test_now[0] += 60
        assert await held() is None
        assert statements == []


async def test_a_renamed_guest_is_read_again_rather_than_answered_from_the_cache():
    """The cache is only as good as its invalidation: the display-name route
    forgets the renamed account, so the old name comes free at once."""
    async with counted_site() as (transport, presence, repo, identities, _):
        client, holder_id = await guest(transport, presence, "asd")
        await identities.warm(holder_id)
        renamed = await client.post("/api/auth/display-name", json={"displayName": "zxc"})
        assert renamed.status_code == 200
        assert await online_guest_holding(
            "asd", claimant_id=None, registry=presence, user_repo=repo,
            choosing=True, identities=identities,
        ) is None
