"""Guest nickname availability checks shared by REST and socket join."""
from __future__ import annotations

from typing import Protocol

from app.repositories.interfaces import UserData


class UsernameLookup(Protocol):
    async def get_by_username(self, username: str) -> UserData | None: ...


def registered_nickname_taken_message(nickname: str) -> str:
    return f"The nickname '{nickname}' is already taken by a registered account"


async def guest_nickname_is_available(
    user_repo: UsernameLookup,
    nickname: str,
    current_user_id: str,
) -> bool:
    clean = nickname.strip()
    if not clean:
        return False
    existing = await user_repo.get_by_username(clean)
    if existing is None or existing.is_anonymous:
        return True
    return existing.id == current_user_id
