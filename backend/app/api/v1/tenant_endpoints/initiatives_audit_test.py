"""Initiative membership and roles reaching the audit log.

A membership is the second gate into a community's content, so every route
that writes one is recorded the same way: whose membership, in which
initiative, on which role, and by which route. The routes differ — a manager
adding somebody, a member walking into an open initiative, a request being
answered, a project handing its owner a row — and ``detail.via`` is what tells
them apart afterwards.

The roles themselves are recorded too: a role is a bundle of permissions, so
changing one changes what every holder may do.
"""

from __future__ import annotations

import json

from httpx2 import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.models.platform.guild import CommunityRole
from app.models.tenant.initiative import (
    DEFAULT_PERMISSION_VALUES,
    InitiativeRoleModel,
)
from app.testing import emitted
from app.testing.factories import create_initiative


def _of(envelopes: list[dict], event: AuditEventType) -> list[dict]:
    """The envelopes of one event type, out of a single read of the stream."""
    return [e for e in envelopes if e["event_type"] == event.value]


async def _role(session: AsyncSession, initiative_id: int, name: str):
    return (
        await session.exec(
            select(InitiativeRoleModel).where(
                InitiativeRoleModel.initiative_id == initiative_id,
                InitiativeRoleModel.name == name,
            )
        )
    ).one()


class TestMembership:
    async def test_a_membership_is_recorded_from_add_to_removal(
        self, client: AsyncClient, session: AsyncSession, acting_user, capfd
    ):
        """Each write records whose membership, on which role and by which
        route; a refused add and a repeat add change no row, so they record
        nothing."""
        manager = await acting_user(guild_role=CommunityRole.member, initiative=True)
        ordinary = await acting_user(
            guild_role=CommunityRole.member,
            guild=manager.guild,
            initiative=manager.initiative,
            initiative_role="member",
        )
        newcomer = await acting_user(
            guild_role=CommunityRole.member, guild=manager.guild
        )
        member_role = await _role(session, manager.initiative.id, "member")
        pm_role = await _role(session, manager.initiative.id, "project_manager")
        members = manager.g(f"/initiatives/{manager.initiative.id}/members")
        payload = {"user_id": newcomer.user.id}
        capfd.readouterr()

        response = await client.post(members, headers=ordinary.headers, json=payload)
        assert response.status_code == 403
        assert emitted(capfd, AuditEventType.INITIATIVE_MEMBER_ADDED) == []

        for _ in range(2):
            response = await client.post(members, headers=manager.headers, json=payload)
            assert response.status_code == 200, response.text
        envelopes = emitted(capfd)
        (row,) = _of(envelopes, AuditEventType.INITIATIVE_MEMBER_ADDED)
        assert _of(envelopes, AuditEventType.INITIATIVE_MEMBER_ROLE_CHANGED) == []
        assert row["actor_user_id"] == manager.user.id
        assert row["target_user_id"] == newcomer.user.id
        assert row["guild_id"] == manager.guild.id
        assert row["target"] == {
            "type": "initiative",
            "id": manager.initiative.id,
        }
        assert row["detail"] == {
            "role_id": member_role.id,
            "role": "member",
            "via": "manager",
        }

        response = await client.patch(
            f"{members}/{newcomer.user.id}",
            headers=manager.headers,
            json={"role_id": pm_role.id},
        )
        assert response.status_code == 200, response.text
        (row,) = emitted(capfd, AuditEventType.INITIATIVE_MEMBER_ROLE_CHANGED)
        assert row["actor_user_id"] == manager.user.id
        assert row["target_user_id"] == newcomer.user.id
        assert row["detail"] == {
            "from_role_id": member_role.id,
            "from": "member",
            "to_role_id": pm_role.id,
            "to": "project_manager",
        }

        response = await client.delete(
            f"{members}/{newcomer.user.id}", headers=manager.headers
        )
        assert response.status_code == 204, response.text
        (row,) = emitted(capfd, AuditEventType.INITIATIVE_MEMBER_REMOVED)
        assert row["actor_user_id"] == manager.user.id
        assert row["target_user_id"] == newcomer.user.id
        assert row["guild_id"] == manager.guild.id
        assert row["detail"] == {"role": "project_manager", "via": "manager"}

    async def test_creating_an_initiative_records_its_creators_membership(
        self, client: AsyncClient, acting_user, capfd
    ):
        """The creator's own row is a membership like any other, and a guild
        admin's lands on the manager role their standing implies."""
        admin = await acting_user(guild_role=CommunityRole.admin)
        capfd.readouterr()

        response = await client.post(
            admin.g("/initiatives/"),
            headers=admin.headers,
            json={"name": "Recorded at birth"},
        )
        assert response.status_code == 201, response.text
        initiative_id = response.json()["id"]

        (row,) = emitted(capfd, AuditEventType.INITIATIVE_MEMBER_ADDED)
        assert row["actor_user_id"] == row["target_user_id"] == admin.user.id
        assert row["target"] == {"type": "initiative", "id": initiative_id}
        assert row["detail"]["via"] == "created"
        assert row["detail"]["role"] == "moderator"

    async def test_walking_into_an_open_initiative_records_the_route(
        self, client: AsyncClient, session: AsyncSession, acting_user, capfd
    ):
        manager = await acting_user(guild_role=CommunityRole.member)
        initiative = await create_initiative(
            session, manager.guild, manager.user, name="Open house", join_policy="open"
        )
        joiner = await acting_user(guild_role=CommunityRole.member, guild=manager.guild)
        capfd.readouterr()

        response = await client.post(
            joiner.g(f"/initiatives/{initiative.id}/join"),
            headers=joiner.headers,
        )
        assert response.status_code == 200, response.text

        (row,) = emitted(capfd, AuditEventType.INITIATIVE_MEMBER_ADDED)
        assert row["actor_user_id"] == row["target_user_id"] == joiner.user.id
        assert row["guild_id"] == manager.guild.id
        assert row["detail"]["via"] == "self_join"
        assert row["detail"]["role"] == "member"

    async def test_an_answered_request_is_recorded_against_whoever_approved_it(
        self, client: AsyncClient, session: AsyncSession, acting_user, capfd
    ):
        """An approval records the membership against the manager who answered;
        a denial records no membership."""
        manager = await acting_user(guild_role=CommunityRole.member)
        initiative = await create_initiative(
            session,
            manager.guild,
            manager.user,
            name="Knock first",
            join_policy="request",
        )
        requests = f"/initiatives/{initiative.id}/join-requests"
        knocks = {}
        for answer in ("deny", "approve"):
            requester = await acting_user(
                guild_role=CommunityRole.member, guild=manager.guild
            )
            knock = await client.post(
                requester.g(requests), headers=requester.headers, json={}
            )
            assert knock.status_code == 201, knock.text
            knocks[answer] = (requester, knock.json()["id"])
        capfd.readouterr()

        for answer, (_requester, request_id) in knocks.items():
            response = await client.post(
                manager.g(f"{requests}/{request_id}/{answer}"),
                headers=manager.headers,
            )
            assert response.status_code == 200, response.text

        (row,) = emitted(capfd, AuditEventType.INITIATIVE_MEMBER_ADDED)
        assert row["actor_user_id"] == manager.user.id
        assert row["target_user_id"] == knocks["approve"][0].user.id
        assert row["detail"]["via"] == "join_request"


