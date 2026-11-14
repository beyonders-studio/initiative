"""who made it, and who binned it: a member, a plug-in or Initiative

Every table that records an author gains ``created_by_kind`` beside
``created_by``: ``member`` (``created_by`` is a user id), ``plugin`` (an
installed plug-in acting as its community; ``created_by`` is the install) or
``system`` (Initiative itself; ``created_by`` is NULL). Two CHECKs hold the
pair together, so NULL means Initiative and nothing else. The four tables only
a person writes keep their author required as a CHECK on the kind rather than
``NOT NULL`` on the column.

``public.fn_set_author`` stamps an unnamed author from the request: a user
makes a member, an install alone a plug-in, neither the system. A caller that
names an author names its kind too; one that names only the id is refused. The
author tables' ``tr_<t>_set_created_by`` triggers call it; the older
``public.fn_set_created_by``, which knows no kind, is left as it was for
whatever still calls it.

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

The downgrade points the triggers back at ``fn_set_created_by``, clears the
plug-in authors to NULL and drops the kind and ``fn_set_author``.

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
CREATE OR REPLACE FUNCTION public.fn_set_author() RETURNS trigger
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

#: Points the schema's author triggers from one stamp function to another.
_REPOINT = """
DO $$
DECLARE found record;
BEGIN
  FOR found IN
    SELECT t.tgrelid, pg_get_triggerdef(t.oid) AS def
    FROM pg_trigger t
    JOIN pg_class c ON c.oid = t.tgrelid
    WHERE c.relnamespace = current_schema()::regnamespace
      AND t.tgfoid = 'public.{old}'::regproc
      AND EXISTS (
        SELECT 1 FROM pg_attribute a
        WHERE a.attrelid = t.tgrelid AND a.attname = 'created_by_kind'
          AND NOT a.attisdropped
      )
  LOOP
    EXECUTE regexp_replace(
      regexp_replace(found.def, 'CREATE TRIGGER', 'CREATE OR REPLACE TRIGGER'),
      'EXECUTE FUNCTION \\S*{old}\\(\\)', 'EXECUTE FUNCTION public.{new}()'
    );
  END LOOP;
END $$;
"""


#: The schema's policies and triggers that read ``created_by_kind`` or
#: ``deleted_by_kind``, and the triggers whose own function in the schema does.
_UNREAD_KINDS = """
DO $$
DECLARE found record;
BEGIN
  FOR found IN
    SELECT DISTINCT d.classid, d.objid
    FROM pg_depend d
    JOIN pg_attribute a ON a.attrelid = d.refobjid AND a.attnum = d.refobjsubid
    JOIN pg_class c ON c.oid = d.refobjid
    WHERE c.relnamespace = current_schema()::regnamespace
      AND a.attname IN ('created_by_kind', 'deleted_by_kind')
      AND d.classid IN ('pg_policy'::regclass, 'pg_trigger'::regclass)
  LOOP
    IF found.classid = 'pg_policy'::regclass THEN
      EXECUTE (SELECT format('DROP POLICY %I ON %s', polname, polrelid::regclass)
               FROM pg_policy WHERE oid = found.objid);
    ELSE
      EXECUTE (SELECT format('DROP TRIGGER %I ON %s', tgname, tgrelid::regclass)
               FROM pg_trigger WHERE oid = found.objid);
    END IF;
  END LOOP;
  FOR found IN
    SELECT t.tgname, t.tgrelid
    FROM pg_trigger t
    JOIN pg_class c ON c.oid = t.tgrelid
    JOIN pg_proc f ON f.oid = t.tgfoid
    WHERE c.relnamespace = current_schema()::regnamespace
      AND f.pronamespace = current_schema()::regnamespace
      AND NOT t.tgisinternal
      AND (strpos(f.prosrc, 'created_by_kind') > 0
           OR strpos(f.prosrc, 'deleted_by_kind') > 0)
  LOOP
    EXECUTE format('DROP TRIGGER %I ON %s', found.tgname, found.tgrelid::regclass);
  END LOOP;
END $$;
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
    op.execute(_REPOINT.format(old="fn_set_created_by", new="fn_set_author"))
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
    # The rendered policies, triggers and trigger functions that read the
    # kinds come off first: the columns cannot be dropped from under them,
    # and the release this goes back to renders its own at boot.
    op.execute(_UNREAD_KINDS)
    op.execute(_REPOINT.format(old="fn_set_author", new="fn_set_created_by"))
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
    op.execute("DROP FUNCTION IF EXISTS public.fn_set_author()")
    op.execute("DROP FUNCTION IF EXISTS public.fn_stamp_deleted_by()")
