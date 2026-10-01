"""SQLAlchemy implementations of domain repository interfaces."""
from __future__ import annotations

import asyncio
import base64
import hmac
import math
import secrets
from collections import Counter, OrderedDict, defaultdict
from collections.abc import Awaitable, Callable, Collection, Mapping, Sequence
import dataclasses
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import time
from time import thread_time
from uuid import UUID

from sqlalchemy import ColumnElement, Row, Uuid, and_, any_, bindparam, case, delete, desc, exists, func, insert, or_, select, union_all, update
from sqlalchemy import text as sql_text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased, defer, selectinload

from app.services.runtime_metrics import metrics
from app.services.telemetry import database_operation_of, telemetry
from app.db import read_session
from app.db.roles import SEEDED_TABLES
from app.encode_pool import off_loop as _off_loop
from app.db.models import (
    GalleryShelfReview,
    AuditEvent,
    Friendship,
    GameParticipant,
    GamePromptSource,
    GameRecord,
    IdentityAlias,
    Prompt,
    PromptAlias,
    PromptConcept,
    PromptList,
    PromptListRevision,
    PromptListRevisionItem,
    PromptListEdition,
    PromptListEditionItem,
    PromptListEditionTag,
    PromptListTag,
    PromptListStar,
    PromptTakedown,
    PromptTag,
    PromptUsageBatch,
    PromptUsageFact,
    PromptVersion,
    PromptVersionAlias,
    PromptVersionTag,
    ScoreEvent,
    TurnDrawing,
    ProfileDrawingPin,
    TurnDrawingReaction,
    TurnParticipantOutcome,
    TurnPromptOffer,
    TurnPromptOfferSource,
    TurnRecord,
    User,
    UserBlock,
    UserSettings,
    UserStatsDaily,
    generate_uuid,
)
from app.canvas_history import binary_action_count
from app.canvas_storage import (
    CorruptStoredDrawingError,
    prepare_stored_drawing,
    stored_drawing_checksum,
    stored_drawing_format,
)
from app.services.gallery_ranking import (
    HOT_HORIZON,
    MAX_GALLERY_OFFSET,
    MAX_GALLERY_PAGE,
    TOP_WINDOWS,
    hot_score,
)
from app.domain_values import (
    AGNOSTIC_PROMPT_LANGUAGE,
    MIXED_PROMPT_LANGUAGE,
    RuntimeEventType,
    AccountState,
    AuditTargetType,
    DRAWING_UNAVAILABLE_RECAP_BUDGET,
    FriendshipState,
    GAME_OUTCOMES,
    GAME_PROMPT_SOURCE_MODES,
    GAME_VISIBILITIES,
    PROFILE_PIN_SLOTS,
    GameOutcome,
    GalleryShelfDecision,
    GameVisibility,
    PROMPT_LANGUAGES,
    PROMPT_OFFER_SOURCE_KINDS,
    PromptLanguage,
    PROMPT_SOURCE_KINDS,
    PromptContentModerationState,
    PromptListVisibility,
    REACTION_EMOJI_CODES,
    REACTION_SET_VERSION,
    OFFERED_REACTION_EMOJI_CODES,
    SCORE_EVENT_TYPES,
    TURN_ELIGIBILITY_REASONS,
    TURN_PARTICIPANT_OUTCOMES,
    TURN_PARTICIPANT_STATES,
    TurnDrawingStatus,
)
from app.auth.avatar_doodles import random_doodle_key
from app.auth.avatars import validate_avatar_key
from app.auth.pending_role import pending_offer
from app.services.prompt_editions import (
    content_hash as edition_content_hash,
    drop_editions,
    editions_of,
    snapshot_edition,
    working_copy_state,
)
from app.services.prompt_reclaim import retire_prompt_list
from app.services.prompt_takedowns import record_takedowns
from app.auth.erasure import (
    LockSetChangedError,
    TOMBSTONE_SNAPSHOT,
    erased_identity_ids,
    require_live_account,
)
from app.services.user_stats_projection import (
    adjust_reactions_received,
    fold_identity_into_account,
    increment_user_stats_projection,
)
from app.services.friends import friendship_key, other_of
from app.repositories.interfaces import (
    StoredDrawingInput,
    AuditStamp,
    CommunityPromptList,
    CommunityPromptListDetail,
    CopiedFrom,
    EditionSummary,
    CommunityPromptListPage,
    AccountAlreadyClaimedError,
    BundledPromptDefinition,
    PinnedPromptSelection,
    PromptSample,
    SampledPrompt,
    DrawingReactionResult,
    GalleryEntry,
    GalleryPage,
    GameDetail,
    GameHistoryConflictError,
    PromptUsageConflictError,
    GameHistoryRepository,
    GameParticipantInput,
    GameParticipantSummary,
    GameRecordInput,
    GameSummary,
    RecentCoPlayer,
    ScoreEventInput,
    InvalidProfileDataError,
    IdentityMergeError,
    TurnDetail,
    TurnDrawingDetail,
    TurnDrawingInput,
    ProfilePinDetail,
    ProfilePinEntry,
    ProfilePinsResult,
    TurnDrawingReactionDetail,
    TurnDrawingReactionInput,
    TurnParticipantOutcomeDetail,
    TurnParticipantOutcomeInput,
    TurnRecordInput,
    UserCredentials,
    UserData,
    UserRepository,
    UserStats,
    UsernameTakenError,
    PromptListRepository,
    PromptListConflictError,
    PromptListEntry,
    PromptListEntryInput,
    PromptListMutationError,
    PromptListNotFoundError,
    PromptListSelectionError,
    PromptListsChangedError,
    MixedRoomListError,
    TooManyPlayerListsError,
    PromptTranslation,
    PromptSeedConflictError,
    PromptListSummary,
    OwnedPromptList,
    PromptStatsSummary,
    PromptUsage,
    ResolvedPromptSelection,
)
from app.prompt_content import (
    LIST_TAG_SLUG_ORDER,
    LIST_TAG_VOCABULARY,
    MAX_PLAYER_PROMPT_LISTS,
    UnknownListTag,
    clean_list_tags,
    clean_prompt_aliases_keyed,
    normalize_prompt_answer,
    visible_text_problem,
    languages_sharing_words,
    prompt_match_key,
    prompt_match_keys,
    prompt_match_variants,
    validate_prompt_list_language,
)
from app.prompts import letter_histogram
from app.refusals import ErrorCode

logger = logging.getLogger(__name__)

# How many times a pin write restarts when a merge lands inside the barrier's
# window between its alias read and its lock (app.auth.erasure).
PIN_WRITE_LOCK_RETRIES = 3


# One screenful of the community catalogue, and the depth past which browsing
# has stopped being browsing. The ceiling is not about the database - the
# offset is cheap at this size - but about what a deep page is *for*: nobody
# reaches page four hundred by reading, so the request is a scrape, and a
# filter is the better answer than a longer scroll.
MAX_COMMUNITY_PAGE = 48
MAX_COMMUNITY_OFFSET = 480


def _playable_in(language: str) -> ColumnElement[bool]:
    """The lists a room in `language` could pick: its own, and every
    language-agnostic one (#821), which is played in any room. Asking for
    `zxx` itself narrows to the agnostic lists alone."""
    if language == AGNOSTIC_PROMPT_LANGUAGE:
        return PromptList.language == AGNOSTIC_PROMPT_LANGUAGE
    return PromptList.language.in_((language, AGNOSTIC_PROMPT_LANGUAGE))


def _published_by_a_player():
    """What "in the community catalogue" means, in one place.

    The fourth clause is the one that was missing everywhere it mattered.
    Bundled lists are public and active too - that is what the official
    catalogue *is* - so a predicate checking only public-active-present let an
    official list be starred and forked. Forking one was the worse half: the
    fork path builds its entries directly, so copying Standard - a thousand
    prompts and more - would have written an owned list well past R-LIST-04's 500.
    """
    return (
        PromptList.visibility == PromptListVisibility.PUBLIC.value,
        PromptList.moderation_state == PromptContentModerationState.ACTIVE.value,
        PromptList.deleted_at.is_(None),
        PromptList.is_bundled.is_(False),
        # And something to show: what the catalogue serves is the live
        # edition (#1360), so a first publication still waiting for review
        # is public and in nobody's catalogue until a moderator clears it.
        _live_edition_of(PromptList.id).exists(),
    )


EDITION_PUBLISHED = "published"
EDITION_UNDER_REVIEW = "under_review"


def _live_edition_of(list_id):
    """The list's live edition, as a select of its id (#1360)."""
    return select(PromptListEdition.id).where(
        PromptListEdition.prompt_list_id == list_id,
        PromptListEdition.state == EDITION_PUBLISHED,
    )


def _encode_catalogue_cursor(offset: int) -> str:
    return str(offset)


# The cursor is signed with a key this process made up at start (#1072
# review): the depth ceiling reads the rows served off the cursor, and an
# unsigned one could be rewritten to read the whole Gallery. Per process
# rather than a configured secret because nothing has to verify it but the
# process that issued it - one worker - and a restart reading an old cursor
# as page one is the outcome a mangled cursor gets anyway.
_GALLERY_CURSOR_KEY = secrets.token_bytes(32)
_GALLERY_CURSOR_MAC_BYTES = 16


def _gallery_cursor_mac(token: bytes) -> bytes:
    return hmac.new(_GALLERY_CURSOR_KEY, token, "sha256").digest()[:_GALLERY_CURSOR_MAC_BYTES]


def _encode_gallery_cursor(
    sort: str, sort_key: float | int | None, finished_at: datetime, turn_id: UUID, served: int
) -> str:
    """Where the last row of a page stood, so the next page starts after it.

    Keyset rather than an offset (#1072): a game finishing between two page
    reads ranks above the cut in every order, and an offset then served the
    row at the cut twice - a drawing shown two times on one screen - or
    skipped one on the way down. `served` keeps the depth ceiling: the
    cursor knows how many rows came before it, which an offset used to be.
    The sort is inside, so a cursor cannot be carried from one order to
    another, and the whole thing is signed.
    """
    token = json.dumps(
        [sort, sort_key, finished_at.isoformat(), str(turn_id), served], separators=(",", ":")
    ).encode()
    return base64.urlsafe_b64encode(token + _gallery_cursor_mac(token)).decode().rstrip("=")


def _decode_gallery_cursor(
    cursor: str | None, *, sort: str
) -> tuple[float | int | None, datetime, UUID, int] | None:
    """A malformed, forged, or foreign cursor reads as the first page, as the
    catalogue's does: it is an opaque token the client got from us, and page
    one is a better answer than a 422 - or a 500 from a value the driver
    refuses at bind time - on a link somebody shared."""
    if not cursor:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded.encode())
        token, mac = raw[:-_GALLERY_CURSOR_MAC_BYTES], raw[-_GALLERY_CURSOR_MAC_BYTES:]
        if not hmac.compare_digest(mac, _gallery_cursor_mac(token)):
            return None
        cursor_sort, sort_key, finished_at, turn_id, served = json.loads(token.decode())
        if cursor_sort != sort:
            return None
        if sort_key is not None:
            if isinstance(sort_key, bool) or not isinstance(sort_key, (int, float)):
                return None
            sort_key = float(sort_key)
            if not math.isfinite(sort_key):
                return None
        finished = datetime.fromisoformat(finished_at)
        if finished.tzinfo is None:
            return None
        return (sort_key, finished, UUID(turn_id), max(0, int(served)))
    except (ValueError, TypeError, AttributeError):
        return None


def _decode_catalogue_cursor(cursor: str | None) -> int:
    """A malformed cursor reads as the first page rather than an error.

    It is an opaque token the client got from us; the only way to hold a bad
    one is to have mangled it, and answering page one is a better outcome than
    a 422 on a link somebody shared.
    """
    if not cursor:
        return 0
    try:
        return max(0, int(cursor))
    except ValueError:
        return 0

MAX_PAGINATION_LIMIT = 100
DEFAULT_PAGINATION_LIMIT = 20
MAX_OWNED_PROMPT_LISTS = 25


async def _owned_list_count(session: AsyncSession, owner_id: UUID) -> int:
    """The lists counting toward an account's allowance. Callers hold the
    owner's row `FOR UPDATE` (`require_live_account(..., exclusive=True)`), so
    the number is still true when they insert (#898)."""
    count = await session.scalar(
        select(func.count(PromptList.id)).where(
            PromptList.owner_user_id == owner_id,
            PromptList.is_bundled.is_(False),
            PromptList.deleted_at.is_(None),
        )
    )
    return int(count or 0)
MAX_PROMPTS_PER_OWNED_LIST = 500


def _entity_id(value: str | UUID) -> UUID:
    """Convert a domain/wire identifier at the persistence boundary."""
    return value if isinstance(value, UUID) else UUID(value)


def _optional_entity_id(value: str | UUID) -> UUID | None:
    try:
        return _entity_id(value)
    except (ValueError, AttributeError, TypeError):
        return None


def _public_id(value: UUID) -> str:
    return str(value)


@dataclass
class _GameSizing:
    """What one finished game wrote, measured as it is written (#895) and
    reported only once the transaction has committed, so a retried or
    refused write is never counted."""

    drawings: list[tuple[str, int, int, int, float | None]] = field(default_factory=list)
    offer_sources: int = 0

    def record(
        self,
        *,
        participants: int,
        turns: Sequence[TurnRecordInput],
        score_events: int,
        drawings: int,
        reactions: int,
        prompt_sources: int,
    ) -> None:
        for magic, raw_bytes, stored_bytes, actions, seconds in self.drawings:
            telemetry.drawing_stored(
                magic, raw_bytes=raw_bytes, stored_bytes=stored_bytes, actions=actions, seconds=seconds
            )
            # Counted on `/metrics` and not stored (#965): the sizes and the
            # encoding's ratio are the `sketchy_drawing_*_bytes` histograms
            # just above, which Prometheus keeps for as long as it retains.
            metrics.record(RuntimeEventType.DRAWING_ENCODED, value=stored_bytes)
        telemetry.game_rows_written(
            {
                "game_records": 1,
                "game_participants": participants,
                "turn_records": len(turns),
                "turn_participant_outcomes": sum(len(turn.participant_outcomes) for turn in turns),
                "turn_prompt_offers": sum(len(turn.prompt_offers) for turn in turns),
                "turn_prompt_offer_sources": self.offer_sources,
                "game_prompt_sources": prompt_sources,
                "score_events": score_events,
                "turn_drawings": drawings,
                "turn_drawing_reactions": reactions,
            }
        )


@dataclass(frozen=True)
class _PreparedDrawing:
    """One drawing encoded for storage, before the transaction that writes it."""

    blob: bytes
    magic: bytes
    version: int
    checksum: str
    wire_bytes: int
    action_count: int
    # None for a drawing prepared at staging: its encode was recorded there.
    seconds: float | None


@dataclass(frozen=True)
class _UnpreparedDrawing:
    """A drawing whose stored form could not be made, and why. Raised only
    if the row is written: an erased drawer's drawing is a tombstone whatever
    its bytes were, as it was when this ran inside the transaction."""

    error: Exception


def _prepare_drawing(payload: bytes) -> _PreparedDrawing:
    # Thread time, not wall time: on a worker thread the wall clock also
    # counts the GIL turns the event loop takes meanwhile.
    started = thread_time()
    blob, magic, version, checksum = prepare_stored_drawing(payload)
    return _PreparedDrawing(
        blob=blob,
        magic=magic,
        version=version,
        checksum=checksum,
        wire_bytes=len(payload),
        action_count=binary_action_count(payload),
        seconds=thread_time() - started,
    )


def _verified_stored_drawing(stored: StoredDrawingInput) -> _PreparedDrawing:
    """A drawing the envelope carried already prepared (#1259), written as it
    is once its bytes are proved to be the ones it was prepared as.

    What travels beside the blob is checked too, as far as the blob can say:
    a row whose format disagrees with its own header is one the integrity
    audit would later call mismatched (#1259 review). Its encode was timed
    where it happened, at staging."""
    if stored_drawing_checksum(stored.blob) != stored.checksum:
        raise CorruptStoredDrawingError("a staged drawing failed its checksum")
    magic = stored.magic.encode("ascii")
    if stored_drawing_format(stored.blob) != (magic, stored.version):
        raise CorruptStoredDrawingError("a staged drawing's format disagrees with its header")
    if stored.action_count < 0 or stored.wire_bytes < 0:
        raise CorruptStoredDrawingError("a staged drawing carries a negative count")
    return _PreparedDrawing(
        blob=stored.blob,
        magic=magic,
        version=stored.version,
        checksum=stored.checksum,
        wire_bytes=stored.wire_bytes,
        action_count=stored.action_count,
        seconds=None,
    )


def _prepare_drawings(
    drawings: list[TurnDrawingInput] | None,
) -> list[_PreparedDrawing | _UnpreparedDrawing | None]:
    prepared: list[_PreparedDrawing | _UnpreparedDrawing | None] = []
    for drawing in drawings or []:
        if not drawing.is_kept:
            prepared.append(None)
            continue
        try:
            if drawing.stored is not None:
                prepared.append(_verified_stored_drawing(drawing.stored))
            else:
                prepared.append(_prepare_drawing(drawing.payload))
        except Exception as error:  # noqa: BLE001 - re-raised if the row is written
            prepared.append(_UnpreparedDrawing(error))
    return prepared


def _turn_drawing(
    drawing: TurnDrawingInput,
    turn_id: UUID,
    game_id: UUID,
    sizing: _GameSizing | None,
    # `None` for a drawing with no payload: there was nothing to prepare, and
    # the row below says so instead of carrying bytes.
    prepared: _PreparedDrawing | None,
) -> TurnDrawing:
    """Build the row for one turn's drawing, stored or explained.

    A drawing the recap had to drop is recorded as unavailable rather than
    omitted, so history says the same thing the players were told instead of
    implying the turn was never drawn.
    """

    if not drawing.is_kept:
        return TurnDrawing(
            turn_id=turn_id,
            game_id=game_id,
            status=TurnDrawingStatus.UNAVAILABLE.value,
            unavailable_reason=(
                drawing.unavailable_reason or DRAWING_UNAVAILABLE_RECAP_BUDGET
            ),
        )
    if sizing is not None:
        sizing.drawings.append(
            (
                prepared.magic.decode("ascii"),
                prepared.wire_bytes,
                len(prepared.blob),
                prepared.action_count,
                prepared.seconds,
            )
        )
    return TurnDrawing(
        turn_id=turn_id,
        game_id=game_id,
        status=TurnDrawingStatus.READY.value,
        format_magic=prepared.magic.decode("ascii"),
        format_version=prepared.version,
        payload=prepared.blob,
        byte_size=len(prepared.blob),
        checksum_sha256=prepared.checksum,
        stored_at=datetime.now(timezone.utc),
    )


def _erased_turn_drawing(turn_id: UUID, game_id: UUID) -> TurnDrawing:
    """The row an erased account's drawing is written as: that it was, not what.

    The same shape `anonymize_account` leaves behind for a drawing already
    stored, so history reads identically whether the deletion came before
    or after the game was written.
    """
    now = datetime.now(timezone.utc)
    return TurnDrawing(
        turn_id=turn_id,
        game_id=game_id,
        status=TurnDrawingStatus.DELETED.value,
        deleted_at=now,
    )


@dataclass(frozen=True, slots=True)
class _RevisionVersion:
    """One member of a working copy, as a save reads it (#1236): what the version
    is, what it answers to, and what a moderator decided about it."""

    id: UUID
    concept_id: UUID
    canonical_answer: str
    version: int
    match_key: str
    moderation_state: str
    moderated_at: datetime | None
    moderated_by_user_id: UUID | None
    aliases: tuple[str, ...]


async def _working_copy_versions(
    session: AsyncSession, prompt_list_id: UUID
) -> list[_RevisionVersion]:
    """A list's working copy in order, from one flat select (#1359)."""
    rows = (
        await session.execute(
            select(
                Prompt.position,
                Prompt.id,
                PromptVersion.id,
                PromptVersion.concept_id,
                PromptVersion.canonical_answer,
                PromptVersion.version,
                PromptVersion.match_key,
                PromptVersion.moderation_state,
                PromptVersion.moderated_at,
                PromptVersion.moderated_by_user_id,
                PromptAlias.answer,
            )
            .select_from(Prompt)
            .join(PromptVersion, PromptVersion.id == Prompt.prompt_version_id)
            .outerjoin(
                PromptVersionAlias,
                PromptVersionAlias.prompt_version_id == PromptVersion.id,
            )
            .outerjoin(PromptAlias, PromptAlias.id == PromptVersionAlias.alias_id)
            .where(Prompt.prompt_list_id == prompt_list_id)
            .order_by(Prompt.position, Prompt.id)
        )
    ).all()
    members: dict[UUID, tuple[tuple, list[str]]] = {}
    for _position, row_id, *fields, alias in rows:
        held = members.get(row_id)
        if held is None:
            held = members[row_id] = (tuple(fields), [])
        if alias is not None:
            held[1].append(alias)
    return [
        _RevisionVersion(*fields, aliases=tuple(sorted(aliases)))
        for fields, aliases in members.values()
    ]


def _same_membership(
    previous: Sequence[_RevisionVersion], entries: Sequence[PromptListEntryInput]
) -> bool:
    """Whether `entries` restate the working copy exactly: identity, answer, aliases, order."""
    if len(previous) != len(entries):
        return False
    for version, entry in zip(previous, entries, strict=True):
        if entry.concept_id is None or UUID(entry.concept_id) != version.concept_id:
            return False
        if version.canonical_answer != entry.answer:
            return False
        if version.aliases != tuple(sorted(entry.aliases)):
            return False
    return True


def _standing_offer(user: User) -> str | None:
    """The offered role, or nothing once it has lapsed.

    Filtered here rather than at the caller so a lapsed offer is invisible
    everywhere at once: the account is told nothing is waiting, and it is
    cleared for good the next time anything tries to take it up.
    """
    return pending_offer(user)


def _to_user_data(user: User) -> UserData:
    """Convert a database User entity to a public UserData DTO (without password_hash)."""
    return UserData(
        id=_public_id(user.id),
        username=user.username,
        display_name=user.display_name,
        name_color=user.name_color,
        avatar_key=user.avatar_key,
        is_anonymous=user.is_anonymous,
        state=user.state,
        role=user.role,
        pending_role=_standing_offer(user),
        created_at=user.created_at,
        updated_at=user.updated_at,
        last_login_at=user.last_login_at,
        last_active_at=user.last_active_at,
        last_seen_at=user.last_seen_at,
    )


async def _canonical_user_id(session: AsyncSession, user_id: UUID) -> UUID:
    target = await session.scalar(
        select(IdentityAlias.target_user_id).where(
            IdentityAlias.source_user_id == user_id
        )
    )
    return target or user_id


async def _identity_ids(session: AsyncSession, user_id: UUID) -> tuple[UUID, ...]:
    canonical = await _canonical_user_id(session, user_id)
    aliases = (
        await session.scalars(
            select(IdentityAlias.source_user_id).where(
                IdentityAlias.target_user_id == canonical
            )
        )
    ).all()
    return (canonical, *aliases)


def _gallery_predicate():
    """What "in the Gallery" means (R-GAL-01), in one place: a public game
    and a kept, readable drawing. Over `TurnDrawing` joined to `GameRecord`;
    the third door beside the participant check and the pin predicate, and
    deliberately its own clauses so an edit to either cannot loosen it."""
    return (
        GameRecord.visibility == GameVisibility.PUBLIC.value,
        TurnDrawing.status == TurnDrawingStatus.READY.value,
        TurnDrawing.payload.is_not(None),
        TurnDrawing.gallery_hidden_at.is_(None),
    )


def _gallery_shows(drawing: TurnDrawing | None) -> bool:
    """The drawing half of the gallery predicate on a loaded row - the game
    half is checked by the caller, which has the game. Read off the metadata
    (`ck_turn_drawings_ready_identity` ties a ready row to its checksum), so
    the deferred blob is never loaded to answer it."""
    return (
        drawing is not None
        and drawing.status == TurnDrawingStatus.READY.value
        and drawing.checksum_sha256 is not None
        and drawing.gallery_hidden_at is None
    )


@dataclass(frozen=True)
class _ReactionSummary:
    details: tuple[TurnDrawingReactionDetail, ...]
    counts: dict[str, int]
    my_reaction: str | None


_NO_REACTIONS = _ReactionSummary(details=(), counts={}, my_reaction=None)


async def _reaction_summaries(
    session: AsyncSession,
    turn_ids: Sequence[UUID],
    viewer_ids: Sequence[UUID] = (),
) -> dict[UUID, _ReactionSummary]:
    """How a page of drawings' reactions are shown (R-REACT-05), without
    hydrating a row per reaction: the counts come grouped by code, the named
    list is the seat rows alone - bounded by a room's seats - and the
    viewer's own pick is one more small query. Since anyone signed in may
    react (#524), the rows behind one drawing are not bounded by anything a
    page should have to instantiate."""
    if not turn_ids:
        return {}
    ids = list(turn_ids)
    counts: dict[UUID, dict[str, int]] = defaultdict(dict)
    for turn_id, emoji, count in (
        await session.execute(
            select(
                TurnDrawingReaction.turn_id,
                TurnDrawingReaction.emoji,
                func.count(),
            )
            .where(TurnDrawingReaction.turn_id.in_(ids))
            .group_by(TurnDrawingReaction.turn_id, TurnDrawingReaction.emoji)
        )
    ).all():
        counts[turn_id][emoji] = int(count)
    details: dict[UUID, list[TurnDrawingReactionDetail]] = defaultdict(list)
    for row in (
        await session.scalars(
            select(TurnDrawingReaction)
            .where(
                TurnDrawingReaction.turn_id.in_(ids),
                TurnDrawingReaction.participant_id.is_not(None),
            )
            .order_by(TurnDrawingReaction.created_at, TurnDrawingReaction.id)
        )
    ).all():
        details[row.turn_id].append(
            TurnDrawingReactionDetail(
                seat_id=_public_id(row.participant_id), emoji=row.emoji
            )
        )
    mine: dict[UUID, str] = {}
    if viewer_ids:
        mine = dict(
            (
                await session.execute(
                    select(TurnDrawingReaction.turn_id, TurnDrawingReaction.emoji).where(
                        TurnDrawingReaction.turn_id.in_(ids),
                        TurnDrawingReaction.user_id.in_(list(viewer_ids)),
                    )
                )
            ).all()
        )
    return {
        turn_id: _ReactionSummary(
            details=tuple(details.get(turn_id, ())),
            counts=dict(counts.get(turn_id, {})),
            my_reaction=mine.get(turn_id),
        )
        for turn_id in ids
    }


async def apply_gallery_decision(
    session: AsyncSession,
    turn_id: UUID,
    *,
    decision: str,
    decided_by_user_id: UUID,
    now: datetime,
) -> tuple[UUID, UUID | None] | None:
    """Write a moderator's decision in the caller's transaction (R-GAL-09,
    R-GAL-10): the hidden flag on the drawing and the one review row per
    turn, under the drawing row's lock. In the caller's transaction so the
    audit event that records it commits with it or not at all. Answers the
    turn id and the drawer's account, or ``None`` when no kept drawing has
    that id."""
    if decision not in (
        GalleryShelfDecision.RELEASED.value,
        GalleryShelfDecision.HIDDEN.value,
    ):
        return None
    drawing = await session.scalar(
        select(TurnDrawing)
        .where(
            TurnDrawing.turn_id == turn_id,
            TurnDrawing.status == TurnDrawingStatus.READY.value,
        )
        .options(defer(TurnDrawing.payload))
        .with_for_update()
    )
    if drawing is None:
        return None
    turn = await session.get(TurnRecord, turn_id)
    drawing.gallery_hidden_at = (
        now if decision == GalleryShelfDecision.HIDDEN.value else None
    )
    drawing.updated_at = now
    review = await session.get(GalleryShelfReview, turn_id)
    if review is None:
        session.add(
            GalleryShelfReview(
                turn_id=turn_id,
                decision=decision,
                decided_by_user_id=decided_by_user_id,
                decided_at=now,
            )
        )
    else:
        review.decision = decision
        review.decided_by_user_id = decided_by_user_id
        review.decided_at = now
    await session.flush()
    drawer = turn.drawer_user_id if turn is not None else None
    return turn_id, drawer


