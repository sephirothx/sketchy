"""Solo's runs over REST (#1434): what is served, under which id, and what is kept.

Play is local, so these hold the server to its half: it serves only what the
pool allows, never under a turn id and never naming the drawer, hands over
the answer forms each drawing is judged by, and records each result once,
in order, deriving the points itself.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from uuid import UUID

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app.api.errors import install_refusal_handler
from app.api.solo import create_solo_router, drawing_limiter, run_limiter, serve_limiter
from app.auth.middleware import SessionAuthMiddleware
from app.db.models import (
    Prompt,
    PromptAlias,
    PromptList,
    PromptVersion,
    UserSettings,
    PromptUsageFact,
    PromptVersionAlias,
    SoloRun,
    SoloServe,
    TurnDrawing,
    UserStatsDaily,
    generate_uuid,
)
from app.guess_judge import AnswerForm, JudgeTarget, judge
from app.repositories.solo import SoloRepository
from app.repositories.sqlalchemy import SqlAlchemyGameHistoryRepository, SqlAlchemyUserRepository
from app.solo_rules import decode_answers
from tests.dbfixtures import create_test_db
from tests.solo_fixtures import player, record_turn, seed_concept
from tests.test_api_profiles import sign_in_as


@pytest_asyncio.fixture
async def env():
    factory, engine = await create_test_db()
    for limiter in (run_limiter, serve_limiter, drawing_limiter):
        limiter.reset()
    app = FastAPI()
    install_refusal_handler(app)
    app.add_middleware(SessionAuthMiddleware, session_factory=factory)
    app.include_router(create_solo_router(factory))
    users = SqlAlchemyUserRepository(factory)
    history = SqlAlchemyGameHistoryRepository(factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http, users, history, factory
    await engine.dispose()


async def _pool_of(users, history, factory, count: int, forms=None):
    """A drawer and a guesser, and `count` servable drawings between them."""
    drawer = await player(users, factory, "Drawer")
    guesser = await player(users, factory, "Guesser")
    turns = []
    for index in range(count):
        concept = await seed_concept(factory, forms or {"en": f"word{index}", "de": f"Wort{index}"})
        language = next(iter(concept.versions))
        turns.append(
            await record_turn(
                history, drawer=drawer.id, guessers=[guesser.id],
                version_id=concept.versions[language],
            )
        )
    return drawer, guesser, turns


def _target(serve: dict) -> JudgeTarget:
    raw = json.loads(decode_answers(serve["serveId"], serve["forms"]))
    return JudgeTarget(
        language=raw["language"],
        own=AnswerForm(raw["own"]["prompt"], tuple(raw["own"]["aliases"])),
        others={k: AnswerForm(v["prompt"], tuple(v["aliases"])) for k, v in raw["others"].items()},
        taken=frozenset(raw["taken"]),
    )


async def _start(http, length=5) -> dict:
    answer = await http.post("/api/solo/runs", json={"length": length})
    assert answer.status_code == 201, answer.text
    return answer.json()


async def _serve(http, run_id: str, count=1) -> list[dict]:
    answer = await http.post(f"/api/solo/runs/{run_id}/serves", params={"count": count})
    assert answer.status_code == 200, answer.text
    return answer.json()["serves"]


async def _settle(http, serve_id: str, outcome="solved", seconds=6.0):
    return await http.post(
        f"/api/solo/serves/{serve_id}/result", json={"outcome": outcome, "seconds": seconds}
    )


async def test_solo_is_for_registered_players(env):
    http, users, history, factory = env
    refused = await http.post("/api/solo/runs", json={"length": 5})
    assert refused.status_code == 401
    guest = await users.create_anonymous(display_name="Visitor")
    await sign_in_as(http, factory, guest.id)
    refused = await http.post("/api/solo/runs", json={"length": 5})
    assert refused.status_code == 403
    assert refused.json()["errorCode"] == "account_required"
    assert refused.json()["params"] == {"action": "solo"}


async def test_a_serve_names_neither_turn_nor_drawer_and_carries_its_answer(env):
    http, users, history, factory = env
    drawer, _, [turn] = await _pool_of(users, history, factory, 1)
    stranger = await player(users, factory, "Stranger", languages=("en", "de"))
    await sign_in_as(http, factory, stranger.id)
    run = await _start(http)
    assert run["serves"] == [] and run["state"] == "active"
    [serve] = await _serve(http, run["runId"])

    text = json.dumps(serve) + json.dumps(run)
    assert turn.turn_id not in text and turn.game_id not in text
    assert drawer.id not in text and "Drawer" not in text
    assert "word0" not in text and serve["prompt"] is None
    # The answer is in the forms, for the client to judge with.
    target = _target(serve)
    assert target.own.answer == "word0" and set(target.others) == {"de"}
    assert judge("word0", target) == "correct"
    assert judge("Wort0", target) == "correct"
    assert judge("wordd0", target) == "close"


async def test_the_fourth_door_serves_the_drawing_only_to_the_player_it_was_served_to(env):
    http, users, history, factory = env
    _, _, [turn] = await _pool_of(users, history, factory, 1)
    stranger = await player(users, factory, "Stranger")
    other = await player(users, factory, "Other")
    await sign_in_as(http, factory, stranger.id)
    run = await _start(http)
    [serve] = await _serve(http, run["runId"])
    path = f"/api/solo/serves/{serve['serveId']}/drawing"

    bytes_answer = await http.get(path)
    assert bytes_answer.status_code == 200
    assert bytes_answer.headers["cache-control"] == "private, no-cache"
    again = await http.get(path, headers={"If-None-Match": bytes_answer.headers["etag"]})
    assert again.status_code == 304
    # The turn id is no way in, on this door.
    assert (await http.get(f"/api/solo/serves/{turn.turn_id}/drawing")).status_code == 404

    await sign_in_as(http, factory, other.id)
    assert (await http.get(path)).status_code == 404
    http.cookies.clear()
    assert (await http.get(path)).status_code == 404

    # A moderator's hide closes the door at once, a remembered validator too.
    await sign_in_as(http, factory, stranger.id)
    async with factory() as session:
        async with session.begin():
            await session.execute(
                update(TurnDrawing)
                .where(TurnDrawing.turn_id == UUID(turn.turn_id))
                .values(gallery_hidden_at=func.now())
            )
    gone = await http.get(path, headers={"If-None-Match": bytes_answer.headers["etag"]})
    assert gone.status_code == 404
    assert gone.json()["errorCode"] == "no_such_drawing"


async def test_a_result_is_recorded_once_in_order_and_the_server_derives_the_points(env):
    http, users, history, factory = env
    await _pool_of(users, history, factory, 3)
    stranger = await player(users, factory, "Stranger")
    await sign_in_as(http, factory, stranger.id)
    run = await _start(http)
    first, second = await _serve(http, run["runId"], count=2)
    # Never more than two open: the one played and the one held ready.
    assert await _serve(http, run["runId"]) == []

    out_of_order = await _settle(http, second["serveId"])
    assert out_of_order.status_code == 409
    assert out_of_order.json()["errorCode"] == "solo_conflict"
    too_long = await _settle(http, first["serveId"], seconds=31)
    assert too_long.status_code == 422

    settled = await _settle(http, first["serveId"], seconds=15)
    assert settled.status_code == 200
    body = settled.json()
    assert body["serve"]["points"] == 200 and body["serve"]["outcome"] == "solved"
    assert body["serve"]["prompt"] in {"word0", "word1", "word2"}
    assert body["serve"]["promptLanguage"] == "en"
    assert (body["run"]["solved"], body["run"]["points"]) == (1, 200)
    assert (await _settle(http, first["serveId"])).status_code == 409

    given_up = (await _settle(http, second["serveId"], "given_up", 3)).json()
    assert given_up["serve"]["points"] is None
    assert given_up["run"]["points"] == 200 and given_up["run"]["state"] == "active"

    other = await player(users, factory, "Other")
    await sign_in_as(http, factory, other.id)
    refused = await _settle(http, second["serveId"])
    assert refused.status_code == 404
    assert refused.json()["errorCode"] == "no_such_drawing"
    assert (await http.get(f"/api/solo/runs/{run['runId']}")).status_code == 404


async def test_a_five_run_ends_with_its_fifth_drawing_and_repeats_a_thin_pool(env, monkeypatch):
    # Every draw starts at the bottom of the pool's order: only the
    # seen-exclusion can make the second drawing a different one.
    monkeypatch.setattr("app.repositories.solo.random.randrange", lambda _stop: 0)
    http, users, history, factory = env
    _, _, turns = await _pool_of(users, history, factory, 2)
    stranger = await player(users, factory, "Stranger")
    await sign_in_as(http, factory, stranger.id)
    run = await _start(http)
    served_turns = []
    for _ in range(5):
        [serve] = await _serve(http, run["runId"])
        answer = (await _settle(http, serve["serveId"], seconds=0)).json()
        served_turns.append(serve["serveId"])
    assert answer["run"]["state"] == "ended" and answer["run"]["endReason"] == "completed"
    assert (answer["run"]["solved"], answer["run"]["points"]) == (5, 1500)
    async with factory() as session:
        turn_ids = (
            await session.scalars(select(SoloServe.turn_id).order_by(SoloServe.position))
        ).all()
    # Both drawings first, unseen, before either is repeated.
    assert set(turn_ids[:2]) == {UUID(turn.turn_id) for turn in turns}
    assert len(turn_ids) == 5
    refused = await http.post(f"/api/solo/runs/{run['runId']}/serves")
    assert refused.status_code == 409


async def test_an_unlimited_run_ends_at_its_first_miss_and_drops_the_drawing_held_ready(env):
    http, users, history, factory = env
    await _pool_of(users, history, factory, 4)
    stranger = await player(users, factory, "Stranger")
    await sign_in_as(http, factory, stranger.id)
    run = await _start(http, None)
    first, second = await _serve(http, run["runId"], count=2)
    assert (await _settle(http, first["serveId"], seconds=29.5)).json()["run"]["state"] == "active"
    [third] = await _serve(http, run["runId"])
    ended = (await _settle(http, second["serveId"], "timed_out", 30)).json()["run"]
    assert (ended["state"], ended["endReason"], ended["solved"]) == ("ended", "missed", 1)
    assert [serve["position"] for serve in ended["serves"]] == [1, 2]
    async with factory() as session:
        assert await session.get(SoloServe, UUID(third["serveId"])) is None


async def test_starting_a_run_abandons_only_the_one_of_its_length(env):
    http, users, history, factory = env
    await _pool_of(users, history, factory, 6)
    stranger = await player(users, factory, "Stranger")
    await sign_in_as(http, factory, stranger.id)
    five = await _start(http, 5)
    [serve] = await _serve(http, five["runId"])
    await _settle(http, serve["serveId"])

    unlimited = await _start(http, None)
    [serve] = await _serve(http, unlimited["runId"])
    await _settle(http, serve["serveId"])
    [held] = await _serve(http, unlimited["runId"])
    ten = await _start(http, 10)

    async def states() -> dict:
        async with factory() as session:
            return {
                run.id: (run.state, run.end_reason, run.solved)
                for run in (await session.scalars(select(SoloRun))).all()
            }

    # One of each length goes on at once: Quick, Classic and Endless.
    assert {state for state, _, _ in (await states()).values()} == {"active"}
    resumed = (await http.get(f"/api/solo/runs/{unlimited['runId']}")).json()
    # Continue shows the drawing in play with its forms, so a reload resumes it.
    assert resumed["serves"][-1]["serveId"] == held["serveId"]
    assert resumed["serves"][-1]["forms"]

    await _start(http, 5)
    await _start(http, None)
    runs = await states()
    # A 5 run left unfinished records nothing; an unlimited one ends at its streak.
    assert runs[UUID(five["runId"])] == ("abandoned", "abandoned", 1)
    assert runs[UUID(unlimited["runId"])] == ("ended", "abandoned", 1)
    assert runs[UUID(ten["runId"])] == ("active", None, 0)
    assert sum(state == "active" for state, _, _ in runs.values()) == 3
    async with factory() as session:
        assert await session.get(SoloServe, UUID(held["serveId"])) is None


async def test_starts_at_once_leave_one_run_of_each_length(env):
    """PostgreSQL only: it is the database two transactions overlap in;
    SQLite's one shared test connection would roll one start back with
    another's conflict."""
    _http, users, _history, factory = env
    async with factory() as session:
        if session.get_bind().dialect.name != "postgresql":
            pytest.skip("concurrent transactions are PostgreSQL's")
    stranger = await player(users, factory, "Stranger")
    solo, now = SoloRepository(factory), datetime.now(timezone.utc)
    await asyncio.gather(
        *(solo.start_free_run(stranger.id, length=length, now=now) for length in (None, None, 5, 5, 10))
    )
    async with factory() as session:
        active = (
            await session.scalars(select(SoloRun.length).where(SoloRun.state == "active"))
        ).all()
    assert sorted(active, key=lambda length: length or 99) == [5, 10, None]


