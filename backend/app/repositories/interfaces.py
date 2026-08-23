"""Abstract repository interfaces and domain transfer objects."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.domain_values import TurnEndReason
from app.identifiers import generate_uuid7


class RepositoryError(Exception):
    """Base class for domain repository errors."""
    pass


class GameHistoryConflictError(RepositoryError):
    """A stable game ID was reused with a different persistence payload."""

    pass


class AccountAlreadyClaimedError(RepositoryError):
    """Raised when attempting to claim an account that is already registered."""
    pass


class UsernameTakenError(RepositoryError):
    """Raised when attempting to register or claim a username that is already in use."""
    pass


class InvalidProfileDataError(RepositoryError):
    """Raised when profile update fields fail validation."""
    pass


class IdentityMergeError(RepositoryError):
    """Raised when a guest cannot be merged into a registered account."""
    pass


@dataclass(frozen=True)
class UserData:
    """Read-only public/domain user entity (without sensitive credential hashes)."""

    id: str
    username: str | None
    display_name: str
    name_color: str | None
    avatar_key: str | None
    is_anonymous: bool
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime
    last_active_at: datetime | None = None
    state: str = "anonymous"
    role: str = "user"


@dataclass(frozen=True)
class UserCredentials:
    """Internal authentication credential payload for password verification only."""

    user: UserData
    password_hash: str


@dataclass(frozen=True)
class UserStats:
    """Aggregated lifetime gameplay metrics for a user."""

    user_id: str
    games_played: int = 0
    games_won: int = 0
    win_rate: float = 0.0
    total_score: int = 0
    average_score: float = 0.0
    turns_played: int = 0
    prompts_guessed: int = 0
    drawings_made: int = 0


@dataclass(frozen=True)
class GameRecordInput:
    """Input payload for persisting a finished game."""

    room_name: str
    scoring_mode: str
    hint_mode: str
    drawing_seconds: int
    total_rounds: int
    player_count: int
    started_at: datetime
    finished_at: datetime
    id: str | None = None
    scoring_version: int = 0
    score_ledger_version: int = 0
    rule_snapshot_version: int = 0
    rule_snapshot: dict[str, object] = field(default_factory=dict)
    prompt_source_mode: str = "legacy_unknown"
    prompt_source_revision_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class GameParticipantInput:
    """Input payload for a game participant's final standing."""

    user_id: str | None
    final_score: int
    final_rank: int
    turns_played: int = 0
    seat_id: str | None = None
    display_name: str = "Unknown"
    name_color: str | None = None
    is_anonymous: bool = True


@dataclass(frozen=True)
class TurnParticipantOutcomeInput:
    """One participant seat's complete eligibility and result for a turn."""

    seat_id: str
    user_id: str | None
    eligible: bool
    eligibility_reason: str
    outcome: str
    terminal_state: str
    correct_guess_time_seconds: float | None = None
    wrong_guess_count: int = 0
    near_miss_count: int = 0
    hints_used: int = 0
    points_spent_on_hints: int = 0


@dataclass(frozen=True)
class TurnRecordInput:
    """Input payload for an individual turn/round in a game."""

    id: str
    round_number: int
    turn_number: int
    drawer_user_id: str | None
    prompt: str
    duration_seconds: float
    prompt_version_id: str | None = None
    prompt_source_kind: str = "legacy_unknown"
    guesser_count: int = 0
    prompt_auto_picked: bool = False
    stroke_count: int = 0
    end_reason: str = TurnEndReason.TIMEOUT.value
    wrong_guess_count: int = 0
    near_miss_count: int = 0
    prompt_offers: tuple[PromptOfferInput, ...] = ()
    drawer_seat_id: str | None = None
    participant_outcomes: tuple[TurnParticipantOutcomeInput, ...] = ()


@dataclass(frozen=True)
class PromptOfferInput:
    """One exact option offered to a drawer during a recorded turn."""

    position: int
    prompt: str
    selected: bool
    source_kind: str
    prompt_version_id: str | None = None
    source_revision_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class TurnGuessInput:
    """Input payload for a correct guess in a round."""

    turn_id: str
    user_id: str | None
    points_awarded: int
    guess_time_seconds: float
    hints_used: int = 0
    points_spent_on_hints: int = 0
    wrong_guesses_before: int = 0
    seat_id: str | None = None


@dataclass(frozen=True)
class ScoreEventInput:
    """One ordered, append-only point change in a finished game."""

    id: str
    participant_seat_id: str
    participant_user_id: str | None
    event_order: int
    event_type: str
    points_delta: int
    scoring_version: int
    rule_snapshot_version: int
    turn_id: str | None = None
    corrects_event_id: str | None = None


