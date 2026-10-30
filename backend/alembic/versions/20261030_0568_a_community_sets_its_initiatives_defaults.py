"""a community sets its initiatives' defaults

A community's admins may set, for every initiative in it, each tool's switch,
each permission of the built-in member role, and whether managers may add
roles of their own (``app.models.tenant.initiative.COMMUNITY_DEFAULT_KEYS``).
They are the community's own rows of ``initiative_rules``, in its own schema:
the rows with no initiative. In ``guild_template`` and every ``guild_<id>``,
``initiative_rules.initiative_id`` takes ``NULL`` and the key check names
which keys each kind of row may hold. The managed policies already admit only
the community's admin to a row with no initiative.

``public.standing`` gains ``community_tools``, the tool switches the
community set: the request's standing reads them once, beside the rest, and
each schema's ``initiative_actions()`` reads them there. ``current_standing()``
in every guild schema that has one is restated to build the longer value.

Revision ID: 20261030_0568
Revises: 20261030_0567
Create Date: 2026-10-30
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import guild_schema_names, run_for_each_guild_schema

revision = "20261030_0568"
down_revision = "20261030_0567"
branch_labels = None
depends_on = None

#: The permission keys as they stand at this revision.
PERMISSION_KEYS = (
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
#: The community's keys as they stand at this revision.
COMMUNITY_KEYS = (
    "initiative_tool.project",
    "initiative_tool.file",
    "initiative_tool.queue",
    "initiative_tool.counter_group",
    "initiative_tool.calendar",
    "initiative_tool.dashboard",
    "initiative_tool.post",
    "initiative_tool.wiki",
    "initiative_role.member.projects_enabled",
    "initiative_role.member.create_projects",
    "initiative_role.member.files_enabled",
    "initiative_role.member.create_files",
    "initiative_role.member.queues_enabled",
    "initiative_role.member.create_queues",
    "initiative_role.member.counter_groups_enabled",
    "initiative_role.member.create_counter_groups",
    "initiative_role.member.calendars_enabled",
    "initiative_role.member.create_calendars",
    "initiative_role.member.dashboards_enabled",
    "initiative_role.member.create_dashboards",
    "initiative_role.member.posts_enabled",
    "initiative_role.member.create_posts",
    "initiative_role.member.wikis_enabled",
    "initiative_role.member.create_wikis",
    "initiative_role.member.dashboards_run_as_initiative",
    "initiative_custom_roles",
)


def _quoted(keys) -> str:
    return ", ".join(f"'{key}'" for key in keys)


KEY_CHECK = (
    f"(initiative_id IS NOT NULL AND key IN ({_quoted(PERMISSION_KEYS)}))"
    " OR (initiative_id IS NULL AND initiative_role_id IS NULL"
    f" AND key IN ({_quoted(COMMUNITY_KEYS)}))"
)
KEY_CHECK_BEFORE = f"key IN ({_quoted(PERMISSION_KEYS)})"

#: ``current_standing()`` as revision 20261030_0566 built it.
CURRENT_STANDING_BEFORE = """\
CREATE OR REPLACE FUNCTION current_standing()
 RETURNS standing
 LANGUAGE plpgsql
 STABLE
