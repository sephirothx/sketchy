"""hold a public key a relay cannot carry away

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-09-08 22:00:00.000000

A TOTP code can be read aloud, which N-15 recorded and declined to close.
`user_passkeys` closes it: a WebAuthn credential is bound to this deployment's
origin by the authenticator, so there is nothing for a person to repeat to
somebody on the phone and nothing a lookalike site can obtain.

What is stored is a **public** key, which is the difference from
`user_second_factors` worth stating in a migration: TOTP is symmetric, so that
table holds what the authenticator holds and a database read hands over a
working credential. This one holds a verifier.

`webauthn_challenges` is the other half. Both ceremonies rest on a challenge
that this server chose and that can be spent once, so it is stored rather than
carried in the page, deleted as it is read, and short-lived.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "d0e1f2a3b4c5"
down_revision: str | Sequence[str] | None = "c9d0e1f2a3b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_passkeys",
        # Base64url, as the browser sends it: the sign-in arrives naming the
        # credential, so this is what a lookup has in hand.
        sa.Column("credential_id", sa.String(255), primary_key=True),
        sa.Column("id", sa.Uuid(as_uuid=True, native_uuid=True), nullable=False),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True, native_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("public_key", sa.LargeBinary(), nullable=False),
        sa.Column("sign_count", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(64), nullable=False),
        sa.Column(
            "backed_up", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("sign_count >= 0", name="ck_user_passkeys_sign_count"),
        sa.UniqueConstraint("id", name="uq_user_passkeys_id"),
    )
    op.create_index("ix_user_passkeys_user", "user_passkeys", ["user_id"])

    op.create_table(
        "webauthn_challenges",
        sa.Column("challenge", sa.String(255), primary_key=True),
        sa.Column("purpose", sa.String(16), nullable=False),
        # Null for a sign-in: nobody has said who they are yet, and the
        # credential says it when it comes back.
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True, native_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "purpose IN ('register', 'authenticate')",
            name="ck_webauthn_challenges_purpose",
        ),
    )
    op.create_index(
        "ix_webauthn_challenges_expires_at", "webauthn_challenges", ["expires_at"]
    )
    op.create_index("ix_webauthn_challenges_user", "webauthn_challenges", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_webauthn_challenges_user", table_name="webauthn_challenges")
    op.drop_index("ix_webauthn_challenges_expires_at", table_name="webauthn_challenges")
    op.drop_table("webauthn_challenges")
    op.drop_index("ix_user_passkeys_user", table_name="user_passkeys")
    op.drop_table("user_passkeys")
