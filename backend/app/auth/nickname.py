"""Guest nickname availability checks shared by REST and socket join."""
from __future__ import annotations

import re
from typing import Protocol

from app.repositories.interfaces import UserData

# Keep in sync with MAX_NICKNAME_LENGTH and frontend guestNickname rules.
NICKNAME_REGEX = re.compile(r"^[a-zA-Z0-9_-]{3,16}$")
NICKNAME_RULES_MESSAGE = (
    "Nickname must be 3-16 characters and contain only letters, digits, underscores, or hyphens"
)


class UsernameLookup(Protocol):
    async def get_by_username(self, username: str) -> UserData | None: ...


def is_valid_guest_nickname(nickname: str) -> bool:
    return bool(NICKNAME_REGEX.fullmatch(nickname.strip()))


def registered_nickname_taken_message(nickname: str) -> str:
    return f"The nickname '{nickname}' is already taken by a registered account"


async def guest_nickname_is_available(
    user_repo: UsernameLookup,
    nickname: str,
    current_user_id: str,
) -> bool:
    clean = nickname.strip()
    if not is_valid_guest_nickname(clean):
        return False
    existing = await user_repo.get_by_username(clean)
    if existing is None or existing.is_anonymous:
        return True
    return existing.id == current_user_id
