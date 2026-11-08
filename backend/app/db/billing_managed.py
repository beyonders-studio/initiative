"""Whether this deployment's plans are set by its billing service.

``public.billing_managed()`` answers that inside the database, for the
triggers on ``guilds`` and ``guild_administration`` (migration 0364) that hold
a billing-managed deployment's plan columns and lifecycle statuses to billing.
Its body is a constant rendered here from the environment on every boot, over
the provisioning engine, which owns the function.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection

logger = logging.getLogger(__name__)


def billing_managed_sql(managed: bool) -> str:
    """The function, answering ``managed``."""
    return (
        "CREATE OR REPLACE FUNCTION public.billing_managed()\n"
        " RETURNS boolean\n"
        " LANGUAGE sql\n"
        " STABLE\n"
        f"AS $function$ SELECT {'true' if managed else 'false'} $function$"
    )


async def apply_billing_managed(conn: AsyncConnection, *, managed: bool) -> None:
    from sqlalchemy import text

    await conn.execute(text(billing_managed_sql(managed)))


async def ensure_billing_managed() -> None:
    """Render the function from the environment, after the migrations."""
    from app.db import session as db_session
    from app.services.platform.billing import billing_managed

    managed = billing_managed()
    async with db_session.provisioning_engine.begin() as conn:
        await apply_billing_managed(conn, managed=managed)
    logger.info("billing-managed plans: %s", "on" if managed else "off")
