"""who may join and create are rules

Five of the deployment's switches and limits were read from the environment
on every start. They become platform rules (see ``app.core.rules``), edited in
Settings → Platform, and the environment seeds them once, here, on the upgrade
that moves them and on a fresh install's first start:

- ``ENABLE_PUBLIC_REGISTRATION`` → ``public_registration_enabled``;
- ``DISABLE_GUILD_CREATION`` → ``community_creation_enabled``, its opposite;
- ``GUILD_CREATION_DAILY_LIMIT`` → ``community_creation_daily_limit``;
- ``HIBP_CHECK_ENABLED`` → ``breached_password_check_enabled``;
- ``EXPORT_GUILD_COOLDOWN_HOURS`` → ``community_export_cooldown_hours``.

A value equal to its rule's default writes no row. ``platform_rules`` is
policy-bound for this revision's own role, so it is unforced for the seed and
forced again in the same transaction. The downgrade removes the rows, and the
environment decides again.

Revision ID: 20261030_0560
Revises: 20261029_0559
Create Date: 2026-10-30
"""

from alembic import op
import sqlalchemy as sa

from app.core.config import settings

revision = "20261030_0560"
down_revision = "20261029_0559"
branch_labels = None
depends_on = None

#: (rule key, slot, the environment's value, the rule's default).
SEEDS = (
    (
        "public_registration_enabled",
        "enabled",
        settings.ENABLE_PUBLIC_REGISTRATION,
        True,
    ),
    (
        "community_creation_enabled",
        "enabled",
        not settings.DISABLE_GUILD_CREATION,
        True,
    ),
    (
        "community_creation_daily_limit",
        "amount",
        settings.GUILD_CREATION_DAILY_LIMIT,
        5,
    ),
    ("breached_password_check_enabled", "enabled", settings.HIBP_CHECK_ENABLED, True),
    (
        "community_export_cooldown_hours",
        "amount",
        settings.EXPORT_GUILD_COOLDOWN_HOURS,
        48,
    ),
)
KEYS = "ARRAY[" + ", ".join(f"'{key}'" for key, *_ in SEEDS) + "]"


def upgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(
        "ALTER TABLE public.platform_rules NO FORCE ROW LEVEL SECURITY"
    )
    try:
        for key, slot, value, default in SEEDS:
            if value == default:
                continue
            bind.execute(
                sa.text(
                    f"INSERT INTO public.platform_rules (key, {slot}, updated_at)"
                    " VALUES (:key, :value, now())"
                    " ON CONFLICT (key) DO NOTHING"
                ),
                {"key": key, "value": value},
            )
    finally:
        bind.exec_driver_sql(
            "ALTER TABLE public.platform_rules FORCE ROW LEVEL SECURITY"
        )


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(
        "ALTER TABLE public.platform_rules NO FORCE ROW LEVEL SECURITY"
    )
    try:
        bind.exec_driver_sql(
            f"DELETE FROM public.platform_rules WHERE key = ANY({KEYS})"
        )
    finally:
        bind.exec_driver_sql(
            "ALTER TABLE public.platform_rules FORCE ROW LEVEL SECURITY"
        )