async def test_the_index_holds_one_unlimited_run_too(env):
    # Unlimited is NULL, and a unique index never sees two NULLs clash: the
    # index compares the length as 0 for it, or two Endless runs go on.
    _http, users, _history, factory = env
    stranger = await player(users, factory, "Stranger")
    now = datetime.now(timezone.utc)
    with pytest.raises(IntegrityError):
        async with factory() as session:
            async with session.begin():
                for _ in range(2):
                    session.add(
                        SoloRun(
                            user_id=UUID(stranger.id), mode="free", length=None, state="active",
                            position=0, solved=0, points=0, started_at=now,
                        )
                    )


async def test_a_player_the_pool_has_nothing_for_is_told_so(env):
    http, users, history, factory = env
    await _pool_of(users, history, factory, 1, forms={"fr": "phare"})
    english = await player(users, factory, "English")
    await sign_in_as(http, factory, english.id)
    run = await _start(http)
    refused = await http.post(f"/api/solo/runs/{run['runId']}/serves")
    assert refused.status_code == 409
    assert refused.json()["errorCode"] == "solo_pool_empty"


async def test_the_forms_are_the_player_s_languages_with_aliases_and_false_friends_out(env):
    http, users, history, factory = env
    drawer = await player(users, factory, "Drawer")
    guesser = await player(users, factory, "Guesser")
    hut = await seed_concept(factory, {"en": "hut", "de": "Hütte"})
    hat = await seed_concept(factory, {"de": "Hut", "en": "hat"})
    async with factory() as session:
        async with session.begin():
            alias = PromptAlias(
                id=generate_uuid(), concept_id=hut.id, language="en", answer="shack",
                match_key="shack",
            )
            session.add(alias)
            await session.flush()
            session.add(PromptVersionAlias(prompt_version_id=hut.versions["en"], alias_id=alias.id))
    await record_turn(history, drawer=drawer.id, guessers=[guesser.id], version_id=hut.versions["en"])
    german = await player(users, factory, "German", languages=("de", "en"))
    await sign_in_as(http, factory, german.id)
    run = await _start(http)
    [serve] = await _serve(http, run["runId"])
    target = _target(serve)
    assert (target.language, target.own.answer) == ("de", "Hütte")
    assert target.others["en"] == AnswerForm("hut", ("shack",))
    # German "Hut" is the hat: it does not win the English hut.
    assert "hut" in target.taken
    assert judge("Hut", target) == "another_language"
    assert judge("shack", target) == "correct"
    assert judge("huette", target) == "correct"
    settled = (await _settle(http, serve["serveId"], "given_up", 30)).json()
    assert (settled["serve"]["prompt"], settled["serve"]["promptLanguage"]) == ("Hütte", "de")
    del hat


