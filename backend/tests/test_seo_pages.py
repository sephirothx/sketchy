"""Each public page's own head in the served HTML (#1459, R-SEO-04, R-SEO-05)."""
from __future__ import annotations

import asyncio

import gzip
import json
import re
from pathlib import Path

import pytest
from fastapi import FastAPI

from app.main import configure_frontend
from app.security_headers import _InlineScripts
from app.seo_pages import PageHead, SeoPages, page_heads, render_page
from tests.test_static_delivery import request

SHELL = (Path(__file__).resolve().parents[2] / "frontend" / "index.html").read_text(
    encoding="utf-8"
)
BASE = "https://sketchy.example.org"


def pages_file(**lists) -> dict:
    head = lambda title: {"title": f"{title} · Sketchy", "description": f"About {title}."}  # noqa: E731
    return {
        "version": 1,
        "locales": {
            "en": {
                "tagline": "Free multiplayer drawing & guessing game",
                "contactPending": "[no address yet]",
                "pages": {
                    "/": {
                        "title": "Sketchy – Free multiplayer drawing & guessing game",
                        "description": "A free online drawing and guessing game.",
                    },
                    "/rules": {**head("Rules"), "body": '<div class="prerender"><h1>Rules</h1></div>'},
                    "/privacy": {
                        **head("Privacy notice"),
                        "body": '<div class="prerender"><p>Write to {contact}.</p></div>',
                    },
                    "/solo": head("Solo"),
                    "/terms": head("Terms"),
                },
                "promptLists": {
                    slug: head(name)
                    for slug, name in (lists or {"english_standard": "English — Standard"}).items()
                },
                "standardList": "english_standard",
            }
        },
    }


def scripts(text: str) -> list[str]:
    parser = _InlineScripts()
    parser.feed(text)
    return parser.bodies


def test_a_page_says_what_it_is_before_any_script_runs():
    page = render_page(
        SHELL,
        PageHead(title="Rules · Sketchy", description="How it stays fun.", canonical_path="/rules", lang="en"),
        base_url=BASE,
    )
    assert "<title>Rules · Sketchy</title>" in page
    assert '<meta name="description" content="How it stays fun." />' in page
    assert '<meta property="og:title" content="Rules · Sketchy" />' in page
    assert '<meta property="og:description" content="How it stays fun." />' in page
    assert f'<link rel="canonical" href="{BASE}/rules" />' in page
    assert f'<meta property="og:url" content="{BASE}/rules" />' in page
    assert f'<meta property="og:image" content="{BASE}/og-image.png" />' in page
    assert "application/ld+json" not in page
    # One of each: a second description would be a page saying two things.
    assert page.count('name="description"') == 1
    assert page.count("<title>") == 1


def test_the_scripts_the_policy_admits_are_untouched_and_the_prefetch_stays_first():
    page = render_page(
        SHELL,
        PageHead(title="T", description="D", canonical_path="/", lang="en", home=True),
        base_url=BASE,
    )
    executable = [body for body in scripts(page) if '"@context"' not in body]
    assert executable == scripts(SHELL)
    assert executable[0].lstrip().startswith("try {\n        var sketchyAbort")


def test_the_home_page_names_the_site_in_structured_data():
    page = render_page(
        SHELL,
        PageHead(
            title="Sketchy – Free multiplayer drawing & guessing game",
            description="</script><script>alert(1)</script>",
            canonical_path="/",
            lang="en",
            home=True,
        ),
        base_url=BASE,
    )
    block = re.search(r'<script type="application/ld\+json">(.*?)</script>', page, re.S)
    assert block is not None
    # Nothing in a value can close the element early.
    assert "</script" not in block.group(1).lower()
    data = json.loads(block.group(1))
    kinds = {node["@type"]: node for node in data["@graph"]}
    assert kinds["WebSite"]["name"] == "Sketchy"
    assert kinds["WebSite"]["url"] == f"{BASE}/"
    assert kinds["WebApplication"]["applicationCategory"] == "GameApplication"
    assert kinds["WebApplication"]["offers"]["price"] == "0"
    assert "<title>Sketchy – Free multiplayer drawing &amp; guessing game</title>" in page


