"""Prompt lists in no language at all (#821).

A list of Pokémon or brands is not in a language, so it declares `zxx` and is
played in any room, under the fold of whatever language that room declares.
What a room declares is unchanged: one of the seven, and every list with a
language has to be in it (R-PROMPT-02).
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.errors import install_refusal_handler
from app.api.prompt_lists import community_limiter, create_prompt_list_router
from app.auth.middleware import SessionAuthMiddleware
from app.auth.sessions import COOKIE_NAME, create_session
from app.db.models import PromptList, generate_uuid
from app.game import _accepted_spellings
from app.prompt_content import (
    prompt_match_key,
    prompt_match_variants,
    validate_prompt_language,
    validate_prompt_list_language,
)
from app.repositories.interfaces import (
    BundledPromptDefinition,
    PromptListEntryInput,
    PromptListMutationError,
    PromptListSelectionError,
)
from app.repositories.sqlalchemy import (
    SqlAlchemyPromptListRepository,
    SqlAlchemyUserRepository,
)

from tests.dbfixtures import create_test_db


def test_zxx_is_a_list_language_and_never_a_room_one():
    assert validate_prompt_list_language("zxx") == "zxx"
    assert validate_prompt_list_language(" ZXX ") == "zxx"
    assert validate_prompt_list_language("de") == "de"
    with pytest.raises(ValueError):
        validate_prompt_language("zxx")
    with pytest.raises(ValueError):
        validate_prompt_list_language("ja")


def test_an_agnostic_key_does_not_depend_on_a_room():
    """The stored key is an identity, so it folds with the shared rule only."""
    assert prompt_match_key("Pokémon", "zxx") == "pokemon"
    assert prompt_match_key("Müller", "zxx") == "muller"
    # The German room's own transliteration still reaches the answer at guess
    # time, because acceptance folds the answer's text, not its stored key.
    assert "mueller" in prompt_match_variants("Müller", "de")
    assert not _accepted_spellings("Mueller", "de").isdisjoint(
        _accepted_spellings("Müller", "de")
    )
    assert not _accepted_spellings("pokemon", "de").isdisjoint(
        _accepted_spellings("Pokémon", "de")
    )


@pytest_asyncio.fixture
async def env():
    factory, engine = await create_test_db()
    users = SqlAlchemyUserRepository(factory)
    prompts = SqlAlchemyPromptListRepository(factory)
    await prompts.seed_list_tags()
    app = FastAPI()
    install_refusal_handler(app)
    app.add_middleware(SessionAuthMiddleware, session_factory=factory)
    app.include_router(create_prompt_list_router(prompts, users, factory))
    community_limiter.reset()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as http:
        yield http, users, prompts, factory
    await engine.dispose()


async def _owner(users, name: str = "Owner"):
    guest = await users.create_anonymous(name)
    return await users.claim_account(guest.id, name, "test-hash")


async def _publish(factory, list_id: str) -> None:
    async with factory() as session:
        async with session.begin():
            row = await session.get(PromptList, UUID(list_id))
            row.visibility = "public"
            row.published_at = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


async def _list(prompts, owner_id: str, name: str, language: str, *answers: str):
    return await prompts.create_owned(
        owner_id,
        name=name,
        description="",
        language=language,
        prompts=tuple(PromptListEntryInput(answer=answer) for answer in answers),
    )


async def _bundled(prompts, slug: str, language: str, *answers: str):
    return await prompts.upsert_bundled(
        slug=slug,
        name=slug,
        description="",
        language=language,
        prompts=[BundledPromptDefinition(str(generate_uuid()), a) for a in answers],
        version=1,
    )


async def test_an_agnostic_list_is_selected_beside_the_room_s_own_language(env):
    _, users, prompts, _ = env
    owner = await _owner(users)
    await _bundled(prompts, "german_standard", "de", "Hund", "Katze")
    await _bundled(prompts, "english_standard", "en", "dog", "cat")
    pokemon = await _list(prompts, owner.id, "Pokémon", "zxx", "Pikachu", "Pokémon")
    slug = pokemon.slug

    pinned = await prompts.authorize_selection(
        ["german_standard", slug], requesting_user_id=owner.id, expected_language="de"
    )
    assert pinned.language == "de"
    assert pinned.prompt_count == 4

    resolved = await prompts.resolve_selection(
        [slug], requesting_user_id=owner.id, expected_language="fr"
    )
    assert resolved.language == "fr"
    assert set(resolved.prompts) == {"Pikachu", "Pokémon"}

    # An agnostic list does not make two languages agree with each other.
    with pytest.raises(PromptListSelectionError, match="same language"):
        await prompts.authorize_selection(
            ["german_standard", "english_standard", slug],
            requesting_user_id=owner.id,
        )
    with pytest.raises(PromptListSelectionError, match="room's language"):
        await prompts.authorize_selection(
            ["english_standard", slug],
            requesting_user_id=owner.id,
            expected_language="de",
        )


async def test_an_agnostic_selection_with_no_room_stays_agnostic(env):
    _, users, prompts, _ = env
    owner = await _owner(users)
    pokemon = await _list(prompts, owner.id, "Pokémon", "zxx", "Pikachu")

    pinned = await prompts.authorize_selection(
        [pokemon.slug], requesting_user_id=owner.id
    )

    assert pinned.language == "zxx"


async def test_an_agnostic_list_collides_with_the_room_s_list_under_the_room_s_fold(env):
    """`Mädchen` in a German list and `Maedchen` in an agnostic one are one
    answer to a German room, so the room refuses to draw from both."""
    _, users, prompts, _ = env
    owner = await _owner(users)
    await _bundled(prompts, "german_standard", "de", "Mädchen")
    names = await _list(prompts, owner.id, "Names", "zxx", "Maedchen")

    with pytest.raises(PromptListSelectionError, match="ambiguous"):
        await prompts.authorize_selection(
            ["german_standard", names.slug],
            requesting_user_id=owner.id,
            expected_language="de",
        )
    # An English room folds them apart, so it takes both.
    await _bundled(prompts, "english_standard", "en", "girl")
    pinned = await prompts.authorize_selection(
        [names.slug], requesting_user_id=owner.id, expected_language="en"
    )
    assert pinned.prompt_count == 1


async def test_an_agnostic_list_must_be_unambiguous_in_every_room_language(env):
    """Two keys to the list, one to a German room: refused when saved rather
    than at the door of every German room it is picked in."""
    _, users, prompts, _ = env
    owner = await _owner(users)

    with pytest.raises(PromptListMutationError, match="unambiguous"):
        await _list(prompts, owner.id, "Surnames", "zxx", "Müller", "Mueller")

    # A list in English folds them apart and keeps both.
    english = await _list(prompts, owner.id, "Surnames", "en", "Müller", "Mueller")
    assert english.language == "en"


async def test_the_catalogue_shows_agnostic_lists_under_every_language(env):
    http, users, prompts, factory = env
    owner = await _owner(users)
    for name, language in (
        ("English", "en"),
        ("Deutsch", "de"),
        ("Pokémon", "zxx"),
    ):
        created = await _list(prompts, owner.id, name, language, f"{name} one")
        await _publish(factory, created.id)

    async def names(query: str) -> set[str]:
        response = await http.get(f"/api/prompt-lists/community{query}")
        assert response.status_code == 200, response.text
        return {row["name"] for row in response.json()["lists"]}

    assert await names("?language=de") == {"Deutsch", "Pokémon"}
    assert await names("?language=en") == {"English", "Pokémon"}
    assert await names("?language=zxx") == {"Pokémon"}
    assert await names("") == {"English", "Deutsch", "Pokémon"}
    rows = (await http.get("/api/prompt-lists/community?language=zxx")).json()["lists"]
    assert rows[0]["language"] == "zxx"


async def test_a_list_is_created_agnostic_through_the_api(env):
    http, users, _, factory = env
    owner = await _owner(users)
    issued = await create_session(factory, user_id=owner.id, device_label="Test")
    http.cookies.set(COOKIE_NAME, issued.token)

    response = await http.post(
        "/api/prompt-lists/mine",
        json={
            "name": "Pokémon",
            "language": "zxx",
            "prompts": [{"prompt": "Pikachu"}, {"prompt": "Bulbasaur"}],
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["language"] == "zxx"


async def test_the_official_catalogue_filter_offers_agnostic_lists_too(env):
    """Nothing bundled is agnostic today; the filter still answers the
    question a room asks - what could I pick? - the same way as the
    community one."""
    http, _, prompts, _ = env
    await _bundled(prompts, "german_standard", "de", "Hund")
    await _bundled(prompts, "english_standard", "en", "dog")
    await _bundled(prompts, "flags", "zxx", "Brasil")

    response = await http.get("/api/prompt-lists?language=de")

    assert response.status_code == 200, response.text
    assert {row["slug"] for row in response.json()} == {"german_standard", "flags"}


async def test_a_copy_or_duplicate_of_an_agnostic_list_stays_agnostic(env):
    _, users, prompts, factory = env
    owner = await _owner(users, "Author")
    reader = await _owner(users, "Reader")
    await _bundled(prompts, "german_standard", "de", "Hund")
    original = await _list(prompts, owner.id, "Pokémon", "zxx", "Pikachu", "Evoli")
    await _publish(factory, original.id)

    copy = await prompts.fork_published(reader.id, original.id)
    duplicate = await prompts.duplicate_owned(owner.id, original.id, name="Pokémon 2")

    assert copy.language == "zxx"
    assert duplicate.language == "zxx"
    pinned = await prompts.authorize_selection(
        ["german_standard", copy.slug], requesting_user_id=reader.id, expected_language="de"
    )
    assert pinned.language == "de"


async def test_resolving_refuses_an_agnostic_twin_under_the_room_s_fold(env):
    """The same collision `authorize_selection` refuses, on the path that
    loads the prompts."""
    _, users, prompts, _ = env
    owner = await _owner(users)
    await _bundled(prompts, "german_standard", "de", "Mädchen")
    names = await _list(prompts, owner.id, "Names", "zxx", "Maedchen")

    with pytest.raises(PromptListSelectionError, match="ambiguous"):
        await prompts.resolve_selection(
            ["german_standard", names.slug],
            requesting_user_id=owner.id,
            expected_language="de",
        )


async def test_the_draw_compares_quick_prompts_only_with_keys_in_the_room_s_fold(env):
    """The stored keys of an agnostic list are in another fold: "Bär" stores
    `bar`, which a German room's quick "Bar" must not exclude."""
    _, users, prompts, _ = env
    owner = await _owner(users)
    await _bundled(prompts, "german_standard", "de", "Bar", "Hund")
    names = await _list(prompts, owner.id, "Names", "zxx", "Bär", "Pikachu")
    pinned = await prompts.authorize_selection(
        ["german_standard", names.slug], requesting_user_id=owner.id, expected_language="de"
    )

    sample = await prompts.sample_prompts(
        list(pinned.revision_ids),
        limit=10,
        exclude_match_keys={prompt_match_key("Bar", "de")},
        exclude_language="de",
    )

    assert {prompt.answer for prompt in sample.prompts} == {"Hund", "Bär", "Pikachu"}
    # Every drawn prompt names its concept, which a game tracks it by (#1181).
    assert all(prompt.concept_id for prompt in sample.prompts)
