"""Sharing reaching the audit log.

A share is the last gate in front of a piece of content, and it is rebuilt
from a whole list each time it is saved. What is worth writing down is not the
save — it is each grantee whose level actually moved: granted, raised, lowered
or withdrawn. One record per grantee, and a list saved back unchanged is not
one of them.

Driven through the file grants routes, which are the unified path every
tool's sharing runs through.
"""

from __future__ import annotations

from httpx2 import AsyncClient

from app.core.audit_events import AuditEventType
from app.models.platform.guild import CommunityRole
from app.testing import emitted


async def _file(client: AsyncClient, actor, *, grants: list | None = None) -> int:
    payload = {"name": "Shared thing", "initiative_id": actor.initiative.id}
    if grants is not None:
        payload["grants"] = grants
    response = await client.post(
        actor.g("/files/"), headers=actor.headers, json=payload
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _share(client: AsyncClient, actor, file_id: int, grants: list):
    return await client.put(
        actor.g(f"/files/{file_id}/grants"),
        headers=actor.headers,
        json=grants,
    )


class TestSharing:
    async def test_each_level_that_moves_is_recorded_with_both_ends(
        self, client: AsyncClient, acting_user, capfd
    ):
        """Granted, raised and withdrawn each record the grantee once; a list
        saved back unchanged, and a share refused, record nothing."""
        owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
        reader = await acting_user(
            guild_role=CommunityRole.member,
            guild=owner.guild,
            initiative=owner.initiative,
            initiative_role="member",
        )
        file_id = await _file(client, owner, grants=[])
        read = [{"user_id": reader.user.id, "level": "read"}]
        capfd.readouterr()

        refused = await _share(
            client, reader, file_id, [{"user_id": reader.user.id, "level": "write"}]
        )
        assert refused.status_code in (403, 404)
        assert emitted(capfd, AuditEventType.SHARING_GRANT_CHANGED) == []

        for grants in (
            read,
            read,
            [{"user_id": reader.user.id, "level": "write"}],
            [],
        ):
            response = await _share(client, owner, file_id, grants)
            assert response.status_code == 200, response.text

        rows = emitted(capfd, AuditEventType.SHARING_GRANT_CHANGED)
        assert [(row["detail"]["from"], row["detail"]["to"]) for row in rows] == [
            (None, "read"),
            ("read", "write"),
            ("write", None),
        ]
        row = rows[0]
        assert row["actor_user_id"] == owner.user.id
        assert row["target_user_id"] == reader.user.id
        assert row["guild_id"] == owner.guild.id
        assert row["target"] == {"type": "file", "id": file_id}
        assert row["detail"] == {
            "initiative_id": owner.initiative.id,
            "grantee": {"kind": "user", "id": reader.user.id},
            "from": None,
            "to": "read",
        }

    async def test_creating_a_file_records_the_share_it_starts_with(
        self, client: AsyncClient, acting_user, capfd
    ):
        """A new file is shared with the whole initiative by default, and
        that is a grant like any other."""
        owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
        capfd.readouterr()

        file_id = await _file(client, owner)

        (row,) = emitted(capfd, AuditEventType.SHARING_GRANT_CHANGED)
        assert row["actor_user_id"] == owner.user.id
        assert row["target_user_id"] is None
        assert row["target"] == {"type": "file", "id": file_id}
        assert row["detail"] == {
            "initiative_id": owner.initiative.id,
            "grantee": {"kind": "all_members", "id": None},
            "from": None,
            "to": "read",
        }