class TestRoles:
    async def test_a_role_is_recorded_from_creation_to_deletion(
        self, client: AsyncClient, acting_user, capfd
    ):
        """A display name is a string, so an update's record names the field
        and stops there; a permission is a flag, and both ends of it are
        carried. A patch that moves nothing records nothing."""
        manager = await acting_user(guild_role=CommunityRole.member, initiative=True)
        roles = manager.g(f"/initiatives/{manager.initiative.id}/roles")
        capfd.readouterr()

        response = await client.post(
            roles,
            headers=manager.headers,
            json={
                "name": "leads",
                "display_name": "Leads",
                "is_manager": True,
                "permissions": {"create_files": True},
            },
        )
        assert response.status_code == 201, response.text
        role_id = response.json()["id"]

        (row,) = emitted(capfd, AuditEventType.INITIATIVE_ROLE_CREATED)
        assert row["actor_user_id"] == manager.user.id
        assert row["guild_id"] == manager.guild.id
        assert row["target"] == {"type": "initiative_role", "id": role_id}
        detail = row["detail"]
        assert detail["initiative_id"] == manager.initiative.id
        assert detail["name"] == "leads"
        assert detail["is_manager"] is True
        # The role as written: what the request set, and the member role's
        # answer for every key it left out.
        assert detail["permissions"] == {
            **{key.value: on for key, on in DEFAULT_PERMISSION_VALUES.items()},
            "create_files": True,
        }

        patch = {"display_name": "Team leads", "permissions": {"create_files": False}}
        response = await client.patch(
            f"{roles}/{role_id}", headers=manager.headers, json=patch
        )
        assert response.status_code == 200, response.text
        (row,) = emitted(capfd, AuditEventType.INITIATIVE_ROLE_UPDATED)
        detail = row["detail"]
        assert row["target"] == {"type": "initiative_role", "id": role_id}
        assert detail["changed"] == ["display_name"]
        assert detail["values"] == {}
        assert detail["permissions_changed"] == {
            "create_files": {"from": True, "to": False}
        }
        assert "Team leads" not in json.dumps(row)

        response = await client.patch(
            f"{roles}/{role_id}", headers=manager.headers, json=patch
        )
        assert response.status_code == 200, response.text
        assert emitted(capfd, AuditEventType.INITIATIVE_ROLE_UPDATED) == []

        response = await client.delete(f"{roles}/{role_id}", headers=manager.headers)
        assert response.status_code == 204, response.text
        (row,) = emitted(capfd, AuditEventType.INITIATIVE_ROLE_DELETED)
        assert row["actor_user_id"] == manager.user.id
        assert row["target"] == {"type": "initiative_role", "id": role_id}
        assert row["detail"] == {
            "initiative_id": manager.initiative.id,
            "name": "leads",
        }


class TestLifecycle:
    async def test_trashing_an_initiative_records_how_long_it_is_recoverable(
        self, client: AsyncClient, acting_user, capfd
    ):
        admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
        capfd.readouterr()

        response = await client.delete(
            admin.g(f"/initiatives/{admin.initiative.id}"),
            headers=admin.headers,
        )
        assert response.status_code == 204, response.text

        (row,) = emitted(capfd, AuditEventType.INITIATIVE_DELETED)
        assert row["actor_user_id"] == admin.user.id
        assert row["guild_id"] == admin.guild.id
        assert row["target"] == {
            "type": "initiative",
            "id": admin.initiative.id,
        }
        assert row["detail"]["via"] == "trash"
        assert "retention_days" in row["detail"]
