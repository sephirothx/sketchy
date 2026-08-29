"""add selected turn prompt identity and truthful legacy provenance

Revision ID: d4b7f1a3c965
Revises: c3a6e9f2b854
Create Date: 2026-08-23 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "d4b7f1a3c965"
down_revision: str | Sequence[str] | None = "c3a6e9f2b854"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    sqlite = op.get_bind().dialect.name == "sqlite"
    if sqlite:
        # SQLite accepts an inline reference on an additive nullable column,
        # while Alembic otherwise emits a second unsupported ALTER statement.
        # Avoid batch mode here: rebuilding this parent table can cascade-delete
        # existing turn children while foreign-key enforcement is enabled.
        op.execute(
            "ALTER TABLE turn_records ADD COLUMN prompt_version_id CHAR(32) "
            "REFERENCES prompt_versions(id) ON DELETE RESTRICT"
        )
    else:
        op.add_column(
            "turn_records",
            sa.Column("prompt_version_id", sa.Uuid(), nullable=True),
        )
        op.create_foreign_key(
            "fk_turn_records_prompt_version_id_prompt_versions",
            "turn_records",
            "prompt_versions",
            ["prompt_version_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    source_kind_check = (
        "prompt_source_kind IN "
        "('legacy_unknown', 'curated', 'custom', 'builtin_fallback')"
    )
    identity_check = (
        "(prompt_source_kind = 'curated' AND prompt_version_id IS NOT NULL) "
        "OR (prompt_source_kind != 'curated' AND prompt_version_id IS NULL)"
    )
    if sqlite:
        op.execute(
            "ALTER TABLE turn_records ADD COLUMN prompt_source_kind VARCHAR(24) "
            "DEFAULT 'legacy_unknown' NOT NULL "
            "CONSTRAINT ck_turn_records_prompt_source_kind CHECK ("
            f"{source_kind_check})"
        )
        op.execute(
            "CREATE TRIGGER trg_turn_records_prompt_identity_insert "
            "BEFORE INSERT ON turn_records FOR EACH ROW WHEN NOT ("
            f"{identity_check.replace('prompt_', 'NEW.prompt_')}) "
            "BEGIN SELECT RAISE(ABORT, 'ck_turn_records_prompt_identity'); END"
        )
        op.execute(
            "CREATE TRIGGER trg_turn_records_prompt_identity_update "
            "BEFORE UPDATE OF prompt_source_kind, prompt_version_id "
            "ON turn_records FOR EACH ROW WHEN NOT ("
            f"{identity_check.replace('prompt_', 'NEW.prompt_')}) "
            "BEGIN SELECT RAISE(ABORT, 'ck_turn_records_prompt_identity'); END"
        )
    else:
        op.add_column(
            "turn_records",
            sa.Column(
                "prompt_source_kind",
                sa.String(length=24),
                server_default="legacy_unknown",
                nullable=False,
            ),
        )
        op.create_check_constraint(
            "ck_turn_records_prompt_source_kind",
            "turn_records",
            source_kind_check,
        )
        op.create_check_constraint(
            "ck_turn_records_prompt_identity",
            "turn_records",
            identity_check,
        )
    op.create_index(
        "ix_turn_records_prompt_version_id",
        "turn_records",
        ["prompt_version_id"],
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.execute("DROP TRIGGER trg_turn_records_prompt_identity_update")
        op.execute("DROP TRIGGER trg_turn_records_prompt_identity_insert")
    else:
        op.drop_constraint(
            "ck_turn_records_prompt_identity", "turn_records", type_="check"
        )
        op.drop_constraint(
            "ck_turn_records_prompt_source_kind", "turn_records", type_="check"
        )
    op.drop_index("ix_turn_records_prompt_version_id", table_name="turn_records")
    if op.get_bind().dialect.name != "sqlite":
        op.drop_constraint(
            "fk_turn_records_prompt_version_id_prompt_versions",
            "turn_records",
            type_="foreignkey",
        )
    # Batch, not plain: a later batch rebuild of turn_records re-emits this
    # column's inline FK (and any surviving named check) as table-level
    # clauses that a plain DROP COLUMN leaves dangling on SQLite.
    if op.get_bind().dialect.name == "sqlite":
        # Originally column-level and gone with the column; any later batch
        # rebuild re-emits it as a table-level constraint the rebuild below
        # would otherwise copy over the dropped column.
        inspector = sa.inspect(op.get_bind())
        if any(
            constraint.get("name") == "ck_turn_records_prompt_source_kind"
            for constraint in inspector.get_check_constraints("turn_records")
        ):
            with op.batch_alter_table("turn_records") as batch_op:
                batch_op.drop_constraint(
                    "ck_turn_records_prompt_source_kind", type_="check"
                )
    with op.batch_alter_table("turn_records") as batch_op:
        batch_op.drop_column("prompt_source_kind")
    with op.batch_alter_table("turn_records") as batch_op:
        batch_op.drop_column("prompt_version_id")
