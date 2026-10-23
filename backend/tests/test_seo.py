"""What search engines are told: robots.txt, the sitemap and noindex (#1458).

R-SEO-01..R-SEO-03.
"""
from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.seo import create_seo_router
from app.client_routes import CLIENT_ROUTE_TABLE, CLIENT_ROUTES, INDEXABLE_ROUTES
from app.db.models import generate_uuid
from app.main import configure_frontend
from app.repositories.interfaces import BundledPromptDefinition
from app.repositories.sqlalchemy import SqlAlchemyPromptListRepository
from app.seo import RobotsTagMiddleware, robots_txt, wants_noindex

from tests.dbfixtures import create_test_db
from tests.test_static_delivery import request

SITEMAP = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


def test_every_client_route_is_classified_once():
    # The table is the classification: a route cannot be in it without a
    # verdict, and one listed twice would carry two.
    routes = [route for route, _ in CLIENT_ROUTE_TABLE]
    assert len(routes) == len(set(routes))
    assert all(isinstance(indexable, bool) for _, indexable in CLIENT_ROUTE_TABLE)
    assert set(INDEXABLE_ROUTES) <= set(CLIENT_ROUTES)


def test_only_the_public_pages_are_indexable():
    assert set(INDEXABLE_ROUTES) == {
        "/",
        "/rules",
        "/privacy",
        "/terms",
        "/prompt-lists",
        "/prompt-lists/:slug",
        "/solo",
    }


def test_production_keeps_crawlers_out_of_rooms_and_points_at_the_sitemap():
    text = robots_txt(production=True, base_url="https://sketchy.example.org")
    assert text.splitlines() == [
        "User-agent: *",
        "Disallow: /room/",
        "",
        "Sitemap: https://sketchy.example.org/sitemap.xml",
    ]


def test_production_leaves_the_api_crawlable_so_public_pages_render():
    # A disallowed /api/ would leave Google rendering every public page's
    # error state, since the page reads its words through it.
    text = robots_txt(production=True, base_url="https://sketchy.example.org")
    assert "/api" not in text


def test_anything_but_production_is_closed_to_crawlers():
    assert robots_txt(production=False, base_url="http://localhost:8000") == (
        "User-agent: *\nDisallow: /\n"
    )


@pytest.mark.parametrize(
    "path,status,expected",
    [
        ("/", 200, False),
        ("/rules", 200, False),
        ("/rules/", 200, False),
        ("/Rules", 200, False),
        ("/terms", 304, False),
        ("/prompt-lists/english_standard", 200, False),
        ("/solo", 200, False),
        ("/room/ABC123", 200, True),
        ("/create", 200, True),
        ("/settings/appearance", 200, True),
        # A dot at the start of a parameter is no file extension: the client
        # opens it, so it keeps the route's policy (review of #1505).
        ("/settings/.account", 200, True),
        ("/profile/.x", 200, True),
        ("/gallery/0193f0c1-2b3d-7e00-8a11-6f9c0d2e4b5a", 200, True),
        ("/community-lists", 200, True),
        ("/profile", 200, True),
        ("/reset-password", 200, True),
        ("/no-such-page", 404, True),
        ("/rules", 500, True),
        ("/rules", 308, False),
        ("/room/ABC123", 302, False),
        ("/api/rooms", 200, True),
        ("/api", 404, True),
        ("/socket.io/", 200, True),
        ("/robots.txt", 200, False),
        ("/sitemap.xml", 200, False),
        ("/assets/app-AbCdEf12.js", 200, False),
        ("/og-image.png", 200, False),
    ],
)
def test_noindex_goes_on_everything_but_public_pages_and_files(path, status, expected):
    assert wants_noindex(path, status) is expected


@pytest.fixture
def indexed_app(tmp_path: Path):
    (tmp_path / "index.html").write_bytes(b"<!doctype html><html><body>shell</body></html>")
    (tmp_path / "favicon.svg").write_text("<svg></svg>", encoding="utf-8")
    app = FastAPI()

    @app.get("/api/thing")
    async def thing():
        return {"ok": True}

    configure_frontend(app, tmp_path)
    return RobotsTagMiddleware(app)


