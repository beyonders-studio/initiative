"""Bulk exports reaching the audit log.

An export is data leaving the deployment in one piece, so both aggregate
routes are recorded: who asked, for what, and which job carries it. Nothing
changed, which is exactly what makes the record worth having — a read of
everything looks like nothing at all in the content tables.

Per-entity exports (one project, the task list) are formatted reads and are
not recorded.
"""

from __future__ import annotations

import pytest
from httpx2 import AsyncClient

from app.core.audit_events import AuditEventType
from app.core.config import settings
from app.models.platform.guild import CommunityRole
from app.testing import emitted


@pytest.fixture(autouse=True)
def _tmp_uploads(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "UPLOADS_DIR", str(tmp_path))


async def test_exporting_an_initiative_records_the_job_that_carries_it(
    client: AsyncClient, acting_user, capfd
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    capfd.readouterr()

    response = await client.get(
        a.g("/exports/initiative"),
        headers=a.headers,
        params={"initiative_id": a.initiative.id},
    )
    assert response.status_code == 202, response.text
    job_id = response.json()["id"]

    (row,) = emitted(capfd, AuditEventType.INITIATIVE_EXPORTED)
    assert row["actor_user_id"] == a.user.id
    assert row["guild_id"] == a.guild.id
    assert row["target"] == {"type": "export_job", "id": job_id}
    assert row["detail"] == {
        "mode": "backup",
        "include_uploads": True,
        "initiative_id": a.initiative.id,
        "job_id": job_id,
    }
    # A read changed nothing; the record says so.
    assert row["is_write"] is False


async def test_exporting_a_guild_records_its_own_event(
    client: AsyncClient, acting_user, capfd
):
    a = await acting_user(guild_role=CommunityRole.superadmin, initiative=True)
    capfd.readouterr()

    response = await client.get(
        a.g("/exports/community"),
        headers=a.headers,
        params={"mode": "backup", "include_uploads": False},
    )
    assert response.status_code == 202, response.text
    job_id = response.json()["id"]

    envelopes = emitted(capfd)
    (row,) = [
        envelope
        for envelope in envelopes
        if envelope["event_type"] == AuditEventType.GUILD_EXPORTED.value
    ]
    assert row["actor_user_id"] == a.user.id
    assert row["guild_id"] == a.guild.id
    assert row["target"] == {"type": "export_job", "id": job_id}
    assert row["detail"] == {
        "mode": "backup",
        "include_uploads": False,
        "job_id": job_id,
    }
    assert [
        envelope
        for envelope in envelopes
        if envelope["event_type"] == AuditEventType.INITIATIVE_EXPORTED.value
    ] == []


async def test_a_refused_guild_export_records_nothing(
    client: AsyncClient, acting_user, capfd
):
    seat = await acting_user(guild_role=CommunityRole.superadmin, initiative=True)
    admin = await acting_user(guild_role=CommunityRole.admin, guild=seat.guild)
    capfd.readouterr()

    response = await client.get(admin.g("/exports/community"), headers=admin.headers)
    assert response.status_code == 403

    assert emitted(capfd, AuditEventType.GUILD_EXPORTED) == []