AS $function$
BEGIN
    RETURN ROW(
        (EXISTS (SELECT 1 FROM pg_roles r WHERE r.rolname = session_user AND r.rolbypassrls) AND NULLIF(current_setting('app.current_user_id'::text, true), ''::text) IS NULL AND NULLIF(current_setting('app.current_install_id'::text, true), ''::text) IS NULL),
        NULLIF(current_setting('app.standing_guild_id'::text, true), ''::text) IS NOT DISTINCT FROM COALESCE(NULLIF(current_setting('app.current_guild_id'::text, true), ''::text), NULLIF(current_setting('app.pam_guild_id'::text, true), ''::text), NULLIF(current_setting('app.settings_guild_id'::text, true), ''::text)),
        (NULLIF(current_setting('app.standing_guild_id'::text, true), ''::text) IS NOT DISTINCT FROM COALESCE(NULLIF(current_setting('app.current_guild_id'::text, true), ''::text), NULLIF(current_setting('app.pam_guild_id'::text, true), ''::text), NULLIF(current_setting('app.settings_guild_id'::text, true), ''::text)) AND current_setting('app.guild_admin'::text, true) = 'true'::text),
        current_setting('app.guild_auth_ok'::text, true) = 'true'::text,
        NULLIF(current_setting('app.scope_initiative_id'::text, true), ''::text)::integer,
        current_setting('app.pam_read'::text, true) = 'true'::text,
        current_setting('app.pam_write'::text, true) = 'true'::text,
        COALESCE(string_to_array(NULLIF(current_setting('app.member_initiatives'::text, true), ''::text), ','::text)::integer[], ARRAY[]::integer[]),
        COALESCE(string_to_array(NULLIF(current_setting('app.manager_initiatives'::text, true), ''::text), ','::text)::integer[], ARRAY[]::integer[]),
        COALESCE(string_to_array(NULLIF(current_setting('app.override_initiatives'::text, true), ''::text), ','::text)::integer[], ARRAY[]::integer[]),
        COALESCE(string_to_array(NULLIF(current_setting('app.member_role_ids'::text, true), ''::text), ','::text)::integer[], ARRAY[]::integer[]),
        COALESCE(string_to_array(NULLIF(current_setting('app.role_grants'::text, true), ''::text), ','::text), ARRAY[]::text[]),
        COALESCE(string_to_array(NULLIF(current_setting('app.role_denies'::text, true), ''::text), ','::text), ARRAY[]::text[]),
        COALESCE(string_to_array(NULLIF(current_setting('app.enabled_tools'::text, true), ''::text), ','::text), ARRAY[]::text[]),
        NULLIF(current_setting('app.current_install_id'::text, true), ''::text)::integer,
        COALESCE(string_to_array(NULLIF(current_setting('app.install_read'::text, true), ''::text), ','::text), ARRAY[]::text[]),
        COALESCE(string_to_array(NULLIF(current_setting('app.install_write'::text, true), ''::text), ','::text), ARRAY[]::text[]),
        current_setting('app.content_hold'::text, true) = 'true'::text,
        current_setting('app.pam_moderate'::text, true) = 'true'::text,
        current_setting('app.guest'::text, true) = 'true'::text,
        COALESCE(string_to_array(NULLIF(current_setting('app.guest_item_initiatives'::text, true), ''::text), ','::text)::integer[], ARRAY[]::integer[]),
        COALESCE(string_to_array(NULLIF(current_setting('app.closed_surfaces'::text, true), ''::text), ','::text), ARRAY[]::text[])
    )::public.standing;
END
$function$

"""

#: ``current_standing()`` with ``community_tools`` last.
CURRENT_STANDING_AFTER = """\
CREATE OR REPLACE FUNCTION current_standing()
 RETURNS standing
 LANGUAGE plpgsql
 STABLE
