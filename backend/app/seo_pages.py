"""Each public page's own head in the HTML the server sends (#1459).

Every URL is served one shell, so a crawler that runs no script - and every
link preview, which never does - read the same title and description on every
page. The build writes each public page's title and description, in every
interface language, from the catalogues the app reads
(`frontend/scripts/seo-pages.mjs` → `dist/seo/pages.json`). At startup this
puts them into a copy of the shell per page, beside what only the deployment
knows: the canonical URL and `og:url` on `PUBLIC_BASE_URL`, an absolute
`og:image`, and for the home page the structured data a search engine reads
to name the site.

**Once, at startup, then from memory.** The pages change only with a deploy,
and a deploy restarts the process. Each is gzipped once here and served with
an `ETag` of its own, so nothing is compressed on the loop (#978) and an
unchanged page revalidates to a 304. No Brotli: the server has no encoder,
and the shell's own Brotli copy cannot be reused for bytes the build never
saw. The rest of the shell is byte for byte what the build wrote, so the
inline scripts keep the hashes the Content-Security-Policy admits them by and
the `/api/auth/me` prefetch keeps its place (#983); the structured data is a
`<script type="application/ld+json">`, a data block no policy applies to.

**A page that is not known is not invented.** An official list the build did
not write a head for, or one the catalogue no longer serves, keeps the plain
shell, and `/prompt-lists/<anything else>` is told `noindex`
(`SPAStaticFiles`). Which lists the catalogue serves is read again, in the
background, at most once a minute, since a moderator can hide or restore one
while the process runs: every list the build knows is assembled, and served
only while the catalogue serves it. A room's invite link keeps the generic card on purpose:
a room's name in a preview is not something to publish.
"""
from __future__ import annotations

import asyncio
import gzip
import hashlib
import html
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

PAGES_FILE = Path("seo") / "pages.json"
PAGES_FILE_VERSION = 1
# The language the unprefixed URLs are read in. Other languages get their own
# URLs (#1462); until then this is the only one assembled.
DEFAULT_LOCALE = "en"


@dataclass(frozen=True)
class PageHead:
    """What one page says about itself before any script runs."""

    title: str
    description: str
    canonical_path: str
    lang: str
    home: bool = False
    # The official list the page is about, which the catalogue must still
    # serve for the page to be served (#1459 review), or None.
    list_slug: str | None = None


@dataclass(frozen=True)
class AssembledPage:
    identity: bytes
    gzipped: bytes
    etag: str

    @property
    def gzip_etag(self) -> str:
        return f'{self.etag[:-1]}-gz"'


def _attribute(value: str) -> str:
    return html.escape(value, quote=True)