def _prompt_usage_hash(list_ids: Sequence[UUID], usage: PromptUsage) -> str:
    """Canonical digest of one usage batch, to tell a retry from a conflict."""
    payload = {
        "list_ids": sorted(_public_id(list_id) for list_id in list_ids),
        "sources": sorted(
            (key, sorted(lists)) for key, lists in usage.sources.items()
        ),
        "offers": sorted((key, count) for key, count in usage.offers.items()),
        "picks": sorted(
            (key, totals.picks, totals.correct_guesses, totals.total_guessers)
            for key, totals in usage.picks.items()
        ),
        "occurred_at": usage.occurred_at.isoformat(),
        "scoring_mode": usage.scoring_mode,
        "hint_mode": usage.hint_mode,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _to_game_summary(game: GameRecord, *, with_rule_snapshot: bool = True) -> GameSummary:
    """Convert a stored game and its participants to the DTO both read paths return.

    Presentation comes from the frozen seat snapshots, never from the live
    `User` rows (R-PRIV-08), so nothing here loads them. The rule snapshot
    JSON is only serialised on the detail; a list read leaves it deferred
    and passes `with_rule_snapshot=False` (#611).
    """
    return GameSummary(
        id=_public_id(game.id),
        room_name=game.room_name,
        scoring_mode=game.scoring_mode,
        scoring_version=game.scoring_version,
        score_ledger_version=game.score_ledger_version,
        rule_snapshot_version=game.rule_snapshot_version,
        rule_snapshot=game.rule_snapshot if with_rule_snapshot else {},
        prompt_source_mode=game.prompt_source_mode,
        hint_mode=game.hint_mode,
        drawing_seconds=game.drawing_seconds,
        total_rounds=game.total_rounds,
        player_count=game.player_count,
        started_at=game.started_at,
        finished_at=game.finished_at,
        outcome=game.outcome,
        visibility=game.visibility,
        participants=[
            GameParticipantSummary(
                seat_id=_public_id(p.id),
                user_id=_public_id(p.user_id) if p.user_id else None,
                display_name=p.display_name_snapshot,
                name_color=p.name_color_snapshot,
                is_anonymous=p.is_anonymous_snapshot,
                final_score=p.final_score,
                final_rank=p.final_rank,
            )
            # Ranked seats first by rank, then unranked (abandoned) seats by
            # score; None sorts via the boolean, never compared as a rank.
            for p in sorted(
                game.participants,
                key=lambda x: (
                    x.final_rank is None,
                    x.final_rank or 0,
                    -x.final_score,
                ),
            )
        ],
    )


def _to_prompt_list_summary(
    wl: PromptList,
    prompt_count: int,
    *,
    locale: str | None = None,
    tags: Sequence[str] = (),
    family: str | None = None,
) -> PromptListSummary:
    localization = (
        next(
            (
                candidate
                for candidate in wl.localizations
                if candidate.locale == locale
            ),
            None,
        )
        if locale
        else None
    )
    return PromptListSummary(
        id=_public_id(wl.id),
        slug=wl.slug,
        name=localization.name if localization else wl.name,
        description=localization.description if localization else wl.description,
        language=wl.language,
        prompt_count=prompt_count,
        is_bundled=wl.is_bundled,
        version=wl.version,
        shelf=wl.shelf,
        series=wl.series,
        shelf_position=wl.shelf_position,
        tags=tuple(tags),
        family=family,
    )


def _to_owned_prompt_list(
    wl: PromptList,
    prompts: Sequence[PromptListEntry] = (),
    *,
    prompt_count: int | None = None,
    tags: Sequence[str] = (),
    star_count: int = 0,
    copy_count: int = 0,
    copied_from: CopiedFrom | None = None,
    editions: Mapping[str, PromptListEdition] | None = None,
) -> OwnedPromptList:
    editions = editions or {}
    live = editions.get(EDITION_PUBLISHED)
    pending = editions.get(EDITION_UNDER_REVIEW)
    return OwnedPromptList(
        id=_public_id(wl.id),
        slug=wl.slug,
        name=wl.name,
        description=wl.description,
        language=wl.language,
        visibility=wl.visibility,
        moderation_state=wl.moderation_state,
        version=wl.version,
        prompt_count=len(prompts) if prompt_count is None else prompt_count,
        created_at=wl.created_at,
        updated_at=wl.updated_at,
        prompts=tuple(prompts),
        tags=tuple(tags),
        star_count=star_count,
        copy_count=copy_count,
        copied_from=copied_from,
        live_edition=_edition_summary(live),
        pending_edition=_edition_summary(pending),
        # Against the latest edition, pending first: edits made while one waits
        # are not in it, and a release would publish the older content (#1386
        # review).
        unpublished_changes=(pending or live) is not None
        and (pending or live).content_hash != wl.content_hash,
    )


def _edition_summary(edition: PromptListEdition | None) -> EditionSummary | None:
    if edition is None:
        return None
    return EditionSummary(
        number=edition.number,
        created_at=edition.created_at,
        published_at=edition.published_at,
    )


async def _editions_by_list(
    session: AsyncSession, list_ids: Sequence[UUID]
) -> dict[UUID, dict[str, PromptListEdition]]:
    """Each list's live and pending editions, in one statement."""
    found: dict[UUID, dict[str, PromptListEdition]] = defaultdict(dict)
    if list_ids:
        for edition in (
            await session.scalars(
                select(PromptListEdition).where(
                    PromptListEdition.prompt_list_id.in_(list(list_ids))
                )
            )
        ).all():
            found[edition.prompt_list_id][edition.state] = edition
    return found


def _bundled_revision_hash(
    *, language: str, prompts: Sequence[BundledPromptDefinition]
) -> str:
    """Hash the exact ordered immutable content, independent of JSON layout."""
    payload = {
        "language": language,
        "prompts": [
            {
                "concept_id": prompt.concept_id,
                "prompt_version": prompt.prompt_version,
                "canonical_prompt": prompt.answer,
                "aliases": sorted(prompt.aliases),
                "difficulty": prompt.editorial_difficulty,
                "content_rating": prompt.content_rating,
                "tags": sorted(prompt.tags),
            }
            for prompt in prompts
        ],
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


async def _merge_friendships(session, source_id, target_id) -> None:
    """Move a merged guest's friendships onto the account it became.

    A no-op today: only registered accounts may hold a friendship, and a guest
    being merged is by definition not one. Written anyway, because "registered
    only" is a product decision that could be revisited, and because the shape
    of this merge is genuinely harder than the block merge beside it - a pair
    here is *ordered*, so a remap can move an id from one column to the other
    and the row has to be rebuilt rather than reassigned in place.

    The cases, in the order they are handled:

    * **Self-friendship.** `(source, target)` becomes `(target, target)`, which
      `ck_friendships_ordered` rejects. Deleted, the way the block merge drops
      a pair that would become a self-block.
    * **Duplicate.** A remap landing on a pair that already exists keeps one
      row, and keeps the stronger status: `accepted` beats `pending` beats
      `declined`. An accepted friendship is a decision both people made, and a
      merge is not a reason to quietly undo it.
    * **Crossing pendings collapse.** Two pendings in opposite directions
      become one accepted friendship, for the same reason a crossing request
      does - the alternative is two rows that can never resolve.
    * **The requester moves too.** Miss it and
      `ck_friendships_requester_is_a_member` fires, which is the constraint
      earning its place rather than a bug reaching a user.
    """
    rows = (
        await session.scalars(
            select(Friendship).where(
                or_(
                    Friendship.user_low_id == source_id,
                    Friendship.user_high_id == source_id,
                )
            )
        )
    ).all()
    ranking = {
        FriendshipState.ACCEPTED.value: 3,
        FriendshipState.PENDING.value: 2,
        FriendshipState.DECLINED.value: 1,
    }
    for row in rows:
        other = other_of(row, source_id)
        requested_by = target_id if row.requested_by_id == source_id else row.requested_by_id
        await session.delete(row)
        if other == target_id:
            # The guest and the account it merged into. There is one person
            # here now, and a person is not their own friend.
            continue
        await session.flush()
        low, high = friendship_key(target_id, other)
        existing = await session.get(Friendship, (low, high))
        if existing is None:
            session.add(
                Friendship(
                    user_low_id=low,
                    user_high_id=high,
                    requested_by_id=requested_by,
                    status=row.status,
                    # The answer moves with the status: an accepted or declined
                    # row says when (ck_friendships_pending_unanswered).
                    responded_at=row.responded_at,
                )
            )
            continue
        crossing = (
            existing.status == FriendshipState.PENDING.value
            and row.status == FriendshipState.PENDING.value
            and existing.requested_by_id != requested_by
        )
        if crossing:
            # Two pending requests towards each other are an acceptance, made
            # now: neither row had been answered, so neither has the time.
            existing.status = FriendshipState.ACCEPTED.value
            existing.responded_at = (
                row.responded_at or existing.responded_at or datetime.now(timezone.utc)
            )
        elif ranking[row.status] > ranking[existing.status]:
            existing.status = row.status
            existing.requested_by_id = requested_by
            existing.responded_at = row.responded_at


class SqlAlchemyUserRepository(UserRepository):
    """SQLAlchemy-backed implementation of UserRepository."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_anonymous(
        self,
        display_name: str,
        name_color: str | None = None,
        user_id: str | None = None,
    ) -> UserData:
        async with self._session_factory() as session:
            async with session.begin():
                user = User(
                    id=_entity_id(user_id) if user_id else generate_uuid(),
                    username=None,
                    password_hash=None,
                    # Left empty on purpose: "has no name yet" is what tells
                    # the client this is a first run. Nothing is invented for
                    # the player - they choose, or they sign up.
                    display_name=display_name.strip(),
                    name_color=name_color,
                    avatar_key=None,
                    state=AccountState.ANONYMOUS.value,
                )
                session.add(user)
            return _to_user_data(user)

    async def get_by_id(self, user_id: str) -> UserData | None:
        db_user_id = _optional_entity_id(user_id)
        if db_user_id is None:
            return None
        async with read_session(self._session_factory) as session:
            # One statement: the canonical id is the alias target if the id
            # is a merged guest's, else the id itself (#556).
            canonical = func.coalesce(
                select(IdentityAlias.target_user_id)
                .where(IdentityAlias.source_user_id == db_user_id)
                .scalar_subquery(),
                db_user_id,
            )
            user = await session.scalar(select(User).where(User.id == canonical))
            return _to_user_data(user) if user else None

    async def get_seat_account(self, user_id: str) -> tuple[UserData | None, bool | None]:
        db_user_id = _optional_entity_id(user_id)
        if db_user_id is None:
            return None, None
        async with self._session_factory() as session:
            canonical = func.coalesce(
                select(IdentityAlias.target_user_id)
                .where(IdentityAlias.source_user_id == db_user_id)
                .scalar_subquery(),
                db_user_id,
            )
            row = (
                await session.execute(
                    select(User, UserSettings.colorblind_safe_colors)
                    .outerjoin(UserSettings, UserSettings.user_id == User.id)
                    .where(User.id == canonical)
                )
            ).one_or_none()
        if row is None:
            return None, None
        user, colorblind = row
        return _to_user_data(user), bool(colorblind)

    async def get_by_username(self, username: str) -> UserData | None:
        clean = username.strip()
        if not clean:
            return None
        async with read_session(self._session_factory) as session:
            stmt = select(User).where(func.lower(User.username) == clean.lower())
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()
            return _to_user_data(user) if user else None

    async def find_guest_named(self, name: str, among_user_ids: Sequence[str]) -> str | None:
        clean = name.strip()
        ids = [db_id for value in among_user_ids if (db_id := _optional_entity_id(value)) is not None]
        if not clean or not ids:
            return None
        async with self._session_factory() as session:
            # One array parameter on PostgreSQL rather than an IN list, so the
            # statement text is the same however many ids there are and
            # asyncpg's prepared-statement cache can answer it (#900).
            if session.get_bind().dialect.name == "postgresql":
                listed = User.id == any_(
                    bindparam("ids", ids, type_=postgresql.ARRAY(Uuid(as_uuid=True)))
                )
            else:
                listed = User.id.in_(ids)
            found = await session.scalar(
                select(User.id)
                .where(
                    listed,
                    User.state == AccountState.ANONYMOUS.value,
                    func.lower(User.display_name) == clean.lower(),
                )
                .limit(1)
            )
            return _public_id(found) if found is not None else None

    async def get_credentials_by_username(self, username: str) -> UserCredentials | None:
        clean = username.strip()
        if not clean:
            return None
        async with self._session_factory() as session:
            stmt = select(User).where(func.lower(User.username) == clean.lower())
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()
            if not user or not user.password_hash:
                return None
            return UserCredentials(user=_to_user_data(user), password_hash=user.password_hash)

    async def claim_account(
        self,
        user_id: str,
        username: str,
        password_hash: str,
    ) -> UserData:
        clean_username = username.strip()
        if not clean_username:
            raise ValueError("Username cannot be empty")
        if not password_hash:
            raise ValueError("Password hash cannot be empty")
        db_user_id = _optional_entity_id(user_id)
        if db_user_id is None:
            raise ValueError(f"User '{user_id}' not found")

        async with self._session_factory() as session:
            async with session.begin():
                # 1. Fetch user to claim
                stmt = select(User).where(User.id == db_user_id)
                result = await session.execute(stmt)
                user = result.scalar_one_or_none()
                if user is None:
                    raise ValueError(f"User '{user_id}' not found")
                if not user.is_anonymous:
                    raise AccountAlreadyClaimedError("Account has already been claimed")

                # 2. Check case-insensitive username collision
                collision_stmt = select(User.id).where(
                    and_(
                        func.lower(User.username) == clean_username.lower(),
                        User.id != db_user_id,
                    )
                )
                existing_owner = (await session.execute(collision_stmt)).scalar_one_or_none()
                if existing_owner is not None:
                    raise UsernameTakenError(f"Username '{clean_username}' is already taken")

                user.username = clean_username
                user.password_hash = password_hash
                user.state = AccountState.REGISTERED.value
                # Registered players play as their username, so the display
                # name follows it rather than keeping the old guest nickname.
                user.display_name = clean_username
                # A new account starts with a doodle rather than an initial
                # (R-AVA-09), which its owner can change from Settings. A
                # guest never had a picture (R-AVA-02), so there is nothing
                # here to overwrite.
                user.avatar_key = random_doodle_key()
                try:
                    await session.flush()
                except IntegrityError as error:
                    # The check above can still lose to a concurrent claim of
                    # the same name; the unique index is the real arbiter, and
                    # callers should see the same error either way.
                    raise UsernameTakenError(
                        f"Username '{clean_username}' is already taken"
                    ) from error
            return _to_user_data(user)

    async def update_profile(
        self,
        user_id: str,
        *,
        display_name: str | None = None,
        name_color: str | None = None,
        avatar_key: str | None = None,
    ) -> UserData | None:
        db_user_id = _optional_entity_id(user_id)
        if db_user_id is None:
            return None
        try:
            validated_avatar = (
                validate_avatar_key(avatar_key) if avatar_key is not None else None
            )
        except ValueError as error:
            raise InvalidProfileDataError(str(error)) from error
        async with self._session_factory() as session:
            async with session.begin():
                stmt = select(User).where(User.id == db_user_id)
                result = await session.execute(stmt)
                user = result.scalar_one_or_none()
                if not user:
                    return None
                if display_name is not None:
                    user.display_name = display_name.strip() or user.display_name
                if name_color is not None:
                    user.name_color = name_color
                if avatar_key is not None:
                    user.avatar_key = validated_avatar
            return _to_user_data(user)

    async def replace_password_hash(
        self, user_id: str, expected_hash: str, new_hash: str
    ) -> bool:
        db_user_id = _optional_entity_id(user_id)
        if db_user_id is None or not expected_hash or not new_hash:
            return False
        async with self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    update(User)
                    .where(
                        User.id == db_user_id,
                        User.password_hash == expected_hash,
                    )
                    .values(password_hash=new_hash)
                )
                return bool(result.rowcount)

    async def merge_guest_into_account(
        self, source_user_id: str, target_user_id: str
    ) -> UserData:
        source_id = _optional_entity_id(source_user_id)
        target_id = _optional_entity_id(target_user_id)
        if source_id is None or target_id is None or source_id == target_id:
            raise IdentityMergeError("Guest and account identities must be distinct.")

        async with self._session_factory() as session:
            async with session.begin():
                # Both rows locked, ascending id first: the order every
                # writer of these rows uses (app.auth.erasure), so a merge, a
                # game save and a rebuild cannot wait on each other in a
                # cycle, and the rebuild below joins this transaction with
                # the source's games unable to move underneath it.
                locked = {
                    user.id: user
                    for user in (
                        await session.scalars(
                            select(User)
                            .where(User.id.in_([source_id, target_id]))
                            .order_by(User.id)
                            .with_for_update()
                        )
                    ).all()
                }
                source = locked.get(source_id)
                target = locked.get(target_id)
                existing_target = await session.scalar(
                    select(IdentityAlias.target_user_id).where(
                        IdentityAlias.source_user_id == source_id
                    )
                )
                if existing_target is not None:
                    if existing_target != target_id or target is None:
                        raise IdentityMergeError(
                            "Guest identity is already merged into another account."
                        )
                    return _to_user_data(target)
                if source is None or source.state != AccountState.ANONYMOUS.value:
                    raise IdentityMergeError("Only an anonymous guest can be merged.")
                if target is None or target.state != AccountState.REGISTERED.value:
                    raise IdentityMergeError(
                        "The merge target must be a registered account."
                    )

                source.state = AccountState.MERGED.value
                session.add(
                    IdentityAlias(
                        source_user_id=source.id,
                        target_user_id=target.id,
                    )
                )
                session.add(
                    AuditEvent(
                        id=generate_uuid(),
                        event_type="identity.guest_merged",
                        actor_user_id=target.id,
                        target_user_id=target.id,
                        target_type=AuditTargetType.USER.value,
                        target_id=str(target.id),
                        details={"source_user_id": str(source.id)},
                    )
                )
                # Blocks are account preferences, not historical identity
                # facts. Carry both outgoing mutes and incoming protection to
                # the registered identity, collapsing duplicates and any
                # source/target pair that would become a self-block.
                blocks = (
                    await session.scalars(
                        select(UserBlock).where(
                            or_(
                                UserBlock.blocker_user_id == source.id,
                                UserBlock.blocked_user_id == source.id,
                            )
                        )
                    )
                ).all()
                for block in blocks:
                    blocker_id = (
                        target.id
                        if block.blocker_user_id == source.id
                        else block.blocker_user_id
                    )
                    blocked_id = (
                        target.id
                        if block.blocked_user_id == source.id
                        else block.blocked_user_id
                    )
                    if blocker_id == blocked_id:
                        await session.delete(block)
                        continue
                    if (blocker_id, blocked_id) == (
                        block.blocker_user_id,
                        block.blocked_user_id,
                    ):
                        continue
                    # The pair is the primary key now, so a remap that lands
                    # on an existing pair is a duplicate to drop, not a row
                    # to rewrite.
                    duplicate = await session.scalar(
                        select(UserBlock.blocker_user_id).where(
                            UserBlock.blocker_user_id == blocker_id,
                            UserBlock.blocked_user_id == blocked_id,
                        )
                    )
                    if duplicate is not None:
                        await session.delete(block)
                    else:
                        block.blocker_user_id = blocker_id
                        block.blocked_user_id = blocked_id
                await _merge_friendships(session, source.id, target.id)
                await session.flush()
                # Only the guest's own days: this runs inside a sign-in, on
                # the web role's statement budget, and no other day's total
                # can have changed (#709).
                await fold_identity_into_account(
                    session,
                    source_user_id=source.id,
                    target_user_id=target.id,
                )
            return _to_user_data(target)

    async def touch_last_login(
        self, user_id: str, min_interval_seconds: float = 0.0
    ) -> UserData | None:
        db_user_id = _optional_entity_id(user_id)
        if db_user_id is None:
            return None
        now = datetime.now(timezone.utc)
        async with self._session_factory() as session:
            async with session.begin():
                # One conditional UPDATE with the row returned, rather than a
                # select, a write and a refresh (#556). Nothing comes back
                # when the last login is within the interval - the caller
                # already holds the row it read - or the account is gone.
                due = or_(
                    User.last_login_at.is_(None),
                    User.last_login_at < now - timedelta(seconds=min_interval_seconds),
                )
                user = await session.scalar(
                    update(User)
                    .where(User.id == db_user_id, *(() if min_interval_seconds <= 0 else (due,)))
                    .values(last_login_at=now)
                    .returning(User)
                )
            return _to_user_data(user) if user else None

    async def touch_last_active(self, user_id: str) -> UserData | None:
        db_user_id = _optional_entity_id(user_id)
        if db_user_id is None:
            return None
        async with self._session_factory() as session:
            async with session.begin():
                # One statement (#980): reading the row and then writing it
                # through the ORM was a SELECT and an UPDATE on every seat.
                user = await session.scalar(
                    update(User)
                    .where(User.id == db_user_id)
                    .values(last_active_at=datetime.now(timezone.utc))
                    .returning(User)
                )
            return _to_user_data(user) if user is not None else None

    async def touch_last_seen(self, user_id: str) -> None:
        db_user_id = _optional_entity_id(user_id)
        if db_user_id is None:
            return
        async with self._session_factory() as session:
            async with session.begin():
                # One UPDATE, no read: the handler that asks holds nothing
                # to refresh, and a row that is gone is simply not stamped.
                await session.execute(
                    update(User)
                    .where(User.id == db_user_id)
                    .values(last_seen_at=datetime.now(timezone.utc))
                )

    async def get_play_languages(self, user_id: str) -> tuple[str, ...]:
        db_user_id = _optional_entity_id(user_id)
        if db_user_id is None:
            return ()
        # One statement, so one round trip under `read_session`.
        async with read_session(self._session_factory) as session:
            row = (
                await session.execute(
                    select(UserSettings.prompt_language, UserSettings.extra_prompt_languages)
                    .join(User, User.id == UserSettings.user_id)
                    .where(
                        UserSettings.user_id == db_user_id,
                        User.state == AccountState.REGISTERED.value,
                    )
                )
            ).first()
        if row is None:
            return ()
        return (row[0], *row[1])

    async def get_stats(self, user_id: str) -> UserStats:
        db_user_id = _optional_entity_id(user_id)
        if db_user_id is None:
            return UserStats(user_id=user_id)
        async with self._session_factory() as session:
            canonical_id = await _canonical_user_id(session, db_user_id)
            statement = select(
                func.coalesce(func.sum(UserStatsDaily.games_played), 0),
                func.coalesce(func.sum(UserStatsDaily.games_won), 0),
                func.coalesce(func.sum(UserStatsDaily.total_score), 0),
                func.coalesce(func.sum(UserStatsDaily.turns_played), 0),
                func.coalesce(func.sum(UserStatsDaily.prompts_guessed), 0),
                func.coalesce(func.sum(UserStatsDaily.drawings_made), 0),
                func.coalesce(func.sum(UserStatsDaily.reactions_received), 0),
            ).where(UserStatsDaily.user_id == canonical_id)
            row = (await session.execute(statement)).one()
            games_played = int(row[0] or 0)
            games_won = int(row[1] or 0)
            total_score = int(row[2] or 0)
            turns_played = int(row[3] or 0)
            prompts_guessed = int(row[4] or 0)
            drawings_made = int(row[5] or 0)
            reactions_received = int(row[6] or 0)
            win_rate = (games_won / games_played) if games_played > 0 else 0.0
            average_score = (total_score / games_played) if games_played > 0 else 0.0

            return UserStats(
                user_id=_public_id(canonical_id),
                games_played=games_played,
                games_won=games_won,
                win_rate=round(win_rate, 4),
                total_score=total_score,
                average_score=round(average_score, 2),
                turns_played=turns_played,
                prompts_guessed=prompts_guessed,
                drawings_made=drawings_made,
                reactions_received=reactions_received,
            )


class SqlAlchemyGameHistoryRepository(GameHistoryRepository):
    """SQLAlchemy-backed implementation of GameHistoryRepository."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    @staticmethod
    def _payload_hash(
        game_record: GameRecordInput,
        participants: list[GameParticipantInput],
        turns: list[TurnRecordInput],
        score_events: list[ScoreEventInput] | None = None,
        reactions: list[TurnDrawingReactionInput] | None = None,
        drawings: list[TurnDrawingInput] | None = None,
    ) -> str:
        """Canonical digest used only to distinguish retries from conflicts."""
        payload = {
            "record": {
                "room_name": game_record.room_name,
                "scoring_mode": game_record.scoring_mode,
                "scoring_version": game_record.scoring_version,
                "score_ledger_version": game_record.score_ledger_version,
                "rule_snapshot_version": game_record.rule_snapshot_version,
                "rule_snapshot": game_record.rule_snapshot,
                "prompt_source_mode": game_record.prompt_source_mode,
                "prompt_source_list_ids": sorted(
                    game_record.prompt_source_list_ids
                ),
                "hint_mode": game_record.hint_mode,
                "drawing_seconds": game_record.drawing_seconds,
                "total_rounds": game_record.total_rounds,
                "player_count": game_record.player_count,
                "started_at": game_record.started_at.isoformat(),
                "finished_at": game_record.finished_at.isoformat(),
                "visibility": game_record.visibility,
            },
            # The drawings are content too (#541): a retry that carries
            # different bytes, or a drawing where the first attempt had
            # none, is a different game and must say so.
            "drawings": sorted(
                (
                    {
                        "turn_id": item.turn_id,
                        "unavailable_reason": item.unavailable_reason,
                        # The frame's digest either way: an envelope carries
                        # the drawing prepared, with the digest of the frame
                        # it came from (#1259).
                        "payload_sha256": (
                            item.stored.wire_sha256
                            if item.stored is not None
                            else None
                            if item.payload is None
                            else hashlib.sha256(item.payload).hexdigest()
                        ),
                    }
                    for item in drawings or []
                ),
                key=lambda item: item["turn_id"],
            ),
            "participants": sorted(
                (
                    {
                        "seat_id": item.seat_id,
                        "user_id": item.user_id,
                        "display_name": item.display_name,
                        "name_color": item.name_color,
                        "is_anonymous": item.is_anonymous,
                        "final_score": item.final_score,
                        "final_rank": item.final_rank,
                        "turns_played": item.turns_played,
                    }
                    for item in participants
                ),
                key=lambda item: item["seat_id"] or item["user_id"] or "",
            ),
            "turns": sorted(
                (
                    {
                        "id": item.id,
                        "round_number": item.round_number,
                        "turn_number": item.turn_number,
                        "drawer_user_id": item.drawer_user_id,
                        "drawer_seat_id": item.drawer_seat_id,
                        "prompt": item.prompt,
                        "prompt_version_id": item.prompt_version_id,
                        "prompt_source_kind": item.prompt_source_kind,
                        "duration_seconds": item.duration_seconds,
                        "guesser_count": item.guesser_count,
                        "prompt_auto_picked": item.prompt_auto_picked,
                        "stroke_count": item.stroke_count,
                        "end_reason": item.end_reason,
                        "wrong_guess_count": item.wrong_guess_count,
                        "near_miss_count": item.near_miss_count,
                        "prompt_offers": [
                            {
                                "position": offer.position,
                                "prompt": offer.prompt,
                                "selected": offer.selected,
                                "source_kind": offer.source_kind,
                                "prompt_version_id": offer.prompt_version_id,
                                "source_list_ids": sorted(
                                    offer.source_list_ids
                                ),
                            }
                            for offer in sorted(
                                item.prompt_offers, key=lambda value: value.position
                            )
                        ],
                        "participant_outcomes": [
                            {
                                "seat_id": outcome.seat_id,
                                "user_id": outcome.user_id,
                                "eligible": outcome.eligible,
                                "eligibility_reason": outcome.eligibility_reason,
                                "outcome": outcome.outcome,
                                "terminal_state": outcome.terminal_state,
                                "correct_guess_time_seconds": (
                                    outcome.correct_guess_time_seconds
                                ),
                                "wrong_guess_count": outcome.wrong_guess_count,
                                "near_miss_count": outcome.near_miss_count,
                                "hints_used": outcome.hints_used,
                                "points_spent_on_hints": (
                                    outcome.points_spent_on_hints
                                ),
                                "points_awarded": outcome.points_awarded,
                            }
                            for outcome in sorted(
                                item.participant_outcomes,
                                key=lambda value: value.seat_id,
                            )
                        ],
                    }
                    for item in turns
                ),
                key=lambda item: item["id"],
            ),
            # Part of the digest so that a retry carrying different reactions
            # is a conflict rather than a silent success returning the old id.
            "reactions": sorted(
                (
                    {
                        "turn_id": item.turn_id,
                        "seat_id": item.seat_id,
                        "user_id": item.user_id,
                        "emoji": item.emoji,
                        "set_version": item.set_version,
                    }
                    for item in reactions or []
                ),
                key=lambda item: (item["turn_id"], item["seat_id"]),
            ),
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    @database_operation_of("save_game")
    async def save_game(
        self,
        game_record: GameRecordInput,
        participants: list[GameParticipantInput],
        turns: list[TurnRecordInput],
        score_events: list[ScoreEventInput] | None = None,
        drawings: list[TurnDrawingInput] | None = None,
        reactions: list[TurnDrawingReactionInput] | None = None,
    ) -> str:
        score_events = list(score_events or [])
        reactions = list(reactions or [])
        record_id = (
            _entity_id(game_record.id) if game_record.id else generate_uuid()
        )
        game_source_ids = {
            _entity_id(list_id) for list_id in game_record.prompt_source_list_ids
        }
        if game_record.prompt_source_mode not in GAME_PROMPT_SOURCE_MODES:
            raise ValueError("Unknown game prompt source mode")
        # Everything CPU-bound is done on the history write's own threads and
        # before the transaction opens (#976): the content digest, then each
        # drawing's storage encoding - a pure Python decode and delta walk,
        # then zlib and SHA-256. It used to run on the event loop inside the
        # transaction that holds every player's `users` row: ~14 ms for a game
        # of eight ordinary drawings, ~217 ms for a stroke-heavy one, with
        # every room's strokes and timers waiting. The loop still shares the
        # GIL with the encode while it runs, but gets its turn every switch
        # interval, and the locks are held only for the writes.
        payload_hash = await _off_loop(
            self._payload_hash,
            game_record, participants, turns, score_events, reactions, drawings,
        )
        # A replay of a game already written is answered here, by one read,
        # before any drawing is encoded for nothing (#976 review). The check
        # inside the transaction below stays: it is the one that is exact.
        async with self._session_factory() as session:
            written = await session.scalar(
                select(GameRecord.payload_hash).where(GameRecord.id == record_id)
            )
        if written is not None:
            if written == payload_hash:
                return _public_id(record_id)
            raise GameHistoryConflictError(
                f"Game '{record_id}' already exists with different content."
            )
        prepared = await _off_loop(_prepare_drawings, drawings)
        sizing = _GameSizing()
        try:
            async with self._session_factory() as session:
                existing = await session.get(GameRecord, record_id)
                if existing is not None:
                    if existing.payload_hash == payload_hash:
                        return _public_id(record_id)
                    raise GameHistoryConflictError(
                        f"Game '{record_id}' already exists with different content."
                    )
                if game_record.player_count != len(participants):
                    raise ValueError(
                        "Game player_count must equal its persisted participant seats"
                    )
                referenced_user_ids = {
                    _entity_id(participant.user_id)
                    for participant in participants
                    if participant.user_id
                }
                referenced_user_ids.update(
                    _entity_id(turn.drawer_user_id)
                    for turn in turns
                    if turn.drawer_user_id
                )
                referenced_user_ids.update(
                    _entity_id(outcome.user_id)
                    for turn in turns
                    for outcome in turn.participant_outcomes
                    if outcome.user_id
                )
                referenced_user_ids.update(
                    _entity_id(reaction.user_id) for reaction in reactions
                )
                # A seat may still carry a guest identity that was merged
                # into an account mid-game; the erasure barrier resolves it
                # to that account and locks the account too. Resolving first
                # and locking everything in one ordered statement is what
                # keeps this write and a deletion of that account from each
                # holding what the other waits for.
                merge_targets = set(
                    (
                        await session.scalars(
                            select(IdentityAlias.target_user_id).where(
                                IdentityAlias.source_user_id.in_(referenced_user_ids)
                            )
                        )
                    ).all()
                ) if referenced_user_ids else set()
                # FOR UPDATE, not FOR SHARE: this transaction goes on to
                # write last_active_at on these rows, and two saves sharing a
                # player that both held the shared lock would deadlock on the
                # upgrade. Ascending id order is the erasure barrier's rule
                # (app.auth.erasure), so a save and a deletion cannot cycle.
                users = (
                    await session.scalars(
                        select(User)
                        .where(User.id.in_(referenced_user_ids | merge_targets))
                        .order_by(User.id)
                        .with_for_update()
                    )
                ).all()
                users_by_id = {user.id: user for user in users}
                missing = referenced_user_ids - users_by_id.keys()
                if missing:
                    raise ValueError(
                        "Cannot save game with unknown user ids: "
                        + ", ".join(sorted(str(value) for value in missing))
                    )
                # The erasure barrier (app.auth.erasure): a game finishes in
                # memory and is written a moment later, and a seat's account
                # may have been deleted in between - or the write may be a
                # retry from after the deletion. Every fact stays (the other
                # players' history, R-PRIV-05); what the erased identity
                # would have written back is what the deletion removed: its
                # name and colour on every snapshot, its drawings' pixels,
                # and the reactions those drawings had. The payload hash was
                # taken from the input above, so a retry of the same game is
                # still the same game and not a conflict.
                erased_user_ids = await erased_identity_ids(
                    session, referenced_user_ids
                )

                # The database refuses an unknown outcome too. This one names
                # the offending value instead of surfacing an integrity error
                # from a constraint the caller cannot see.
                if game_record.outcome not in GAME_OUTCOMES:
                    raise ValueError(
                        f"Unknown game outcome {game_record.outcome!r}"
                    )
                if game_record.visibility not in GAME_VISIBILITIES:
                    raise ValueError(
                        f"Unknown game visibility {game_record.visibility!r}"
                    )
                game_db = GameRecord(
                    id=record_id,
                    payload_hash=payload_hash,
                    room_name=game_record.room_name,
                    scoring_mode=game_record.scoring_mode,
                    scoring_version=game_record.scoring_version,
                    score_ledger_version=game_record.score_ledger_version,
                    rule_snapshot_version=game_record.rule_snapshot_version,
                    rule_snapshot=game_record.rule_snapshot,
                    prompt_source_mode=game_record.prompt_source_mode,
                    hint_mode=game_record.hint_mode,
                    drawing_seconds=game_record.drawing_seconds,
                    total_rounds=game_record.total_rounds,
                    player_count=game_record.player_count,
                    started_at=game_record.started_at,
                    finished_at=game_record.finished_at,
                    outcome=game_record.outcome,
                    visibility=game_record.visibility,
                )
                session.add(game_db)
                # The lists the game drew from that still exist: one deleted
                # while the game ran - or before a retry of its write - leaves
                # no provenance to point at, and the turns read the same
                # without it (#1358). Held against deletion until commit, so
                # the check cannot go stale before the rows land; a non-key
                # update such as a save is not blocked by it.
                present_sources = (
                    set(
                        (
                            await session.scalars(
                                select(PromptList.id)
                                .where(PromptList.id.in_(game_source_ids))
                                .with_for_update(read=True, key_share=True)
                            )
                        ).all()
                    )
                    if game_source_ids
                    else set()
                )
                session.add_all(
                    GamePromptSource(game_id=record_id, prompt_list_id=list_id)
                    for list_id in sorted(present_sources)
                )

                participant_inputs_by_id: dict[UUID, GameParticipantInput] = {}
                participant_snapshots_by_id: dict[
                    UUID, tuple[str, str | None, bool]
                ] = {}
                participant_ids_by_user: dict[UUID, UUID] = {}
                for p in participants:
                    participant_id = (
                        _entity_id(p.seat_id) if p.seat_id else generate_uuid()
                    )
                    if participant_id in participant_inputs_by_id:
                        raise ValueError(f"Duplicate participant seat id '{p.seat_id}'")
                    participant_user_id = (
                        _entity_id(p.user_id) if p.user_id else None
                    )
                    participant_user = (
                        users_by_id[participant_user_id]
                        if participant_user_id is not None
                        else None
                    )
                    participant_inputs_by_id[participant_id] = p
                    display_name_snapshot = (
                        p.display_name
                        if p.seat_id or participant_user is None
                        else participant_user.display_name
                    )
                    name_color_snapshot = (
                        p.name_color
                        if p.seat_id or participant_user is None
                        else participant_user.name_color
                    )
                    is_anonymous_snapshot = (
                        p.is_anonymous
                        if p.seat_id or participant_user is None
                        else participant_user.is_anonymous
                    )
                    participant_snapshots_by_id[participant_id] = (
                        TOMBSTONE_SNAPSHOT
                        if participant_user_id in erased_user_ids
                        else (
                            display_name_snapshot,
                            name_color_snapshot,
                            is_anonymous_snapshot,
                        )
                    )
                    (
                        display_name_snapshot,
                        name_color_snapshot,
                        is_anonymous_snapshot,
                    ) = participant_snapshots_by_id[participant_id]
                    if participant_user_id is not None:
                        participant_ids_by_user[participant_user_id] = participant_id
                    session.add(
                        GameParticipant(
                            id=participant_id,
                            game_id=record_id,
                            user_id=participant_user_id,
                            display_name_snapshot=display_name_snapshot,
                            name_color_snapshot=name_color_snapshot,
                            is_anonymous_snapshot=is_anonymous_snapshot,
                            final_score=p.final_score,
                            final_rank=p.final_rank,
                            turns_played=p.turns_played,
                        )
                    )

                created_turn_ids: set[UUID] = set()
                turn_inputs_by_id: dict[UUID, TurnRecordInput] = {}
                drawer_participant_ids_by_turn: dict[UUID, UUID] = {}
                outcome_inputs_by_key: dict[
                    tuple[UUID, UUID], TurnParticipantOutcomeInput
                ] = {}
                # Outcomes and score events are rows, not objects: a sixteen-
                # seat, ten-round game has 2,400 of the one and 2,560 of the
                # other, and each object the unit of work tracks and flushes
                # costs the loop far more than a row in one bulk insert does
                # (#1260). Nothing reads them back through the session.
                outcome_rows: list[dict[str, object]] = []
                score_event_rows: list[dict[str, object]] = []
                for r in turns:
                    if r.prompt_source_kind not in PROMPT_SOURCE_KINDS:
                        raise ValueError(
                            f"Turn '{r.id}' has an unknown prompt source kind"
                        )
                    if (r.prompt_source_kind == "curated") != bool(
                        r.prompt_version_id
                    ):
                        raise ValueError(
                            f"Turn '{r.id}' prompt source and version disagree"
                        )
                    rid = _entity_id(r.id)
                    if rid in created_turn_ids:
                        raise ValueError(f"Duplicate turn id '{r.id}'")
                    created_turn_ids.add(rid)
                    turn_inputs_by_id[rid] = r
                    drawer_user_id = (
                        _entity_id(r.drawer_user_id) if r.drawer_user_id else None
                    )
                    drawer_participant_id = (
                        _entity_id(r.drawer_seat_id)
                        if r.drawer_seat_id
                        else participant_ids_by_user.get(drawer_user_id)
                    )
                    drawer_participant = (
                        participant_inputs_by_id.get(drawer_participant_id)
                        if drawer_participant_id is not None
                        else None
                    )
                    if drawer_participant is None:
                        raise ValueError(
                            f"Turn '{r.id}' references an unknown drawer seat"
                        )
                    if drawer_participant.user_id != r.drawer_user_id:
                        raise ValueError(
                            f"Turn '{r.id}' drawer seat and user identity disagree"
                        )
                    drawer_participant_ids_by_turn[rid] = drawer_participant_id
                    drawer_snapshot = participant_snapshots_by_id[
                        drawer_participant_id
                    ]
                    session.add(
                        TurnRecord(
                            id=rid,
                            game_id=record_id,
                            round_number=r.round_number,
                            turn_number=r.turn_number,
                            drawer_user_id=drawer_user_id,
                            drawer_participant_id=drawer_participant_id,
                            drawer_display_name_snapshot=drawer_snapshot[0],
                            drawer_name_color_snapshot=drawer_snapshot[1],
                            drawer_is_anonymous_snapshot=drawer_snapshot[2],
                            prompt=r.prompt,
                            prompt_version_id=(
                                _entity_id(r.prompt_version_id)
                                if r.prompt_version_id
                                else None
                            ),
                            prompt_source_kind=r.prompt_source_kind,
                            duration_seconds=r.duration_seconds,
                            guesser_count=r.guesser_count,
                            prompt_auto_picked=r.prompt_auto_picked,
                            stroke_count=r.stroke_count,
                            end_reason=r.end_reason,
                            wrong_guess_count=r.wrong_guess_count,
                            near_miss_count=r.near_miss_count,
                        )
                    )
                    if r.prompt_offers and sum(
                        offer.selected for offer in r.prompt_offers
                    ) != 1:
                        raise ValueError(
                            f"Turn '{r.id}' must have exactly one selected prompt offer"
                        )
                    selected_offer = next(
                        (offer for offer in r.prompt_offers if offer.selected), None
                    )
                    if selected_offer is not None and (
                        selected_offer.prompt != r.prompt
                        or selected_offer.prompt_version_id != r.prompt_version_id
                        or selected_offer.source_kind != r.prompt_source_kind
                    ):
                        raise ValueError(
                            f"Turn '{r.id}' selected offer does not match its prompt identity"
                        )
                    for offer in r.prompt_offers:
                        if offer.source_kind not in PROMPT_OFFER_SOURCE_KINDS:
                            raise ValueError(
                                f"Turn '{r.id}' offer has an unknown source kind"
                            )
                        offer_source_ids = {
                            _entity_id(list_id) for list_id in offer.source_list_ids
                        }
                        if not offer_source_ids.issubset(game_source_ids):
                            raise ValueError(
                                f"Turn '{r.id}' offer source is not in the game pool"
                            )
                        if offer.source_kind == "curated" and (
                            not offer.prompt_version_id or not offer_source_ids
                        ):
                            raise ValueError(
                                f"Turn '{r.id}' curated offer lacks exact source identity"
                            )
                        if offer.source_kind != "curated" and (
                            offer.prompt_version_id or offer_source_ids
                        ):
                            raise ValueError(
                                f"Turn '{r.id}' ephemeral offer cannot claim curated identity"
                            )
                        offer_id = generate_uuid()
                        session.add(
                            TurnPromptOffer(
                                id=offer_id,
                                turn_id=rid,
                                position=offer.position,
                                prompt_version_id=(
                                    _entity_id(offer.prompt_version_id)
                                    if offer.prompt_version_id
                                    else None
                                ),
                                prompt_snapshot=offer.prompt,
                                selected=offer.selected,
                                source_kind=offer.source_kind,
                            )
                        )
                        kept_sources = sorted(offer_source_ids & present_sources)
                        session.add_all(
                            TurnPromptOfferSource(offer_id=offer_id, prompt_list_id=list_id)
                            for list_id in kept_sources
                        )
                        sizing.offer_sources += len(kept_sources)

                    if r.participant_outcomes:
                        if r.guesser_count != sum(
                            outcome.eligible for outcome in r.participant_outcomes
                        ):
                            raise ValueError(
                                f"Turn '{r.id}' guesser count disagrees with outcomes"
                            )
                        if r.wrong_guess_count != sum(
                            outcome.wrong_guess_count
                            for outcome in r.participant_outcomes
                        ) or r.near_miss_count != sum(
                            outcome.near_miss_count
                            for outcome in r.participant_outcomes
                        ):
                            raise ValueError(
                                f"Turn '{r.id}' aggregate attempts disagree with outcomes"
                            )
                    for outcome in r.participant_outcomes:
                        participant_id = _entity_id(outcome.seat_id)
                        participant = participant_inputs_by_id.get(participant_id)
                        if participant is None:
                            raise ValueError(
                                f"Turn '{r.id}' outcome references an unknown seat"
                            )
                        if participant_id == drawer_participant_id:
                            raise ValueError(
                                f"Turn '{r.id}' drawer cannot have a guesser outcome"
                            )
                        if participant.user_id != outcome.user_id:
                            raise ValueError(
                                f"Turn '{r.id}' outcome seat and user disagree"
                            )
                        if (
                            outcome.eligibility_reason
                            not in TURN_ELIGIBILITY_REASONS
                            or outcome.outcome not in TURN_PARTICIPANT_OUTCOMES
                            or outcome.terminal_state not in TURN_PARTICIPANT_STATES
                        ):
                            raise ValueError(
                                f"Turn '{r.id}' outcome has an unknown stored state"
                            )
                        if outcome.eligible != (
                            outcome.eligibility_reason == "eligible"
                        ) or outcome.eligible == (outcome.outcome == "ineligible"):
                            raise ValueError(
                                f"Turn '{r.id}' outcome eligibility is inconsistent"
                            )
                        if (outcome.outcome == "correct") != (
                            outcome.correct_guess_time_seconds is not None
                        ):
                            raise ValueError(
                                f"Turn '{r.id}' outcome and correct time disagree"
                            )
                        numeric_values = (
                            outcome.wrong_guess_count,
                            outcome.near_miss_count,
                            outcome.hints_used,
                            outcome.points_spent_on_hints,
                        )
                        if any(value < 0 for value in numeric_values) or (
                            outcome.correct_guess_time_seconds is not None
                            and not 0
                            <= outcome.correct_guess_time_seconds
                            <= r.duration_seconds
                        ):
                            raise ValueError(
                                f"Turn '{r.id}' outcome contains invalid counters or time"
                            )
                        if (outcome.outcome == "correct") != (
                            outcome.points_awarded is not None
                        ) or (outcome.points_awarded or 0) < 0:
                            raise ValueError(
                                f"Turn '{r.id}' outcome and awarded points disagree"
                            )
                        key = (rid, participant_id)
                        if key in outcome_inputs_by_key:
                            raise ValueError(
                                f"Turn '{r.id}' contains duplicate participant outcomes"
                            )
                        outcome_inputs_by_key[key] = outcome
                        outcome_rows.append(
                            {
                                "game_id": record_id,
                                "turn_id": rid,
                                "participant_id": participant_id,
                                "eligible": outcome.eligible,
                                "eligibility_reason": outcome.eligibility_reason,
                                "outcome": outcome.outcome,
                                "terminal_state": outcome.terminal_state,
                                "correct_guess_time_seconds": (
                                    outcome.correct_guess_time_seconds
                                ),
                                "wrong_guess_count": outcome.wrong_guess_count,
                                "near_miss_count": outcome.near_miss_count,
                                "hints_used": outcome.hints_used,
                                "points_spent_on_hints": (
                                    outcome.points_spent_on_hints
                                ),
                                "points_awarded": outcome.points_awarded,
                            }
                        )

                # Drawings ride in the same transaction as their turns: the
                # bytes live only in the process that just played the game, so
                # a row written now and filled in later could never be
                # completed by any retry.
                drawing_rows: dict[UUID, TurnDrawing] = {}
                for drawing, prepared_drawing in zip(drawings or [], prepared, strict=True):
                    drawing_turn_id = _optional_entity_id(drawing.turn_id)
                    if (
                        drawing_turn_id is None
                        or drawing_turn_id not in created_turn_ids
                    ):
                        raise ValueError(
                            f"Drawing references unknown turn_id '{drawing.turn_id}'"
                        )
                    drawer_id = turn_inputs_by_id[drawing_turn_id].drawer_user_id
                    if drawer_id and _entity_id(drawer_id) in erased_user_ids:
                        session.add(
                            _erased_turn_drawing(drawing_turn_id, record_id)
                        )
                        continue
                    if isinstance(prepared_drawing, _UnpreparedDrawing):
                        raise prepared_drawing.error
                    drawing_row = _turn_drawing(
                        drawing, drawing_turn_id, record_id, sizing, prepared_drawing
                    )
                    drawing_rows[drawing_turn_id] = drawing_row
                    session.add(drawing_row)

                # Reactions given while the game was live. They are checked
                # against the rows being written rather than the database,
                # for the same reason as everything else in this transaction:
                # a reaction on a turn that did not survive, or from a seat
                # that is not in this game, has nothing truthful to point at.
                reaction_drawer_ids: list[UUID | None] = []
                seen_reactions: set[tuple[UUID, UUID]] = set()
                written_reactions: Counter[UUID] = Counter()
                for reaction in reactions:
                    reaction_turn_id = _optional_entity_id(reaction.turn_id)
                    if (
                        reaction_turn_id is None
                        or reaction_turn_id not in created_turn_ids
                    ):
                        raise ValueError(
                            f"Reaction references unknown turn_id '{reaction.turn_id}'"
                        )
                    reaction_seat_id = _optional_entity_id(reaction.seat_id)
                    if (
                        reaction_seat_id is None
                        or reaction_seat_id not in participant_inputs_by_id
                    ):
                        raise ValueError(
                            f"Reaction references unknown seat_id '{reaction.seat_id}'"
                        )
                    if participant_inputs_by_id[reaction_seat_id].user_id != (
                        reaction.user_id
                    ):
                        raise ValueError(
                            "Reaction seat and user identity disagree"
                        )
                    if participant_inputs_by_id[reaction_seat_id].is_anonymous:
                        raise ValueError("Guest seats cannot hold a reaction")
                    if drawer_participant_ids_by_turn[reaction_turn_id] == (
                        reaction_seat_id
                    ):
                        raise ValueError(
                            "A drawer cannot react to their own drawing"
                        )
                    if reaction.emoji not in REACTION_EMOJI_CODES:
                        raise ValueError(
                            f"Unknown reaction emoji {reaction.emoji!r}"
                        )
                    key = (reaction_turn_id, reaction_seat_id)
                    if key in seen_reactions:
                        raise ValueError(
                            "A seat holds at most one reaction per drawing"
                        )
                    seen_reactions.add(key)
                    drawer_user_id = turn_inputs_by_id[reaction_turn_id].drawer_user_id
                    reaction_drawer_ids.append(
                        _entity_id(drawer_user_id) if drawer_user_id else None
                    )
                    if drawer_user_id and _entity_id(drawer_user_id) in erased_user_ids:
                        # The drawing it was about is erased above; a
                        # reaction to nothing is not kept (R-PRIV-05 keeps
                        # the ones this seat *gave*, on other drawings).
                        continue
                    session.add(
                        TurnDrawingReaction(
                            game_id=record_id,
                            turn_id=reaction_turn_id,
                            user_id=_entity_id(reaction.user_id),
                            participant_id=reaction_seat_id,
                            emoji=reaction.emoji,
                            set_version=reaction.set_version,
                        )
                    )
                    written_reactions[reaction_turn_id] += 1
                # The Gallery's projections ride in the same transaction as
                # the rows they count (R-GAL-05).
                for drawing_turn_id, drawing_row in drawing_rows.items():
                    count = written_reactions.get(drawing_turn_id, 0)
                    drawing_row.reaction_count = count
                    drawing_row.hot_score = hot_score(count, game_record.finished_at)

                if game_record.score_ledger_version not in (0, 1):
                    raise ValueError("Unsupported score ledger version")
                if game_record.score_ledger_version == 0 and score_events:
                    raise ValueError("Legacy games cannot claim score events")
                if game_record.score_ledger_version == 1:
                    if game_record.scoring_mode == "none":
                        if score_events:
                            raise ValueError(
                                "No-scoring games cannot contain hypothetical score events"
                            )
                        if any(participant.final_score != 0 for participant in participants):
                            raise ValueError(
                                "No-scoring game participant totals must remain zero"
                            )

                    ordered_events = sorted(
                        score_events, key=lambda event: event.event_order
                    )
                    if [event.event_order for event in ordered_events] != list(
                        range(1, len(ordered_events) + 1)
                    ):
                        raise ValueError(
                            "Score event order must be unique and consecutive from one"
                        )

                    event_inputs_by_order: dict[int, ScoreEventInput] = {}
                    actual_gameplay: defaultdict[
                        tuple[str, UUID, UUID], list[int]
                    ] = defaultdict(list)
                    ledger_totals: defaultdict[UUID, int] = defaultdict(int)
                    for event in ordered_events:
                        participant_id = _entity_id(event.participant_seat_id)
                        participant = participant_inputs_by_id.get(participant_id)
                        if participant is None:
                            raise ValueError(
                                "Score event references an unknown participant seat"
                            )
                        if participant.user_id != event.participant_user_id:
                            raise ValueError(
                                "Score event seat and user identity disagree"
                            )
                        if event.event_type not in SCORE_EVENT_TYPES:
                            raise ValueError("Score event has an unknown type")
                        if event.points_delta == 0 or (
                            event.event_type in {"guess_award", "drawer_bonus"}
                            and event.points_delta < 0
                        ) or (
                            event.event_type == "hint_charge"
                            and event.points_delta > 0
                        ):
                            raise ValueError("Score event delta is invalid for its type")
                        turn_id = _entity_id(event.turn_id) if event.turn_id else None
                        if turn_id is not None and turn_id not in turn_inputs_by_id:
                            raise ValueError("Score event references an unknown turn")
                        correction_order = event.corrects_event_order
                        if event.event_type == "correction":
                            # Only entries already walked are targets, so a
                            # forward or self reference is unknown here and
                            # ck_score_events_corrects_earlier agrees below.
                            corrected = (
                                event_inputs_by_order.get(correction_order)
                                if correction_order is not None
                                else None
                            )
                            if corrected is None:
                                raise ValueError(
                                    "A correction must target an earlier score event"
                                )
                            if (
                                corrected.participant_seat_id
                                != event.participant_seat_id
                            ):
                                raise ValueError(
                                    "A correction must target the same participant"
                                )
                        elif correction_order is not None or turn_id is None:
                            raise ValueError(
                                "Gameplay score events require a turn and cannot correct"
                            )
                        else:
                            actual_gameplay[
                                (event.event_type, turn_id, participant_id)
                            ].append(event.points_delta)

                        event_inputs_by_order[event.event_order] = event
                        ledger_totals[participant_id] += event.points_delta
                        score_event_rows.append(
                            {
                                "game_id": record_id,
                                "participant_id": participant_id,
                                "turn_id": turn_id,
                                "event_order": event.event_order,
                                "event_type": event.event_type,
                                "points_delta": event.points_delta,
                                "corrects_event_order": correction_order,
                            }
                        )

                    expected_gameplay: defaultdict[
                        tuple[str, UUID, UUID], list[int]
                    ] = defaultdict(list)
                    if game_record.scoring_mode != "none":
                        drawer_bonuses: defaultdict[tuple[UUID, UUID], int] = (
                            defaultdict(int)
                        )
                        for (turn_id, participant_id), outcome in outcome_inputs_by_key.items():
                            if outcome.outcome != "correct":
                                continue
                            gross_award = (
                                outcome.points_awarded + outcome.points_spent_on_hints
                            )
                            if gross_award > 0:
                                expected_gameplay[
                                    ("guess_award", turn_id, participant_id)
                                ].append(gross_award)
                            if outcome.points_spent_on_hints > 0:
                                expected_gameplay[
                                    ("hint_charge", turn_id, participant_id)
                                ].append(-outcome.points_spent_on_hints)
                            drawer_bonuses[
                                (turn_id, drawer_participant_ids_by_turn[turn_id])
                            ] += outcome.points_awarded
                        for (turn_id, drawer_id), bonus in drawer_bonuses.items():
                            if bonus > 0:
                                expected_gameplay[
                                    ("drawer_bonus", turn_id, drawer_id)
                                ].append(bonus)
                    if dict(actual_gameplay) != dict(expected_gameplay):
                        raise ValueError(
                            "Score events do not match guess awards, hint charges, and drawer bonuses"
                        )
                    for participant_id, participant in participant_inputs_by_id.items():
                        if ledger_totals[participant_id] != participant.final_score:
                            raise ValueError(
                                "Score event ledger does not reconcile to final participant scores"
                            )

                # The turns and seats they point at go first, then the rows,
                # in event order: a correction names an earlier event, which
                # an earlier row wrote. `render_nulls` because a bulk insert
                # otherwise leaves a row's None values out and batches only
                # neighbouring rows with the same columns: a right guesser
                # beside a wrong one - a time and an award beside none - split
                # a real game's outcomes into ~1,600 statements (#1260 review).
                await session.flush()
                if outcome_rows:
                    await session.execute(
                        insert(TurnParticipantOutcome).execution_options(render_nulls=True),
                        outcome_rows,
                    )
                if score_event_rows:
                    await session.execute(
                        insert(ScoreEvent).execution_options(render_nulls=True),
                        score_event_rows,
                    )

                await increment_user_stats_projection(
                    session,
                    finished_at=game_record.finished_at,
                    counts_as_played=(
                        game_record.outcome == GameOutcome.FINISHED.value
                    ),
                    participants=[
                        (
                            _entity_id(participant.user_id)
                            if participant.user_id
                            else None,
                            participant.final_score,
                            participant.final_rank,
                        )
                        for participant in participants
                    ],
                    turn_drawer_ids=[
                        _entity_id(turn.drawer_user_id)
                        if turn.drawer_user_id
                        else None
                        for turn in turns
                    ],
                    guess_user_ids=[
                        _entity_id(outcome.user_id) if outcome.user_id else None
                        for turn in turns
                        for outcome in turn.participant_outcomes
                        if outcome.outcome == "correct"
                    ],
                    reaction_drawer_ids=reaction_drawer_ids,
                )

                if referenced_user_ids:
                    await session.execute(
                        update(User)
                        .where(User.id.in_(referenced_user_ids))
                        .values(last_active_at=datetime.now(timezone.utc))
                    )
                await session.commit()
            sizing.record(
                participants=len(participants),
                turns=turns,
                score_events=len(score_events),
                drawings=len(drawings or ()),
                reactions=len(reactions),
                prompt_sources=len(present_sources),
            )
        except IntegrityError as error:
            # A concurrent writer may have committed the same stable ID after
            # our preflight read. Re-read outside the rolled-back transaction.
            async with self._session_factory() as session:
                existing = await session.get(GameRecord, record_id)
                if existing is None:
                    # Preserve unrelated natural-key/check failures; they are
                    # not evidence that the stable game ID was reused.
                    raise
                if existing.payload_hash == payload_hash:
                    return _public_id(record_id)
                raise GameHistoryConflictError(
                    f"Game '{record_id}' conflicted with a concurrent write."
                ) from error
        return _public_id(record_id)

    async def get_turn_drawing(
        self,
        game_id: str,
        turn_id: str,
        *,
        requesting_user_id: str,
    ) -> TurnDrawingDetail | None:
        db_game_id = _optional_entity_id(game_id)
        db_turn_id = _optional_entity_id(turn_id)
        db_requesting_user_id = _optional_entity_id(requesting_user_id)
        if db_game_id is None or db_turn_id is None or db_requesting_user_id is None:
            return None
        async with self._session_factory() as session:
            identity_ids = await _identity_ids(session, db_requesting_user_id)
            # Authorization is part of the query rather than a check on the
            # result, so the blob is never read for someone who may not see it.
            # Filtering the drawing by game as well as by turn means a turn id
            # borrowed from another game matches nothing by construction.
            participated = (
                select(GameParticipant.id)
                .where(
                    GameParticipant.game_id == db_game_id,
                    GameParticipant.user_id.in_(identity_ids),
                )
                .exists()
            )
            row = await session.scalar(
                select(TurnDrawing).where(
                    TurnDrawing.turn_id == db_turn_id,
                    TurnDrawing.game_id == db_game_id,
                    TurnDrawing.status == TurnDrawingStatus.READY.value,
                    TurnDrawing.payload.is_not(None),
                    participated,
                )
            )
        if row is None:
            return None
        return TurnDrawingDetail(
            turn_id=_public_id(row.turn_id),
            payload=row.payload,
            checksum_sha256=row.checksum_sha256 or "",
        )

    async def get_turn_drawing_checksum(
        self,
        game_id: str,
        turn_id: str,
        *,
        requesting_user_id: str,
    ) -> str | None:
        db_game_id = _optional_entity_id(game_id)
        db_turn_id = _optional_entity_id(turn_id)
        db_requesting_user_id = _optional_entity_id(requesting_user_id)
        if db_game_id is None or db_turn_id is None or db_requesting_user_id is None:
            return None
        async with self._session_factory() as session:
            identity_ids = await _identity_ids(session, db_requesting_user_id)
            participated = (
                select(GameParticipant.id)
                .where(
                    GameParticipant.game_id == db_game_id,
                    GameParticipant.user_id.in_(identity_ids),
                )
                .exists()
            )
            # The same predicate as the drawing itself - a drawing that is
            # not there to download has no validator either - selecting the
            # checksum column alone, never the blob beside it (R-PLAT-14).
            checksum = await session.scalar(
                select(TurnDrawing.checksum_sha256).where(
                    TurnDrawing.turn_id == db_turn_id,
                    TurnDrawing.game_id == db_game_id,
                    TurnDrawing.status == TurnDrawingStatus.READY.value,
                    TurnDrawing.payload.is_not(None),
                    participated,
                )
            )
        return checksum or None

    async def set_drawing_reaction(
        self,
        game_id: str | None,
        turn_id: str,
        *,
        requesting_user_id: str,
        emoji: str | None,
        from_gallery: bool = False,
    ) -> DrawingReactionResult | None:
        db_game_id = _optional_entity_id(game_id) if game_id is not None else None
        db_turn_id = _optional_entity_id(turn_id)
        db_user_id = _optional_entity_id(requesting_user_id)
        if db_turn_id is None or db_user_id is None:
            return None
        if game_id is not None and db_game_id is None:
            return None
        if db_game_id is None and not from_gallery:
            return None
        if emoji is not None and emoji not in OFFERED_REACTION_EMOJI_CODES:
            return None
        async with self._session_factory() as session:
            async with session.begin():
                identity_ids = await _identity_ids(session, db_user_id)
                # Registered is a property of the account now, not of the seat
                # as it was recorded: a guest who claimed their account after
                # the game may react from history like anyone else.
                account = await session.get(User, identity_ids[0])
                if (
                    account is None
                    or account.is_anonymous
                    or account.state != AccountState.REGISTERED.value
                ):
                    return None
                turn_query = (
                    select(TurnRecord)
                    .where(TurnRecord.id == db_turn_id)
                    .options(
                        selectinload(TurnRecord.drawing).load_only(
                            TurnDrawing.status
                        ),
                        selectinload(TurnRecord.game),
                    )
                )
                if db_game_id is not None:
                    turn_query = turn_query.where(TurnRecord.game_id == db_game_id)
                turn = await session.scalar(turn_query)
                if turn is None:
                    return None
                # The reactor's seat, when they had one: written beside the
                # account so the room and history keep naming the reaction.
                seat = await session.scalar(
                    select(GameParticipant)
                    .where(
                        GameParticipant.game_id == turn.game_id,
                        GameParticipant.user_id.in_(identity_ids),
                    )
                    .order_by(GameParticipant.id)
                    .limit(1)
                )
                # The drawer's account, shared, before the drawing: the
                # write below moves the drawer's `user_stats_daily` row by
                # one, and a rebuild holds the account `FOR UPDATE` from its
                # read of the facts to its replacement of the rows - a +1
                # committed in between would be replaced by the older total.
                # Shared, because reactions to one drawer's drawings need not
                # wait on each other; before the drawing row, because every
                # writer that holds both (erasure, the pin write) takes the
                # account first. The whole identity, ascending, in one
                # statement - the erasure barrier's rule. The turn and its
                # drawing were read before this lock: a deletion it waited
                # behind has since erased the drawing and its reactions, so
                # what the lock says decides, not what was loaded (R-REACT-10).
                if turn.drawer_user_id is not None and await erased_identity_ids(
                    session, (turn.drawer_user_id,)
                ):
                    return None
                # The drawing row, locked: the count and the Hot score kept
                # on it are set from the rows after this write, and two
                # reactions landing together must not both count their own.
                drawing_row = await session.scalar(
                    select(TurnDrawing)
                    .where(TurnDrawing.turn_id == db_turn_id)
                    .options(defer(TurnDrawing.payload))
                    .with_for_update()
                )
                if from_gallery:
                    # The gallery predicate (R-GAL-01): a public game with a
                    # kept drawing. Not a seat - that is the point of the door.
                    if turn.game.visibility != GameVisibility.PUBLIC.value:
                        return None
                    if not _gallery_shows(drawing_row):
                        return None
                elif seat is None:
                    return None
                # By seat and by account: a drawer who left and rejoined may
                # hold a second seat, and a merged identity a second id.
                if (
                    seat is not None and turn.drawer_participant_id == seat.id
                ) or turn.drawer_user_id in identity_ids:
                    return None
                # An erased drawing takes its reactions with it and takes no
                # new ones; there is nothing left to react to.
                if (
                    turn.drawing is not None
                    and turn.drawing.status == TurnDrawingStatus.DELETED.value
                ):
                    return None

                existing = await session.scalar(
                    select(TurnDrawingReaction).where(
                        TurnDrawingReaction.turn_id == db_turn_id,
                        TurnDrawingReaction.user_id.in_(identity_ids),
                    )
                )
                delta = 0
                if emoji is None:
                    if existing is not None:
                        await session.delete(existing)
                        delta = -1
                elif existing is None:
                    session.add(
                        TurnDrawingReaction(
                            game_id=turn.game_id,
                            turn_id=db_turn_id,
                            user_id=identity_ids[0],
                            participant_id=seat.id if seat is not None else None,
                            emoji=emoji,
                            set_version=REACTION_SET_VERSION,
                        )
                    )
                    delta = 1
                elif existing.emoji != emoji:
                    existing.emoji = emoji
                    existing.set_version = REACTION_SET_VERSION
                await session.flush()
                if delta and turn.drawer_user_id is not None:
                    await adjust_reactions_received(
                        session,
                        user_id=turn.drawer_user_id,
                        finished_at=turn.game.finished_at,
                        delta=delta,
                    )
                # Nothing here hydrates a row per reaction (#897). Anyone
                # signed in may react from the Gallery, so the rows behind one
                # drawing are bounded by nothing, and every other reaction to
                # it waits on this lock: the counts come grouped by code, the
                # named list is the seated rows, and the projection is still
                # set from the rows (R-GAL-05) - their grouped total, not an
                # increment of what the column said.
                summary = (await _reaction_summaries(session, (db_turn_id,)))[db_turn_id]
                if drawing_row is not None:
                    total = sum(summary.counts.values())
                    drawing_row.reaction_count = total
                    drawing_row.hot_score = hot_score(total, turn.game.finished_at)
                return DrawingReactionResult(
                    turn_id=_public_id(db_turn_id),
                    seat_id=_public_id(seat.id) if seat is not None else None,
                    emoji=emoji,
                    reactions=summary.details,
                    reaction_counts=summary.counts,
                )

    @database_operation_of("gallery_page")
    async def list_gallery(
        self,
        *,
        sort: str = "hot",
        window: str = "all",
        limit: int = 24,
        cursor: str | None = None,
        requesting_user_id: str | None = None,
        shelf_filter: str | None = None,
    ) -> GalleryPage:
        """One page of the Gallery (R-GAL-04).

        One predicate decides what is in it (`_gallery_predicate`), the same
        one the bytes route and the reaction door read, so a takedown or an
        erasure drops a drawing out of all three without a second code path
        agreeing to it. The orders read the projections kept on the row
        (R-GAL-05) rather than counting reactions, and every order breaks
        ties by the game's finish and then the turn id, so two reads agree.

        Pages are keyed on where the last row stood, not counted (#1072): a
        game finishing between two reads ranks above the cut in every order,
        and an offset served the row at the cut twice. A Hot score that the
        rebuild moved between two reads can still shift a row across the
        cut - a ranked feed has no fixed page boundary - which is the one
        drift left, and a reload's to settle.
        """
        if sort not in ("hot", "new", "top") or window not in TOP_WINDOWS:
            return GalleryPage(entries=(), next_cursor=None)
        requester_id = _optional_entity_id(requesting_user_id)
        limit = max(1, min(int(limit), MAX_GALLERY_PAGE))
        after = _decode_gallery_cursor(cursor, sort=sort)
        served = after[3] if after else 0
        # The community catalogue's rule, for the same reason: nobody reaches
        # this deep by looking, so a deeper page is a scrape.
        if served >= MAX_GALLERY_OFFSET:
            return GalleryPage(entries=(), next_cursor=None)
        stmt = (
            select(
                TurnRecord,
                GameRecord.finished_at,
                TurnDrawing.reaction_count,
                TurnDrawing.hot_score,
            )
            .join(GameRecord, GameRecord.id == TurnRecord.game_id)
            .join(TurnDrawing, TurnDrawing.turn_id == TurnRecord.id)
            .where(*_gallery_predicate())
        )
        if shelf_filter == "released":
            stmt = stmt.where(
                select(GalleryShelfReview.turn_id)
                .where(
                    GalleryShelfReview.turn_id == TurnRecord.id,
                    GalleryShelfReview.decision == GalleryShelfDecision.RELEASED.value,
                )
                .exists()
            )
        elif shelf_filter == "undecided":
            stmt = stmt.where(
                ~select(GalleryShelfReview.turn_id)
                .where(GalleryShelfReview.turn_id == TurnRecord.id)
                .exists()
            )
        elif shelf_filter is not None:
            return GalleryPage(entries=(), next_cursor=None)
        now = datetime.now(timezone.utc)
        if sort == "new":
            order = (GameRecord.finished_at.desc(), TurnRecord.id.desc())
            sort_column = None
        elif sort == "top":
            since = TOP_WINDOWS[window]
            if since is not None:
                stmt = stmt.where(GameRecord.finished_at >= now - since)
            order = (
                TurnDrawing.reaction_count.desc(),
                GameRecord.finished_at.asc(),
                TurnRecord.id.asc(),
            )
            sort_column = TurnDrawing.reaction_count
        else:
            stmt = stmt.where(GameRecord.finished_at >= now - HOT_HORIZON)
            order = (
                TurnDrawing.hot_score.desc(),
                GameRecord.finished_at.asc(),
                TurnRecord.id.asc(),
            )
            sort_column = TurnDrawing.hot_score
        if after is not None:
            after_key, after_finished, after_id, _ = after
            if sort_column is None:
                # New: strictly later in the order means an earlier finish,
                # or the same finish and a smaller id.
                stmt = stmt.where(
                    or_(
                        GameRecord.finished_at < after_finished,
                        and_(GameRecord.finished_at == after_finished, TurnRecord.id < after_id),
                    )
                )
            elif after_key is not None:
                later_in_tie = or_(
                    GameRecord.finished_at > after_finished,
                    and_(GameRecord.finished_at == after_finished, TurnRecord.id > after_id),
                )
                stmt = stmt.where(
                    or_(sort_column < after_key, and_(sort_column == after_key, later_in_tie))
                )
        stmt = stmt.order_by(*order).limit(limit + 1)
        async with self._session_factory() as session:
            viewer_ids: tuple[UUID, ...] = (
                await _identity_ids(session, requester_id) if requester_id else ()
            )
            fetched = (await session.execute(stmt)).all()
            has_more = len(fetched) > limit
            fetched = fetched[:limit]
            rows = [(turn, finished_at, count) for turn, finished_at, count, _ in fetched]
            last_hot_score = fetched[-1][3] if fetched else None
            summaries = await _reaction_summaries(
                session, [turn.id for turn, _, _ in rows], viewer_ids
            )
        entries = []
        last_key: float | int | None = None
        for turn, finished_at, _count in rows:
            summary = summaries.get(turn.id, _NO_REACTIONS)
            entries.append(
                GalleryEntry(
                    turn_id=_public_id(turn.id),
                    round_number=turn.round_number,
                    turn_number=turn.turn_number,
                    drawer_display_name=turn.drawer_display_name_snapshot,
                    drawer_name_color=turn.drawer_name_color_snapshot,
                    drawer_is_anonymous=turn.drawer_is_anonymous_snapshot,
                    prompt=turn.prompt,
                    stroke_count=turn.stroke_count,
                    finished_at=finished_at,
                    reaction_counts=summary.counts,
                    my_reaction=summary.my_reaction,
                    drawn_by_me=turn.drawer_user_id in viewer_ids,
                )
            )
        next_cursor = None
        if has_more:
            last_turn, last_finished, last_count = rows[-1]
            if sort == "top":
                last_key = last_count
            elif sort == "hot":
                last_key = last_hot_score
            next_cursor = _encode_gallery_cursor(
                sort, last_key, last_finished, last_turn.id, served + len(rows)
            )
        return GalleryPage(entries=tuple(entries), next_cursor=next_cursor)

    async def get_gallery_entry(
        self, turn_id: str, *, requesting_user_id: str | None = None
    ) -> GalleryEntry | None:
        db_turn_id = _optional_entity_id(turn_id)
        if db_turn_id is None:
            return None
        requester_id = _optional_entity_id(requesting_user_id)
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(TurnRecord, GameRecord.finished_at)
                    .join(GameRecord, GameRecord.id == TurnRecord.game_id)
                    .join(TurnDrawing, TurnDrawing.turn_id == TurnRecord.id)
                    .where(TurnRecord.id == db_turn_id, *_gallery_predicate())
                )
            ).first()
            if row is None:
                return None
            turn, finished_at = row
            viewer_ids: tuple[UUID, ...] = (
                await _identity_ids(session, requester_id) if requester_id else ()
            )
            summary = (await _reaction_summaries(session, [turn.id], viewer_ids)).get(
                turn.id, _NO_REACTIONS
            )
        return GalleryEntry(
            turn_id=_public_id(turn.id),
            round_number=turn.round_number,
            turn_number=turn.turn_number,
            drawer_display_name=turn.drawer_display_name_snapshot,
            drawer_name_color=turn.drawer_name_color_snapshot,
            drawer_is_anonymous=turn.drawer_is_anonymous_snapshot,
            prompt=turn.prompt,
            stroke_count=turn.stroke_count,
            finished_at=finished_at,
            reaction_counts=summary.counts,
            my_reaction=summary.my_reaction,
            drawn_by_me=turn.drawer_user_id in viewer_ids,
        )

    async def set_gallery_decision(
        self,
        turn_id: str,
        *,
        decision: str,
        decided_by_user_id: str,
    ) -> tuple[str, str | None] | None:
        db_turn_id = _optional_entity_id(turn_id)
        db_reviewer_id = _optional_entity_id(decided_by_user_id)
        if db_turn_id is None or db_reviewer_id is None:
            return None
        async with self._session_factory() as session:
            async with session.begin():
                decided = await apply_gallery_decision(
                    session,
                    db_turn_id,
                    decision=decision,
                    decided_by_user_id=db_reviewer_id,
                    now=datetime.now(timezone.utc),
                )
                if decided is None:
                    return None
                decided_turn_id, drawer = decided
                return _public_id(decided_turn_id), (
                    _public_id(drawer) if drawer is not None else None
                )

    async def viewer_gallery_facts(
        self, turn_ids: Sequence[str], *, viewer_user_id: str
    ) -> dict[str, tuple[str | None, bool]]:
        db_viewer_id = _optional_entity_id(viewer_user_id)
        db_turn_ids = [t for t in (_optional_entity_id(turn_id) for turn_id in turn_ids) if t]
        if db_viewer_id is None or not db_turn_ids:
            return {}
        async with self._session_factory() as session:
            viewer_ids = await _identity_ids(session, db_viewer_id)
            drawn = (
                await session.execute(
                    select(TurnRecord.id, TurnRecord.drawer_user_id).where(
                        TurnRecord.id.in_(db_turn_ids)
                    )
                )
            ).all()
            picks = dict(
                (
                    await session.execute(
                        select(TurnDrawingReaction.turn_id, TurnDrawingReaction.emoji).where(
                            TurnDrawingReaction.turn_id.in_(db_turn_ids),
                            TurnDrawingReaction.user_id.in_(viewer_ids),
                        )
                    )
                ).all()
            )
        return {
            _public_id(turn_id): (picks.get(turn_id), drawer_user_id in viewer_ids)
            for turn_id, drawer_user_id in drawn
        }

    async def get_gallery_drawing(self, turn_id: str) -> TurnDrawingDetail | None:
        db_turn_id = _optional_entity_id(turn_id)
        if db_turn_id is None:
            return None
        async with self._session_factory() as session:
            row = await session.scalar(
                select(TurnDrawing)
                .join(GameRecord, GameRecord.id == TurnDrawing.game_id)
                .where(TurnDrawing.turn_id == db_turn_id, *_gallery_predicate())
            )
        if row is None or row.payload is None:
            return None
        return TurnDrawingDetail(
            turn_id=_public_id(row.turn_id),
            payload=row.payload,
            checksum_sha256=row.checksum_sha256 or "",
        )

    async def get_gallery_drawing_checksum(self, turn_id: str) -> str | None:
        db_turn_id = _optional_entity_id(turn_id)
        if db_turn_id is None:
            return None
        async with self._session_factory() as session:
            checksum = await session.scalar(
                select(TurnDrawing.checksum_sha256)
                .join(GameRecord, GameRecord.id == TurnDrawing.game_id)
                .where(TurnDrawing.turn_id == db_turn_id, *_gallery_predicate())
            )
        return checksum or None

    async def set_profile_pins(
        self,
        *,
        requesting_user_id: str,
        turn_ids: Sequence[str],
    ) -> ProfilePinsResult | None:
        db_user_id = _optional_entity_id(requesting_user_id)
        if db_user_id is None:
            return None
        db_turn_ids: list[UUID] = []
        for turn_id in turn_ids:
            db_turn_id = _optional_entity_id(turn_id)
            if db_turn_id is None or db_turn_id in db_turn_ids:
                return None
            db_turn_ids.append(db_turn_id)
        if len(db_turn_ids) > PROFILE_PIN_SLOTS:
            return None
        # The barrier can find, under its lock, a target merged in since its
        # alias read; it then abandons the transaction rather than lock more
        # (LockSetChangedError), and the whole write starts again so the
        # complete set goes into one ordered statement. Bounded: a merge is a
        # sign-in, and three in a row inside this window is not a real thing.
        rows: list[tuple[UUID, UUID]] | None = None
        for attempt in range(PIN_WRITE_LOCK_RETRIES):
            try:
                rows = await self._replace_profile_pins(db_user_id, db_turn_ids)
            except LockSetChangedError:
                if attempt == PIN_WRITE_LOCK_RETRIES - 1:
                    telemetry.db_retry("profile_pins", "exhausted")
                    raise
                telemetry.db_retry("profile_pins", "retried")
                continue
            break
        if rows is None:
            return None
        return ProfilePinsResult(
            pins=tuple(
                ProfilePinDetail(
                    turn_id=_public_id(db_turn_id),
                    game_id=_public_id(game_id),
                    position=position,
                )
                for position, (game_id, db_turn_id) in enumerate(rows)
            )
        )

    async def _replace_profile_pins(
        self, db_user_id: UUID, db_turn_ids: list[UUID]
    ) -> list[tuple[UUID, UUID]] | None:
        """One attempt at the whole-shelf write: the barrier, the checks, the
        rows. `None` for every refusal; the rows written otherwise."""
        async with self._session_factory() as session:
            async with session.begin():
                identity_ids = await _identity_ids(session, db_user_id)
                # The erasure barrier (app.auth.erasure), for both accounts a
                # pin is about. The pinner's: authentication before a deletion
                # is not authorization after it, and a pin written past the
                # deletion would put a shelf back on a tombstoned profile.
                # Each drawer's: their deletion erases the drawing and takes
                # its pins with it, and a pin validated before that commit
                # and written after it would outlive the drawing it names.
                # One lock over all of them, ascending, held to the commit;
                # the checks below run under it and see either the state
                # before the deletion, which the deletion then erases, or the
                # state after it, which refuses. Exclusive rather than the
                # barrier's usual shared lock, because this write must also
                # serialize with *itself*: two whole-shelf replacements for
                # one account that both pass a shared lock both delete
                # nothing and both insert position 0, and the second one
                # dies on the unique position instead of replacing the first.
                drawers = (
                    await session.execute(
                        select(TurnRecord.drawer_user_id).where(
                            TurnRecord.id.in_(db_turn_ids),
                            TurnRecord.drawer_user_id.is_not(None),
                        )
                    )
                ).scalars().all()
                erased = await erased_identity_ids(
                    session, (identity_ids[0], *drawers), exclusive=True
                )
                if identity_ids[0] in erased:
                    return None
                # Pins belong to the canonical account: a guest cannot pin
                # (R-PIN-01), so there is never a guest shelf to merge.
                account = await session.get(User, identity_ids[0])
                if (
                    account is None
                    or account.is_anonymous
                    or account.state != AccountState.REGISTERED.value
                ):
                    return None
                # Everything a turn has to be, in one query per turn: a seat
                # for this identity in its game, the game public, the drawing
                # there to show. Checked before anything is written, so a
                # refused list leaves the shelf as it was.
                seated = (
                    select(GameParticipant.id)
                    .where(
                        GameParticipant.game_id == TurnRecord.game_id,
                        GameParticipant.user_id.in_(identity_ids),
                    )
                    .exists()
                )
                rows: list[tuple[UUID, UUID]] = []
                for db_turn_id in db_turn_ids:
                    game_id = await session.scalar(
                        select(TurnRecord.game_id)
                        .join(GameRecord, GameRecord.id == TurnRecord.game_id)
                        .join(TurnDrawing, TurnDrawing.turn_id == TurnRecord.id)
                        .where(
                            TurnRecord.id == db_turn_id,
                            GameRecord.visibility == GameVisibility.PUBLIC.value,
                            TurnDrawing.status == TurnDrawingStatus.READY.value,
                            TurnDrawing.payload.is_not(None),
                            TurnDrawing.gallery_hidden_at.is_(None),
                            seated,
                        )
                    )
                    if game_id is None:
                        return None
                    rows.append((game_id, db_turn_id))
                # Replace rather than diff: the unique position per account
                # would otherwise have to be shuffled through a spare slot.
                await session.execute(
                    delete(ProfileDrawingPin).where(
                        ProfileDrawingPin.user_id == identity_ids[0]
                    )
                )
                for position, (game_id, db_turn_id) in enumerate(rows):
                    session.add(
                        ProfileDrawingPin(
                            user_id=identity_ids[0],
                            game_id=game_id,
                            turn_id=db_turn_id,
                            position=position,
                        )
                    )
        return rows

    def _pinned_drawing_predicate(self, profile_user_id: UUID, turn_id: UUID):
        """Everything a pinned-drawing read has to hold, as one predicate the
        bytes and the validator share: this account pinned this turn, the
        game is public, the drawing is there to show. Deliberately not the
        participant subquery `get_turn_drawing` uses - this is the other
        door (R-PIN-06), and it stays a separate query so a later edit to
        either cannot loosen the other by accident."""
        pinned = (
            select(ProfileDrawingPin.turn_id)
            .where(
                ProfileDrawingPin.user_id == profile_user_id,
                ProfileDrawingPin.turn_id == turn_id,
                ProfileDrawingPin.game_id == TurnDrawing.game_id,
            )
            .exists()
        )
        public = (
            select(GameRecord.id)
            .where(
                GameRecord.id == TurnDrawing.game_id,
                GameRecord.visibility == GameVisibility.PUBLIC.value,
            )
            .exists()
        )
        return and_(
            TurnDrawing.turn_id == turn_id,
            TurnDrawing.status == TurnDrawingStatus.READY.value,
            TurnDrawing.payload.is_not(None),
            # A drawing a moderator hid from the Gallery is hidden from every
            # shelf that shows it to strangers (R-GAL-09): a pin is not a way
            # around a takedown any more than around a private game.
            TurnDrawing.gallery_hidden_at.is_(None),
            pinned,
            public,
        )

    async def get_profile_pins(
        self, profile_user_id: str, *, viewer_user_id: str | None = None
    ) -> tuple[ProfilePinEntry, ...]:
        db_profile_user_id = _optional_entity_id(profile_user_id)
        if db_profile_user_id is None:
            return ()
        db_viewer_id = (
            _optional_entity_id(viewer_user_id) if viewer_user_id is not None else None
        )
        async with self._session_factory() as session:
            canonical = await _canonical_user_id(session, db_profile_user_id)
            viewer_ids: tuple[UUID, ...] = (
                await _identity_ids(session, db_viewer_id) if db_viewer_id else ()
            )
            rows = (
                await session.execute(
                    select(ProfileDrawingPin, TurnRecord)
                    .join(
                        TurnRecord,
                        and_(
                            TurnRecord.id == ProfileDrawingPin.turn_id,
                            TurnRecord.game_id == ProfileDrawingPin.game_id,
                        ),
                    )
                    .join(GameRecord, GameRecord.id == TurnRecord.game_id)
                    .join(TurnDrawing, TurnDrawing.turn_id == TurnRecord.id)
                    .where(
                        ProfileDrawingPin.user_id == canonical,
                        GameRecord.visibility == GameVisibility.PUBLIC.value,
                        TurnDrawing.status == TurnDrawingStatus.READY.value,
                        TurnDrawing.payload.is_not(None),
                        TurnDrawing.gallery_hidden_at.is_(None),
                    )
                    .order_by(ProfileDrawingPin.position)
                )
            ).all()
            summaries = await _reaction_summaries(
                session, [turn.id for _, turn in rows], viewer_ids
            )
        entries = []
        for pin, turn in rows:
            summary = summaries.get(turn.id, _NO_REACTIONS)
            entries.append(
                ProfilePinEntry(
                    turn_id=_public_id(pin.turn_id),
                    position=pin.position,
                    round_number=turn.round_number,
                    turn_number=turn.turn_number,
                    drawer_display_name=turn.drawer_display_name_snapshot,
                    drawer_name_color=turn.drawer_name_color_snapshot,
                    drawer_is_anonymous=turn.drawer_is_anonymous_snapshot,
                    prompt=turn.prompt,
                    stroke_count=turn.stroke_count,
                    reactions=summary.details,
                    reaction_counts=summary.counts,
                    my_reaction=summary.my_reaction,
                    drawn_by_me=turn.drawer_user_id in viewer_ids,
                )
            )
        return tuple(entries)

    async def get_pinned_drawing(
        self, profile_user_id: str, turn_id: str
    ) -> TurnDrawingDetail | None:
        db_profile_user_id = _optional_entity_id(profile_user_id)
        db_turn_id = _optional_entity_id(turn_id)
        if db_profile_user_id is None or db_turn_id is None:
            return None
        async with self._session_factory() as session:
            canonical = await _canonical_user_id(session, db_profile_user_id)
            row = await session.scalar(
                select(TurnDrawing).where(
                    self._pinned_drawing_predicate(canonical, db_turn_id)
                )
            )
        if row is None:
            return None
        return TurnDrawingDetail(
            turn_id=_public_id(row.turn_id),
            payload=row.payload,
            checksum_sha256=row.checksum_sha256 or "",
        )

    async def get_pinned_drawing_checksum(
        self, profile_user_id: str, turn_id: str
    ) -> str | None:
        db_profile_user_id = _optional_entity_id(profile_user_id)
        db_turn_id = _optional_entity_id(turn_id)
        if db_profile_user_id is None or db_turn_id is None:
            return None
        async with self._session_factory() as session:
            canonical = await _canonical_user_id(session, db_profile_user_id)
            checksum = await session.scalar(
                select(TurnDrawing.checksum_sha256).where(
                    self._pinned_drawing_predicate(canonical, db_turn_id)
                )
            )
        return checksum or None

    async def get_recent_co_players(
        self,
        user_id: str,
        *,
        since: datetime,
        limit: int = 20,
    ) -> list[RecentCoPlayer]:
        """Registered accounts this one finished a game with since *since*.

        A self-join over `game_participants`: the caller's seats give the game
        ids, and the other seats in those games give the accounts. Bounded by
        time rather than by a page of history, because the question is "who
        have I been playing with", and a returning player's answer should be
        empty rather than a year old.

        The live `users` row supplies the name and picture, not the seat's
        snapshot: a snapshot is what somebody was called in that game, and
        this list exists to offer a friendship with who they are now. It also
        means a deleted account drops out for free, since the seat's `user_id`
        is set null when it goes.

        Finished games only. An abandoned one is not a claim that these people
        played together, and R-HIST-06 already refuses to treat it as one.
        """
        db_user_id = _optional_entity_id(user_id)
        if db_user_id is None:
            return []
        clamped_limit = max(1, min(limit, MAX_PAGINATION_LIMIT))

        async with self._session_factory() as session:
            identity_ids = await _identity_ids(session, db_user_id)
            mine = aliased(GameParticipant)
            theirs = aliased(GameParticipant)
            stmt = (
                select(
                    User.id,
                    User.display_name,
                    User.name_color,
                    User.avatar_key,
                    func.max(GameRecord.finished_at).label("last_played_at"),
                )
                .select_from(mine)
                .join(GameRecord, GameRecord.id == mine.game_id)
                .join(theirs, theirs.game_id == mine.game_id)
                .join(User, User.id == theirs.user_id)
                .where(
                    mine.user_id.in_(identity_ids),
                    theirs.user_id.notin_(identity_ids),
                    GameRecord.outcome == GameOutcome.FINISHED.value,
                    GameRecord.finished_at >= since,
                    # Registered, which is one filter for three refusals:
                    # a guest cannot hold a friendship (R-FRIEND-03), a
                    # merged identity is somebody else's account now, and a
                    # deleted one is nobody. `is_anonymous` is a property
                    # over this column rather than a column, so the state is
                    # what a query can ask about.
                    User.state == AccountState.REGISTERED.value,
                )
                .group_by(User.id, User.display_name, User.name_color, User.avatar_key)
                .order_by(func.max(GameRecord.finished_at).desc())
                .limit(clamped_limit)
            )
            rows = (await session.execute(stmt)).all()
            return [
                RecentCoPlayer(
                    user_id=_public_id(row.id),
                    display_name=row.display_name,
                    name_color=row.name_color,
                    avatar_key=row.avatar_key,
                    last_played_at=row.last_played_at,
                )
                for row in rows
            ]

    @database_operation_of("history_page")
    async def get_user_games(
        self,
        user_id: str,
        limit: int = DEFAULT_PAGINATION_LIMIT,
        offset: int = 0,
        *,
        include_abandoned: bool = False,
        requesting_user_id: str | None = None,
    ) -> list[GameSummary]:
        """A page of the games `user_id` sat in, as `requesting_user_id` may see them.

        A game from a public room is on the page for anyone; one from a
        private room only when the requester also sat in it (#469). The
        subject's own games are all games they sat in, so an owner reading
        their own profile needs no separate rule - and nor does a merged
        guest, whose seats are found through the same identity walk.
        """
        db_user_id = _optional_entity_id(user_id)
        if db_user_id is None:
            return []
        clamped_limit = max(1, min(limit, MAX_PAGINATION_LIMIT))
        clamped_offset = max(0, offset)

        async with self._session_factory() as session:
            identity_ids = await _identity_ids(session, db_user_id)
            # Find game IDs the user was a participant in
            user_games_subq = (
                select(GameParticipant.game_id)
                .where(GameParticipant.user_id.in_(identity_ids))
                .scalar_subquery()
            )
            visible = GameRecord.visibility == GameVisibility.PUBLIC.value
            db_requesting_user_id = (
                None
                if requesting_user_id is None
                else _optional_entity_id(requesting_user_id)
            )
            if db_requesting_user_id is not None:
                requester_ids = (
                    identity_ids
                    if db_requesting_user_id in identity_ids
                    else await _identity_ids(session, db_requesting_user_id)
                )
                requester_games_subq = (
                    select(GameParticipant.game_id)
                    .where(GameParticipant.user_id.in_(requester_ids))
                    .scalar_subquery()
                )
                visible = or_(visible, GameRecord.id.in_(requester_games_subq))

            stmt = (
                select(GameRecord)
                .where(
                    GameRecord.id.in_(user_games_subq),
                    visible,
                    *(
                        ()
                        if include_abandoned
                        else (GameRecord.outcome == GameOutcome.FINISHED.value,)
                    ),
                )
                .options(
                    selectinload(GameRecord.participants),
                    defer(GameRecord.rule_snapshot, raiseload=True),
                )
                # The id breaks a tie: two games finished in the same
                # microsecond had no order between them, so a page boundary
                # could repeat one and skip the other (#1077).
                .order_by(GameRecord.finished_at.desc(), GameRecord.id.desc())
                .limit(clamped_limit)
                .offset(clamped_offset)
            )

            result = await session.execute(stmt)
            games = result.scalars().all()

            return [_to_game_summary(g, with_rule_snapshot=False) for g in games]

    async def get_game_detail(
        self,
        game_id: str,
        requesting_user_id: str,
    ) -> GameDetail | None:
        db_game_id = _optional_entity_id(game_id)
        if db_game_id is None:
            return None
        db_requesting_user_id = _optional_entity_id(requesting_user_id)
        if db_requesting_user_id is None:
            return None
        async with self._session_factory() as session:
            requesting_identity_ids = await _identity_ids(
                session, db_requesting_user_id
            )
            # The prompts drawn, who guessed them and how fast belong to the
            # players who were there, not to anyone holding the game id: the
            # participation test is in the query, so a stranger's request
            # answers 404 after one statement rather than after the dozen
            # eager loads below (#611).
            stmt = (
                select(GameRecord)
                .where(
                    GameRecord.id == db_game_id,
                    exists().where(
                        GameParticipant.game_id == GameRecord.id,
                        GameParticipant.user_id.in_(requesting_identity_ids),
                    ),
                )
                .options(
                    selectinload(GameRecord.participants),
                    # Status only; the blob is fetched by its own route so a
                    # game detail never carries megabytes of canvas.
                    selectinload(GameRecord.turns).selectinload(
                        TurnRecord.drawing
                    ).load_only(TurnDrawing.status),
                    selectinload(GameRecord.turns).selectinload(
                        TurnRecord.participant_outcomes
                    ),
                    # Not the prompt offers or the score ledger: the page
                    # reads neither, and for a 16-seat, 10-round game they
                    # were half the load and half the 1.5 MB response (#1254).
                    # A player's own seats' events, and the offers on the
                    # turns they drew, are in their export.
                )
            )
            result = await session.execute(stmt)
            g = result.scalar_one_or_none()
            if not g:
                return None

            requester_seats = sorted(
                (p for p in g.participants if p.user_id in requesting_identity_ids),
                key=lambda p: p.id,
            )
            if not requester_seats:
                return None

            summary = _to_game_summary(g)
            reaction_summaries = await _reaction_summaries(
                session, [turn.id for turn in g.turns]
            )

            turn_details: list[TurnDetail] = []
            for r in sorted(g.turns, key=lambda x: (x.round_number, x.turn_number)):
                outcome_details = [
                    TurnParticipantOutcomeDetail(
                        seat_id=_public_id(outcome.participant_id),
                        eligible=outcome.eligible,
                        eligibility_reason=outcome.eligibility_reason,
                        outcome=outcome.outcome,
                        terminal_state=outcome.terminal_state,
                        correct_guess_time_seconds=(
                            outcome.correct_guess_time_seconds
                        ),
                        wrong_guess_count=outcome.wrong_guess_count,
                        near_miss_count=outcome.near_miss_count,
                        hints_used=outcome.hints_used,
                        points_spent_on_hints=outcome.points_spent_on_hints,
                        points_awarded=outcome.points_awarded,
                    )
                    for outcome in sorted(
                        r.participant_outcomes,
                        key=lambda value: str(value.participant_id),
                    )
                ]
                turn_details.append(
                    TurnDetail(
                        id=_public_id(r.id),
                        stroke_count=r.stroke_count,
                        drawing_status=(
                            r.drawing.status if r.drawing is not None else None
                        ),
                        round_number=r.round_number,
                        turn_number=r.turn_number,
                        drawer_user_id=(
                            _public_id(r.drawer_user_id) if r.drawer_user_id else None
                        ),
                        drawer_seat_id=(
                            _public_id(r.drawer_participant_id)
                            if r.drawer_participant_id
                            else None
                        ),
                        drawer_display_name=r.drawer_display_name_snapshot,
                        drawer_name_color=r.drawer_name_color_snapshot,
                        drawer_is_anonymous=r.drawer_is_anonymous_snapshot,
                        prompt=r.prompt,
                        duration_seconds=r.duration_seconds,
                        prompt_version_id=(
                            _public_id(r.prompt_version_id)
                            if r.prompt_version_id
                            else None
                        ),
                        prompt_source_kind=r.prompt_source_kind,
                        participant_outcomes=outcome_details,
                        reactions=list(
                            reaction_summaries.get(r.id, _NO_REACTIONS).details
                        ),
                        reaction_counts=reaction_summaries.get(
                            r.id, _NO_REACTIONS
                        ).counts,
                    )
                )

            return GameDetail(
                summary=summary,
                turns=turn_details,
                my_seat_id=_public_id(requester_seats[0].id),
            )


# How many ranked ids the catalogue's star order keeps per filter: every
# page a reader can reach (`MAX_COMMUNITY_OFFSET`), one full page past it,
# and one more to say whether there is a next page.
CATALOGUE_RANKING_DEPTH = MAX_COMMUNITY_OFFSET + MAX_COMMUNITY_PAGE + 1
# How long one ranking serves the star order, when the application asks for
# a cache at all (`CATALOGUE_RANKING_TTL_SECONDS`).
CATALOGUE_RANKING_TTL_SECONDS = 60.0
# Distinct filters (language and tag set) whose ranking is kept at once. Tag
# sets are chosen by the reader, so the number of keys is theirs too; past
# this the least recently read goes.
CATALOGUE_RANKING_KEYS = 256


class _CatalogueRanking:
    """The community catalogue's star order, computed at most once per TTL
    per filter and shared by every reader (#901).

    Stars stay facts (R-LIST-16): what is cached is only the *order*, a
    tuple of list ids. Ranking needs every published list's count before it
    can return the first 25, which cost 14 ms per page at 5,000 lists and
    grew with every list published; a page read from the cached order fetches
    its 25 rows by id, with their counts, in under a millisecond. One worker
    owns it, so it is exact to within its TTL. A list taken down, retired or
    unpublished leaves the page at once - the page's own read re-applies
    every filter - and a publish, or a save that changes a published list's
    tags, through this process resets it.
    """

    def __init__(self, ttl_seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.ttl_seconds = ttl_seconds
        self._clock = clock
        self._entries: OrderedDict[tuple, tuple[float, tuple[UUID, ...]]] = OrderedDict()
        self._lock = asyncio.Lock()
        self._generation = 0

    def _fresh(self, key: tuple) -> tuple[UUID, ...] | None:
        entry = self._entries.get(key)
        if entry is None or self._clock() - entry[0] >= self.ttl_seconds:
            return None
        self._entries.move_to_end(key)
        return entry[1]

    async def get(
        self, key: tuple, read: Callable[[], Awaitable[tuple[UUID, ...]]]
    ) -> tuple[UUID, ...]:
        found = self._fresh(key)
        if found is not None:
            return found
        async with self._lock:
            # Whoever waited finds what the first arrival read.
            found = self._fresh(key)
            if found is not None:
                return found
            while True:
                generation = self._generation
                ranked = await read()
                if generation == self._generation:
                    break
            self._entries[key] = (self._clock(), ranked)
            self._entries.move_to_end(key)
            while len(self._entries) > CATALOGUE_RANKING_KEYS:
                self._entries.popitem(last=False)
            return ranked

    def invalidate(self) -> None:
        self._generation += 1
        self._entries.clear()


#: Rows read per turn of the loop when a selection's content is read cold:
#: about 8 ms of row handling each, measured.
VERDICT_READ_CHUNK = 1000


async def _rows_in_chunks(session: AsyncSession, statement) -> list:
    """Every row of `statement`, handed over a chunk at a time.

    A selection at its ceiling is ~210,000 rows of answers and aliases, and
    materialising them in one go held the loop for ~0.4 s before any folding
    began (#1237); a chunk at a time gives the loop back between them.
    """
    rows: list = []
    result = await session.stream(statement)
    async for partition in result.partitions(VERDICT_READ_CHUNK):
        rows.extend(partition)
        await asyncio.sleep(0)
    return rows


#: Selections whose verdict is remembered (#1237). A verdict is a few
#: integers; the bound is on how many distinct selections are kept, oldest out.
MAX_REMEMBERED_VERDICTS = 512

#: Mixed selections whose false friends are remembered (#1367). Most mixed
#: rooms pin the same bundled families, so a handful covers them; each entry is
#: a few hundred keys.
MAX_REMEMBERED_FALSE_FRIENDS = 64


def _mixed_false_friends(rows: Sequence[tuple[str, str, str]]) -> dict[str, dict[str, frozenset[str]]]:
    """Every key, per seat language, that names one concept there and is
    another concept's word in some other language (#1367).

    `rows` are (language, concept, text): every answer and alias of the pinned
    lists. Keys are spellings as `prompt_match_variants` gives them - what
    a guess and an answer are compared on. A text in no language is that
    seat's word too, whatever the seat plays. A guess that lands on one of the
    returned keys means the concepts listed to that seat - German "Hut" is the hat - and so must not
    win a drawing whose other-language spelling folds the same way (an
    English hut), drawn into the game or not.
    """
    # By every spelling each language accepts, not only the canonical key: a
    # guess is accepted on those (R-GUESS-01), and German "Lüge" is "luge" as
    # well as "luege" - the French sled - which a canonical key never meets.
    own: dict[str, dict[str, set[str]]] = {language: defaultdict(set) for language in PROMPT_LANGUAGES}
    for language, concept, text in rows:
        for seat in PROMPT_LANGUAGES:
            if language in (seat, AGNOSTIC_PROMPT_LANGUAGE):
                for spelling in prompt_match_variants(text, seat):
                    own[seat][spelling].add(concept)
    found: dict[str, dict[str, frozenset[str]]] = {}
    for language, concept, text in rows:
        if language == AGNOSTIC_PROMPT_LANGUAGE:
            continue
        for spelling in prompt_match_variants(text, language):
            for seat in PROMPT_LANGUAGES:
                if seat == language:
                    continue
                owners = own[seat].get(spelling)
                if owners and owners - {concept}:
                    found.setdefault(seat, {})[spelling] = frozenset(owners)
    return found


@dataclass(frozen=True, slots=True)
class _BundledFamilies:
    """The official lists a mixed-language room can play, by family (#1374).

    A family is the official lists holding exactly the same concepts - one
    per room language - so a seat in any of them can play every prompt
    (R-PROMPT-13). Worked out from the data rather than from slugs, and once:
    official content changes only when the seed runs, and every mixed pin used
    to read every official list's prompts to find it again.
    """

    # Each family member's id -> the family's members in PROMPT_LANGUAGES order.
    members: dict[UUID, tuple[UUID, ...]]
    # Each family member's id -> the family's name: its English member's slug.
    names: dict[UUID, str]


AMBIGUOUS_SELECTION = "Selected prompt lists contain ambiguous answers or aliases"
EMPTY_SELECTION = "Selected prompt lists do not contain any prompts"


@dataclass(frozen=True, slots=True)
class _SelectionVerdict:
    """What checking a selection's content concluded: how many prompts it
    offers, and whether any answer reaches two of them."""

    prompt_count: int
    ambiguous: bool


async def _lock_versions(session: AsyncSession, *where) -> None:
    """Take the row locks a multi-row UPDATE of prompt versions needs, in id
    order, before it runs.

    A save stamps the versions it drops and a moderator's decision carries
    to copies in the owner's other lists; two such UPDATEs over the same
    rows, each locking in whatever order the plan visits them, can deadlock
    (#1385 review). Ascending ids give every writer one order.
    """
    await session.execute(
        select(PromptVersion.id).where(*where).order_by(PromptVersion.id).with_for_update()
    )


async def _draw_snapshot(
    session: AsyncSession,
    expected_versions: Mapping[str, int] | None,
    pinned: Sequence[_Source] = (),
) -> None:
    """Hold a draw to one snapshot of the content authorization checked.

    The working copy changes in place (#1359), so a draw that read its
    versions, then their sources, then their false friends in separate
    snapshots could see a save land between them - a drawn prompt whose
    sources had gone, so no provenance and no usage facts (#1385 review).
    REPEATABLE READ on PostgreSQL, taken before the first statement. On
    SQLite an explicit BEGIN: the driver's legacy transaction control opens
    no transaction for a SELECT, so each read would otherwise see whatever
    was committed by then; inside one, WAL holds every read to the snapshot
    the first took. Then the lists must still be at the versions
    authorization checked, or a save in between could have added an answer
    it never saw collide - and an edition a room plays must still be live:
    approving an update deletes the edition it replaces (#1360), and a draw
    from it would come back empty.
    """
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        await session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
    elif dialect == "sqlite":
        # Ended by the session's close, which rolls the driver back.
        await (await session.connection()).exec_driver_sql("BEGIN")
    editions = [pin.edition_id for pin in pinned if pin.edition_id is not None]
    if editions:
        live = set(
            (
                await session.scalars(
                    select(PromptListEdition.id).where(
                        PromptListEdition.id.in_(editions),
                        PromptListEdition.state == EDITION_PUBLISHED,
                    )
                )
            ).all()
        )
        if live != set(editions):
            raise PromptListsChangedError("A selected prompt list changed since it was checked.")
    if not expected_versions:
        return
    expected = {_entity_id(list_id): version for list_id, version in expected_versions.items()}
    found = dict(
        (
            await session.execute(
                select(PromptList.id, PromptList.version).where(
                    PromptList.id.in_(list(expected))
                )
            )
        ).all()
    )
    if any(found.get(list_id) != version for list_id, version in expected.items()):
        raise PromptListsChangedError("A selected prompt list changed since it was checked.")


@dataclass(frozen=True, slots=True)
class _Source:
    """One pinned list and what a room plays of it: its working copy, or the
    live edition named here (#1360)."""

    id: UUID
    edition_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class _Pin:
    """A list admitted to a selection, with the edition it is played from -
    none for a bundled list or one the room's host owns (#1360)."""

    list: PromptList
    edition: PromptListEdition | None = None

    @property
    def id(self) -> UUID:
        return self.list.id

    @property
    def edition_id(self) -> UUID | None:
        return self.edition.id if self.edition is not None else None

    @property
    def language(self) -> str:
        return self.list.language

    @property
    def letter_counts(self) -> dict:
        return (self.edition or self.list).letter_counts

    @property
    def letter_total(self) -> int:
        return (self.edition or self.list).letter_total

    @property
    def key(self) -> tuple:
        """What one content is remembered by: an edition never changes, and a
        working copy is one content at one version (#1359)."""
        if self.edition is not None:
            return ("e", str(self.edition.id))
        return ("l", str(self.list.id), self.list.version)


def _sources(
    list_ids: Sequence[str], edition_ids: Mapping[str, str] | None
) -> list[_Source]:
    editions = {
        _entity_id(list_id): _entity_id(edition_id)
        for list_id, edition_id in (edition_ids or {}).items()
    }
    return [
        _Source(list_id, editions.get(list_id))
        for list_id in (_entity_id(raw) for raw in list_ids)
    ]


def _working_copy_versions_of(pins: Sequence[_Pin]) -> dict[str, int]:
    """The version of each list a room plays the working copy of: the draw
    refuses one saved since (#1385 review). An edition never changes, so the
    lists played from one are checked by the edition instead."""
    return {
        _public_id(pin.id): pin.list.version for pin in pins if pin.edition_id is None
    }


def _edition_ids(pins: Sequence[_Pin]) -> dict[str, str]:
    return {
        _public_id(pin.id): _public_id(pin.edition_id)
        for pin in pins
        if pin.edition_id is not None
    }


def _membership(pins):
    """(list_id, version_id, position) of everything these pins play: a
    working copy's rows, or an edition's items (#1360)."""
    working = [pin.id for pin in pins if pin.edition_id is None]
    editions = [pin.edition_id for pin in pins if pin.edition_id is not None]
    parts = []
    if working or not editions:
        parts.append(
            select(
                Prompt.prompt_list_id.label("list_id"),
                Prompt.prompt_version_id.label("version_id"),
                Prompt.position.label("position"),
            ).where(Prompt.prompt_list_id.in_(working))
        )
    if editions:
        parts.append(
            select(
                PromptListEdition.prompt_list_id.label("list_id"),
                PromptListEditionItem.prompt_version_id.label("version_id"),
                PromptListEditionItem.position.label("position"),
            )
            .join(PromptListEdition, PromptListEdition.id == PromptListEditionItem.edition_id)
            .where(PromptListEditionItem.edition_id.in_(editions))
        )
    return (union_all(*parts) if len(parts) > 1 else parts[0]).subquery()


async def _source_lists(
    session: AsyncSession, pinned: Sequence, version_ids: Sequence[UUID]
) -> defaultdict[UUID, tuple[str, ...]]:
    """Which lists each drawn version came from, in the order they were pinned.

    A version can sit in several selected lists, and a turn records every
    source it was legitimately offered from (#1358).
    """
    order = {pin.id: index for index, pin in enumerate(pinned)}
    found: dict[UUID, list[UUID]] = defaultdict(list)
    if version_ids:
        held = _membership(pinned)
        for version_id, list_id in (
            await session.execute(
                select(held.c.version_id, held.c.list_id).where(
                    held.c.version_id.in_(list(version_ids))
                )
            )
        ).all():
            found[version_id].append(list_id)
    sources: defaultdict[UUID, tuple[str, ...]] = defaultdict(tuple)
    for version_id, lists in found.items():
        sources[version_id] = tuple(
            _public_id(list_id) for list_id in sorted(lists, key=order.__getitem__)
        )
    return sources


def _single_language_verdict(rows: Sequence[Row], language: str) -> _SelectionVerdict:
    """Fold every active answer and alias under `language`; off the loop.

    Keyed from the *text* under the fold in force now, not the stored keys
    (review of #1070): a fold that widened since the rows were written makes
    two stored keys one answer, and the game matches under the new fold.
    """
    reached_by: dict[str, UUID] = {}
    for version_id, answer in rows:
        if reached_by.setdefault(prompt_match_key(answer, language), version_id) != version_id:
            return _SelectionVerdict(prompt_count=0, ambiguous=True)
    return _SelectionVerdict(prompt_count=len({version_id for version_id, _ in rows}), ambiguous=False)


def _mixed_verdict(
    rows: Sequence[Row], alias_rows: Sequence[Row], language_of: dict[UUID, str]
) -> _SelectionVerdict:
    """A mixed room's check, every room language at once; off the loop.

    Each room language sees its own lists and the lists in no language. Each
    text is folded once per distinct transliteration rather than once per
    room language (`prompt_match_keys`): eight languages, at most five keys.
    The rows arrive as the database returned them, so none of this - not even
    grouping the aliases - runs on the loop.
    """
    aliases: dict[UUID, list[str]] = defaultdict(list)
    for version_id, answer in alias_rows:
        aliases[version_id].append(answer)
    reached_by: dict[str, dict[str, UUID]] = {language: {} for language in PROMPT_LANGUAGES}
    for list_id, version_id, _concept, answer in rows:
        list_language = language_of[list_id]
        languages = (
            PROMPT_LANGUAGES if list_language == AGNOSTIC_PROMPT_LANGUAGE else (list_language,)
        )
        for text in (answer, *aliases.get(version_id, ())):
            for language, key in prompt_match_keys(text, languages).items():
                if reached_by[language].setdefault(key, version_id) != version_id:
                    return _SelectionVerdict(prompt_count=0, ambiguous=True)
    return _SelectionVerdict(
        prompt_count=len({concept for _, _, concept, _ in rows}), ambiguous=False
    )


class SqlAlchemyPromptListRepository(PromptListRepository):
    """SQLAlchemy-backed implementation of PromptListRepository."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        catalogue_ranking_ttl_seconds: float = 0.0,
    ) -> None:
        self._session_factory = session_factory
        # Off unless asked for: the application sets it (60 s by default,
        # `CATALOGUE_RANKING_TTL_SECONDS`); a test that writes and reads back
        # at once gets the uncached order it expects.
        self._ranking = _CatalogueRanking(catalogue_ranking_ttl_seconds)
        # What authorizing a selection concluded (#1237), by the lists it
        # pinned and their versions and the fold they were checked under, with the moderation
        # fingerprint it was concluded at. See `authorize_selection`.
        self._verdicts: OrderedDict[tuple, tuple[tuple, _SelectionVerdict]] = OrderedDict()
        # A mixed selection's false friends (#1367), by the lists pinned and
        # their versions: a list at one version holds one content (#1359).
        self._false_friends: OrderedDict[tuple, dict[str, dict[str, frozenset[str]]]] = (
            OrderedDict()
        )
        # The official families (#1374), worked out on first use and dropped by
        # every `upsert_bundled`, the only thing that changes official content.
        # The generation keeps a reading that began before a seed's write from
        # being kept after it.
        self._families: _BundledFamilies | None = None
        self._families_generation = 0

    async def refresh_planner_statistics(self) -> None:
        """ANALYZE the prompt tables after seeding, on PostgreSQL.

        A database the seed has just filled has no statistics yet, so the
        planner takes every table for a row or two and joins the aliases of a
        thousand-prompt list by walking all of them once per prompt: two
        million comparisons for one list, and a mixed room's selection past
        the 30-second statement timeout on a busy CI runner (#1367).
        Autovacuum would get there, a minute later; startup should not wait
        on it. The application role is granted MAINTAIN on these tables for
        it (`app.db.roles.SEEDED_TABLES`). Never a reason not to start: a
        role without the grant is warned and skipped by PostgreSQL itself, a
        table a VACUUM or a migration is holding is skipped rather than
        waited for, and anything else is logged - autovacuum is the fallback.
        """
        async with self._session_factory() as session:
            if session.get_bind().dialect.name != "postgresql":
                return
            try:
                await session.execute(
                    sql_text(f"ANALYZE (SKIP_LOCKED) {', '.join(SEEDED_TABLES)}")
                )
                await session.commit()
            except DBAPIError:
                logger.warning("Could not analyze the seeded prompt tables", exc_info=True)

    @staticmethod
    def _star_count():
        """How many rows name this list. Derived, never stored (R-LIST-16)."""
        return (
            select(func.count())
            .select_from(PromptListStar)
            .where(PromptListStar.prompt_list_id == PromptList.id)
            .correlate(PromptList)
            .scalar_subquery()
        )

    @staticmethod
    async def _copied_from(
        session: AsyncSession, list_ids: Sequence[UUID]
    ) -> dict[UUID, CopiedFrom]:
        """What each of these lists was copied from, as it is now (R-LIST-21).

        One query for all of them, whatever the caller is reading. The original
        is the list the copy's `copied_from_list_id` names (#1361), read as it
        currently stands: its name and its owner's display name today, since an
        original is free to be renamed. A list that is not a copy is absent.

        Whether it links is the catalogue's own question, asked the way the
        catalogue asks it (`_published_by_a_player`), so a credit never links to
        a list the catalogue would refuse to open. A copy whose original is gone
        - retired, or already reclaimed so the pointer is null - says only that
        it was copied: `is_copy` is what survives, and it names nothing.
        """
        if not list_ids:
            return {}
        copy_list = aliased(PromptList)
        source = aliased(PromptList)
        live = aliased(PromptListEdition)
        rows = (
            await session.execute(
                select(copy_list.id, source, live.name, User.display_name)
                .select_from(copy_list)
                .outerjoin(source, source.id == copy_list.copied_from_list_id)
                .outerjoin(
                    live,
                    and_(live.prompt_list_id == source.id, live.state == EDITION_PUBLISHED),
                )
                .outerjoin(User, User.id == source.owner_user_id)
                .where(copy_list.id.in_(list_ids), copy_list.is_copy.is_(True))
            )
        ).all()
        credits: dict[UUID, CopiedFrom] = {}
        for list_id, original, live_name, display_name in rows:
            # The name the original was published under: its working copy's
            # may be an unpublished rename, which is the owner's alone (#1360).
            name = live_name if live_name is not None else original.name if original else None
            if original is None or original.deleted_at is not None:
                credits[list_id] = CopiedFrom(status="deleted")
            elif (
                original.visibility == PromptListVisibility.PUBLIC.value
                and original.moderation_state == PromptContentModerationState.ACTIVE.value
                and not original.is_bundled
                and live_name is not None
            ):
                credits[list_id] = CopiedFrom(
                    status="published",
                    list_id=_public_id(original.id),
                    name=name,
                    owner_display_name=display_name,
                )
            else:
                credits[list_id] = CopiedFrom(
                    status="withdrawn",
                    name=name,
                    owner_display_name=display_name,
                )
        return credits

    @staticmethod
    def _copy_count():
        """How many copies of this list still exist. Derived, never stored
        (R-LIST-20).

        The lists whose `copied_from_list_id` names this one (#1361): a copy
        records the list it was taken from, so an edit on either side changes
        nothing here. A copy that was deleted is not counted, and a copy of a
        copy counts toward what it was taken from.
        """
        copy_list = aliased(PromptList)
        return (
            select(func.count(copy_list.id))
            .where(
                copy_list.copied_from_list_id == PromptList.id,
                copy_list.deleted_at.is_(None),
            )
            .correlate(PromptList)
            .scalar_subquery()
        )

    @staticmethod
    def _edition_prompt_count(edition):
        return (
            select(func.count())
            .select_from(PromptListEditionItem)
            .where(PromptListEditionItem.edition_id == edition.id)
            .correlate(edition)
            .scalar_subquery()
        )

    @staticmethod
    async def _edition_tags(
        session: AsyncSession, edition_ids: Sequence[UUID]
    ) -> dict[UUID, tuple[str, ...]]:
        """Tag slugs of each edition, in vocabulary order (R-LIST-18)."""
        if not edition_ids:
            return {}
        rows = (
            await session.execute(
                select(PromptListEditionTag.edition_id, PromptTag.slug)
                .join(PromptTag, PromptTag.id == PromptListEditionTag.tag_id)
                .where(PromptListEditionTag.edition_id.in_(list(edition_ids)))
            )
        ).all()
        held: dict[UUID, set[str]] = {}
        for edition_id, slug in rows:
            held.setdefault(edition_id, set()).add(slug)
        return {
            edition_id: tuple(slug for slug in LIST_TAG_SLUG_ORDER if slug in slugs)
            for edition_id, slugs in held.items()
        }

    @staticmethod
    async def _edition_entries(
        session: AsyncSession, edition_id: UUID
    ) -> tuple[PromptListEntry, ...]:
        """An edition's prompts in order, as the working copy is read."""
        rows = (
            await session.execute(
                select(
                    PromptListEditionItem.position,
                    PromptVersion.concept_id,
                    PromptVersion.id,
                    PromptVersion.canonical_answer,
                    PromptVersion.moderation_state,
                    PromptAlias.answer,
                )
                .select_from(PromptListEditionItem)
                .join(PromptVersion, PromptVersion.id == PromptListEditionItem.prompt_version_id)
                .outerjoin(
                    PromptVersionAlias,
                    PromptVersionAlias.prompt_version_id == PromptVersion.id,
                )
                .outerjoin(PromptAlias, PromptAlias.id == PromptVersionAlias.alias_id)
                .where(PromptListEditionItem.edition_id == edition_id)
                .order_by(PromptListEditionItem.position)
            )
        ).all()
        by_position: dict[int, tuple[UUID, UUID, str, str, list[str]]] = {}
        for position, concept_id, version_id, answer, state, alias in rows:
            held = by_position.get(position)
            if held is None:
                held = by_position[position] = (concept_id, version_id, answer, state, [])
            if alias is not None:
                held[4].append(alias)
        return tuple(
            PromptListEntry(
                concept_id=_public_id(concept_id),
                prompt_version_id=_public_id(version_id),
                answer=answer,
                aliases=tuple(sorted(aliases)),
                moderation_state=state,
            )
            for concept_id, version_id, answer, state, aliases in by_position.values()
        )

    @staticmethod
    def _prompt_count():
        return (
            select(func.count(Prompt.id))
            .where(Prompt.prompt_list_id == PromptList.id)
            .correlate(PromptList)
            .scalar_subquery()
        )

    async def list_all(
        self, *, language: str | None = None, locale: str | None = None
    ) -> list[PromptListSummary]:
        async with self._session_factory() as session:
            stmt = (
                select(PromptList, self._prompt_count())
                .options(selectinload(PromptList.localizations))
                .where(
                    PromptList.is_bundled.is_(True),
                    PromptList.moderation_state
                    == PromptContentModerationState.ACTIVE.value,
                )
                .order_by(PromptList.name)
            )
            if language is not None:
                stmt = stmt.where(_playable_in(language))
            rows = (await session.execute(stmt)).all()
            tags = await self._working_copy_tags(
                session, [prompt_list.id for prompt_list, _ in rows]
            )
            families = await self._bundled_families(session)
            return [
                _to_prompt_list_summary(
                    prompt_list,
                    int(prompt_count),
                    locale=locale,
                    tags=tags.get(prompt_list.id, ()),
                    family=families.names.get(prompt_list.id),
                )
                for prompt_list, prompt_count in rows
            ]

    async def get_by_slug(
        self, slug: str, *, locale: str | None = None
    ) -> PromptListSummary | None:
        async with self._session_factory() as session:
            stmt = (
                select(PromptList, self._prompt_count())
                .options(selectinload(PromptList.localizations))
                .where(
                    PromptList.slug == slug,
                    PromptList.is_bundled.is_(True),
                    PromptList.moderation_state
                    == PromptContentModerationState.ACTIVE.value,
                )
            )
            row = (await session.execute(stmt)).one_or_none()
            if row is None:
                return None
            tags = await self._working_copy_tags(session, [row[0].id])
            families = await self._bundled_families(session)
            return _to_prompt_list_summary(
                row[0],
                int(row[1]),
                locale=locale,
                tags=tags.get(row[0].id, ()),
                family=families.names.get(row[0].id),
            )

    @staticmethod
    def _clean_owned_entries(
        entries: Sequence[PromptListEntryInput], *, language: str
    ) -> tuple[PromptListEntryInput, ...]:
        if not entries:
            raise PromptListMutationError("Add at least one prompt.")
        if len(entries) > MAX_PROMPTS_PER_OWNED_LIST:
            raise PromptListMutationError(
                f"A prompt list can contain at most {MAX_PROMPTS_PER_OWNED_LIST} prompts."
            )
        cleaned: list[PromptListEntryInput] = []
        # A list in a language is unambiguous under that language's fold. A
        # language-agnostic one (#821) is played under whichever language the
        # room declares, so it has to be unambiguous under every one of them:
        # "Müller" and "Mueller" are two keys to the list and one to a German
        # room, which would then refuse the list at the door as ambiguous.
        folds = (
            PROMPT_LANGUAGES if language == AGNOSTIC_PROMPT_LANGUAGE else (language,)
        )
        seen_matches: dict[str, set[str]] = {fold: set() for fold in folds}
        seen_concepts: set[str] = set()
        for entry in entries:
            answer = " ".join(entry.answer.split())
            try:
                # Validates the answer (length, folded length) and keys it
                # under the list's own language, which is the fold the
                # ambiguity check below uses for a list in a language: each
                # text is folded once, not three times over (#1236).
                answer_key = normalize_prompt_answer(answer, language)
                aliases, alias_keys = clean_prompt_aliases_keyed(
                    list(entry.aliases),
                    canonical_key=answer_key,
                    language=language,
                )
            except ValueError as error:
                raise PromptListMutationError(str(error)) from error
            if language == AGNOSTIC_PROMPT_LANGUAGE:
                keyed = [prompt_match_keys(text, folds) for text in (answer, *aliases)]
                accepted_by_fold = {
                    fold: {keys[fold] for keys in keyed} for fold in folds
                }
            else:
                accepted_by_fold = {language: {answer_key, *alias_keys}}
            for fold, seen in seen_matches.items():
                accepted_keys = accepted_by_fold[fold]
                if seen.intersection(accepted_keys):
                    raise PromptListMutationError(
                        "Prompt answers and aliases must be unambiguous within a list."
                    )
                seen.update(accepted_keys)
            if entry.concept_id:
                try:
                    concept_id = str(UUID(entry.concept_id))
                except (ValueError, TypeError, AttributeError) as error:
                    raise PromptListMutationError("Invalid prompt identity.") from error
                if concept_id in seen_concepts:
                    raise PromptListMutationError(
                        "A prompt can appear only once in a list."
                    )
                seen_concepts.add(concept_id)
            else:
                concept_id = None
            cleaned.append(
                PromptListEntryInput(
                    answer=answer,
                    concept_id=concept_id,
                    aliases=aliases,
                )
            )
        return tuple(cleaned)

    @staticmethod
    def _clean_owned_metadata(
        *, name: str, description: str, language: str
    ) -> tuple[str, str, str]:
        name = " ".join(name.split())
        description = " ".join(description.split())
        if not name or len(name) > 64:
            raise PromptListMutationError("Name must be 1-64 characters.")
        if len(description) > 255:
            raise PromptListMutationError("Description must be at most 255 characters.")
        # The same refusal as an answer's (#1245), less the emoji joiner a
        # title may use: an override that turns the line around, or a name
        # that looks like another and is not, is spoofing in the catalogue.
        for label, text in (("Name", name), ("Description", description)):
            problem = visible_text_problem(text, emoji_joiner=True)
            if problem is not None:
                raise PromptListMutationError(f"{label} {problem}.")
        try:
            language = validate_prompt_list_language(language)
        except ValueError as error:
            raise PromptListMutationError(str(error)) from error
        return name, description, language

    @database_operation_of("community_catalogue")
    async def list_community(
        self,
        *,
        language: str | None = None,
        tags: Sequence[str] = (),
        sort: str = "stars",
        limit: int = 24,
        cursor: str | None = None,
        requesting_user_id: str | None = None,
        starred_only: bool = False,
    ) -> CommunityPromptListPage:
        """One page of published lists (R-LIST-14).

        Three conditions decide what is in the catalogue, and they are the
        same three everywhere: public, active, and not retired. A takedown or a
        deletion therefore drops a list out of here without a second code path
        agreeing to it.

        Star counts are derived from the rows rather than kept on the list
        (R-LIST-16), so nothing can drift. At this scale the aggregate is one
        grouped join; `user_stats_daily` is the precedent if it ever stops
        being.
        """
        requester_id = _optional_entity_id(requesting_user_id)
        limit = max(1, min(int(limit), MAX_COMMUNITY_PAGE))
        star_count = self._star_count().label("star_count")
        filters: list[ColumnElement[bool]] = list(_published_by_a_player())
        if starred_only:
            if requester_id is None:
                # Nobody's shortlist. The route refuses this first; the guard
                # is here so the query can never mean "everyone's stars".
                return CommunityPromptListPage(lists=(), next_cursor=None)
            filters.append(
                select(PromptListStar.prompt_list_id)
                .where(
                    PromptListStar.prompt_list_id == PromptList.id,
                    PromptListStar.user_id == requester_id,
                )
                .exists()
            )
        if language is not None:
            filters.append(_playable_in(language))
        for slug in tags:
            # One EXISTS per tag rather than an IN over all of them: a list
            # must carry *every* tag asked for, and an IN would match a list
            # carrying any one. Filters are capped at MAX_LIST_TAGS, so this
            # cannot grow without bound. The live edition's tags: what the
            # catalogue shows is what was published (#1360).
            filters.append(
                select(PromptListEditionTag.tag_id)
                .join(PromptTag, PromptTag.id == PromptListEditionTag.tag_id)
                .join(PromptListEdition, PromptListEdition.id == PromptListEditionTag.edition_id)
                .where(
                    PromptListEdition.prompt_list_id == PromptList.id,
                    PromptListEdition.state == EDITION_PUBLISHED,
                    PromptTag.slug == slug,
                )
                .exists()
            )
        # Ties broken by id, and the cursor carries both halves: two lists
        # published in the same millisecond, or with the same number of stars,
        # would otherwise be able to swap places between pages and let one of
        # them be shown twice or not at all.
        if sort == "newest":
            order = (PromptList.published_at.desc(), PromptList.id.desc())
        else:
            order = (
                desc(star_count),
                PromptList.published_at.desc(),
                PromptList.id.desc(),
            )
        offset = _decode_catalogue_cursor(cursor)
        # Offset paging, deliberately: the catalogue is browsed a few pages
        # deep at most, and a keyset cursor over a derived count would have to
        # re-rank on every request anyway. MAX_COMMUNITY_OFFSET is what keeps
        # a deep page from becoming a scan somebody can ask for repeatedly.
        # A shortlist is exempt: every row in it is a list this account starred,
        # so reading it to the end collects nothing the reader did not choose -
        # and the room picker does read it to the end, where stopping at the
        # ceiling would drop the rest without a word.
        if offset >= MAX_COMMUNITY_OFFSET and not starred_only:
            return CommunityPromptListPage(lists=(), next_cursor=None)
        live = aliased(PromptListEdition)
        columns = (
            PromptList,
            live,
            self._edition_prompt_count(live),
            star_count,
            User.display_name,
            self._copy_count(),
        )
        on_live = and_(live.prompt_list_id == PromptList.id, live.state == EDITION_PUBLISHED)
        ranked_page: list[UUID] | None = None
        if sort != "newest" and not starred_only and self._ranking.ttl_seconds > 0:
            # The star order is the one that has to count every published
            # list before it can return one; read it from the shared ranking
            # and fetch only this page's rows (#901).
            async def rank() -> tuple[UUID, ...]:
                async with self._session_factory() as session:
                    return tuple(
                        (
                            await session.scalars(
                                select(PromptList.id)
                                .where(*filters)
                                .order_by(*order)
                                .limit(CATALOGUE_RANKING_DEPTH)
                            )
                        ).all()
                    )

            ranked = await self._ranking.get((language, tuple(sorted(tags))), rank)
            ranked_page = list(ranked[offset : offset + limit + 1])
            stmt = (
                select(*columns)
                .join(User, User.id == PromptList.owner_user_id)
                .join(live, on_live)
                # Every filter again, not only the catalogue predicate: the
                # ranking is an order, and a list retagged or taken down
                # since it was read must not be served under a filter it no
                # longer meets.
                .where(PromptList.id.in_(ranked_page), *filters)
            )
        else:
            stmt = (
                select(*columns)
                .join(User, User.id == PromptList.owner_user_id)
                .join(live, on_live)
                .where(*filters)
                .order_by(*order)
                .offset(offset)
                .limit(limit + 1)
            )
        async with self._session_factory() as session:
            rows = (await session.execute(stmt)).all()
            if ranked_page is not None:
                # In the ranking's order; a list that has left the catalogue
                # since the ranking was read is simply not on the page.
                position = {list_id: index for index, list_id in enumerate(ranked_page)}
                rows.sort(key=lambda row: position[row[0].id])
                has_more = len(ranked_page) > limit
                rows = [row for row in rows if position[row[0].id] < limit]
            else:
                has_more = len(rows) > limit
                rows = rows[:limit]
            list_ids = [row[0].id for row in rows]
            tags_by_edition = await self._edition_tags(session, [row[1].id for row in rows])
            mine: set[UUID] = set()
            if requester_id is not None and list_ids:
                mine = {
                    row
                    for row in (
                        await session.scalars(
                            select(PromptListStar.prompt_list_id).where(
                                PromptListStar.user_id == requester_id,
                                PromptListStar.prompt_list_id.in_(list_ids),
                            )
                        )
                    ).all()
                }
        return CommunityPromptListPage(
            lists=tuple(
                CommunityPromptList(
                    id=_public_id(prompt_list.id),
                    slug=prompt_list.slug,
                    name=edition.name,
                    description=edition.description,
                    language=prompt_list.language,
                    prompt_count=int(prompt_count),
                    owner_display_name=display_name,
                    tags=tags_by_edition.get(edition.id, ()),
                    star_count=int(stars),
                    copy_count=int(copies),
                    published_at=prompt_list.published_at,
                    version=prompt_list.version,
                    starred_by_me=(
                        None if requester_id is None else prompt_list.id in mine
                    ),
                    is_mine=(
                        None
                        if requester_id is None
                        else prompt_list.owner_user_id == requester_id
                    ),
                )
                for prompt_list, edition, prompt_count, stars, display_name, copies in rows
            ),
            next_cursor=(
                _encode_catalogue_cursor(offset + limit) if has_more else None
            ),
        )

    async def get_community(
        self, prompt_list_id: str, *, requesting_user_id: str | None = None
    ) -> CommunityPromptListDetail | None:
        """One published list and what is in it (R-LIST-19).

        The same predicate the listing uses, so a list that left the catalogue
        cannot be read through here either - a takedown closes both doors at
        once, which is the property post-hoc moderation rests on.
        """
        list_id = _optional_entity_id(prompt_list_id)
        if list_id is None:
            return None
        requester_id = _optional_entity_id(requesting_user_id)
        async with self._session_factory() as session:
            live = aliased(PromptListEdition)
            row = (
                await session.execute(
                    select(
                        PromptList,
                        live,
                        self._edition_prompt_count(live),
                        self._star_count(),
                        User.display_name,
                        self._copy_count(),
                    )
                    .join(User, User.id == PromptList.owner_user_id)
                    .join(
                        live,
                        and_(
                            live.prompt_list_id == PromptList.id,
                            live.state == EDITION_PUBLISHED,
                        ),
                    )
                    .where(PromptList.id == list_id, *_published_by_a_player())
                )
            ).one_or_none()
            if row is None:
                return None
            prompt_list, edition, prompt_count, stars, display_name, copies = row
            credit = (await self._copied_from(session, [prompt_list.id])).get(
                prompt_list.id
            )
            # The live edition, never the working copy: an owner's unpublished
            # edits are nobody else's to read (#1360).
            entries = await self._edition_entries(session, edition.id)
            tags_by_edition = await self._edition_tags(session, [edition.id])
            starred_by_me = None
            if requester_id is not None:
                starred_by_me = (
                    await session.scalar(
                        select(PromptListStar.prompt_list_id).where(
                            PromptListStar.user_id == requester_id,
                            PromptListStar.prompt_list_id == prompt_list.id,
                        )
                    )
                ) is not None
        return CommunityPromptListDetail(
            id=_public_id(prompt_list.id),
            slug=prompt_list.slug,
            name=edition.name,
            description=edition.description,
            language=prompt_list.language,
            prompt_count=int(prompt_count),
            owner_display_name=display_name,
            tags=tags_by_edition.get(edition.id, ()),
            star_count=int(stars),
            copy_count=int(copies),
            copied_from=credit,
            published_at=prompt_list.published_at,
            version=prompt_list.version,
            starred_by_me=starred_by_me,
            is_mine=(
                None if requester_id is None else prompt_list.owner_user_id == requester_id
            ),
            prompts=tuple(
                dataclasses.replace(entry, aliases=())
                for entry in entries
                if entry.moderation_state == PromptContentModerationState.ACTIVE.value
            ),
        )

    @staticmethod
    async def _working_copy_tags(
        session: AsyncSession, list_ids: Sequence[UUID]
    ) -> dict[UUID, tuple[str, ...]]:
        """Tag slugs of each list's working copy, in vocabulary order (R-LIST-18)."""
        if not list_ids:
            return {}
        rows = (
            await session.execute(
                select(PromptListTag.prompt_list_id, PromptTag.slug)
                .join(PromptTag, PromptTag.id == PromptListTag.tag_id)
                .where(PromptListTag.prompt_list_id.in_(list(list_ids)))
            )
        ).all()
        held: dict[UUID, set[str]] = {}
        for list_id, slug in rows:
            held.setdefault(list_id, set()).add(slug)
        return {
            list_id: tuple(slug for slug in LIST_TAG_SLUG_ORDER if slug in slugs)
            for list_id, slugs in held.items()
        }

    async def _replace_list_tags(
        self, session: AsyncSession, list_id: UUID, tags: Sequence[str]
    ) -> None:
        """Make a working copy's tags `tags`, writing only the ones that changed."""
        wanted_tags = {row.id: row for row in await self._tag_rows(session, tags)}
        held_tags = set(
            (
                await session.scalars(
                    select(PromptListTag.tag_id).where(
                        PromptListTag.prompt_list_id == list_id
                    )
                )
            ).all()
        )
        if held_tags - set(wanted_tags):
            await session.execute(
                delete(PromptListTag).where(
                    PromptListTag.prompt_list_id == list_id,
                    PromptListTag.tag_id.in_(held_tags - set(wanted_tags)),
                )
            )
        session.add_all(
            PromptListTag(prompt_list_id=list_id, tag_id=tag_id)
            for tag_id in sorted(set(wanted_tags) - held_tags)
        )

    async def list_owned(self, owner_user_id: str) -> list[OwnedPromptList]:
        owner_id = _optional_entity_id(owner_user_id)
        if owner_id is None:
            return []
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(
                        PromptList,
                        self._prompt_count(),
                        self._star_count(),
                        self._copy_count(),
                    )
                    .where(
                        PromptList.owner_user_id == owner_id,
                        PromptList.is_bundled.is_(False),
                        PromptList.deleted_at.is_(None),
                    )
                    .order_by(PromptList.updated_at.desc(), PromptList.name)
                )
            ).all()
            # One query for every row's tags rather than one per row: the
            # collection is capped at 25 lists, but a per-row read here would
            # be the shape that stops being fine the moment the cap moves.
            tags_by_list = await self._working_copy_tags(
                session, [prompt_list.id for prompt_list, *_ in rows]
            )
            credits = await self._copied_from(
                session, [prompt_list.id for prompt_list, *_ in rows]
            )
            editions = await _editions_by_list(
                session, [prompt_list.id for prompt_list, *_ in rows]
            )
            return [
                _to_owned_prompt_list(
                    prompt_list,
                    prompt_count=int(prompt_count),
                    star_count=int(stars),
                    copy_count=int(copies),
                    copied_from=credits.get(prompt_list.id),
                    tags=tags_by_list.get(prompt_list.id, ()),
                    editions=editions.get(prompt_list.id),
                )
                for prompt_list, prompt_count, stars, copies in rows
            ]

    async def _owned_with_entries(
        self, session: AsyncSession, owner_id: UUID, prompt_list_id: UUID
    ) -> OwnedPromptList | None:
        """One owned list and its current content, in four statements whatever
        it holds (#1236).

        The content used to be read as an ORM graph - items, their versions,
        each version's alias links, each link's alias - which for a list at the
        ceiling (500 prompts of 20 aliases) is ~21,000 objects and 30
        statements, ~200 ms of the only event loop, on every open of the
        editor and three times over on every save. The counts ride the list's
        own row as subqueries, the content is one flat select, and the tags
        and the copy credit are one query each.
        """
        row = (
            await session.execute(
                select(
                    PromptList,
                    self._star_count(),
                    self._copy_count(),
                ).where(
                    PromptList.id == prompt_list_id,
                    PromptList.owner_user_id == owner_id,
                    PromptList.is_bundled.is_(False),
                    PromptList.deleted_at.is_(None),
                )
                .with_for_update(read=True, of=PromptList)
            )
        ).first()
        if row is None:
            return None
        prompt_list, stars, copies = row
        entries = await self._working_copy_entries(session, prompt_list.id)
        # One save's prompts beside the same save's tags: the list row is
        # held `FOR SHARE` (above), so a save - which takes it `FOR UPDATE` -
        # cannot commit between the two reads (#1291 review, #1359).
        tags = (await self._working_copy_tags(session, [prompt_list.id])).get(
            prompt_list.id, ()
        )
        credits = await self._copied_from(session, [prompt_list.id])
        editions = await _editions_by_list(session, [prompt_list.id])
        return _to_owned_prompt_list(
            prompt_list,
            entries,
            tags=tags,
            star_count=int(stars or 0),
            copy_count=int(copies or 0),
            copied_from=credits.get(prompt_list.id),
            editions=editions.get(prompt_list.id),
        )

    @staticmethod
    async def _working_copy_entries(
        session: AsyncSession, prompt_list_id: UUID
    ) -> tuple[PromptListEntry, ...]:
        """A list's working copy in order, from one flat select of
        (row, concept, version, answer, state, alias) (#1359)."""
        rows = (
            await session.execute(
                select(
                    Prompt.id,
                    PromptVersion.concept_id,
                    PromptVersion.id,
                    PromptVersion.canonical_answer,
                    PromptVersion.moderation_state,
                    PromptAlias.answer,
                )
                .select_from(Prompt)
                .join(PromptVersion, PromptVersion.id == Prompt.prompt_version_id)
                .outerjoin(
                    PromptVersionAlias,
                    PromptVersionAlias.prompt_version_id == PromptVersion.id,
                )
                .outerjoin(PromptAlias, PromptAlias.id == PromptVersionAlias.alias_id)
                .where(Prompt.prompt_list_id == prompt_list_id)
                .order_by(Prompt.position, Prompt.id)
            )
        ).all()
        by_row: dict[UUID, tuple[UUID, UUID, str, str, list[str]]] = {}
        for row_id, concept_id, version_id, answer, state, alias in rows:
            held = by_row.get(row_id)
            if held is None:
                held = by_row[row_id] = (concept_id, version_id, answer, state, [])
            if alias is not None:
                held[4].append(alias)
        return tuple(
            PromptListEntry(
                concept_id=_public_id(concept_id),
                prompt_version_id=_public_id(version_id),
                answer=answer,
                aliases=tuple(sorted(aliases)),
                moderation_state=state,
            )
            for concept_id, version_id, answer, state, aliases in by_row.values()
        )

    async def get_owned(
        self, owner_user_id: str, prompt_list_id: str
    ) -> OwnedPromptList | None:
        owner_id = _optional_entity_id(owner_user_id)
        list_id = _optional_entity_id(prompt_list_id)
        if owner_id is None or list_id is None:
            return None
        async with self._session_factory() as session:
            return await self._owned_with_entries(session, owner_id, list_id)

    async def create_owned(
        self,
        owner_user_id: str,
        *,
        name: str,
        description: str,
        language: str,
        prompts: Sequence[PromptListEntryInput],
        tags: Sequence[str] = (),
    ) -> OwnedPromptList:
        owner_id = _optional_entity_id(owner_user_id)
        if owner_id is None:
            raise PromptListMutationError("Invalid owner.")
        tag_slugs = self._clean_owned_tags(tags)
        name, description, language = self._clean_owned_metadata(
            name=name, description=description, language=language
        )
        entries = self._clean_owned_entries(prompts, language=language)
        if any(entry.concept_id for entry in entries):
            raise PromptListMutationError(
                "New lists cannot claim existing prompt identities."
            )
        async with self._session_factory() as session:
            async with session.begin():
                # Exclusive: the allowance is count-then-insert, and the
                # account row is what serialises two creates at the cap (#898).
                await require_live_account(session, owner_id, exclusive=True)
                if await _owned_list_count(session, owner_id) >= MAX_OWNED_PROMPT_LISTS:
                    raise PromptListMutationError(
                        f"An account can own at most {MAX_OWNED_PROMPT_LISTS} prompt lists.",
                        code=ErrorCode.PROMPT_LIST_ALLOWANCE_REACHED,
                        params={"max": MAX_OWNED_PROMPT_LISTS},
                    )
                list_id = generate_uuid()
                prompt_list = PromptList(
                    id=list_id,
                    owner_user_id=owner_id,
                    slug=f"user-{list_id}",
                    name=name,
                    description=description,
                    language=language,
                    is_bundled=False,
                    # Every list starts private; publishing is the only way
                    # out of it (R-LIST-02, R-LIST-11).
                    visibility=PromptListVisibility.PRIVATE.value,
                    moderation_state=PromptContentModerationState.ACTIVE.value,
                    version=1,
                )
                session.add(prompt_list)
                await session.flush()
                await self._write_working_copy(
                    session,
                    prompt_list=prompt_list,
                    entries=entries,
                    tags=tag_slugs,
                )
            result = await self._owned_with_entries(session, owner_id, list_id)
            assert result is not None
            return result

    async def update_owned(
        self,
        owner_user_id: str,
        prompt_list_id: str,
        *,
        expected_version: int,
        name: str,
        description: str,
        prompts: Sequence[PromptListEntryInput],
        tags: Sequence[str] = (),
    ) -> OwnedPromptList:
        owner_id = _optional_entity_id(owner_user_id)
        list_id = _optional_entity_id(prompt_list_id)
        if owner_id is None or list_id is None:
            raise PromptListNotFoundError("Prompt list not found.")
        tag_slugs = self._clean_owned_tags(tags)
        async with self._session_factory() as session:
            async with session.begin():
                await require_live_account(session, owner_id)
                prompt_list = await session.scalar(
                    select(PromptList)
                    .where(
                        PromptList.id == list_id,
                        PromptList.owner_user_id == owner_id,
                        PromptList.is_bundled.is_(False),
                        PromptList.deleted_at.is_(None),
                    )
                    .with_for_update()
                )
                if prompt_list is None:
                    raise PromptListNotFoundError("Prompt list not found.")
                # Before any of the content is looked at: a save that lost the
                # race is refused for the price of the lock, not of folding
                # every answer in the list (#1236).
                if prompt_list.version != expected_version:
                    raise PromptListConflictError(
                        "This list changed since you opened it. Reload before saving."
                    )
                # A save never changes visibility. Publishing is an act with a
                # gate, a rate limit and an audit event (R-LIST-11), and a save
                # that carried it either way would be a route around all three
                # - out of the catalogue as a side effect of fixing a typo, or
                # into it without the review. `publish` and `unpublish` are
                # the only ways across.
                name, description, _ = self._clean_owned_metadata(
                    name=name,
                    description=description,
                    language=prompt_list.language,
                )
                entries = self._clean_owned_entries(
                    prompts, language=prompt_list.language
                )
                # Only the tags are compared here, so only the tags are read:
                # this used to load the whole list to ask about them.
                current_tags = (
                    await self._working_copy_tags(session, [list_id])
                ).get(list_id, ())
                metadata_changed = (
                    prompt_list.name != name
                    or prompt_list.description != description
                    # Tags are the working copy's, so changing them is a change
                    # of content and moves the version, exactly as R-LIST-05
                    # says a name change does.
                    or current_tags != tag_slugs
                )
                next_version = prompt_list.version + 1
                if metadata_changed:
                    # Before the write, which digests them with the content.
                    prompt_list.name = name
                    prompt_list.description = description
                written = await self._write_working_copy(
                    session,
                    prompt_list=prompt_list,
                    entries=entries,
                    force=metadata_changed,
                    tags=tag_slugs,
                )
                if not written:
                    # An exact restatement of what is saved: nothing to
                    # version, nothing to rewrite (#613). The list and its
                    # optimistic version are as they were.
                    result = await self._owned_with_entries(session, owner_id, list_id)
                    assert result is not None
                    return result
                prompt_list.name = name
                prompt_list.description = description
                prompt_list.version = next_version
                prompt_list.updated_at = datetime.now(timezone.utc)
                retagged_in_catalogue = (
                    current_tags != tag_slugs
                    and prompt_list.visibility == PromptListVisibility.PUBLIC.value
                )
            if retagged_in_catalogue:
                # A tag filter's ranking was read over the old tags: a list
                # newly carrying one belongs on that page now (#901).
                self._ranking.invalidate()
            result = await self._owned_with_entries(session, owner_id, list_id)
            assert result is not None
            return result

    async def _copy_into_new_list(
        self,
        session: AsyncSession,
        *,
        owner_id: UUID,
        source: PromptList,
        name: str,
        lineage: bool,
        edition: PromptListEdition | None = None,
    ) -> UUID:
        """Write a new private list holding *source*'s working copy.

        The one place a list's content is carried into another list, shared by
        a copy of somebody's published list and a duplicate of one's own, so
        what may be carried is decided once for both: only prompt versions a
        moderator left active, through the editor's own validation, checked
        against the owner's allowance before anything is written. `lineage` is
        the difference - a copy records the list it came from and is marked as
        one (R-LIST-17, R-LIST-21, #1361); a duplicate records neither.
        """
        # Checked before anything is written, so a refusal at the cap
        # leaves nothing behind (R-LIST-08's spirit: fail visibly). Both
        # callers hold the owner's row exclusively, which is what makes this
        # count still true at the insert (#898).
        if await _owned_list_count(session, owner_id) >= MAX_OWNED_PROMPT_LISTS:
            raise PromptListMutationError(
                f"An account can own at most {MAX_OWNED_PROMPT_LISTS} "
                "prompt lists. Delete one first.",
                code=ErrorCode.PROMPT_LIST_ALLOWANCE_REACHED,
                params={"max": MAX_OWNED_PROMPT_LISTS},
            )
        # Only what a player may draw. Carrying a hidden version would hand
        # content a moderator took out of play to a new list - under a new
        # owner who never saw the decision, or back to its own author with a
        # fresh identity and none of the finding (R-LIST-07, R-MOD-11).
        held = (
            await self._edition_entries(session, edition.id)
            if edition is not None
            else await self._working_copy_entries(session, source.id)
        )
        entries = tuple(
            PromptListEntryInput(answer=entry.answer, aliases=entry.aliases)
            for entry in held
            if entry.moderation_state == PromptContentModerationState.ACTIVE.value
        )
        if not entries:
            raise PromptListMutationError("That list has no usable prompts to copy.")
        # Through the same validation an editor's save goes through, so the
        # next thing that carries entries cannot quietly acquire its own rules.
        entries = self._clean_owned_entries(entries, language=source.language)
        list_id = generate_uuid()
        created = PromptList(
            id=list_id,
            owner_user_id=owner_id,
            slug=f"user-{list_id}",
            name=name,
            description=edition.description if edition is not None else source.description,
            language=source.language,
            is_bundled=False,
            is_copy=lineage,
            copied_from_list_id=source.id if lineage else None,
            copied_from_edition_id=edition.id if lineage and edition is not None else None,
            visibility=PromptListVisibility.PRIVATE.value,
            moderation_state=PromptContentModerationState.ACTIVE.value,
            version=1,
        )
        session.add(created)
        await session.flush()
        await self._write_working_copy(
            session,
            prompt_list=created,
            entries=entries,
            tags=(
                (await self._edition_tags(session, [edition.id])).get(edition.id, ())
                if edition is not None
                else (await self._working_copy_tags(session, [source.id])).get(source.id, ())
            ),
        )
        return list_id

    async def fork_published(
        self, user_id: str, prompt_list_id: str
    ) -> OwnedPromptList:
        """Copy a published list into a private one of the caller's (R-LIST-17).

        Private on creation whatever the source is: a fork is somebody taking
        content to work on, and publishing it is a separate act with its own
        gate (R-LIST-11). Independent from the moment it exists, too - hiding
        the source afterwards does not reach into the copy, which is why the
        lineage may end up naming a list that is no longer served.

        The lineage names the source **list**, on the copy's own row (#1361):
        the credit reads it as it is now, so an edit on either side changes
        nothing, and the pointer is cleared when the source is deleted.
        """
        forker_id = _optional_entity_id(user_id)
        source_id = _optional_entity_id(prompt_list_id)
        if forker_id is None or source_id is None:
            raise PromptListNotFoundError("Prompt list not found.")
        async with self._session_factory() as session:
            async with session.begin():
                await require_live_account(session, forker_id, exclusive=True)
                source = await session.scalar(
                    select(PromptList)
                    .where(
                        PromptList.id == source_id,
                        *_published_by_a_player(),
                    )
                    # One save's prompts beside the same save's name and tags
                    # (#1385 review).
                    .with_for_update(read=True, of=PromptList)
                )
                if source is None:
                    raise PromptListNotFoundError("Prompt list not found.")
                # A copy credits and counts toward the list it came from
                # (R-LIST-20, R-LIST-21), and neither means anything when the
                # author is the one copying: the count would be the author's
                # own button presses, and the credit would name them to
                # themselves. Their own list is duplicated instead.
                if source.owner_user_id == forker_id:
                    raise PromptListMutationError(
                        "That list is already yours. Duplicate it from your own lists instead.",
                        code=ErrorCode.CANNOT_COPY_OWN_PROMPT_LIST,
                    )
                # From the live edition: what the copier saw in the catalogue,
                # never the author's unpublished working copy (#1360).
                edition = await session.scalar(
                    select(PromptListEdition).where(
                        PromptListEdition.prompt_list_id == source.id,
                        PromptListEdition.state == EDITION_PUBLISHED,
                    )
                )
                assert edition is not None, "the catalogue predicate requires one"
                list_id = await self._copy_into_new_list(
                    session,
                    owner_id=forker_id,
                    source=source,
                    name=edition.name,
                    lineage=True,
                    edition=edition,
                )
            result = await self._owned_with_entries(session, forker_id, list_id)
            assert result is not None
            return result

    async def duplicate_owned(
        self, owner_user_id: str, prompt_list_id: str, *, name: str
    ) -> OwnedPromptList:
        """A second private list of the owner's, with this one's saved contents.

        No lineage, no copy count, no credit (R-LIST-17): it is the author's own
        content twice. Done here rather than by the client re-creating the list
        from what the editor shows, because that shows hidden prompts and hidden
        lists to their owner, and an ordinary create would give their text new,
        active identities - a takedown undone by a button. So a list a moderator
        is holding or hid is refused, hidden prompt versions are left out, and
        a list that is itself a copy is refused too: a duplicate of it would be
        the credit R-LIST-21 says its owner cannot remove.
        """
        owner_id = _optional_entity_id(owner_user_id)
        list_id = _optional_entity_id(prompt_list_id)
        if owner_id is None or list_id is None:
            raise PromptListNotFoundError("Prompt list not found.")
        async with self._session_factory() as session:
            async with session.begin():
                await require_live_account(session, owner_id, exclusive=True)
                source = await session.scalar(
                    select(PromptList)
                    .where(
                        PromptList.id == list_id,
                        PromptList.owner_user_id == owner_id,
                        PromptList.is_bundled.is_(False),
                        PromptList.deleted_at.is_(None),
                    )
                    # One save's prompts beside the same save's name and tags:
                    # a save, holding the row FOR UPDATE, waits (#1385 review).
                    .with_for_update(read=True)
                )
                if source is None:
                    raise PromptListNotFoundError("Prompt list not found.")
                name, _, _ = self._clean_owned_metadata(
                    name=name,
                    description=source.description,
                    language=source.language,
                )
                if source.moderation_state != PromptContentModerationState.ACTIVE.value:
                    raise PromptListMutationError(
                        "A list under moderation cannot be duplicated.",
                        code=ErrorCode.CANNOT_DUPLICATE_PROMPT_LIST,
                        params={"reason": "moderation"},
                    )
                if source.is_copy:
                    raise PromptListMutationError(
                        "A copy of somebody else's list cannot be duplicated.",
                        code=ErrorCode.CANNOT_DUPLICATE_PROMPT_LIST,
                        params={"reason": "copy"},
                    )
                created_id = await self._copy_into_new_list(
                    session,
                    owner_id=owner_id,
                    source=source,
                    name=name,
                    lineage=False,
                )
            result = await self._owned_with_entries(session, owner_id, created_id)
            assert result is not None
            return result

    async def set_star(
        self, user_id: str, prompt_list_id: str, *, starred: bool
    ) -> int:
        """Star or unstar a **published** list (R-LIST-16).

        Published only, because a star is a public act about a public thing:
        a star on a private list would be lasting evidence that the starrer
        could see it, which only its owner can.

        Starring one's own list is allowed. It is a bookmark as much as a
        vote, and a rule against it would be a rule nobody can enforce anyway
        - a second account costs nothing, which is what the trust gate on
        publication is for rather than this.
        """
        starrer_id = _optional_entity_id(user_id)
        list_id = _optional_entity_id(prompt_list_id)
        if starrer_id is None or list_id is None:
            raise PromptListNotFoundError("Prompt list not found.")
        async with self._session_factory() as session:
            async with session.begin():
                await require_live_account(session, starrer_id)
                target = await session.scalar(
                    select(PromptList.id).where(
                        PromptList.id == list_id,
                        *_published_by_a_player(),
                    )
                )
                if target is None:
                    raise PromptListNotFoundError("Prompt list not found.")
                if starred:
                    # A savepoint, not a read-then-insert. Two requests for
                    # the same star - a double click, a retry - both saw no
                    # row and both inserted, and the loser got a primary-key
                    # IntegrityError for asking for a state that now holds.
                    # The composite key is still what makes starring twice
                    # one row; this is what makes it one row *concurrently*.
                    try:
                        async with session.begin_nested():
                            session.add(
                                PromptListStar(
                                    user_id=starrer_id, prompt_list_id=list_id
                                )
                            )
                    except IntegrityError:
                        pass
                else:
                    await session.execute(
                        delete(PromptListStar).where(
                            PromptListStar.user_id == starrer_id,
                            PromptListStar.prompt_list_id == list_id,
                        )
                    )
            return int(
                await session.scalar(
                    select(func.count())
                    .select_from(PromptListStar)
                    .where(PromptListStar.prompt_list_id == list_id)
                )
                or 0
            )

    async def set_owned_publication(
        self,
        owner_user_id: str,
        prompt_list_id: str,
        *,
        published: bool,
        under_review: bool = False,
        audit: AuditStamp | None = None,
    ) -> OwnedPromptList:
        """Publish or unpublish an owned list (R-LIST-11).

        Publishing is its own act rather than a `visibility` an ordinary save
        could carry, which is why this is not part of `update_owned`: the gate,
        the rate limit and the audit event all hang off the act, and a field on
        a save would be a way around all three.

        Publishing snapshots the working copy as the list's next **edition**
        (#1360): on a list already published, that is Publish update.
        `under_review` is the operator switch (R-LIST-13): the new edition
        waits for a moderator and the live one keeps playing. Unpublishing
        never changes a moderation state, because leaving the catalogue is not
        a moderator's finding.
        """
        owner_id = _optional_entity_id(owner_user_id)
        list_id = _optional_entity_id(prompt_list_id)
        if owner_id is None or list_id is None:
            raise PromptListNotFoundError("Prompt list not found.")
        async with self._session_factory() as session:
            async with session.begin():
                await require_live_account(session, owner_id)
                prompt_list = await session.scalar(
                    select(PromptList)
                    .where(
                        PromptList.id == list_id,
                        PromptList.owner_user_id == owner_id,
                        PromptList.is_bundled.is_(False),
                        PromptList.deleted_at.is_(None),
                    )
                    .with_for_update()
                )
                if prompt_list is None:
                    raise PromptListNotFoundError("Prompt list not found.")
                now = datetime.now(timezone.utc)
                editions = await editions_of(session, prompt_list.id)
                if published:
                    if (
                        prompt_list.moderation_state
                        == PromptContentModerationState.HIDDEN.value
                    ):
                        # A hidden list is one a moderator ruled on. Publishing
                        # it would put it back in front of people by the
                        # owner's own hand, which is the one thing a takedown
                        # has to survive.
                        raise PromptListMutationError(
                            "This list is hidden and cannot be published. "
                            "A moderator must review it first.",
                            code=ErrorCode.PROMPT_LIST_HIDDEN,
                        )
                    # Publishing - first, or a Publish update - snapshots the
                    # working copy as the next edition (#1360). Under the
                    # operator switch it waits for review and the live one
                    # keeps playing; otherwise it is live at once and replaces
                    # it. Republishing exactly what is already there - live,
                    # or already waiting - makes nothing.
                    version_ids, tags, digest = await working_copy_state(
                        session, prompt_list
                    )
                    # The working copy's digest as of now, written back: a
                    # list from before editions carries none, and comparing an
                    # empty one with the edition just made said "unpublished
                    # changes" of identical content (#1386 review).
                    prompt_list.content_hash = digest
                    state = EDITION_UNDER_REVIEW if under_review else EDITION_PUBLISHED
                    already = editions.get(state)
                    pending = editions.get(EDITION_UNDER_REVIEW)
                    repeat = (
                        already is not None
                        and already.content_hash == digest
                        and (state == EDITION_UNDER_REVIEW or pending is None)
                    )
                    changed = not repeat or (
                        prompt_list.visibility != PromptListVisibility.PUBLIC.value
                    )
                    if not repeat:
                        replaced = [pending.id] if pending is not None else []
                        if state == EDITION_PUBLISHED and already is not None:
                            replaced.append(already.id)
                        live = editions.get(EDITION_PUBLISHED)
                        if (
                            state == EDITION_UNDER_REVIEW
                            and live is not None
                            and prompt_list.visibility != PromptListVisibility.PUBLIC.value
                        ):
                            # Republishing a withdrawn list under the switch:
                            # the edition its owner took out of the catalogue
                            # would be back the moment the list turned public,
                            # unreviewed, beside the one waiting (#1386
                            # review). It goes; the list is out until release.
                            replaced.append(live.id)
                        await drop_editions(session, replaced, now=now)
                        await session.flush()
                        await snapshot_edition(
                            session,
                            prompt_list,
                            state=state,
                            now=now,
                            version_ids=version_ids,
                            tags=tags,
                            digest=digest,
                        )
                    if prompt_list.visibility != PromptListVisibility.PUBLIC.value:
                        prompt_list.visibility = PromptListVisibility.PUBLIC.value
                        prompt_list.published_at = now
                else:
                    # Withdrawing a list that is not out is nothing to record
                    # (#1241): no ledger row - they are permanent - and no
                    # catalogue re-rank. 200 withdrawals of a private list
                    # wrote 200 rows in 1.7 s.
                    pending = editions.get(EDITION_UNDER_REVIEW)
                    changed = (
                        prompt_list.visibility == PromptListVisibility.PUBLIC.value
                        or pending is not None
                    )
                    if changed:
                        prompt_list.visibility = PromptListVisibility.PRIVATE.value
                        prompt_list.published_at = None
                        # A hold is released by withdrawing, a finding is not:
                        # with nothing left to publish, the pending edition
                        # would sit in the moderators' queue as private content
                        # they could still decide on. The live edition stays,
                        # out of the catalogue with the list, so nothing a
                        # game or a copy points at goes (R-LIST-11). `hidden`
                        # is a moderator's ruling and stays, or withdrawal
                        # would launder a takedown.
                        if pending is not None:
                            await drop_editions(session, [pending.id], now=now)
                if changed:
                    prompt_list.updated_at = datetime.now(timezone.utc)
                # In this transaction, not a later one. Written after the
                # refusals above, so the ledger records what happened rather
                # than what was attempted - and with the change, so a failure
                # between the two cannot leave a list published with nothing
                # in the ledger to say who published it.
                if audit is not None and changed:
                    session.add(
                        AuditEvent(
                            id=generate_uuid(),
                            event_type=audit.event_type,
                            actor_user_id=_optional_entity_id(
                                audit.actor_user_id
                            ),
                            target_type=AuditTargetType.PROMPT_LIST.value,
                            target_id=str(prompt_list.id),
                            request_id=audit.request_id,
                            ip_hash=audit.ip_hash,
                            details={},
                            created_at=datetime.now(timezone.utc),
                        )
                    )
            # Committed: a list just published is in the catalogue for its
            # author's next read, not a minute later (#901).
            if changed:
                self._ranking.invalidate()
            result = await self._owned_with_entries(session, owner_id, list_id)
            assert result is not None
            return result

    async def delete_owned(self, owner_user_id: str, prompt_list_id: str) -> bool:
        """Retire the list: gone from the owner's view and from every room now,
        and collected whole by the sweep after a grace (`services.prompt_reclaim`,
        #605); the games that played it name the list and read the same without
        it (#1358)."""
        owner_id = _optional_entity_id(owner_user_id)
        list_id = _optional_entity_id(prompt_list_id)
        if owner_id is None or list_id is None:
            return False
        async with self._session_factory() as session:
            async with session.begin():
                prompt_list = await session.scalar(
                    select(PromptList)
                    .where(
                        PromptList.id == list_id,
                        PromptList.owner_user_id == owner_id,
                        PromptList.is_bundled.is_(False),
                        PromptList.deleted_at.is_(None),
                    )
                    .with_for_update()
                )
                if prompt_list is None:
                    return False
                await retire_prompt_list(session, prompt_list)
            return True

    async def seed_list_tags(self) -> tuple[str, ...]:
        """Make the curated vocabulary present, and its display names current.

        Idempotent, and run at startup beside the bundled lists. A slug is
        never rewritten - lists reference the row - so this inserts what is
        missing and refreshes the name on what is there, which is how a tag is
        renamed (R-LIST-18).
        """
        async with self._session_factory() as session:
            async with session.begin():
                existing = {
                    row.slug: row
                    for row in (
                        await session.scalars(
                            select(PromptTag).where(
                                PromptTag.slug.in_(list(LIST_TAG_SLUG_ORDER))
                            )
                        )
                    ).all()
                }
                for slug, name in LIST_TAG_VOCABULARY:
                    row = existing.get(slug)
                    if row is None:
                        session.add(
                            PromptTag(id=generate_uuid(), slug=slug, name=name)
                        )
                    elif row.name != name:
                        row.name = name
        return LIST_TAG_SLUG_ORDER

    @staticmethod
    def _clean_owned_tags(tags: Sequence[str]) -> tuple[str, ...]:
        try:
            return clean_list_tags(list(tags))
        except UnknownListTag as error:
            raise PromptListMutationError(
                str(error),
                code=ErrorCode.UNKNOWN_PROMPT_TAG,
                params={"tag": error.tag},
            ) from error
        except ValueError as error:
            # Too many tags: unreachable from the API, whose request bound
            # refuses it first, and from the editor, which disables the box.
            raise PromptListMutationError(str(error)) from error

    @staticmethod
    async def _tag_rows(
        session: AsyncSession, slugs: Sequence[str]
    ) -> list[PromptTag]:
        """The `prompt_tags` rows for these slugs, created if seeding has not.

        The vocabulary is seeded at startup, so this normally finds every row.
        Creating a missing one keeps a list save from depending on that having
        happened - an unknown slug cannot arrive here, because the vocabulary
        check ran before the transaction opened.
        """
        if not slugs:
            return []
        names = dict(LIST_TAG_VOCABULARY)
        found = {
            row.slug: row
            for row in (
                await session.scalars(
                    select(PromptTag).where(PromptTag.slug.in_(list(slugs)))
                )
            ).all()
        }
        for slug in slugs:
            if slug not in found:
                row = PromptTag(id=generate_uuid(), slug=slug, name=names[slug])
                session.add(row)
                found[slug] = row
        await session.flush()
        return [found[slug] for slug in slugs]

    async def _write_working_copy(
        self,
        session: AsyncSession,
        *,
        prompt_list: PromptList,
        entries: Sequence[PromptListEntryInput],
        force: bool = False,
        tags: Sequence[str] = (),
    ) -> bool:
        """Overwrite the list's working copy with `entries`, writing only what
        changed (#1359), or say that nothing about the content changed.

        Returns False, having written nothing, when every entry names its
        current concept with its current answer and aliases in the current
        order - the exact save an editor makes by pressing Save twice (#613).
        `force` goes on anyway, for a change to the metadata or the tags.
        Until #1359 every save wrote the whole list again as a new immutable
        revision: 500 item rows for a one-word edit of a 500-prompt list.
        """
        # The working copy being replaced, as flat rows rather than an ORM
        # graph: only these fields of each version are read below, and a list
        # at the ceiling was ~21,000 objects on every save (#1236).
        previous = await _working_copy_versions(session, prompt_list.id)
        current_by_concept = {version.concept_id: version for version in previous}
        # Every word the owner may not type back in: a word deleted and typed
        # in again - now, or a save later - is a new concept, and one existing
        # entry respelled into it is a new version of another; either way,
        # born with that entry's `active` it undid the takedown in a couple of
        # clicks (#1020 review). And not this list's alone: a word hidden in
        # one of the owner's lists typed into another of theirs - or a new
        # one - is the same word (#1091), in the languages where the word
        # means the same thing - this list's own, and no language at all
        # (#821, `languages_sharing_words`). The owner's takedown records say
        # which concepts those are (#1357); until they existed every revision
        # of every list the owner had ever held was searched, and revisions
        # had to outlive their lists to be found. A decision covers every
        # version of its concept, so each one's spellings are asked.
        hidden_versions = (
            (
                await session.scalars(
                    select(PromptVersion)
                    .where(
                        PromptVersion.moderation_state
                        == PromptContentModerationState.HIDDEN.value,
                        PromptVersion.language.in_(
                            languages_sharing_words(prompt_list.language)
                        ),
                        PromptVersion.concept_id.in_(
                            select(PromptTakedown.concept_id).where(
                                PromptTakedown.owner_user_id
                                == prompt_list.owner_user_id
                            )
                        ),
                    )
                    .options(
                        selectinload(PromptVersion.version_aliases).selectinload(
                            PromptVersionAlias.alias
                        )
                    )
                )
            ).unique().all()
            if prompt_list.owner_user_id is not None
            else ()
        )
        # A hidden word and an entry are the same word when a room that plays
        # both keys them as one word - its canonical key, not the wider set a
        # guess is accepted under (#821 review) - so each pair is
        # compared in the fold of such a room - keyed by that fold, which the
        # entry is keyed under too. A list in a language meets its own hidden
        # words by their stored keys, and an agnostic list's as that
        # language's rooms fold them. An agnostic list meets a hidden word in
        # a language in that language's fold: "Bär" hidden in German stops a
        # "Bär" here but not a "Bar", another word to a German room. And it
        # meets another agnostic list's hidden word in every room's fold,
        # since both are played in every room - the rule its own save keeps
        # (R-PROMPT-12): hidden "Müller" stops "Mueller".
        hidden_by_key: dict[tuple[str, str], PromptVersion] = {}
        for hidden in hidden_versions:
            texts = (
                hidden.canonical_answer,
                *(link.alias.answer for link in hidden.version_aliases),
            )
            stored = (
                hidden.match_key,
                *(link.alias.match_key for link in hidden.version_aliases),
            )
            if hidden.language == prompt_list.language != AGNOSTIC_PROMPT_LANGUAGE:
                pairs = [(prompt_list.language, key) for key in stored]
            elif prompt_list.language != AGNOSTIC_PROMPT_LANGUAGE:
                pairs = [
                    (prompt_list.language, prompt_match_key(text, prompt_list.language))
                    for text in texts
                ]
            elif hidden.language != AGNOSTIC_PROMPT_LANGUAGE:
                pairs = [(hidden.language, key) for key in stored]
            else:
                pairs = [
                    (fold, prompt_match_key(text, fold))
                    for fold in PROMPT_LANGUAGES
                    for text in texts
                ]
            for pair in pairs:
                hidden_by_key[pair] = hidden
        hidden_folds = {fold for fold, _ in hidden_by_key}
        supplied_ids = {
            UUID(entry.concept_id) for entry in entries if entry.concept_id is not None
        }
        if not supplied_ids.issubset(current_by_concept):
            raise PromptListMutationError(
                "A prompt identity does not belong to this list."
            )

        if not force and previous and _same_membership(previous, entries):
            return False

        alias_map: dict[tuple[UUID, str], PromptAlias] = {}
        if current_by_concept:
            aliases = (
                await session.scalars(
                    select(PromptAlias).where(
                        PromptAlias.concept_id.in_(current_by_concept),
                        PromptAlias.language == prompt_list.language,
                    )
                )
            ).all()
            alias_map = {
                (alias.concept_id, alias.match_key): alias for alias in aliases
            }

        resolved: list[tuple[UUID, PromptVersion, PromptListEntryInput]] = []
        pending_links: list[tuple[PromptVersion, PromptAlias]] = []
        carried_to: set[UUID] = set()
        for entry in entries:
            concept_id = UUID(entry.concept_id) if entry.concept_id else generate_uuid()
            existing = current_by_concept.get(concept_id)
            actual_aliases = existing.aliases if existing else ()
            if (
                existing is not None
                and existing.canonical_answer == entry.answer
                and actual_aliases == tuple(sorted(entry.aliases))
            ):
                resolved.append((concept_id, existing, entry))
                continue
            if existing is None:
                session.add(PromptConcept(id=concept_id))
                prompt_version_number = 1
            else:
                prompt_version_number = existing.version + 1
            prompt_version = PromptVersion(
                id=generate_uuid(),
                concept_id=concept_id,
                language=prompt_list.language,
                version=prompt_version_number,
                canonical_answer=entry.answer,
                match_key=normalize_prompt_answer(entry.answer, prompt_list.language),
            )
            decided_by = existing
            # A moderator who ruled this entry's word active has the last say
            # on that word: a hidden copy elsewhere must not re-hide it the
            # next time an alias is added (#1091 review). Respelled into a
            # different word, it is that word's decision that counts.
            ruled_active_as_is = (
                existing is not None
                and existing.moderation_state == PromptContentModerationState.ACTIVE.value
                and existing.moderated_at is not None
                and existing.match_key == prompt_version.match_key
            )
            if hidden_by_key and not ruled_active_as_is and not (
                existing is not None
                and existing.moderation_state
                == PromptContentModerationState.HIDDEN.value
            ):
                # Hidden wins over the entry's own state: an existing active
                # entry respelled into a hidden word is that word again.
                decided_by = next(
                    (
                        hidden_by_key[(fold, key)]
                        for fold in hidden_folds
                        for key in (
                            (
                                prompt_version.match_key,
                                *(
                                    normalize_prompt_answer(alias, prompt_list.language)
                                    for alias in entry.aliases
                                ),
                            )
                            if fold == prompt_list.language
                            else tuple(
                                prompt_match_key(text, fold)
                                for text in (entry.answer, *entry.aliases)
                            )
                        )
                        if (fold, key) in hidden_by_key
                    ),
                    existing,
                )
            if decided_by is not None:
                # A moderator's decision is about the concept, not one
                # spelling of it: a new version born `active` brought a hidden
                # word back in the list's next save with nobody asked -
                # add one alias and it was live again (#1020). The decision,
                # and who made it, carries to every version after it, and to
                # the same word deleted and typed in again; only a moderator
                # changes it.
                prompt_version.moderation_state = decided_by.moderation_state
                prompt_version.moderated_by_user_id = decided_by.moderated_by_user_id
                prompt_version.moderated_at = decided_by.moderated_at
                if decided_by is not existing:
                    # Carried from another of the owner's words: this concept
                    # is that takedown's too, so it is recorded - the next
                    # list, in a language only this one shares words with,
                    # finds it, and a restore finds it by its byline (#1357).
                    carried_to.add(concept_id)
            session.add(prompt_version)
            for alias_answer in entry.aliases:
                alias_key = normalize_prompt_answer(alias_answer, prompt_list.language)
                alias = alias_map.get((concept_id, alias_key))
                if alias is None:
                    alias = PromptAlias(
                        id=generate_uuid(),
                        concept_id=concept_id,
                        language=prompt_list.language,
                        answer=alias_answer,
                        match_key=alias_key,
                    )
                    session.add(alias)
                    alias_map[(concept_id, alias_key)] = alias
                pending_links.append((prompt_version, alias))
            resolved.append((concept_id, prompt_version, entry))
        await session.flush()
        session.add_all(
            PromptVersionAlias(
                prompt_version_id=prompt_version.id, alias_id=alias.id
            )
            for prompt_version, alias in pending_links
        )
        if carried_to:
            await record_takedowns(
                session,
                ((prompt_list.owner_user_id, concept_id) for concept_id in carried_to),
            )

        # The working copy as one digest, beside the live edition's: whether
        # the owner has changes not yet published (#1360). The caller has set
        # the name and description this save writes.
        prompt_list.content_hash = edition_content_hash(
            language=prompt_list.language,
            name=prompt_list.name,
            description=prompt_list.description,
            tags=tags,
            version_ids=[prompt_version.id for _, prompt_version, _ in resolved],
        )
        # Every member, whatever moderation currently says about it: a
        # takedown does not rewrite the list, so a tally of the active ones
        # would drift at the first decision and never come back on a restore.
        prompt_list.letter_counts, prompt_list.letter_total = letter_histogram(
            prompt_version.canonical_answer for _, prompt_version, _ in resolved
        )
        # The caller has already held the tags to the vocabulary
        # (`_clean_owned_tags`).
        await self._replace_list_tags(session, prompt_list.id, tags)

        # The display rows (`prompts`, unique on text within a list). Only a
        # row whose text or version actually changes is written; a row whose
        # new text is another retained row's current text - two answers
        # swapped - takes a temporary text first so the unique index never
        # sees both at once. Before #613 every retained row went through the
        # temporary text and back, two writes per unchanged prompt.
        transitional_rows = (
            await session.scalars(
                select(Prompt).where(Prompt.prompt_list_id == prompt_list.id)
            )
        ).all()
        rows_by_concept = {
            row.concept_id: row for row in transitional_rows if row.concept_id
        }
        retained = {concept_id for concept_id, _, _ in resolved}
        removed = [row for row in transitional_rows if row.concept_id not in retained]
        # The versions this save takes out of the working copy - a removed
        # prompt's, and a reworded one's old wording - are stamped, so the
        # sweep collects them a grace from now rather than at once: a game
        # that drew one still writes it into its turns when it ends (#1359).
        unlisted = {row.prompt_version_id for row in removed} | {
            row.prompt_version_id
            for concept_id, prompt_version, _ in resolved
            if (row := rows_by_concept.get(concept_id)) is not None
            and row.prompt_version_id != prompt_version.id
        }
        if unlisted:
            await _lock_versions(session, PromptVersion.id.in_(unlisted))
            await session.execute(
                update(PromptVersion)
                .where(PromptVersion.id.in_(unlisted))
                .values(unlisted_at=func.now(), unlisted_from_list_id=prompt_list.id)
                .execution_options(synchronize_session=False)
            )
        for row in removed:
            await session.delete(row)
        if removed:
            # Gone before anything new is inserted: the unit of work would
            # otherwise insert first, and a new prompt may reuse the text.
            await session.flush()
        occupied = {
            row.text
            for row in transitional_rows
            if row.concept_id in retained
        }
        new_texts = {
            entry.answer
            for concept_id, _, entry in resolved
            if concept_id not in rows_by_concept
        }
        changing = [
            (row, prompt_version, entry)
            for concept_id, prompt_version, entry in resolved
            if (row := rows_by_concept.get(concept_id)) is not None
            and (row.text != entry.answer or row.prompt_version_id != prompt_version.id)
        ]
        position_of = {
            concept_id: position for position, (concept_id, _, _) in enumerate(resolved)
        }
        # Order is the working copy's too, and only a row that moved is
        # written: rewording one prompt moves nothing.
        for concept_id, row in rows_by_concept.items():
            if concept_id in position_of and row.position != position_of[concept_id]:
                row.position = position_of[concept_id]
        colliding = [
            row
            for row, _, entry in changing
            if (entry.answer != row.text and entry.answer in occupied)
            or row.text in new_texts
        ]
        if colliding:
            for row in colliding:
                row.text = f"__editing__{row.id}"
            await session.flush()
        for row, prompt_version, entry in changing:
            row.prompt_version_id = prompt_version.id
            row.text = entry.answer
        for concept_id, prompt_version, entry in resolved:
            if concept_id not in rows_by_concept:
                session.add(
                    Prompt(
                        id=generate_uuid(),
                        prompt_list_id=prompt_list.id,
                        concept_id=concept_id,
                        prompt_version_id=prompt_version.id,
                        text=entry.answer,
                        position=position_of[concept_id],
                    )
                )
        return True

    async def get_prompts(self, prompt_list_id: str) -> list[str]:
        db_prompt_list_id = _optional_entity_id(prompt_list_id)
        if db_prompt_list_id is None:
            return []
        async with self._session_factory() as session:
            stmt = (
                select(Prompt.text)
                .where(Prompt.prompt_list_id == db_prompt_list_id)
                .order_by(Prompt.text)
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def _pinned_lists(
        self,
        session: AsyncSession,
        slugs: list[str],
        *,
        requesting_user_id: str | None,
        expected_language: str | None = None,
    ) -> tuple[list[_Pin], str]:
        """Authorize a selection and pin the lists it names.

        Shared by `resolve_selection` and `authorize_selection` so the two can
        never disagree about which lists a caller may combine: the checks a room
        is admitted by are the checks the game's prompts are drawn under. A
        room draws from each list at Start (#1359): from its working copy when
        the list is bundled or the room's host owns it - the owner tries their
        changes before publishing them - and from its live edition otherwise
        (#1360), which is what every other player sees.
        """
        requester_id = _optional_entity_id(requesting_user_id)
        list_rows = (
            await session.scalars(
                select(PromptList).where(
                    PromptList.slug.in_(slugs), PromptList.deleted_at.is_(None)
                )
            )
        ).all()
        authorized_rows = [
            row
            for row in list_rows
            if row.moderation_state == PromptContentModerationState.ACTIVE.value
            and (
                row.is_bundled
                or (requester_id is not None and row.owner_user_id == requester_id)
                # Published: the third ground a room may admit a list on
                # (R-LIST-15). It needs no capability because publishing is
                # the owner saying so, and it is checked here rather than at
                # the picker so that Start re-checks it too - which is what
                # makes an unpublish or a takedown between the two refuse the
                # room visibly instead of quietly shrinking its pool.
                or row.visibility == PromptListVisibility.PUBLIC.value
            )
        ]
        played_from_edition = [
            row.id
            for row in authorized_rows
            if not row.is_bundled
            and not (requester_id is not None and row.owner_user_id == requester_id)
        ]
        live_editions = {
            edition.prompt_list_id: edition
            for edition in (
                await session.scalars(
                    select(PromptListEdition).where(
                        PromptListEdition.prompt_list_id.in_(played_from_edition),
                        PromptListEdition.state == EDITION_PUBLISHED,
                    )
                )
            ).all()
        } if played_from_edition else {}
        # A published list with nothing live - a first publication still
        # waiting for review - is in nobody else's room either.
        authorized_rows = [
            row
            for row in authorized_rows
            if row.id not in played_from_edition or row.id in live_editions
        ]
        found = {row.slug for row in authorized_rows}
        missing = [slug for slug in slugs if slug not in found]
        if missing:
            raise PromptListSelectionError(
                f"Prompt list{'s' if len(missing) != 1 else ''} not found: "
                + ", ".join(missing)
            )
        if (
            sum(1 for row in authorized_rows if not row.is_bundled)
            > MAX_PLAYER_PROMPT_LISTS
        ):
            raise TooManyPlayerListsError(
                f"A room can use at most {MAX_PLAYER_PROMPT_LISTS} players' lists"
            )
        if expected_language == MIXED_PROMPT_LANGUAGE:
            return (
                await self._pinned_mixed_lists(
                    session,
                    slugs,
                    {row.slug: row for row in authorized_rows},
                    live_editions,
                ),
                MIXED_PROMPT_LANGUAGE,
            )
        # A language-agnostic list (#821) sits beside any language: it is
        # matched under whatever the room declares, so it is left out of the
        # agreement the lists owe each other.
        languages = {
            row.language
            for row in authorized_rows
            if row.language != AGNOSTIC_PROMPT_LANGUAGE
        }
        if len(languages) > 1:
            raise PromptListSelectionError(
                "Selected prompt lists must use the same language"
            )
        # The room declares the language and the lists answer to it
        # (R-PROMPT-02). Without this the language would still be a property of
        # whatever was selected last, which is what a declared field replaces.
        if expected_language is not None and not languages <= {expected_language}:
            raise PromptListSelectionError(
                "Selected prompt lists are not in this room's language"
            )
        # What the selection is matched under: the room's language when it
        # declared one, else the one the lists share - and `zxx` only when
        # every list is agnostic and nobody said which room it is for.
        language = (
            expected_language
            or next(iter(languages), None)
            or AGNOSTIC_PROMPT_LANGUAGE
        )
        rows_by_slug = {row.slug: row for row in authorized_rows}
        return [
            _Pin(rows_by_slug[slug], live_editions.get(rows_by_slug[slug].id))
            for slug in slugs
        ], language

    @staticmethod
    async def _members(
        session: AsyncSession, pins: Sequence[_Pin]
    ) -> dict[UUID, list[PromptVersion]]:
        """What each pinned list plays, as prompt versions in order, with their
        aliases loaded: what `resolve_selection` walks."""
        members: dict[UUID, list[PromptVersion]] = defaultdict(list)
        if not pins:
            return members
        held = _membership(pins)
        for list_id, prompt_version in (
            await session.execute(
                select(held.c.list_id, PromptVersion)
                .join(PromptVersion, PromptVersion.id == held.c.version_id)
                .order_by(held.c.list_id, held.c.position)
                .options(
                    selectinload(PromptVersion.version_aliases).selectinload(
                        PromptVersionAlias.alias
                    )
                )
            )
        ).all():
            members[list_id].append(prompt_version)
        return members

    async def _pinned_mixed_lists(
        self,
        session: AsyncSession,
        slugs: list[str],
        rows_by_slug: dict[str, PromptList],
        live_editions: Mapping[UUID, PromptListEdition],
    ) -> list[_Pin]:
        """Pin a mixed-language room's lists (#1182): every language of each.

        A list in no language is pinned as it is. A list in a language is
        admitted only with its **family** - the bundled lists whose working
        copies hold exactly its concepts - and only when that family spells
        every concept in every room language, because every seat must be able
        to play every prompt in its own: Standard, Extended and every themed
        official family (R-PROMPT-01), never Local; a list in one language is
        refused by name rather than quietly narrowing who may sit down. Asked
        of the data, not of a slug, so a family made some other way is admitted
        the same way - once per seed, by `_bundled_families`, rather than by
        reading every official list's prompts on every pin (#1374).
        """
        families = await self._bundled_families(session)
        wanted = {
            member
            for slug in slugs
            for member in families.members.get(rows_by_slug[slug].id, ())
        }
        # The other languages' members, still active and still here: the
        # families were worked out when the seed last ran, and a pin answers
        # for the lists as they are now.
        loaded = {
            member.id: member
            for member in (
                await session.scalars(
                    select(PromptList).where(
                        PromptList.id.in_(list(wanted)),
                        PromptList.is_bundled.is_(True),
                        PromptList.deleted_at.is_(None),
                        PromptList.moderation_state
                        == PromptContentModerationState.ACTIVE.value,
                    )
                )
            ).all()
        } if wanted else {}

        pinned: list[_Pin] = []
        for slug in slugs:
            row = rows_by_slug[slug]
            if row.language == AGNOSTIC_PROMPT_LANGUAGE:
                pinned.append(_Pin(row, live_editions.get(row.id)))
                continue
            members = families.members.get(row.id) if row.is_bundled else None
            if not members or any(member not in loaded for member in members):
                raise MixedRoomListError(
                    f"A mixed-language room cannot use this list: {slug}"
                )
            pinned.extend(_Pin(loaded[member]) for member in members)
        # A family chosen twice - two languages' Standard - is pinned once.
        return list({pin.id: pin for pin in pinned}.values())

    async def _bundled_families(self, session: AsyncSession) -> _BundledFamilies:
        """The official families, worked out once per seed (`_BundledFamilies`)."""
        if self._families is not None:
            return self._families
        generation = self._families_generation
        bundled = (
            await session.execute(
                select(PromptList.id, PromptList.slug, PromptList.language).where(
                    PromptList.is_bundled.is_(True),
                    PromptList.deleted_at.is_(None),
                    PromptList.moderation_state
                    == PromptContentModerationState.ACTIVE.value,
                    PromptList.language.in_(PROMPT_LANGUAGES),
                )
                .order_by(PromptList.slug)
            )
        ).all()
        concepts: dict[UUID, set[UUID]] = defaultdict(set)
        if bundled:
            for list_id, concept_id in (
                await session.execute(
                    select(Prompt.prompt_list_id, Prompt.concept_id).where(
                        Prompt.prompt_list_id.in_([row.id for row in bundled]),
                        Prompt.concept_id.is_not(None),
                    )
                )
            ).all():
                concepts[list_id].add(concept_id)
        by_content: dict[frozenset[UUID], dict[str, list[Row]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for row in bundled:
            by_content[frozenset(concepts[row.id])][row.language].append(row)
        members: dict[UUID, tuple[UUID, ...]] = {}
        names: dict[UUID, str] = {}
        for content, by_language in by_content.items():
            if not content or not set(PROMPT_LANGUAGES) <= set(by_language):
                continue
            # Ordered by slug, so a family keeps its name from one start to
            # the next. Two lists of one language with the same concepts are
            # both members: each is pinned with itself in its own language's
            # place and the first of the others, as a pin always was.
            first = {language: by_language[language][0] for language in PROMPT_LANGUAGES}
            name = first[PromptLanguage.ENGLISH.value].slug
            for language, rows in by_language.items():
                for row in rows:
                    members[row.id] = tuple(
                        row.id if member_language == language else first[member_language].id
                        for member_language in PROMPT_LANGUAGES
                    )
                    names[row.id] = name
        families = _BundledFamilies(members=members, names=names)
        if generation == self._families_generation:
            self._families = families
        return families

    async def resolve_selection(
        self,
        slugs: list[str],
        *,
        requesting_user_id: str | None = None,
        expected_language: str | None = None,
    ) -> ResolvedPromptSelection:
        if not slugs:
            raise PromptListSelectionError("Select at least one prompt list")
        async with self._session_factory() as session:
            lists, language = await self._pinned_lists(
                session,
                slugs,
                requesting_user_id=requesting_user_id,
                expected_language=expected_language,
            )
            members = await self._members(session, lists)
            prompts: list[str] = []
            aliases: dict[str, tuple[str, ...]] = {}
            prompt_version_ids: dict[str, str] = {}
            source_lists_by_version: dict[UUID, list[str]] = defaultdict(list)
            seen_versions: set[UUID] = set()
            seen_match_versions: dict[str, UUID] = {}
            for pinned in lists:
                for prompt_version in members[pinned.id]:
                    if (
                        prompt_version.moderation_state
                        != PromptContentModerationState.ACTIVE.value
                    ):
                        continue
                    source_lists_by_version[prompt_version.id].append(
                        _public_id(pinned.id)
                    )
                    if prompt_version.id in seen_versions:
                        continue
                    # Keyed from the text under the fold in force now, not
                    # from the keys the rows were written with: a fold that
                    # widened since (#1011's apostrophes) makes two stored
                    # keys one answer, and the game matches under the new
                    # fold, so the check that keeps a game's answers apart
                    # has to see what the game will see (review of #1070).
                    accepted_keys = {
                        prompt_match_key(prompt_version.canonical_answer, language),
                        *(
                            prompt_match_key(link.alias.answer, language)
                            for link in prompt_version.version_aliases
                        ),
                    }
                    if any(key in seen_match_versions for key in accepted_keys):
                        raise PromptListSelectionError(
                            "Selected prompt lists contain ambiguous answers or aliases"
                        )
                    seen_versions.add(prompt_version.id)
                    seen_match_versions.update(
                        (key, prompt_version.id) for key in accepted_keys
                    )
                    answer = prompt_version.canonical_answer
                    prompts.append(answer)
                    aliases[answer] = tuple(
                        sorted(
                            link.alias.answer
                            for link in prompt_version.version_aliases
                        )
                    )
                    prompt_version_ids[answer] = _public_id(prompt_version.id)
            if not prompts:
                raise PromptListSelectionError(
                    "Selected prompt lists do not contain any prompts"
                )
            return ResolvedPromptSelection(
                slugs=tuple(slugs),
                language=language,
                prompts=tuple(prompts),
                list_ids=tuple(_public_id(pinned.id) for pinned in lists),
                edition_ids=_edition_ids(lists),
                aliases=aliases,
                prompt_version_ids=prompt_version_ids,
                prompt_source_list_ids={
                    answer: tuple(source_lists_by_version[UUID(version_id)])
                    for answer, version_id in prompt_version_ids.items()
                },
            )

    async def authorize_selection(
        self,
        slugs: list[str],
        *,
        requesting_user_id: str | None = None,
        expected_language: str | None = None,
    ) -> PinnedPromptSelection:
        if not slugs:
            raise PromptListSelectionError("Select at least one prompt list")
        async with self._session_factory() as session:
            lists, language = await self._pinned_lists(
                session,
                slugs,
                requesting_user_id=requesting_user_id,
                expected_language=expected_language,
            )
            if language == MIXED_PROMPT_LANGUAGE:
                return await self._authorize_mixed(session, slugs, lists)
            list_ids = [pinned.id for pinned in lists]
            verdict = await self._remembered_verdict(
                session,
                ("single", language),
                lists,
                lambda: self._single_language_rows(session, lists),
                lambda rows: _single_language_verdict(rows, language),
            )
            if verdict.ambiguous:
                raise PromptListSelectionError(AMBIGUOUS_SELECTION)
            if not verdict.prompt_count:
                raise PromptListSelectionError(EMPTY_SELECTION)
            prompt_count = verdict.prompt_count

            letter_counts: Counter[str] = Counter()
            letter_total = 0
            for pinned in lists:
                letter_counts.update(pinned.letter_counts or {})
                letter_total += pinned.letter_total or 0

            return PinnedPromptSelection(
                slugs=tuple(slugs),
                language=language,
                list_ids=tuple(_public_id(list_id) for list_id in list_ids),
                list_versions=_working_copy_versions_of(lists),
                edition_ids=_edition_ids(lists),
                prompt_count=int(prompt_count),
                letter_counts=dict(letter_counts),
                letter_total=letter_total,
            )

    async def _remembered_verdict(
        self,
        session: AsyncSession,
        fold: tuple,
        lists: Sequence[_Pin],
        read_rows,
        judge,
    ) -> _SelectionVerdict:
        """The verdict on these lists under `fold`, remembered (#1237).

        Keyed by each list's version as well as its id: a save overwrites the
        working copy in place and moves the version (#1359), so a list at one
        version holds one content. What that content concludes then changes
        only when a moderator hides or restores a version in it - which is what
        the fingerprint reads, in one aggregate statement: how many members,
        how many active, and the latest decision. Toggling a room between two
        selections, or starting game after game on one, used to fold every
        answer of every list each time on the only event loop (3.3 s for
        twenty agnostic lists in a mixed room). A miss folds off the loop.

        The fingerprint is read before the rows, so a decision landing between
        the two leaves a verdict filed under the older fingerprint - which the
        next authorization then refuses to reuse. Never the other way round.
        """
        key = (fold, tuple(sorted(pin.key for pin in lists)))
        fingerprint = await self._moderation_fingerprint(session, lists)
        remembered = self._verdicts.get(key)
        if remembered is not None and remembered[0] == fingerprint:
            self._verdicts.move_to_end(key)
            return remembered[1]
        rows = await read_rows()
        verdict = await _off_loop(judge, rows)
        self._verdicts[key] = (fingerprint, verdict)
        self._verdicts.move_to_end(key)
        while len(self._verdicts) > MAX_REMEMBERED_VERDICTS:
            self._verdicts.popitem(last=False)
        return verdict

    @staticmethod
    async def _moderation_fingerprint(
        session: AsyncSession, pins: Sequence[_Pin]
    ) -> tuple:
        """What moderation has made of these lists' members, as one row.

        Of what each pinned list plays - its working copy or its live edition.

        The only way a version's state changes is a moderator's decision,
        which stamps `moderated_at`; the counts catch a decision that left
        the latest stamp where it was.
        """
        held = _membership(pins)
        row = (
            await session.execute(
                select(
                    func.count(),
                    func.sum(
                        case(
                            (
                                PromptVersion.moderation_state
                                == PromptContentModerationState.ACTIVE.value,
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    func.max(PromptVersion.moderated_at),
                )
                .select_from(held)
                .join(PromptVersion, PromptVersion.id == held.c.version_id)
            )
        ).one()
        return (int(row[0] or 0), int(row[1] or 0), row[2])

    @staticmethod
    async def _single_language_rows(
        session: AsyncSession, pins: Sequence[_Pin]
    ) -> list[Row]:
        """Every active prompt version's own answer and its aliases, as text.

        `resolve_selection` catches colliding answers by walking every prompt
        it loads. Pinning loads none, so the same question is asked of these
        rows instead: does any answer - a prompt's own or one of its aliases -
        reach two different prompt versions?
        """
        held = _membership(pins)
        active = [
            PromptVersion.moderation_state == PromptContentModerationState.ACTIVE.value,
        ]
        own_answers = select(
            held.c.version_id.label("version_id"),
            PromptVersion.canonical_answer.label("answer"),
        ).join(
            PromptVersion,
            PromptVersion.id == held.c.version_id,
        ).where(*active)
        alias_answers = select(
            held.c.version_id.label("version_id"),
            PromptAlias.answer.label("answer"),
        ).join(
            PromptVersion,
            PromptVersion.id == held.c.version_id,
        ).join(
            PromptVersionAlias,
            PromptVersionAlias.prompt_version_id == PromptVersion.id,
        ).join(
            PromptAlias, PromptAlias.id == PromptVersionAlias.alias_id
        ).where(*active)
        return await _rows_in_chunks(session, own_answers.union(alias_answers))

    async def sample_mixed_prompts(
        self,
        list_ids: Sequence[str],
        *,
        limit: int,
        expected_versions: Mapping[str, int] | None = None,
        edition_ids: Mapping[str, str] | None = None,
    ) -> PromptSample:
        if limit <= 0 or not list_ids:
            return PromptSample()
        pinned = _sources(list_ids, edition_ids)
        async with self._session_factory() as session:
            await _draw_snapshot(session, expected_versions, pinned)
            in_pinned = [
                PromptVersion.id.in_(select(_membership(pinned).c.version_id)),
                PromptVersion.moderation_state
                == PromptContentModerationState.ACTIVE.value,
            ]
            # Concepts first, then their forms: a random order over versions
            # would weigh a concept by how many languages spell it, and every
            # Standard concept is spelled once per language against an agnostic
            # prompt's once.
            # Only concepts every seat can play, decided before the limit: a
            # concept a takedown left short of a language is not drawn, and
            # asking afterwards could spend the whole random batch on those
            # while playable ones went unsampled (review of #1194).
            playable = (
                select(PromptVersion.concept_id)
                .where(*in_pinned)
                .group_by(PromptVersion.concept_id)
                .having(
                    or_(
                        func.max(
                            case(
                                (PromptVersion.language == AGNOSTIC_PROMPT_LANGUAGE, 1),
                                else_=0,
                            )
                        )
                        == 1,
                        func.count(func.distinct(PromptVersion.language))
                        >= len(PROMPT_LANGUAGES),
                    )
                )
            )
            concepts = (
                await session.scalars(playable.order_by(func.random()).limit(limit))
            ).all()
            if not concepts:
                return PromptSample()
            if len(concepts) < limit:
                drawable = len(concepts)
            else:
                drawable = max(
                    await session.scalar(
                        select(func.count()).select_from(playable.subquery())
                    )
                    or 0,
                    len(concepts),
                )
            versions = (
                await session.scalars(
                    select(PromptVersion)
                    .where(*in_pinned, PromptVersion.concept_id.in_(concepts))
                    .options(
                        selectinload(PromptVersion.version_aliases).selectinload(
                            PromptVersionAlias.alias
                        )
                    )
                )
            ).all()
            sources = await _source_lists(session, pinned, [version.id for version in versions])
            # In the same snapshot as the draw: false friends of the content
            # drawn, not of a save that landed since.
            false_friends = await self._mixed_false_friends(pinned, session=session)

        def form(version: PromptVersion) -> PromptTranslation:
            return PromptTranslation(
                answer=version.canonical_answer,
                aliases=tuple(sorted(link.alias.answer for link in version.version_aliases)),
                prompt_version_id=_public_id(version.id),
                source_list_ids=sources[version.id],
            )

        forms: dict[UUID, dict[str, PromptTranslation]] = defaultdict(dict)
        match_keys: dict[UUID, str] = {}
        for version in versions:
            forms[version.concept_id][version.language] = form(version)
            match_keys[version.concept_id] = version.match_key
        prompts: list[SampledPrompt] = []
        for concept_id in concepts:
            spelled = forms.get(concept_id, {})
            agnostic = spelled.get(AGNOSTIC_PROMPT_LANGUAGE)
            if agnostic is not None:
                translations: dict[str, PromptTranslation] = {}
                shown = agnostic
            elif set(PROMPT_LANGUAGES) <= set(spelled):
                translations = {language: spelled[language] for language in PROMPT_LANGUAGES}
                shown = translations[PROMPT_LANGUAGES[0]]
            else:
                drawable = max(0, drawable - 1)
                continue
            prompts.append(
                SampledPrompt(
                    answer=shown.answer,
                    match_key=match_keys[concept_id],
                    aliases=shown.aliases,
                    prompt_version_id=shown.prompt_version_id,
                    source_list_ids=shown.source_list_ids,
                    concept_id=_public_id(concept_id),
                    translations=translations,
                )
            )
        return PromptSample(
            prompts=tuple(prompts),
            drawable=drawable,
            false_friends=false_friends,
        )

    async def _mixed_false_friends(
        self, pins: Sequence[_Source], *, session: AsyncSession
    ) -> dict[str, dict[str, frozenset[str]]]:
        """`_mixed_false_friends` for these lists, remembered.

        Every version counts, hidden ones too: a hidden word is still what the
        word means to the seat, and leaving it out would only let a few more
        guesses through for the wrong drawing. Remembered by each list's
        version as well as its id: a save overwrites the working copy and
        moves the version (#1359), so one version is one content.
        """
        working = [pin.id for pin in pins if pin.edition_id is None]
        versions = {}
        if working:
            versions = dict(
                (
                    await session.execute(
                        select(PromptList.id, PromptList.version).where(
                            PromptList.id.in_(working)
                        )
                    )
                ).all()
            )
        key = tuple(
            sorted(
                ("e", str(pin.edition_id))
                if pin.edition_id is not None
                else ("l", str(pin.id), versions.get(pin.id))
                for pin in pins
            )
        )
        remembered = self._false_friends.get(key)
        if remembered is not None:
            self._false_friends.move_to_end(key)
            return remembered
        held = _membership(pins)
        answers = (
            select(PromptVersion.language, PromptVersion.concept_id, PromptVersion.canonical_answer)
            .join(held, held.c.version_id == PromptVersion.id)
        )
        aliases = (
            select(PromptVersion.language, PromptVersion.concept_id, PromptAlias.answer)
            .join(held, held.c.version_id == PromptVersion.id)
            .join(PromptVersionAlias, PromptVersionAlias.prompt_version_id == PromptVersion.id)
            .join(PromptAlias, PromptAlias.id == PromptVersionAlias.alias_id)
        )
        rows = await _rows_in_chunks(session, answers.union(aliases))
        found = await _off_loop(
            _mixed_false_friends,
            [(language, _public_id(concept), text) for language, concept, text in rows],
        )
        self._false_friends[key] = found
        while len(self._false_friends) > MAX_REMEMBERED_FALSE_FRIENDS:
            self._false_friends.popitem(last=False)
        return found

    async def _authorize_mixed(
        self,
        session: AsyncSession,
        slugs: list[str],
        lists: list[_Pin],
    ) -> PinnedPromptSelection:
        """What `authorize_selection` establishes, for a mixed-language room.

        Each room language sees its own lists and the lists in no language, so
        each is asked on its own: whether any answer reaches two prompts under
        that language's fold, and how often each letter appears, which prices
        the wheel for the seats playing in it. The count is of concepts - one
        prompt, however many languages spell it.
        """
        language_of = {pinned.id: pinned.language for pinned in lists}
        held = _membership(lists)

        active = [
            PromptVersion.moderation_state == PromptContentModerationState.ACTIVE.value,
        ]

        async def read_rows():
            rows = await _rows_in_chunks(
                session,
                select(
                    held.c.list_id,
                    PromptVersion.id,
                    PromptVersion.concept_id,
                    PromptVersion.canonical_answer,
                )
                .join(
                    PromptVersion,
                    PromptVersion.id == held.c.version_id,
                )
                .where(*active),
            )
            alias_rows = []
            if rows:
                # Joined to the items rather than listed by id: Standard and
                # Extended pinned in every language are ~17,000 versions on
                # their own (#1367), too many to bind one by one.
                alias_rows = await _rows_in_chunks(
                    session,
                    select(PromptVersionAlias.prompt_version_id, PromptAlias.answer)
                    .join(PromptAlias, PromptAlias.id == PromptVersionAlias.alias_id)
                    .join(
                        held,
                        held.c.version_id == PromptVersionAlias.prompt_version_id,
                    )
                    .join(
                        PromptVersion,
                        PromptVersion.id == held.c.version_id,
                    )
                    .where(*active),
                )
            return rows, alias_rows

        verdict = await self._remembered_verdict(
            session,
            ("mixed",),
            lists,
            read_rows,
            lambda read: _mixed_verdict(*read, language_of),
        )
        if verdict.ambiguous:
            raise PromptListSelectionError(AMBIGUOUS_SELECTION)
        if not verdict.prompt_count:
            raise PromptListSelectionError(EMPTY_SELECTION)

        counts: dict[str, Counter[str]] = {}
        totals: dict[str, int] = {}
        for room_language in PROMPT_LANGUAGES:
            tally: Counter[str] = Counter()
            total = 0
            for pinned in lists:
                if pinned.language in (room_language, AGNOSTIC_PROMPT_LANGUAGE):
                    tally.update(pinned.letter_counts or {})
                    total += pinned.letter_total or 0
            counts[room_language] = tally
            totals[room_language] = total

        return PinnedPromptSelection(
            slugs=tuple(slugs),
            language=MIXED_PROMPT_LANGUAGE,
            list_ids=tuple(_public_id(pinned.id) for pinned in lists),
            list_versions=_working_copy_versions_of(lists),
            edition_ids=_edition_ids(lists),
            prompt_count=verdict.prompt_count,
            letter_counts_by_language={
                language: dict(tally) for language, tally in counts.items()
            },
            letter_total_by_language=totals,
        )

    async def sample_prompts(
        self,
        list_ids: Sequence[str],
        *,
        limit: int,
        exclude_match_keys: Collection[str] = (),
        exclude_language: str | None = None,
        expected_versions: Mapping[str, int] | None = None,
        edition_ids: Mapping[str, str] | None = None,
    ) -> PromptSample:
        if limit <= 0 or not list_ids:
            return PromptSample()
        pinned = _sources(list_ids, edition_ids)
        excluded = set(exclude_match_keys)
        async with self._session_factory() as session:
            await _draw_snapshot(session, expected_versions, pinned)
            # Shadowed answers are excluded in the query rather than filtered
            # afterwards, so a draw returns what was asked for however much of
            # a list the room has claimed. Quick prompts are capped at
            # MAX_CUSTOM_PROMPTS (2000), well inside what either backend binds.
            eligible = [
                PromptVersion.id.in_(select(_membership(pinned).c.version_id)),
                PromptVersion.moderation_state
                == PromptContentModerationState.ACTIVE.value,
            ]
            if excluded:
                shadowed = PromptVersion.match_key.notin_(excluded)
                eligible.append(
                    shadowed
                    if exclude_language is None
                    else or_(PromptVersion.language != exclude_language, shadowed)
                )

            versions = (
                (
                    await session.execute(
                        select(PromptVersion)
                        .where(*eligible)
                        .order_by(func.random())
                        .limit(limit)
                        .options(
                            selectinload(PromptVersion.version_aliases).selectinload(
                                PromptVersionAlias.alias
                            )
                        )
                    )
                )
                .scalars()
                .all()
            )
            if not versions:
                return PromptSample()

            # The draw comes first and the count second, so a `drawable` this
            # draw already disproved is never reported. Postgres reads each
            # statement at its own snapshot, so a takedown committing between
            # the two would otherwise leave a count saying there is content and
            # a draw holding none - and a caller weighting on that count, or
            # trusting it to mean the lists are playable, would be wrong in the
            # one direction that matters. Fewer rows than asked for means there
            # are no more; only a full draw needs asking.
            if len(versions) < limit:
                drawable = len(versions)
            else:
                drawable = max(
                    await session.scalar(
                        select(func.count()).select_from(
                            select(PromptVersion.id).where(*eligible).subquery()
                        )
                    )
                    or 0,
                    len(versions),
                )

            # Which of the pinned lists each drawn prompt came from: a
            # version can sit in several selected lists, and a turn records
            # every source it was legitimately offered from.
            sources = await _source_lists(session, pinned, [version.id for version in versions])

            return PromptSample(
                prompts=tuple(
                    SampledPrompt(
                        answer=version.canonical_answer,
                        match_key=version.match_key,
                        aliases=tuple(
                            sorted(
                                link.alias.answer
                                for link in version.version_aliases
                            )
                        ),
                        prompt_version_id=_public_id(version.id),
                        source_list_ids=sources[version.id],
                        concept_id=_public_id(version.concept_id),
                    )
                    for version in versions
                ),
                drawable=drawable,
            )

    async def get_prompts_by_slugs(self, slugs: list[str]) -> list[str]:
        if not slugs:
            return []
        return list((await self.resolve_selection(slugs)).prompts)

    async def upsert_bundled(
        self,
        slug: str,
        name: str,
        description: str,
        language: str,
        prompts: Sequence[BundledPromptDefinition],
        version: int,
        *,
        shelf: str | None = None,
        series: str | None = None,
        shelf_position: int | None = None,
        tags: Sequence[str] = (),
    ) -> PromptListSummary:
        try:
            # Held to the vocabulary here too, not only by the seed, so a
            # caller passing another slug is refused as a seed conflict.
            list_tags = clean_list_tags(list(tags))
        except ValueError as error:
            raise PromptSeedConflictError(str(error)) from error
        list_tags = tuple(slug for slug in LIST_TAG_SLUG_ORDER if slug in list_tags)
        source_prompts = tuple(prompts)
        if not source_prompts:
            raise PromptSeedConflictError("bundled prompt lists cannot be empty")
        concept_ids = [UUID(prompt.concept_id) for prompt in source_prompts]
        if len(set(concept_ids)) != len(concept_ids):
            raise PromptSeedConflictError(
                "a concept may appear only once in a prompt-list revision"
            )
        answer_keys = [
            normalize_prompt_answer(prompt.answer, language)
            for prompt in source_prompts
        ]
        if len(set(answer_keys)) != len(answer_keys):
            raise PromptSeedConflictError(
                "a prompt-list revision cannot contain duplicate displayed answers"
            )
        content_hash = _bundled_revision_hash(
            language=language, prompts=source_prompts
        )

        async with self._session_factory() as session:
            async with session.begin():
                stmt = (
                    select(PromptList)
                    .where(PromptList.slug == slug)
                    .options(
                        selectinload(PromptList.prompts),
                        selectinload(PromptList.revisions),
                    )
                )
                result = await session.execute(stmt)
                wl = result.scalar_one_or_none()

                if wl is None:
                    existing_prompts: tuple[Prompt, ...] = ()
                    existing_revisions: tuple[PromptListRevision, ...] = ()
                    wl = PromptList(
                        id=generate_uuid(),
                        slug=slug,
                        name=name,
                        description=description,
                        language=language,
                        is_bundled=True,
                        visibility=PromptListVisibility.PUBLIC.value,
                        # The official catalogue is published by being seeded;
                        # `ck_prompt_lists_published_at` holds it to the same
                        # rule a player's list obeys (R-LIST-11).
                        published_at=datetime.now(timezone.utc),
                        moderation_state=PromptContentModerationState.ACTIVE.value,
                        version=version,
                    )
                    session.add(wl)
                    await session.flush()
                elif not wl.is_bundled:
                    raise PromptSeedConflictError(
                        f"bundled seed cannot replace user-owned list {slug}"
                    )
                else:
                    existing_prompts = tuple(wl.prompts)
                    existing_revisions = tuple(wl.revisions)

                existing_revision = next(
                    (
                        revision
                        for revision in existing_revisions
                        if revision.version == version
                    ),
                    None,
                )
                if existing_revision is not None:
                    if (
                        existing_revision.content_hash != content_hash
                        or existing_revision.language != language
                    ):
                        raise PromptSeedConflictError(
                            f"bundled list {slug} version {version} changed in place"
                        )
                    wl.name = name
                    wl.description = description
                    wl.visibility = PromptListVisibility.PUBLIC.value
                    wl.published_at = wl.published_at or datetime.now(timezone.utc)
                    wl.moderation_state = PromptContentModerationState.ACTIVE.value
                elif version < wl.version:
                    raise PromptSeedConflictError(
                        f"bundled list {slug} cannot roll back from version "
                        f"{wl.version} to {version}"
                    )
                else:
                    prompt_versions = await self._ensure_bundled_prompt_versions(
                        session, definitions=source_prompts, language=language
                    )
                    revision_counts, revision_total = letter_histogram(
                        prompt_version.canonical_answer
                        for prompt_version in prompt_versions
                    )
                    revision = PromptListRevision(
                        id=generate_uuid(),
                        prompt_list_id=wl.id,
                        version=version,
                        language=language,
                        content_hash=content_hash,
                        letter_counts=revision_counts,
                        letter_total=revision_total,
                    )
                    session.add(revision)
                    await session.flush()
                    session.add_all(
                        [
                            PromptListRevisionItem(
                                revision_id=revision.id,
                                prompt_version_id=prompt_version.id,
                                position=position,
                            )
                            for position, prompt_version in enumerate(prompt_versions)
                        ]
                    )

                    existing_by_concept = {
                        prompt.concept_id: prompt
                        for prompt in existing_prompts
                        if prompt.concept_id is not None
                    }
                    unlinked_by_key = {
                        prompt_match_key(prompt.text, language): prompt
                        for prompt in existing_prompts
                        if prompt.concept_id is None
                    }
                    selected_rows: dict[UUID, Prompt] = {}
                    # prompt_versions rides along unused so strict= keeps
                    # proving the three lists describe the same prompts.
                    for definition, _prompt_version, answer_key in zip(
                        source_prompts, prompt_versions, answer_keys, strict=True
                    ):
                        concept_id = UUID(definition.concept_id)
                        prompt_row = existing_by_concept.get(concept_id)
                        if prompt_row is None:
                            prompt_row = unlinked_by_key.get(answer_key)
                        if prompt_row is not None:
                            selected_rows[concept_id] = prompt_row

                    retained_ids = {id(prompt) for prompt in selected_rows.values()}
                    for prompt_row in existing_prompts:
                        if id(prompt_row) not in retained_ids:
                            await session.delete(prompt_row)
                    await session.flush()

                    for position, (definition, prompt_version) in enumerate(
                        zip(source_prompts, prompt_versions, strict=True)
                    ):
                        concept_id = UUID(definition.concept_id)
                        prompt_row = selected_rows.get(concept_id)
                        if prompt_row is None:
                            prompt_row = Prompt(
                                id=generate_uuid(),
                                prompt_list_id=wl.id,
                                concept_id=concept_id,
                                prompt_version_id=prompt_version.id,
                                text=definition.answer,
                                position=position,
                            )
                            session.add(prompt_row)
                        prompt_row.concept_id = concept_id
                        prompt_row.prompt_version_id = prompt_version.id
                        prompt_row.text = definition.answer
                        prompt_row.position = position

                    wl.name = name
                    wl.description = description
                    wl.language = language
                    wl.visibility = PromptListVisibility.PUBLIC.value
                    wl.published_at = wl.published_at or datetime.now(timezone.utc)
                    wl.moderation_state = PromptContentModerationState.ACTIVE.value
                    wl.version = version
                    # The working copy rooms draw from (#1359), priced like
                    # an owned list's: the revision keeps the same tally
                    # only for the seed's own conflict check.
                    wl.letter_counts = revision_counts
                    wl.letter_total = revision_total

                # Navigation, rewritten on every start whatever the version
                # (#1374): moving a list to another shelf is not new content.
                wl.shelf = shelf
                wl.series = series if shelf is not None else None
                wl.shelf_position = (shelf_position or 0) if shelf is not None else None
                await self._replace_list_tags(session, wl.id, list_tags)
            # Official content may have changed, and the families with it.
            self._families = None
            self._families_generation += 1

            await session.refresh(wl)
            prompt_count = await session.scalar(
                select(func.count(Prompt.id)).where(Prompt.prompt_list_id == wl.id)
            )
            return _to_prompt_list_summary(wl, int(prompt_count or 0), tags=list_tags)

    async def _ensure_bundled_prompt_versions(
        self,
        session: AsyncSession,
        *,
        definitions: Sequence[BundledPromptDefinition],
        language: str,
    ) -> list[PromptVersion]:
        """Resolve one source revision with bounded, set-based database reads."""
        concept_ids = [UUID(definition.concept_id) for definition in definitions]

        existing_concept_ids: set[UUID] = set()
        existing_versions: list[PromptVersion] = []
        for offset in range(0, len(concept_ids), 500):
            concept_chunk = concept_ids[offset : offset + 500]
            existing_concept_ids.update(
                (
                    await session.scalars(
                        select(PromptConcept.id).where(
                            PromptConcept.id.in_(concept_chunk)
                        )
                    )
                ).all()
            )
            existing_versions.extend(
                (
                    await session.scalars(
                        select(PromptVersion)
                        .where(
                            PromptVersion.concept_id.in_(concept_chunk),
                            PromptVersion.language == language,
                        )
                        .options(
                            selectinload(PromptVersion.version_aliases).selectinload(
                                PromptVersionAlias.alias
                            ),
                            selectinload(PromptVersion.version_tags).selectinload(
                                PromptVersionTag.tag
                            ),
                        )
                    )
                ).all()
            )

        session.add_all(
            PromptConcept(id=concept_id)
            for concept_id in concept_ids
            if concept_id not in existing_concept_ids
        )
        version_map = {
            (entry.concept_id, entry.version): entry for entry in existing_versions
        }
        latest_versions: dict[UUID, int] = defaultdict(int)
        for entry in existing_versions:
            latest_versions[entry.concept_id] = max(
                latest_versions[entry.concept_id], entry.version
            )

        resolved: list[PromptVersion] = []
        new_pairs: list[tuple[BundledPromptDefinition, PromptVersion]] = []
        for definition, concept_id in zip(definitions, concept_ids, strict=True):
            match_key = normalize_prompt_answer(definition.answer, language)
            prompt_version = version_map.get(
                (concept_id, definition.prompt_version)
            )
            if prompt_version is not None:
                actual_aliases = tuple(
                    sorted(
                        link.alias.answer
                        for link in prompt_version.version_aliases
                    )
                )
                actual_tags = tuple(
                    sorted(
                        link.tag.slug for link in prompt_version.version_tags
                    )
                )
                if (
                    prompt_version.canonical_answer != definition.answer
                    or prompt_version.match_key != match_key
                    or prompt_version.editorial_difficulty
                    != definition.editorial_difficulty
                    or prompt_version.content_rating != definition.content_rating
                    or actual_aliases != tuple(sorted(definition.aliases))
                    or actual_tags != tuple(sorted(definition.tags))
                ):
                    raise PromptSeedConflictError(
                        f"prompt concept {definition.concept_id} version "
                        f"{definition.prompt_version} changed in place"
                    )
                resolved.append(prompt_version)
                continue

            # A wording this database has never held in this language starts
            # wherever the file says: a fresh install seeds a reworded prompt
            # at its current version, never having seen the first. Only a
            # language that already holds versions must climb one at a time,
            # because a gap there is a version the file skipped (#1367).
            expected_version = latest_versions[concept_id] + 1
            if latest_versions[concept_id] and definition.prompt_version != expected_version:
                raise PromptSeedConflictError(
                    f"prompt concept {definition.concept_id} expected version "
                    f"{expected_version}, got {definition.prompt_version}"
                )
            prompt_version = PromptVersion(
                id=generate_uuid(),
                concept_id=concept_id,
                language=language,
                version=definition.prompt_version,
                canonical_answer=definition.answer,
                match_key=match_key,
                editorial_difficulty=definition.editorial_difficulty,
                content_rating=definition.content_rating,
            )
            session.add(prompt_version)
            latest_versions[concept_id] = definition.prompt_version
            new_pairs.append((definition, prompt_version))
            resolved.append(prompt_version)
        await session.flush()

        requested_alias_keys = {
            (UUID(definition.concept_id), normalize_prompt_answer(alias, language))
            for definition, _ in new_pairs
            for alias in definition.aliases
        }
        alias_map: dict[tuple[UUID, str], PromptAlias] = {}
        if requested_alias_keys:
            alias_concepts = {key[0] for key in requested_alias_keys}
            aliases = (
                await session.scalars(
                    select(PromptAlias).where(
                        PromptAlias.concept_id.in_(alias_concepts),
                        PromptAlias.language == language,
                    )
                )
            ).all()
            alias_map = {
                (alias.concept_id, alias.match_key): alias for alias in aliases
            }

        requested_tags = {
            tag for definition, _ in new_pairs for tag in definition.tags
        }
        tag_map = {
            tag.slug: tag
            for tag in (
                (
                    await session.scalars(
                        select(PromptTag).where(PromptTag.slug.in_(requested_tags))
                    )
                ).all()
                if requested_tags
                else []
            )
        }

        alias_links: list[tuple[PromptVersion, PromptAlias]] = []
        tag_links: list[tuple[PromptVersion, PromptTag]] = []
        for definition, prompt_version in new_pairs:
            concept_id = UUID(definition.concept_id)
            for alias_answer in definition.aliases:
                alias_key = normalize_prompt_answer(alias_answer, language)
                alias = alias_map.get((concept_id, alias_key))
                if alias is None:
                    alias = PromptAlias(
                        id=generate_uuid(),
                        concept_id=concept_id,
                        language=language,
                        answer=alias_answer,
                        match_key=alias_key,
                    )
                    session.add(alias)
                    alias_map[(concept_id, alias_key)] = alias
                elif alias.answer != alias_answer:
                    raise PromptSeedConflictError(
                        f"prompt alias {alias_answer!r} changes immutable display copy"
                    )
                alias_links.append((prompt_version, alias))
            for tag_slug in definition.tags:
                tag = tag_map.get(tag_slug)
                if tag is None:
                    tag = PromptTag(
                        id=generate_uuid(),
                        slug=tag_slug,
                        name=tag_slug.replace("-", " ").title(),
                    )
                    session.add(tag)
                    tag_map[tag_slug] = tag
                tag_links.append((prompt_version, tag))
        await session.flush()
        session.add_all(
            PromptVersionAlias(
                prompt_version_id=prompt_version.id, alias_id=alias.id
            )
            for prompt_version, alias in alias_links
        )
        session.add_all(
            PromptVersionTag(
                prompt_version_id=prompt_version.id, tag_id=tag.id
            )
            for prompt_version, tag in tag_links
        )
        return resolved

    @database_operation_of("prompt_usage")
    async def record_prompt_usage(
        self,
        prompt_list_ids: Sequence[str],
        usage: PromptUsage,
    ) -> None:
        """Append a game's ID-attributed facts to the lists it drew from.

        Each version is credited to the lists the draw found it in
        (`usage.sources`), and only to lists the game pinned, so a malformed
        internal call cannot credit a list the game never played. A list
        deleted since keeps its facts with the list set to null, as the
        `SET NULL` would have left them a moment after the write (#1358).
        """
        list_ids = [
            list_id
            for raw in prompt_list_ids
            if (list_id := _optional_entity_id(raw)) is not None
        ]
        batch_id = _optional_entity_id(usage.batch_id)
        if not list_ids or not usage:
            return
        if batch_id is None:
            raise ValueError("Prompt usage batch ID must be a UUID.")
        payload_hash = _prompt_usage_hash(list_ids, usage)
        pinned = set(list_ids)
        async with self._session_factory() as session:
            async with session.begin():
                existing = await session.get(PromptUsageBatch, batch_id)
                if existing is not None:
                    # A committed-after-timeout retry of the same finished game
                    # is harmless; the same id carrying different facts is not
                    # (#541). One transaction means a batch is all-or-none, so
                    # the batch row is proof the facts are there too.
                    if existing.payload_hash == payload_hash:
                        return
                    raise PromptUsageConflictError(
                        f"Prompt usage batch '{batch_id}' was retried with different facts."
                    )
                # Held against deletion until commit, so a list found here
                # cannot go before its facts land (the history write's rule).
                present = set(
                    (
                        await session.scalars(
                            select(PromptList.id)
                            .where(PromptList.id.in_(list_ids))
                            .with_for_update(read=True, key_share=True)
                        )
                    ).all()
                )
                facts: list[PromptUsageFact] = []
                for version_key in sorted({*usage.offers, *usage.picks}):
                    prompt_version_id = _optional_entity_id(version_key)
                    if prompt_version_id is None:
                        continue
                    offer_count = usage.offers.get(version_key, 0)
                    totals = usage.picks.get(version_key)
                    if offer_count <= 0 and totals is None:
                        continue
                    sources = {
                        list_id
                        for raw in usage.sources.get(version_key, ())
                        if (list_id := _optional_entity_id(raw)) in pinned
                    }
                    for list_id in sorted(sources):
                        facts.append(
                            PromptUsageFact(
                                batch_id=batch_id,
                                prompt_list_id=list_id if list_id in present else None,
                                prompt_version_id=prompt_version_id,
                                occurred_at=usage.occurred_at,
                                scoring_mode=usage.scoring_mode,
                                hint_mode=usage.hint_mode,
                                offer_count=offer_count,
                                pick_count=totals.picks if totals else 0,
                                correct_guess_count=(
                                    totals.correct_guesses if totals else 0
                                ),
                                total_guesser_count=(
                                    totals.total_guessers if totals else 0
                                ),
                            )
                        )
                # Written even when nothing matched - a batch of zero facts is
                # a game that offered nothing from its pinned lists, which is
                # not the same as a game whose usage was never written.
                session.add(
                    PromptUsageBatch(
                        batch_id=batch_id,
                        payload_hash=payload_hash,
                        fact_count=len(facts),
                    )
                )
                session.add_all(facts)

    async def get_prompt_stats(
        self,
        prompt_list_slug: str,
        *,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
        scoring_mode: str | None = None,
        hint_mode: str | None = None,
    ) -> list[PromptStatsSummary]:
        async with self._session_factory() as session:
            prompt_list = await session.scalar(
                select(PromptList).where(
                    PromptList.slug == prompt_list_slug,
                    PromptList.is_bundled.is_(True),
                    PromptList.moderation_state
                    == PromptContentModerationState.ACTIVE.value,
                )
            )
            if prompt_list is None:
                return []
            prompts = (
                await session.scalars(
                    select(Prompt)
                    .where(Prompt.prompt_list_id == prompt_list.id)
                    .order_by(Prompt.text)
                )
            ).all()

            fact_filters = [PromptUsageFact.prompt_list_id == prompt_list.id]
            if from_time is not None:
                fact_filters.append(PromptUsageFact.occurred_at >= from_time)
            if to_time is not None:
                fact_filters.append(PromptUsageFact.occurred_at < to_time)
            if scoring_mode is not None:
                fact_filters.append(PromptUsageFact.scoring_mode == scoring_mode)
            if hint_mode is not None:
                fact_filters.append(PromptUsageFact.hint_mode == hint_mode)
            aggregates = {
                concept_id: (offers, picks, correct, guessers)
                for concept_id, offers, picks, correct, guessers in (
                    await session.execute(
                        select(
                            PromptVersion.concept_id,
                            func.sum(PromptUsageFact.offer_count),
                            func.sum(PromptUsageFact.pick_count),
                            func.sum(PromptUsageFact.correct_guess_count),
                            func.sum(PromptUsageFact.total_guesser_count),
                        )
                        .join(
                            PromptUsageFact,
                            PromptUsageFact.prompt_version_id == PromptVersion.id,
                        )
                        .where(*fact_filters)
                        .group_by(PromptVersion.concept_id)
                    )
                ).all()
            }

            summaries: list[PromptStatsSummary] = []
            for prompt in prompts:
                offer_count, pick_count, correct_count, guesser_count = (
                    aggregates.get(prompt.concept_id, (0, 0, 0, 0))
                )
                pick_rate = pick_count / offer_count if offer_count > 0 else 0.0
                ratio = correct_count / guesser_count if guesser_count > 0 else 0.0
                summaries.append(
                    PromptStatsSummary(
                        text=prompt.text,
                        offer_count=offer_count,
                        pick_count=pick_count,
                        correct_guess_count=correct_count,
                        total_guesser_count=guesser_count,
                        pick_rate=round(pick_rate, 4),
                        correct_guess_ratio=round(ratio, 4),
                    )
                )
            return summaries
