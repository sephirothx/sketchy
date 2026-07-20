"""Process-wide singletons shared between the REST routes and Socket.IO handlers."""
from app.rooms import RoomManager

room_manager = RoomManager()
