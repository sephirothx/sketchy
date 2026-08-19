"""ASGI entrypoint: mounts the Socket.IO server alongside a small FastAPI REST app."""
from contextlib import asynccontextmanager
from pathlib import Path

import socketio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException
from starlette.middleware.gzip import GZipMiddleware

from app.auth.middleware import SessionAuthMiddleware
from app.auth.routes import create_auth_router
from app.db import async_session_factory, init_db
from app.db.seed import seed_word_lists
from app.handlers import register_all_handlers
from app.repositories.sqlalchemy import (
    SqlAlchemyGameHistoryRepository,
    SqlAlchemyUserRepository,
    SqlAlchemyWordListRepository,
)
from app.state import room_manager


class SPAStaticFiles(StaticFiles):
    """Serve the SPA for extensionless client routes while preserving real 404s."""

    async def get_response(self, path: str, scope):
        try:
            response = await super().get_response(path, scope)
        except HTTPException as exc:
            is_client_route = (
                exc.status_code == 404
                and not path.startswith("api/")
                and not Path(path).suffix
            )
            if not is_client_route:
                raise
            response = await super().get_response("index.html", scope)

        if path.startswith("assets/"):
            response.headers["Cache-Control"] = (
                "public, max-age=31536000, immutable"
            )
        else:
            # HTML and non-fingerprinted files must revalidate so a new deploy is
            # discovered instead of leaving clients on a stale application shell.
            response.headers["Cache-Control"] = "no-cache"
        return response


def configure_frontend(app: FastAPI, directory: Path) -> None:
    """Enable static compression and mount the production frontend when present."""

    app.add_middleware(GZipMiddleware, minimum_size=500)
    if directory.is_dir():
        app.mount(
            "/",
            SPAStaticFiles(directory=str(directory), html=True),
            name="frontend",
        )


user_repo = SqlAlchemyUserRepository(async_session_factory)
game_history_repo = SqlAlchemyGameHistoryRepository(async_session_factory)
word_list_repo = SqlAlchemyWordListRepository(async_session_factory)

sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")
handler_context = register_all_handlers(
    sio,
    room_manager,
    user_repo=user_repo,
    game_history_repo=game_history_repo,
    word_list_repo=word_list_repo,
    session_factory=async_session_factory,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await init_db()
    await seed_word_lists(word_list_repo)
    try:
        yield
    finally:
        await handler_context.timers.close()


api = FastAPI(title="Sketchy", lifespan=lifespan)
# No allow_credentials: the frontend is served from this same origin, so the
# session cookie rides along without CORS involvement. Turning credentials on
# alongside a wildcard origin is invalid anyway, and would be the only reason
# to need CSRF tokens on top of SameSite=Lax.
api.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
api.add_middleware(SessionAuthMiddleware, session_factory=async_session_factory)
api.include_router(create_auth_router(user_repo, async_session_factory))


@api.get("/api/health")
async def health():
    return {"status": "ok"}


@api.get("/api/rooms")
async def list_public_rooms():
    return room_manager.list_public_rooms()


@api.get("/api/word-lists")
async def list_word_lists():
    lists = await word_list_repo.list_all()
    return [
        {
            "slug": wl.slug,
            "name": wl.name,
            "description": wl.description,
            "language": wl.language,
            "wordCount": wl.word_count,
            "isBundled": wl.is_bundled,
            "version": wl.version,
        }
        for wl in lists
    ]


# In production, serve the built frontend as static files from the same origin
# (single-port self-hosting). No-op during development when the folder is absent.
_frontend_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
configure_frontend(api, _frontend_dist)

app = socketio.ASGIApp(sio, other_asgi_app=api, socketio_path="socket.io")
