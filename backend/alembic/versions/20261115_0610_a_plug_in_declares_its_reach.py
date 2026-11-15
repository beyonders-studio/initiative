"""a plug-in declares its reach

- ``plugin_service_registrations.availability`` (``none``, ``beta`` or
  ``operations``), written from the listing's latest manifest, in place of
  ``operations_only``: a registration limited to the operations community is
  ``operations`` until its next apply. The install floor and the billing
  change log's writer read it where they read ``operations_only``.
- ``plugin_beta_communities``: the communities the owner picks for a beta
  plug-in, by listing. The system engine reads and writes it; an installed
  plug-in's standing reads its own community's row, and the change log's
  writer reads it to tell billing whether an install is in reach. Nothing to
  backfill, so it is locked down as soon as it exists. Its policies are
  rendered from the shared-table registry at boot.
- ``public.billing_plugin_status`` counts an install out of reach as
  suspended by either spelling.
- A registration's reach moving, or its beta list, is announced on
  ``plugin_states`` at commit, as a suspension is.

Revision ID: 20261115_0610
Revises: 20261115_0609
Create Date: 2026-11-15
"""

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20261115_0610"
down_revision = "20261115_0609"
branch_labels = None
depends_on = None

REGISTRATIONS = "plugin_service_registrations"
BETA = "plugin_beta_communities"
#: The billing change log's writer (migration 20261021_0532).
WRITER = '"app_billing_log"'
CHECK = "ck_plugin_service_registrations_availability"


def _plugin_status(reach: str) -> str:
    """``public.billing_plugin_status`` as 20261115_0609 wrote it, with an
    install out of the registration ``r``'s reach when ``reach`` holds."""
    return f"""
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
                  AND (r.suspended_at IS NOT NULL OR {reach})
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


_OPERATIONS = (
    "i.guild_id IS DISTINCT FROM ("
    "SELECT s.operations_guild_id FROM public.app_settings s WHERE s.id = 1)"
)
_OUT_OF_REACH = f"""(
                       (r.availability = 'operations' AND {_OPERATIONS})
                       OR (r.availability = 'beta' AND NOT EXISTS (
                           SELECT 1 FROM public.plugin_beta_communities b
                            WHERE b.listing_uid = r.listing_uid
                              AND b.community_id = i.guild_id)))"""
_OUT_OF_REACH_BEFORE = f"(r.operations_only AND {_OPERATIONS})"

#: A registration's suspension or reach moved; the second spelling is
#: 20261115_0609's.
_REGISTRATION_MOVED = (
    f"AFTER UPDATE OF suspended_at, availability ON public.{REGISTRATIONS}"
    " FOR EACH ROW WHEN (OLD.suspended_at IS DISTINCT FROM NEW.suspended_at"
    " OR OLD.availability IS DISTINCT FROM NEW.availability)"
)
_REGISTRATION_MOVED_BEFORE = (
    f"AFTER UPDATE OF suspended_at ON public.{REGISTRATIONS} FOR EACH ROW"
    " WHEN (OLD.suspended_at IS DISTINCT FROM NEW.suspended_at)"
)


def _registration_trigger(when: str) -> None:
    op.execute(
        f"DROP TRIGGER IF EXISTS plugin_registration_state_notify"
        f" ON public.{REGISTRATIONS}"
    )
    op.execute(
        f"CREATE TRIGGER plugin_registration_state_notify {when}"
        " EXECUTE FUNCTION public.plugin_state_notify()"
    )


def _unforced_update(statement: str) -> None:
    """Run ``statement`` on the registrations with their row security lifted,
    and put it back: no policy admits the migration's own role."""
    op.execute(f"ALTER TABLE public.{REGISTRATIONS} NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute(statement)
    finally:
        op.execute(f"ALTER TABLE public.{REGISTRATIONS} FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    op.add_column(
        REGISTRATIONS,
        sa.Column("availability", sa.Text(), server_default="none", nullable=False),
    )
    op.create_check_constraint(
        CHECK, REGISTRATIONS, "availability IN ('none', 'beta', 'operations')"
    )
    _unforced_update(
        f"UPDATE public.{REGISTRATIONS} SET availability = 'operations'"
        " WHERE operations_only"
    )
    # Its column grants go with it.
    op.drop_column(REGISTRATIONS, "operations_only")
    op.execute(
        f"GRANT SELECT (availability) ON public.{REGISTRATIONS}"
        f" TO plugin_install_base, {WRITER}"
    )

    op.create_table(
        BETA,
        sa.Column("listing_uid", sa.String(length=14), nullable=False),
        sa.Column("community_id", sa.Integer(), nullable=False),
        sa.Column("added_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["listing_uid"], ["public.marketplace_listings.uid"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["community_id"], ["public.guilds.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["added_by"], ["public.users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("listing_uid", "community_id"),
        schema="public",
    )
    op.create_index(f"ix_{BETA}_community_id", BETA, ["community_id"], schema="public")
    base = f"{settings.PLATFORM_ROLE_PREFIX}platform_base"
    for statement in (
        f"ALTER TABLE public.{BETA} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE public.{BETA} FORCE ROW LEVEL SECURITY",
        # The schema's default privileges hand every new public table to both
        # floors, so they are wound back before anything is given.
        f'REVOKE ALL ON TABLE public.{BETA} FROM app_guild_base, "{base}"',
        f"GRANT SELECT, INSERT, DELETE ON TABLE public.{BETA} TO app_admin",
        f"GRANT SELECT (listing_uid, community_id) ON TABLE public.{BETA}"
        f" TO plugin_install_base, {WRITER}",
    ):
        op.execute(statement)

    op.execute(_plugin_status(_OUT_OF_REACH))
    _registration_trigger(_REGISTRATION_MOVED)
    op.execute(
        f"CREATE TRIGGER plugin_beta_communities_notify AFTER INSERT OR DELETE"
        f" ON public.{BETA} FOR EACH STATEMENT"
        " EXECUTE FUNCTION public.plugin_state_notify()"
    )


def downgrade() -> None:
    op.add_column(
        REGISTRATIONS,
        sa.Column(
            "operations_only", sa.Boolean(), server_default="false", nullable=False
        ),
    )
    _unforced_update(
        f"UPDATE public.{REGISTRATIONS} SET operations_only = true"
        " WHERE availability = 'operations'"
    )
    op.execute(
        f"GRANT SELECT (operations_only) ON public.{REGISTRATIONS}"
        f" TO plugin_install_base, {WRITER}"
    )
    op.execute(_plugin_status(_OUT_OF_REACH_BEFORE))
    _registration_trigger(_REGISTRATION_MOVED_BEFORE)

    bind = op.get_bind()
    for (name,) in bind.execute(
        sa.text("SELECT polname FROM pg_policy WHERE polrelid = to_regclass(:t)"),
        {"t": f"public.{BETA}"},
    ).all():
        op.execute(f'DROP POLICY IF EXISTS "{name}" ON public.{BETA}')
    op.drop_table(BETA, schema="public")

    op.drop_constraint(CHECK, REGISTRATIONS)
    op.drop_column(REGISTRATIONS, "availability")
