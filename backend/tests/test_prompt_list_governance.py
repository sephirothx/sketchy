"""Prompt-list governance schema for player-owned lists."""
from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models import (
    PromptList,
    PromptListTag,
    PromptTag,
    User,
    generate_uuid,
)

from tests.dbfixtures import create_test_db


async def _database():
    return await create_test_db()


async def test_user_list_defaults_are_private_owned_and_actively_moderated():
    factory, engine = await _database()
    try:
        owner_id = generate_uuid()
        async with factory() as session:
            async with session.begin():
                session.add(User(id=owner_id, display_name="Owner"))
                await session.flush()
                prompt_list = PromptList(
                    slug="owners-list",
                    name="Owner's list",
                    owner_user_id=owner_id,
                    is_bundled=False,
                )
                session.add(prompt_list)
            await session.refresh(prompt_list)
            assert prompt_list.visibility == "private"
            assert prompt_list.moderation_state == "active"
            assert prompt_list.created_at is not None
            assert prompt_list.updated_at is not None

        async with factory() as session:
            with pytest.raises(IntegrityError):
                async with session.begin():
                    session.add(
                        PromptList(
                            # Withdrawn (R-LIST-03): a list is private or
                            # published, and the schema holds to that.
                            slug="unlisted",
                            name="Unlisted",
                            owner_user_id=owner_id,
                            is_bundled=False,
                            visibility="unlisted",
                        )
                    )

        async with factory() as session:
            with pytest.raises(IntegrityError):
                async with session.begin():
                    session.add(
                        PromptList(
                            slug="owned-official",
                            name="Owned official",
                            owner_user_id=owner_id,
                            is_bundled=True,
                            visibility="public",
                        )
                    )
    finally:
        await engine.dispose()


async def test_copy_provenance_and_tags_are_structured():
    factory, engine = await _database()
    try:
        owner_id = generate_uuid()
        async with factory() as session:
            async with session.begin():
                session.add(User(id=owner_id, display_name="Owner"))
                await session.flush()
                source = PromptList(
                    slug="source-list",
                    name="Source",
                    owner_user_id=owner_id,
                    is_bundled=False,
                )
                fork = PromptList(
                    slug="fork-list",
                    name="Fork",
                    owner_user_id=owner_id,
                    is_bundled=False,
                )
                session.add_all([source, fork])
                await session.flush()
                fork.is_copy, fork.copied_from_list_id = True, source.id
                tag = PromptTag(slug="animals", name="Animals")
                session.add(tag)
                await session.flush()
                session.add(PromptListTag(prompt_list_id=fork.id, tag_id=tag.id))

        async with factory() as session:
            stored = await session.get(PromptList, fork.id)
            assert stored is not None
            assert stored.copied_from_list_id == source.id
            assert (
                await session.scalar(select(PromptListTag.tag_id))
            ) == tag.id
    finally:
        await engine.dispose()
