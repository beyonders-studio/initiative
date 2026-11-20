"""the platform connects for every community

- ``plugin_service_registrations.shared_routes``, ``plugin_installs.exclusive``
  and ``uq_plugin_installs_exclusive_route`` go: every community that connects
  the same vendor account holds its route, and a delivery goes to each.
- ``plugin_service_registrations.platform_connections``: the community
  connections the operator connected once for every community, by connection
  id. No grant: only the system engine reads the table's new column. A change
  to it is announced on ``plugin_states`` at commit, as a suspension is, so
  every process reads the communities' connection afresh.

Revision ID: 20261119_0618
Revises: 20261118_0617
Create Date: 2026-11-19
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261119_0618"
down_revision = "20261118_0617"
branch_labels = None
depends_on = None

INDEX = "uq_plugin_installs_exclusive_route"
REGISTRATIONS = "plugin_service_registrations"

#: A registration's suspension, reach or platform connections moved; the
#: second spelling is 20261115_0610's.
_REGISTRATION_MOVED = (
    f"AFTER UPDATE OF suspended_at, availability, platform_connections"
    f" ON public.{REGISTRATIONS} FOR EACH ROW"
    " WHEN (OLD.suspended_at IS DISTINCT FROM NEW.suspended_at"
    " OR OLD.availability IS DISTINCT FROM NEW.availability"
    " OR OLD.platform_connections IS DISTINCT FROM NEW.platform_connections)"
)
_REGISTRATION_MOVED_BEFORE = (
    f"AFTER UPDATE OF suspended_at, availability ON public.{REGISTRATIONS}"
    " FOR EACH ROW WHEN (OLD.suspended_at IS DISTINCT FROM NEW.suspended_at"
    " OR OLD.availability IS DISTINCT FROM NEW.availability)"
)


def _registration_trigger(when: str) -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS plugin_registration_state_notify"
        f" ON public.{REGISTRATIONS}"
    )
    op.execute(
        f"CREATE TRIGGER plugin_registration_state_notify {when}"
        " EXECUTE FUNCTION public.plugin_state_notify()"
    )


def upgrade() -> None:
    op.drop_index(INDEX, table_name="plugin_installs")
    op.drop_column("plugin_installs", "exclusive")
    op.drop_column("plugin_service_registrations", "shared_routes")
    op.add_column(
        "plugin_service_registrations",
        sa.Column(
            "platform_connections",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
    )
    _registration_trigger(_REGISTRATION_MOVED)


def downgrade() -> None:
    _registration_trigger(_REGISTRATION_MOVED_BEFORE)
    op.drop_column("plugin_service_registrations", "platform_connections")
    # Every registration comes back sharing its routes, which is what each
    # route held by more than one community needs.
    op.add_column(
        "plugin_service_registrations",
        sa.Column("shared_routes", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.alter_column(
        "plugin_service_registrations", "shared_routes", server_default="false"
    )
    op.add_column(
        "plugin_installs",
        sa.Column("exclusive", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.alter_column("plugin_installs", "exclusive", server_default="true")
    op.create_index(
        INDEX,
        "plugin_installs",
        ["listing_uid", "hook_route"],
        unique=True,
        postgresql_where=sa.text("exclusive AND hook_route IS NOT NULL"),
    )
