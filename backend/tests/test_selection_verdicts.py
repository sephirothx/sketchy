"""Authorizing a selection is remembered, and a cold one does not hold the loop (#1237).

`authorize_selection` runs at room creation, at every change of a room's lists
and before every game, and it folded every answer and alias of every selected
list each time, on the event loop - 3.3 s for twenty agnostic lists in a mixed
room, repeatable by toggling the selection. A revision never changes, so the
verdict is remembered under the moderation fingerprint of its members, and a
miss is folded off the loop.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest
from sqlalchemy import event, update

from app.db.models import PromptVersion, User, generate_uuid
from app.domain_values import MIXED_PROMPT_LANGUAGE
from app.repositories import sqlalchemy as repository_module
from app.repositories.interfaces import (
    PromptListEntryInput,
    PromptListMutationError,
    PromptListSelectionError,
)
from app.repositories.sqlalchemy import SqlAlchemyPromptListRepository

from tests.dbfixtures import create_test_db


@pytest.fixture
async def seeded():
    factory, engine = await create_test_db()
    owner = generate_uuid()
    async with factory() as session, session.begin():
        session.add(User(
            id=owner, username="host", password_hash="hash", display_name="Host",
            is_anonymous=False, state="registered",
        ))
    repo = SqlAlchemyPromptListRepository(factory)
    try:
        yield repo, engine, factory, str(owner)
    finally:
        await engine.dispose()


def entries(*answers: str, aliases: dict[str, tuple[str, ...]] | None = None):
    aliases = aliases or {}
    return [PromptListEntryInput(answer=answer, aliases=aliases.get(answer, ())) for answer in answers]


class Folds:
    """How many cold folds ran, and whether each ran off the loop."""

    def __init__(self, monkeypatch) -> None:
        self.cold = 0
        self.off_loop = 0
        original = repository_module._off_loop

        async def counting(function, *args):
            self.off_loop += 1
            return await original(function, *args)

        monkeypatch.setattr(repository_module, "_off_loop", counting)


def statements(engine):
    issued = []

    def count(*_args, **_kwargs):
        issued.append(1)

    event.listen(engine.sync_engine, "before_cursor_execute", count)
    return issued, lambda: event.remove(engine.sync_engine, "before_cursor_execute", count)


async def test_an_unchanged_selection_is_not_folded_again(seeded, monkeypatch):
    repo, engine, factory, owner = seeded
    lists = [
        await repo.create_owned(owner, name=f"L{index}", description="", language="en",
                                prompts=entries(f"cat{index}", f"dog{index}", f"eel{index}"))
        for index in range(3)
    ]
    slugs = [created.slug for created in lists]
    folds = Folds(monkeypatch)

    first = await repo.authorize_selection(slugs, requesting_user_id=owner, expected_language="en")
    issued, stop = statements(engine)
    try:
        second = await repo.authorize_selection(slugs, requesting_user_id=owner, expected_language="en")
    finally:
        stop()
    # Toggled back to the same lists in another order: the same selection.
    third = await repo.authorize_selection(list(reversed(slugs)), requesting_user_id=owner, expected_language="en")

    assert folds.off_loop == 1, "folded once, off the loop, and never again"
    assert first.prompt_count == second.prompt_count == third.prompt_count == 9
    assert len(issued) <= 3, "the lists, their revisions and one fingerprint"


async def test_a_prompt_hidden_between_two_authorizations_is_excluded(seeded, monkeypatch):
    repo, engine, factory, owner = seeded
    created = await repo.create_owned(owner, name="L", description="", language="en",
                                      prompts=entries("cat", "dog", "eel"))
    before = await repo.authorize_selection([created.slug], requesting_user_id=owner, expected_language="en")
    hidden = UUID(created.prompts[0].prompt_version_id)
    async with factory() as session, session.begin():
        await session.execute(
            update(PromptVersion)
            .where(PromptVersion.id == hidden)
            .values(moderation_state="hidden", moderated_at=datetime.now(timezone.utc))
        )
    after = await repo.authorize_selection([created.slug], requesting_user_id=owner, expected_language="en")

    assert (before.prompt_count, after.prompt_count) == (3, 2)


async def test_a_restored_prompt_counts_again(seeded):
    repo, engine, factory, owner = seeded
    created = await repo.create_owned(owner, name="L", description="", language="en",
                                      prompts=entries("cat", "dog"))
    version = UUID(created.prompts[0].prompt_version_id)
    for state, expected in (("hidden", 1), ("active", 2)):
        async with factory() as session, session.begin():
            await session.execute(
                update(PromptVersion).where(PromptVersion.id == version)
                .values(moderation_state=state, moderated_at=datetime.now(timezone.utc))
            )
        selection = await repo.authorize_selection([created.slug], requesting_user_id=owner, expected_language="en")
        assert selection.prompt_count == expected


async def test_an_ambiguous_selection_stays_refused_when_remembered(seeded, monkeypatch):
    repo, engine, factory, owner = seeded
    one = await repo.create_owned(owner, name="One", description="", language="en",
                                  prompts=entries("cat", aliases={"cat": ("kitty",)}))
    two = await repo.create_owned(owner, name="Two", description="", language="en",
                                  prompts=entries("kitty"))
    folds = Folds(monkeypatch)
    for _ in range(2):
        with pytest.raises(PromptListSelectionError, match="ambiguous"):
            await repo.authorize_selection([one.slug, two.slug], requesting_user_id=owner, expected_language="en")
    assert folds.off_loop == 1


async def test_a_mixed_room_s_verdict_is_remembered_and_still_refuses_a_clash(seeded, monkeypatch):
    repo, engine, factory, owner = seeded
    # "Mueller" and "Müller" are one answer to a German room; each list alone
    # is fine, and the two together are not.
    umlaut = await repo.create_owned(owner, name="Umlaut", description="", language="zxx",
                                     prompts=entries("Müller"))
    spelled = await repo.create_owned(owner, name="Spelled", description="", language="zxx",
                                      prompts=entries("Mueller"))
    fine = await repo.create_owned(owner, name="Fine", description="", language="zxx",
                                   prompts=entries("tree", "rock"))
    folds = Folds(monkeypatch)
    for _ in range(2):
        with pytest.raises(PromptListSelectionError, match="ambiguous"):
            await repo.authorize_selection(
                [umlaut.slug, spelled.slug], requesting_user_id=owner,
                expected_language=MIXED_PROMPT_LANGUAGE,
            )
        selection = await repo.authorize_selection([fine.slug], requesting_user_id=owner, expected_language=MIXED_PROMPT_LANGUAGE)
        assert selection.prompt_count == 2
    assert folds.off_loop == 2, "one fold per selection, then remembered"


async def test_what_is_remembered_is_bounded(seeded, monkeypatch):
    repo, engine, factory, owner = seeded
    monkeypatch.setattr(repository_module, "MAX_REMEMBERED_VERDICTS", 2)
    lists = [
        await repo.create_owned(owner, name=f"L{index}", description="", language="en", prompts=entries(f"w{index}"))
        for index in range(4)
    ]
    for created in lists:
        await repo.authorize_selection([created.slug], requesting_user_id=owner, expected_language="en")
    assert len(repo._verdicts) == 2


async def test_answers_one_guess_can_win_are_refused_everywhere_they_meet(seeded):
    """German "Spüle" (sink) and "Spule" (spool) are two keys, and "Spule"
    wins both: a dropped umlaut is accepted (R-GUESS-01). One list holding both
    is refused at its save, and two lists holding one each are refused when a
    room selects them, at the door and again at the draw (#1396)."""
    repo, _engine, _factory, owner = seeded
    with pytest.raises(PromptListMutationError, match="unambiguous"):
        await repo.create_owned(owner, name="Both", description="", language="de",
                                prompts=entries("Spüle", "Spule"))
    sink = await repo.create_owned(owner, name="Sink", description="", language="de",
                                   prompts=entries("Spüle"))
    spool = await repo.create_owned(owner, name="Spool", description="", language="de",
                                    prompts=entries("Spule"))
    slugs = [sink.slug, spool.slug]
    with pytest.raises(PromptListSelectionError, match="ambiguous"):
        await repo.authorize_selection(slugs, requesting_user_id=owner, expected_language="de")
    with pytest.raises(PromptListSelectionError, match="ambiguous"):
        await repo.resolve_selection(slugs, requesting_user_id=owner, expected_language="de")
    # A mixed room plays lists in no language under every seat's fold, the
    # German one included.
    agnostic = [
        (await repo.create_owned(owner, name=name, description="", language="zxx",
                                 prompts=entries(answer))).slug
        for name, answer in (("Sink zxx", "Spüle"), ("Spool zxx", "Spule"))
    ]
    with pytest.raises(PromptListSelectionError, match="ambiguous"):
        await repo.authorize_selection(
            agnostic, requesting_user_id=owner, expected_language=MIXED_PROMPT_LANGUAGE
        )
    # Without a transliteration the same letters are two words.
    english = [
        (await repo.create_owned(owner, name=name, description="", language="en",
                                 prompts=entries(answer))).slug
        for name, answer in (("Sink en", "spuele"), ("Spool en", "spule"))
    ]
    selection = await repo.authorize_selection(english, requesting_user_id=owner, expected_language="en")
    assert selection.prompt_count == 2


async def test_an_ampersand_is_each_room_language_s_own_and(seeded):
    """A Spanish guess "rock y roll" wins both "rock & roll" and "rock y roll",
    so a list in no language holding both is refused at its save, and two
    lists holding one each are refused in a mixed room (review of #1406)."""
    repo, _engine, _factory, owner = seeded
    with pytest.raises(PromptListMutationError, match="unambiguous"):
        await repo.create_owned(owner, name="Both", description="", language="zxx",
                                prompts=entries("rock & roll", "rock y roll"))
    lists = [
        (await repo.create_owned(owner, name=name, description="", language="zxx",
                                 prompts=entries(answer))).slug
        for name, answer in (("Sign", "rock & roll"), ("Word", "rock y roll"))
    ]
    with pytest.raises(PromptListSelectionError, match="ambiguous"):
        await repo.authorize_selection(lists, requesting_user_id=owner, expected_language=MIXED_PROMPT_LANGUAGE)
