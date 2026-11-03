"""A community holds a storage key, wrapped, when storage is encrypted.

``guild_storage_keys`` is one row per community: the key every object the
community stores is encrypted under while ``STORAGE_ENCRYPTION`` is set,
wrapped by the deployment's root — Fernet under ``SECRET_KEY``
(``local_sealed``, ``SALT_STORAGE_KEY``) or a Cloud KMS key (``kms_sealed``).
A deployment that never sets ``STORAGE_ENCRYPTION`` leaves it empty.

app_admin-only, like ``user_birthdates``: RLS enabled and forced with no
policies, and the schema's default grants revoked from the two base roles, so
no request role reads a key. The table is new and empty, so nothing is
backfilled and there is no DML to order against the lockdown.

Revision ID: 20261028_0552
Revises: 20261028_0551
Create Date: 2026-10-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20261028_0552"
down_revision = "20261028_0551"
branch_labels = None
depends_on = None


def _platform(role: str) -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_{role}"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    op.create_table(
        "guild_storage_keys",
        sa.Column("guild_id", sa.Integer(), primary_key=True),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("local_sealed", sa.Text(), nullable=True),
        sa.Column("kms_sealed", sa.Text(), nullable=True),
        sa.Column("kms_key", sa.Text(), nullable=True),
        sa.Column("backfilled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "(local_sealed IS NULL) <> (kms_sealed IS NULL)",
            name="guild_storage_keys_one_root",
        ),
        sa.CheckConstraint(
            "(kms_sealed IS NULL) = (kms_key IS NULL)",
            name="guild_storage_keys_kms_names_key",
        ),
    )

    if not _is_postgres():
        return

    base = _platform("base")
    for statement in (
        "ALTER TABLE public.guild_storage_keys ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE public.guild_storage_keys FORCE ROW LEVEL SECURITY",
        # The public schema default-grants platform_base + app_guild_base full
        # DML on every new table; both come straight back off.
        f'REVOKE ALL ON TABLE public.guild_storage_keys FROM app_guild_base, "{base}"',
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.guild_storage_keys TO app_admin",
    ):
        op.execute(statement)


def downgrade() -> None:
    op.drop_table("guild_storage_keys")
