"""retain lobby chat in room_messages

A line said in the lobby has no room and no seat, so the two columns that
named them become nullable, and a CHECK says that a null scope *is* a lobby
line and nothing else - never a room line that lost its room. The audience
value set gains `lobby` on the retained rows and on the evidence copies a
report pins, because the copy carries the audience across and a report about
the lobby would otherwise fail at the insert.

Revision ID: x7e1c5a9b036
Revises: w6d0b4f8a925
Create Date: 2026-09-02 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "x7e1c5a9b036"
down_revision: str | Sequence[str] | None = "w6d0b4f8a925"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = sa.Uuid()
AUDIENCES_BEFORE = "'room', 'prompt_aware'"
AUDIENCES_AFTER = "'room', 'prompt_aware', 'lobby'"
LOBBY_HAS_NO_SCOPE = (
    "(audience = 'lobby' AND room_instance_id IS NULL"
    " AND sender_player_id IS NULL)"
    " OR (audience <> 'lobby' AND room_instance_id IS NOT NULL"
    " AND sender_player_id IS NOT NULL)"
)
LOBBY_IS_CHAT = "audience <> 'lobby' OR message_kind = 'chat'"


def upgrade() -> None:
    with op.batch_alter_table("room_messages") as batch_op:
        batch_op.alter_column("room_instance_id", existing_type=_UUID, nullable=True)
        batch_op.alter_column("sender_player_id", existing_type=_UUID, nullable=True)
        batch_op.drop_constraint("ck_room_messages_audience", type_="check")
        batch_op.create_check_constraint(
            "ck_room_messages_audience", f"audience IN ({AUDIENCES_AFTER})"
        )
        batch_op.create_check_constraint(
            "ck_room_messages_lobby_has_no_scope", LOBBY_HAS_NO_SCOPE
        )
        batch_op.create_check_constraint(
            "ck_room_messages_lobby_is_chat", LOBBY_IS_CHAT
        )

    with op.batch_alter_table("player_report_message_evidence") as batch_op:
        batch_op.drop_constraint("ck_report_message_evidence_audience", type_="check")
        batch_op.create_check_constraint(
            "ck_report_message_evidence_audience",
            f"audience IN ({AUDIENCES_AFTER})",
        )


def downgrade() -> None:
    bind = op.get_bind()
    # Retained lobby lines cannot satisfy NOT NULL again, and they are the
    # short-lived kind - thirty days, kept for a report that may never come -
    # so the downgrade lets them go. Evidence a report already pinned is a
    # moderator's record of why they decided something, and this migration
    # does not get to decide that; a database holding some is refused.
    pinned = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM player_report_message_evidence "
            "WHERE audience = 'lobby'"
        )
    ).scalar()
    if pinned:
        raise RuntimeError(
            f"cannot downgrade: {pinned} pinned report evidence rows cite lobby "
            "chat, which the previous schema cannot hold. Resolve or purge those "
            "reports first."
        )
    bind.execute(sa.text("DELETE FROM room_messages WHERE audience = 'lobby'"))

    with op.batch_alter_table("player_report_message_evidence") as batch_op:
        batch_op.drop_constraint("ck_report_message_evidence_audience", type_="check")
        batch_op.create_check_constraint(
            "ck_report_message_evidence_audience",
            f"audience IN ({AUDIENCES_BEFORE})",
        )

    with op.batch_alter_table("room_messages") as batch_op:
        batch_op.drop_constraint("ck_room_messages_lobby_is_chat", type_="check")
        batch_op.drop_constraint("ck_room_messages_lobby_has_no_scope", type_="check")
        batch_op.drop_constraint("ck_room_messages_audience", type_="check")
        batch_op.create_check_constraint(
            "ck_room_messages_audience", f"audience IN ({AUDIENCES_BEFORE})"
        )
        batch_op.alter_column("sender_player_id", existing_type=_UUID, nullable=False)
        batch_op.alter_column("room_instance_id", existing_type=_UUID, nullable=False)
