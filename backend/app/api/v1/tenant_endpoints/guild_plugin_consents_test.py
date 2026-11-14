"""The community's side of a plug-in acting as its members.

A member answers a plug-in's request to act as them on their own consent screen
(``plugin_member_tokens_test``). The community's seat sees every answer an install
holds and can end them, one member's or everybody's, and never give one. And an
answer lasts only as long as the relationship behind it: a member leaving the
community, or the plug-in being uninstalled, takes it with them.

Every answer is in the audit log naming both the person who acted and the
member whose consent it was, with ``via`` telling the member's own withdrawal
from the seat's.
"""

from __future__ import annotations

from httpx2 import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.core.plugin_access_token import seal_install_token
from app.models.platform.guild import CommunityRole
from app.models.tenant.plugin_member_consent import PluginMemberConsent
from app.services.marketplace.plugin_refs import ensure_plugin_ref
from app.testing import emitted, route_session_to_guild
from app.testing.plugin_clients import CLIENT, InstalledPlugin, install_plugin

CONSENT_URL = "/api/v1/plugin-platform/consent-requests"


async def _installed(session, acting_user, role_session) -> InstalledPlugin:
    return await install_plugin(
        session, acting_user, role_session, granted=["files:read"]
    )


async def _member(acting_user, installed: InstalledPlugin):
    return await acting_user(
        guild_role=CommunityRole.member,
        guild=installed.guild,
        initiative=installed.placed,
        initiative_role="member",
    )


