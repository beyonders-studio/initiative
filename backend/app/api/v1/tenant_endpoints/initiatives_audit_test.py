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
from app.models.tenant.initiative import InitiativeRoleModel
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
    async def test_adding_a_member_records_the_role_they_landed_on(
        self, client: AsyncClient, session: AsyncSession, acting_user, capfd
    ):
        manager = await acting_user(guild_role=CommunityRole.member, initiative=True)
        newcomer = await acting_user(
            guild_role=CommunityRole.member, guild=manager.guild
        )
        member_role = await _role(session, manager.initiative.id, "member")
        capfd.readouterr()

        response = await client.post(
            manager.g(f"/initiatives/{manager.initiative.id}/members"),
            headers=manager.headers,
            json={"user_id": newcomer.user.id},
        )
        assert response.status_code == 200, response.text

        (row,) = emitted(capfd, AuditEventType.INITIATIVE_MEMBER_ADDED)
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

    async def test_adding_somebody_already_on_that_role_records_nothing(
        self, client: AsyncClient, acting_user, capfd
    ):
        """The second call changes no row, so there is nothing to write down."""
        manager = await acting_user(guild_role=CommunityRole.member, initiative=True)
        newcomer = await acting_user(
            guild_role=CommunityRole.member, guild=manager.guild
        )
        payload = {"user_id": newcomer.user.id}
        capfd.readouterr()

        first = await client.post(
            manager.g(f"/initiatives/{manager.initiative.id}/members"),
            headers=manager.headers,
            json=payload,
        )
        second = await client.post(
            manager.g(f"/initiatives/{manager.initiative.id}/members"),
            headers=manager.headers,
            json=payload,
        )
        assert first.status_code == second.status_code == 200

        envelopes = emitted(capfd)
        assert len(_of(envelopes, AuditEventType.INITIATIVE_MEMBER_ADDED)) == 1
        assert _of(envelopes, AuditEventType.INITIATIVE_MEMBER_ROLE_CHANGED) == []

    async def test_a_refused_add_records_nothing(
        self, client: AsyncClient, acting_user, capfd
    ):
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
        capfd.readouterr()

        response = await client.post(
            ordinary.g(f"/initiatives/{manager.initiative.id}/members"),
            headers=ordinary.headers,
            json={"user_id": newcomer.user.id},
        )
        assert response.status_code == 403

        assert emitted(capfd, AuditEventType.INITIATIVE_MEMBER_ADDED) == []

    async def test_changing_a_members_role_records_both_ends_of_the_move(
        self, client: AsyncClient, session: AsyncSession, acting_user, capfd
    ):
        manager = await acting_user(guild_role=CommunityRole.member, initiative=True)
        member = await acting_user(
            guild_role=CommunityRole.member,
            guild=manager.guild,
            initiative=manager.initiative,
            initiative_role="member",
        )
        member_role = await _role(session, manager.initiative.id, "member")
        pm_role = await _role(session, manager.initiative.id, "project_manager")
        capfd.readouterr()

        response = await client.patch(
            manager.g(f"/initiatives/{manager.initiative.id}/members/{member.user.id}"),
            headers=manager.headers,
            json={"role_id": pm_role.id},
        )
        assert response.status_code == 200, response.text

        (row,) = emitted(capfd, AuditEventType.INITIATIVE_MEMBER_ROLE_CHANGED)
        assert row["actor_user_id"] == manager.user.id
        assert row["target_user_id"] == member.user.id
        assert row["detail"] == {
            "from_role_id": member_role.id,
            "from": "member",
            "to_role_id": pm_role.id,
            "to": "project_manager",
        }

    async def test_removing_a_member_records_the_role_they_held(
        self, client: AsyncClient, acting_user, capfd
    ):
        manager = await acting_user(guild_role=CommunityRole.member, initiative=True)
        member = await acting_user(
            guild_role=CommunityRole.member,
            guild=manager.guild,
            initiative=manager.initiative,
            initiative_role="member",
        )
        capfd.readouterr()

        response = await client.delete(
            manager.g(f"/initiatives/{manager.initiative.id}/members/{member.user.id}"),
            headers=manager.headers,
        )
        assert response.status_code == 204, response.text

        (row,) = emitted(capfd, AuditEventType.INITIATIVE_MEMBER_REMOVED)
        assert row["actor_user_id"] == manager.user.id
        assert row["target_user_id"] == member.user.id
        assert row["guild_id"] == manager.guild.id
        assert row["detail"] == {"role": "member", "via": "manager"}

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

    async def test_an_approved_request_is_recorded_against_whoever_answered_it(
        self, client: AsyncClient, session: AsyncSession, acting_user, capfd
    ):
        manager = await acting_user(guild_role=CommunityRole.member)
        initiative = await create_initiative(
            session,
            manager.guild,
            manager.user,
            name="Knock first",
            join_policy="request",
        )
        requester = await acting_user(
            guild_role=CommunityRole.member, guild=manager.guild
        )

        knock = await client.post(
            requester.g(f"/initiatives/{initiative.id}/join-requests"),
            headers=requester.headers,
            json={},
        )
        assert knock.status_code == 201, knock.text
        request_id = knock.json()["id"]
        capfd.readouterr()

        approved = await client.post(
            manager.g(
                f"/initiatives/{initiative.id}/join-requests/{request_id}/approve"
            ),
            headers=manager.headers,
        )
        assert approved.status_code == 200, approved.text

        (row,) = emitted(capfd, AuditEventType.INITIATIVE_MEMBER_ADDED)
        assert row["actor_user_id"] == manager.user.id
        assert row["target_user_id"] == requester.user.id
        assert row["detail"]["via"] == "join_request"

    async def test_a_denied_request_records_no_membership(
        self, client: AsyncClient, session: AsyncSession, acting_user, capfd
    ):
        manager = await acting_user(guild_role=CommunityRole.member)
        initiative = await create_initiative(
            session, manager.guild, manager.user, name="Denied", join_policy="request"
        )
        requester = await acting_user(
            guild_role=CommunityRole.member, guild=manager.guild
        )

        knock = await client.post(
            requester.g(f"/initiatives/{initiative.id}/join-requests"),
            headers=requester.headers,
            json={},
        )
        assert knock.status_code == 201, knock.text
        capfd.readouterr()

        denied = await client.post(
            manager.g(
                f"/initiatives/{initiative.id}/join-requests/{knock.json()['id']}/deny"
            ),
            headers=manager.headers,
        )
        assert denied.status_code == 200, denied.text

        assert emitted(capfd, AuditEventType.INITIATIVE_MEMBER_ADDED) == []


