"""baseline schema

Revision ID: f0a1b2c3d4e5
Revises:
Create Date: 2026-09-06 04:08:33.446425

The one revision an empty database is built from (#557). Nothing was
deployed when the 70-revision chain that preceded it was folded into this
file, so no database holds rows written under an earlier revision and none
of that chain's backfills, refusals or accommodations had anything left to
protect; a checkout that predates it rebuilds its SQLite file. Generated
from the models and then edited by hand where autogenerate could not see:
the two expression indexes on users that SQLite cannot reflect, the
append-only trigger on score_events, and dialect-neutral defaults in place
of the SQLite-compiled ones. It does not import the models - a historical
revision stays what it was when it ran.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "f0a1b2c3d4e5"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _users_expression_indexes() -> None:
    """Case-insensitive uniqueness of usernames and emails, only where set.

    Declared on the model too, but SQLite cannot reflect an expression index,
    so autogenerate skips them and the migration suite pins their definition
    by name on both dialects.
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


def _score_events_append_only() -> None:
    """Events are corrected by appending a correction event (R-HIST-11).

    Once inserted, an event's reason, amount and order cannot be rewritten;
    the database refuses the UPDATE rather than trusting every writer to.
    """
    if op.get_bind().dialect.name == "sqlite":
        op.execute(
            "CREATE TRIGGER trg_score_events_immutable_update "
            "BEFORE UPDATE ON score_events BEGIN "
            "SELECT RAISE(ABORT, 'score events are immutable'); END"
        )
        return
    op.execute(
        "CREATE FUNCTION reject_score_event_update() RETURNS trigger "
        "LANGUAGE plpgsql AS $$ BEGIN "
        "RAISE EXCEPTION 'score events are immutable'; END; $$"
    )
    op.execute(
        "CREATE TRIGGER trg_score_events_immutable_update "
        "BEFORE UPDATE ON score_events FOR EACH ROW "
        "EXECUTE FUNCTION reject_score_event_update()"
    )