def test_text_is_escaped_where_it_lands():
    page = render_page(
        SHELL,
        PageHead(title='A "quoted" <list>', description="Tom & Jerry", canonical_path="/x", lang="en"),
        base_url=BASE,
    )
    assert "<title>A \"quoted\" &lt;list&gt;</title>" in page
    assert 'content="A &quot;quoted&quot; &lt;list&gt;"' in page
    assert 'content="Tom &amp; Jerry"' in page


def test_a_shell_missing_a_tag_is_refused_rather_than_half_written():
    with pytest.raises(ValueError):
        render_page(
            SHELL.replace('<meta name="description"', '<meta name="summary"'),
            PageHead(title="T", description="D", canonical_path="/", lang="en"),
            base_url=BASE,
        )


def test_every_list_the_build_knows_gets_a_head():
    # Whether one is served is asked when it is (review of #1459): a
    # moderator can hide or restore a list while the process runs.
    heads = page_heads(pages_file(english_standard="English — Standard", retired="Retired"))
    assert heads["/prompt-lists/english_standard"].list_slug == "english_standard"
    assert heads["/prompt-lists/retired"].list_slug == "retired"
    # The bare catalogue is the reader's Standard list, under that list's URL.
    assert heads["/prompt-lists"].canonical_path == "/prompt-lists/english_standard"
    assert heads["/prompt-lists"].list_slug == "english_standard"
    assert heads["/"].home and not heads["/rules"].home
    assert heads["/rules"].list_slug is None


async def read_again(app, pages: SeoPages) -> None:
    """Have a request start the catalogue's read, and let it land: it runs in
    the background, so no page waits for the database."""
    await request(app, "/rules")
    if pages.reading is not None:
        await pages.reading


async def test_a_list_follows_the_catalogue_while_the_process_runs(tmp_path: Path):
    (tmp_path / "index.html").write_text(SHELL, encoding="utf-8")
    (tmp_path / "seo").mkdir()
    (tmp_path / "seo" / "pages.json").write_text(
        json.dumps(pages_file(english_standard="English — Standard", german_standard="Deutsch")),
        encoding="utf-8",
    )
    catalogue = {"english_standard", "german_standard"}

    async def reread() -> set[str]:
        return set(catalogue)

    pages = SeoPages(ttl_seconds=0)
    pages.load(tmp_path, list_slugs=set(catalogue), base_url=BASE, reread=reread)
    app = FastAPI()
    configure_frontend(app, tmp_path, pages)

    # A moderator hides German: no page of its own, and noindex.
    catalogue.discard("german_standard")
    await read_again(app, pages)
    status, headers, body = await request(app, "/prompt-lists/german_standard")
    assert status == 200 and headers["x-robots-tag"] == "noindex"
    assert "<title>Sketchy</title>" in body.decode()
    # And restores it: the page it had, findable again.
    catalogue.add("german_standard")
    await read_again(app, pages)
    status, headers, body = await request(app, "/prompt-lists/german_standard")
    assert "x-robots-tag" not in headers
    assert "<title>Deutsch · Sketchy</title>" in body.decode()
    # The bare catalogue goes with the Standard list it shows.
    catalogue.discard("english_standard")
    await read_again(app, pages)
    _, headers, body = await request(app, "/prompt-lists")
    assert "<title>Sketchy</title>" in body.decode()


async def test_the_catalogue_is_read_at_most_once_a_minute(tmp_path: Path):
    (tmp_path / "index.html").write_text(SHELL, encoding="utf-8")
    (tmp_path / "seo").mkdir()
    (tmp_path / "seo" / "pages.json").write_text(json.dumps(pages_file()), encoding="utf-8")
    reads = 0

    async def reread() -> set[str]:
        nonlocal reads
        reads += 1
        return {"english_standard"}

    pages = SeoPages()
    pages.load(tmp_path, list_slugs={"english_standard"}, base_url=BASE, reread=reread)
    app = FastAPI()
    configure_frontend(app, tmp_path, pages)
    for _ in range(5):
        await request(app, "/prompt-lists/english_standard")
    # Just loaded: the startup read stands for the minute.
    assert reads == 0
    pages.read_at -= pages.ttl_seconds + 1
    for _ in range(5):
        await request(app, "/rules")
    if pages.reading is not None:
        await pages.reading
    # One read for the burst, and it ran beside the requests.
    assert reads == 1
    # Assets never ask.
    pages.read_at -= pages.ttl_seconds + 1
    await request(app, "/favicon.svg")
    assert reads == 1


