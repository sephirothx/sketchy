"""give a lost account a way back in

Revision ID: b2e9f60c8a45
Revises: a1c7e4b9d360
Create Date: 2026-08-24 12:40:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "b2e9f60c8a45"
down_revision: str | Sequence[str] | None = "a1c7e4b9d360"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PURPOSES = "'password_reset', 'email_verify'"
OUTBOX_STATES = "'pending', 'sent', 'failed'"
TEMPLATES = (
    "'verify_email', 'reset_password', 'password_changed', "
    "'account_banned', 'content_hidden'"
)


def upgrade() -> None:
    op.create_table(
        "auth_tokens",
        sa.Column("token_hash", sa.String(length=64), primary_key=True),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True, native_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requested_ip_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"purpose IN ({PURPOSES})", name="ck_auth_tokens_purpose"
        ),
        sa.CheckConstraint(
            "purpose <> 'email_verify' OR email IS NOT NULL",
            name="ck_auth_tokens_verify_address",
        ),
    )
    op.create_index(
        "ix_auth_tokens_user_purpose", "auth_tokens", ["user_id", "purpose"]
    )
    op.create_index("ix_auth_tokens_expires_at", "auth_tokens", ["expires_at"])

    op.create_table(
        "email_outbox",
        sa.Column(
            "id", sa.Uuid(as_uuid=True, native_uuid=True), primary_key=True
        ),
        sa.Column("to_address", sa.String(length=255), nullable=False),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True, native_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("template", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column(
            "attempts", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("last_error", sa.String(length=256), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            f"state IN ({OUTBOX_STATES})", name="ck_email_outbox_state"
        ),
        sa.CheckConstraint(
            f"template IN ({TEMPLATES})", name="ck_email_outbox_template"
        ),
        sa.CheckConstraint(
            "(state = 'sent') = (sent_at IS NOT NULL)",
            name="ck_email_outbox_sent_at",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_email_outbox_attempts"),
    )
    op.create_index("ix_email_outbox_user_id", "email_outbox", ["user_id"])
    op.create_index(
        "ix_email_outbox_ready", "email_outbox", ["state", "next_attempt_at"]
    )

    with op.batch_alter_table("user_settings") as batch:
        batch.add_column(
            sa.Column(
                "email_reminder_last_shown_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("user_settings") as batch:
        batch.drop_column("email_reminder_last_shown_at")
    op.drop_index("ix_email_outbox_ready", table_name="email_outbox")
    op.drop_index("ix_email_outbox_user_id", table_name="email_outbox")
    op.drop_table("email_outbox")
    op.drop_index("ix_auth_tokens_expires_at", table_name="auth_tokens")
    op.drop_index("ix_auth_tokens_user_purpose", table_name="auth_tokens")
    op.drop_table("auth_tokens")
