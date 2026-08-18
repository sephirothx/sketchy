"""ASGI entrypoint: mounts the Socket.IO server alongside a small FastAPI REST app."""
from contextlib import asynccontextmanager
from pathlib import Path

import socketio
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.gzip import GZipMiddleware

from app.auth.jwt import create_token, get_or_create_jwt_secret
from app.auth.middleware import AuthMiddleware, set_auth_cookie
from app.auth.password import hash_password, verify_password
from app.auth.schemas import LoginRequest, RegisterRequest
from app.db import async_session_factory, init_db
from app.db.seed import seed_word_lists
from app.handlers import register_all_handlers
from app.repositories.interfaces import (
    AccountAlreadyClaimedError,
    UserData,
    UsernameTakenError,
)
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
        except StarletteHTTPException as exc:
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
_jwt_secret: str = ""

handler_context = register_all_handlers(
    sio,
    room_manager,
    user_repo=user_repo,
    game_history_repo=game_history_repo,
    word_list_repo=word_list_repo,
    jwt_secret_getter=lambda: _jwt_secret,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _jwt_secret
    await init_db()
    _jwt_secret = await get_or_create_jwt_secret(async_session_factory)
    await seed_word_lists(word_list_repo)
    try:
        yield
    finally:
        await handler_context.timers.close()


api = FastAPI(title="Sketchy", lifespan=lifespan)
api.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)
api.add_middleware(
    AuthMiddleware,
    user_repo=user_repo,
    jwt_secret_getter=lambda: _jwt_secret,
)


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


@api.get("/api/auth/me")
async def get_current_user(request: Request):
    user: UserData | None = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    stats = await user_repo.get_stats(user.id)
    return {
        "id": user.id,
        "username": user.username,
        "displayName": user.display_name,
        "nameColor": user.name_color,
        "avatarUrl": user.avatar_url,
        "isAnonymous": user.is_anonymous,
        "createdAt": user.created_at.isoformat() if user.created_at else "",
        "stats": {
            "gamesPlayed": stats.games_played,
            "gamesWon": stats.games_won,
            "winRate": stats.win_rate,
            "totalScore": stats.total_score,
            "averageScore": stats.average_score,
        } if stats else None,
    }


@api.post("/api/auth/register")
async def register_user(req: RegisterRequest, request: Request, response: Response):
    current_user: UserData | None = getattr(request.state, "user", None)
    pw_hash = hash_password(req.password)
    try:
        if current_user and current_user.is_anonymous:
            user = await user_repo.claim_account(
                user_id=current_user.id,
                username=req.username,
                password_hash=pw_hash,
                display_name=req.username,
            )
        else:
            user = await user_repo.register(
                username=req.username,
                password_hash=pw_hash,
                display_name=req.username,
            )
    except UsernameTakenError:
        raise HTTPException(status_code=409, detail="Username is already taken")
    except AccountAlreadyClaimedError:
        raise HTTPException(status_code=400, detail="Account is already registered")

    token = create_token(user.id, _jwt_secret)
    set_auth_cookie(response, token)
    return {
        "id": user.id,
        "username": user.username,
        "displayName": user.display_name,
        "nameColor": user.name_color,
        "avatarUrl": user.avatar_url,
        "isAnonymous": user.is_anonymous,
        "createdAt": user.created_at.isoformat() if user.created_at else "",
        "token": token,
    }


@api.post("/api/auth/login")
async def login_user(req: LoginRequest, response: Response):
    creds = await user_repo.get_credentials_by_username(req.username)
    if not creds or not verify_password(req.password, creds.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    user = creds.user
    token = create_token(user.id, _jwt_secret)
    set_auth_cookie(response, token)
    return {
        "id": user.id,
        "username": user.username,
        "displayName": user.display_name,
        "nameColor": user.name_color,
        "avatarUrl": user.avatar_url,
        "isAnonymous": user.is_anonymous,
        "createdAt": user.created_at.isoformat() if user.created_at else "",
        "token": token,
    }


@api.post("/api/auth/logout")
async def logout_user(response: Response):
    guest = await user_repo.create_anonymous(display_name="Guest")
    token = create_token(guest.id, _jwt_secret)
    set_auth_cookie(response, token)
    return {
        "ok": True,
        "token": token,
        "user": {
            "id": guest.id,
            "username": guest.username,
            "displayName": guest.display_name,
            "nameColor": guest.name_color,
            "avatarUrl": guest.avatar_url,
            "isAnonymous": guest.is_anonymous,
            "createdAt": guest.created_at.isoformat() if guest.created_at else "",
        },
    }


# In production, serve the built frontend as static files from the same origin
_frontend_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
configure_frontend(api, _frontend_dist)

app = socketio.ASGIApp(sio, other_asgi_app=api, socketio_path="socket.io")

