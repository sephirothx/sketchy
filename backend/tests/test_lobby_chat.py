"""The lobby's chat backlog: numbered, bounded, and filtered per arrival."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.services.lobby_chat import LOBBY_CHAT_BACKLOG, LobbyChatLog

NOON = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)


def say(log: LobbyChatLog, author: str, text: str, **overrides):
    fields = {
        "user_id": author,
        "display_name": author.title(),
        "name_color": None,
        "is_anonymous": False,
        "text": text,
        "sent_at": NOON,
    }
    fields.update(overrides)
    return log.append(**fields)


def test_lines_are_numbered_in_the_order_they_were_said():
    log = LobbyChatLog()
    assert log.last_seq == 0
    first = say(log, "ada", "hello")
    second = say(log, "bob", "hi")
    assert (first.seq, second.seq) == (1, 2)
    assert log.last_seq == 2
    assert [line.seq for line in log.backlog_for()] == [1, 2]


def test_the_backlog_keeps_only_the_most_recent_lines():
    log = LobbyChatLog()
    for index in range(LOBBY_CHAT_BACKLOG + 10):
        say(log, "ada", f"line {index}")
    held = log.backlog_for()
    assert len(held) == LOBBY_CHAT_BACKLOG
    assert held[0].seq == 11
    assert held[-1].seq == LOBBY_CHAT_BACKLOG + 10
    # Numbers already spent stay spent: the count is of lines said, not held.
    assert log.last_seq == LOBBY_CHAT_BACKLOG + 10


def test_an_arrival_is_not_shown_the_authors_they_blocked():
    log = LobbyChatLog()
    say(log, "ada", "one")
    say(log, "bob", "two")
    say(log, "ada", "three")
    assert [line.text for line in log.backlog_for(hidden_authors={"ada"})] == ["two"]
    assert [line.text for line in log.backlog_for(hidden_authors={"nobody"})] == [
        "one",
        "two",
        "three",
    ]
    assert log.authors() == {"ada", "bob"}


def test_an_ended_account_takes_its_lines_with_it():
    log = LobbyChatLog()
    say(log, "ada", "one")
    say(log, "bob", "two")
    say(log, "ada", "three")
    log.drop_author("ada")
    assert [line.text for line in log.backlog_for()] == ["two"]
    assert log.authors() == {"bob"}
    # The next line is numbered after the ones that were dropped, so a client
    # holding them still sees it as new.
    assert say(log, "bob", "four").seq == 4


def test_the_wire_shape_names_the_account_and_the_instant():
    log = LobbyChatLog()
    line = say(log, "ada", "hello", name_color="#4f9", retained_message_id="0192-abc")
    assert line.payload() == {
        "seq": 1,
        "userId": "ada",
        "displayName": "Ada",
        "nameColor": "#4f9",
        "isAnonymous": False,
        "text": "hello",
        "sentAt": "2026-09-02T12:00:00+00:00",
        "retainedMessageId": "0192-abc",
    }


def test_an_unretained_line_carries_no_identifier_to_cite():
    """The absence is the signal, exactly as room chat says it (R-MOD-08a)."""
    log = LobbyChatLog()
    payload = say(log, "ada", "hello").payload()
    assert "retainedMessageId" not in payload


def test_a_naive_instant_is_refused_rather_than_guessed_at():
    log = LobbyChatLog()
    with pytest.raises(ValueError):
        say(log, "ada", "hello", sent_at=NOON.replace(tzinfo=None))
    assert log.last_seq == 0


def test_a_smaller_ring_is_honoured():
    log = LobbyChatLog(backlog=2)
    for index in range(3):
        say(log, "ada", str(index), sent_at=NOON + timedelta(seconds=index))
    assert [line.text for line in log.backlog_for()] == ["1", "2"]


# --- the backlog across a restart -------------------------------------------

from uuid import UUID, uuid4  # noqa: E402

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.db.models import Base, RoomMessage, User, UserBan  # noqa: E402
from app.services.lobby_chat import recent_lobby_lines, restore_lobby_backlog  # noqa: E402


def retained(author: UUID, text: str, *, at: datetime, audience="lobby", expired=False):
    return RoomMessage(
        id=uuid4(),
        room_instance_id=None if audience == "lobby" else uuid4(),
        sender_user_id=author,
        sender_player_id=None if audience == "lobby" else uuid4(),
        sender_display_name_snapshot="Someone",
        sender_name_color_snapshot="#4f9",
        sender_is_anonymous_snapshot=False,
        is_spectator=False,
        message_kind="chat",
        audience=audience,
        audience_user_ids=[] if audience == "lobby" else [str(author)],
        text=text,
        # An expired row was said forty days ago and lapsed ten days ago; the
        # schema refuses one that expires before it was said.
        created_at=at - timedelta(days=40) if expired else at,
        expires_at=at - timedelta(days=10) if expired else at + timedelta(days=30),
    )


async def _database():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


@pytest.mark.asyncio
async def test_a_restart_hands_the_next_arrival_what_was_said_before_it():
    """The ring is memory, but the lines were retained: the most recent
    fifty come back, oldest first, minus what expired, what was said in a
    room, and what a suspended account said."""
    engine, factory = await _database()
    ada, bob, banned = UUID(int=1), UUID(int=2), UUID(int=3)
    try:
        async with factory() as session:
            async with session.begin():
                session.add_all(
                    [
                        User(id=ada, display_name="Ada"),
                        User(id=bob, display_name="Bob"),
                        User(id=banned, display_name="Banned"),
                        UserBan(id=uuid4(), user_id=banned, reason="spam", is_active=True),
                    ]
                )
            async with session.begin():
                session.add_all(
                    [retained(ada, f"line {i}", at=NOON + timedelta(minutes=i)) for i in range(60)]
                    + [
                        retained(bob, "expired", at=NOON + timedelta(hours=2), expired=True),
                        retained(bob, "in a room", at=NOON + timedelta(hours=2), audience="room"),
                        retained(banned, "still suspended", at=NOON + timedelta(hours=2)),
                    ]
                )

        log = LobbyChatLog()
        assert await restore_lobby_backlog(log, factory) == LOBBY_CHAT_BACKLOG

        held = log.backlog_for()
        assert [line.text for line in held] == [f"line {i}" for i in range(10, 60)]
        assert [line.seq for line in held] == list(range(1, LOBBY_CHAT_BACKLOG + 1))
        assert held[0].user_id == str(ada)
        assert held[0].sent_at == NOON + timedelta(minutes=10)
        # Every restored line can still be cited: it is the retained row.
        async with factory() as session:
            rows = await recent_lobby_lines(session)
        assert [line.retained_message_id for line in held] == [str(row.id) for row in rows]
        # And the next line said follows on from them.
        assert say(log, "carol", "after the restart").seq == LOBBY_CHAT_BACKLOG + 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_a_database_that_does_not_answer_leaves_the_backlog_empty():
    """A deploy must not wait on the chat backlog."""

    class Hanging:
        def __call__(self):
            return self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def scalars(self, *_args, **_kwargs):
            await asyncio.sleep(3600)

    log = LobbyChatLog()
    assert await restore_lobby_backlog(log, Hanging(), bound_seconds=0.01) == 0
    assert log.backlog_for() == [] and log.last_seq == 0
    assert await restore_lobby_backlog(log, None) == 0


def test_the_backlog_is_restored_only_before_anything_was_said():
    log = LobbyChatLog()
    say(log, "ada", "already said")
    with pytest.raises(RuntimeError):
        log.restore([])
