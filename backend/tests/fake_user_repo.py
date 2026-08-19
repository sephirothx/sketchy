"""In-memory UserRepository for handler tests that need account identity."""
from __future__ import annotations

from datetime import datetime, timezone

from app.repositories.interfaces import (
    AccountAlreadyClaimedError,
    UserCredentials,
    UserData,
    UsernameTakenError,
    UserRepository,
    UserStats,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class FakeUserRepository(UserRepository):
    """Dict-backed stand-in with the same identity semantics as the real one."""

    def __init__(self) -> None:
        self.users: dict[str, UserData] = {}
        self.password_hashes: dict[str, str] = {}
        self._counter = 0

    def add_guest(self, user_id: str, display_name: str = "Guest") -> UserData:
        user = UserData(
            id=user_id,
            username=None,
            display_name=display_name,
            name_color=None,
            avatar_url=None,
            is_anonymous=True,
            created_at=_now(),
            updated_at=_now(),
            last_login_at=_now(),
        )
        self.users[user_id] = user
        return user

    def add_registered(
        self, user_id: str, username: str, password_hash: str = "hash"
    ) -> UserData:
        user = UserData(
            id=user_id,
            username=username,
            display_name=username,
            name_color=None,
            avatar_url=None,
            is_anonymous=False,
            created_at=_now(),
            updated_at=_now(),
            last_login_at=_now(),
        )
        self.users[user_id] = user
        self.password_hashes[user_id] = password_hash
        return user

    async def create_anonymous(
        self,
        display_name: str,
        name_color: str | None = None,
        user_id: str | None = None,
    ) -> UserData:
        self._counter += 1
        return self.add_guest(user_id or f"guest-{self._counter}", display_name or "Guest")

    async def get_by_id(self, user_id: str) -> UserData | None:
        return self.users.get(user_id)

    async def get_by_username(self, username: str) -> UserData | None:
        target = username.strip().lower()
        return next(
            (u for u in self.users.values() if (u.username or "").lower() == target),
            None,
        )

    async def get_credentials_by_username(self, username: str) -> UserCredentials | None:
        user = await self.get_by_username(username)
        if not user or user.id not in self.password_hashes:
            return None
        return UserCredentials(user=user, password_hash=self.password_hashes[user.id])

    async def claim_account(
        self, user_id: str, username: str, password_hash: str
    ) -> UserData:
        user = self.users.get(user_id)
        if user is None:
            raise ValueError(f"User '{user_id}' not found")
        if not user.is_anonymous:
            raise AccountAlreadyClaimedError("Account has already been claimed")
        existing = await self.get_by_username(username)
        if existing is not None and existing.id != user_id:
            raise UsernameTakenError(f"Username '{username}' is already taken")
        claimed = UserData(
            id=user.id,
            username=username,
            display_name=username,
            name_color=user.name_color,
            avatar_url=user.avatar_url,
            is_anonymous=False,
            created_at=user.created_at,
            updated_at=_now(),
            last_login_at=_now(),
        )
        self.users[user_id] = claimed
        self.password_hashes[user_id] = password_hash
        return claimed

    async def update_profile(
        self,
        user_id: str,
        *,
        display_name: str | None = None,
        name_color: str | None = None,
        avatar_url: str | None = None,
    ) -> UserData | None:
        user = self.users.get(user_id)
        if user is None:
            return None
        updated = UserData(
            id=user.id,
            username=user.username,
            display_name=display_name if display_name is not None else user.display_name,
            name_color=name_color if name_color is not None else user.name_color,
            avatar_url=avatar_url if avatar_url is not None else user.avatar_url,
            is_anonymous=user.is_anonymous,
            created_at=user.created_at,
            updated_at=_now(),
            last_login_at=user.last_login_at,
        )
        self.users[user_id] = updated
        return updated

    async def touch_last_login(
        self, user_id: str, min_interval_seconds: float = 0.0
    ) -> UserData | None:
        user = self.users.get(user_id)
        if user is None:
            return None
        refreshed = UserData(
            id=user.id,
            username=user.username,
            display_name=user.display_name,
            name_color=user.name_color,
            avatar_url=user.avatar_url,
            is_anonymous=user.is_anonymous,
            created_at=user.created_at,
            updated_at=user.updated_at,
            last_login_at=_now(),
        )
        self.users[user_id] = refreshed
        return refreshed

    async def get_stats(self, user_id: str) -> UserStats:
        return UserStats(user_id=user_id)
