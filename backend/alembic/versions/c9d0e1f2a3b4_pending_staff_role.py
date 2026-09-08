"""offer a staff role and wait for the second factor before it takes effect

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-09-08 21:00:00.000000

A staff role could only be granted to somebody who had already enrolled a
second factor, because granting it revokes the account's sessions and a staff
account cannot sign back in without a code. That is a true constraint, but it
was pointed the wrong way: it made every promotion start with an administrator
telling a player out of band to go and find a setting, and it put that setting
in front of every player who would never need it.

`users.pending_role` turns the order around. The grant records an offer, the
account stays exactly what it was, and enrolling the second factor is what
moves the value into `role` - so the sessions are revoked at the moment the
role actually begins, and there is no window in which a staff account exists
without a factor.

`role_change_notices.pending` distinguishes the two things an account can be
told: that it holds a role, and that one is waiting for it. The second asks
something of the reader, so it cannot be phrased as the first.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "c9d0e1f2a3b4"
down_revision: str | Sequence[str] | None = "b8c9d0e1f2a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _users_expression_indexes() -> None:
    """Restore what a SQLite table rebuild takes with it.

    `batch_alter_table` copies the table to add a CHECK, and copies back only
    the indexes it can reflect - which on SQLite is every index except these
    two, for the reason the baseline states: the dialect cannot reflect an
    expression index. Without this the case-insensitive uniqueness of a
    username survives the migration on PostgreSQL and quietly does not on
    SQLite. Definitions copied from `f0a1b2c3d4e5`, which is where they are
    pinned.
    """
    op.create_index(
        "ix_users_username_lower",
        "users",
        [sa.text("lower(username)")],
        unique=True,
        postgresql_where=sa.text("username IS NOT NULL"),
        sqlite_where=sa.text("username IS NOT NULL"),
    )
    op.create_index(
        "ix_users_email_lower",
        "users",
        [sa.text("lower(email)")],
        unique=True,
        postgresql_where=sa.text("email IS NOT NULL"),
        sqlite_where=sa.text("email IS NOT NULL"),
    )


def _rebuilds_the_table() -> bool:
    """Whether this dialect answers a new CHECK by copying the table."""
    return op.get_bind().dialect.name == "sqlite"


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("pending_role", sa.String(16), nullable=True))
        batch.add_column(
            sa.Column("pending_role_at", sa.DateTime(timezone=True), nullable=True)
        )
        # A moderator role and nothing else. `user` is not a staff role, so
        # there is nothing for an account to wait for; `admin` is not granted
        # over the network at all, so it cannot be offered over it either.
        # Spelled out rather than derived from `app.domain_values`, because a
        # migration says what a database was asked for on the day it ran and
        # must not change meaning when a constant does.
        batch.create_check_constraint(
            "ck_users_pending_role",
            "pending_role IS NULL OR pending_role IN ('moderator')",
        )
        batch.create_check_constraint(
            "ck_users_pending_role_dated",
            "(pending_role IS NULL) = (pending_role_at IS NULL)",
        )
    if _rebuilds_the_table():
        _users_expression_indexes()

    op.add_column(
        "role_change_notices",
        sa.Column(
            "pending",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("role_change_notices", "pending")
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("ck_users_pending_role_dated", type_="check")
        batch.drop_constraint("ck_users_pending_role", type_="check")
        batch.drop_column("pending_role_at")
        batch.drop_column("pending_role")
    if _rebuilds_the_table():
        _users_expression_indexes()
