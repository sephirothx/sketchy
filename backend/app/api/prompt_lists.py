"""Prompt list discovery, and the usage statistics the games feed back into it."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from app.api.serializers import prompt_list_payload, prompt_stats_payload
from app.auth.rate_limit import RateLimiter, client_key
from app.repositories.interfaces import PromptListRepository, PromptStatsSummary

# How many guessers a prompt must have faced before its difficulty means
# anything. `correct_guess_ratio` is 0.0 both for a prompt nobody has ever
# guessed and for one that has never been offered, so ranking without a floor
# fills the "hardest" list with prompts that have simply never been played.
MIN_RATED_GUESSERS = 5

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 25

SORTS = ("hardest", "easiest", "most-picked")

# The bundled lists top out around 600 prompts, and this reads them whole.
# Generous for someone browsing, tight enough to be a poor scraping tool.
stats_limiter = RateLimiter(limit=60, window_seconds=60)


def _is_rated(summary: PromptStatsSummary) -> bool:
    return summary.total_guesser_count >= MIN_RATED_GUESSERS


def _sort_key(sort: str):
    if sort == "most-picked":
        return lambda s: (-s.pick_rate, -s.pick_count, s.text)
    if sort == "easiest":
        return lambda s: (-s.correct_guess_ratio, s.text)
    return lambda s: (s.correct_guess_ratio, s.text)


def create_prompt_list_router(prompt_list_repo: PromptListRepository) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/prompt-lists")
    async def list_prompt_lists():
        return [prompt_list_payload(pl) for pl in await prompt_list_repo.list_all()]

    @router.get("/prompt-lists/{slug}/prompt-stats")
    async def prompt_stats(
        slug: str,
        request: Request,
        sort: str = Query(default="hardest"),
        limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    ):
        """How a list's prompts have actually played, hardest first by default.

        Ranking and slicing happen here rather than in the repository: the
        largest bundled list is a few hundred rows, which is nothing to sort in
        memory, and `get_prompt_stats` is relied on unchanged by several suites.

        Only prompts with enough guessers behind them are ranked. The rest are
        reported as a count rather than dropped silently, because "no prompt in
        this list is rated yet" is the honest answer on a new server and an
        empty list is not.
        """
        if not stats_limiter.check(client_key(request)):
            raise HTTPException(
                status_code=429, detail="Too many requests. Please wait and try again."
            )
        if sort not in SORTS:
            raise HTTPException(status_code=422, detail="Unknown sort.")

        summaries = await prompt_list_repo.get_prompt_stats(slug)
        if not summaries:
            raise HTTPException(status_code=404, detail="No such prompt list.")

        rated = [summary for summary in summaries if _is_rated(summary)]
        rated.sort(key=_sort_key(sort))
        return {
            "slug": slug,
            "sort": sort,
            "minRatedGuessers": MIN_RATED_GUESSERS,
            "ratedCount": len(rated),
            "unratedCount": len(summaries) - len(rated),
            "prompts": [prompt_stats_payload(summary) for summary in rated[:limit]],
        }

    return router
