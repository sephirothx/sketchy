"""An administrator erasing one drawing for illegal content (#1419, R-MOD-22):
everywhere a player could meet it goes, the report's evidence copy stays for
administrators alone, and nobody else may do it."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import UUID

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.api.errors import install_refusal_handler
from app.api.gallery import create_gallery_router, gallery_limiter
from app.api.moderation import create_moderation_router
from app.api.profiles import create_profile_router
from app.auth.account_data import anonymize_account
from app.auth.middleware import SessionAuthMiddleware
from app.db.models import (
    AuditEvent,
    generate_uuid,
    InboxEntry,
    ProfileDrawingPin,
    TurnDrawing,
    TurnDrawingReaction,
    TurnDrawingShare,
    User,
)
from app.domain_values import TurnDrawingStatus, UserRole
from app.repositories import sqlalchemy as repository
from app.repositories.sqlalchemy import (
    SqlAlchemyGameHistoryRepository,
    erase_drawing_for_moderation,
    SqlAlchemyUserRepository,
)
from app.services.inbox import add_entry
from app.services.gallery_shelf import GalleryShelfCache, shelf_reader
from tests.dbfixtures import create_test_db
from tests.test_api_gallery import _as_moderator
from tests.test_api_profiles import _registered, sign_in_as
from tests.test_drawing_reactions import record_game

NOW = datetime.now(timezone.utc)


@pytest_asyncio.fixture
async def env():
    session_factory, engine = await create_test_db()
    gallery_limiter.reset()
    users = SqlAlchemyUserRepository(session_factory)
    history = SqlAlchemyGameHistoryRepository(session_factory)
    shelf = GalleryShelfCache(shelf_reader(history, session_factory))
    erased: list[str] = []

    async def on_drawing_erased(turn_id: str) -> None:
        erased.append(turn_id)

    app = FastAPI()
    install_refusal_handler(app)
    app.add_middleware(SessionAuthMiddleware, session_factory=session_factory)
    app.include_router(create_profile_router(users, history))
    app.include_router(create_gallery_router(history, shelf=shelf))
    app.include_router(
        create_moderation_router(
            session_factory,
            game_history_repo=history,
            on_gallery_decision=shelf.invalidate,
            on_drawing_erased=on_drawing_erased,
        )
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        http.erased = erased
        yield http, users, history, session_factory
    await engine.dispose()


async def _staff(users, factory, name: str, role: UserRole):
    account = await _registered(users, name)
    async with factory() as session:
        async with session.begin():
            (await session.get(User, UUID(account.id))).role = role.value
    return account


async def _reported_drawing(http, users, history, factory):
    """A public game's drawing, shared, reacted to and pinned, with a share
    entry in its drawer's inbox, and reported from the Gallery so a report
    carries a copy of it."""
    ann = await _registered(users, "Ann")
    bob = await _registered(users, "Bob")
    cid = await _registered(users, "Cid")
    game = await record_game(
        history, drawer=ann.id, reactor=bob.id, visibility="public",
        shared_by="reactor", reactions="default", finished_at=NOW,
    )
    turn = UUID(game.turn_id)
    async with factory() as session:
        async with session.begin():
            session.add(
                ProfileDrawingPin(
                    user_id=UUID(bob.id), turn_id=turn, game_id=UUID(game.game_id),
                    position=0, created_at=NOW,
                )
            )
            await add_entry(session, user_id=ann.id, kind="drawing_shared", subject_id=turn)
    await sign_in_as(http, factory, cid.id)
    filed = await http.post(f"/api/gallery/{game.turn_id}/report", json={"details": "Not legal."})
    assert filed.status_code == 201, filed.text
    return game, ann, bob, filed.json()["id"]


async def _count(factory, model, turn: UUID) -> int:
    async with factory() as session:
        return await session.scalar(
            select(func.count()).select_from(model).where(model.turn_id == turn)
        )


async def test_an_administrator_erases_a_drawing_everywhere_a_player_could_meet_it(env):
    http, users, history, factory = env
    game, ann, bob, report_id = await _reported_drawing(http, users, history, factory)
    turn = UUID(game.turn_id)
    admin = await _staff(users, factory, "Admin", UserRole.ADMIN)
    assert await _count(factory, TurnDrawingReaction, turn) == 1
    assert await _count(factory, TurnDrawingShare, turn) == 1
    assert await _count(factory, ProfileDrawingPin, turn) == 1

    await _as_moderator(http, factory, admin.id)
    path = f"/api/moderation/drawings/{game.turn_id}/erase"
    assert (await http.post(path, json={"note": "  "})).status_code == 422
    erased = await http.post(path, json={"note": "CSAM, reported to fedpol"})
    assert erased.status_code == 200, erased.text
    assert http.erased == [game.turn_id], "a recap still open is told"

    async with factory() as session:
        drawing = await session.get(TurnDrawing, turn)
        assert drawing.status == TurnDrawingStatus.DELETED.value
        assert drawing.payload is None and drawing.checksum_sha256 is None
        assert drawing.moderation_erased_at is not None
        assert (drawing.reaction_count, drawing.gallery_share_count) == (0, 0)
        audit = await session.scalar(select(AuditEvent).where(AuditEvent.event_type == "drawing.erased"))
        assert audit.actor_user_id == UUID(admin.id) and audit.target_user_id == UUID(ann.id)
        assert audit.details == {"note": "CSAM, reported to fedpol"}
        assert await session.scalar(
            select(func.count()).select_from(InboxEntry).where(InboxEntry.subject_id == turn)
        ) == 0, "the drawer is not offered View on what is gone"
    for model in (TurnDrawingReaction, TurnDrawingShare, ProfileDrawingPin):
        assert await _count(factory, model, turn) == 0, model.__name__

    # The players who were there read why it went; the Gallery and the
    # bytes have nothing; it cannot be erased twice.
    await sign_in_as(http, factory, bob.id)
    detail = (await http.get(f"/api/games/{game.game_id}")).json()
    assert detail["turns"][0]["drawingStatus"] == "removed"
    assert (await http.get(f"/api/gallery/{game.turn_id}")).status_code == 404
    await _as_moderator(http, factory, admin.id)
    assert (await http.post(path, json={"note": "again"})).status_code == 404

    # The report's copy stays, for administrators alone.
    assert (await http.get(f"/api/moderation/reports/{report_id}/drawing")).status_code == 200
    moderator = await _staff(users, factory, "Mod", UserRole.MODERATOR)
    await _as_moderator(http, factory, moderator.id)
    assert (await http.get(f"/api/moderation/reports/{report_id}/drawing")).status_code == 404
    queue = (await http.get("/api/moderation/reports")).json()
    [incident] = queue["incidents"]
    [report] = incident["reports"]
    assert report["turnErased"] is True and report["drawing"]["erased"] is True


async def test_only_an_administrator_may_erase_and_only_after_a_step_up(env):
    """A moderator hides (R-GAL-09); erasing is an administrator's, behind a
    step-up. A moderator is answered 404, as for every administrator's route
    (R-ROLE-01); a player is refused as every moderation route refuses one."""
    http, users, history, factory = env
    game, ann, bob, _ = await _reported_drawing(http, users, history, factory)
    path = f"/api/moderation/drawings/{game.turn_id}/erase"
    body = {"note": "illegal"}

    http.cookies.clear()
    assert (await http.post(path, json=body)).status_code == 401
    await sign_in_as(http, factory, bob.id)
    assert (await http.post(path, json=body)).status_code == 403, "not staff"
    moderator = await _staff(users, factory, "Mod", UserRole.MODERATOR)
    await _as_moderator(http, factory, moderator.id)
    assert (await http.post(path, json=body)).status_code == 404
    admin = await _staff(users, factory, "Admin", UserRole.ADMIN)
    await sign_in_as(http, factory, admin.id)
    assert (await http.post(path, json=body)).status_code == 403, "no step-up"
    async with factory() as session:
        drawing = await session.get(TurnDrawing, UUID(game.turn_id))
        assert drawing.status == TurnDrawingStatus.READY.value and drawing.payload is not None
    assert http.erased == []


async def test_the_warned_player_is_not_shown_an_erased_drawing_back(env):
    """Their own work is shown back in a warning (R-MOD-12) - unless an
    administrator erased it, which a notice must not undo."""
    http, users, history, factory = env
    game, ann, _, report_id = await _reported_drawing(http, users, history, factory)
    admin = await _staff(users, factory, "Admin", UserRole.ADMIN)
    await _as_moderator(http, factory, admin.id)
    warned = await http.post(
        "/api/moderation/warnings",
        json={"userId": ann.id, "reason": "Drawing", "category": "offensive_drawing", "reportId": report_id},
    )
    assert warned.status_code == 201, warned.text
    warning_id = warned.json()["id"]
    await sign_in_as(http, factory, ann.id)
    drawing_path = f"/api/warnings/{warning_id}/drawings/{report_id}"
    assert (await http.get(drawing_path)).status_code == 200

    await _as_moderator(http, factory, admin.id)
    assert (await http.post(f"/api/moderation/drawings/{game.turn_id}/erase", json={"note": "x"})).status_code == 200
    await sign_in_as(http, factory, ann.id)
    assert (await http.get(drawing_path)).status_code == 404


async def test_an_erasure_and_its_drawers_account_deletion_wait_for_each_other(env, monkeypatch):
    """The erasure takes the drawer's account before the drawing, the order an
    account deletion takes them in. Drawing first, it held the row the
    deletion wanted while its audit record waited on the account the deletion
    held, and PostgreSQL rolled one of them back. PostgreSQL only: SQLite has
    one writer, so the two cannot interleave."""
    http, users, history, factory = env
    async with factory() as probe:
        if probe.get_bind().dialect.name != "postgresql":
            pytest.skip("row locks interleave only on PostgreSQL")
    ann = await _registered(users, "AnnDeletes")
    bob = await _registered(users, "BobPlays")
    admin = await _staff(users, factory, "AdminErases", UserRole.ADMIN)
    game = await record_game(history, drawer=ann.id, reactor=bob.id, visibility="public", finished_at=NOW)
    turn = UUID(game.turn_id)

    holding, carry_on = asyncio.Event(), asyncio.Event()
    original = repository.forget_inbox_subjects

    async def pausing(*args, **kwargs):
        # By here the erasure holds whatever it locks before its last write.
        holding.set()
        await carry_on.wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr(repository, "forget_inbox_subjects", pausing)

    async def erase():
        async with factory() as session:
            async with session.begin():
                assert await erase_drawing_for_moderation(
                    session, turn, erased_by_user_id=UUID(admin.id), now=NOW
                )
                # The route's audit record, whose foreign key names the drawer.
                session.add(
                    AuditEvent(
                        id=generate_uuid(), event_type="drawing.erased",
                        actor_user_id=UUID(admin.id), target_user_id=UUID(ann.id),
                        target_type="drawing", target_id=game.turn_id,
                        details={"note": "x"}, created_at=NOW,
                    )
                )

    erasing = asyncio.create_task(erase())
    await asyncio.wait_for(holding.wait(), timeout=10)
    deleting = asyncio.create_task(anonymize_account(factory, user_id=ann.id))
    await asyncio.sleep(0.5)
    carry_on.set()
    await asyncio.wait_for(asyncio.gather(erasing, deleting), timeout=20)

    async with factory() as session:
        drawing = await session.get(TurnDrawing, turn)
        assert drawing.status == TurnDrawingStatus.DELETED.value
        assert drawing.moderation_erased_at is not None