async def test_an_agnostic_drawing_is_one_answer_in_the_player_s_fold(env):
    http, users, history, factory = env
    await _pool_of(users, history, factory, 1, forms={"zxx": "Pikachu"})
    polish = await player(users, factory, "Polish", languages=("pl", "en"))
    await sign_in_as(http, factory, polish.id)
    run = await _start(http)
    [serve] = await _serve(http, run["runId"])
    target = _target(serve)
    assert (target.language, target.own.answer, dict(target.others)) == ("pl", "Pikachu", {})
    settled = (await _settle(http, serve["serveId"], "timed_out", 30)).json()
    assert settled["serve"]["promptLanguage"] == "zxx"


async def test_playing_writes_nothing_to_game_statistics(env):
    http, users, history, factory = env
    await _pool_of(users, history, factory, 2)
    stranger = await player(users, factory, "Stranger")

    async def counts():
        async with factory() as session:
            return (
                await session.scalar(select(func.count()).select_from(UserStatsDaily)),
                await session.scalar(
                    select(func.coalesce(func.sum(UserStatsDaily.prompts_guessed), 0))
                ),
                await session.scalar(select(func.count()).select_from(PromptUsageFact)),
            )

    before = await counts()
    await sign_in_as(http, factory, stranger.id)
    run = await _start(http, None)
    for _ in range(2):
        [serve] = await _serve(http, run["runId"])
        await _settle(http, serve["serveId"])
    assert await counts() == before


