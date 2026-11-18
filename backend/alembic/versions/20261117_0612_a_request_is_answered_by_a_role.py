"""a request is answered by a role

``share_requests.scope`` may be ``role``, in ``guild_template`` and every
``guild_<id>``: changing a thing's sharing answers a pending request it reaches,
and a grant to an initiative role the requester holds is one of the ways it
can.

Revision ID: 20261117_0612
Revises: 20261116_0611
Create Date: 2026-11-17
"""

from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261117_0612"
down_revision = "20261116_0611"
branch_labels = None
depends_on = None

TABLE = "share_requests"
CHECK = "ck_share_requests_scope"


def _apply_upgrade() -> None:
    op.drop_constraint(CHECK, TABLE, type_="check")
    op.create_check_constraint(
        CHECK, TABLE, "scope IS NULL OR scope IN ('user', 'initiative', 'role')"
    )


def _apply_downgrade() -> None:
    op.drop_constraint(CHECK, TABLE, type_="check")
    # NOT VALID: a request a role answered keeps the scope it was given.
    op.execute(
        f"ALTER TABLE {TABLE} ADD CONSTRAINT {CHECK}"
        " CHECK (scope IS NULL OR scope IN ('user', 'initiative')) NOT VALID"
    )


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)
