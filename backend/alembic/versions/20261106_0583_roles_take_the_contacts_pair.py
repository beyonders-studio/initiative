"""roles take the contacts pair

In ``guild_template`` and every ``guild_<id>``, every role that predates the
contacts tool takes ``contacts_enabled`` and ``create_contacts`` as
``DEFAULT_PERMISSION_VALUES`` says, and a built-in manager role both. The
rules' key CHECK, as the last start rendered it, admits the pair before the
rows are written; a start renders it whole again.

The downgrade drops the ``entity_presence`` view, which reads the contacts
table 20261105_0582's downgrade drops; a start renders the view again. That
downgrade removes the rows.

Revision ID: 20261106_0583
Revises: 20261105_0582
Create Date: 2026-11-06
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261106_0583"
down_revision = "20261105_0582"
branch_labels = None
depends_on = None

#: The tool's role pair.
_ROLE_KEYS = ("contacts_enabled", "create_contacts")

# Permission key -> the value a role created at this revision stores. Mirrors
# ``DEFAULT_PERMISSION_VALUES`` as it stands here — every key, so a role
# missing any of them is made whole by one pass.
_ROLE_PERMISSION_DEFAULTS: dict[str, bool] = {
    "calendars_enabled": False,
    "contacts_enabled": False,
    "counter_groups_enabled": False,
    "create_calendars": False,
    "create_contacts": False,
    "create_counter_groups": False,
    "create_dashboards": False,
    "create_files": False,
    "create_posts": False,
    "create_projects": False,
    "create_wikis": False,
    "dashboards_enabled": False,
    "dashboards_run_as_initiative": False,
    "files_enabled": True,
    "posts_enabled": False,
    "projects_enabled": True,
    "wikis_enabled": False,
}


def backfill_sql(defaults: dict[str, bool]) -> str:
    """The INSERT this revision runs, unqualified so it applies in whichever
    guild schema the search_path names. A built-in manager role holds every
    key; everything else gets the default."""
    values = ", ".join(
        f"('{key}', {'true' if enabled else 'false'})"
        for key, enabled in sorted(defaults.items())
    )
    return f"""
        INSERT INTO initiative_rules (initiative_id, initiative_role_id, key, enabled)
        SELECT r.initiative_id,
               r.id,
               k.key,
               CASE
                   WHEN r.is_builtin AND r.is_manager THEN true
                   ELSE k.enabled
               END
        FROM initiative_roles AS r
        CROSS JOIN (VALUES {values}) AS k(key, enabled)
        ON CONFLICT (initiative_id, key, initiative_role_id) DO NOTHING
    """


def _admit_role_keys() -> None:
    """The rules' key CHECK, as the last start rendered it, with the role pair
    first among an initiative's keys."""
    bind = op.get_bind()
    definition = bind.execute(
        sa.text(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = to_regclass('initiative_rules') "
            "AND conname = 'ck_initiative_rules_key'"
        )
    ).scalar()
    if definition is None or f"'{_ROLE_KEYS[0]}'" in definition:
        return
    added = "".join(f"'{key}'::text, " for key in _ROLE_KEYS)
    op.execute("ALTER TABLE initiative_rules DROP CONSTRAINT ck_initiative_rules_key")
    op.execute(
        "ALTER TABLE initiative_rules ADD CONSTRAINT ck_initiative_rules_key "
        + definition.replace("ARRAY[", f"ARRAY[{added}", 1)
    )


def _write_unforced(table: str, statement: str) -> None:
    """Run one DML statement on ``table``, with its FORCE row security, where
    it has it, lifted for the statement and put back after."""
    forced = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT relforcerowsecurity FROM pg_class WHERE oid = to_regclass(:t)"
            ),
            {"t": table},
        )
        .scalar()
    )
    if not forced:
        op.execute(statement)
        return
    op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute(statement)
    finally:
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def _upgrade() -> None:
    _admit_role_keys()
    _write_unforced("initiative_rules", backfill_sql(_ROLE_PERMISSION_DEFAULTS))


def _downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS entity_presence CASCADE")


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _upgrade)


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _downgrade)