@pytest.mark.parametrize("body", [{"length": 7}, {"length": "5"}, {}, {"length": 5, "x": 1}])
async def test_a_run_is_5_10_or_unlimited(env, body):
    http, users, history, factory = env
    stranger = await player(users, factory, "Stranger")
    await sign_in_as(http, factory, stranger.id)
    assert (await http.post("/api/solo/runs", json=body)).status_code == 422


async def test_deleting_an_account_takes_its_runs_and_closes_its_drawings_to_others(env):
    from app.auth.account_data import anonymize_account

    http, users, history, factory = env
    drawer, _, [turn] = await _pool_of(users, history, factory, 1)
    stranger = await player(users, factory, "Stranger")
    await sign_in_as(http, factory, stranger.id)
    run = await _start(http)
    [serve] = await _serve(http, run["runId"])
    await _settle(http, serve["serveId"])

    # The drawer goes: the stranger's run stays, the drawing does not.
    await anonymize_account(factory, user_id=drawer.id)
    assert (await http.get(f"/api/solo/serves/{serve['serveId']}/drawing")).status_code == 404
    assert (await http.get(f"/api/solo/runs/{run['runId']}")).status_code == 200

    # The player goes: their runs and serves go with them.
    await anonymize_account(factory, user_id=stranger.id)
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(SoloRun)) == 0
        assert await session.scalar(select(func.count()).select_from(SoloServe)) == 0


