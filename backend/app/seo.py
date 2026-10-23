"""What search engines are told: robots.txt, the sitemap, and noindex (#1458).

Every URL is served the same single-page shell, so nothing in the page itself
can tell a crawler which URLs are worth indexing. Three things do it instead.

**`robots.txt`** says where not to go and where the sitemap is. In production
it keeps crawlers out of `/room/` and nothing else. A crawler that runs the
page's script would otherwise walk into a live game. Everything else stays
crawlable on purpose. Google renders a public page by running it, which
means fetching `/api/`, and a disallowed `/api/` would leave it rendering the
page's error state instead of its words. A disallowed page is also never
fetched, so its `noindex` is never read, and a linked URL can still be listed
bare. Outside production the answer is `Disallow: /`: a staging host or a
tunnel to a laptop must never be indexed at all.

**`sitemap.xml`** lists the public pages a person could search for, as
absolute URLs on `PUBLIC_BASE_URL`, the one origin the app calls its own. It
lists the official word lists one by one, read from the catalogue. Community
lists stay out until they pass a trust threshold (#1463).

**`X-Robots-Tag: noindex`** goes on every response a search engine should
leave out of its index: a client route `app/client_routes.py` does not mark
indexable, a URL with no page (404), and every `/api/` and `/socket.io/`
answer. It is a header rather than a `<meta>` tag because the shell is one
file shared by every route. Static files (scripts, images, the manifest) are
left alone: they are not pages, and a script must stay fetchable for the
renderer either way.
"""
from __future__ import annotations

from pathlib import PurePosixPath
from xml.sax.saxutils import escape

from app.client_routes import is_indexable_route

ROBOTS_PATH = "/robots.txt"
SITEMAP_PATH = "/sitemap.xml"

# The public pages that are always there, in the order a sitemap lists them.
# `/prompt-lists` itself is left out: without a list named it shows the
# reader's own Standard list (R-STAT-01), so it is a different page for each
# reader and the lists are listed by name instead.
STATIC_PUBLIC_PATHS: tuple[str, ...] = ("/", "/rules", "/solo", "/terms", "/privacy")

NOINDEX = (b"x-robots-tag", b"noindex")


def robots_txt(*, production: bool, base_url: str) -> str:
    """The robots.txt this deployment serves."""
    if not production:
        return "User-agent: *\nDisallow: /\n"
    return (
        "User-agent: *\n"
        "Disallow: /room/\n"
        "\n"
        f"Sitemap: {base_url}{SITEMAP_PATH}\n"
    )


def public_paths(list_slugs: list[str]) -> list[str]:
    """Every path the sitemap lists: the fixed pages, then each official list."""
    return [*STATIC_PUBLIC_PATHS, *(f"/prompt-lists/{slug}" for slug in sorted(list_slugs))]


def sitemap_xml(*, base_url: str, paths: list[str]) -> str:
    """A sitemap of *paths* on *base_url*.

    No `lastmod`: the pages change with a deploy rather than on a date this
    process knows, and search engines ignore a `lastmod` that is not true.
    """
    entries = "".join(
        f"<url><loc>{escape(base_url + path)}</loc></url>" for path in paths
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{entries}</urlset>"
    )


def wants_noindex(path: str, status: int) -> bool:
    """Whether the answer to *path* with *status* should carry noindex.

    Static files keep no header: a path with a file extension is a file,
    never a client route (the SPA mount serves the shell only for paths
    without one).
    """
    if path in (ROBOTS_PATH, SITEMAP_PATH):
        return False
    if path.startswith(("/api/", "/socket.io")) or path == "/api":
        return True
    # The static mount's own test (`SPAStaticFiles`: `Path(path).suffix`),
    # so a client route whose parameter merely starts with a dot -
    # `/settings/.account`, which the client opens - is not taken for a file.
    if PurePosixPath(path).suffix:
        return False
    # A 304 updates the headers of the response it revalidates, so it must
    # say what its 200 said. A redirect is left alone too: some crawlers
    # carry its tags over to where it points, and production's redirect to
    # HTTPS points at the public pages themselves.
    if 300 <= status < 400:
        return False
    return status != 200 or not is_indexable_route(path)


class RobotsTagMiddleware:
    """Add `X-Robots-Tag: noindex` where `wants_noindex` says so.

    Pure ASGI, outermost, so a refusal from any layer below is covered too.
    A header the application already set wins.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "/")

        async def send_with_tag(message) -> None:
            if message["type"] == "http.response.start" and wants_noindex(
                path, message["status"]
            ):
                headers = list(message.get("headers", []))
                if all(name.lower() != NOINDEX[0] for name, _ in headers):
                    headers.append(NOINDEX)
                    message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_tag)
