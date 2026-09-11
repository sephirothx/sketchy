"""Prompt list discovery, and the usage statistics the games feed back into it."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.errors import Refusal
from app.refusals import ErrorCode
from app.api.serializers import (
    community_prompt_list_detail_payload,
    community_prompt_list_payload,
    owned_prompt_list_payload,
    prompt_list_payload,
    prompt_stats_payload,
    shared_prompt_list_payload,
)
from app.auth.audit import audit_coordinates
from app.auth.rate_limit import RateLimiter, client_key
from app.db.models import User, UserWarning
from uuid import UUID
from app.prompt_content import (
    LIST_TAG_VOCABULARY,
    MAX_LIST_TAGS,
    UnknownListTag,
    clean_list_tags,
    best_supported_prompt_locale,
    validate_prompt_language,
)
from app.prompts import MAX_PROMPT_LENGTH
from app.repositories.interfaces import (
    AuditStamp,
    PromptListConflictError,
    PromptListEntryInput,
    PromptListMutationError,
    PromptListNotFoundError,
    PromptListRepository,
    PromptStatsSummary,
    UserData,
    UserRepository,
)
from app.repositories.sqlalchemy import (
    MAX_COMMUNITY_PAGE,
    MAX_PROMPTS_PER_OWNED_LIST,
)
from app.services.publication_policy import read_publication_review
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
COMMUNITY_SORTS = ("stars", "newest")

# The bundled lists top out around 600 prompts, and this reads them whole.
# Generous for someone browsing, tight enough to be a poor scraping tool.
stats_limiter = RateLimiter(limit=60, window_seconds=60)
share_limiter = RateLimiter(limit=30, window_seconds=60)
# Publishing is a deliberate act somebody takes a handful of times, and the
# thing it costs an abuser is the account (R-LIST-12) rather than the request.
# The limit is here so that account cannot be spent quickly.
publish_limiter = RateLimiter(limit=10, window_seconds=600)
# Browsing is cheap and ordinary; this is here so the catalogue is a poor way
# to enumerate every published list quickly, the way the stats limiter is.
community_limiter = RateLimiter(limit=120, window_seconds=60)
# A preview reads a whole list, up to 500 prompts, so it is priced like
# the stats page rather than like a listing.
preview_limiter = RateLimiter(limit=60, window_seconds=60)
# Starring is one click, and a person browsing does it a handful of times a
# session. The limit is what stops one account walking the catalogue.
star_limiter = RateLimiter(limit=60, window_seconds=60)

PUBLISHED_EVENT = "prompt_list.published"
UNPUBLISHED_EVENT = "prompt_list.unpublished"


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
    # Bounded here so an oversized list is refused before it reaches a
    # transaction; the vocabulary check that names the offending tag lives in
    # `prompt_content.clean_list_tags`, because naming it is the point.
    tags: list[str] = Field(default_factory=list, max_length=MAX_LIST_TAGS)


class UpdateOwnedPromptListRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", populate_by_name=True)

    expected_version: int = Field(alias="expectedVersion", ge=1)
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=255)
    visibility: Literal["private", "unlisted"] = "private"
    prompts: list[PromptEntryRequest] = Field(
        min_length=1, max_length=MAX_PROMPTS_PER_OWNED_LIST
    )
    tags: list[str] = Field(default_factory=list, max_length=MAX_LIST_TAGS)


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
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api")

    async def require_registered(request: Request) -> UserData:
        user_id = getattr(request.state, "user_id", None)
        user = await user_repo.get_by_id(user_id) if user_repo and user_id else None
        if user is None:
            raise Refusal(401, ErrorCode.SIGN_IN_REQUIRED, "Sign in first.")
        if user.is_anonymous:
            raise Refusal(
                403,
                ErrorCode.ACCOUNT_REQUIRED,
                "Create an account to save reusable prompt lists.",
                params={"action": "prompt_lists"},
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

    def mutation_error(error: PromptListMutationError) -> Refusal:
        if isinstance(error, PromptListNotFoundError):
            return Refusal(404, ErrorCode.PROMPT_LIST_NOT_FOUND, str(error))
        if isinstance(error, PromptListConflictError):
            return Refusal(409, ErrorCode.PROMPT_LIST_CONFLICT, str(error))
        return Refusal(
            422,
            error.code or ErrorCode.PROMPT_LIST_INVALID,
            str(error),
            params=error.params,
        )

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
                raise Refusal(422, ErrorCode.PROMPT_LIST_INVALID, str(error)) from error
        locale = best_supported_prompt_locale(request.headers.get("accept-language"))
        return [
            prompt_list_payload(prompt_list)
            for prompt_list in await prompt_list_repo.list_all(
                language=language, locale=locale
            )
        ]

    @router.get("/prompt-tags")
    async def list_prompt_tags():
        """The vocabulary a list owner may choose from (R-LIST-18).

        Served rather than duplicated in the client: a client guessing at the
        set would show tags a save then refuses. Unauthenticated, because it
        is a fixed vocabulary and the community catalogue filters by it.
        """
        return {
            "maxPerList": MAX_LIST_TAGS,
            "tags": [{"slug": slug, "name": name} for slug, name in LIST_TAG_VOCABULARY],
        }

    @router.get("/prompt-lists/community")
    async def list_community_prompt_lists(
        request: Request,
        language: str | None = Query(default=None),
        tag: list[str] = Query(default_factory=list),
        sort: str = Query(default="stars"),
        starred: bool = Query(default=False),
        limit: int = Query(default=24, ge=1, le=MAX_COMMUNITY_PAGE),
        cursor: str | None = Query(default=None, max_length=32),
    ):
        """Published lists, separate from the official catalogue (R-LIST-14).

        Its own route rather than a facet on `/api/prompt-lists`, so that
        R-LIST-09 keeps holding without a filter having to be right: nobody
        reading the official catalogue has to ask whether a row was written by
        a stranger.

        Open to a signed-out caller. A published list is public by its owner's
        deliberate act, and requiring an account to *look* would make the
        catalogue useless as a link somebody shares.
        """
        if not community_limiter.check(client_key(request)):
            raise Refusal(
                429,
                ErrorCode.TOO_MANY_REQUESTS,
                "Too many requests. Please wait and try again.",
            )
        if language is not None:
            try:
                language = validate_prompt_language(language)
            except ValueError as error:
                raise Refusal(422, ErrorCode.PROMPT_LIST_INVALID, str(error)) from error
        if sort not in COMMUNITY_SORTS:
            raise Refusal(422, ErrorCode.UNKNOWN_SORT, "Unknown sort.", field="sort")
        try:
            tags = clean_list_tags(tag)
        except UnknownListTag as error:
            # Refused rather than ignored: dropping a filter answers a
            # different question than the one asked (R-LIST-18).
            raise Refusal(
                422,
                ErrorCode.UNKNOWN_PROMPT_TAG,
                str(error),
                field="tag",
                params={"tag": error.tag},
            ) from error
        except ValueError as error:
            raise Refusal(
                422, ErrorCode.PROMPT_LIST_INVALID, str(error), field="tag"
            ) from error
        # A guest holds a session and a user id, and cannot star anything
        # (R-LIST-12). Passing that id through answered `starredByMe: false`,
        # which is the registered answer - it says "you have not starred this"
        # to somebody who cannot, and invites a control that would 403. Only a
        # registered account is a star requester; everyone else reads null.
        requester = await _star_requester(request)
        if starred and requester is None:
            raise Refusal(
                403,
                ErrorCode.ACCOUNT_REQUIRED,
                "Create an account to star prompt lists.",
                params={"action": "stars"},
            )
        page = await prompt_list_repo.list_community(
            language=language,
            tags=tags,
            sort=sort,
            limit=limit,
            cursor=cursor,
            requesting_user_id=requester,
            starred_only=starred,
        )
        return {
            "lists": [
                community_prompt_list_payload(prompt_list)
                for prompt_list in page.lists
            ],
            "nextCursor": page.next_cursor,
        }

    @router.get("/prompt-lists/community/{prompt_list_id}")
    async def read_community_prompt_list(prompt_list_id: str, request: Request):
        """Every prompt in a published list (R-LIST-19).

        Choosing a list to play or to copy from a name and a count is choosing
        blind, and playing one reveals its prompts anyway - so the contents are
        readable by anyone the listing is readable by, signed out included.
        Rate-limited, because this is the one route that returns a list whole.
        """
        if not preview_limiter.check(client_key(request)):
            raise Refusal(
                429,
                ErrorCode.TOO_MANY_REQUESTS,
                "Too many requests. Please wait and try again.",
            )
        detail = await prompt_list_repo.get_community(
            prompt_list_id, requesting_user_id=await _star_requester(request)
        )
        if detail is None:
            raise Refusal(
                404, ErrorCode.PROMPT_LIST_NOT_FOUND, "Prompt list not found."
            )
        return community_prompt_list_detail_payload(detail)

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
                tags=body.tags,
            )
        except PromptListMutationError as error:
            raise mutation_error(error) from error
        return owned_prompt_list_payload(created)

    @router.get("/prompt-lists/mine/{prompt_list_id}")
    async def get_my_prompt_list(prompt_list_id: str, request: Request):
        user = await require_registered(request)
        prompt_list = await prompt_list_repo.get_owned(user.id, prompt_list_id)
        if prompt_list is None:
            raise Refusal(404, ErrorCode.PROMPT_LIST_NOT_FOUND, "Prompt list not found.")
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
                tags=body.tags,
            )
        except PromptListMutationError as error:
            raise mutation_error(error) from error
        return owned_prompt_list_payload(updated)

    async def _star_requester(request: Request) -> str | None:
        """The caller's id if starring is a thing they could do, else None."""
        user_id = getattr(request.state, "user_id", None)
        if user_id is None or user_repo is None:
            return None
        user = await user_repo.get_by_id(user_id)
        return None if user is None or user.is_anonymous else user.id

    async def require_publisher(request: Request, *, action: str = "publish") -> UserData:
        """R-LIST-12's gate: registered, verified, and not in trouble.

        The bar is about the account rather than the content, because content
        is judged after the fact (R-LIST-13) - so what the gate has to cost
        somebody publishing abuse is the account itself, which an unverified
        address does not.

        A ban is not checked here: a suspended account's every request but
        export, deletion and logout is already refused before this route runs
        (R-BAN-04), so a check would be dead code pretending to be a rule. An
        unacknowledged warning is the state that reaches this far.
        """
        user = await require_registered(request)
        if session_factory is None:  # pragma: no cover - wiring guard
            # A programming error, not a refusal: no player can cause it.
            raise RuntimeError("create_prompt_list_router needs a session factory")
        async with session_factory() as session:
            row = await session.get(User, UUID(user.id))
            if row is None or row.email_verified_at is None:
                raise Refusal(
                    403,
                    ErrorCode.EMAIL_VERIFICATION_REQUIRED,
                    "Verify your email address first.",
                    params={"action": action},
                )
            pending = await session.scalar(
                select(UserWarning.id).where(
                    UserWarning.user_id == UUID(user.id),
                    UserWarning.acknowledged_at.is_(None),
                )
            )
        if pending is not None:
            raise Refusal(
                403,
                ErrorCode.WARNING_UNREAD,
                "Read your moderator warning first.",
                params={"action": action},
            )
        return user

    async def _stamp(request: Request, user: UserData, event: str) -> AuditStamp:
        """The ledger entry's coordinates, for the repository to write.

        Gathered here and written *there* so the entry commits with the change
        it describes — the reason `config_store` gives for taking a session
        rather than a factory. Publishing used to commit, and then a second
        transaction wrote the ledger; a failure between the two left a list
        published with nothing to say who published it.
        """
        request_id, ip_hash = await audit_coordinates(request, session_factory)
        return AuditStamp(
            event_type=event,
            actor_user_id=user.id,
            request_id=request_id,
            ip_hash=ip_hash,
        )

    async def _set_star(prompt_list_id: str, request: Request, *, starred: bool):
        """Starring needs a verified account, for R-LIST-12's reason.

        A star is a public number somebody else's list carries, so the account
        giving it has to cost something - otherwise the count means only that
        somebody could open a browser.
        """
        user = await require_publisher(request, action="star")
        if not star_limiter.check(client_key(request)):
            raise Refusal(
                429,
                ErrorCode.TOO_MANY_ATTEMPTS,
                "Too many attempts. Please wait and try again.",
            )
        try:
            count = await prompt_list_repo.set_star(
                user.id, prompt_list_id, starred=starred
            )
        except PromptListMutationError as error:
            raise mutation_error(error) from error
        return {"starCount": count, "starredByMe": starred}

    @router.post(
        "/prompt-lists/{prompt_list_id}/fork",
        status_code=status.HTTP_201_CREATED,
    )
    async def fork_prompt_list(prompt_list_id: str, request: Request):
        """Take a copy of a published list (R-LIST-17).

        The copy is **private**: a fork is somebody taking content to work on,
        and publishing it is a separate act with its own gate. It counts
        against R-LIST-04's allowance and is refused visibly at the cap,
        having written nothing.
        """
        user = await require_registered(request)
        if not publish_limiter.check(client_key(request)):
            raise Refusal(
                429,
                ErrorCode.TOO_MANY_ATTEMPTS,
                "Too many attempts. Please wait and try again.",
            )
        try:
            forked = await prompt_list_repo.fork_published(user.id, prompt_list_id)
        except PromptListMutationError as error:
            raise mutation_error(error) from error
        return owned_prompt_list_payload(forked)

    @router.put("/prompt-lists/{prompt_list_id}/star")
    async def star_prompt_list(prompt_list_id: str, request: Request):
        """Star a published list. Idempotent: the composite primary key is
        what makes starring twice the same row, so there is no guard here."""
        return await _set_star(prompt_list_id, request, starred=True)

    @router.delete("/prompt-lists/{prompt_list_id}/star")
    async def unstar_prompt_list(prompt_list_id: str, request: Request):
        """Take it back. Unstarring one never starred is not an error - the
        caller's intent is already true."""
        return await _set_star(prompt_list_id, request, starred=False)

    @router.post("/prompt-lists/mine/{prompt_list_id}/publish")
    async def publish_my_prompt_list(prompt_list_id: str, request: Request):
        """Put an owned list in the community catalogue (R-LIST-11).

        Its own endpoint rather than a `visibility` field on the save, because
        the gate above, the rate limit and the audit event all belong to the
        act. A field on a save would be a way around all three.
        """
        user = await require_publisher(request)
        if not publish_limiter.check(client_key(request)):
            raise Refusal(
                429,
                ErrorCode.TOO_MANY_ATTEMPTS,
                "Too many attempts. Please wait and try again.",
            )
        try:
            updated = await prompt_list_repo.set_owned_publication(
                user.id,
                prompt_list_id,
                published=True,
                under_review=await read_publication_review(session_factory),
                audit=await _stamp(request, user, PUBLISHED_EVENT),
            )
        except PromptListMutationError as error:
            raise mutation_error(error) from error
        return owned_prompt_list_payload(updated)

    @router.post("/prompt-lists/mine/{prompt_list_id}/unpublish")
    async def unpublish_my_prompt_list(prompt_list_id: str, request: Request):
        """Take it back out. The stars stay as rows (R-LIST-16); the list
        simply stops being reachable, and publishing again finds them."""
        user = await require_registered(request)
        try:
            updated = await prompt_list_repo.set_owned_publication(
                user.id,
                prompt_list_id,
                published=False,
                audit=await _stamp(request, user, UNPUBLISHED_EVENT),
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
            raise Refusal(404, ErrorCode.PROMPT_LIST_NOT_FOUND, "Prompt list not found.")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post("/prompt-lists/shared")
    async def resolve_shared_prompt_list(
        body: SharedPromptListRequest, request: Request
    ):
        if not share_limiter.check(client_key(request)):
            raise Refusal(
                429,
                ErrorCode.TOO_MANY_ATTEMPTS,
                "Too many attempts. Please wait and try again.",
            )
        prompt_list = await prompt_list_repo.get_shared(body.code)
        if prompt_list is None:
            raise Refusal(
                404,
                ErrorCode.SHARED_PROMPT_LIST_NOT_FOUND,
                "No shared prompt list found.",
            )
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
            raise Refusal(
                429,
                ErrorCode.TOO_MANY_REQUESTS,
                "Too many requests. Please wait and try again.",
            )
        if sort not in SORTS:
            raise Refusal(422, ErrorCode.UNKNOWN_SORT, "Unknown sort.", field="sort")
        for field_name, value in (("from", from_time), ("to", to_time)):
            if value is not None and value.tzinfo is None:
                raise Refusal(
                    422,
                    ErrorCode.TIMEZONE_REQUIRED,
                    f"{field_name} must include a timezone.",
                    field=field_name,
                )
        if from_time is not None:
            from_time = from_time.astimezone(timezone.utc)
        if to_time is not None:
            to_time = to_time.astimezone(timezone.utc)
        if from_time is not None and to_time is not None and from_time >= to_time:
            raise Refusal(
                422, ErrorCode.RANGE_REVERSED, "from must be earlier than to.", field="from"
            )

        summaries = await prompt_list_repo.get_prompt_stats(
            slug,
            from_time=from_time,
            to_time=to_time,
            scoring_mode=scoring_mode.value if scoring_mode else None,
            hint_mode=hint_mode.value if hint_mode else None,
        )
        if not summaries:
            raise Refusal(404, ErrorCode.PROMPT_LIST_NOT_FOUND, "No such prompt list.")

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
