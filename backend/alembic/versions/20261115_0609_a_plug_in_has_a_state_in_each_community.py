"""a plug-in has a state in each community

- ``plugin_service_registrations.suspended_at`` and ``suspended_by``: the
  owner suspends a plug-in everywhere. They replace ``enabled``: a
  registration switched off is suspended from now. The install floor reads
  ``suspended_at`` where it read ``enabled``.
- ``plugin_installs`` gains each install's ``status`` (``active``,
  ``read_only``, ``on_hold``, ``deleted``) and when it last moved, whether
  staff suspended it there and who did, and the status its plug-in was last
  told (``plugin_status_sent``). Every install starts ``active``.
- The install floor reads its own install's row: a column grant here, and a
  policy rendered from the shared-table registry at boot. Billing's role reads
  and writes the statuses of the community it is routed to, the same way.
- The billing change log: ``plugin.status`` with ``listing_uid``, ``status``
  and ``suspended`` (by the owner, by staff, or out of reach), written by the
  ``plugin_installs`` trigger when an install's status or suspension moves,
  and by the system engine for every install of a registration suspended or
  lifted (``public.billing_plugin_status``). Its writer reads what that takes.
- A suspension or a status that moves is announced on ``plugin_states`` at
  commit, so every process drops its registration snapshot.

Revision ID: 20261115_0609
Revises: 20261112_0608
Create Date: 2026-11-15
"""

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20261115_0609"
down_revision = "20261112_0608"
branch_labels = None
depends_on = None

REGISTRATIONS = "plugin_service_registrations"
INSTALLS = "plugin_installs"
#: The billing change log's writer (migration 20261021_0532).
WRITER = '"app_billing_log"'
#: The channel a moved state is announced on.
CHANNEL = "plugin_states"

_INSTALL_FLOOR_COLUMNS = "guild_id, install_id, listing_uid, status, suspended_at"

_WRITER_GRANTS = (
    f"GRANT SELECT ({_INSTALL_FLOOR_COLUMNS}) ON TABLE public.{INSTALLS} TO {{r}}",
    "GRANT SELECT (listing_uid, suspended_at, operations_only)"
    f" ON TABLE public.{REGISTRATIONS} TO {{r}}",
    "GRANT SELECT (id, operations_guild_id) ON TABLE public.app_settings TO {r}",
)

_PLUGIN_STATUS = """
CREATE OR REPLACE FUNCTION public.billing_plugin_status(
    p_guild integer, p_install integer
) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $fn$
DECLARE v record;
BEGIN
    IF NOT public.billing_managed() THEN
        RETURN;
    END IF;
    SELECT i.listing_uid, i.status,
           i.suspended_at IS NOT NULL OR EXISTS (
               SELECT 1 FROM public.plugin_service_registrations r
                WHERE r.listing_uid = i.listing_uid
                  AND (r.suspended_at IS NOT NULL
                       OR (r.operations_only AND i.guild_id IS DISTINCT FROM (
                           SELECT s.operations_guild_id FROM public.app_settings s
                            WHERE s.id = 1)))
           ) AS suspended
      INTO v
      FROM public.plugin_installs i
     WHERE i.guild_id = p_guild AND i.install_id = p_install;
    IF NOT FOUND THEN
        RETURN;
    END IF;
    PERFORM public.billing_change_row(
        p_guild, 'plugin.status',
        jsonb_build_object('listing_uid', v.listing_uid, 'status', v.status,
                           'suspended', v.suspended));
END $fn$;
"""

_INSTALLS_CHANGED = """
CREATE OR REPLACE FUNCTION public.billing_install_changed() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $fn$
BEGIN
    IF TG_OP = 'INSERT' THEN
        PERFORM public.billing_change_row(
            NEW.guild_id, 'plugin.installed',
            jsonb_build_object('listing_uid', NEW.listing_uid));
    ELSIF TG_OP = 'UPDATE' THEN
        PERFORM public.billing_plugin_status(NEW.guild_id, NEW.install_id);
    ELSIF EXISTS (SELECT 1 FROM public.guilds WHERE id = OLD.guild_id) THEN
        PERFORM public.billing_change_row(
            OLD.guild_id, 'plugin.uninstalled',
            jsonb_build_object('listing_uid', OLD.listing_uid));
    END IF;
    RETURN NULL;
END $fn$;
"""