@pytest.fixture
def served(tmp_path: Path):
    (tmp_path / "index.html").write_text(SHELL, encoding="utf-8")
    (tmp_path / "seo").mkdir()
    (tmp_path / "seo" / "pages.json").write_text(json.dumps(pages_file()), encoding="utf-8")
    pages = SeoPages()
    # `added_since` is served but the build wrote no head for it.
    pages.load(tmp_path, list_slugs={"english_standard", "added_since"}, base_url=BASE)
    assert pages.loaded
    app = FastAPI()
    configure_frontend(app, tmp_path, pages)
    return app


@pytest.mark.parametrize(
    "path,title",
    [
        ("/", "Sketchy – Free multiplayer drawing &amp; guessing game"),
        ("/rules", "Rules · Sketchy"),
        ("/Rules/", "Rules · Sketchy"),
        ("/prompt-lists/english_standard", "English — Standard · Sketchy"),
        ("/prompt-lists", "English — Standard · Sketchy"),
    ],
)
async def test_each_public_page_is_served_its_own_head(served, path, title):
    status, headers, body = await request(served, path)
    assert status == 200
    assert headers["content-type"].startswith("text/html")
    assert headers["cache-control"] == "no-cache"
    assert f"<title>{title}</title>" in body.decode()


async def test_a_page_is_served_gzipped_and_revalidates(served):
    status, headers, body = await request(served, "/rules", headers={"Accept-Encoding": "gzip, br"})
    assert status == 200
    assert headers["content-encoding"] == "gzip"
    assert headers["vary"] == "Accept-Encoding"
    assert "<title>Rules · Sketchy</title>" in gzip.decompress(body).decode()
    again, revalidated, empty = await request(
        served,
        "/rules",
        headers={"Accept-Encoding": "gzip", "If-None-Match": headers["etag"]},
    )
    assert again == 304 and empty == b""
    assert revalidated["etag"] == headers["etag"]
    # The identity copy has a validator of its own: two bodies, two names.
    _, identity, _ = await request(served, "/rules")
    assert identity["etag"] != headers["etag"]
    assert "content-encoding" not in identity


async def test_head_answers_without_a_body(served):
    status, headers, body = await request(served, "/rules", method="HEAD")
    assert status == 200 and body == b""
    assert int(headers["content-length"]) > 0


async def test_an_unknown_list_keeps_the_shell_and_is_told_noindex(served):
    status, headers, body = await request(served, "/prompt-lists/no_such_list")
    assert status == 200
    assert headers["x-robots-tag"] == "noindex"
    assert "<title>Sketchy</title>" in body.decode()


async def test_a_room_keeps_the_generic_card(served):
    status, _, body = await request(served, "/room/ABC123")
    assert status == 200
    assert "<title>Sketchy</title>" in body.decode()
    assert 'rel="canonical"' not in body.decode()


async def test_the_build_s_pages_file_is_not_served_and_the_shell_file_is_noindex(served):
    status, _, _ = await request(served, "/seo/pages.json")
    assert status == 404
    _, headers, _ = await request(served, "/index.html")
    assert headers["x-robots-tag"] == "noindex"


def test_a_build_without_the_pages_file_serves_the_plain_shell(tmp_path: Path):
    (tmp_path / "index.html").write_text(SHELL, encoding="utf-8")
    pages = SeoPages()
    pages.load(tmp_path, list_slugs=set(), base_url=BASE)
    assert not pages.loaded and pages.get("/") is None


def test_a_pages_file_it_cannot_read_serves_the_plain_shell(tmp_path: Path):
    (tmp_path / "index.html").write_text(SHELL, encoding="utf-8")
    (tmp_path / "seo").mkdir()
    (tmp_path / "seo" / "pages.json").write_text('{"version": 99}', encoding="utf-8")
    pages = SeoPages()
    pages.load(tmp_path, list_slugs=set(), base_url=BASE)
    assert not pages.loaded


async def test_a_proxy_s_weakened_validator_still_revalidates(served):
    _, headers, _ = await request(served, "/rules", headers={"Accept-Encoding": "gzip"})
    answered, _, _ = await request(
        served,
        "/rules",
        headers={"Accept-Encoding": "gzip", "If-None-Match": f"W/{headers['etag']}"},
    )
    assert answered == 304


async def test_a_public_page_answers_only_get_and_head(served):
    status, _, _ = await request(served, "/rules", method="POST")
    assert status == 405


