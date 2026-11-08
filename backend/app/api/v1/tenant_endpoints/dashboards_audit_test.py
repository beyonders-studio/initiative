"""A dashboard's view mode reaching the audit log.

Running a dashboard as its initiative shows everybody who can open it what the
initiative holds, so turning it on or off is a sharing change, recorded as one
against the dashboard.
"""

from __future__ import annotations

from httpx2 import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.models.platform.guild import CommunityRole
from app.testing import emitted

COUNT_TASKS = "SELECT count(*) AS n FROM tasks"


async def _dashboards_on(session: AsyncSession, initiative) -> None:
    initiative.dashboards_enabled = True
    session.add(initiative)
    await session.commit()
    await session.refresh(initiative)


async def _dashboard(client: AsyncClient, actor) -> int:
    response = await client.post(
        actor.g("/dashboards/"),
        headers=actor.headers,
        json={
            "name": "Status",
            "initiative_id": actor.initiative.id,
            "definition": {
                "version": 1,
                "widgets": [
                    {
                        "id": "w1",
                        "type": "stat",
                        "grid": {"x": 0, "y": 0, "w": 4, "h": 2},
                        "binding": {"source": "query", "sql": COUNT_TASKS},
                    }
                ],
            },
        },
    )
    assert response.status_code in (200, 201), response.text
    return response.json()["id"]


def _view_mode_rows(capfd):
    """Only the view-mode changes — a creation's own default share is an
    ordinary grant and is recorded separately."""
    rows = emitted(capfd, AuditEventType.SHARING_GRANT_CHANGED)
    return [row for row in rows if "view_mode" in row["detail"]]


async def _set(client: AsyncClient, actor, dashboard_id: int, mode: str):
    response = await client.put(
        actor.g(f"/dashboards/{dashboard_id}/view-mode"),
        headers=actor.headers,
        json={"mode": mode},
    )
    assert response.status_code == 200, response.text


async def test_running_as_the_initiative_is_recorded_as_a_sharing_change(
    client: AsyncClient, session: AsyncSession, acting_user, capfd
):
    author = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _dashboards_on(session, author.initiative)
    dashboard_id = await _dashboard(client, author)
    capfd.readouterr()

    await _set(client, author, dashboard_id, "initiative")

    (row,) = _view_mode_rows(capfd)
    assert row["actor_user_id"] == author.user.id
    assert row["guild_id"] == author.guild.id
    assert row["target"] == {"type": "dashboard", "id": dashboard_id}
    assert row["detail"] == {
        "initiative_id": author.initiative.id,
        "view_mode": {"from": "individual", "to": "initiative"},
    }


async def test_setting_the_same_mode_again_records_nothing_further(
    client: AsyncClient, session: AsyncSession, acting_user, capfd
):
    author = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _dashboards_on(session, author.initiative)
    dashboard_id = await _dashboard(client, author)
    capfd.readouterr()

    await _set(client, author, dashboard_id, "initiative")
    await _set(client, author, dashboard_id, "initiative")
    await _set(client, author, dashboard_id, "individual")

    rows = _view_mode_rows(capfd)
    assert [r["detail"]["view_mode"]["to"] for r in rows] == [
        "initiative",
        "individual",
    ]