@dataclass(frozen=True)
class GameParticipantSummary:
    """Summary of player placement in a game record."""

    seat_id: str
    user_id: str | None
    display_name: str
    name_color: str | None
    is_anonymous: bool
    final_score: int
    final_rank: int


@dataclass(frozen=True)
class GameSummary:
    """Summary view of a past game."""

    id: str
    room_name: str
    scoring_mode: str
    hint_mode: str
    drawing_seconds: int
    total_rounds: int
    player_count: int
    started_at: datetime
    finished_at: datetime
    participants: list[GameParticipantSummary] = field(default_factory=list)
    scoring_version: int = 0
    score_ledger_version: int = 0
    rule_snapshot_version: int = 0
    rule_snapshot: dict[str, object] = field(default_factory=dict)
    prompt_source_mode: str = "legacy_unknown"


@dataclass(frozen=True)
class TurnGuessDetail:
    """Detailed guess event in a past round."""

    user_id: str | None
    seat_id: str | None
    display_name: str
    name_color: str | None
    is_anonymous: bool
    points_awarded: int
    guess_time_seconds: float


@dataclass(frozen=True)
class TurnParticipantOutcomeDetail:
    """Participant-visible factual outcome for one seat and turn."""

    seat_id: str
    eligible: bool
    eligibility_reason: str
    outcome: str
    terminal_state: str
    correct_guess_time_seconds: float | None
    wrong_guess_count: int
    near_miss_count: int
    hints_used: int
    points_spent_on_hints: int


@dataclass(frozen=True)
class ScoreEventDetail:
    """Participant-visible auditable score change."""

    id: str
    participant_seat_id: str
    participant_user_id: str | None
    event_order: int
    event_type: str
    points_delta: int
    scoring_version: int
    rule_snapshot_version: int
    turn_id: str | None
    corrects_event_id: str | None


@dataclass(frozen=True)
class TurnDetail:
    """Detailed view of a single turn in a past game."""

    round_number: int
    turn_number: int
    drawer_user_id: str | None
    drawer_seat_id: str | None
    drawer_display_name: str
    drawer_name_color: str | None
    drawer_is_anonymous: bool
    prompt: str
    duration_seconds: float
    prompt_version_id: str | None = None
    prompt_source_kind: str = "legacy_unknown"
    guesses: list[TurnGuessDetail] = field(default_factory=list)
    prompt_offers: list[PromptOfferDetail] = field(default_factory=list)
    participant_outcomes: list[TurnParticipantOutcomeDetail] = field(
        default_factory=list
    )


@dataclass(frozen=True)
class PromptOfferDetail:
    position: int
    prompt: str
    selected: bool
    source_kind: str
    prompt_version_id: str | None
    source_revision_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class GameDetail:
    """Complete detail view of a past game including all turns and guesses."""

    summary: GameSummary
    turns: list[TurnDetail] = field(default_factory=list)
    score_events: list[ScoreEventDetail] = field(default_factory=list)


@dataclass(frozen=True)
class PromptListSummary:
    """Summary metadata for a prompt list."""

    id: str
    slug: str
    name: str
    description: str
    language: str
    prompt_count: int
    is_bundled: bool
    version: int


@dataclass(frozen=True)
class PromptListEntryInput:
    """One ordered prompt supplied while creating or revising a player list."""

    answer: str
    concept_id: str | None = None
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class PromptListEntry:
    """Editable content from the latest immutable player-list revision."""

    concept_id: str
    prompt_version_id: str
    answer: str
    aliases: tuple[str, ...] = ()
    moderation_state: str = "active"


@dataclass(frozen=True)
class OwnedPromptList:
    """Owner-facing list metadata plus its current ordered content."""

    id: str
    slug: str
    name: str
    description: str
    language: str
    visibility: str
    share_code: str | None
    moderation_state: str
    version: int
    prompt_count: int
    created_at: datetime
    updated_at: datetime
    prompts: tuple[PromptListEntry, ...] = ()


@dataclass(frozen=True)
class SharedPromptList:
    """Capability-resolved list content safe to show to a signed-in player."""

    id: str
    slug: str
    name: str
    description: str
    language: str
    prompt_count: int
    is_bundled: bool
    version: int
    prompts: tuple[PromptListEntry, ...] = ()


@dataclass(frozen=True)
class ResolvedPromptSelection:
    """One valid, language-homogeneous prompt-list selection."""

    slugs: tuple[str, ...]
    language: str
    prompts: tuple[str, ...]
    revision_ids: tuple[str, ...] = ()
    aliases: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    prompt_version_ids: Mapping[str, str] = field(default_factory=dict)
    prompt_source_revision_ids: Mapping[str, tuple[str, ...]] = field(
        default_factory=dict
    )


