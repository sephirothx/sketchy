"""hold the lifecycle invariants at the database boundary

Revision ID: d4e7c1f5a692
Revises: c3d6b0e4f581
Create Date: 2026-09-06 02:30:00.000000

Every writer already keeps these; the row now refuses a second writer, a
repair script or a partial restore that does not (#553). Bans lose the
`is_active` flag, which recorded only "not revoked": active is one
predicate everywhere - not revoked and not past expiry - and the two ban
indexes become partials over the unrevoked rows. A drawing gains a
same-game key to its turn.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "d4e7c1f5a692"
down_revision: str | Sequence[str] | None = "c3d6b0e4f581"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECKS: tuple[tuple[str, str, str], ...] = (
    (
        "turn_prompt_offers",
        "ck_turn_prompt_offers_curated_version",
        "(source_kind = 'curated') = (prompt_version_id IS NOT NULL)",
    ),
    ("prompt_usage_facts", "ck_prompt_usage_facts_picks_within_offers", "pick_count <= offer_count"),
    (
        "prompt_usage_facts",
        "ck_prompt_usage_facts_correct_within_guessers",
        "correct_guess_count <= total_guesser_count",
    ),
    (
        "users",
        "ck_users_registered_credentials",
        "(state = 'registered') = (username IS NOT NULL AND password_hash IS NOT NULL)",
    ),
    ("player_reports", "ck_player_reports_reviewed_identity", "status = 'pending' OR reviewed_at IS NOT NULL"),
    (
        "prompt_content_reports",
        "ck_prompt_content_reports_reviewed_identity",
        "status = 'pending' OR reviewed_at IS NOT NULL",
    ),
    ("friendships", "ck_friendships_pending_unanswered", "(status = 'pending') = (responded_at IS NULL)"),
    (
        "data_exports",
        "ck_data_exports_ready_has_artifact",
        "status <> 'ready' OR (artifact IS NOT NULL AND artifact_encoding IS NOT NULL)",
    ),
    ("data_exports", "ck_data_exports_failed_has_code", "status <> 'failed' OR failure_code IS NOT NULL"),
    (
        "data_exports",
        "ck_data_exports_terminal_completed",
        "status NOT IN ('ready', 'failed') OR completed_at IS NOT NULL",
    ),
    ("data_exports", "ck_data_exports_started", "status = 'pending' OR started_at IS NOT NULL"),
    ("turn_drawings", "ck_turn_drawings_ready_stored_at", "status <> 'ready' OR stored_at IS NOT NULL"),
    ("turn_drawings", "ck_turn_drawings_deleted_at", "status <> 'deleted' OR deleted_at IS NOT NULL"),
    (
        "turn_drawings",
        "ck_turn_drawings_byte_size_matches",
        "payload IS NULL OR byte_size IS NULL OR length(payload) = byte_size",
    ),
    ("email_outbox", "ck_email_outbox_failed_has_error", "state <> 'failed' OR last_error IS NOT NULL"),
    ("prompt_lists", "ck_prompt_lists_public_is_bundled", "visibility <> 'public' OR is_bundled = true"),
    ("auth_sessions", "ck_auth_sessions_expiry_after_creation", "expires_at > created_at"),
    (
        "uploaded_avatar_assets",
        "ck_uploaded_avatar_assets_byte_size",
        "byte_size > 0 AND byte_size <= 131072",
    ),
    ("uploaded_avatar_assets", "ck_uploaded_avatar_assets_dimensions", "width > 0 AND height > 0"),
    (
        "user_bans",
        "ck_user_bans_revocation_identity",
        "revoked_at IS NOT NULL OR (revoked_by_user_id IS NULL AND revoke_reason IS NULL)",
    ),
)


# SQLite reflection loses the ON DELETE of a foreign key that an earlier
# migration added inline through a batch column (see r1e5c8f3a469): the one
# such column here is restated so the rebuild keeps its SET NULL.
_REFLECT_ARGS = {
    "user_bans": [
        sa.Column(
            "source_report_id",
            sa.Uuid(),
            sa.ForeignKey("player_reports.id", ondelete="SET NULL"),
            nullable=True,
        )
    ],
}


def _restore_users_expression_indexes_on_sqlite() -> None:
    """A SQLite batch rebuild of `users` cannot carry its two hand-written
    expression indexes across (see 8c4e1a7b2d60); put them back."""
    if op.get_bind().dialect.name != "sqlite":
        return
    op.create_index(
        "ix_users_username_lower",
        "users",
        [sa.text("lower(username)")],
        unique=True,
        sqlite_where=sa.text("username IS NOT NULL"),
    )
    op.create_index(
        "ix_users_email_lower",
        "users",
        [sa.text("lower(email)")],
        unique=True,
        sqlite_where=sa.text("email IS NOT NULL"),
    )


def _batch(table: str):
    return op.batch_alter_table(table, reflect_args=_REFLECT_ARGS.get(table, []))


def upgrade() -> None:
    # Reports decided by an earlier migration's fold (c4d1a8e35b72) carry no
    # review time; a decision is a decision, and the update time is when it
    # was made. Nothing is deployed, so no real row is touched (Pre-v1 note).
    op.execute(
        "UPDATE player_reports SET reviewed_at = updated_at "
        "WHERE status <> 'pending' AND reviewed_at IS NULL"
    )
    op.execute(
        "UPDATE prompt_content_reports SET reviewed_at = created_at "
        "WHERE status <> 'pending' AND reviewed_at IS NULL"
    )
    for table, name, expression in _CHECKS:
        with _batch(table) as batch:
            batch.create_check_constraint(name, expression)
    _restore_users_expression_indexes_on_sqlite()
    with op.batch_alter_table("turn_drawings") as batch:
        batch.drop_constraint("ck_turn_drawings_erased", type_="check")
        batch.create_check_constraint(
            "ck_turn_drawings_erased",
            "status NOT IN ('unavailable', 'deleted') OR (payload IS NULL AND object_key IS NULL)",
        )
        batch.create_foreign_key(
            "fk_turn_drawings_turn_same_game",
            "turn_records",
            ["game_id", "turn_id"],
            ["game_id", "id"],
            ondelete="CASCADE",
        )
    op.drop_index("ix_user_bans_user_active_expires", table_name="user_bans")
    op.drop_index("ix_user_bans_active_newest", table_name="user_bans")
    # A plain DROP COLUMN, which SQLite has supported since 3.35: a batch
    # rebuild here re-reflected the table's foreign keys without their ON
    # DELETE actions.
    op.drop_column("user_bans", "is_active")
    op.create_index(
        "ix_user_bans_user_expires", "user_bans", ["user_id", "expires_at"], unique=False
    )
    op.create_index(
        "ix_user_bans_unrevoked_newest",
        "user_bans",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text("revoked_at IS NULL"),
        sqlite_where=sa.text("revoked_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_user_bans_unrevoked_newest", table_name="user_bans")
    op.drop_index("ix_user_bans_user_expires", table_name="user_bans")
    op.add_column(
        "user_bans",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.execute("UPDATE user_bans SET is_active = (revoked_at IS NULL)")
    op.create_index(
        "ix_user_bans_active_newest",
        "user_bans",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text("is_active IS TRUE"),
        sqlite_where=sa.text("is_active IS TRUE"),
    )
    op.create_index(
        "ix_user_bans_user_active_expires",
        "user_bans",
        ["user_id", "is_active", "expires_at"],
        unique=False,
    )
    with op.batch_alter_table("turn_drawings") as batch:
        batch.drop_constraint("fk_turn_drawings_turn_same_game", type_="foreignkey")
        batch.drop_constraint("ck_turn_drawings_erased", type_="check")
        batch.create_check_constraint(
            "ck_turn_drawings_erased",
            "status NOT IN ('unavailable', 'deleted') OR payload IS NULL",
        )
    for table, name, _ in reversed(_CHECKS):
        with _batch(table) as batch:
            batch.drop_constraint(name, type_="check")
    _restore_users_expression_indexes_on_sqlite()
    if op.get_bind().dialect.name == "sqlite":
        # The upgrade's rebuild wrote source_report_id's foreign key as a
        # table-level constraint; the migration that added that column drops
        # it with a plain DROP COLUMN, which SQLite refuses while a
        # table-level constraint names it. Take the constraint off again so
        # the older downgrade keeps working; the column and its rows stay.
        with op.batch_alter_table(
            "user_bans",
            naming_convention={
                "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"
            },
        ) as batch:
            batch.drop_constraint(
                "fk_user_bans_source_report_id_player_reports", type_="foreignkey"
            )