async def test_a_list_slug_is_matched_as_written(served):
    # The page asks the server for the slug exactly as typed, and there is
    # no `English_Standard`: it must not be served the real list's head.
    status, headers, body = await request(served, "/prompt-lists/English_Standard")
    assert status == 200
    assert headers["x-robots-tag"] == "noindex"
    assert "<title>Sketchy</title>" in body.decode()
    # The rest of the path is matched without case, as the router does.
    _, _, body = await request(served, "/Prompt-Lists/english_standard")
    assert "<title>English — Standard · Sketchy</title>" in body.decode()


async def test_a_served_list_without_a_head_stays_findable(served):
    # It is in the sitemap: noindex would contradict it.
    status, headers, body = await request(served, "/prompt-lists/added_since")
    assert status == 200
    assert "x-robots-tag" not in headers
    assert "<title>Sketchy</title>" in body.decode()


async def test_a_list_hidden_at_startup_gets_its_page_back_when_restored(tmp_path: Path):
    (tmp_path / "index.html").write_text(SHELL, encoding="utf-8")
    (tmp_path / "seo").mkdir()
    (tmp_path / "seo" / "pages.json").write_text(
        json.dumps(pages_file(english_standard="English — Standard", german_standard="Deutsch")),
        encoding="utf-8",
    )
    catalogue = {"english_standard"}

    async def reread() -> set[str]:
        return set(catalogue)

    pages = SeoPages(ttl_seconds=0)
    pages.load(tmp_path, list_slugs=set(catalogue), base_url=BASE, reread=reread)
    app = FastAPI()
    configure_frontend(app, tmp_path, pages)
    _, headers, _ = await request(app, "/prompt-lists/german_standard")
    assert headers["x-robots-tag"] == "noindex"
    catalogue.add("german_standard")
    await read_again(app, pages)
    _, headers, body = await request(app, "/prompt-lists/german_standard")
    assert "x-robots-tag" not in headers
    assert "<title>Deutsch · Sketchy</title>" in body.decode()


async def test_a_failed_read_keeps_the_last_answer(tmp_path: Path):
    (tmp_path / "index.html").write_text(SHELL, encoding="utf-8")
    (tmp_path / "seo").mkdir()
    (tmp_path / "seo" / "pages.json").write_text(json.dumps(pages_file()), encoding="utf-8")

    async def reread() -> set[str]:
        raise ConnectionError("the database is down")

    pages = SeoPages(ttl_seconds=0)
    pages.load(tmp_path, list_slugs={"english_standard"}, base_url=BASE, reread=reread)
    app = FastAPI()
    configure_frontend(app, tmp_path, pages)
    await read_again(app, pages)
    _, headers, body = await request(app, "/prompt-lists/english_standard")
    assert "x-robots-tag" not in headers
    assert "<title>English — Standard · Sketchy</title>" in body.decode()


async def test_a_read_that_hangs_is_given_up(tmp_path: Path):
    (tmp_path / "index.html").write_text(SHELL, encoding="utf-8")
    (tmp_path / "seo").mkdir()
    (tmp_path / "seo" / "pages.json").write_text(json.dumps(pages_file()), encoding="utf-8")

    async def reread() -> set[str]:
        await asyncio.Event().wait()  # a dead connection, never answering
        return set()

    pages = SeoPages(ttl_seconds=0.01)
    pages.load(tmp_path, list_slugs={"english_standard"}, base_url=BASE, reread=reread)
    pages.read_at -= 1
    pages.follow_catalogue()
    await pages.reading
    # Given up, the last answer kept, and free to start the next read.
    assert pages.reading is None
    assert pages.list_slugs == {"english_standard"}


async def test_a_page_with_readable_text_carries_it_inside_root(served):
    _, _, body = await request(served, "/rules")
    assert '<div id="root"><div class="prerender"><h1>Rules</h1></div></div>' in body.decode()
    # A page without any keeps the empty root React mounts into.
    _, _, body = await request(served, "/prompt-lists/english_standard")
    assert '<div id="root"></div>' in body.decode()


def test_the_contact_address_is_filled_in_and_escaped():
    heads = page_heads(pages_file(), contact='op"<x>@example.org')
    assert heads["/privacy"].body == (
        '<div class="prerender"><p>Write to '
        '<a href="mailto:op&quot;&lt;x&gt;@example.org">op&quot;&lt;x&gt;@example.org</a>.</p></div>'
    )
    # Without one, the words the page shows then.
    heads = page_heads(pages_file(), contact=None)
    assert heads["/privacy"].body == '<div class="prerender"><p>Write to [no address yet].</p></div>'


