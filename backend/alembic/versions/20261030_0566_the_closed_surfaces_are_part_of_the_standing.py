"""the closed surfaces are part of the standing

The seat's write policies on the AI-connection and plug-in tables asked
``public.community_surface_open()``, a function outside the community's schema.
A community's policies call only functions in that schema; what they need from
``public`` reaches them through the request's standing, computed once per
request by the statement inside the schema.

- ``public.standing`` gains ``closed_surfaces``, the ``surface.*`` keys the
  deployment has closed for the community. The standing statement reads them
  from ``public.community_rules``, scoped to the routed community, once per
  request. ``current_standing()`` in every guild schema that has one is
  restated to build the longer value.
- ``public.community_surface_open()`` is dropped, and with it the seat's write
  policies that called it. Every community's schema renders them again at
  boot, reading the standing.

The bodies are stated here in full, as they were and as they become.

Revision ID: 20261030_0566
Revises: 20261030_0565
Create Date: 2026-10-30
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import guild_schema_names

revision = "20261030_0566"
down_revision = "20261030_0565"
branch_labels = None
depends_on = None

#: ``current_standing()`` as revision 20261010_0490 built it.
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
        COALESCE(string_to_array(NULLIF(current_setting('app.guest_item_initiatives'::text, true), ''::text), ','::text)::integer[], ARRAY[]::integer[])
    )::public.standing;
END
$function$

"""

#: ``current_standing()`` with ``closed_surfaces`` last.
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
        COALESCE(string_to_array(NULLIF(current_setting('app.closed_surfaces'::text, true), ''::text), ','::text), ARRAY[]::text[])
    )::public.standing;
END
$function$

"""

#: ``public.community_surface_open()`` as revision 20261030_0562 installed it.
COMMUNITY_SURFACE_OPEN = """\
CREATE OR REPLACE FUNCTION public.community_surface_open(p_guild_id integer, p_surface text)
 RETURNS boolean
 LANGUAGE plpgsql
 STABLE
AS $function$
BEGIN
    RETURN NOT EXISTS (
        SELECT 1
        FROM public.community_rules r
        WHERE r.guild_id = p_guild_id
          AND r.key = p_surface
          AND r.user_id IS NULL
          AND r.set_by = 'deployment'
          AND NOT r.enabled
    );
END
$function$

"""


def _schemas_with_standing(bind) -> list[str]:
    """The guild schemas that carry ``current_standing()``. The template holds
    structure only, and a schema the back-fill has not rendered yet is given the
    current body when it is."""
    return [
        schema
        for schema in guild_schema_names(bind)
        if bind.execute(
            sa.text("SELECT to_regprocedure(CAST(:sig AS text)) IS NOT NULL"),
            {"sig": f"{schema}.current_standing()"},
        ).scalar()
    ]


def _restate(bind, body: str) -> None:
    for schema in _schemas_with_standing(bind):
        bind.execute(
            sa.text("SELECT set_config('search_path', :sp, true)"),
            {"sp": f"{schema}, public"},
        )
        bind.exec_driver_sql(body)
    bind.execute(sa.text("SELECT set_config('search_path', 'public', true)"))


def upgrade() -> None:
    bind = op.get_bind()
    op.execute("ALTER TYPE public.standing ADD ATTRIBUTE closed_surfaces text[]")
    _restate(bind, CURRENT_STANDING_AFTER)
    op.execute(
        "DROP FUNCTION IF EXISTS public.community_surface_open(integer, text) CASCADE"
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(COMMUNITY_SURFACE_OPEN)
    # The seat's policies that read the field go with its reader; the old
    # build renders them again at boot.
    for schema in guild_schema_names(bind):
        op.execute(
            f'DROP FUNCTION IF EXISTS "{schema}".standing_closed_surfaces() CASCADE'
        )
    op.execute("ALTER TYPE public.standing DROP ATTRIBUTE closed_surfaces")
    _restate(bind, CURRENT_STANDING_BEFORE)
