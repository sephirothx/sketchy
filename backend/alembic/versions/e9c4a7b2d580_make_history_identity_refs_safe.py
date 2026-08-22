"""make history identity refs safe

Revision ID: e9c4a7b2d580
Revises: d8b3f6a1c470
Create Date: 2026-08-22 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e9c4a7b2d580"
down_revision: Union[str, Sequence[str], None] = "d8b3f6a1c470"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NAMING_CONVENTION = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"
}


def _existing_user_fk(table_name: str, column_name: str) -> str:
    for foreign_key in sa.inspect(op.get_bind()).get_foreign_keys(table_name):
        if foreign_key["constrained_columns"] == [column_name]:
            return foreign_key["name"] or f"fk_{table_name}_{column_name}_users"
    raise RuntimeError(f"Missing {table_name}.{column_name} foreign key")


def _add_snapshot_columns() -> None:
    op.add_column(
        "game_participants",
        sa.Column("display_name_snapshot", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "game_participants",
        sa.Column("name_color_snapshot", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "game_participants",
        sa.Column("is_anonymous_snapshot", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "turn_records",
        sa.Column("drawer_display_name_snapshot", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "turn_records",
        sa.Column("drawer_name_color_snapshot", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "turn_records",
        sa.Column("drawer_is_anonymous_snapshot", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "turn_guesses",
        sa.Column("display_name_snapshot", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "turn_guesses",
        sa.Column("name_color_snapshot", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "turn_guesses",
        sa.Column("is_anonymous_snapshot", sa.Boolean(), nullable=True),
    )


def _backfill_snapshots() -> None:
    op.execute(
        "UPDATE game_participants SET "
        "display_name_snapshot = (SELECT display_name FROM users WHERE users.id = game_participants.user_id), "
        "name_color_snapshot = (SELECT name_color FROM users WHERE users.id = game_participants.user_id), "
        "is_anonymous_snapshot = (SELECT CASE WHEN state = 'anonymous' THEN TRUE ELSE FALSE END FROM users WHERE users.id = game_participants.user_id)"
    )
    op.execute(
        "UPDATE turn_records SET "
        "drawer_display_name_snapshot = (SELECT display_name FROM users WHERE users.id = turn_records.drawer_user_id), "
        "drawer_name_color_snapshot = (SELECT name_color FROM users WHERE users.id = turn_records.drawer_user_id), "
        "drawer_is_anonymous_snapshot = (SELECT CASE WHEN state = 'anonymous' THEN TRUE ELSE FALSE END FROM users WHERE users.id = turn_records.drawer_user_id)"
    )
    op.execute(
        "UPDATE turn_guesses SET "
        "display_name_snapshot = (SELECT display_name FROM users WHERE users.id = turn_guesses.user_id), "
        "name_color_snapshot = (SELECT name_color FROM users WHERE users.id = turn_guesses.user_id), "
        "is_anonymous_snapshot = (SELECT CASE WHEN state = 'anonymous' THEN TRUE ELSE FALSE END FROM users WHERE users.id = turn_guesses.user_id)"
    )


def _make_safe_reference(
    table_name: str,
    column_name: str,
    snapshot_columns: tuple[tuple[str, sa.types.TypeEngine, bool], ...],
) -> None:
    old_fk_name = _existing_user_fk(table_name, column_name)
    with op.batch_alter_table(
        table_name, naming_convention=NAMING_CONVENTION
    ) as batch_op:
        batch_op.drop_constraint(old_fk_name, type_="foreignkey")
        batch_op.alter_column(
            column_name,
            existing_type=sa.Uuid(native_uuid=True),
            nullable=True,
        )
        for snapshot_name, snapshot_type, nullable in snapshot_columns:
            batch_op.alter_column(
                snapshot_name, existing_type=snapshot_type, nullable=nullable
            )
        batch_op.create_foreign_key(
            f"fk_{table_name}_{column_name}_users_set_null",
            "users",
            [column_name],
            ["id"],
            ondelete="SET NULL",
        )


def upgrade() -> None:
    """Freeze presentation and prevent account removal from cascading history."""
    _add_snapshot_columns()
    _backfill_snapshots()
    _make_safe_reference(
        "game_participants",
        "user_id",
        (
            ("display_name_snapshot", sa.String(length=32), False),
            ("name_color_snapshot", sa.String(length=16), True),
            ("is_anonymous_snapshot", sa.Boolean(), False),
        ),
    )
    _make_safe_reference(
        "turn_records",
        "drawer_user_id",
        (
            ("drawer_display_name_snapshot", sa.String(length=32), False),
            ("drawer_name_color_snapshot", sa.String(length=16), True),
            ("drawer_is_anonymous_snapshot", sa.Boolean(), False),
        ),
    )
    _make_safe_reference(
        "turn_guesses",
        "user_id",
        (
            ("display_name_snapshot", sa.String(length=32), False),
            ("name_color_snapshot", sa.String(length=16), True),
            ("is_anonymous_snapshot", sa.Boolean(), False),
        ),
    )


def _restore_cascade_reference(
    table_name: str,
    column_name: str,
    snapshot_columns: tuple[str, ...],
) -> None:
    with op.batch_alter_table(
        table_name, naming_convention=NAMING_CONVENTION
    ) as batch_op:
        batch_op.drop_constraint(
            f"fk_{table_name}_{column_name}_users_set_null", type_="foreignkey"
        )
        batch_op.alter_column(
            column_name,
            existing_type=sa.Uuid(native_uuid=True),
            nullable=False,
        )
        batch_op.create_foreign_key(
            f"fk_{table_name}_{column_name}_users",
            "users",
            [column_name],
            ["id"],
            ondelete="CASCADE",
        )
        for snapshot_name in snapshot_columns:
            batch_op.drop_column(snapshot_name)


def downgrade() -> None:
    """Restore cascade references; requires no identity-null history rows."""
    _restore_cascade_reference(
        "turn_guesses",
        "user_id",
        ("is_anonymous_snapshot", "name_color_snapshot", "display_name_snapshot"),
    )
    _restore_cascade_reference(
        "turn_records",
        "drawer_user_id",
        (
            "drawer_is_anonymous_snapshot",
            "drawer_name_color_snapshot",
            "drawer_display_name_snapshot",
        ),
    )
    _restore_cascade_reference(
        "game_participants",
        "user_id",
        ("is_anonymous_snapshot", "name_color_snapshot", "display_name_snapshot"),
    )
