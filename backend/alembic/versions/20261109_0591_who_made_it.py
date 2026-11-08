"""who made it, and who binned it: a member, a plug-in or Initiative

Every table that records an author gains ``created_by_kind`` beside
``created_by``: ``member`` (``created_by`` is a user id), ``plugin`` (an
installed plug-in acting as its community; ``created_by`` is the install) or
``system`` (Initiative itself; ``created_by`` is NULL). Two CHECKs hold the
pair together, so NULL means Initiative and nothing else. The four tables only
a person writes keep their author required as a CHECK on the kind rather than
``NOT NULL`` on the column.

``public.fn_set_created_by`` stamps an unnamed author from the request: a user
makes a member, an install alone a plug-in, neither the system. A caller that
names an author names its kind too; one that names only the id is refused.

Existing rows: a named author is a member. An unnamed one is a plug-in's
where something says which: its create event still in the community's
``event_outbox`` with an install and no user, an owner grant naming an install
on a tool's item, or a webhook subscription's ``plugin_install_id``. Every
other unnamed author is the system.

Every trashable table gains ``deleted_by_kind`` beside ``deleted_by`` on the
same terms, stamped as a row goes to the trash and cleared as it comes back
(``public.fn_stamp_deleted_by``, rendered at start with its triggers). A
trashed row that names who binned it was binned by a member; one that names
nobody, by the system. A live row keeps no ``deleted_by``.

The downgrade puts the old function back, clears the plug-in authors to NULL
and drops the kind.

Revision ID: 20261109_0591
Revises: 20261109_0590
Create Date: 2026-11-09
"""

from collections.abc import Iterator
from contextlib import contextmanager

from alembic import op
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261109_0591"
down_revision = "20261109_0590"
branch_labels = None
depends_on = None

#: Every table carrying ``created_by`` at this revision.
_AUTHOR_TABLES = (
    "calendar_events",
    "calendars",
    "collections",
    "comments",
    "contacts",
    "counter_groups",
    "counters",
    "custom_role_claim_rules",
    "custom_roles",
    "dashboards",
    "data_jobs",
    "evidence",
    "file_versions",
    "files",
    "guest_invite_grants",
    "guild_ai_connections",
    "guild_plugins",
    "guild_settings",
    "initiative_roles",
    "initiatives",
    "intake_bindings",
    "metadata_definitions",
    "moderation_actions",
    "pending_uploads",
    "post_poll_options",
    "post_polls",
    "posts",
    "projects",
    "reactions",
    "relationships",
    "resource_grants",
    "tags",
    "task_statuses",
    "task_types",
    "tasks",
    "tool_layouts",
    "uploads",
    "webhook_subscriptions",
    "wiki_pages",
    "wikis",
)

#: Every table carrying ``deleted_by`` at this revision.
_TRASHABLE_TABLES = (
    "calendar_events",
    "calendars",
    "collections",
    "comments",
    "contacts",
    "counter_groups",
    "counters",
    "dashboards",
    "files",
    "initiatives",
    "posts",
    "projects",
    "tags",
    "tasks",
    "wiki_pages",
    "wikis",
)

#: Each tool's resource type and table: an unnamed author of an item a
#: plug-in's install owns is that plug-in.
_TOOLS = (
    ("project", "projects"),
    ("file", "files"),
    ("counter_group", "counter_groups"),
    ("calendar", "calendars"),
    ("dashboard", "dashboards"),
    ("post", "posts"),
    ("wiki", "wikis"),
    ("contact", "contacts"),
)

#: The tables only a person writes, whose author was ``NOT NULL``.
_MEMBER_ONLY = ("data_jobs", "guild_plugins", "pending_uploads", "reactions")

