"""a supporter's two-tone name

Revision ID: 7a9b0c1d2e3f
Revises: 8b0c1d2e3f4a
Create Date: 2026-11-02 23:00:00.000000

`users.name_style` is a key from a closed list, beside `name_color` rather than
in it (#1476). Null for everybody today, so the check has nothing to find. On
SQLite the check rides the new column: a batch rebuild of `users` would lose its
expression indexes, which reflection cannot see.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "7a9b0c1d2e3f"
down_revision: str | Sequence[str] | None = "8b0c1d2e3f4a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK = "name_style IN ('sunset', 'ocean', 'aurora', 'ember', 'berry', 'meadow')"


def upgrade() -> None:
    if op.get_context().dialect.name == "postgresql":
        op.add_column("users", sa.Column("name_style", sa.String(16), nullable=True))
        op.create_check_constraint(
            "ck_users_name_style", "users", _CHECK, postgresql_not_valid=True
        )
        op.execute("ALTER TABLE users VALIDATE CONSTRAINT ck_users_name_style")
    else:
        op.execute(
            "ALTER TABLE users ADD COLUMN name_style VARCHAR(16) "
            f"CONSTRAINT ck_users_name_style CHECK ({_CHECK})"
        )


def downgrade() -> None:
    if op.get_context().dialect.name == "postgresql":
        op.drop_constraint("ck_users_name_style", "users", type_="check")
    op.drop_column("users", "name_style")
