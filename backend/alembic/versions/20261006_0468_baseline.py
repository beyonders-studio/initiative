"""Baseline: the schema the chain built at v0.75.0.

Every revision up to 20261006_0468 was collapsed into this one by
``scripts/collapse_migrations.py``. A database stamped at it or later never
runs it. A fresh one gets the group roles and memberships those revisions made
(the logins are ``app.db.bootstrap``'s), their extensions, and
``alembic/baseline/schema_0468.sql``. A database stamped before it is refused
at boot and told to start v0.75.0 first
(``app.db.init_db.check_pre_baseline_db``).

Revision ID: 20261006_0468
Revises:
Create Date: (collapsed)
"""

from pathlib import Path

from alembic import op
from app.db.guild_migrations import split_sql_statements
from sqlalchemy import text

revision = "20261006_0468"
down_revision = None
branch_labels = None
depends_on = None

#: The release this baseline was cut at: the oldest a database may come from.
release = "v0.75.0"

_SQL = Path(__file__).resolve().parents[1] / "baseline" / "schema_0468.sql"
_MARK = "@@PLATFORM_ROLE_PREFIX@@"

#: Each group role: its name and whether it inherits.
_ROLES = (
    ("app_dm_reader", True),
    ("app_guild_base", True),
    ("app_guild_base_ro", True),
    ("app_profile_reader", True),
    ("app_superadmin", True),
    ("initiative_billing", True),
    ("platform_base", True),
    ("platform_base_ro", True),
    ("platform_member", True),
    ("platform_moderator", True),
    ("platform_operator", True),
    ("platform_owner", True),
    ("platform_support", True),
    ("platform_suspended", True),
    ("plugin_install_base", True),
)

#: Each membership: role, member, and its admin, inherit and set options.
_MEMBERSHIPS = (
    ("app_dm_reader", "app_provisioner", False, True, True),
    ("app_profile_reader", "app_provisioner", False, True, True),
    ("initiative_billing", "app_user", False, False, True),
    ("platform_base", "platform_member", False, True, True),
    ("platform_base", "platform_moderator", False, True, True),
    ("platform_base", "platform_operator", False, True, True),
    ("platform_base", "platform_owner", False, True, True),
    ("platform_base", "platform_support", False, True, True),
    ("platform_base_ro", "platform_suspended", False, True, True),
    ("platform_member", "app_admin", False, False, True),
    ("platform_member", "app_user", False, False, True),
    ("platform_moderator", "app_admin", False, False, True),
    ("platform_moderator", "app_user", False, False, True),
    ("platform_operator", "app_admin", False, False, True),
    ("platform_operator", "app_user", False, False, True),
    ("platform_owner", "app_admin", False, False, True),
    ("platform_owner", "app_user", False, False, True),
    ("platform_support", "app_admin", False, False, True),
    ("platform_support", "app_user", False, False, True),
    ("platform_suspended", "app_admin", False, False, True),
    ("platform_suspended", "app_user", False, False, True),
)

#: Each extension and its schema.
_EXTENSIONS = (("pg_trgm", "public"),)

#: Operator classes ``app.db.bootstrap`` installs when it runs as a superuser.
#: An index built on one that is missing is built on the default class.
_BOOTSTRAP_OPCLASSES = ("tsvector_search_ops",)


def _prefix() -> str:
    from app.core.config import settings

    return settings.PLATFORM_ROLE_PREFIX


def _name(role: str) -> str:
    """A role as the catalog holds it (``app.db.public_rls.role_name``)."""
    prefixed = role.startswith("platform_") or role == "initiative_billing"
    return f"{_prefix()}{role}" if prefixed else role


def upgrade() -> None:
    bind = op.get_bind()
    for role, inherit in _ROLES:
        exists = bind.execute(
            text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": _name(role)}
        ).scalar()
        if not exists:
            bind.execute(
                text(
                    f'CREATE ROLE "{_name(role)}" NOLOGIN '
                    f"{'INHERIT' if inherit else 'NOINHERIT'}"
                )
            )
    for role, member, admin, inherit, can_set in _MEMBERSHIPS:
        bind.execute(
            text(
                f'GRANT "{_name(role)}" TO "{_name(member)}" WITH ADMIN {admin}, '
                f"INHERIT {inherit}, SET {can_set}"
            )
        )
    for extension, schema in _EXTENSIONS:
        bind.execute(
            text(f'CREATE EXTENSION IF NOT EXISTS "{extension}" WITH SCHEMA "{schema}"')
        )
    missing = [
        name
        for name in _BOOTSTRAP_OPCLASSES
        if not bind.execute(
            text(
                "SELECT 1 FROM pg_opclass c JOIN pg_namespace n "
                "ON n.oid = c.opcnamespace "
                "WHERE n.nspname = 'public' AND c.opcname = :name"
            ),
            {"name": name},
        ).scalar()
    ]
    bind.execute(text("SET LOCAL check_function_bodies = false"))
    sql = _SQL.read_text().replace(_MARK, _prefix())
    for name in missing:
        sql = sql.replace(f" public.{name})", ")")
    for statement in split_sql_statements(sql):
        # Raw, so a colon in a function body is not read as a parameter.
        bind.exec_driver_sql(statement)


def downgrade() -> None:
    raise NotImplementedError(
        "Nothing comes before the v0.75.0 baseline; restore a backup instead."
    )