_STAMP_FUNCTION = """
CREATE OR REPLACE FUNCTION public.fn_set_created_by() RETURNS trigger
    LANGUAGE plpgsql AS $stamp$
BEGIN
    IF NEW.created_by_kind IS NULL THEN
        IF NEW.created_by IS NOT NULL THEN
            RAISE EXCEPTION 'created_by names no kind' USING ERRCODE = '23514';
        END IF;
        NEW.created_by := NULLIF(
            current_setting('app.current_user_id', true), ''
        )::integer;
        IF NEW.created_by IS NOT NULL THEN
            NEW.created_by_kind := 'member';
        ELSE
            NEW.created_by := NULLIF(
                current_setting('app.current_install_id', true), ''
            )::integer;
            NEW.created_by_kind :=
                CASE WHEN NEW.created_by IS NULL THEN 'system' ELSE 'plugin' END;
        END IF;
    END IF;
    RETURN NEW;
END;
$stamp$;
"""

_PREVIOUS_STAMP_FUNCTION = """
CREATE OR REPLACE FUNCTION public.fn_set_created_by() RETURNS trigger
    LANGUAGE plpgsql AS $stamp$
BEGIN
    IF NEW.created_by IS NULL THEN
        NEW.created_by := NULLIF(
            current_setting('app.current_user_id', true), ''
        )::integer;
    END IF;
    RETURN NEW;
END;
$stamp$;
"""


def _present(bind: Connection, tables: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        table
        for table in tables
        if bind.execute(text("SELECT to_regclass(:t)"), {"t": table}).scalar()
    )


@contextmanager
def _held(bind: Connection, tables: tuple[str, ...]) -> Iterator[None]:
    """Unforce each table's row security and hold its user triggers for the
    backfill, then restore both. A failure rolls the revision back with them."""
    forced = [
        table
        for table in tables
        if bind.execute(
            text(
                "SELECT relforcerowsecurity FROM pg_class WHERE oid = to_regclass(:t)"
            ),
            {"t": table},
        ).scalar()
    ]
    for table in forced:
        bind.exec_driver_sql(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    for table in tables:
        bind.exec_driver_sql(f"ALTER TABLE {table} DISABLE TRIGGER USER")
    yield
    for table in tables:
        bind.exec_driver_sql(f"ALTER TABLE {table} ENABLE TRIGGER USER")
    for table in forced:
        bind.exec_driver_sql(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def _upgrade() -> None:
    bind = op.get_bind()
    tables = _present(bind, _AUTHOR_TABLES)
    for table in tables:
        op.execute(f"ALTER TABLE {table} ADD COLUMN created_by_kind varchar(16)")

    with _held(bind, (*tables, *_present(bind, ("event_outbox",)))):
        for table in tables:
            op.execute(
                f"UPDATE {table} SET created_by_kind = 'member'"  # noqa: S608
                " WHERE created_by IS NOT NULL"
            )
        for table in tables:
            if table in _MEMBER_ONLY or table == "relationships":
                continue
            op.execute(
                f"UPDATE {table} SET created_by = o.actor_install_id,"  # noqa: S608
                " created_by_kind = 'plugin'"
                " FROM (SELECT DISTINCT ON (resource_id) resource_id, actor_install_id"
                "       FROM event_outbox"
                f"      WHERE resource_type = '{table}' AND action = 'created'"
                "        AND actor_user_id IS NULL AND actor_install_id IS NOT NULL"
                "       ORDER BY resource_id, id) o"
                f" WHERE {table}.id = o.resource_id AND {table}.created_by IS NULL"
            )
        if "resource_grants" in tables:
            for kind, table in _TOOLS:
                if table not in tables:
                    continue
                op.execute(
                    f"UPDATE {table} SET created_by = g.plugin_install_id,"  # noqa: S608
                    " created_by_kind = 'plugin'"
                    " FROM resource_grants g"
                    f" WHERE g.resource_type = '{kind}' AND g.resource_id = {table}.id"
                    "   AND g.level = 'owner' AND g.plugin_install_id IS NOT NULL"
                    f"  AND {table}.created_by_kind IS NULL"
                )
        if "webhook_subscriptions" in tables:
            op.execute(
                "UPDATE webhook_subscriptions SET created_by = plugin_install_id,"
                " created_by_kind = 'plugin'"
                " WHERE created_by_kind IS NULL AND plugin_install_id IS NOT NULL"
            )
        for table in tables:
            op.execute(
                f"UPDATE {table} SET created_by_kind = 'system'"  # noqa: S608
                " WHERE created_by_kind IS NULL"
            )

    for table in tables:
        op.execute(f"ALTER TABLE {table} ALTER COLUMN created_by_kind SET NOT NULL")
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT ck_{table}_created_by_kind"
            " CHECK (created_by_kind IN ('member', 'plugin', 'system'))"
        )
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT ck_{table}_created_by"
            " CHECK ((created_by_kind = 'system') = (created_by IS NULL))"
        )
    _upgrade_deleted_by(bind)
    for table in _present(bind, _MEMBER_ONLY):
        op.execute(f"ALTER TABLE {table} ALTER COLUMN created_by DROP NOT NULL")
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT ck_{table}_created_by_member"
            " CHECK (created_by_kind = 'member')"
        )


