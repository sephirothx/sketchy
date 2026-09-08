"""shorten what a stolen session is worth, and make a staff role prove itself

Revision ID: a7b8c9d0e1f2
Revises: e6f7a8b9c0d1
Create Date: 2026-09-08 14:00:00.000000

The 2026-08-27 audit's PR-17 (#468) in one revision.

`auth_sessions` gains what the shortened lifetimes and the anomaly signals
need. The lifetimes themselves are not columns: the absolute bound is clamped
at resolution against the account's current role, so promoting somebody to
moderator shortens the sessions they already hold, and the idle bound is
measured from `last_used_at`, which was already maintained. What has to be
stored is the address a session was issued to and the one it was last used
from - both keyed hashes, never addresses (R-PRIV-09) - so "this session has
moved" is answerable, plus when that last happened and how often, and when
this device last proved a second factor.

`user_second_factors` and `user_recovery_codes` hold the TOTP secret a staff
account must produce (R-AUTH-20) and the single-use codes that replace it when
the authenticator is gone. `auth_login_lockouts` remembers consecutive login
failures across rate-limit windows, which a fixed window cannot: backing off
means the tenth failure costs more than the second, and a window that rolls
every five minutes forgets both.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "a7b8c9d0e1f2"
down_revision: str | Sequence[str] | None = "e6f7a8b9c0d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Batch mode for SQLite's benefit: it rebuilds the table, which is the
    # only way it can add a CHECK constraint to one that already exists.
    with op.batch_alter_table("auth_sessions") as batch:
        batch.add_column(sa.Column("ip_hash", sa.String(length=64), nullable=True))
        batch.add_column(
            sa.Column("last_ip_hash", sa.String(length=64), nullable=True)
        )
        batch.add_column(
            sa.Column("anomaly_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.add_column(
            sa.Column(
                "anomaly_count",
                sa.Integer(),
                server_default=sa.text("0"),
                nullable=False,
            )
        )
        batch.add_column(
            sa.Column("stepped_up_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.create_check_constraint("ck_auth_sessions_anomaly_count", "anomaly_count >= 0")
        batch.create_check_constraint(
            "ck_auth_sessions_anomaly_pair",
            "(anomaly_at IS NULL) = (anomaly_count = 0)",
        )

    op.create_table(
        "user_second_factors",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("secret", sa.String(length=64), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_step", sa.BigInteger(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "failed_attempts",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "failed_attempts >= 0", name="ck_user_second_factors_failed_attempts"
        ),
        sa.CheckConstraint("last_step >= 0", name="ck_user_second_factors_last_step"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )

    op.create_table(
        "user_recovery_codes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "code_hash", name="uq_user_recovery_codes_code"),
    )
    op.create_index(
        "ix_user_recovery_codes_user",
        "user_recovery_codes",
        ["user_id", "used_at"],
        unique=False,
    )

    op.create_table(
        "auth_login_lockouts",
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "consecutive_failures >= 0", name="ck_auth_login_lockouts_failures"
        ),
        sa.PrimaryKeyConstraint("key_hash"),
    )
    op.create_index(
        "ix_auth_login_lockouts_locked_until",
        "auth_login_lockouts",
        ["locked_until"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_auth_login_lockouts_locked_until", table_name="auth_login_lockouts"
    )
    op.drop_table("auth_login_lockouts")
    op.drop_index("ix_user_recovery_codes_user", table_name="user_recovery_codes")
    op.drop_table("user_recovery_codes")
    op.drop_table("user_second_factors")
    with op.batch_alter_table("auth_sessions") as batch:
        batch.drop_constraint("ck_auth_sessions_anomaly_pair", type_="check")
        batch.drop_constraint("ck_auth_sessions_anomaly_count", type_="check")
        batch.drop_column("stepped_up_at")
        batch.drop_column("anomaly_count")
        batch.drop_column("anomaly_at")
        batch.drop_column("last_ip_hash")
        batch.drop_column("ip_hash")
