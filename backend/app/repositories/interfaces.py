"""Abstract repository interfaces and domain transfer objects."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from app.domain_values import TurnEndReason


class RepositoryError(Exception):
    """Base class for domain repository errors."""
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


@dataclass(frozen=True)
class GameParticipantInput:
    """Input payload for a game participant's final standing."""

    user_id: str
    final_score: int
    final_rank: int
    turns_played: int = 0


@dataclass(frozen=True)
class TurnRecordInput:
    """Input payload for an individual turn/round in a game."""

    id: str
    round_number: int
    turn_number: int
    drawer_user_id: str
    prompt: str
    duration_seconds: float
    guesser_count: int = 0
    prompt_auto_picked: bool = False
    stroke_count: int = 0
    end_reason: str = TurnEndReason.TIMEOUT.value
    wrong_guess_count: int = 0
    near_miss_count: int = 0


@dataclass(frozen=True)
class TurnGuessInput:
    """Input payload for a correct guess in a round."""

    turn_id: str
    user_id: str
    points_awarded: int
    guess_time_seconds: float
    hints_used: int = 0
    points_spent_on_hints: int = 0
    wrong_guesses_before: int = 0


@dataclass(frozen=True)
class GameParticipantSummary:
    """Summary of player placement in a game record."""

    user_id: str
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


@dataclass(frozen=True)
class TurnGuessDetail:
    """Detailed guess event in a past round."""

    user_id: str
    display_name: str
    points_awarded: int
    guess_time_seconds: float


@dataclass(frozen=True)
class TurnDetail:
    """Detailed view of a single turn in a past game."""

    round_number: int
    turn_number: int
    drawer_user_id: str
    drawer_display_name: str
    prompt: str
    duration_seconds: float
    guesses: list[TurnGuessDetail] = field(default_factory=list)


@dataclass(frozen=True)
class GameDetail:
    """Complete detail view of a past game including all turns and guesses."""

    summary: GameSummary
    turns: list[TurnDetail] = field(default_factory=list)


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
    """One finished game's effect on a prompt list's counters.

    Keyed by the prompt as stored - trimmed and lower-cased - so the repository
    matches rows without re-deriving it. Aggregated across the game's turns,
    which is what lets the whole game be written in a few statements.
    """

    offers: Mapping[str, int]
    picks: Mapping[str, PromptPickTotals]

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
    async def list_all(self) -> list[PromptListSummary]:
        """List all available prompt lists."""
        ...

    @abstractmethod
    async def get_by_slug(self, slug: str) -> PromptListSummary | None:
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
    async def upsert_bundled(
        self,
        slug: str,
        name: str,
        description: str,
        language: str,
        prompts: list[str],
        version: int,
    ) -> PromptListSummary:
        """Insert or update a bundled prompt list, preserving existing usage statistics on matching prompts."""
        ...

    @abstractmethod
    async def record_prompt_usage(
        self,
        prompt_list_slugs: Sequence[str],
        usage: PromptUsage,
    ) -> None:
        """Apply one finished game's offers and picks to every named list.

        One call for the whole game rather than one per prompt per list: this
        runs at the moment a game ends, and a transaction per turn is the
        difference between a handful of statements and dozens of commits.
        """
        ...

    @abstractmethod
    async def get_prompt_stats(
        self,
        prompt_list_slug: str,
    ) -> list[PromptStatsSummary]:
        """Retrieve usage statistics and difficulty ratios for prompts in a list."""
        ...
