"""What the operator surfaces write down.

An operator reaches accounts and communities they are not in, so what they do
is recorded with the community it touched.
"""

from __future__ import annotations

import pytest
from httpx2 import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.models.platform.guild import CommunityRole
from app.models.platform.user import UserRole
from app.testing import emitted
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_user,
    get_auth_headers,
)


def _where(row) -> tuple:
    return (
        row["actor_user_id"],
        row["target_user_id"],
        row["guild_id"],
        row["target"],
    )


# --- accounts ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("action", "event_type"),
    [
        ("deactivate", AuditEventType.USER_DEACTIVATED),
        ("soft_delete", AuditEventType.USER_DELETION_SCHEDULED),
        ("hard_delete", AuditEventType.USER_DELETED),
    ],
)
async def test_closing_someone_elses_account_is_recorded_against_them(
    client: AsyncClient, session: AsyncSession, action: str, event_type, capfd
):
    operator = await create_user(session, role=UserRole.operator)
    operator_id = operator.id
    target = await create_user(session)
    target_id = target.id
    capfd.readouterr()

    response = await client.request(
        "DELETE",
        f"/api/v1/operator/users/{target_id}",
        headers=get_auth_headers(operator),
        json={"action": action},
    )
    assert response.status_code == 200, response.text

    rows = emitted(capfd, event_type)
    assert [_where(row) for row in rows] == [
        (operator_id, target_id, None, {"type": "user", "id": target_id})
    ]
    assert rows[0]["detail"] == {"self": False}


@pytest.mark.parametrize("action", ["deactivate", "hard_delete"])
async def test_closing_an_account_records_every_community_it_left(
    client: AsyncClient, session: AsyncSession, action: str, capfd
):
    operator = await create_user(session, role=UserRole.operator)
    operator_id = operator.id
    owner = await create_user(session)
    guild = await create_guild(session, creator=owner)
    guild_id = guild.id
    await create_guild_membership(
        session, user=owner, guild=guild, role=CommunityRole.superadmin
    )
    target = await create_user(session)
    target_id = target.id
    await create_guild_membership(
        session, user=target, guild=guild, role=CommunityRole.member
    )
    capfd.readouterr()

    response = await client.request(
        "DELETE",
        f"/api/v1/operator/users/{target_id}",
        headers=get_auth_headers(operator),
        json={"action": action},
    )
    assert response.status_code == 200, response.text

    rows = emitted(capfd, AuditEventType.GUILD_MEMBER_REMOVED)
    assert [_where(row) for row in rows] == [
        (operator_id, target_id, guild_id, {"type": "guild", "id": guild_id})
    ]
    assert rows[0]["detail"] == {"role": "member", "via": "account_closed"}


async def test_a_refused_account_deletion_records_nothing(
    client: AsyncClient, session: AsyncSession, capfd
):
    """Deleting yourself from here is refused; nothing happened to record."""
    operator = await create_user(session, role=UserRole.operator)
    capfd.readouterr()

    response = await client.request(
        "DELETE",
        f"/api/v1/operator/users/{operator.id}",
        headers=get_auth_headers(operator),
        json={"action": "deactivate"},
    )
    assert response.status_code == 400
    assert emitted(capfd, AuditEventType.USER_DEACTIVATED) == []
