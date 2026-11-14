"""unsigned devices are removed

A message device has signed its keys since 0.73; one registered before that
signed itself the next time it opened. A device that never did is removed, with
its keys, queue and verification messages (they cascade), so every device and
key now carries a signature: both columns become NOT NULL, and nothing updates
a signature any more, so the platform floor's column grant on it goes.

Such a device registers again when it next opens, and its local message history
goes with the old registration.

Revision ID: 20261109_0600
Revises: 20261109_0599
Create Date: 2026-11-09
"""

from alembic import op

from app.core.config import settings

revision = "20261109_0600"
down_revision = "20261109_0599"
branch_labels = None
depends_on = None

_TABLES = ("dm_devices", "dm_one_time_keys")


def _platform_base() -> str:
    return f'"{settings.PLATFORM_ROLE_PREFIX}platform_base"'


def upgrade() -> None:
    # The migration's own deletes match no policy, so the tables' forced row
    # security is lifted around them.
    for table in _TABLES:
        op.execute(f"ALTER TABLE public.{table} NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute("DELETE FROM public.dm_devices WHERE signature IS NULL")
        op.execute("DELETE FROM public.dm_one_time_keys WHERE signature IS NULL")
    finally:
        for table in _TABLES:
            op.execute(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY")
    for table in _TABLES:
        op.execute(f"ALTER TABLE public.{table} ALTER COLUMN signature SET NOT NULL")
    op.execute(
        f"REVOKE UPDATE (signature) ON public.dm_devices FROM {_platform_base()}"
    )


def downgrade() -> None:
    """The removed devices are not restored."""
    op.execute(f"GRANT UPDATE (signature) ON public.dm_devices TO {_platform_base()}")
    for table in _TABLES:
        op.execute(f"ALTER TABLE public.{table} ALTER COLUMN signature DROP NOT NULL")