#: As revision 20261021_0532 wrote it.
_INSTALLS_CHANGED_BEFORE = """
CREATE OR REPLACE FUNCTION public.billing_install_changed() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $fn$
BEGIN
    IF TG_OP = 'INSERT' THEN
        PERFORM public.billing_change_row(
            NEW.guild_id, 'plugin.installed',
            jsonb_build_object('listing_uid', NEW.listing_uid));
    ELSIF EXISTS (SELECT 1 FROM public.guilds WHERE id = OLD.guild_id) THEN
        PERFORM public.billing_change_row(
            OLD.guild_id, 'plugin.uninstalled',
            jsonb_build_object('listing_uid', OLD.listing_uid));
    END IF;
    RETURN NULL;
END $fn$;
"""

_NOTIFY = f"""
CREATE OR REPLACE FUNCTION public.plugin_state_notify() RETURNS trigger
LANGUAGE plpgsql
AS $fn$
BEGIN
    PERFORM pg_notify('{CHANNEL}', '');
    RETURN NULL;
END $fn$;
"""

#: An install's status or suspension moved.
_INSTALL_STATE_MOVED = (
    f"AFTER UPDATE OF status, suspended_at ON public.{INSTALLS} FOR EACH ROW"
    " WHEN (OLD.status IS DISTINCT FROM NEW.status"
    " OR OLD.suspended_at IS DISTINCT FROM NEW.suspended_at)"
)

_TRIGGERS = (
    (
        "billing_plugin_install_state",
        INSTALLS,
        _INSTALL_STATE_MOVED,
        "billing_install_changed()",
    ),
    (
        "plugin_install_state_notify",
        INSTALLS,
        _INSTALL_STATE_MOVED,
        "plugin_state_notify()",
    ),
    (
        "plugin_install_held_gone_notify",
        INSTALLS,
        f"AFTER DELETE ON public.{INSTALLS} FOR EACH ROW"
        " WHEN (OLD.status <> 'active' OR OLD.suspended_at IS NOT NULL)",
        "plugin_state_notify()",
    ),
    (
        "plugin_registration_state_notify",
        REGISTRATIONS,
        f"AFTER UPDATE OF suspended_at ON public.{REGISTRATIONS} FOR EACH ROW"
        " WHEN (OLD.suspended_at IS DISTINCT FROM NEW.suspended_at)",
        "plugin_state_notify()",
    ),
)

#: The registry's policies on the two tables for the roles granted here,
#: dropped before the grants on a downgrade.
_POLICIES = (
    (INSTALLS, "install_reads_its_install"),
    (INSTALLS, "billing_plugin_installs_select"),
    (INSTALLS, "billing_plugin_installs_update"),
    (INSTALLS, "billing_log_read"),
    (REGISTRATIONS, "billing_log_read"),
)


def _billing_role() -> str:
    return f'"{settings.PLATFORM_ROLE_PREFIX}initiative_billing"'


