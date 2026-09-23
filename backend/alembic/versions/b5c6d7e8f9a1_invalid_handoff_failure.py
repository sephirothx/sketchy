"""a finished game the writer refuses fails as `invalid`, not as a slow database

Revision ID: b5c6d7e8f9a1
Revises: d7e8f9a0b1c2
Create Date: 2026-09-23 09:00:00.000000

The handoff loop retried every failure of `save_game` other than a conflict on
the transient schedule - two hours of backoff - and then failed the row as
`exhausted`. A ledger that does not reconcile refuses the same way on every
attempt, so the code the row ended with said "the database was slow" about a
game whose content the writer would never accept (#992). `invalid` names that
on first sight. Widening the check is safe at any time; nothing running writes
the new value before this revision, and the wider check accepts every row
already there.

The shape is the one `tests/test_online_ddl.py` asks for; as in d7e8f9a0b1c2,
it buys nothing until the runner commits between statements (#969).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "b5c6d7e8f9a1"
down_revision: str | Sequence[str] | None = "d7e8f9a0b1c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "finished_game_envelopes"
_NAME = "ck_finished_game_envelopes_failure"
_BEFORE = ("conflict", "exhausted", "unreadable")
_AFTER = _BEFORE + ("invalid",)


def _check(values: tuple[str, ...]) -> str:
    return "failure_code IN (" + ", ".join(repr(value) for value in values) + ")"


def _replace(values: tuple[str, ...]) -> None:
    if op.get_context().dialect.name == "postgresql":
        op.drop_constraint(_NAME, _TABLE, type_="check")
        op.create_check_constraint(_NAME, _TABLE, _check(values), postgresql_not_valid=True)
        op.execute(f"ALTER TABLE {_TABLE} VALIDATE CONSTRAINT {_NAME}")
    else:
        with op.batch_alter_table(_TABLE) as batch:
            batch.drop_constraint(_NAME, type_="check")
            # online-ddl: SQLite rebuilds the table in batch mode; it has no NOT VALID and holds no live deployment
            batch.create_check_constraint(_NAME, _check(values))


def upgrade() -> None:
    _replace(_AFTER)


def downgrade() -> None:
    # A row that failed as `invalid` would refuse the narrower check; going
    # back re-labels it as the code the loop used to end on.
    op.execute(
        sa.text(f"UPDATE {_TABLE} SET failure_code = 'exhausted' WHERE failure_code = 'invalid'")
    )
    _replace(_BEFORE)