class TestRoles:
    async def test_creating_a_role_records_what_it_may_do(
        self, client: AsyncClient, acting_user, capfd
    ):
        manager = await acting_user(guild_role=CommunityRole.member, initiative=True)
        capfd.readouterr()

        response = await client.post(
            manager.g(f"/initiatives/{manager.initiative.id}/roles"),
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
        assert detail["permissions"] == {"create_files": True}

    async def test_updating_a_role_records_the_permissions_that_moved(
        self, client: AsyncClient, acting_user, capfd
    ):
        """A display name is a string, so the record names the field and stops
        there; a permission is a flag, and both ends of it are carried."""
        manager = await acting_user(guild_role=CommunityRole.member, initiative=True)
        created = await client.post(
            manager.g(f"/initiatives/{manager.initiative.id}/roles"),
            headers=manager.headers,
            json={
                "name": "leads",
                "display_name": "Leads",
                "permissions": {"create_files": False},
            },
        )
        assert created.status_code == 201, created.text
        role_id = created.json()["id"]
        capfd.readouterr()

        response = await client.patch(
            manager.g(f"/initiatives/{manager.initiative.id}/roles/{role_id}"),
            headers=manager.headers,
            json={
                "display_name": "Team leads",
                "permissions": {"create_files": True},
            },
        )
        assert response.status_code == 200, response.text

        (row,) = emitted(capfd, AuditEventType.INITIATIVE_ROLE_UPDATED)
        detail = row["detail"]
        assert row["target"] == {"type": "initiative_role", "id": role_id}
        assert detail["changed"] == ["display_name"]
        assert detail["values"] == {}
        assert detail["permissions_changed"] == {
            "create_files": {"from": False, "to": True}
        }
        assert "Team leads" not in json.dumps(row)

    async def test_a_role_patch_that_moves_nothing_records_nothing(
        self, client: AsyncClient, acting_user, capfd
    ):
        manager = await acting_user(guild_role=CommunityRole.member, initiative=True)
        created = await client.post(
            manager.g(f"/initiatives/{manager.initiative.id}/roles"),
            headers=manager.headers,
            json={
                "name": "leads",
                "display_name": "Leads",
                "permissions": {"create_files": False},
            },
        )
        assert created.status_code == 201, created.text
        capfd.readouterr()

        response = await client.patch(
            manager.g(
                f"/initiatives/{manager.initiative.id}/roles/{created.json()['id']}"
            ),
            headers=manager.headers,
            json={
                "display_name": "Leads",
                "permissions": {"create_files": False},
            },
        )
        assert response.status_code == 200, response.text

        assert emitted(capfd, AuditEventType.INITIATIVE_ROLE_UPDATED) == []

    async def test_deleting_a_role_records_which_one(
        self, client: AsyncClient, acting_user, capfd
    ):
        manager = await acting_user(guild_role=CommunityRole.member, initiative=True)
        created = await client.post(
            manager.g(f"/initiatives/{manager.initiative.id}/roles"),
            headers=manager.headers,
            json={"name": "leads", "display_name": "Leads"},
        )
        assert created.status_code == 201, created.text
        role_id = created.json()["id"]
        capfd.readouterr()

        response = await client.delete(
            manager.g(f"/initiatives/{manager.initiative.id}/roles/{role_id}"),
            headers=manager.headers,
        )
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
