"""The privacy notice and the terms read one thing from the server (#1417)."""
from __future__ import annotations

from httpx import ASGITransport, AsyncClient

from app.main import app


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_the_contact_address_is_served_to_anybody(monkeypatch):
    monkeypatch.setenv("CONTACT_ADDRESS", "privacy@sketchy.example.org")
    async with await _client() as client:
        answered = await client.get("/api/legal")
    assert answered.status_code == 200
    assert answered.json() == {"contactAddress": "privacy@sketchy.example.org"}


async def test_a_deployment_without_one_says_so(monkeypatch):
    monkeypatch.delenv("CONTACT_ADDRESS", raising=False)
    async with await _client() as client:
        answered = await client.get("/api/legal")
    assert answered.json() == {"contactAddress": None}
