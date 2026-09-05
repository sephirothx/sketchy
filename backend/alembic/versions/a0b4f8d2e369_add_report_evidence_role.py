"""mark report evidence as cited or context

A report copies two kinds of line: what it is about, and what was said around
it so a moderator reads the line where it was said. The second kind is chosen
by the server and must never be shown back to the reported player as their
own words, so the copy has to say which it is. Every row that exists today was
selected as evidence, which is what the default records.

Revision ID: a0b4f8d2e369
Revises: z9a3e7c1d258
Create Date: 2026-09-05 18:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "a0b4f8d2e369"
down_revision: str | Sequence[str] | None = "z9a3e7c1d258"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLES = "'cited', 'context'"


def upgrade() -> None:
    with op.batch_alter_table("player_report_message_evidence") as batch_op:
        batch_op.add_column(
            sa.Column(
                "role",
                sa.String(length=16),
                nullable=False,
                server_default="cited",
            )
        )
        batch_op.create_check_constraint(
            "ck_report_message_evidence_role", f"role IN ({ROLES})"
        )


def downgrade() -> None:
    # Context rows are third-party lines the previous schema would present as
    # evidence against the reported player, which they are not. They were
    # copied for a moderator's reading and are dropped rather than
    # misfiled; the cited rows are untouched.
    op.execute(
        sa.text("DELETE FROM player_report_message_evidence WHERE role = 'context'")
    )
    with op.batch_alter_table("player_report_message_evidence") as batch_op:
        batch_op.drop_constraint("ck_report_message_evidence_role", type_="check")
        batch_op.drop_column("role")