class PromptListSelectionError(ValueError):
    """A selected list is missing or cannot be combined with the others."""


class PromptSeedConflictError(ValueError):
    """Bundled source contradicts an already-persisted immutable revision."""


class PromptListMutationError(ValueError):
    """A safe validation or authorization failure for a player-owned list."""


class PromptListConflictError(PromptListMutationError):
    """An edit was based on a stale immutable list revision."""


class PromptListNotFoundError(PromptListMutationError):
    """The requested player-owned list is absent or not owned by the caller."""


@dataclass(frozen=True, slots=True)
class BundledPromptDefinition:
    """One explicit prompt identity in a checked-in bundled seed file."""

    concept_id: str
    answer: str
    prompt_version: int = 1
    aliases: tuple[str, ...] = ()
    editorial_difficulty: str = "unspecified"
    content_rating: str = "everyone"
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class PromptStatsSummary:
    """Detailed statistics and derived difficulty metrics for a prompt."""

    text: str
    offer_count: int
    pick_count: int
    correct_guess_count: int
    total_guesser_count: int
    pick_rate: float
    correct_guess_ratio: float


@dataclass(frozen=True, slots=True)
class PromptPickTotals:
    """What being drawn cost one prompt over a whole game.

    More than one turn can land on the same prompt: a pool too small to keep
    excluding what it has already used starts offering repeats.
    """

    picks: int
    correct_guesses: int
    total_guessers: int


@dataclass(frozen=True, slots=True)
class PromptUsage:
    """One finished game's immutable prompt-usage fact batch.

    Keyed by immutable prompt-version ID. Display text is deliberately absent:
    ephemeral custom prompts can equal curated text without receiving curated
    attribution. Aggregation lets a whole game be written in a few statements.
    """

    offers: Mapping[str, int]
    picks: Mapping[str, PromptPickTotals]
    batch_id: str = field(default_factory=lambda: str(generate_uuid7()))
    occurred_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    scoring_mode: str = "default"
    hint_mode: str = "none"

    def __bool__(self) -> bool:
        return bool(self.offers or self.picks)


class UserRepository(ABC):
    """Data access boundary for user profiles and accounts."""

    @abstractmethod
    async def create_anonymous(
        self,
        display_name: str,
        name_color: str | None = None,
        user_id: str | None = None,
    ) -> UserData:
        """Create a new anonymous guest user."""
        ...

    @abstractmethod
    async def get_by_id(self, user_id: str) -> UserData | None:
        """Fetch user by unique ID without returning credential hashes."""
        ...

    @abstractmethod
    async def get_by_username(self, username: str) -> UserData | None:
        """Fetch user by case-insensitive unique username without returning credential hashes."""
        ...

    @abstractmethod
    async def get_credentials_by_username(self, username: str) -> UserCredentials | None:
        """Fetch user authentication credentials by case-insensitive username for auth verification."""
        ...

    @abstractmethod
    async def claim_account(
        self,
        user_id: str,
        username: str,
        password_hash: str,
    ) -> UserData:
        """Upgrade an anonymous user to a registered account with credentials."""
        ...

    @abstractmethod
    async def replace_password_hash(
        self, user_id: str, expected_hash: str, new_hash: str
    ) -> bool:
        """Atomically replace a credential hash if it has not changed."""
        ...

    @abstractmethod
    async def merge_guest_into_account(
        self, source_user_id: str, target_user_id: str
    ) -> UserData:
        """Alias a guest to an account without rewriting historical seats."""
        ...

    @abstractmethod
    async def update_profile(
        self,
        user_id: str,
        *,
        display_name: str | None = None,
        name_color: str | None = None,
        avatar_key: str | None = None,
    ) -> UserData | None:
        """Update display settings for a user."""
        ...

    @abstractmethod
    async def touch_last_login(
        self, user_id: str, min_interval_seconds: float = 0.0
    ) -> UserData | None:
        """Refresh ``last_login_at``, skipping the write if it is recent enough.

        ``GET /api/auth/me`` runs on every page load, so an unconditional write
        would mean a database round trip per visitor per load. Callers that only
        want a coarse "last seen" pass a non-zero interval; login and register
        pass 0 to always record the event.
        """
        ...

    @abstractmethod
    async def touch_last_active(self, user_id: str) -> UserData | None:
        """Record meaningful gameplay activity for retention decisions."""
        ...

    @abstractmethod
    async def get_stats(self, user_id: str) -> UserStats:
        """Calculate aggregated lifetime statistics for a user."""
        ...


