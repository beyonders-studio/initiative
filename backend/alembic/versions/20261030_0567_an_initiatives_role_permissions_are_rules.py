"""an initiative's role permissions are its rules

In ``guild_template`` and every ``guild_<id>``, ``initiative_role_permissions``
becomes ``initiative_rules`` (see ``app.models.tenant.initiative``): one row
per role and permission key, carrying the role's initiative beside the role.
The table stays in the community's own schema, read there by the standing
statement as the old one was.

``initiative_roles`` gains a unique ``(id, initiative_id)`` for the rules'
foreign key to name, so a rule never points at another initiative's role.

The rows move one for one and are counted against their source. Both source
tables are policy-bound for this revision's role, so each is unforced for the
copy and put back as it was.

Revision ID: 20261030_0567
Revises: 20261030_0566
Create Date: 2026-10-30
"""

from collections.abc import Iterator
from contextlib import contextmanager

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261030_0567"
down_revision = "20261030_0566"
branch_labels = None
depends_on = None

#: The permission keys as they stand at this revision.
KEYS = (
    "calendars_enabled",
    "counter_groups_enabled",
    "create_calendars",
    "create_counter_groups",
    "create_dashboards",
    "create_files",
    "create_posts",
    "create_projects",
    "create_queues",
    "create_wikis",
    "dashboards_enabled",
    "dashboards_run_as_initiative",
    "files_enabled",
    "posts_enabled",
    "projects_enabled",
    "queues_enabled",
    "wikis_enabled",
)
QUOTED_KEYS = ", ".join(f"'{key}'" for key in KEYS)


@contextmanager
def _unforced(*tables: str) -> Iterator[sa.engine.Connection]:
    """Row security lifted from ``tables`` for the statements inside, and put
    back as it was."""
    bind = op.get_bind()
    forced = [
        table
        for table in tables
        if bind.execute(
            sa.text(
                "SELECT relforcerowsecurity FROM pg_class WHERE oid = to_regclass(:t)"
            ),
            {"t": table},
        ).scalar()
    ]
    for table in forced:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    yield bind
    for table in forced:
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def _check(copied: int, source: int) -> None:
    if copied != source:
        raise RuntimeError(f"initiative rules: copied {copied} of {source} rows")


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _upgrade)


def _upgrade() -> None:
    op.create_unique_constraint(
        "uq_initiative_roles_initiative", "initiative_roles", ["id", "initiative_id"]
    )
    op.create_table(
        "initiative_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("initiative_id", sa.Integer(), nullable=False),
        sa.Column("initiative_role_id", sa.Integer(), nullable=True),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.CheckConstraint(f"key IN ({QUOTED_KEYS})", name="ck_initiative_rules_key"),
        sa.ForeignKeyConstraint(
            ["initiative_id"], ["initiatives.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["initiative_role_id", "initiative_id"],
            ["initiative_roles.id", "initiative_roles.initiative_id"],
            ondelete="CASCADE",
            name="fk_initiative_rules_role",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "initiative_id",
            "key",
            "initiative_role_id",
            name="uq_initiative_rules_subject",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index(
        "ix_initiative_rules_initiative_role_id",
        "initiative_rules",
        ["initiative_role_id"],
    )
    with _unforced("initiative_role_permissions", "initiative_roles") as bind:
        source = bind.execute(
            sa.text("SELECT count(*) FROM initiative_role_permissions")
        ).scalar_one()
        bind.execute(
            sa.text(
                "INSERT INTO initiative_rules"
                " (initiative_id, initiative_role_id, key, enabled)"
                " SELECT r.initiative_id, p.initiative_role_id, p.permission_key,"
                " p.enabled"
                " FROM initiative_role_permissions p"
                " JOIN initiative_roles r ON r.id = p.initiative_role_id"
            )
        )
        copied = bind.execute(
            sa.text("SELECT count(*) FROM initiative_rules")
        ).scalar_one()
        _check(copied, source)
    op.drop_table("initiative_role_permissions")


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _downgrade)


def _downgrade() -> None:
    op.create_table(
        "initiative_role_permissions",
        sa.Column("initiative_role_id", sa.Integer(), nullable=False),
        sa.Column("permission_key", sa.String(length=50), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            f"permission_key IN ({QUOTED_KEYS})",
            name="ck_initiative_role_permissions_permission_key",
        ),
        sa.ForeignKeyConstraint(
            ["initiative_role_id"], ["initiative_roles.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("initiative_role_id", "permission_key"),
    )
    with _unforced("initiative_rules") as bind:
        source = bind.execute(
            sa.text(
                "SELECT count(*) FROM initiative_rules"
                " WHERE initiative_role_id IS NOT NULL"
            )
        ).scalar_one()
        bind.execute(
            sa.text(
                "INSERT INTO initiative_role_permissions"
                " (initiative_role_id, permission_key, enabled)"
                " SELECT initiative_role_id, key, enabled FROM initiative_rules"
                " WHERE initiative_role_id IS NOT NULL"
            )
        )
        copied = bind.execute(
            sa.text("SELECT count(*) FROM initiative_role_permissions")
        ).scalar_one()
        _check(copied, source)
    op.drop_table("initiative_rules")
    op.drop_constraint(
        "uq_initiative_roles_initiative", "initiative_roles", type_="unique"
    )