def _unforced_update(statement: str) -> None:
    """Run ``statement`` on the registrations with their row security lifted,
    and put it back: no policy admits the migration's own role."""
    op.execute(f"ALTER TABLE public.{REGISTRATIONS} NO FORCE ROW LEVEL SECURITY")
    op.execute(statement)
    op.execute(f"ALTER TABLE public.{REGISTRATIONS} FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    op.add_column(
        REGISTRATIONS,
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        REGISTRATIONS,
        sa.Column(
            "suspended_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    _unforced_update(
        f"UPDATE public.{REGISTRATIONS} SET suspended_at = now() WHERE NOT enabled"
    )
    # Its column grant goes with it.
    op.drop_column(REGISTRATIONS, "enabled")
    op.execute(
        f"GRANT SELECT (suspended_at) ON public.{REGISTRATIONS} TO plugin_install_base"
    )

    op.add_column(
        INSTALLS,
        sa.Column("status", sa.Text(), server_default="active", nullable=False),
    )
    op.create_check_constraint(
        "ck_plugin_installs_status",
        INSTALLS,
        "status IN ('active', 'read_only', 'on_hold', 'deleted')",
    )
    for column in (
        sa.Column("status_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "suspended_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("plugin_status_sent", sa.Text(), nullable=True),
    ):
        op.add_column(INSTALLS, column)
    op.execute(
        f"GRANT SELECT ({_INSTALL_FLOOR_COLUMNS}) ON public.{INSTALLS}"
        " TO plugin_install_base"
    )
    op.execute(
        "GRANT SELECT (guild_id, install_id, listing_uid, status),"
        f" UPDATE (status, status_changed_at) ON public.{INSTALLS}"
        f" TO {_billing_role()}"
    )

    for grant in _WRITER_GRANTS:
        op.execute(grant.format(r=WRITER))
    op.execute(_PLUGIN_STATUS)
    op.execute(_INSTALLS_CHANGED)
    # Ownership can only be handed to a role that may create in the schema.
    # Given for the assignment and taken straight back.
    op.execute(f"GRANT CREATE ON SCHEMA public TO {WRITER}")
    op.execute(
        "ALTER FUNCTION public.billing_plugin_status(integer, integer)"
        f" OWNER TO {WRITER}"
    )
    op.execute(f"REVOKE CREATE ON SCHEMA public FROM {WRITER}")
    op.execute(
        "REVOKE ALL ON FUNCTION public.billing_plugin_status(integer, integer)"
        " FROM PUBLIC"
    )
    # A registration suspended or lifted is told for each of its installs.
    op.execute(
        "GRANT EXECUTE ON FUNCTION public.billing_plugin_status(integer, integer)"
        " TO app_admin"
    )
    op.execute(_NOTIFY)
    for name, _table, when, function in _TRIGGERS:
        op.execute(f"CREATE TRIGGER {name} {when} EXECUTE FUNCTION public.{function}")


def downgrade() -> None:
    for name, table, _when, _function in _TRIGGERS:
        op.execute(f"DROP TRIGGER IF EXISTS {name} ON public.{table}")
    op.execute("DROP FUNCTION IF EXISTS public.plugin_state_notify()")
    op.execute(_INSTALLS_CHANGED_BEFORE)
    op.execute("DROP FUNCTION IF EXISTS public.billing_plugin_status(integer, integer)")
    for table, policy in _POLICIES:
        op.execute(f"DROP POLICY IF EXISTS {policy} ON public.{table}")
    for grant in _WRITER_GRANTS:
        op.execute(
            grant.format(r=WRITER)
            .replace("GRANT ", "REVOKE ", 1)
            .replace(" TO ", " FROM ")
        )
    op.execute(
        f"REVOKE SELECT ({_INSTALL_FLOOR_COLUMNS}) ON public.{INSTALLS}"
        " FROM plugin_install_base"
    )
    op.execute(
        "REVOKE SELECT (guild_id, install_id, listing_uid, status),"
        f" UPDATE (status, status_changed_at) ON public.{INSTALLS}"
        f" FROM {_billing_role()}"
    )
    for column in (
        "plugin_status_sent",
        "suspended_by",
        "suspended_at",
        "status_changed_at",
    ):
        op.drop_column(INSTALLS, column)
    op.drop_constraint("ck_plugin_installs_status", INSTALLS)
    op.drop_column(INSTALLS, "status")

    op.add_column(
        REGISTRATIONS,
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
    )
    _unforced_update(
        f"UPDATE public.{REGISTRATIONS} SET enabled = false"
        " WHERE suspended_at IS NOT NULL"
    )
    op.execute(
        f"GRANT SELECT (enabled) ON public.{REGISTRATIONS} TO plugin_install_base"
    )
    op.drop_column(REGISTRATIONS, "suspended_by")
    op.drop_column(REGISTRATIONS, "suspended_at")
