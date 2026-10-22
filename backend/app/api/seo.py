"""robots.txt and sitemap.xml, the two files crawlers ask for by name (#1458)."""
from __future__ import annotations

import time

from fastapi import APIRouter
from fastapi.responses import Response

from app.deployment import is_production, public_base_url
from app.repositories.interfaces import PromptListRepository
from app.seo import ROBOTS_PATH, SITEMAP_PATH, public_paths, robots_txt, sitemap_xml

# The official lists change only with a deploy, which restarts the process;
# a minute bounds what a moderator hiding a bundled list leaves behind.
SITEMAP_TTL_SECONDS = 60.0
# An hour: neither file changes between deploys, and a crawler that holds an
# old copy a little longer loses nothing.
CRAWLER_FILE_CACHE = {"Cache-Control": "public, max-age=3600"}


def create_seo_router(prompt_lists: PromptListRepository) -> APIRouter:
    router = APIRouter()
    cached: dict[str, tuple[float, str]] = {}

    @router.get(ROBOTS_PATH, include_in_schema=False)
    async def robots():
        """What crawlers may fetch: `app/seo.py` says why it is so little."""
        return Response(
            robots_txt(production=is_production(), base_url=public_base_url()),
            media_type="text/plain",
            headers=CRAWLER_FILE_CACHE,
        )

    @router.get(SITEMAP_PATH, include_in_schema=False)
    async def sitemap():
        """The public pages, as absolute URLs on `PUBLIC_BASE_URL`."""
        base_url = public_base_url()
        hit = cached.get(base_url)
        if hit is None or time.monotonic() - hit[0] > SITEMAP_TTL_SECONDS:
            slugs = [entry.slug for entry in await prompt_lists.list_all()]
            hit = (time.monotonic(), sitemap_xml(base_url=base_url, paths=public_paths(slugs)))
            cached[base_url] = hit
        return Response(hit[1], media_type="application/xml", headers=CRAWLER_FILE_CACHE)

    return router
