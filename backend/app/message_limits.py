"""Shared backend limits for player-authored text: chat, guesses and report details."""

MAX_CHAT_MESSAGE_LENGTH = 500

# The words a reporter may add beside a report, on every route: a seat reported
# from a room (socket), a lobby line, a name or picture (`POST /api/reports`),
# a Gallery drawing, and prompt content. One number because it is one dialog:
# the room's socket report used to stop at 1000 while REST took 2000, so the
# same complaint fitted or not depending on where it was typed. 2000 is the
# larger of the two, so nothing that was accepted before is refused now.
MAX_REPORT_DETAILS = 2_000
