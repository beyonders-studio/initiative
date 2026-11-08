"""every author table stamps its author

``created_by_kind`` is NOT NULL on every table that names an author, and
``public.fn_set_created_by`` fills it for a write that names no author. These
tables carry the column without the trigger, so such a write is refused.

Revision ID: 20261109_0592
Revises: 20261109_0591
Create Date: 2026-11-09
"""

from alembic import op
from sqlalchemy import text

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261109_0592"
down_revision = "20261109_0591"
branch_labels = None
depends_on = None

#: The tables carrying ``created_by_kind`` without ``tr_<t>_set_created_by``.
_TABLES = (
    "custom_role_claim_rules",
    "custom_roles",
    "evidence",
    "guest_invite_grants",
    "intake_bindings",
    "moderation_actions",
    "pending_uploads",
    "posts",
    "reactions",
    "relationships",
    "wiki_pages",
    "wikis",
)


def _present() -> tuple[str, ...]:
    bind = op.get_bind()
    return tuple(
        table
        for table in _TABLES
        if bind.execute(text("SELECT to_regclass(:t)"), {"t": table}).scalar()
    )


def _upgrade() -> None:
    for table in _present():
        op.execute(
            f"CREATE OR REPLACE TRIGGER tr_{table}_set_created_by BEFORE INSERT "
            f"ON {table} FOR EACH ROW EXECUTE FUNCTION public.fn_set_created_by()"
        )


def _downgrade() -> None:
    for table in _present():
        op.execute(f"DROP TRIGGER IF EXISTS tr_{table}_set_created_by ON {table}")


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _upgrade)


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _downgrade)