class GameHistoryRepository(ABC):
    """Data access boundary for finished game history and turn logs."""

    @abstractmethod
    async def save_game(
        self,
        game_record: GameRecordInput,
        participants: list[GameParticipantInput],
        turns: list[TurnRecordInput],
        guesses: list[TurnGuessInput],
        score_events: list[ScoreEventInput] | None = None,
    ) -> str:
        """Persist a completed game along with participants, turns, and guesses in a single transaction."""
        ...

    @abstractmethod
    async def get_user_games(
        self,
        user_id: str,
        limit: int = 20,
        offset: int = 0,
    ) -> list[GameSummary]:
        """Fetch clamped paginated summary of games where a user participated."""
        ...

    @abstractmethod
    async def get_game_detail(
        self,
        game_id: str,
        requesting_user_id: str | None = None,
    ) -> GameDetail | None:
        """Fetch full round-by-round details for a specific game, optionally scoped to a participant."""
        ...


class PromptListRepository(ABC):
    """Data access boundary for curated prompt lists and prompt usage statistics."""

    @abstractmethod
    async def list_all(
        self, *, language: str | None = None, locale: str | None = None
    ) -> list[PromptListSummary]:
        """List prompt lists, optionally filtering content and localizing copy."""
        ...

    @abstractmethod
    async def get_by_slug(
        self, slug: str, *, locale: str | None = None
    ) -> PromptListSummary | None:
        """Fetch a prompt list by its slug identifier."""
        ...

    @abstractmethod
    async def get_prompts(self, prompt_list_id: str) -> list[str]:
        """Retrieve prompt strings belonging to a specific list."""
        ...

    @abstractmethod
    async def get_prompts_by_slugs(self, slugs: list[str]) -> list[str]:
        """Retrieve deduplicated prompt strings across multiple prompt list slugs."""
        ...

    @abstractmethod
    async def resolve_selection(
        self,
        slugs: list[str],
        *,
        requesting_user_id: str | None = None,
        share_codes: Sequence[str] = (),
    ) -> ResolvedPromptSelection:
        """Resolve an authorized, language-homogeneous list selection."""
        ...

    @abstractmethod
    async def list_owned(self, owner_user_id: str) -> list[OwnedPromptList]:
        """List the caller's reusable prompt lists without their prompt bodies."""
        ...

    @abstractmethod
    async def get_owned(
        self, owner_user_id: str, prompt_list_id: str
    ) -> OwnedPromptList | None:
        """Return one owned list with its current immutable content."""
        ...

    @abstractmethod
    async def get_shared(self, share_code: str) -> SharedPromptList | None:
        """Resolve active unlisted-list content by its explicit bearer code."""
        ...

    @abstractmethod
    async def create_owned(
        self,
        owner_user_id: str,
        *,
        name: str,
        description: str,
        language: str,
        visibility: str,
        prompts: Sequence[PromptListEntryInput],
    ) -> OwnedPromptList:
        """Create a reusable player list and immutable revision one."""
        ...

    @abstractmethod
    async def update_owned(
        self,
        owner_user_id: str,
        prompt_list_id: str,
        *,
        expected_version: int,
        name: str,
        description: str,
        visibility: str,
        prompts: Sequence[PromptListEntryInput],
    ) -> OwnedPromptList:
        """Create the next immutable revision using optimistic concurrency."""
        ...

    @abstractmethod
    async def delete_owned(self, owner_user_id: str, prompt_list_id: str) -> bool:
        """Delete a player-owned list and all of its revisions."""
        ...

    @abstractmethod
    async def upsert_bundled(
        self,
        slug: str,
        name: str,
        description: str,
        language: str,
        prompts: Sequence[BundledPromptDefinition],
        version: int,
    ) -> PromptListSummary:
        """Store one immutable bundled revision without text-keyed identity."""
        ...

    @abstractmethod
    async def record_prompt_usage(
        self,
        prompt_list_revision_ids: Sequence[str],
        usage: PromptUsage,
    ) -> None:
        """Append one finished game's offers and picks to every pinned revision.

        One call for the whole game rather than one per prompt per revision: this
        runs at the moment a game ends, and a transaction per turn is the
        difference between a handful of statements and dozens of commits.
        """
        ...

    @abstractmethod
    async def get_prompt_stats(
        self,
        prompt_list_slug: str,
        *,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
        scoring_mode: str | None = None,
        hint_mode: str | None = None,
    ) -> list[PromptStatsSummary]:
        """Derive windowed/dimensioned statistics from immutable usage facts."""
        ...
