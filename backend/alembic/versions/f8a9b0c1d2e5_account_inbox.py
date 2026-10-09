"""account inbox: one table for every notice, warnings kept with the account

Revision ID: f8a9b0c1d2e5
Revises: e7f8a9b0c1d4
Create Date: 2026-10-09 00:00:00.000000

Everything the app tells a player about their own account lands in one inbox
(#1436): `inbox_entries`, one row per message, naming the fact it is about.
It replaces the three per-kind stores that each did half of this -
`role_change_notices`, `drawing_share_notices`, and the "told yet?" columns
`player_reports.reporter_notified_at` and `friendships.acceptance_announced_at`
- which are dropped. `user_warnings` stays, as moderation history, but is now
deleted with its account (`CASCADE`, `user_id` required) instead of orphaned.

Nothing is deployed, so nothing is carried across: no notice is turned into
an inbox entry, and warnings already orphaned are deleted.

Going back recreates the dropped tables, columns and index empty, and puts
`user_warnings.user_id` back to nullable with `SET NULL`.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "f8a9b0c1d2e5"
down_revision: str | Sequence[str] | None = "e7f8a9b0c1d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = sa.Uuid(as_uuid=True, native_uuid=True)
_JSON = sa.JSON(none_as_null=True).with_variant(
    postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), "postgresql"
)
_KINDS = (
    "kind IN ('warning', 'drawing_shared', 'friend_request', 'friend_accepted',"
    " 'game_invite', 'reports_reviewed', 'role')"
)
_UNREAD = "read_at IS NULL"
_SUBJECT = "subject_id IS NOT NULL"
_UNANNOUNCED = "reporter_notified_at IS NULL AND status <> 'pending'"
_WARNING_FK = "fk_user_warnings_user_id_users"


def _warning_owner(ondelete: str, nullable: bool) -> None:
    """Point `user_warnings.user_id` at its account with `ondelete`.

    The baseline left the constraint unnamed, which PostgreSQL calls
    `user_warnings_user_id_fkey` and SQLite does not name at all, so batch mode
    is handed a convention to find it by.
    """
    postgres = op.get_bind().dialect.name == "postgresql"
    with op.batch_alter_table(
        "user_warnings",
        naming_convention={"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"},
    ) as batch:
        if postgres and ondelete == "CASCADE":
            batch.drop_constraint("user_warnings_user_id_fkey", type_="foreignkey")
        else:
            batch.drop_constraint(_WARNING_FK, type_="foreignkey")
        batch.alter_column("user_id", existing_type=_UUID, nullable=nullable)
        batch.create_foreign_key(_WARNING_FK, "users", ["user_id"], ["id"], ondelete=ondelete)


def upgrade() -> None:
    op.create_table(
        "inbox_entries",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "user_id", _UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("subject_id", _UUID, nullable=True),
        sa.Column("params", _JSON, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(_KINDS, name="ck_inbox_entries_kind"),
    )
    op.create_index(
        "ix_inbox_entries_user_created", "inbox_entries", ["user_id", "created_at"]
    )
    op.create_index("ix_inbox_entries_created_at", "inbox_entries", ["created_at"])
    op.create_index(
        "ix_inbox_entries_user_unread",
        "inbox_entries",
        ["user_id"],
        postgresql_where=sa.text(_UNREAD),
        sqlite_where=sa.text(_UNREAD),
    )
    op.create_index(
        "uq_inbox_entries_subject",
        "inbox_entries",
        ["user_id", "kind", "subject_id"],
        unique=True,
        postgresql_where=sa.text(_SUBJECT),
        sqlite_where=sa.text(_SUBJECT),
    )

    op.drop_index(
        "ix_drawing_share_notices_user_pending", table_name="drawing_share_notices"
    )
    op.drop_table("drawing_share_notices")
    op.drop_index(
        "ix_role_change_notices_user_pending", table_name="role_change_notices"
    )
    op.drop_table("role_change_notices")

    op.drop_index("ix_player_reports_reporter_unannounced", table_name="player_reports")
    with op.batch_alter_table("player_reports") as batch:
        batch.drop_column("reporter_notified_at")
    with op.batch_alter_table("friendships") as batch:
        batch.drop_column("acceptance_announced_at")

    op.execute("DELETE FROM user_warnings WHERE user_id IS NULL")
    _warning_owner("CASCADE", nullable=False)


def downgrade() -> None:
    _warning_owner("SET NULL", nullable=True)

    with op.batch_alter_table("friendships") as batch:
        batch.add_column(
            sa.Column("acceptance_announced_at", sa.DateTime(timezone=True), nullable=True)
        )
    with op.batch_alter_table("player_reports") as batch:
        batch.add_column(
            sa.Column("reporter_notified_at", sa.DateTime(timezone=True), nullable=True)
        )
    op.create_index(
        "ix_player_reports_reporter_unannounced",
        "player_reports",
        ["reporter_user_id"],
        postgresql_where=sa.text(_UNANNOUNCED),
        sqlite_where=sa.text(_UNANNOUNCED),
    )

    op.create_table(
        "role_change_notices",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "user_id", _UUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("pending", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("role IN ('user', 'moderator')", name="ck_role_change_notices_role"),
    )
    op.create_index(
        "ix_role_change_notices_user_pending",
        "role_change_notices",
        ["user_id", "acknowledged_at"],
    )
    op.create_table(
        "drawing_share_notices",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "user_id", _UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("game_id", _UUID, nullable=False),
        sa.Column("turn_id", _UUID, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["game_id", "turn_id"],
            ["turn_records.game_id", "turn_records.id"],
            name="fk_drawing_share_notices_turn_same_game",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("turn_id", name="uq_drawing_share_notices_turn_id"),
    )
    op.create_index(
        "ix_drawing_share_notices_user_pending",
        "drawing_share_notices",
        ["user_id", "acknowledged_at"],
    )

    op.drop_index("uq_inbox_entries_subject", table_name="inbox_entries")
    op.drop_index("ix_inbox_entries_user_unread", table_name="inbox_entries")
    op.drop_index("ix_inbox_entries_created_at", table_name="inbox_entries")
    op.drop_index("ix_inbox_entries_user_created", table_name="inbox_entries")
    op.drop_table("inbox_entries")
