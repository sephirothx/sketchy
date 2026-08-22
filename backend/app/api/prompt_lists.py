"""Prompt list discovery, and the usage statistics the games feed back into it."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from app.api.serializers import prompt_list_payload, prompt_stats_payload
from app.auth.rate_limit import RateLimiter, client_key
from app.prompt_content import best_supported_prompt_locale, validate_prompt_language
from app.repositories.interfaces import PromptListRepository, PromptStatsSummary

# How many guessers a prompt must have faced before its difficulty means
# anything. `correct_guess_ratio` is 0.0 both for a prompt nobody has ever
# guessed and for one that has never been offered, so ranking without a floor
# fills the "hardest" list with prompts that have simply never been played.
MIN_RATED_GUESSERS = 5

# The whole list, because the page shows the whole list. The largest bundled
# one is under 600 prompts of at most 64 characters, so the response is small
# even at the ceiling; the cap is here to bound a list someone builds later.
MAX_PAGE_SIZE = 2000
DEFAULT_PAGE_SIZE = 2000

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


def _ordered(summaries: list[PromptStatsSummary], sort: str) -> list[PromptStatsSummary]:
    """Rated prompts in the requested order, then the rest alphabetically.

    Unrated prompts are listed rather than dropped - a player looking up a
    prompt should find it - but they are never ranked among the measured ones.
    Their ratios are zero for want of data, which would otherwise plant every
    prompt nobody has drawn yet at the top of "hardest".
    """
    rated = sorted((s for s in summaries if _is_rated(s)), key=_sort_key(sort))
    unrated = sorted((s for s in summaries if not _is_rated(s)), key=lambda s: s.text)
    return rated + unrated


def create_prompt_list_router(prompt_list_repo: PromptListRepository) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/prompt-lists")
    async def list_prompt_lists(
        request: Request,
        language: str | None = Query(default=None),
    ):
        """List catalogue entries, localized for the caller when copy exists."""
        if language is not None:
            try:
                language = validate_prompt_language(language)
            except ValueError as error:
                raise HTTPException(status_code=422, detail=str(error)) from error
        locale = best_supported_prompt_locale(request.headers.get("accept-language"))
        return [
            prompt_list_payload(prompt_list)
            for prompt_list in await prompt_list_repo.list_all(
                language=language, locale=locale
            )
        ]

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

        Every prompt in the list comes back, so a player can look one up. Only
        those with enough guessers behind them are ranked; the rest follow,
        alphabetically, flagged as unrated. Their ratios read as zero for want
        of data, and ranking on that would fill "hardest" with prompts nobody
        has drawn yet.
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

        ordered = _ordered(summaries, sort)
        rated_count = sum(1 for summary in summaries if _is_rated(summary))
        return {
            "slug": slug,
            "sort": sort,
            "minRatedGuessers": MIN_RATED_GUESSERS,
            "ratedCount": rated_count,
            "unratedCount": len(summaries) - rated_count,
            "prompts": [
                {**prompt_stats_payload(summary), "isRated": _is_rated(summary)}
                for summary in ordered[:limit]
            ],
        }

    return router