@pytest.fixture
def two_languages(tmp_path: Path):
    pages = pages_file(english_standard="English — Standard", german_standard="Deutsch — Standard")
    german = json.loads(json.dumps(pages["locales"]["en"]))
    for head in [*german["pages"].values(), *german["promptLists"].values()]:
        head["title"] = "DE " + head["title"]
    german["standardList"] = "german_standard"
    pages["locales"]["de"] = german
    (tmp_path / "index.html").write_text(SHELL, encoding="utf-8")
    (tmp_path / "seo").mkdir()
    (tmp_path / "seo" / "pages.json").write_text(json.dumps(pages), encoding="utf-8")
    store = SeoPages()
    store.load(tmp_path, list_slugs={"english_standard", "german_standard"}, base_url=BASE)
    app = FastAPI()
    configure_frontend(app, tmp_path, store)
    return app


async def test_each_language_has_its_own_address_and_names_the_others(two_languages):
    _, _, body = await request(two_languages, "/de/rules")
    page = body.decode()
    assert "<title>DE Rules · Sketchy</title>" in page
    assert '<html lang="de">' in page
    assert f'<link rel="canonical" href="{BASE}/de/rules" />' in page
    assert f'<link rel="alternate" hreflang="de" href="{BASE}/de/rules" />' in page
    assert f'<link rel="alternate" hreflang="en" href="{BASE}/rules" />' in page
    assert f'<link rel="alternate" hreflang="x-default" href="{BASE}/rules" />' in page
    _, _, body = await request(two_languages, "/de")
    assert f'<link rel="canonical" href="{BASE}/de" />' in body.decode()
    # The prefix is matched without case, as the client matches it.
    _, _, body = await request(two_languages, "/DE/Rules/")
    assert "<title>DE Rules · Sketchy</title>" in body.decode()


async def test_the_bare_catalogue_points_at_the_language_s_own_standard_list(two_languages):
    _, _, body = await request(two_languages, "/de/prompt-lists")
    page = body.decode()
    assert f'<link rel="canonical" href="{BASE}/de/prompt-lists/german_standard" />' in page
    assert 'hreflang=' not in page


async def test_english_has_one_address(two_languages):
    status, headers, _ = await request(two_languages, "/en/rules")
    assert status == 301 and headers["location"] == "/rules"
    status, headers, _ = await request(two_languages, "/en")
    assert status == 301 and headers["location"] == "/"
    status, headers, _ = await request(two_languages, "/en//")
    assert status == 301 and headers["location"] == "/"


async def test_only_a_public_page_has_an_address_per_language(two_languages):
    status, _, _ = await request(two_languages, "/de/room/ABC123")
    assert status == 404
    status, headers, _ = await request(two_languages, "/de/prompt-lists/no_such_list")
    assert status == 200 and headers["x-robots-tag"] == "noindex"


async def test_a_hidden_list_leaves_every_language_s_address(tmp_path: Path):
    pages = pages_file(english_standard="English — Standard", german_standard="Deutsch — Standard")
    pages["locales"]["de"] = {**json.loads(json.dumps(pages["locales"]["en"])), "standardList": "german_standard"}
    (tmp_path / "index.html").write_text(SHELL, encoding="utf-8")
    (tmp_path / "seo").mkdir()
    (tmp_path / "seo" / "pages.json").write_text(json.dumps(pages), encoding="utf-8")
    catalogue = {"english_standard", "german_standard"}

    async def reread() -> set[str]:
        return set(catalogue)

    store = SeoPages(ttl_seconds=0)
    store.load(tmp_path, list_slugs=set(catalogue), base_url=BASE, reread=reread)
    app = FastAPI()
    configure_frontend(app, tmp_path, store)
    catalogue.discard("german_standard")
    for path in ("/de/prompt-lists/german_standard", "/prompt-lists/german_standard"):
        _, headers, body = await request(app, path)
        assert headers["x-robots-tag"] == "noindex", path
        assert "<title>Sketchy</title>" in body.decode(), path
    # The German bare catalogue shows German's Standard list, so it goes too.
    _, _, body = await request(app, "/de/prompt-lists")
    assert "<title>Sketchy</title>" in body.decode()