async def test_the_false_friend_guard_reads_every_spelling_not_only_the_key(env):
    # French "luge" is a sled; German "Lüge" (a lie) is "luege" by its key and
    # "luge" by its plain fold. A German who types "Lüge" means the lie and
    # must not win the French sled (#1492 review).
    http, users, history, factory = env
    drawer = await player(users, factory, "Drawer")
    guesser = await player(users, factory, "Guesser")
    sled = await seed_concept(factory, {"fr": "luge", "de": "Schlitten"})
    await seed_concept(factory, {"de": "Lüge"})
    await record_turn(history, drawer=drawer.id, guessers=[guesser.id], version_id=sled.versions["fr"])
    bilingual = await player(users, factory, "Bilingual", languages=("de", "fr"))
    await sign_in_as(http, factory, bilingual.id)
    [serve] = await _serve(http, (await _start(http))["runId"])
    target = _target(serve)
    assert (target.language, target.own.answer) == ("de", "Schlitten")
    assert "luge" in target.taken
    assert judge("Lüge", target) == "another_language"
    assert judge("Schlitten", target) == "correct"


async def test_wording_is_the_drawn_version_or_the_official_one_never_a_private_rewording(env):
    http, users, history, factory = env
    drawer = await player(users, factory, "Drawer")
    guesser = await player(users, factory, "Guesser")
    concept = await seed_concept(factory, {"en": "hut", "de": "Hütte"})
    # Newer versions nobody official plays: a player's private rewording.
    async with factory() as session:
        async with session.begin():
            for language, text in (("en", "cabin"), ("de", "Kate")):
                session.add(
                    PromptVersion(
                        id=generate_uuid(), concept_id=concept.id, language=language,
                        version=2, canonical_answer=text, match_key=text.lower(),
                    )
                )
    await record_turn(history, drawer=drawer.id, guessers=[guesser.id], version_id=concept.versions["en"])
    stranger = await player(users, factory, "Stranger", languages=("en", "de"))
    await sign_in_as(http, factory, stranger.id)
    [serve] = await _serve(http, (await _start(http))["runId"])
    target = _target(serve)
    assert target.own.answer == "hut" and target.others["de"].answer == "Hütte"
    assert judge("cabin", target) is None


