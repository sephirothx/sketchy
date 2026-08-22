"""Persistent player prompt lists: immutable revisions and access boundaries."""
from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base, PromptListRevision, PromptVersion, User, generate_uuid
from app.repositories.interfaces import (
    PromptListConflictError,
    PromptListEntryInput,
    PromptListSelectionError,
)
from app.repositories.sqlalchemy import SqlAlchemyPromptListRepository

pytestmark = pytest.mark.asyncio


async def _database():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    owner_id = generate_uuid()
    other_id = generate_uuid()
    async with factory() as session:
        async with session.begin():
            session.add_all(
                [
                    User(
                        id=owner_id,
                        username="owner",
                        display_name="Owner",
                        is_anonymous=False,
                        state="registered",
                    ),
                    User(
                        id=other_id,
                        username="other",
                        display_name="Other",
                        is_anonymous=False,
                        state="registered",
                    ),
                ]
            )
    return factory, engine, str(owner_id), str(other_id)


async def test_owned_lists_are_uuidv7_revisioned_and_private_by_default():
    factory, engine, owner_id, other_id = await _database()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        created = await repo.create_owned(
            owner_id,
            name="Party animals",
            description="Our recurring list",
            language="en",
            visibility="private",
            prompts=(
                PromptListEntryInput(answer="red panda"),
                PromptListEntryInput(answer="otter"),
            ),
        )

        assert UUID(created.id).version == 7
        assert created.version == 1
        assert created.visibility == "private"
        assert created.share_code is None
        assert [entry.answer for entry in created.prompts] == ["red panda", "otter"]
        assert all(UUID(entry.concept_id).version == 7 for entry in created.prompts)
        assert await repo.list_all() == []  # never leaks into the public catalogue
        assert await repo.get_owned(other_id, created.id) is None
        with pytest.raises(PromptListSelectionError, match="not found"):
            await repo.resolve_selection([created.slug])

        selection = await repo.resolve_selection(
            [created.slug], requesting_user_id=owner_id
        )
        assert selection.prompts == ("red panda", "otter")
        assert len(selection.revision_ids) == 1

        panda = created.prompts[0]
        updated = await repo.update_owned(
            owner_id,
            created.id,
            expected_version=1,
            name="Party animals",
            description="Revised",
            visibility="unlisted",
            prompts=(
                PromptListEntryInput(
                    concept_id=panda.concept_id,
                    answer="giant panda",
                    aliases=("panda",),
                ),
                PromptListEntryInput(answer="capybara"),
            ),
        )
        assert updated.version == 2
        assert updated.share_code and len(updated.share_code) >= 8
        assert updated.prompts[0].concept_id == panda.concept_id
        assert updated.prompts[0].prompt_version_id != panda.prompt_version_id
        assert updated.prompts[0].aliases == ("panda",)

        async with factory() as session:
            revisions = (
                await session.scalars(
                    select(PromptListRevision).where(
                        PromptListRevision.prompt_list_id == UUID(created.id)
                    )
                )
            ).all()
            panda_versions = (
                await session.scalars(
                    select(PromptVersion).where(
                        PromptVersion.concept_id == UUID(panda.concept_id)
                    )
                )
            ).all()
        assert {revision.version for revision in revisions} == {1, 2}
        assert {version.canonical_answer for version in panda_versions} == {
            "red panda",
            "giant panda",
        }

        with pytest.raises(PromptListConflictError, match="Reload"):
            await repo.update_owned(
                owner_id,
                created.id,
                expected_version=1,
                name="Stale",
                description="",
                visibility="private",
                prompts=(PromptListEntryInput(answer="apple"),),
            )

        shared = await repo.get_shared(updated.share_code)
        assert shared is not None and shared.slug == created.slug
        with pytest.raises(PromptListSelectionError):
            await repo.resolve_selection([created.slug])
        shared_selection = await repo.resolve_selection(
            [created.slug], share_codes=(updated.share_code,)
        )
        assert shared_selection.prompts == ("giant panda", "capybara")
    finally:
        await engine.dispose()


async def test_only_the_owner_can_delete_a_player_list():
    factory, engine, owner_id, other_id = await _database()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        created = await repo.create_owned(
            owner_id,
            name="Mine",
            description="",
            language="en",
            visibility="private",
            prompts=(PromptListEntryInput(answer="apple"),),
        )
        assert await repo.delete_owned(other_id, created.id) is False
        assert await repo.get_owned(owner_id, created.id) is not None
        assert await repo.delete_owned(owner_id, created.id) is True
        assert await repo.get_owned(owner_id, created.id) is None
    finally:
        await engine.dispose()
