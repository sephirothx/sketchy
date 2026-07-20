"""ASGI entrypoint: mounts the Socket.IO server alongside a small FastAPI REST app."""
from pathlib import Path

import socketio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app import events
from app.state import room_manager

sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")
events.register_handlers(sio, room_manager)

api = FastAPI(title="Sketchy")
api.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@api.get("/api/health")
async def health():
    return {"status": "ok"}


@api.get("/api/rooms")
async def list_public_rooms():
    return room_manager.list_public_rooms()


# In production, serve the built frontend as static files from the same origin
# (single-port self-hosting). No-op during development when the folder is absent.
_frontend_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _frontend_dist.is_dir():
    api.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="frontend")

app = socketio.ASGIApp(sio, other_asgi_app=api, socketio_path="socket.io")
