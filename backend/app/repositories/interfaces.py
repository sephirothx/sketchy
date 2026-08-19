"""Abstract repository interfaces and domain transfer objects."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


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
    avatar_url: str | None
    is_anonymous: bool
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime


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
    rounds_played: int = 0
    words_guessed: int = 0
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


@dataclass(frozen=True)
class RoundRecordInput:
    """Input payload for an individual turn/round in a game."""

    round_number: int
    turn_number: int
    drawer_user_id: str
    word: str
    duration_seconds: float
    id: str | None = None


@dataclass(frozen=True)
class RoundGuessInput:
    """Input payload for a correct guess in a round."""

    round_index: int  # 0-based index matching the list of RoundRecordInput
    user_id: str
    points_awarded: int
    guess_time_seconds: float


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
class RoundGuessDetail:
    """Detailed guess event in a past round."""

    user_id: str
    display_name: str
    points_awarded: int
    guess_time_seconds: float


@dataclass(frozen=True)
class RoundDetail:
    """Detailed view of a single turn in a past game."""

    round_number: int
    turn_number: int
    drawer_user_id: str
    drawer_display_name: str
    word: str
    duration_seconds: float
    guesses: list[RoundGuessDetail] = field(default_factory=list)


@dataclass(frozen=True)
class GameDetail:
    """Complete detail view of a past game including all rounds and guesses."""

    summary: GameSummary
    rounds: list[RoundDetail] = field(default_factory=list)


@dataclass(frozen=True)
class WordListSummary:
    """Summary metadata for a word list."""

    id: str
    slug: str
    name: str
    description: str
    language: str
    word_count: int
    is_bundled: bool
    version: int


@dataclass(frozen=True)
class WordStatsSummary:
    """Detailed statistics and derived difficulty metrics for a word."""

    text: str
    offer_count: int
    pick_count: int
    correct_guess_count: int
    total_guesser_count: int
    pick_rate: float
    correct_guess_ratio: float


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
    async def update_profile(
        self,
        user_id: str,
        *,
        display_name: str | None = None,
        name_color: str | None = None,
        avatar_url: str | None = None,
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
    """Data access boundary for finished game history and round logs."""

    @abstractmethod
    async def save_game(
        self,
        game_record: GameRecordInput,
        participants: list[GameParticipantInput],
        rounds: list[RoundRecordInput],
        guesses: list[RoundGuessInput],
    ) -> str:
        """Persist a completed game along with participants, rounds, and guesses in a single transaction."""
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


class WordListRepository(ABC):
    """Data access boundary for curated word lists and word usage statistics."""

    @abstractmethod
    async def list_all(self) -> list[WordListSummary]:
        """List all available word lists."""
        ...

    @abstractmethod
    async def get_by_slug(self, slug: str) -> WordListSummary | None:
        """Fetch a word list by its slug identifier."""
        ...

    @abstractmethod
    async def get_words(self, word_list_id: str) -> list[str]:
        """Retrieve word strings belonging to a specific list."""
        ...

    @abstractmethod
    async def get_words_by_slugs(self, slugs: list[str]) -> list[str]:
        """Retrieve deduplicated word strings across multiple word list slugs."""
        ...

    @abstractmethod
    async def upsert_bundled(
        self,
        slug: str,
        name: str,
        description: str,
        language: str,
        words: list[str],
        version: int,
    ) -> WordListSummary:
        """Insert or update a bundled word list, preserving existing usage statistics on matching words."""
        ...

    @abstractmethod
    async def increment_word_offers(
        self,
        word_list_slug: str,
        word_texts: list[str],
    ) -> None:
        """Increment the offer_count for words presented as options to the drawer."""
        ...

    @abstractmethod
    async def increment_word_stats(
        self,
        word_list_slug: str,
        word_text: str,
        correct_guesses: int,
        total_guessers: int,
    ) -> None:
        """Increment pick count, correct guess count, and potential guesser count for a drawn word."""
        ...

    @abstractmethod
    async def get_word_stats(
        self,
        word_list_slug: str,
    ) -> list[WordStatsSummary]:
        """Retrieve usage statistics and difficulty ratios for words in a list."""
        ...
