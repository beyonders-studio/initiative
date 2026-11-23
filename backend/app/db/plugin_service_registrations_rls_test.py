"""Role-security test for the plug-in service registry.

The table holds each plug-in's shared-secret ciphertext and is written on the
system engine alone: the schema's default privileges are wound back,
``app_admin`` carries every verb, and no person's request-path role holds a
grant or a policy on it. The other readers are the install floor, whose
standing statement reads four columns of the registration its token names, and
the billing change log's writer, which records a plug-in's status.

Style mirrors ``auth_sessions_rls_test``: ``SET ROLE platform_<tier>``
drops to a non-superuser role so table GRANTs and policies are enforced exactly
as they are on a real request.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db.public_rls import (
    platform_tier,
    role_name,
)
from app.models.platform.user import UserRole
from app.testing import as_role, create_user

TABLE = "plugin_service_registrations"


async def _make_row(session, public_id: str = "acme.widgets") -> None:
    await session.exec(
        text(
            "INSERT INTO public.publishers (prefix, display_name, verified, enabled, "
            "created_at) VALUES ('acme', 'Acme', false, true, now()) "
            "ON CONFLICT (prefix) DO NOTHING"
        )
    )
    await session.exec(
        text(
            f"INSERT INTO {TABLE} "
            "(public_id, publisher_id, base_url, allowed_origins, jwks, "
            " mandatory, created_at, updated_at) "
            "SELECT :pid, p.id, 'http://127.0.0.1:9100', '[]'::jsonb, "
            " '{\"keys\": []}'::jsonb, false, now(), now() "
            "FROM public.publishers p WHERE p.prefix = 'acme'"
        ),
        params={"pid": public_id},
    )


async def test_no_platform_tier_reads_or_writes_registrations(session):
    """Every tier, the owner included, is refused at the grant layer."""
    user = await create_user(session)
    await _make_row(session)

    for tier in UserRole:
        for statement in (
            f"SELECT jwks FROM {TABLE}",
            f"UPDATE {TABLE} SET suspended_at = now()",
            f"DELETE FROM {TABLE}",
        ):
            async with as_role(session, role_name(platform_tier(tier)), user.id):
                with pytest.raises(DBAPIError):
                    async with session.begin_nested():
                        await session.exec(text(statement))
