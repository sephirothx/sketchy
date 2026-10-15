"""Solo's pool (#1434): which drawings may be served, and to whom.

One test per exclusion, each written against a drawing that would otherwise
be served, so it fails if its clause goes missing. The pool's rebuild is held
to the finished-game write, and erasure takes rows out.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import select, update

from app.auth.account_data import anonymize_account
from app.db.models import (
    IdentityAlias,
    PromptVersion,
    SoloPoolEntry,
    TurnDrawing,
    UserSettings,
)
from app.repositories.solo import SoloRepository
from app.repositories.sqlalchemy import (
    SqlAlchemyGameHistoryRepository,
    SqlAlchemyUserRepository,
    erase_drawing_for_moderation,
)
from app.services.solo_pool import rebuild_solo_pool
from app.solo_rules import sample_key
from tests.dbfixtures import create_test_db
from tests.solo_fixtures import player, record_turn, seed_concept


@pytest_asyncio.fixture
async def env():
    factory, engine = await create_test_db()
    try:
        yield (
            SqlAlchemyUserRepository(factory),
            SqlAlchemyGameHistoryRepository(factory),
            SoloRepository(factory),
            factory,
        )
    finally:
        await engine.dispose()


async def _pool(factory) -> set[UUID]:
    async with factory() as session:
        return set((await session.scalars(select(SoloPoolEntry.turn_id))).all())


async def _served(solo, user) -> set[str]:
    return {str(turn) for turn in await solo.servable_turn_ids(user.id, limit=100)}


async def _cast(users, factory, history, *, visibility="public", **turn):
    """A drawer, a guesser in the game, a stranger who would be served, and
    one recorded turn of `lighthouse` between the first two."""
    drawer = await player(users, factory, "Drawer")
    guesser = await player(users, factory, "Guesser")
    stranger = await player(users, factory, "Stranger")
    concept = turn.pop("concept", None) or await seed_concept(
        factory, {"en": "lighthouse", "de": "Leuchtturm"}
    )
    recorded = await record_turn(
        history,
        drawer=drawer.id,
        guessers=[guesser.id],
        version_id=turn.pop("version_id", concept.versions["en"]),
        visibility=visibility,
        **turn,
    )
    return drawer, guesser, stranger, concept, recorded


async def test_a_public_guessed_curated_drawing_is_served_to_a_stranger(env):
    users, history, solo, factory = env
    drawer, guesser, stranger, _, recorded = await _cast(users, factory, history)

    async with factory() as session:
        row = await session.get(SoloPoolEntry, UUID(recorded.turn_id))
    assert (row.guesser_count, row.correct_count) == (1, 1)
    assert row.sample_key == sample_key(recorded.turn_id)
    assert await _served(solo, stranger) == {recorded.turn_id}
    # Nobody who sat in the game is served it: they know the answer.
    assert await _served(solo, drawer) == set()
    assert await _served(solo, guesser) == set()


@pytest.mark.parametrize(
    "turn, why",
    [
        ({"visibility": "private"}, "a private room's drawings are seen by nobody who was not there"),
        ({"version_id": None}, "a custom prompt has no concept and no moderation"),
        ({"correct": 0}, "nobody in the game named it"),
        ({"stroke_count": 4}, "under five actions is not a drawing to name"),
        ({"drawing": False}, "no drawing was kept"),
    ],
)
async def test_what_the_game_decided_keeps_a_turn_out_of_the_pool(env, turn, why):
    users, history, solo, factory = env
    *_, stranger, _, recorded = await _cast(users, factory, history, **turn)
    assert UUID(recorded.turn_id) not in await _pool(factory), why
    assert await _served(solo, stranger) == set(), why


async def test_an_abandoned_public_game_s_finished_turn_is_in_the_pool(env):
    users, history, solo, factory = env
    *_, stranger, _, recorded = await _cast(users, factory, history, outcome="abandoned")
    assert await _served(solo, stranger) == {recorded.turn_id}


async def test_the_pool_bar_is_five_strokes(env):
    users, history, solo, factory = env
    *_, stranger, _, recorded = await _cast(users, factory, history, stroke_count=5)
    assert await _served(solo, stranger) == {recorded.turn_id}


async def _set_drawing(factory, turn_id: str, **values) -> None:
    async with factory() as session:
        async with session.begin():
            await session.execute(
                update(TurnDrawing).where(TurnDrawing.turn_id == UUID(turn_id)).values(**values)
            )


NOW = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)


async def test_a_moderator_s_hide_takes_it_out_and_lifting_it_brings_it_back(env):
    users, history, solo, factory = env
    *_, stranger, _, recorded = await _cast(users, factory, history)
    await _set_drawing(factory, recorded.turn_id, gallery_hidden_at=NOW)
    assert await _served(solo, stranger) == set()
    await _set_drawing(factory, recorded.turn_id, gallery_hidden_at=None)
    assert await _served(solo, stranger) == {recorded.turn_id}


async def test_the_drawer_taking_one_drawing_out_takes_only_that_one(env):
    users, history, solo, factory = env
    drawer, guesser, stranger, concept, recorded = await _cast(users, factory, history)
    other = await record_turn(
        history, drawer=drawer.id, guessers=[guesser.id], version_id=concept.versions["en"]
    )
    await _set_drawing(factory, recorded.turn_id, solo_withdrawn_at=NOW)
    assert await _served(solo, stranger) == {other.turn_id}


async def test_the_drawer_s_opt_out_takes_every_drawing_out(env):
    users, history, solo, factory = env
    drawer, _, stranger, _, recorded = await _cast(users, factory, history)
    async with factory() as session:
        async with session.begin():
            row = await session.get(UserSettings, UUID(drawer.id))
            row.solo_opt_out = True
    assert await _served(solo, stranger) == set()


async def test_an_opt_out_on_the_account_a_guest_drawer_merged_into_holds(env):
    users, history, solo, factory = env
    guest = await users.create_anonymous(display_name="Visitor")
    owner = await player(users, factory, "Owner")
    guesser = await player(users, factory, "Guesser")
    stranger = await player(users, factory, "Stranger")
    concept = await seed_concept(factory, {"en": "lighthouse"})
    recorded = await record_turn(
        history, drawer=guest.id, guessers=[guesser.id], version_id=concept.versions["en"]
    )
    # A guest's drawing is served: anonymity and reports are its consent.
    assert await _served(solo, stranger) == {recorded.turn_id}
    async with factory() as session:
        async with session.begin():
            session.add(
                IdentityAlias(source_user_id=UUID(guest.id), target_user_id=UUID(owner.id))
            )
            (await session.get(UserSettings, UUID(owner.id))).solo_opt_out = True
    assert await _served(solo, stranger) == set()


async def test_a_game_the_player_sat_in_under_another_identity_is_not_served(env):
    users, history, solo, factory = env
    drawer = await player(users, factory, "Drawer")
    guest = await users.create_anonymous(display_name="Visitor")
    stranger = await player(users, factory, "Stranger")
    concept = await seed_concept(factory, {"en": "lighthouse"})
    recorded = await record_turn(
        history, drawer=drawer.id, guessers=[guest.id], version_id=concept.versions["en"]
    )
    assert await _served(solo, stranger) == {recorded.turn_id}
    async with factory() as session:
        async with session.begin():
            session.add(
                IdentityAlias(source_user_id=UUID(guest.id), target_user_id=UUID(stranger.id))
            )
    assert await _served(solo, stranger) == set()


@pytest.mark.parametrize(
    "values",
    [{"moderation_state": "hidden"}, {"content_rating": "teen"}, {"content_rating": "mature"}],
)
async def test_the_drawn_version_taken_down_or_rated_up_takes_it_out(env, values):
    users, history, solo, factory = env
    *_, concept, recorded = await _cast(users, factory, history)
    # Plays German too, whose version stays playable: only the version the
    # drawer drew is touched, and that alone has to take the drawing out.
    stranger = await player(users, factory, "Bilingual", languages=("en", "de"))
    assert await _served(solo, stranger) == {recorded.turn_id}
    async with factory() as session:
        async with session.begin():
            await session.execute(
                update(PromptVersion)
                .where(PromptVersion.id == concept.versions["en"])
                .values(**values)
            )
    assert await _served(solo, stranger) == set()


async def test_a_player_is_served_only_concepts_in_their_languages(env):
    users, history, solo, factory = env
    drawer = await player(users, factory, "Drawer")
    guesser = await player(users, factory, "Guesser")
    concept = await seed_concept(factory, {"de": "Leuchtturm", "fr": "phare"})
    recorded = await record_turn(
        history, drawer=drawer.id, guessers=[guesser.id], version_id=concept.versions["de"]
    )
    english = await player(users, factory, "English", languages=("en",))
    german_second = await player(users, factory, "Bilingual", languages=("en", "de"))
    french = await player(users, factory, "French", languages=("fr",))
    assert await _served(solo, english) == set()
    assert await _served(solo, german_second) == {recorded.turn_id}
    # Drawn in German, guessed in French: the concept is what is played.
    assert await _served(solo, french) == {recorded.turn_id}


async def test_only_a_playable_version_in_the_player_s_language_counts(env):
    users, history, solo, factory = env
    drawer = await player(users, factory, "Drawer")
    guesser = await player(users, factory, "Guesser")
    concept = await seed_concept(factory, {"de": "Leuchtturm"})
    rated = await seed_concept(factory, {"fr": "phare"}, rating="teen")
    async with factory() as session:
        async with session.begin():
            await session.execute(
                update(PromptVersion)
                .where(PromptVersion.id == rated.versions["fr"])
                .values(concept_id=concept.id)
            )
    await record_turn(
        history, drawer=drawer.id, guessers=[guesser.id], version_id=concept.versions["de"]
    )
    french = await player(users, factory, "French", languages=("fr",))
    assert await _served(solo, french) == set()


async def test_an_agnostic_concept_is_played_in_every_language(env):
    users, history, solo, factory = env
    drawer = await player(users, factory, "Drawer")
    guesser = await player(users, factory, "Guesser")
    concept = await seed_concept(factory, {"zxx": "Pikachu"})
    recorded = await record_turn(
        history, drawer=drawer.id, guessers=[guesser.id], version_id=concept.versions["zxx"]
    )
    polish = await player(users, factory, "Polish", languages=("pl",))
    assert await _served(solo, polish) == {recorded.turn_id}


async def test_a_guest_is_served_nothing(env):
    users, history, solo, factory = env
    *_, recorded = await _cast(users, factory, history)
    guest = await users.create_anonymous(display_name="Visitor")
    assert await solo.servable_turn_ids(guest.id) == []


async def test_erasing_a_drawing_for_moderation_takes_its_row_out(env):
    users, history, solo, factory = env
    *_, stranger, _, recorded = await _cast(users, factory, history)
    async with factory() as session:
        async with session.begin():
            await erase_drawing_for_moderation(
                session, UUID(recorded.turn_id), erased_by_user_id=None, now=NOW
            )
    assert await _pool(factory) == set()
    assert await _served(solo, stranger) == set()


async def test_deleting_the_drawer_s_account_takes_their_rows_out(env):
    users, history, solo, factory = env
    drawer, guesser, stranger, concept, recorded = await _cast(users, factory, history)
    kept = await record_turn(
        history, drawer=guesser.id, guessers=[drawer.id], version_id=concept.versions["en"]
    )
    await anonymize_account(factory, user_id=drawer.id)
    assert await _pool(factory) == {UUID(kept.turn_id)}
    assert await _served(solo, stranger) == {kept.turn_id}


async def test_the_rebuild_reproduces_what_the_writes_did(env):
    users, history, solo, factory = env
    drawer, guesser, stranger, concept, recorded = await _cast(users, factory, history)
    await record_turn(
        history, drawer=drawer.id, guessers=[guesser.id], version_id=concept.versions["en"],
        visibility="private",
    )
    second = await record_turn(
        history, drawer=guesser.id, guessers=[drawer.id, stranger.id],
        version_id=concept.versions["de"], correct=1,
    )

    async def rows():
        async with factory() as session:
            return {
                (r.turn_id, r.game_id, r.concept_id, r.prompt_version_id, r.drawer_user_id,
                 r.guesser_count, r.correct_count, r.sample_key)
                for r in (await session.scalars(select(SoloPoolEntry))).all()
            }

    written = await rows()
    assert {row[0] for row in written} == {UUID(recorded.turn_id), UUID(second.turn_id)}
    second_row = next(row for row in written if row[0] == UUID(second.turn_id))
    assert (second_row[5], second_row[6]) == (2, 1)
    async with factory() as session:
        async with session.begin():
            await session.execute(SoloPoolEntry.__table__.delete())
    assert await rebuild_solo_pool(factory) == 2
    assert await rows() == written
    # Run again over a full table: nothing doubles.
    assert await rebuild_solo_pool(factory) == 2
    assert await rows() == written


async def test_the_integrity_audit_reports_a_pool_that_drifted_from_its_facts(env):
    from app.services.integrity_audit import _solo_pool_slice

    users, history, solo, factory = env
    drawer, guesser, stranger, concept, recorded = await _cast(users, factory, history)
    private = await record_turn(
        history, drawer=drawer.id, guessers=[guesser.id], version_id=concept.versions["en"],
        visibility="private",
    )
    third = await record_turn(
        history, drawer=drawer.id, guessers=[guesser.id], version_id=concept.versions["en"]
    )

    async def audit():
        async with factory() as session:
            result = await _solo_pool_slice(session, None)
        return {(m.row_id, m.kind) for m in result.mismatches}

    assert await audit() == set()
    async with factory() as session:
        async with session.begin():
            await session.execute(
                SoloPoolEntry.__table__.delete().where(
                    SoloPoolEntry.turn_id == UUID(recorded.turn_id)
                )
            )
            await session.execute(
                update(SoloPoolEntry)
                .where(SoloPoolEntry.turn_id == UUID(third.turn_id))
                .values(correct_count=1, guesser_count=9)
            )
            row = await session.get(SoloPoolEntry, UUID(third.turn_id))
            session.add(
                SoloPoolEntry(
                    turn_id=UUID(private.turn_id), game_id=UUID(private.game_id),
                    concept_id=concept.id, prompt_version_id=concept.versions["en"],
                    drawer_user_id=UUID(drawer.id), guesser_count=1, correct_count=1,
                    finished_at=row.finished_at, sample_key=1,
                )
            )
    assert await audit() == {
        (recorded.turn_id, "missing"),
        (third.turn_id, "stale"),
        (private.turn_id, "unexpected"),
    }


@pytest.mark.parametrize(
    "values",
    [
        {"status": "deleted", "payload": None, "object_key": None, "checksum_sha256": None,
         "byte_size": None, "format_magic": None, "format_version": None, "deleted_at": NOW},
        {"status": "unavailable", "payload": None, "object_key": None, "checksum_sha256": None,
         "byte_size": None, "format_magic": None, "format_version": None,
         "unavailable_reason": "recap_budget"},
    ],
)
async def test_a_drawing_no_longer_kept_is_not_served_even_while_its_row_stands(env, values):
    # A rebuild racing an erasure can put a row back (#1491 review): serving
    # asks the drawing itself, so the row standing serves nothing.
    users, history, solo, factory = env
    *_, stranger, _, recorded = await _cast(users, factory, history)
    await _set_drawing(factory, recorded.turn_id, **values)
    assert UUID(recorded.turn_id) in await _pool(factory)
    assert await _served(solo, stranger) == set()


async def test_each_drawer_s_opt_out_is_their_own_with_merged_and_plain_drawers_side_by_side(env):
    # Two merged guests and a plain drawer: one alias row per guest, and the
    # opt-out of one canonical account reaches that account's drawings alone
    # (#1491 review - an uncorrelated alias lookup failed on PostgreSQL with
    # two merged drawers and pinned one opt-out on every row).
    users, history, solo, factory = env
    guesser = await player(users, factory, "Guesser")
    stranger = await player(users, factory, "Stranger")
    plain = await player(users, factory, "Plain")
    owners = [await player(users, factory, f"Owner{i}") for i in range(2)]
    guests = [await users.create_anonymous(display_name=f"Visitor{i}") for i in range(2)]
    concept = await seed_concept(factory, {"en": "lighthouse"})
    turns = {}
    for name, drawer in (("plain", plain), ("first", guests[0]), ("second", guests[1])):
        turns[name] = (
            await record_turn(
                history, drawer=drawer.id, guessers=[guesser.id], version_id=concept.versions["en"]
            )
        ).turn_id
    async with factory() as session:
        async with session.begin():
            for guest, owner in zip(guests, owners, strict=True):
                session.add(
                    IdentityAlias(source_user_id=UUID(guest.id), target_user_id=UUID(owner.id))
                )
    assert await _served(solo, stranger) == set(turns.values())
    async with factory() as session:
        async with session.begin():
            (await session.get(UserSettings, UUID(owners[0].id))).solo_opt_out = True
    assert await _served(solo, stranger) == {turns["plain"], turns["second"]}
