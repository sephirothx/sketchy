"""gallery moderation: hidden drawings, shelf reviews, a drawing as an audit target

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-09-15 21:00:00.000000

A moderator can hide a drawing from the Gallery (#524, R-GAL-09) - a
judgement about the lobby, kept as `gallery_hidden_at` on the drawing row
beside its bytes, which stay for the players who were there. Under the
`gallery.shelf_review` switch the lobby's shelf shows only drawings a
moderator released, so `gallery_shelf_reviews` records that decision, one
row per turn (R-GAL-10). Both acts are audited against the drawing, which
the audit ledger's target check now admits.

Going back drops the column and the table; a hidden drawing reappears in
the Gallery, which is what "hidden" meant while the column existed.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "d2e3f4a5b6c7"
down_revision: str | Sequence[str] | None = "c1d2e3f4a5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TARGET_TYPES_BEFORE = (
    "target_type IS NULL OR target_type IN "
    "('user', 'prompt_list', 'prompt_version', 'room', 'app_config', 'bug_report')"
)
_TARGET_TYPES_AFTER = (
    "target_type IS NULL OR target_type IN "
    "('user', 'prompt_list', 'prompt_version', 'room', 'app_config', "
    "'bug_report', 'drawing')"
)


def upgrade() -> None:
    with op.batch_alter_table("turn_drawings") as batch:
        batch.add_column(
            sa.Column("gallery_hidden_at", sa.DateTime(timezone=True), nullable=True)
        )
    op.create_table(
        "gallery_shelf_reviews",
        sa.Column(
            "turn_id",
            sa.Uuid(as_uuid=True, native_uuid=True),
            sa.ForeignKey("turn_records.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column(
            "decided_by_user_id",
            sa.Uuid(as_uuid=True, native_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "decision IN ('released', 'hidden')",
            name="ck_gallery_shelf_reviews_decision",
        ),
    )
    op.create_index(
        "ix_gallery_shelf_reviews_decided_by_user_id",
        "gallery_shelf_reviews",
        ["decided_by_user_id"],
    )
    with op.batch_alter_table("audit_events") as batch:
        batch.drop_constraint("ck_audit_events_target_type", type_="check")
        batch.create_check_constraint("ck_audit_events_target_type", _TARGET_TYPES_AFTER)


def downgrade() -> None:
    op.execute("DELETE FROM audit_events WHERE target_type = 'drawing'")
    with op.batch_alter_table("audit_events") as batch:
        batch.drop_constraint("ck_audit_events_target_type", type_="check")
        batch.create_check_constraint("ck_audit_events_target_type", _TARGET_TYPES_BEFORE)
    op.drop_index(
        "ix_gallery_shelf_reviews_decided_by_user_id", table_name="gallery_shelf_reviews"
    )
    op.drop_table("gallery_shelf_reviews")
    with op.batch_alter_table("turn_drawings") as batch:
        batch.drop_column("gallery_hidden_at")
