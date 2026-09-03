"""jsonb on PostgreSQL, and a compressed export document

Every JSON column moves from PostgreSQL's text `json` to `jsonb`, which
stores a parsed form, compares, and can be GIN-indexed; SQLite is
unaffected either way. `data_exports.artifact` stops being JSON at all and
becomes gzip-compressed bytes with the encoding recorded beside them.

Revision ID: t3a7e1c5d682
Revises: s2f6d9a4b571
Create Date: 2026-08-29 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "t3a7e1c5d682"
down_revision: str | Sequence[str] | None = "s2f6d9a4b571"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Every JSON-bearing column, as (table, column, nullable).
JSON_COLUMNS: tuple[tuple[str, str, bool], ...] = (
    ("room_presets", "allowed_tools", False),
    ("room_presets", "prompt_list_ids", False),
    ("user_settings", "key_bindings", False),
    ("runtime_events", "details", True),
    ("email_outbox", "payload", False),
    ("audit_events", "details", False),
    ("player_reports", "context_snapshot", False),
    ("room_messages", "audience_user_ids", False),
    ("bug_reports", "client_context", False),
    ("bug_reports", "server_context", False),
    ("game_records", "rule_snapshot", False),
    ("prompt_list_revisions", "letter_counts", False),
)


def upgrade() -> None:
    sqlite = op.get_bind().dialect.name == "sqlite"

    # A Python None used to persist as the JSON value `null` rather than SQL
    # NULL, so rows that read as "no details" were really holding a token -
    # and a larger one than the `{}` it replaced. The type now declares
    # none_as_null; these are the rows written before it did.
    if sqlite:
        op.execute(
            "UPDATE runtime_events SET details = NULL WHERE details = 'null'"
        )
    else:
        op.execute(
            "UPDATE runtime_events SET details = NULL "
            "WHERE details::text = 'null'"
        )

    if not sqlite:
        for table, column, nullable in JSON_COLUMNS:
            op.alter_column(
                table,
                column,
                existing_type=sa.JSON(),
                type_=postgresql.JSONB(),
                existing_nullable=nullable,
                postgresql_using=f"{column}::jsonb",
            )

    # The artifact stops being JSON and becomes compressed bytes. Existing
    # documents are not converted: an export lives seven days, is regenerable
    # on request, and re-encoding one in a migration would mean parsing
    # somebody's personal data to rewrite it. Rows lose their document and
    # keep their audit line, which is the same shape a failed export takes.
    op.execute(
        "UPDATE data_exports SET artifact = NULL, status = 'failed', "
        "failure_code = 'artifact_reencoded' "
        "WHERE artifact IS NOT NULL"
    )
    with op.batch_alter_table("data_exports") as batch_op:
        batch_op.drop_column("artifact")
        batch_op.add_column(
            sa.Column("artifact", sa.LargeBinary(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("artifact_encoding", sa.String(16), nullable=True)
        )
        batch_op.create_check_constraint(
            "ck_data_exports_artifact_encoding",
            "artifact_encoding IS NULL OR artifact_encoding IN ('gzip+json')",
        )
        batch_op.create_check_constraint(
            "ck_data_exports_artifact_encoding_present",
            "(artifact IS NULL) = (artifact_encoding IS NULL)",
        )


def downgrade() -> None:
    sqlite = op.get_bind().dialect.name == "sqlite"

    op.execute(
        "UPDATE data_exports SET artifact = NULL, artifact_encoding = NULL, "
        "status = 'failed', failure_code = 'artifact_reencoded' "
        "WHERE artifact IS NOT NULL"
    )
    with op.batch_alter_table("data_exports") as batch_op:
        batch_op.drop_constraint(
            "ck_data_exports_artifact_encoding_present", type_="check"
        )
        batch_op.drop_constraint(
            "ck_data_exports_artifact_encoding", type_="check"
        )
        batch_op.drop_column("artifact_encoding")
        batch_op.drop_column("artifact")
        batch_op.add_column(sa.Column("artifact", sa.JSON(), nullable=True))

    if not sqlite:
        for table, column, nullable in JSON_COLUMNS:
            op.alter_column(
                table,
                column,
                existing_type=postgresql.JSONB(),
                type_=sa.JSON(),
                existing_nullable=nullable,
                postgresql_using=f"{column}::json",
            )
