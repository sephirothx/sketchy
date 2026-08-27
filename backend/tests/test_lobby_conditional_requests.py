"""`GET /api/rooms` answers an unchanged lobby without sending it again.

Every lobby viewer re-fetches this on a four-second timer whether or not
anything moved. gzip shrinks the body; a validator removes it.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app, room_manager


@pytest.fixture(autouse=True)
def _empty_lobby():
    room_manager.rooms.clear()
    yield
    room_manager.rooms.clear()


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_an_unchanged_lobby_is_answered_304_with_no_body():
    room_manager.create_room(name="Studio", is_public=True)
    async with await _client() as client:
        first = await client.get("/api/rooms")
        assert first.status_code == 200
        etag = first.headers["ETag"]
        assert first.json()[0]["name"] == "Studio"

        again = await client.get("/api/rooms", headers={"If-None-Match": etag})
        assert again.status_code == 304
        assert not again.content
        # The validator comes back so the client can keep revalidating.
        assert again.headers["ETag"] == etag


@pytest.mark.asyncio
async def test_a_changed_lobby_gets_a_new_validator_and_a_body():
    room_manager.create_room(name="Studio", is_public=True)
    async with await _client() as client:
        etag = (await client.get("/api/rooms")).headers["ETag"]

        room_manager.create_room(name="Annex", is_public=True)
        changed = await client.get("/api/rooms", headers={"If-None-Match": etag})

        assert changed.status_code == 200
        assert changed.headers["ETag"] != etag
        assert {room["name"] for room in changed.json()} == {"Studio", "Annex"}


@pytest.mark.asyncio
async def test_the_validator_tracks_fields_a_change_counter_would_miss():
    """A hash cannot go stale; a hand-maintained counter can.

    `to_public_summary()` exposes 22 fields. Any of them moving must produce a
    new validator, including ones no membership event touches.
    """
    room = room_manager.create_room(name="Studio", is_public=True)
    async with await _client() as client:
        etag = (await client.get("/api/rooms")).headers["ETag"]

        room.name = "Studio Renamed"
        renamed = await client.get("/api/rooms", headers={"If-None-Match": etag})
        assert renamed.status_code == 200
        assert renamed.headers["ETag"] != etag


@pytest.mark.asyncio
async def test_a_client_that_sends_no_validator_still_gets_the_list():
    """The old client, and the first poll of every new one."""
    room_manager.create_room(name="Studio", is_public=True)
    async with await _client() as client:
        response = await client.get("/api/rooms")
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-cache"
        assert len(response.json()) == 1
