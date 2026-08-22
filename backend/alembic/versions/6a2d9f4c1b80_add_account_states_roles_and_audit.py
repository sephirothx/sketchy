"""add account states roles and audit

Revision ID: 6a2d9f4c1b80
Revises: 5f1c7a3d8e24
Create Date: 2026-08-22 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "6a2d9f4c1b80"
down_revision: Union[str, Sequence[str], None] = "5f1c7a3d8e24"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Replace the guest flag with lifecycle state and add roles/auditing."""
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column(
                "state",
                sa.String(length=16),
                server_default="anonymous",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "role",
                sa.String(length=16),
                server_default="user",
                nullable=False,
            )
        )

    op.execute(
        "UPDATE users SET state = CASE "
        "WHEN is_anonymous THEN 'anonymous' ELSE 'registered' END"
    )

    with op.batch_alter_table("users") as batch_op:
        batch_op.create_check_constraint(
            "ck_users_state",
            "state IN ('anonymous', 'registered', 'merged', 'deleted')",
        )
        batch_op.create_check_constraint(
            "ck_users_role", "role IN ('user', 'moderator', 'admin')"
        )
        batch_op.drop_column("is_anonymous")

    # SQLite cannot reflect expression indexes while rebuilding a table, so
    # the batch operations above cannot preserve this hand-written index.
    if op.get_bind().dialect.name == "sqlite":
        op.create_index(
            "ix_users_username_lower",
            "users",
            [sa.text("lower(username)")],
            unique=True,
            sqlite_where=sa.text("username IS NOT NULL"),
        )

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(native_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(native_uuid=True), nullable=True),
        sa.Column("target_user_id", sa.Uuid(native_uuid=True), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("ip_hash", sa.String(length=64), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["target_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_audit_events_actor_user_id"),
        "audit_events",
        ["actor_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_audit_events_event_type"),
        "audit_events",
        ["event_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_audit_events_target_user_id"),
        "audit_events",
        ["target_user_id"],
        unique=False,
    )


def downgrade() -> None:
    """Restore the legacy guest flag and remove roles/auditing."""
    op.drop_index(op.f("ix_audit_events_target_user_id"), table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_event_type"), table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_actor_user_id"), table_name="audit_events")
    op.drop_table("audit_events")

    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_anonymous",
                sa.Boolean(),
                server_default=sa.true(),
                nullable=False,
            )
        )
    op.execute("UPDATE users SET is_anonymous = (state = 'anonymous')")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("ck_users_role", type_="check")
        batch_op.drop_constraint("ck_users_state", type_="check")
        batch_op.drop_column("role")
        batch_op.drop_column("state")
    if op.get_bind().dialect.name == "sqlite":
        op.create_index(
            "ix_users_username_lower",
            "users",
            [sa.text("lower(username)")],
            unique=True,
            sqlite_where=sa.text("username IS NOT NULL"),
        )