async def test_a_resumed_drawing_is_judged_as_it_was_served(env):
    http, users, history, factory = env
    await _pool_of(users, history, factory, 2)
    stranger = await player(users, factory, "Stranger", languages=("en", "de"))
    await sign_in_as(http, factory, stranger.id)
    run = await _start(http, None)
    [serve] = await _serve(http, run["runId"])
    async with factory() as session:
        async with session.begin():
            settings = await session.get(UserSettings, UUID(stranger.id))
            settings.prompt_language, settings.extra_prompt_languages = "pl", []
    resumed = (await http.get(f"/api/solo/runs/{run['runId']}")).json()["serves"][0]
    assert _target(resumed) == _target(serve)


async def test_a_dropped_drawing_is_not_counted_as_served(env):
    http, users, history, factory = env
    await _pool_of(users, history, factory, 3)
    stranger = await player(users, factory, "Stranger")
    await sign_in_as(http, factory, stranger.id)
    run = await _start(http, None)
    first, _held = await _serve(http, run["runId"], count=2)
    ended = (await _settle(http, first["serveId"], "given_up", 4)).json()["run"]
    # An unlimited run ends on giving up too, and the drawing held ready goes.
    assert (ended["state"], ended["endReason"], ended["position"]) == ("ended", "missed", 1)


async def test_a_thin_pool_repeats_the_drawing_seen_longest_ago(env, monkeypatch):
    monkeypatch.setattr("app.repositories.solo.random.randrange", lambda _stop: 0)
    http, users, history, factory = env
    await _pool_of(users, history, factory, 3)
    stranger = await player(users, factory, "Stranger")
    await sign_in_as(http, factory, stranger.id)
    run = await _start(http, None)
    order = []
    for _ in range(3):
        [serve] = await _serve(http, run["runId"])
        await _settle(http, serve["serveId"])
        order.append(serve["serveId"])
    [repeat] = await _serve(http, run["runId"])
    async with factory() as session:
        turns = {
            serve.id: serve.turn_id
            for serve in (await session.scalars(select(SoloServe))).all()
        }
    assert turns[UUID(repeat["serveId"])] == turns[UUID(order[0])]


async def test_another_player_s_run_and_a_settle_after_an_abandon_are_refused_cleanly(env):
    http, users, history, factory = env
    await _pool_of(users, history, factory, 3)
    stranger = await player(users, factory, "Stranger")
    other = await player(users, factory, "Other")
    await sign_in_as(http, factory, stranger.id)
    run = await _start(http)
    _first, held = await _serve(http, run["runId"], count=2)
    await sign_in_as(http, factory, other.id)
    refused = await http.post(f"/api/solo/runs/{run['runId']}/serves")
    assert refused.status_code == 404 and refused.json()["errorCode"] == "no_such_solo_run"
    await sign_in_as(http, factory, stranger.id)
    await _start(http)
    # The abandon took the drawing held ready: reporting it is a refusal, not an error.
    late = await _settle(http, held["serveId"])
    assert late.status_code in (404, 409)


async def test_the_drawn_version_is_the_wording_in_its_own_language(env):
    # An official list reworded the concept since the game: the drawing was
    # of the drawer's wording, and that is what its player is judged by.
    http, users, history, factory = env
    drawer = await player(users, factory, "Drawer")
    guesser = await player(users, factory, "Guesser")
    concept = await seed_concept(factory, {"en": "hut"})
    newer = generate_uuid()
    async with factory() as session:
        async with session.begin():
            session.add(
                PromptVersion(
                    id=newer, concept_id=concept.id, language="en", version=2,
                    canonical_answer="mountain hut", match_key="mountainhut",
                )
            )
            listed = generate_uuid()
            session.add(
                PromptList(
                    id=listed, slug=f"solo-{listed}", name="Official reworded", description="",
                    language="en", version=1, is_bundled=True,
                )
            )
            await session.flush()
            session.add(
                Prompt(prompt_list_id=listed, concept_id=concept.id, prompt_version_id=newer,
                       text="mountain hut")
            )
    await record_turn(history, drawer=drawer.id, guessers=[guesser.id], version_id=concept.versions["en"])
    stranger = await player(users, factory, "Stranger")
    await sign_in_as(http, factory, stranger.id)
    [serve] = await _serve(http, (await _start(http))["runId"])
    assert _target(serve).own.answer == "hut"