async def _asked(client: AsyncClient, installed: InstalledPlugin, member) -> int:
    """The plug-in asks ``member`` for one purpose; returns the request's id, as
    the member's own list shows it."""
    token, _exp = seal_install_token(
        guild_id=installed.guild.id,
        install_id=installed.plugin.id,
        client_id=CLIENT,
        scopes=frozenset(["files:read"]),
        initiative_id=None,
    )
    asked = await client.post(
        CONSENT_URL,
        json={
            "member": await ensure_plugin_ref(
                guild_id=installed.guild.id,
                public_id=installed.public_id,
                user_id=member.user.id,
            ),
            "purpose": "node-1",
            "label": "Comment on the linked issue as you",
            "access": "read",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert asked.status_code in (200, 201), asked.text
    listed = await client.get(
        member.g(f"/plugins/{installed.plugin.id}"), headers=member.headers
    )
    (row,) = listed.json()["consents"]
    return row["id"]


async def _granted(client: AsyncClient, installed: InstalledPlugin, member) -> int:
    consent_id = await _asked(client, installed, member)
    answered = await client.put(
        member.g(f"/plugins/{installed.plugin.id}/consents/{consent_id}"),
        headers=member.headers,
        json={"access": "read"},
    )
    assert answered.status_code == 200, answered.text
    return consent_id


async def _statuses(client: AsyncClient, installed: InstalledPlugin) -> dict[int, str]:
    members = await client.get(
        installed.seat.g(f"/plugins/{installed.plugin.id}/members"),
        headers=installed.seat.headers,
    )
    assert members.status_code == 200, members.text
    return {row["user_id"]: row["status"] for row in members.json()["consents"]}


async def _rows_for(session: AsyncSession, guild_id: int, user_id: int) -> list:
    await route_session_to_guild(session, guild_id)
    return list(
        (
            await session.exec(
                select(PluginMemberConsent).where(
                    PluginMemberConsent.user_id == user_id
                )
            )
        ).all()
    )


# --- what the seat sees and ends ---------------------------------------------


async def test_the_seat_sees_every_members_answers(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    installed = await _installed(session, acting_user, role_session)
    answered = await _member(acting_user, installed)
    waiting = await _member(acting_user, installed)
    await _granted(client, installed, answered)
    await _asked(client, installed, waiting)

    members = await client.get(
        installed.seat.g(f"/plugins/{installed.plugin.id}/members"),
        headers=installed.seat.headers,
    )

    assert members.status_code == 200, members.text
    rows = {row["user_id"]: row for row in members.json()["consents"]}
    assert rows[answered.user.id]["status"] == "granted"
    assert rows[answered.user.id]["granted_access"] == "read"
    assert rows[answered.user.id]["label"] == "Comment on the linked issue as you"
    assert rows[waiting.user.id]["status"] == "pending"
    assert members.json()["consent_summary"] == {
        "member_count": 2,
        "allowed_count": 1,
        "open_count": 2,
    }


async def test_a_member_does_not_get_the_members_view(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    installed = await _installed(session, acting_user, role_session)
    member = await _member(acting_user, installed)

    response = await client.get(
        member.g(f"/plugins/{installed.plugin.id}/members"), headers=member.headers
    )

    assert response.status_code == 403


async def test_the_seat_ends_one_members_answers_and_nobody_elses(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    installed = await _installed(session, acting_user, role_session)
    ended = await _member(acting_user, installed)
    kept = await _member(acting_user, installed)
    for member in (ended, kept):
        await _granted(client, installed, member)

    response = await client.delete(
        installed.seat.g(
            f"/plugins/{installed.plugin.id}/members/{ended.user.id}/consents"
        ),
        headers=installed.seat.headers,
    )

    assert response.status_code == 204, response.text
    assert await _statuses(client, installed) == {
        ended.user.id: "revoked",
        kept.user.id: "granted",
    }


async def test_a_member_cannot_end_anybodys(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    installed = await _installed(session, acting_user, role_session)
    member = await _member(acting_user, installed)
    other = await _member(acting_user, installed)
    await _granted(client, installed, other)

    everyone = await client.post(
        member.g(f"/plugins/{installed.plugin.id}/consents/revoke-all"),
        headers=member.headers,
    )
    one = await client.delete(
        member.g(f"/plugins/{installed.plugin.id}/members/{other.user.id}/consents"),
        headers=member.headers,
    )

    assert everyone.status_code == 403
    assert one.status_code == 403
    assert (await _statuses(client, installed))[other.user.id] == "granted"


# --- when the relationship ends ----------------------------------------------


async def test_leaving_the_community_takes_their_answers(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    """A member who leaves has not left a plug-in able to act as them."""
    installed = await _installed(session, acting_user, role_session)
    leaver = await _member(acting_user, installed)
    await _granted(client, installed, leaver)

    left = await client.delete(
        f"/api/v1/communities/{installed.guild.id}/leave", headers=leaver.headers
    )

    assert left.status_code == 204, left.text
    assert await _rows_for(session, installed.guild.id, leaver.user.id) == []


async def test_uninstalling_takes_every_answer_and_counts_them(
    client: AsyncClient, session: AsyncSession, acting_user, role_session, capfd
):
    installed = await _installed(session, acting_user, role_session)
    member = await _member(acting_user, installed)
    await _granted(client, installed, member)
    capfd.readouterr()

    removed = await client.delete(
        installed.seat.g(f"/plugins/{installed.plugin.id}"),
        headers=installed.seat.headers,
    )

    assert removed.status_code == 204, removed.text
    (row,) = emitted(capfd, AuditEventType.PLUGIN_UNINSTALLED)
    assert row["detail"]["consents"] == 1
    assert await _rows_for(session, installed.guild.id, member.user.id) == []


# --- the audit log -----------------------------------------------------------


async def test_allowing_a_request_records_the_member_and_the_depth(
    client: AsyncClient, session: AsyncSession, acting_user, role_session, capfd
):
    installed = await _installed(session, acting_user, role_session)
    member = await _member(acting_user, installed)
    capfd.readouterr()

    consent_id = await _granted(client, installed, member)

    (row,) = emitted(capfd, AuditEventType.PLUGIN_CONSENT_GRANTED)
    assert row["actor_user_id"] == member.user.id
    assert row["target_user_id"] == member.user.id
    assert row["guild_id"] == installed.guild.id
    assert row["target"] == {"type": "plugin", "id": installed.plugin.id}
    assert row["detail"] == {
        "consent_id": consent_id,
        "purpose": "node-1",
        "access": "read",
        "via": "self",
    }


async def test_the_seat_ending_an_answer_names_both_of_them(
    client: AsyncClient, session: AsyncSession, acting_user, role_session, capfd
):
    installed = await _installed(session, acting_user, role_session)
    member = await _member(acting_user, installed)
    consent_id = await _granted(client, installed, member)
    capfd.readouterr()

    response = await client.delete(
        installed.seat.g(
            f"/plugins/{installed.plugin.id}/members/{member.user.id}/consents"
        ),
        headers=installed.seat.headers,
    )
    assert response.status_code == 204, response.text

    (row,) = emitted(capfd, AuditEventType.PLUGIN_CONSENT_REVOKED)
    assert row["actor_user_id"] == installed.seat.user.id
    assert row["target_user_id"] == member.user.id
    assert row["detail"] == {
        "consent_id": consent_id,
        "purpose": "node-1",
        "via": "admin",
    }


async def test_declining_a_request_records_nothing(
    client: AsyncClient, session: AsyncSession, acting_user, role_session, capfd
):
    """Nothing was in force, so nothing ended: the log is what says whether an
    plug-in could act as somebody."""
    installed = await _installed(session, acting_user, role_session)
    member = await _member(acting_user, installed)
    consent_id = await _asked(client, installed, member)
    capfd.readouterr()

    response = await client.delete(
        member.g(f"/plugins/{installed.plugin.id}/consents/{consent_id}"),
        headers=member.headers,
    )

    assert response.status_code == 204, response.text
    assert emitted(capfd, AuditEventType.PLUGIN_CONSENT_REVOKED) == []
