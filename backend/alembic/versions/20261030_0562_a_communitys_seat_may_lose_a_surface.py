"""a community's seat may lose a surface

Two surface keys join the community rules (see ``app.core.rules``):
``surface.ai_connections`` and ``surface.plugins``, each open until the
deployment closes it for one community. Only the deployment writes one, so
``rule_key_writers`` gains a ``deployment`` row for each.

``public.community_surface_open()`` answers whether a surface is open, and the
seat's write policies on that surface's tables ask it; those policies are
rendered with every community's schema at boot. Its body is restated here as
this revision installs it.

Revision ID: 20261030_0562
Revises: 20261030_0561
Create Date: 2026-10-30
"""

from alembic import op

revision = "20261030_0562"
down_revision = "20261030_0561"
branch_labels = None
depends_on = None

SURFACES = ("surface.ai_connections", "surface.plugins")

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


def upgrade() -> None:
    for key in SURFACES:
        op.execute(
            "INSERT INTO public.rule_key_writers (key, set_by)"
            f" VALUES ('{key}', 'deployment')"
        )
    op.get_bind().exec_driver_sql(COMMUNITY_SURFACE_OPEN)


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(
        "ALTER TABLE public.community_rules NO FORCE ROW LEVEL SECURITY"
    )
    try:
        bind.exec_driver_sql(
            "DELETE FROM public.community_rules"
            " WHERE key IN ('surface.ai_connections', 'surface.plugins')"
        )
    finally:
        bind.exec_driver_sql(
            "ALTER TABLE public.community_rules FORCE ROW LEVEL SECURITY"
        )
    # The policies that ask it are rendered again, without it, by the version
    # being returned to.
    bind.exec_driver_sql(
        "DROP FUNCTION public.community_surface_open(integer, text) CASCADE"
    )
    for key in SURFACES:
        op.execute(f"DELETE FROM public.rule_key_writers WHERE key = '{key}'")