def _structured_data(head: PageHead, base_url: str) -> str:
    """The site's name and what it is, as schema.org reads them.

    `<` is escaped so no value can close the script element early.
    """
    url = f"{base_url}/"
    graph = {
        "@context": "https://schema.org",
        "@graph": [
            {"@type": "WebSite", "name": "Sketchy", "url": url, "inLanguage": head.lang},
            {
                "@type": "WebApplication",
                "name": "Sketchy",
                "url": url,
                "description": head.description,
                "applicationCategory": "GameApplication",
                "operatingSystem": "Any",
                "inLanguage": head.lang,
                "offers": {"@type": "Offer", "price": "0", "priceCurrency": "EUR"},
            },
        ],
    }
    body = json.dumps(graph, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    return f'<script type="application/ld+json">{body}</script>'


def _replace_once(pattern: str, replacement: str, text: str) -> str:
    result, count = re.subn(pattern, lambda _: replacement, text, flags=re.IGNORECASE)
    if count != 1:
        raise ValueError(f"the shell has {count} matches for {pattern!r}, not one")
    return result


def render_page(shell: str, head: PageHead, *, base_url: str) -> str:
    """*shell* with *head* in it.

    Each tag is replaced in place and must be there exactly once: a shell
    whose markup moved fails here, at startup, rather than serving a page
    that silently says two different things.
    """
    canonical = f"{base_url}{head.canonical_path}"
    title = _attribute(head.title)
    description = _attribute(head.description)
    page = _replace_once(r'<html lang="[^"]*">', f'<html lang="{_attribute(head.lang)}">', shell)
    page = _replace_once(
        r'<meta name="description" content="[^"]*"\s*/?>',
        f'<meta name="description" content="{description}" />',
        page,
    )
    page = _replace_once(
        r'<meta property="og:title" content="[^"]*"\s*/?>',
        f'<meta property="og:title" content="{title}" />',
        page,
    )
    page = _replace_once(
        r'<meta property="og:description" content="[^"]*"\s*/?>',
        f'<meta property="og:description" content="{description}" />',
        page,
    )
    # Root-relative in the shell, which knows no origin; absolute here, as
    # Open Graph asks for, now that one is known.
    image = re.search(r'<meta property="og:image" content="(/[^"]*)"', page)
    if image is None:
        raise ValueError("the shell has no root-relative og:image")
    page = _replace_once(
        r'<meta property="og:image" content="/[^"]*"\s*/?>',
        f'<meta property="og:image" content="{_attribute(base_url)}{image.group(1)}" />',
        page,
    )
    added = [
        f'<link rel="canonical" href="{_attribute(canonical)}" />',
        f'<meta property="og:url" content="{_attribute(canonical)}" />',
    ]
    if head.home:
        added.append(_structured_data(head, base_url))
    page = _replace_once(
        r"<title>[^<]*</title>",
        f"<title>{html.escape(head.title, quote=False)}</title>\n    " + "\n    ".join(added),
        page,
    )
    return page


def assemble(text: str) -> AssembledPage:
    identity = text.encode("utf-8")
    digest = hashlib.blake2b(identity, digest_size=16).hexdigest()
    # mtime=0, so the same page always compresses to the same bytes.
    return AssembledPage(identity, gzip.compress(identity, compresslevel=9, mtime=0), f'"{digest}"')


def page_heads(pages: dict, *, locale: str = DEFAULT_LOCALE) -> dict[str, PageHead]:
    """Every public page's head for *locale*, keyed by its path.

    Every list the build wrote a head for is included, whether or not the
    catalogue serves it now: a moderator can hide or restore an official list
    while the process runs, so which of them is served is asked when a page
    is (`SeoPages.get`). The bare `/prompt-lists` is the reader's Standard
    list (R-STAT-01) under that list's canonical URL.
    """
    entry = pages["locales"][locale]
    heads: dict[str, PageHead] = {}
    for path, head in entry["pages"].items():
        heads[path] = PageHead(
            title=head["title"],
            description=head["description"],
            canonical_path=path,
            lang=locale,
            home=path == "/",
        )
    for slug, head in entry["promptLists"].items():
        heads[f"/prompt-lists/{slug}"] = PageHead(
            title=head["title"],
            description=head["description"],
            canonical_path=f"/prompt-lists/{slug}",
            lang=locale,
            list_slug=slug,
        )
    standard = entry.get("standardList")
    if standard and f"/prompt-lists/{standard}" in heads:
        heads["/prompt-lists"] = heads[f"/prompt-lists/{standard}"]
    return heads


LIST_PREFIX = "/prompt-lists/"


def page_key(path: str) -> str:
    """How a request path finds its page: as react-router matches it, with
    case and a trailing slash ignored - except in a list's slug, which the
    page asks the server for exactly as written, so `English_Standard` is a
    list that does not exist rather than a second copy of one that does."""
    trimmed = path.rstrip("/") or "/"
    if trimmed.lower().startswith(LIST_PREFIX) and trimmed.count("/") == 2:
        return LIST_PREFIX + trimmed[len(LIST_PREFIX):]
    return trimmed.lower()


# How long one read of which official lists the catalogue serves stands: the
# sitemap's minute (`api/seo.py`), so a list a moderator hides or restores
# leaves or rejoins its page and the sitemap together.
VISIBILITY_TTL_SECONDS = 60.0


@dataclass
class SeoPages:
    """The assembled pages, filled once at startup, and which official lists
    the catalogue serves, read again at most once a minute."""

    pages: dict[str, AssembledPage] = field(default_factory=dict)
    loaded: bool = False
    list_slugs: frozenset[str] = frozenset()
    # The official list each list page needs the catalogue to serve.
    needs: dict[str, str] = field(default_factory=dict)
    # Reads the slugs the catalogue serves now; None reads nothing again.
    reread: Callable[[], Awaitable[set[str]]] | None = None
    ttl_seconds: float = VISIBILITY_TTL_SECONDS
    read_at: float = 0.0
    # The read in flight, held so it is not collected mid-way.
    reading: asyncio.Task | None = field(default=None, repr=False)

    def follow_catalogue(self) -> None:
        """Read the catalogue's official lists again, in the background, once
        the last read is older than `ttl_seconds`. No page waits for the
        database - the answer reaches the requests after it - and one read
        runs at a time, so a burst of requests makes one query. A read that
        fails keeps the last answer."""
        if (
            self.reread is None
            or self.reading is not None
            or time.monotonic() - self.read_at < self.ttl_seconds
        ):
            return
        self.read_at = time.monotonic()
        self.reading = asyncio.get_running_loop().create_task(self._read(self.reread))

    async def _read(self, reread: Callable[[], Awaitable[set[str]]]) -> None:
        try:
            # Bounded, so a read stuck on a dead connection cannot stop the
            # following for good: the next request after it starts another.
            self.list_slugs = frozenset(await asyncio.wait_for(reread(), self.ttl_seconds or None))
        except Exception:
            logger.warning("Public pages keep the last list of official lists", exc_info=True)
        finally:
            self.reading = None

    def get(self, path: str) -> AssembledPage | None:
        key = page_key(path)
        needed = self.needs.get(key)
        if needed is not None and needed not in self.list_slugs:
            # A list a moderator hid gets no page of its own, nor does the
            # bare catalogue that would show it (#1459 review).
            return None
        return self.pages.get(key)

    def is_unknown_list(self, path: str) -> bool:
        """Whether *path* names an official list the catalogue does not serve.

        Asked of the catalogue, not of the pages: a list the build wrote no
        head for is still a real page, served the plain shell, and must stay
        indexable - it is in the sitemap."""
        key = page_key(path)
        return key.startswith(LIST_PREFIX) and key[len(LIST_PREFIX):] not in self.list_slugs

    def load(
        self,
        dist: Path,
        *,
        list_slugs: set[str],
        base_url: str,
        reread: Callable[[], Awaitable[set[str]]] | None = None,
    ) -> None:
        """Assemble every page from the build in *dist*.

        A checkout without a build, or a build without the pages file, serves
        the plain shell as before; a pages file this code cannot read is the
        same, and says so in the log rather than taking the site down over a
        title.
        """
        try:
            shell = (dist / "index.html").read_text(encoding="utf-8")
            pages = json.loads((dist / PAGES_FILE).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        try:
            if pages.get("version") != PAGES_FILE_VERSION:
                raise ValueError(f"pages file version {pages.get('version')!r}")
            heads = page_heads(pages)
            assembled = {
                page_key(path): assemble(render_page(shell, head, base_url=base_url))
                for path, head in heads.items()
            }
        except (KeyError, TypeError, ValueError):
            logger.exception("Public pages keep the plain shell: %s could not be used", PAGES_FILE)
            return
        headless = sorted(slug for slug in list_slugs if f"{LIST_PREFIX}{slug}" not in heads)
        if headless:
            # A list added without a build that knows it: served, findable,
            # with the generic head until the next build.
            logger.warning("Official lists served without a head of their own: %s", ", ".join(headless))
        self.pages = assembled
        self.needs = {
            page_key(path): head.list_slug for path, head in heads.items() if head.list_slug
        }
        self.list_slugs = frozenset(list_slugs)
        self.reread = reread
        self.read_at = time.monotonic()
        self.loaded = True
