"""RLS / role-security tests for the auth identity foundation.

Locks in a deliberate least-privilege decision (see the migration
20260705_0131):

* ``federated_identities`` is **own-row** on the request path — a platform tier
  sees only its own links, and there is NO admin-read-all policy (platform user
  management runs on the system engine, not the request path).

Style mirrors ``platform_role_rls_test``: the ``session`` fixture connects as the
superuser, but ``SET ROLE platform_<tier>`` drops to a non-superuser role so RLS
and table GRANTs are enforced exactly like the production request path.
"""

import pytest
from sqlalchemy import text

from app.db.public_rls import platform_tier, role_name
from app.testing import as_role, create_user


async def _make_provider(session, slug: str) -> int:
    return (
        await session.exec(
            text(
                "INSERT INTO auth_providers "
                "(slug, display_name, kind, enabled, allow_jit, created_at, updated_at) "
                "VALUES (:s, :s, 'oidc', true, true, now(), now()) RETURNING id"
            ),
            params={"s": slug},
        )
    ).scalar_one()


async def _link(session, user_id: int, provider_id: int, subject: str) -> None:
    await session.exec(
        text(
            "INSERT INTO federated_identities "
            "(user_id, provider_id, subject, email_verified, created_at) "
            "VALUES (:u, :p, :sub, true, now())"
        ),
        params={"u": user_id, "p": provider_id, "sub": subject},
    )


@pytest.mark.parametrize("tier", ["member", "operator"])
async def test_federated_identity_is_own_row_on_request_path(session, tier):
    """No operator-read-all policy: every tier sees only its own links on the
    request path — cross-user identity reads run on the system engine."""
    provider = await _make_provider(session, f"acme-{tier}")
    u1 = await create_user(session)
    u2 = await create_user(session)
    await _link(session, u1.id, provider, "sub-1")
    await _link(session, u2.id, provider, "sub-2")

    async with as_role(session, role_name(platform_tier(tier)), u1.id):
        rows = {
            r[0]
            for r in (
                await session.exec(text("SELECT user_id FROM federated_identities"))
            ).fetchall()
        }
    assert rows == {u1.id}
