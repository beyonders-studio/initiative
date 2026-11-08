"""What somebody did with a grant, not just that they held one.

The grant itself is recorded when it is issued. These pin the other half: one
line per request served through it, so "an operator held this community for an
hour" and "an operator opened four hundred files" read differently.
"""

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.models.platform.guild import CommunityRole, Guild
from app.testing import Actor, create_guild, emitted

BREAK_GLASS = "/api/v1/access-grants/break-glass"
PAM = AuditEventType.PAM_REQUEST


@pytest.fixture
async def outsider(acting_user, session: AsyncSession):
    """An operator, and a community they do not belong to."""

    async def _make(tier: str = "operator") -> tuple[Actor, Guild]:
        return await acting_user(tier), await create_guild(session)

    return _make


async def _break_glass(client: AsyncClient, actor: Actor, guild: Guild) -> None:
    issued = await client.post(
        BREAK_GLASS,
        json={"community_id": guild.id, "reason": "prod incident #42"},
        headers=actor.headers,
    )
    assert issued.status_code == 201, issued.text


async def test_each_request_through_a_grant_is_written_down(
    client: AsyncClient, acting_user, outsider, capfd
):
    a, guild = await outsider()
    await acting_user(guild_role=CommunityRole.admin, guild=guild, initiative=True)
    await _break_glass(client, a, guild)
    capfd.readouterr()

    reached = await client.get(f"/api/v1/c/{guild.id}/initiatives/", headers=a.headers)
    assert reached.status_code == 200, reached.text

    (line,) = emitted(capfd, PAM)
    assert line["actor_user_id"] == a.user.id
    assert line["guild_id"] == guild.id
    assert line["tier"] == 1
    assert line["category"] == "authorization"
    # The reach is recorded; what a request changed is its own event.
    assert line["is_write"] is False
    assert line["detail"] == {
        "method": "GET",
        "route": "/api/v1/c/{community_id}/initiatives/",
        "status": 200,
        "reached": {"community_id": guild.id},
    }


async def test_the_line_names_the_grant_that_served_it(
    client: AsyncClient, acting_user, outsider, capfd
):
    """Which grant, at what level, and whether somebody let themselves in."""
    a, guild = await outsider()
    await acting_user(guild_role=CommunityRole.admin, guild=guild, initiative=True)
    await _break_glass(client, a, guild)
    capfd.readouterr()

    await client.get(f"/api/v1/c/{guild.id}/initiatives/", headers=a.headers)

    (line,) = emitted(capfd, PAM)
    context = line["context"]
    assert context["grant_id"] is not None
    assert context["access_level"] == "read_write"
    assert context["settings_grant_id"] is not None
    assert context["settings_level"] == "superadmin"
    assert context["break_glass"] is True
    assert context["request_id"]


async def test_a_member_reaching_their_own_community_is_not_recorded(
    client: AsyncClient, acting_user, capfd
):
    """This log is about privileged access. Every member's every request would
    be a different feature, and a far larger one."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    capfd.readouterr()

    reached = await client.get(
        f"/api/v1/c/{a.guild.id}/initiatives/", headers=a.headers
    )
    assert reached.status_code == 200

    assert emitted(capfd, PAM) == []


async def test_a_refused_request_is_recorded_with_what_it_was_refused(
    client: AsyncClient, acting_user, outsider, capfd
):
    """A grantee reaching past what the grant allows is exactly what somebody
    reviewing the window wants to see."""
    a, guild = await outsider()
    await acting_user(guild_role=CommunityRole.admin, guild=guild, initiative=True)
    await _break_glass(client, a, guild)
    capfd.readouterr()

    refused = await client.post(
        f"/api/v1/c/{guild.id}/initiatives/",
        json={"name": "Not mine to make"},
        headers=a.headers,
    )
    assert refused.status_code >= 400

    (line,) = emitted(capfd, PAM)
    assert line["detail"]["method"] == "POST"
    assert line["detail"]["status"] == refused.status_code


async def test_reaching_nothing_still_records_the_attempt(
    client: AsyncClient, acting_user, outsider, capfd
):
    """A grant that reaches one community does not reach another, and the
    request that tried is still part of the window's record."""
    a, guild = await outsider()
    await _break_glass(client, a, guild)
    capfd.readouterr()

    missing = await client.get(
        f"/api/v1/c/{guild.id}/initiatives/9999", headers=a.headers
    )
    assert missing.status_code == 404

    (line,) = emitted(capfd, PAM)
    assert line["detail"]["status"] == 404
    assert line["detail"]["reached"] == {
        "community_id": guild.id,
        "initiative_id": 9999,
    }