def _upgrade_deleted_by(bind: Connection) -> None:
    tables = _present(bind, _TRASHABLE_TABLES)
    for table in tables:
        op.execute(f"ALTER TABLE {table} ADD COLUMN deleted_by_kind varchar(16)")
    with _held(bind, tables):
        for table in tables:
            op.execute(
                f"UPDATE {table} SET deleted_by = NULL"  # noqa: S608
                " WHERE deleted_at IS NULL AND deleted_by IS NOT NULL"
            )
            op.execute(
                f"UPDATE {table} SET deleted_by_kind = CASE"  # noqa: S608
                " WHEN deleted_by IS NULL THEN 'system' ELSE 'member' END"
                " WHERE deleted_at IS NOT NULL"
            )
    for table in tables:
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT ck_{table}_deleted_by_kind"
            " CHECK (deleted_by_kind IN ('member', 'plugin', 'system'))"
        )
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT ck_{table}_deleted_by CHECK ("
            " CASE WHEN deleted_at IS NULL"
            " THEN deleted_by IS NULL AND deleted_by_kind IS NULL"
            " ELSE deleted_by_kind IS NOT NULL"
            " AND (deleted_by_kind = 'system') = (deleted_by IS NULL) END)"
        )


def _downgrade() -> None:
    bind = op.get_bind()
    tables = _present(bind, _AUTHOR_TABLES)
    trashable = _present(bind, _TRASHABLE_TABLES)
    for table in trashable:
        op.execute(f"DROP TRIGGER IF EXISTS tr_{table}_stamp_deleted_by ON {table}")
        op.execute(
            f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS ck_{table}_deleted_by"
        )
        op.execute(
            f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS ck_{table}_deleted_by_kind"
        )
    for table in _present(bind, _MEMBER_ONLY):
        op.execute(
            f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS ck_{table}_created_by_member"
        )
        op.execute(f"ALTER TABLE {table} ALTER COLUMN created_by SET NOT NULL")
    for table in tables:
        op.execute(
            f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS ck_{table}_created_by"
        )
        op.execute(
            f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS ck_{table}_created_by_kind"
        )
    # A plug-in was named by NULL before this revision.
    with _held(bind, tables):
        for table in tables:
            op.execute(
                f"UPDATE {table} SET created_by = NULL"  # noqa: S608
                " WHERE created_by_kind = 'plugin'"
            )
        for table in trashable:
            op.execute(
                f"UPDATE {table} SET deleted_by = NULL"  # noqa: S608
                " WHERE deleted_by_kind = 'plugin'"
            )
    for table in trashable:
        op.execute(f"ALTER TABLE {table} DROP COLUMN deleted_by_kind")
    for table in tables:
        op.execute(f"ALTER TABLE {table} DROP COLUMN created_by_kind")


def upgrade() -> None:
    op.execute(_STAMP_FUNCTION)
    run_for_each_guild_schema(op.get_bind(), _upgrade)


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _downgrade)
    op.execute(_PREVIOUS_STAMP_FUNCTION)
    op.execute("DROP FUNCTION IF EXISTS public.fn_stamp_deleted_by()")