def upgrade() -> None:
    op.create_table('app_config',
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('value', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('auth_rate_limit_buckets',
    sa.Column('scope', sa.String(length=32), nullable=False),
    sa.Column('key_hash', sa.String(length=64), nullable=False),
    sa.Column('attempt_count', sa.Integer(), nullable=False),
    sa.Column('window_started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('window_expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('scope', 'key_hash')
    )
    op.create_index('ix_auth_rate_limit_buckets_window_expires_at', 'auth_rate_limit_buckets', ['window_expires_at'], unique=False)

    op.create_table('game_records',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('payload_hash', sa.String(length=64), server_default='', nullable=False),
    sa.Column('room_name', sa.String(length=64), nullable=False),
    sa.Column('scoring_mode', sa.String(length=16), nullable=False),
    sa.Column('scoring_version', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('score_ledger_version', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('rule_snapshot_version', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('rule_snapshot', sa.JSON(none_as_null=True).with_variant(postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), 'postgresql'), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('prompt_source_mode', sa.String(length=24), nullable=False),
    sa.Column('hint_mode', sa.String(length=16), nullable=False),
    sa.Column('drawing_seconds', sa.Integer(), nullable=False),
    sa.Column('total_rounds', sa.Integer(), nullable=False),
    sa.Column('player_count', sa.Integer(), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('outcome', sa.String(length=16), server_default=sa.text("'finished'"), nullable=False),
    sa.Column('persisted_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.CheckConstraint("hint_mode IN ('none', 'checkpoints', 'purchase', 'wheel')", name='ck_game_records_hint_mode'),
    sa.CheckConstraint("prompt_source_mode IN ('curated', 'custom', 'mixed', 'builtin_fallback')", name='ck_game_records_prompt_source_mode'),
    sa.CheckConstraint("scoring_mode IN ('none', 'default', 'pressure')", name='ck_game_records_scoring_mode'),
    sa.CheckConstraint('drawing_seconds > 0', name='ck_game_records_drawing_seconds'),
    sa.CheckConstraint("outcome IN ('finished', 'abandoned', 'shutdown')", name='ck_game_records_outcome'),
    sa.CheckConstraint('player_count >= 1', name='ck_game_records_player_count'),
    sa.CheckConstraint('rule_snapshot_version >= 0', name='ck_game_records_rule_snapshot_version'),
    sa.CheckConstraint('score_ledger_version >= 0', name='ck_game_records_score_ledger_version'),
    sa.CheckConstraint('scoring_version >= 0', name='ck_game_records_scoring_version'),
    sa.CheckConstraint('started_at <= finished_at', name='ck_game_records_time_order'),
    sa.CheckConstraint('total_rounds >= 1', name='ck_game_records_total_rounds'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_game_records_finished_at', 'game_records', ['finished_at'], unique=False)
    op.create_index('ix_game_records_outcome_finished_at', 'game_records', ['outcome', 'finished_at'], unique=False)

    op.create_table('planned_shutdown_abandonments',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('game_id', sa.Uuid(), nullable=False),
    sa.Column('room_instance_id', sa.Uuid(), nullable=False),
    sa.Column('contract_version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('reason', sa.String(length=24), nullable=False),
    sa.Column('phase', sa.String(length=24), nullable=False),
    sa.Column('round_number', sa.Integer(), nullable=False),
    sa.Column('completed_turn_count', sa.Integer(), nullable=False),
    sa.Column('seated_player_count', sa.Integer(), nullable=False),
    sa.Column('connected_player_count', sa.Integer(), nullable=False),
    sa.Column('spectator_count', sa.Integer(), nullable=False),
    sa.Column('canvas_action_count', sa.Integer(), nullable=False),
    sa.Column('game_started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('observed_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.CheckConstraint("phase IN ('choosing_prompt', 'drawing', 'turn_results', 'game_end')", name='ck_shutdown_abandonment_phase'),
    sa.CheckConstraint("reason IN ('drain_timeout')", name='ck_shutdown_abandonment_reason'),
    sa.CheckConstraint('contract_version = 1', name='ck_shutdown_abandonment_contract'),
    sa.CheckConstraint('round_number >= 0 AND completed_turn_count >= 0', name='ck_shutdown_abandonment_progress'),
    sa.CheckConstraint('seated_player_count >= 0 AND connected_player_count >= 0 AND spectator_count >= 0 AND canvas_action_count >= 0', name='ck_shutdown_abandonment_counts'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_planned_shutdown_abandonments_game_id', 'planned_shutdown_abandonments', ['game_id'], unique=True)
    op.create_index('ix_planned_shutdown_abandonments_observed_at', 'planned_shutdown_abandonments', ['observed_at'], unique=False)
    op.create_index('ix_planned_shutdown_abandonments_room_instance_id', 'planned_shutdown_abandonments', ['room_instance_id'], unique=False)

    op.create_table('prompt_concepts',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('prompt_tags',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('slug', sa.String(length=32), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('description', sa.String(length=255), server_default='', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('slug')
    )
    op.create_table('room_code_reservations',
    sa.Column('code', sa.String(length=6), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('retired_until', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("(kind = 'persistent' AND retired_until IS NULL) OR kind = 'ephemeral'", name='ck_persistent_room_code_never_retires'),
    sa.CheckConstraint("kind IN ('ephemeral', 'persistent')", name='ck_room_code_kind'),
    sa.PrimaryKeyConstraint('code')
    )
    op.create_index('ix_room_code_reservations_retired_until', 'room_code_reservations', ['retired_until'], unique=False)

    op.create_table('runtime_stats_daily',
    sa.Column('stat_date', sa.Date(), nullable=False),
    sa.Column('metric', sa.String(length=32), nullable=False),
    sa.Column('occurrences', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('value_sum', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('value_max', sa.Integer(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.CheckConstraint('occurrences >= 0 AND value_sum >= 0', name='ck_runtime_stats_nonnegative'),
    sa.PrimaryKeyConstraint('stat_date', 'metric')
    )
    op.create_table('users',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('username', sa.String(length=32), nullable=True),
    sa.Column('password_hash', sa.String(length=255), nullable=True),
    sa.Column('display_name', sa.String(length=32), nullable=False),
    sa.Column('name_color', sa.String(length=16), nullable=True),
    sa.Column('avatar_key', sa.String(length=80), nullable=True),
    sa.Column('avatar_upload_blocked_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('state', sa.String(length=16), server_default='anonymous', nullable=False),
    sa.Column('role', sa.String(length=16), server_default='user', nullable=False),
    sa.Column('email', sa.String(length=255), nullable=True),
    sa.Column('email_verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('last_login_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('last_active_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.CheckConstraint("(state = 'registered') = (username IS NOT NULL AND password_hash IS NOT NULL)", name='ck_users_registered_credentials'),
    sa.CheckConstraint("role IN ('user', 'moderator', 'admin')", name='ck_users_role'),
    sa.CheckConstraint("state IN ('anonymous', 'registered', 'merged', 'deleted')", name='ck_users_state'),
    sa.CheckConstraint('email IS NOT NULL OR email_verified_at IS NULL', name='ck_users_verified_email_present'),
    sa.CheckConstraint('email IS NULL OR email = lower(trim(email))', name='ck_users_email_normalized'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_users_state_last_active_at', 'users', ['state', 'last_active_at'], unique=False)

    op.create_table('audit_events',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('event_type', sa.String(length=64), nullable=False),
    sa.Column('actor_user_id', sa.Uuid(), nullable=True),
    sa.Column('target_user_id', sa.Uuid(), nullable=True),
    sa.Column('target_type', sa.String(length=32), nullable=True),
    sa.Column('target_id', sa.String(length=64), nullable=True),
    sa.Column('request_id', sa.String(length=64), nullable=True),
    sa.Column('ip_hash', sa.String(length=64), nullable=True),
    sa.Column('details', sa.JSON(none_as_null=True).with_variant(postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.CheckConstraint("target_type IS NULL OR target_type IN ('user', 'prompt_list', 'prompt_version', 'room', 'app_config', 'bug_report')", name='ck_audit_events_target_type'),
    sa.CheckConstraint('(target_type IS NULL AND target_id IS NULL) OR (target_type IS NOT NULL AND target_id IS NOT NULL)', name='ck_audit_events_target_pair'),
    sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['target_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_audit_events_actor_user_id', 'audit_events', ['actor_user_id'], unique=False)
    op.create_index('ix_audit_events_created_at', 'audit_events', ['created_at'], unique=False)
    op.create_index('ix_audit_events_target', 'audit_events', ['target_type', 'target_id'], unique=False)
    op.create_index('ix_audit_events_target_user_id', 'audit_events', ['target_user_id'], unique=False)
    op.create_index('ix_audit_events_type_created_at', 'audit_events', ['event_type', 'created_at'], unique=False)

    op.create_table('auth_sessions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('device_label', sa.String(length=64), nullable=False),
    sa.Column('rotated_from_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('last_used_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint('expires_at > created_at', name='ck_auth_sessions_expiry_after_creation'),
    sa.ForeignKeyConstraint(['rotated_from_id'], ['auth_sessions.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('rotated_from_id'),
    sa.UniqueConstraint('token_hash')
    )
    op.create_index('ix_auth_sessions_expires_at', 'auth_sessions', ['expires_at'], unique=False)
    op.create_index('ix_auth_sessions_user_id', 'auth_sessions', ['user_id'], unique=False)

    op.create_table('auth_tokens',
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('purpose', sa.String(length=32), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('consumed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('requested_ip_hash', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.CheckConstraint("purpose <> 'email_verify' OR email IS NOT NULL", name='ck_auth_tokens_verify_address'),
    sa.CheckConstraint("purpose IN ('password_reset', 'email_verify')", name='ck_auth_tokens_purpose'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('token_hash')
    )
    op.create_index('ix_auth_tokens_expires_at', 'auth_tokens', ['expires_at'], unique=False)
    op.create_index('ix_auth_tokens_user_purpose', 'auth_tokens', ['user_id', 'purpose'], unique=False)

    op.create_table('bug_reports',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('reporter_user_id', sa.Uuid(), nullable=True),
    sa.Column('area', sa.String(length=32), nullable=False),
    sa.Column('severity', sa.String(length=16), nullable=False),
    sa.Column('summary', sa.String(length=200), nullable=False),
    sa.Column('details', sa.Text(), nullable=False),
    sa.Column('build_sha', sa.String(length=64), nullable=True),
    sa.Column('route', sa.String(length=255), nullable=True),
    sa.Column('room_code', sa.String(length=16), nullable=True),
    sa.Column('game_id', sa.Uuid(), nullable=True),
    sa.Column('turn_id', sa.Uuid(), nullable=True),
    sa.Column('client_context', sa.JSON(none_as_null=True).with_variant(postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('server_context', sa.JSON(none_as_null=True).with_variant(postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('screenshot_status', sa.String(length=16), server_default='none', nullable=False),
    sa.Column('screenshot_payload', sa.LargeBinary(), nullable=True),
    sa.Column('screenshot_content_type', sa.String(length=64), nullable=True),
    sa.Column('screenshot_byte_size', sa.Integer(), nullable=True),
    sa.Column('screenshot_width', sa.Integer(), nullable=True),
    sa.Column('screenshot_height', sa.Integer(), nullable=True),
    sa.Column('screenshot_checksum_sha256', sa.String(length=64), nullable=True),
    sa.Column('status', sa.String(length=16), server_default='pending', nullable=False),
    sa.Column('reviewed_by_user_id', sa.Uuid(), nullable=True),
    sa.Column('resolution_note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("area IN ('drawing_and_canvas', 'guessing_and_chat', 'rounds_and_scoring', 'rooms_and_lobby', 'prompt_lists', 'account_and_settings', 'connection_and_sync', 'performance', 'accessibility', 'other')", name='ck_bug_reports_area'),
    sa.CheckConstraint("screenshot_status <> 'erased' OR screenshot_payload IS NULL", name='ck_bug_reports_screenshot_erased'),
    sa.CheckConstraint("screenshot_status <> 'none' OR screenshot_payload IS NULL", name='ck_bug_reports_screenshot_absent'),
    sa.CheckConstraint("screenshot_status <> 'ready' OR (screenshot_payload IS NOT NULL AND screenshot_byte_size IS NOT NULL AND screenshot_checksum_sha256 IS NOT NULL AND screenshot_content_type IS NOT NULL)", name='ck_bug_reports_screenshot_ready_identity'),
    sa.CheckConstraint("screenshot_status IN ('none', 'ready', 'erased')", name='ck_bug_reports_screenshot_status'),
    sa.CheckConstraint("severity IN ('blocks_play', 'major', 'minor')", name='ck_bug_reports_severity'),
    sa.CheckConstraint("status = 'pending' OR reviewed_at IS NOT NULL", name='ck_bug_reports_reviewed_identity'),
    sa.CheckConstraint("status IN ('pending', 'resolved', 'dismissed')", name='ck_bug_reports_status'),
    sa.CheckConstraint('screenshot_byte_size IS NULL OR (screenshot_byte_size > 0 AND screenshot_byte_size <= 2097152)', name='ck_bug_reports_screenshot_byte_size'),
    sa.ForeignKeyConstraint(['reporter_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['reviewed_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_bug_reports_reporter_user_id', 'bug_reports', ['reporter_user_id'], unique=False)
    op.create_index('ix_bug_reports_reviewed_by_user_id', 'bug_reports', ['reviewed_by_user_id'], unique=False)
    op.create_index('ix_bug_reports_status_created_at', 'bug_reports', ['status', 'created_at'], unique=False)

    op.create_table('data_exports',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.String(length=16), server_default='pending', nullable=False),
    sa.Column('schema_version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('artifact', sa.LargeBinary(), nullable=True),
    sa.Column('artifact_encoding', sa.String(length=16), nullable=True),
    sa.Column('failure_code', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("artifact_encoding IN ('gzip+json')", name='ck_data_exports_artifact_encoding'),
    sa.CheckConstraint("status <> 'failed' OR failure_code IS NOT NULL", name='ck_data_exports_failed_has_code'),
    sa.CheckConstraint("status <> 'ready' OR (artifact IS NOT NULL AND artifact_encoding IS NOT NULL)", name='ck_data_exports_ready_has_artifact'),
    sa.CheckConstraint("status = 'pending' OR started_at IS NOT NULL", name='ck_data_exports_started'),
    sa.CheckConstraint("status IN ('pending', 'processing', 'ready', 'failed')", name='ck_data_exports_status'),
    sa.CheckConstraint("status NOT IN ('ready', 'failed') OR completed_at IS NOT NULL", name='ck_data_exports_terminal_completed'),
    sa.CheckConstraint('(artifact IS NULL) = (artifact_encoding IS NULL)', name='ck_data_exports_artifact_encoding_present'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_data_exports_expires_at', 'data_exports', ['expires_at'], unique=False)
    op.create_index('ix_data_exports_user_created_at', 'data_exports', ['user_id', 'created_at'], unique=False)
    op.create_index('uq_data_exports_one_live_per_user', 'data_exports', ['user_id'], unique=True, postgresql_where=sa.text("status IN ('pending', 'processing')"), sqlite_where=sa.text("status IN ('pending', 'processing')"))

    op.create_table('email_outbox',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('to_address', sa.String(length=255), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=True),
    sa.Column('template', sa.String(length=64), nullable=False),
    sa.Column('payload', sa.JSON(none_as_null=True).with_variant(postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('state', sa.String(length=16), nullable=False),
    sa.Column('attempts', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('last_error', sa.String(length=256), nullable=True),
    sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("(state = 'sent') = (sent_at IS NOT NULL)", name='ck_email_outbox_sent_at'),
    sa.CheckConstraint("state <> 'failed' OR last_error IS NOT NULL", name='ck_email_outbox_failed_has_error'),
    sa.CheckConstraint("state IN ('pending', 'sent', 'failed')", name='ck_email_outbox_state'),
    sa.CheckConstraint("template IN ('verify_email', 'reset_password', 'password_changed', 'account_banned', 'content_hidden')", name='ck_email_outbox_template'),
    sa.CheckConstraint('attempts >= 0', name='ck_email_outbox_attempts'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_email_outbox_ready', 'email_outbox', ['state', 'next_attempt_at'], unique=False)
    op.create_index('ix_email_outbox_sent_at_sent', 'email_outbox', ['sent_at', 'id'], unique=False, postgresql_where=sa.text("state = 'sent'"), sqlite_where=sa.text("state = 'sent'"))
    op.create_index('ix_email_outbox_user_id', 'email_outbox', ['user_id'], unique=False)

    op.create_table('external_identities',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('provider', sa.String(length=64), nullable=False),
    sa.Column('subject', sa.String(length=255), nullable=False),
    sa.Column('provider_email', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('provider', 'subject', name='uq_external_identity')
    )
    op.create_index('ix_external_identities_user_id', 'external_identities', ['user_id'], unique=False)

    op.create_table('friendships',
    sa.Column('user_low_id', sa.Uuid(), nullable=False),
    sa.Column('user_high_id', sa.Uuid(), nullable=False),
    sa.Column('requested_by_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('responded_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("(status = 'pending') = (responded_at IS NULL)", name='ck_friendships_pending_unanswered'),
    sa.CheckConstraint("status IN ('pending', 'accepted', 'declined')", name='ck_friendships_status'),
    sa.CheckConstraint('requested_by_id = user_low_id OR requested_by_id = user_high_id', name='ck_friendships_requester_is_a_member'),
    sa.CheckConstraint('user_low_id < user_high_id', name='ck_friendships_ordered'),
    sa.ForeignKeyConstraint(['requested_by_id'], ['users.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_high_id'], ['users.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_low_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_low_id', 'user_high_id')
    )
    op.create_index('ix_friendships_requested_by_id', 'friendships', ['requested_by_id'], unique=False)
    op.create_index('ix_friendships_user_high_id', 'friendships', ['user_high_id'], unique=False)

    op.create_table('game_participants',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('game_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=True),
    sa.Column('display_name_snapshot', sa.String(length=32), nullable=False),
    sa.Column('name_color_snapshot', sa.String(length=16), nullable=True),
    sa.Column('is_anonymous_snapshot', sa.Boolean(), nullable=False),
    sa.Column('final_score', sa.Integer(), nullable=False),
    sa.Column('final_rank', sa.Integer(), nullable=True),
    sa.Column('turns_played', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.CheckConstraint('final_rank IS NULL OR final_rank >= 1', name='ck_game_participants_final_rank'),
    sa.ForeignKeyConstraint(['game_id'], ['game_records.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('game_id', 'id', name='uq_game_participants_game_id_id')
    )
    op.create_index('ix_game_participants_user_id', 'game_participants', ['user_id'], unique=False)
    op.create_index('uq_game_participants_game_user', 'game_participants', ['game_id', 'user_id'], unique=True)

    op.create_table('identity_aliases',
    sa.Column('source_user_id', sa.Uuid(), nullable=False),
    sa.Column('target_user_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.CheckConstraint('source_user_id != target_user_id', name='ck_identity_alias_distinct'),
    sa.ForeignKeyConstraint(['source_user_id'], ['users.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['target_user_id'], ['users.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('source_user_id')
    )
    op.create_index('ix_identity_aliases_target_user_id', 'identity_aliases', ['target_user_id'], unique=False)

    op.create_table('prompt_aliases',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('concept_id', sa.Uuid(), nullable=False),
    sa.Column('language', sa.String(length=16), nullable=False),
    sa.Column('answer', sa.String(length=64), nullable=False),
    sa.Column('match_key', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.CheckConstraint("language IN ('en', 'de', 'es', 'fr', 'it', 'nl', 'pt')", name='ck_prompt_aliases_language'),
    sa.ForeignKeyConstraint(['concept_id'], ['prompt_concepts.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('concept_id', 'language', 'match_key', name='uq_prompt_alias_concept_language_match_key')
    )
    op.create_table('prompt_lists',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('owner_user_id', sa.Uuid(), nullable=True),
    sa.Column('slug', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('description', sa.String(length=255), server_default='', nullable=False),
    sa.Column('language', sa.String(length=16), server_default='en', nullable=False),
    sa.Column('is_bundled', sa.Boolean(), server_default=sa.true(), nullable=False),
    sa.Column('visibility', sa.String(length=16), server_default='private', nullable=False),
    sa.Column('share_code', sa.String(length=24), nullable=True),
    sa.Column('moderation_state', sa.String(length=16), server_default='active', nullable=False),
    sa.Column('moderated_by_user_id', sa.Uuid(), nullable=True),
    sa.Column('moderated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.CheckConstraint("language IN ('en', 'de', 'es', 'fr', 'it', 'nl', 'pt')", name='ck_prompt_lists_language'),
    sa.CheckConstraint("moderation_state IN ('active', 'under_review', 'hidden')", name='ck_prompt_lists_moderation_state'),
    sa.CheckConstraint("visibility != 'unlisted' OR share_code IS NOT NULL", name='ck_prompt_lists_unlisted_share_code'),
    sa.CheckConstraint("visibility <> 'public' OR is_bundled = true", name='ck_prompt_lists_public_is_bundled'),
    sa.CheckConstraint("visibility IN ('private', 'unlisted', 'public')", name='ck_prompt_lists_visibility'),
    sa.CheckConstraint('is_bundled = false OR owner_user_id IS NULL', name='ck_prompt_lists_bundled_owner'),
    sa.ForeignKeyConstraint(['moderated_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['owner_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_prompt_lists_deleted_at', 'prompt_lists', ['deleted_at'], unique=False)
    op.create_index('ix_prompt_lists_moderated_by', 'prompt_lists', ['moderated_by_user_id'], unique=False, postgresql_where=sa.text('moderated_by_user_id IS NOT NULL'), sqlite_where=sa.text('moderated_by_user_id IS NOT NULL'))
    op.create_index('ix_prompt_lists_moderation_state', 'prompt_lists', ['moderation_state'], unique=False)
    op.create_index('ix_prompt_lists_owner_user_id', 'prompt_lists', ['owner_user_id'], unique=False)
    op.create_index('ix_prompt_lists_share_code', 'prompt_lists', ['share_code'], unique=True)
    op.create_index('ix_prompt_lists_slug', 'prompt_lists', ['slug'], unique=True)
    op.create_index('ix_prompt_lists_visibility', 'prompt_lists', ['visibility'], unique=False)

    op.create_table('prompt_versions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('concept_id', sa.Uuid(), nullable=False),
    sa.Column('language', sa.String(length=16), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('canonical_answer', sa.String(length=64), nullable=False),
    sa.Column('match_key', sa.String(length=64), nullable=False),
    sa.Column('editorial_difficulty', sa.String(length=16), server_default='unspecified', nullable=False),
    sa.Column('content_rating', sa.String(length=16), server_default='everyone', nullable=False),
    sa.Column('moderation_state', sa.String(length=16), server_default='active', nullable=False),
    sa.Column('moderated_by_user_id', sa.Uuid(), nullable=True),
    sa.Column('moderated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.CheckConstraint("content_rating IN ('everyone', 'teen', 'mature')", name='ck_prompt_versions_content_rating'),
    sa.CheckConstraint("editorial_difficulty IN ('unspecified', 'easy', 'medium', 'hard')", name='ck_prompt_versions_editorial_difficulty'),
    sa.CheckConstraint("language IN ('en', 'de', 'es', 'fr', 'it', 'nl', 'pt')", name='ck_prompt_versions_language'),
    sa.CheckConstraint("moderation_state IN ('active', 'under_review', 'hidden')", name='ck_prompt_versions_moderation_state'),
    sa.CheckConstraint('version >= 1', name='ck_prompt_versions_version_positive'),
    sa.ForeignKeyConstraint(['concept_id'], ['prompt_concepts.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['moderated_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('concept_id', 'language', 'version', name='uq_prompt_version_concept_language_version')
    )
    op.create_index('ix_prompt_versions_moderated_by', 'prompt_versions', ['moderated_by_user_id'], unique=False, postgresql_where=sa.text('moderated_by_user_id IS NOT NULL'), sqlite_where=sa.text('moderated_by_user_id IS NOT NULL'))
    op.create_index('ix_prompt_versions_moderation_state', 'prompt_versions', ['moderation_state'], unique=False)

    op.create_table('role_change_notices',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=True),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("role IN ('user', 'moderator')", name='ck_role_change_notices_role'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_role_change_notices_user_pending', 'role_change_notices', ['user_id', 'acknowledged_at'], unique=False)

    op.create_table('room_messages',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('room_instance_id', sa.Uuid(), nullable=True),
    sa.Column('game_id', sa.Uuid(), nullable=True),
    sa.Column('turn_id', sa.Uuid(), nullable=True),
    sa.Column('sender_user_id', sa.Uuid(), nullable=True),
    sa.Column('sender_player_id', sa.Uuid(), nullable=True),
    sa.Column('sender_seat_id', sa.Uuid(), nullable=True),
    sa.Column('sender_display_name_snapshot', sa.String(length=32), nullable=False),
    sa.Column('sender_name_color_snapshot', sa.String(length=16), nullable=True),
    sa.Column('sender_is_anonymous_snapshot', sa.Boolean(), nullable=False),
    sa.Column('is_spectator', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.Column('message_kind', sa.String(length=24), nullable=False),
    sa.Column('audience', sa.String(length=24), nullable=False),
    sa.Column('audience_user_ids', sa.JSON(none_as_null=True).with_variant(postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('near_miss_kind', sa.String(length=16), nullable=True),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("(audience = 'lobby' AND room_instance_id IS NULL AND sender_player_id IS NULL) OR (audience <> 'lobby' AND room_instance_id IS NOT NULL AND sender_player_id IS NOT NULL)", name='ck_room_messages_lobby_has_no_scope'),
    sa.CheckConstraint("audience <> 'lobby' OR message_kind = 'chat'", name='ck_room_messages_lobby_is_chat'),
    sa.CheckConstraint("audience IN ('room', 'prompt_aware', 'lobby')", name='ck_room_messages_audience'),
    sa.CheckConstraint("message_kind = 'chat' OR (game_id IS NOT NULL AND turn_id IS NOT NULL)", name='ck_room_messages_guesses_have_turn'),
    sa.CheckConstraint("message_kind = 'wrong_guess' OR near_miss_kind IS NULL", name='ck_room_messages_near_miss_only_for_wrong_guess'),
    sa.CheckConstraint("message_kind IN ('chat', 'wrong_guess', 'correct_guess')", name='ck_room_messages_kind'),
    sa.CheckConstraint("near_miss_kind IN ('close', 'partial')", name='ck_room_messages_near_miss_kind'),
    sa.CheckConstraint('expires_at > created_at', name='ck_room_messages_expiry_after_creation'),
    sa.CheckConstraint('turn_id IS NULL OR game_id IS NOT NULL', name='ck_room_messages_turn_has_game'),
    sa.ForeignKeyConstraint(['sender_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_room_messages_expires_at', 'room_messages', ['expires_at'], unique=False)
    op.create_index('ix_room_messages_game_turn_created', 'room_messages', ['game_id', 'turn_id', 'created_at'], unique=False)
    op.create_index('ix_room_messages_lobby_newest', 'room_messages', ['created_at', 'id'], unique=False, postgresql_where=sa.text("audience = 'lobby'"), sqlite_where=sa.text("audience = 'lobby'"))
    op.create_index('ix_room_messages_room_instance_id', 'room_messages', ['room_instance_id'], unique=False)
    op.create_index('ix_room_messages_sender_created', 'room_messages', ['sender_user_id', 'created_at'], unique=False)

    op.create_table('room_presets',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('owner_user_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('name_key', sa.String(length=64), nullable=False),
    sa.Column('room_name', sa.String(length=40), nullable=False),
    sa.Column('is_public', sa.Boolean(), nullable=False),
    sa.Column('max_players', sa.Integer(), nullable=False),
    sa.Column('rounds', sa.Integer(), nullable=False),
    sa.Column('drawing_seconds', sa.Integer(), nullable=False),
    sa.Column('hint_mode', sa.String(length=16), nullable=False),
    sa.Column('scoring_mode', sa.String(length=16), nullable=False),
    sa.Column('spectators_see_prompt', sa.Boolean(), nullable=False),
    sa.Column('hide_masked_prompt', sa.Boolean(), nullable=False),
    sa.Column('allowed_tools', sa.JSON(none_as_null=True).with_variant(postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('color_mode', sa.String(length=24), nullable=False),
    sa.Column('prompt_list_ids', sa.JSON(none_as_null=True).with_variant(postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.CheckConstraint("color_mode IN ('all', 'palette', 'colorblind_safe', 'black_and_white')", name='ck_room_presets_color_mode'),
    sa.CheckConstraint("hint_mode IN ('none', 'checkpoints', 'purchase', 'wheel')", name='ck_room_presets_hint_mode'),
    sa.CheckConstraint("scoring_mode IN ('none', 'default', 'pressure')", name='ck_room_presets_scoring_mode'),
    sa.CheckConstraint('drawing_seconds IN (15, 30, 60, 90, 120, 180, 240, 300)', name='ck_room_presets_drawing_seconds'),
    sa.CheckConstraint('max_players >= 2 AND max_players <= 16', name='ck_room_presets_max_players'),
    sa.CheckConstraint('rounds >= 1 AND rounds <= 10', name='ck_room_presets_rounds'),
    sa.CheckConstraint('version >= 1', name='ck_room_presets_version'),
    sa.ForeignKeyConstraint(['owner_user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('owner_user_id', 'name_key', name='uq_room_presets_owner_name')
    )
    op.create_table('runtime_events',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('event_type', sa.String(length=32), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('room_id', sa.String(length=64), nullable=True),
    sa.Column('user_id', sa.Uuid(), nullable=True),
    sa.Column('value', sa.Integer(), nullable=True),
    sa.Column('details', sa.JSON(none_as_null=True).with_variant(postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.CheckConstraint("event_type IN ('room.created', 'room.closed', 'player.joined', 'player.left', 'player.disconnected', 'player.reconnected', 'player.evicted', 'game.started', 'game.finished', 'game.abandoned', 'turn.ended', 'timer.overran', 'canvas.payload_observed', 'drawing.stored', 'recap.budget_dropped', 'command.throttled', 'history.write_abandoned')", name='ck_runtime_events_type'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_runtime_events_occurred_at', 'runtime_events', ['occurred_at'], unique=False)
    op.create_index('ix_runtime_events_type_occurred', 'runtime_events', ['event_type', 'occurred_at'], unique=False)
    op.create_index('ix_runtime_events_user_id', 'runtime_events', ['user_id'], unique=False)

    op.create_table('uploaded_avatar_assets',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('object_key', sa.String(length=512), nullable=False),
    sa.Column('content_type', sa.String(length=64), nullable=False),
    sa.Column('byte_size', sa.Integer(), nullable=False),
    sa.Column('width', sa.Integer(), nullable=False),
    sa.Column('height', sa.Integer(), nullable=False),
    sa.Column('checksum_sha256', sa.String(length=64), nullable=False),
    sa.Column('payload', sa.LargeBinary(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.CheckConstraint('byte_size > 0 AND byte_size <= 131072', name='ck_uploaded_avatar_assets_byte_size'),
    sa.CheckConstraint('width > 0 AND height > 0', name='ck_uploaded_avatar_assets_dimensions'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id')
    )
    op.create_index('ix_uploaded_avatar_assets_object_key', 'uploaded_avatar_assets', ['object_key'], unique=False)

    op.create_table('user_blocks',
    sa.Column('blocker_user_id', sa.Uuid(), nullable=False),
    sa.Column('blocked_user_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.CheckConstraint('blocker_user_id != blocked_user_id', name='chk_no_self_block'),
    sa.ForeignKeyConstraint(['blocked_user_id'], ['users.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['blocker_user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('blocker_user_id', 'blocked_user_id')
    )
    op.create_index('ix_user_blocks_blocked_user_id', 'user_blocks', ['blocked_user_id'], unique=False)

    op.create_table('user_settings',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('theme', sa.String(length=16), server_default='system', nullable=False),
    sa.Column('sound_effects', sa.Boolean(), server_default=sa.true(), nullable=False),
    sa.Column('confetti_effects', sa.Boolean(), server_default=sa.true(), nullable=False),
    sa.Column('sound_effects_volume', sa.Float(), server_default=sa.text('0.7'), nullable=False),
    sa.Column('brush_cursor', sa.String(length=16), server_default='crosshair', nullable=False),
    sa.Column('key_bindings', sa.JSON(none_as_null=True).with_variant(postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), 'postgresql'), server_default=sa.text('\'{"brush":["p","1"],"fill":["f","2"],"eraser":["e","3"],"rectangle":["r","4"],"triangle":["t","5"],"ellipse":["c","6"],"brushDecrease":["["],"brushIncrease":["]"],"undo":["z"]}\''), nullable=False),
    sa.Column('colorblind_safe_colors', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.Column('time_format', sa.String(length=8), server_default='system', nullable=False),
    sa.Column('email_reminder_last_shown_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.CheckConstraint("brush_cursor IN ('crosshair', 'circle')", name='ck_user_settings_brush_cursor'),
    sa.CheckConstraint("theme IN ('light', 'dark', 'system')", name='ck_user_settings_theme'),
    sa.CheckConstraint("time_format IN ('system', '12h', '24h')", name='ck_user_settings_time_format'),
    sa.CheckConstraint('sound_effects_volume >= 0.0 AND sound_effects_volume <= 1.0', name='ck_user_settings_volume'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id')
    )
    op.create_table('user_stats_daily',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('stat_date', sa.Date(), nullable=False),
    sa.Column('games_played', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('games_won', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('total_score', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('turns_played', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('prompts_guessed', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('drawings_made', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('reactions_received', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.CheckConstraint('games_played >= 0 AND games_won >= 0 AND games_won <= games_played AND turns_played >= 0 AND prompts_guessed >= 0 AND drawings_made >= 0 AND reactions_received >= 0', name='ck_user_stats_daily_nonnegative'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'stat_date')
    )
    op.create_index('ix_user_stats_daily_stat_date', 'user_stats_daily', ['stat_date'], unique=False)

    op.create_table('prompt_content_reports',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('reporter_user_id', sa.Uuid(), nullable=True),
    sa.Column('reported_owner_user_id', sa.Uuid(), nullable=True),
    sa.Column('prompt_list_id', sa.Uuid(), nullable=True),
    sa.Column('prompt_version_id', sa.Uuid(), nullable=True),
    sa.Column('target_type', sa.String(length=16), nullable=False),
    sa.Column('list_name_snapshot', sa.String(length=64), nullable=False),
    sa.Column('prompt_snapshot', sa.String(length=64), nullable=True),
    sa.Column('reason', sa.String(length=32), nullable=False),
    sa.Column('details', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=16), server_default='pending', nullable=False),
    sa.Column('reviewed_by_user_id', sa.Uuid(), nullable=True),
    sa.Column('resolution_note', sa.Text(), nullable=True),
    sa.Column('resolution_moderation_state', sa.String(length=16), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("(target_type = 'list' AND prompt_snapshot IS NULL) OR (target_type = 'prompt' AND prompt_snapshot IS NOT NULL)", name='ck_prompt_content_reports_target_snapshot'),
    sa.CheckConstraint("reason IN ('inappropriate', 'hateful_or_abusive', 'sexual_content', 'violence', 'spam', 'other')", name='ck_prompt_content_reports_reason'),
    sa.CheckConstraint("resolution_moderation_state IN ('active', 'under_review', 'hidden')", name='ck_prompt_content_reports_resolution_state'),
    sa.CheckConstraint("status = 'pending' OR reviewed_at IS NOT NULL", name='ck_prompt_content_reports_reviewed_identity'),
    sa.CheckConstraint("status IN ('pending', 'resolved', 'dismissed')", name='ck_prompt_content_reports_status'),
    sa.CheckConstraint("target_type IN ('list', 'prompt')", name='ck_prompt_content_reports_target_type'),
    sa.CheckConstraint('reporter_user_id IS NULL OR reported_owner_user_id IS NULL OR reporter_user_id != reported_owner_user_id', name='ck_prompt_content_reports_not_self'),
    sa.ForeignKeyConstraint(['prompt_list_id'], ['prompt_lists.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['prompt_version_id'], ['prompt_versions.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['reported_owner_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['reporter_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['reviewed_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_prompt_content_reports_prompt_list_id', 'prompt_content_reports', ['prompt_list_id'], unique=False)
    op.create_index('ix_prompt_content_reports_prompt_version_id', 'prompt_content_reports', ['prompt_version_id'], unique=False)
    op.create_index('ix_prompt_content_reports_reported_owner_user_id', 'prompt_content_reports', ['reported_owner_user_id'], unique=False)
    op.create_index('ix_prompt_content_reports_reporter_user_id', 'prompt_content_reports', ['reporter_user_id'], unique=False)
    op.create_index('ix_prompt_content_reports_reviewed_by_user_id', 'prompt_content_reports', ['reviewed_by_user_id'], unique=False)
    op.create_index('ix_prompt_content_reports_status_created_at', 'prompt_content_reports', ['status', 'created_at'], unique=False)
    op.create_index('uq_prompt_content_reports_open_list', 'prompt_content_reports', ['reporter_user_id', 'prompt_list_id'], unique=True, postgresql_where=sa.text("status = 'pending' AND prompt_version_id IS NULL"), sqlite_where=sa.text("status = 'pending' AND prompt_version_id IS NULL"))
    op.create_index('uq_prompt_content_reports_open_prompt', 'prompt_content_reports', ['reporter_user_id', 'prompt_version_id'], unique=True, postgresql_where=sa.text("status = 'pending' AND prompt_version_id IS NOT NULL"), sqlite_where=sa.text("status = 'pending' AND prompt_version_id IS NOT NULL"))

    op.create_table('prompt_list_localizations',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('prompt_list_id', sa.Uuid(), nullable=False),
    sa.Column('locale', sa.String(length=16), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('description', sa.String(length=255), server_default='', nullable=False),
    sa.CheckConstraint("locale IN ('en', 'de', 'es', 'fr', 'it', 'nl', 'pt')", name='ck_prompt_list_localizations_locale'),
    sa.ForeignKeyConstraint(['prompt_list_id'], ['prompt_lists.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('prompt_list_id', 'locale', name='uq_prompt_list_localization_locale')
    )
    op.create_table('prompt_list_revisions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('prompt_list_id', sa.Uuid(), nullable=False),
    sa.Column('forked_from_revision_id', sa.Uuid(), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('language', sa.String(length=16), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('letter_counts', sa.JSON(none_as_null=True).with_variant(postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), 'postgresql'), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('letter_total', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.CheckConstraint("language IN ('en', 'de', 'es', 'fr', 'it', 'nl', 'pt')", name='ck_prompt_list_revisions_language'),
    sa.CheckConstraint('version >= 1', name='ck_prompt_list_revisions_version_positive'),
    sa.ForeignKeyConstraint(['forked_from_revision_id'], ['prompt_list_revisions.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['prompt_list_id'], ['prompt_lists.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('prompt_list_id', 'version', name='uq_prompt_list_revision_version')
    )
    op.create_index('ix_prompt_list_revisions_forked_from_revision_id', 'prompt_list_revisions', ['forked_from_revision_id'], unique=False)

    op.create_table('prompt_version_aliases',
    sa.Column('prompt_version_id', sa.Uuid(), nullable=False),
    sa.Column('alias_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['alias_id'], ['prompt_aliases.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['prompt_version_id'], ['prompt_versions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('prompt_version_id', 'alias_id')
    )
    op.create_index('ix_prompt_version_aliases_alias_id', 'prompt_version_aliases', ['alias_id'], unique=False)

    op.create_table('prompt_version_tags',
    sa.Column('prompt_version_id', sa.Uuid(), nullable=False),
    sa.Column('tag_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['prompt_version_id'], ['prompt_versions.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tag_id'], ['prompt_tags.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('prompt_version_id', 'tag_id')
    )
    op.create_index('ix_prompt_version_tags_tag_id', 'prompt_version_tags', ['tag_id'], unique=False)

    op.create_table('prompts',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('prompt_list_id', sa.Uuid(), nullable=False),
    sa.Column('concept_id', sa.Uuid(), nullable=False),
    sa.Column('prompt_version_id', sa.Uuid(), nullable=False),
    sa.Column('text', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['concept_id'], ['prompt_concepts.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['prompt_list_id'], ['prompt_lists.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['prompt_version_id'], ['prompt_versions.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('prompt_list_id', 'concept_id', name='uq_prompt_list_concept'),
    sa.UniqueConstraint('prompt_list_id', 'text', name='uq_prompt_list_text')
    )
    op.create_index('ix_prompts_concept_id', 'prompts', ['concept_id'], unique=False)
    op.create_index('ix_prompts_prompt_version_id', 'prompts', ['prompt_version_id'], unique=False)

    op.create_table('turn_records',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('game_id', sa.Uuid(), nullable=False),
    sa.Column('round_number', sa.Integer(), nullable=False),
    sa.Column('turn_number', sa.Integer(), nullable=False),
    sa.Column('drawer_user_id', sa.Uuid(), nullable=True),
    sa.Column('drawer_participant_id', sa.Uuid(), nullable=False),
    sa.Column('drawer_display_name_snapshot', sa.String(length=32), nullable=False),
    sa.Column('drawer_name_color_snapshot', sa.String(length=16), nullable=True),
    sa.Column('drawer_is_anonymous_snapshot', sa.Boolean(), nullable=False),
    sa.Column('prompt', sa.String(length=64), nullable=False),
    sa.Column('prompt_version_id', sa.Uuid(), nullable=True),
    sa.Column('prompt_source_kind', sa.String(length=24), nullable=False),
    sa.Column('duration_seconds', sa.Float(), nullable=False),
    sa.Column('guesser_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('prompt_auto_picked', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.Column('stroke_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('end_reason', sa.String(length=16), server_default='timeout', nullable=False),
    sa.Column('wrong_guess_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('near_miss_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.CheckConstraint("(prompt_source_kind = 'curated' AND prompt_version_id IS NOT NULL) OR (prompt_source_kind != 'curated' AND prompt_version_id IS NULL)", name='ck_turn_records_prompt_identity'),
    sa.CheckConstraint("end_reason IN ('all_guessed', 'timeout')", name='ck_turn_records_end_reason'),
    sa.CheckConstraint("prompt_source_kind IN ('curated', 'custom', 'builtin_fallback')", name='ck_turn_records_prompt_source_kind'),
    sa.CheckConstraint('duration_seconds > 0', name='ck_turn_records_duration'),
    sa.CheckConstraint('round_number >= 1 AND turn_number >= 1 AND guesser_count >= 0 AND wrong_guess_count >= 0 AND near_miss_count >= 0 AND stroke_count >= 0', name='ck_turn_records_counts_nonnegative'),
    sa.ForeignKeyConstraint(['drawer_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['game_id', 'drawer_participant_id'], ['game_participants.game_id', 'game_participants.id'], name='fk_turn_records_drawer_seat_same_game', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['game_id'], ['game_records.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['prompt_version_id'], ['prompt_versions.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('game_id', 'id', name='uq_turn_records_game_id_id')
    )
    op.create_index('ix_turn_records_drawer_participant_id', 'turn_records', ['drawer_participant_id'], unique=False)
    op.create_index('ix_turn_records_drawer_user_id', 'turn_records', ['drawer_user_id'], unique=False)
    op.create_index('ix_turn_records_prompt_version_id', 'turn_records', ['prompt_version_id'], unique=False)
    op.create_index('uq_turn_records_game_round_turn', 'turn_records', ['game_id', 'round_number', 'turn_number'], unique=True)

    op.create_table('game_prompt_sources',
    sa.Column('game_id', sa.Uuid(), nullable=False),
    sa.Column('prompt_list_revision_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['game_id'], ['game_records.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['prompt_list_revision_id'], ['prompt_list_revisions.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('game_id', 'prompt_list_revision_id')
    )
    op.create_index('ix_game_prompt_sources_prompt_list_revision_id', 'game_prompt_sources', ['prompt_list_revision_id'], unique=False)

    op.create_table('player_reports',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('reporter_user_id', sa.Uuid(), nullable=True),
    sa.Column('reported_user_id', sa.Uuid(), nullable=True),
    sa.Column('game_id', sa.Uuid(), nullable=True),
    sa.Column('turn_id', sa.Uuid(), nullable=True),
    sa.Column('reason', sa.String(length=32), nullable=False),
    sa.Column('details', sa.Text(), nullable=False),
    sa.Column('context_snapshot', sa.JSON(none_as_null=True).with_variant(postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), 'postgresql'), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('status', sa.String(length=16), server_default='pending', nullable=False),
    sa.Column('reviewed_by_user_id', sa.Uuid(), nullable=True),
    sa.Column('resolution_note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("reason IN ('harassment', 'offensive_drawing', 'inappropriate_name', 'cheating', 'spam', 'inappropriate_avatar')", name='ck_player_reports_reason'),
    sa.CheckConstraint("status = 'pending' OR reviewed_at IS NOT NULL", name='ck_player_reports_reviewed_identity'),
    sa.CheckConstraint("status IN ('pending', 'resolved', 'dismissed')", name='ck_player_reports_status'),
    sa.CheckConstraint('reporter_user_id IS NULL OR reported_user_id IS NULL OR reporter_user_id != reported_user_id', name='ck_player_reports_not_self'),
    sa.ForeignKeyConstraint(['game_id'], ['game_records.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['reported_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['reporter_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['reviewed_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['turn_id'], ['turn_records.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_player_reports_game_id', 'player_reports', ['game_id'], unique=False)
    op.create_index('ix_player_reports_reported_user_id', 'player_reports', ['reported_user_id'], unique=False)
    op.create_index('ix_player_reports_reporter_user_id', 'player_reports', ['reporter_user_id'], unique=False)
    op.create_index('ix_player_reports_reviewed_by_user_id', 'player_reports', ['reviewed_by_user_id'], unique=False)
    op.create_index('ix_player_reports_status_created_at', 'player_reports', ['status', 'created_at'], unique=False)
    op.create_index('ix_player_reports_turn_id', 'player_reports', ['turn_id'], unique=False)
    op.create_index('uq_player_reports_open_target', 'player_reports', ['reporter_user_id', 'reported_user_id'], unique=True, postgresql_where=sa.text("status = 'pending'"), sqlite_where=sa.text("status = 'pending'"))

    op.create_table('prompt_list_revision_items',
    sa.Column('revision_id', sa.Uuid(), nullable=False),
    sa.Column('prompt_version_id', sa.Uuid(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.CheckConstraint('position >= 0', name='ck_prompt_list_revision_items_position_nonnegative'),
    sa.ForeignKeyConstraint(['prompt_version_id'], ['prompt_versions.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['revision_id'], ['prompt_list_revisions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('revision_id', 'prompt_version_id'),
    sa.UniqueConstraint('revision_id', 'position', name='uq_prompt_list_revision_item_position')
    )
    op.create_index('ix_prompt_list_revision_items_prompt_version_id', 'prompt_list_revision_items', ['prompt_version_id'], unique=False)

    op.create_table('prompt_list_revision_tags',
    sa.Column('revision_id', sa.Uuid(), nullable=False),
    sa.Column('tag_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['revision_id'], ['prompt_list_revisions.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tag_id'], ['prompt_tags.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('revision_id', 'tag_id')
    )
    op.create_index('ix_prompt_list_revision_tags_tag_id', 'prompt_list_revision_tags', ['tag_id'], unique=False)

    op.create_table('prompt_usage_facts',
    sa.Column('batch_id', sa.Uuid(), nullable=False),
    sa.Column('prompt_list_revision_id', sa.Uuid(), nullable=False),
    sa.Column('prompt_version_id', sa.Uuid(), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('scoring_mode', sa.String(length=16), nullable=False),
    sa.Column('hint_mode', sa.String(length=16), nullable=False),
    sa.Column('offer_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('pick_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('correct_guess_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('total_guesser_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.CheckConstraint("hint_mode IN ('none', 'checkpoints', 'purchase', 'wheel')", name='ck_prompt_usage_facts_hint_mode'),
    sa.CheckConstraint("scoring_mode IN ('none', 'default', 'pressure')", name='ck_prompt_usage_facts_scoring_mode'),
    sa.CheckConstraint('correct_guess_count <= total_guesser_count', name='ck_prompt_usage_facts_correct_within_guessers'),
    sa.CheckConstraint('correct_guess_count >= 0', name='ck_prompt_usage_facts_correct_guesses'),
    sa.CheckConstraint('offer_count >= 0', name='ck_prompt_usage_facts_offers'),
    sa.CheckConstraint('pick_count <= offer_count', name='ck_prompt_usage_facts_picks_within_offers'),
    sa.CheckConstraint('pick_count >= 0', name='ck_prompt_usage_facts_picks'),
    sa.CheckConstraint('total_guesser_count >= 0', name='ck_prompt_usage_facts_total_guessers'),
    sa.ForeignKeyConstraint(['prompt_list_revision_id'], ['prompt_list_revisions.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['prompt_version_id'], ['prompt_versions.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('batch_id', 'prompt_list_revision_id', 'prompt_version_id')
    )
    op.create_index('ix_prompt_usage_facts_revision_occurred_at', 'prompt_usage_facts', ['prompt_list_revision_id', 'occurred_at'], unique=False)
    op.create_index('ix_prompt_usage_facts_version_occurred_at', 'prompt_usage_facts', ['prompt_version_id', 'occurred_at'], unique=False)

    op.create_table('score_events',
    sa.Column('game_id', sa.Uuid(), nullable=False),
    sa.Column('event_order', sa.Integer(), nullable=False),
    sa.Column('participant_id', sa.Uuid(), nullable=False),
    sa.Column('turn_id', sa.Uuid(), nullable=True),
    sa.Column('event_type', sa.String(length=24), nullable=False),
    sa.Column('points_delta', sa.Integer(), nullable=False),
    sa.Column('corrects_event_order', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.CheckConstraint("(event_type = 'correction' AND corrects_event_order IS NOT NULL) OR (event_type != 'correction' AND corrects_event_order IS NULL)", name='ck_score_events_correction_target'),
    sa.CheckConstraint("(event_type IN ('guess_award', 'drawer_bonus') AND points_delta > 0) OR (event_type = 'hint_charge' AND points_delta < 0) OR event_type = 'correction'", name='ck_score_events_delta_direction'),
    sa.CheckConstraint("event_type = 'correction' OR turn_id IS NOT NULL", name='ck_score_events_turn_required'),
    sa.CheckConstraint("event_type IN ('guess_award', 'hint_charge', 'drawer_bonus', 'correction')", name='ck_score_events_event_type'),
    sa.CheckConstraint('corrects_event_order IS NULL OR corrects_event_order < event_order', name='ck_score_events_corrects_earlier'),
    sa.CheckConstraint('event_order > 0', name='ck_score_events_order_positive'),
    sa.CheckConstraint('points_delta != 0', name='ck_score_events_delta_nonzero'),
    sa.ForeignKeyConstraint(['game_id', 'corrects_event_order'], ['score_events.game_id', 'score_events.event_order'], name='fk_score_events_correction_same_game', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['game_id', 'participant_id'], ['game_participants.game_id', 'game_participants.id'], name='fk_score_events_seat_same_game', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['game_id', 'turn_id'], ['turn_records.game_id', 'turn_records.id'], name='fk_score_events_turn_same_game', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['game_id'], ['game_records.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('game_id', 'event_order')
    )
    op.create_index('ix_score_events_correction', 'score_events', ['game_id', 'corrects_event_order'], unique=False, postgresql_where=sa.text('corrects_event_order IS NOT NULL'), sqlite_where=sa.text('corrects_event_order IS NOT NULL'))
    op.create_index('ix_score_events_participant_id', 'score_events', ['participant_id'], unique=False)
    op.create_index('ix_score_events_turn_id', 'score_events', ['turn_id'], unique=False)

    op.create_table('turn_drawing_reactions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('game_id', sa.Uuid(), nullable=False),
    sa.Column('turn_id', sa.Uuid(), nullable=False),
    sa.Column('participant_id', sa.Uuid(), nullable=False),
    sa.Column('emoji', sa.String(length=16), nullable=False),
    sa.Column('set_version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.CheckConstraint("emoji IN ('heart', 'laugh', 'wow', 'fire')", name='ck_turn_drawing_reactions_emoji'),
    sa.CheckConstraint('set_version >= 1', name='ck_turn_drawing_reactions_set_version'),
    sa.ForeignKeyConstraint(['game_id', 'participant_id'], ['game_participants.game_id', 'game_participants.id'], name='fk_turn_drawing_reactions_seat_same_game', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['game_id', 'turn_id'], ['turn_records.game_id', 'turn_records.id'], name='fk_turn_drawing_reactions_turn_same_game', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('turn_id', 'participant_id', name='uq_turn_drawing_reactions_turn_participant')
    )
    op.create_index('ix_turn_drawing_reactions_game_id', 'turn_drawing_reactions', ['game_id'], unique=False)
    op.create_index('ix_turn_drawing_reactions_participant_id', 'turn_drawing_reactions', ['participant_id'], unique=False)

    op.create_table('turn_drawings',
    sa.Column('turn_id', sa.Uuid(), nullable=False),
    sa.Column('game_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('format_magic', sa.String(length=4), nullable=True),
    sa.Column('format_version', sa.Integer(), nullable=True),
    sa.Column('payload', sa.LargeBinary(), nullable=True),
    sa.Column('byte_size', sa.Integer(), nullable=True),
    sa.Column('checksum_sha256', sa.String(length=64), nullable=True),
    sa.Column('object_key', sa.String(length=256), nullable=True),
    sa.Column('unavailable_reason', sa.String(length=32), nullable=True),
    sa.Column('failure_code', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('stored_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("(status = 'unavailable') = (unavailable_reason IS NOT NULL)", name='ck_turn_drawings_unavailable_reason'),
    sa.CheckConstraint("status <> 'deleted' OR deleted_at IS NOT NULL", name='ck_turn_drawings_deleted_at'),
    sa.CheckConstraint("status <> 'ready' OR (format_magic IS NOT NULL AND format_version IS NOT NULL AND byte_size IS NOT NULL AND checksum_sha256 IS NOT NULL AND (payload IS NOT NULL OR object_key IS NOT NULL))", name='ck_turn_drawings_ready_identity'),
    sa.CheckConstraint("status <> 'ready' OR stored_at IS NOT NULL", name='ck_turn_drawings_ready_stored_at'),
    sa.CheckConstraint("status IN ('pending', 'ready', 'unavailable', 'failed', 'deleted')", name='ck_turn_drawings_status'),
    sa.CheckConstraint("status NOT IN ('unavailable', 'deleted') OR (payload IS NULL AND object_key IS NULL)", name='ck_turn_drawings_erased'),
    sa.CheckConstraint('byte_size IS NULL OR (byte_size > 0 AND byte_size <= 8388608)', name='ck_turn_drawings_byte_size'),
    sa.CheckConstraint('payload IS NULL OR byte_size IS NULL OR length(payload) = byte_size', name='ck_turn_drawings_byte_size_matches'),
    sa.ForeignKeyConstraint(['game_id', 'turn_id'], ['turn_records.game_id', 'turn_records.id'], name='fk_turn_drawings_turn_same_game', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['game_id'], ['game_records.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['turn_id'], ['turn_records.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('turn_id')
    )
    op.create_index('ix_turn_drawings_game_id', 'turn_drawings', ['game_id'], unique=False)
    op.create_index('ix_turn_drawings_status_created_at', 'turn_drawings', ['status', 'created_at'], unique=False)

    op.create_table('turn_participant_outcomes',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('game_id', sa.Uuid(), nullable=False),
    sa.Column('turn_id', sa.Uuid(), nullable=False),
    sa.Column('participant_id', sa.Uuid(), nullable=False),
    sa.Column('eligible', sa.Boolean(), nullable=False),
    sa.Column('eligibility_reason', sa.String(length=24), nullable=False),
    sa.Column('outcome', sa.String(length=16), nullable=False),
    sa.Column('terminal_state', sa.String(length=24), nullable=False),
    sa.Column('correct_guess_time_seconds', sa.Float(), nullable=True),
    sa.Column('wrong_guess_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('near_miss_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('hints_used', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('points_spent_on_hints', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.CheckConstraint("(eligible AND eligibility_reason = 'eligible' AND outcome != 'ineligible') OR (NOT eligible AND eligibility_reason != 'eligible' AND outcome = 'ineligible')", name='ck_turn_participant_outcomes_eligibility'),
    sa.CheckConstraint("(outcome = 'correct' AND correct_guess_time_seconds IS NOT NULL) OR (outcome != 'correct' AND correct_guess_time_seconds IS NULL)", name='ck_turn_participant_outcomes_correct_time'),
    sa.CheckConstraint("eligibility_reason IN ('eligible', 'afk', 'disconnected', 'joined_late')", name='ck_turn_participant_outcomes_eligibility_reason'),
    sa.CheckConstraint("outcome IN ('correct', 'incorrect', 'no_attempt', 'ineligible')", name='ck_turn_participant_outcomes_outcome'),
    sa.CheckConstraint("terminal_state IN ('active', 'afk', 'disconnected', 'left')", name='ck_turn_participant_outcomes_terminal_state'),
    sa.CheckConstraint('wrong_guess_count >= 0 AND near_miss_count >= 0 AND hints_used >= 0 AND points_spent_on_hints >= 0', name='ck_turn_participant_outcomes_nonnegative'),
    sa.ForeignKeyConstraint(['game_id', 'participant_id'], ['game_participants.game_id', 'game_participants.id'], name='fk_turn_participant_outcomes_seat_same_game', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['game_id', 'turn_id'], ['turn_records.game_id', 'turn_records.id'], name='fk_turn_participant_outcomes_turn_same_game', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('turn_id', 'id', name='uq_turn_participant_outcomes_turn_id_id'),
    sa.UniqueConstraint('turn_id', 'participant_id', name='uq_turn_participant_outcomes_turn_participant')
    )
    op.create_index('ix_turn_participant_outcomes_participant_id', 'turn_participant_outcomes', ['participant_id'], unique=False)

    op.create_table('turn_prompt_offers',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('turn_id', sa.Uuid(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('prompt_version_id', sa.Uuid(), nullable=True),
    sa.Column('prompt_snapshot', sa.String(length=64), nullable=False),
    sa.Column('selected', sa.Boolean(), nullable=False),
    sa.Column('source_kind', sa.String(length=24), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.CheckConstraint("(source_kind = 'curated') = (prompt_version_id IS NOT NULL)", name='ck_turn_prompt_offers_curated_version'),
    sa.CheckConstraint("source_kind IN ('curated', 'custom', 'builtin_fallback')", name='ck_turn_prompt_offers_source_kind'),
    sa.CheckConstraint('position >= 0', name='ck_turn_prompt_offers_position'),
    sa.ForeignKeyConstraint(['prompt_version_id'], ['prompt_versions.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['turn_id'], ['turn_records.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('turn_id', 'position', name='uq_turn_prompt_offers_turn_position')
    )
    op.create_index('ix_turn_prompt_offers_prompt_version_id', 'turn_prompt_offers', ['prompt_version_id'], unique=False)
    op.create_index('uq_turn_prompt_offers_selected', 'turn_prompt_offers', ['turn_id'], unique=True, sqlite_where=sa.text('selected = 1'), postgresql_where=sa.text('selected'))

    op.create_table('player_report_drawing_evidence',
    sa.Column('report_id', sa.Uuid(), nullable=False),
    sa.Column('turn_id_snapshot', sa.Uuid(), nullable=False),
    sa.Column('round_number', sa.Integer(), nullable=False),
    sa.Column('prompt_snapshot', sa.String(length=64), nullable=False),
    sa.Column('action_count', sa.Integer(), nullable=False),
    sa.Column('format_magic', sa.String(length=4), nullable=False),
    sa.Column('format_version', sa.Integer(), nullable=False),
    sa.Column('payload', sa.LargeBinary(), nullable=False),
    sa.Column('byte_size', sa.Integer(), nullable=False),
    sa.Column('checksum_sha256', sa.String(length=64), nullable=False),
    sa.Column('captured_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.CheckConstraint('byte_size > 0 AND byte_size <= 8388608', name='ck_report_drawing_evidence_byte_size'),
    sa.CheckConstraint('round_number >= 1 AND action_count >= 0', name='ck_report_drawing_evidence_counts'),
    sa.ForeignKeyConstraint(['report_id'], ['player_reports.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('report_id')
    )
    op.create_table('player_report_message_evidence',
    sa.Column('report_id', sa.Uuid(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('role', sa.String(length=16), server_default='cited', nullable=False),
    sa.Column('source_message_id', sa.Uuid(), nullable=True),
    sa.Column('source_message_snapshot_id', sa.Uuid(), nullable=False),
    sa.Column('game_id_snapshot', sa.Uuid(), nullable=True),
    sa.Column('turn_id_snapshot', sa.Uuid(), nullable=True),
    sa.Column('sender_user_id', sa.Uuid(), nullable=True),
    sa.Column('sender_display_name_snapshot', sa.String(length=32), nullable=False),
    sa.Column('sender_name_color_snapshot', sa.String(length=16), nullable=True),
    sa.Column('sender_is_anonymous_snapshot', sa.Boolean(), nullable=False),
    sa.Column('message_kind', sa.String(length=24), nullable=False),
    sa.Column('audience', sa.String(length=24), nullable=False),
    sa.Column('near_miss_kind', sa.String(length=16), nullable=True),
    sa.Column('text_snapshot', sa.Text(), nullable=False),
    sa.Column('message_created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('copied_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.CheckConstraint("audience IN ('room', 'prompt_aware', 'lobby')", name='ck_report_message_evidence_audience'),
    sa.CheckConstraint("message_kind = 'wrong_guess' OR near_miss_kind IS NULL", name='ck_report_message_evidence_near_miss_only_for_wrong_guess'),
    sa.CheckConstraint("message_kind IN ('chat', 'wrong_guess', 'correct_guess')", name='ck_report_message_evidence_kind'),
    sa.CheckConstraint("near_miss_kind IN ('close', 'partial')", name='ck_report_message_evidence_near_miss_kind'),
    sa.CheckConstraint("role IN ('cited', 'context')", name='ck_report_message_evidence_role'),
    sa.CheckConstraint('position >= 0', name='ck_report_message_evidence_position'),
    sa.ForeignKeyConstraint(['report_id'], ['player_reports.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['sender_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['source_message_id'], ['room_messages.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('report_id', 'position'),
    sa.UniqueConstraint('report_id', 'source_message_snapshot_id', name='uq_report_message_evidence_source')
    )
    op.create_index('ix_player_report_message_evidence_sender_user_id', 'player_report_message_evidence', ['sender_user_id'], unique=False)
    op.create_index('ix_player_report_message_evidence_source_message_id', 'player_report_message_evidence', ['source_message_id'], unique=False)

    op.create_table('turn_guesses',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('turn_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=True),
    sa.Column('participant_id', sa.Uuid(), nullable=True),
    sa.Column('outcome_id', sa.Uuid(), nullable=False),
    sa.Column('display_name_snapshot', sa.String(length=32), nullable=False),
    sa.Column('name_color_snapshot', sa.String(length=16), nullable=True),
    sa.Column('is_anonymous_snapshot', sa.Boolean(), nullable=False),
    sa.Column('points_awarded', sa.Integer(), nullable=False),
    sa.Column('guess_time_seconds', sa.Float(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['participant_id'], ['game_participants.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['turn_id', 'outcome_id'], ['turn_participant_outcomes.turn_id', 'turn_participant_outcomes.id'], name='fk_turn_guesses_outcome_same_turn', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['turn_id'], ['turn_records.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_turn_guesses_participant_id', 'turn_guesses', ['participant_id'], unique=False)
    op.create_index('ix_turn_guesses_user_id', 'turn_guesses', ['user_id'], unique=False)
    op.create_index('uq_turn_guesses_outcome', 'turn_guesses', ['outcome_id'], unique=True)
    op.create_index('uq_turn_guesses_turn_participant', 'turn_guesses', ['turn_id', 'participant_id'], unique=True)

    op.create_table('turn_prompt_offer_sources',
    sa.Column('offer_id', sa.Uuid(), nullable=False),
    sa.Column('prompt_list_revision_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['offer_id'], ['turn_prompt_offers.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['prompt_list_revision_id'], ['prompt_list_revisions.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('offer_id', 'prompt_list_revision_id')
    )
    op.create_index('ix_turn_prompt_offer_sources_prompt_list_revision_id', 'turn_prompt_offer_sources', ['prompt_list_revision_id'], unique=False)

    op.create_table('user_bans',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=True),
    sa.Column('banned_by_user_id', sa.Uuid(), nullable=True),
    sa.Column('reason', sa.String(length=255), nullable=False),
    sa.Column('source_report_id', sa.Uuid(), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_by_user_id', sa.Uuid(), nullable=True),
    sa.Column('revoke_reason', sa.String(length=255), nullable=True),
    sa.CheckConstraint('expires_at IS NULL OR expires_at > created_at', name='ck_user_bans_expiry_after_creation'),
    sa.CheckConstraint('revoked_at IS NOT NULL OR (revoked_by_user_id IS NULL AND revoke_reason IS NULL)', name='ck_user_bans_revocation_identity'),
    sa.ForeignKeyConstraint(['banned_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['revoked_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['source_report_id'], ['player_reports.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_user_bans_banned_by_user_id', 'user_bans', ['banned_by_user_id'], unique=False)
    op.create_index('ix_user_bans_revoked_by', 'user_bans', ['revoked_by_user_id'], unique=False, postgresql_where=sa.text('revoked_by_user_id IS NOT NULL'), sqlite_where=sa.text('revoked_by_user_id IS NOT NULL'))
    op.create_index('ix_user_bans_source_report_id', 'user_bans', ['source_report_id'], unique=False)
    op.create_index('ix_user_bans_unrevoked_newest', 'user_bans', ['created_at'], unique=False, postgresql_where=sa.text('revoked_at IS NULL'), sqlite_where=sa.text('revoked_at IS NULL'))
    op.create_index('ix_user_bans_user_expires', 'user_bans', ['user_id', 'expires_at'], unique=False)

    op.create_table('user_warnings',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=True),
    sa.Column('issued_by_user_id', sa.Uuid(), nullable=True),
    sa.Column('reason', sa.String(length=255), nullable=False),
    sa.Column('source_report_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['issued_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['source_report_id'], ['player_reports.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_user_warnings_issued_by', 'user_warnings', ['issued_by_user_id'], unique=False, postgresql_where=sa.text('issued_by_user_id IS NOT NULL'), sqlite_where=sa.text('issued_by_user_id IS NOT NULL'))
    op.create_index('ix_user_warnings_source_report_id', 'user_warnings', ['source_report_id'], unique=False)
    op.create_index('ix_user_warnings_user_pending', 'user_warnings', ['user_id', 'acknowledged_at'], unique=False)

    _users_expression_indexes()
    _score_events_append_only()


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.execute("DROP TRIGGER trg_score_events_immutable_update")
    else:
        op.execute("DROP TRIGGER trg_score_events_immutable_update ON score_events")
        op.execute("DROP FUNCTION reject_score_event_update()")

    op.drop_table('user_warnings')

    op.drop_table('user_bans')

    op.drop_table('turn_prompt_offer_sources')

    op.drop_table('turn_guesses')

    op.drop_table('player_report_message_evidence')
    op.drop_table('player_report_drawing_evidence')

    op.drop_table('turn_prompt_offers')

    op.drop_table('turn_participant_outcomes')

    op.drop_table('turn_drawings')

    op.drop_table('turn_drawing_reactions')

    op.drop_table('score_events')

    op.drop_table('prompt_usage_facts')

    op.drop_table('prompt_list_revision_tags')

    op.drop_table('prompt_list_revision_items')

    op.drop_table('player_reports')

    op.drop_table('game_prompt_sources')

    op.drop_table('turn_records')

    op.drop_table('prompts')

    op.drop_table('prompt_version_tags')

    op.drop_table('prompt_version_aliases')

    op.drop_table('prompt_list_revisions')
    op.drop_table('prompt_list_localizations')

    op.drop_table('prompt_content_reports')

    op.drop_table('user_stats_daily')
    op.drop_table('user_settings')

    op.drop_table('user_blocks')

    op.drop_table('uploaded_avatar_assets')

    op.drop_table('runtime_events')
    op.drop_table('room_presets')

    op.drop_table('room_messages')

    op.drop_table('role_change_notices')

    op.drop_table('prompt_versions')

    op.drop_table('prompt_lists')
    op.drop_table('prompt_aliases')

    op.drop_table('identity_aliases')

    op.drop_table('game_participants')

    op.drop_table('friendships')

    op.drop_table('external_identities')

    op.drop_table('email_outbox')

    op.drop_table('data_exports')

    op.drop_table('bug_reports')

    op.drop_table('auth_tokens')

    op.drop_table('auth_sessions')

    op.drop_table('audit_events')

    op.drop_table('users')
    op.drop_table('runtime_stats_daily')

    op.drop_table('room_code_reservations')
    op.drop_table('prompt_tags')
    op.drop_table('prompt_concepts')

    op.drop_table('planned_shutdown_abandonments')

    op.drop_table('game_records')

    op.drop_table('auth_rate_limit_buckets')
    op.drop_table('app_config')
