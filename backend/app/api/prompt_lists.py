"""Prompt list discovery, and the usage statistics the games feed back into it."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.serializers import (
    owned_prompt_list_payload,
    prompt_list_payload,
    prompt_stats_payload,
    shared_prompt_list_payload,
)
from app.auth.rate_limit import RateLimiter, client_key
from app.prompt_content import best_supported_prompt_locale, validate_prompt_language
from app.prompts import MAX_PROMPT_LENGTH
from app.repositories.interfaces import (
    PromptListConflictError,
    PromptListEntryInput,
    PromptListMutationError,
    PromptListNotFoundError,
    PromptListRepository,
    PromptStatsSummary,
    UserData,
    UserRepository,
)
from app.repositories.sqlalchemy import MAX_PROMPTS_PER_OWNED_LIST
from app.domain_values import HintMode, ScoringMode

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
share_limiter = RateLimiter(limit=30, window_seconds=60)


class PromptEntryRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", populate_by_name=True)

    concept_id: str | None = Field(default=None, alias="conceptId", max_length=36)
    prompt: str = Field(min_length=1, max_length=MAX_PROMPT_LENGTH)
    aliases: list[str] = Field(default_factory=list, max_length=20)


class CreateOwnedPromptListRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", populate_by_name=True)

    name: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=255)
    language: str = Field(default="en", min_length=2, max_length=16)
    visibility: Literal["private", "unlisted"] = "private"
    prompts: list[PromptEntryRequest] = Field(
        min_length=1, max_length=MAX_PROMPTS_PER_OWNED_LIST
    )


class UpdateOwnedPromptListRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", populate_by_name=True)

    expected_version: int = Field(alias="expectedVersion", ge=1)
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=255)
    visibility: Literal["private", "unlisted"] = "private"
    prompts: list[PromptEntryRequest] = Field(
        min_length=1, max_length=MAX_PROMPTS_PER_OWNED_LIST
    )


class SharedPromptListRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    code: str = Field(min_length=8, max_length=24)


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


def create_prompt_list_router(
    prompt_list_repo: PromptListRepository,
    user_repo: UserRepository | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api")

    async def require_registered(request: Request) -> UserData:
        user_id = getattr(request.state, "user_id", None)
        user = await user_repo.get_by_id(user_id) if user_repo and user_id else None
        if user is None:
            raise HTTPException(status_code=401, detail="Sign in first.")
        if user.is_anonymous:
            raise HTTPException(
                status_code=403,
                detail="Create an account to save reusable prompt lists.",
            )
        return user

    def entry_inputs(
        prompts: list[PromptEntryRequest],
    ) -> tuple[PromptListEntryInput, ...]:
        return tuple(
            PromptListEntryInput(
                concept_id=prompt.concept_id,
                answer=prompt.prompt,
                aliases=tuple(prompt.aliases),
            )
            for prompt in prompts
        )

    def mutation_error(error: PromptListMutationError) -> HTTPException:
        if isinstance(error, PromptListNotFoundError):
            return HTTPException(status_code=404, detail=str(error))
        if isinstance(error, PromptListConflictError):
            return HTTPException(status_code=409, detail=str(error))
        return HTTPException(status_code=422, detail=str(error))

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

    @router.get("/prompt-lists/mine")
    async def list_my_prompt_lists(request: Request):
        user = await require_registered(request)
        return [
            owned_prompt_list_payload(prompt_list)
            for prompt_list in await prompt_list_repo.list_owned(user.id)
        ]

    @router.post(
        "/prompt-lists/mine",
        status_code=status.HTTP_201_CREATED,
    )
    async def create_my_prompt_list(
        body: CreateOwnedPromptListRequest, request: Request
    ):
        user = await require_registered(request)
        try:
            created = await prompt_list_repo.create_owned(
                user.id,
                name=body.name,
                description=body.description,
                language=body.language,
                visibility=body.visibility,
                prompts=entry_inputs(body.prompts),
            )
        except PromptListMutationError as error:
            raise mutation_error(error) from error
        return owned_prompt_list_payload(created)

    @router.get("/prompt-lists/mine/{prompt_list_id}")
    async def get_my_prompt_list(prompt_list_id: str, request: Request):
        user = await require_registered(request)
        prompt_list = await prompt_list_repo.get_owned(user.id, prompt_list_id)
        if prompt_list is None:
            raise HTTPException(status_code=404, detail="Prompt list not found.")
        return owned_prompt_list_payload(prompt_list)

    @router.put("/prompt-lists/mine/{prompt_list_id}")
    async def update_my_prompt_list(
        prompt_list_id: str,
        body: UpdateOwnedPromptListRequest,
        request: Request,
    ):
        user = await require_registered(request)
        try:
            updated = await prompt_list_repo.update_owned(
                user.id,
                prompt_list_id,
                expected_version=body.expected_version,
                name=body.name,
                description=body.description,
                visibility=body.visibility,
                prompts=entry_inputs(body.prompts),
            )
        except PromptListMutationError as error:
            raise mutation_error(error) from error
        return owned_prompt_list_payload(updated)

    @router.delete(
        "/prompt-lists/mine/{prompt_list_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    async def delete_my_prompt_list(prompt_list_id: str, request: Request):
        user = await require_registered(request)
        if not await prompt_list_repo.delete_owned(user.id, prompt_list_id):
            raise HTTPException(status_code=404, detail="Prompt list not found.")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post("/prompt-lists/shared")
    async def resolve_shared_prompt_list(
        body: SharedPromptListRequest, request: Request
    ):
        if not share_limiter.check(client_key(request)):
            raise HTTPException(
                status_code=429, detail="Too many attempts. Please wait and try again."
            )
        prompt_list = await prompt_list_repo.get_shared(body.code)
        if prompt_list is None:
            raise HTTPException(status_code=404, detail="No shared prompt list found.")
        return shared_prompt_list_payload(prompt_list)

    @router.get("/prompt-lists/{slug}/prompt-stats")
    async def prompt_stats(
        slug: str,
        request: Request,
        sort: str = Query(default="hardest"),
        limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
        from_time: datetime | None = Query(default=None, alias="from"),
        to_time: datetime | None = Query(default=None, alias="to"),
        scoring_mode: ScoringMode | None = Query(default=None, alias="scoringMode"),
        hint_mode: HintMode | None = Query(default=None, alias="hintMode"),
    ):
        """How a list's prompts have actually played, hardest first by default.

        Fact filtering and aggregation happen in the repository. Ranking and
        slicing stay here: the largest bundled list is a few hundred rows,
        which is small enough to sort in memory after aggregation.

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
        for field_name, value in (("from", from_time), ("to", to_time)):
            if value is not None and value.tzinfo is None:
                raise HTTPException(
                    status_code=422,
                    detail=f"{field_name} must include a timezone.",
                )
        if from_time is not None:
            from_time = from_time.astimezone(timezone.utc)
        if to_time is not None:
            to_time = to_time.astimezone(timezone.utc)
        if from_time is not None and to_time is not None and from_time >= to_time:
            raise HTTPException(status_code=422, detail="from must be earlier than to.")

        summaries = await prompt_list_repo.get_prompt_stats(
            slug,
            from_time=from_time,
            to_time=to_time,
            scoring_mode=scoring_mode.value if scoring_mode else None,
            hint_mode=hint_mode.value if hint_mode else None,
        )
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