@pytest.mark.parametrize(
    "path,status,tagged",
    [
        ("/", 200, False),
        ("/rules", 200, False),
        ("/room/ABC123", 200, True),
        ("/settings", 200, True),
        ("/settings/.account", 200, True),
        ("/not-a-page", 404, True),
        ("/api/thing", 200, True),
        ("/favicon.svg", 200, False),
    ],
)
async def test_the_header_is_what_a_crawler_sees(indexed_app, path, status, tagged):
    answered, headers, _ = await request(indexed_app, path)
    assert answered == status
    assert (headers.get("x-robots-tag") == "noindex") is tagged


async def test_a_revalidated_public_page_stays_indexable(indexed_app):
    # A 304 replaces the headers of the copy it revalidates, so a noindex on
    # it would take an indexed page out of the index.
    _, headers, _ = await request(indexed_app, "/")
    answered, revalidated, _ = await request(
        indexed_app, "/", headers={"If-None-Match": headers["etag"]}
    )
    assert answered == 304
    assert "x-robots-tag" not in revalidated


@pytest_asyncio.fixture
async def crawler_files():
    session_factory, engine = await create_test_db()
    prompts = SqlAlchemyPromptListRepository(session_factory)
    for slug, language in (("english_standard", "en"), ("german_standard", "de")):
        await prompts.upsert_bundled(
            slug=slug,
            name=slug,
            description="",
            language=language,
            prompts=[BundledPromptDefinition(str(generate_uuid()), "apple")],
            version=1,
        )
    app = FastAPI()
    app.include_router(create_seo_router(prompts))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http, prompts
    await engine.dispose()


async def test_robots_txt_answers_for_the_deployment(crawler_files, monkeypatch):
    http, _ = crawler_files
    monkeypatch.setenv("SKETCHY_ENV", "production")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://sketchy.example.org/")
    answered = await http.get("/robots.txt")
    assert answered.status_code == 200
    assert answered.headers["content-type"].startswith("text/plain")
    assert "Sitemap: https://sketchy.example.org/sitemap.xml" in answered.text

    monkeypatch.setenv("SKETCHY_ENV", "test")
    assert (await http.get("/robots.txt")).text == "User-agent: *\nDisallow: /\n"


async def test_the_sitemap_lists_the_public_pages_and_every_official_list(
    crawler_files, monkeypatch
):
    http, _ = crawler_files
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://sketchy.example.org")
    answered = await http.get("/sitemap.xml")
    assert answered.status_code == 200
    assert answered.headers["content-type"].startswith("application/xml")
    # No cache may keep a hidden list listed longer than this process does.
    assert answered.headers["cache-control"] == "public, max-age=60"
    locations = [
        element.text
        for element in ElementTree.fromstring(answered.content).iter(f"{SITEMAP}loc")
    ]
    assert locations == [
        "https://sketchy.example.org/",
        "https://sketchy.example.org/rules",
        "https://sketchy.example.org/solo",
        "https://sketchy.example.org/terms",
        "https://sketchy.example.org/privacy",
        "https://sketchy.example.org/prompt-lists/english_standard",
        "https://sketchy.example.org/prompt-lists/german_standard",
    ]


async def test_head_is_answered_like_get(crawler_files):
    http, _ = crawler_files
    for path in ("/robots.txt", "/sitemap.xml"):
        answered = await http.head(path)
        assert answered.status_code == 200, path


async def test_the_real_application_is_wired_for_crawlers():
    # The middleware must be around everything, which an app a test assembles
    # itself does not show. (The routes' place before the static mount at "/"
    # shows only with a build present; the end-to-end suite has one.)
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        robots = await http.get("/robots.txt")
        assert robots.status_code == 200
        assert robots.text.startswith("User-agent: *")
        assert "x-robots-tag" not in robots.headers
        health = await http.get("/api/health")
        assert health.headers["x-robots-tag"] == "noindex"
        handshake = await http.get("/socket.io/?EIO=4&transport=polling")
        assert handshake.headers["x-robots-tag"] == "noindex"