AS $function$
BEGIN
    RETURN ROW(
        (EXISTS (SELECT 1 FROM pg_roles r WHERE r.rolname = session_user AND r.rolbypassrls) AND NULLIF(current_setting('app.current_user_id'::text, true), ''::text) IS NULL AND NULLIF(current_setting('app.current_install_id'::text, true), ''::text) IS NULL),
        NULLIF(current_setting('app.standing_guild_id'::text, true), ''::text) IS NOT DISTINCT FROM COALESCE(NULLIF(current_setting('app.current_guild_id'::text, true), ''::text), NULLIF(current_setting('app.pam_guild_id'::text, true), ''::text), NULLIF(current_setting('app.settings_guild_id'::text, true), ''::text)),
        (NULLIF(current_setting('app.standing_guild_id'::text, true), ''::text) IS NOT DISTINCT FROM COALESCE(NULLIF(current_setting('app.current_guild_id'::text, true), ''::text), NULLIF(current_setting('app.pam_guild_id'::text, true), ''::text), NULLIF(current_setting('app.settings_guild_id'::text, true), ''::text)) AND current_setting('app.guild_admin'::text, true) = 'true'::text),
        current_setting('app.guild_auth_ok'::text, true) = 'true'::text,
        NULLIF(current_setting('app.scope_initiative_id'::text, true), ''::text)::integer,
        current_setting('app.pam_read'::text, true) = 'true'::text,
        current_setting('app.pam_write'::text, true) = 'true'::text,
        COALESCE(string_to_array(NULLIF(current_setting('app.member_initiatives'::text, true), ''::text), ','::text)::integer[], ARRAY[]::integer[]),
        COALESCE(string_to_array(NULLIF(current_setting('app.manager_initiatives'::text, true), ''::text), ','::text)::integer[], ARRAY[]::integer[]),
        COALESCE(string_to_array(NULLIF(current_setting('app.override_initiatives'::text, true), ''::text), ','::text)::integer[], ARRAY[]::integer[]),
        COALESCE(string_to_array(NULLIF(current_setting('app.member_role_ids'::text, true), ''::text), ','::text)::integer[], ARRAY[]::integer[]),
        COALESCE(string_to_array(NULLIF(current_setting('app.role_grants'::text, true), ''::text), ','::text), ARRAY[]::text[]),
        COALESCE(string_to_array(NULLIF(current_setting('app.role_denies'::text, true), ''::text), ','::text), ARRAY[]::text[]),
        COALESCE(string_to_array(NULLIF(current_setting('app.enabled_tools'::text, true), ''::text), ','::text), ARRAY[]::text[]),
        NULLIF(current_setting('app.current_install_id'::text, true), ''::text)::integer,
        COALESCE(string_to_array(NULLIF(current_setting('app.install_read'::text, true), ''::text), ','::text), ARRAY[]::text[]),
        COALESCE(string_to_array(NULLIF(current_setting('app.install_write'::text, true), ''::text), ','::text), ARRAY[]::text[]),
        current_setting('app.content_hold'::text, true) = 'true'::text,
        current_setting('app.pam_moderate'::text, true) = 'true'::text,
        current_setting('app.guest'::text, true) = 'true'::text,
        COALESCE(string_to_array(NULLIF(current_setting('app.guest_item_initiatives'::text, true), ''::text), ','::text)::integer[], ARRAY[]::integer[]),
        COALESCE(string_to_array(NULLIF(current_setting('app.closed_surfaces'::text, true), ''::text), ','::text), ARRAY[]::text[]),
        COALESCE(string_to_array(NULLIF(current_setting('app.community_tools'::text, true), ''::text), ','::text), ARRAY[]::text[])
    )::public.standing;
END
$function$

"""


def _restate(bind, body: str) -> None:
    """``body`` in every guild schema that carries ``current_standing()``."""
    for schema in guild_schema_names(bind):
        if not bind.execute(
            sa.text("SELECT to_regprocedure(CAST(:sig AS text)) IS NOT NULL"),
            {"sig": f"{schema}.current_standing()"},
        ).scalar():
            continue
        bind.execute(
            sa.text("SELECT set_config('search_path', :sp, true)"),
            {"sp": f"{schema}, public"},
        )
        bind.exec_driver_sql(body)
    bind.execute(sa.text("SELECT set_config('search_path', 'public', true)"))


def _swap_key_check(expression: str) -> None:
    op.drop_constraint("ck_initiative_rules_key", "initiative_rules")
    op.create_check_constraint(
        "ck_initiative_rules_key", "initiative_rules", expression
    )


def _upgrade() -> None:
    op.alter_column("initiative_rules", "initiative_id", nullable=True)
    _swap_key_check(KEY_CHECK)


def _downgrade() -> None:
    bind = op.get_bind()
    forced = bind.execute(
        sa.text(
            "SELECT relforcerowsecurity FROM pg_class"
            " WHERE oid = to_regclass('initiative_rules')"
        )
    ).scalar()
    if forced:
        op.execute("ALTER TABLE initiative_rules NO FORCE ROW LEVEL SECURITY")
    op.execute("DELETE FROM initiative_rules WHERE initiative_id IS NULL")
    if forced:
        op.execute("ALTER TABLE initiative_rules FORCE ROW LEVEL SECURITY")
    _swap_key_check(KEY_CHECK_BEFORE)
    op.alter_column("initiative_rules", "initiative_id", nullable=False)


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _upgrade)
    op.execute("ALTER TYPE public.standing ADD ATTRIBUTE community_tools text[]")
    _restate(op.get_bind(), CURRENT_STANDING_AFTER)


def downgrade() -> None:
    bind = op.get_bind()
    for schema in guild_schema_names(bind):
        op.execute(f'DROP FUNCTION IF EXISTS "{schema}".standing_community_tools()')
    op.execute("ALTER TYPE public.standing DROP ATTRIBUTE community_tools")
    _restate(bind, CURRENT_STANDING_BEFORE)
    run_for_each_guild_schema(bind, _downgrade)
