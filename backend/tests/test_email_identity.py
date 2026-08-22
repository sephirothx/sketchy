"""Email normalization, uniqueness, and verification invariants."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth.email import EmailAddressError, normalize_email
from app.db.models import Base, User, generate_uuid
from app.domain_values import AccountState


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("  ", None),
        (" Player@Example.COM ", "player@example.com"),
        ("first.last+tag@example.com", "first.last+tag@example.com"),
    ],
)
def test_email_normalization_is_provider_agnostic(raw, expected):
    assert normalize_email(raw) == expected


@pytest.mark.parametrize("raw", ["missing-at.example", "a@localhost", "a b@example.com"])
def test_invalid_email_is_rejected(raw):
    with pytest.raises(EmailAddressError):
        normalize_email(raw)


@pytest.mark.asyncio
async def test_database_requires_normalized_unique_email_and_verification_source():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            async with session.begin():
                session.add(
                    User(
                        id=generate_uuid(),
                        display_name="One",
                        state=AccountState.REGISTERED.value,
                        email="one@example.com",
                    )
                )

        for values in (
            {"email": "ONE@example.com"},
            {
                "email": None,
                "email_verified_at": datetime.now(timezone.utc),
            },
        ):
            with pytest.raises(IntegrityError):
                async with factory() as session:
                    async with session.begin():
                        session.add(
                            User(
                                id=generate_uuid(),
                                display_name="Two",
                                state=AccountState.REGISTERED.value,
                                **values,
                            )
                        )
    finally:
        await engine.dispose()
