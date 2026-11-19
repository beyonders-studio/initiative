"""a community uninstalls a tool plug-in

- ``plugin_installs.uninstalled_at``: when the community's admin uninstalled
  a tool plug-in, consenting to its content being deleted once the deletion
  window ends. Stamped with the move to ``deleted`` (``status_changed_at``),
  so a later move of the status is staff's or billing's, not the
  community's. Until the window ends the community may install it again.
- The guild floors read the state of their own community's installs, of a
  tool plug-in's registration and of its beta list, which a member's standing
  asks of each tool plug-in installed there. Column grants only; the policies
  are rendered from the shared-table registry at boot.

Revision ID: 20261118_0617
Revises: 20261118_0616
Create Date: 2026-11-18
"""

import sqlalchemy as sa
from alembic import op

revision = "20261118_0617"
down_revision = "20261118_0616"
branch_labels = None
depends_on = None

FLOORS = "app_guild_base, app_guild_base_ro"

#: What each floor reads, by table.
_READS = {
    "plugin_installs": "guild_id, install_id, status, suspended_at",
    "plugin_service_registrations": "listing_uid, kind, suspended_at, availability",
    "plugin_beta_communities": "listing_uid, community_id",
}


def upgrade() -> None:
    op.add_column(
        "plugin_installs",
        sa.Column("uninstalled_at", sa.DateTime(timezone=True), nullable=True),
    )
    for table, columns in _READS.items():
        op.execute(f"GRANT SELECT ({columns}) ON public.{table} TO {FLOORS}")


def downgrade() -> None:
    for table, columns in _READS.items():
        op.execute(f"REVOKE SELECT ({columns}) ON public.{table} FROM {FLOORS}")
    op.drop_column("plugin_installs", "uninstalled_at")
