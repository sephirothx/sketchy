"""Pydantic schemas for authentication requests and responses."""
from __future__ import annotations

import re
from pydantic import BaseModel, ConfigDict, Field, field_validator

USERNAME_REGEX = re.compile(r"^[a-zA-Z0-9_-]{3,32}$")
MIN_PASSWORD_LENGTH = 6
MAX_PASSWORD_LENGTH = 128


class RegisterRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", populate_by_name=True)

    username: str = Field(..., min_length=3, max_length=32)
    password: str = Field(..., min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        trimmed = value.strip()
        if not USERNAME_REGEX.fullmatch(trimmed):
            raise ValueError("Username must be 3-32 characters long and contain only letters, digits, underscores, or hyphens")
        return trimmed


class LoginRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", populate_by_name=True)

    username: str = Field(..., min_length=1, max_length=32)
    password: str = Field(..., min_length=1, max_length=MAX_PASSWORD_LENGTH)

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        return value.strip()


class UserResponse(BaseModel):
    id: str
    username: str | None
    display_name: str = Field(alias="displayName")
    name_color: str | None = Field(default=None, alias="nameColor")
    avatar_url: str | None = Field(default=None, alias="avatarUrl")
    is_anonymous: bool = Field(alias="isAnonymous")
    created_at: str = Field(alias="createdAt")
    stats: dict | None = None
