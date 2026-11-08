"""A dashboard that runs as its initiative.

The shape of most tests here: a project nobody but its owner can open, a
member of the same initiative who cannot see it, and a dashboard counting its
tasks.
"""

from __future__ import annotations

from app.core.messages import DashboardMessages
from app.models.platform.guild import CommunityRole
from app.models.platform.user import UserStatus
from app.testing import create_counter_group, create_project, create_task


COUNT_TASKS = "SELECT count(*) AS n FROM tasks"


def dashboard_body(*statements: str) -> dict:
    """A canvas of one stat per statement, w1, w2, … in order."""
    return {
        "version": 1,
        "widgets": [
            {
                "id": f"w{index + 1}",
                "type": "stat",
                "grid": {"x": 0, "y": index * 2, "w": 4, "h": 2},
                "binding": {"source": "query", "sql": sql},
            }
            for index, sql in enumerate(statements or (COUNT_TASKS,))
        ],
    }


async def dashboards_on(session, initiative) -> None:
    """The tool switch. A role permission gates creating one, and the switch
    gates the tool existing at all."""
    initiative.dashboards_enabled = True
    session.add(initiative)
    await session.commit()
    await session.refresh(initiative)


async def make_dashboard(client, actor, sql: str = COUNT_TASKS) -> int:
    response = await client.post(
        actor.g("/dashboards/"),
        json={
            "name": "Status",
            "initiative_id": actor.initiative.id,
            "definition": dashboard_body(sql),
        },
        headers=actor.headers,
    )
    assert response.status_code in (200, 201), response.text
    return response.json()["id"]


async def widget_rows(client, actor, dashboard_id: int, widget_id: str = "w1"):
    response = await client.get(
        actor.g(f"/dashboards/{dashboard_id}/data"), headers=actor.headers
    )
    assert response.status_code == 200, response.text
    entry = response.json()["widgets"][widget_id]
    assert entry["error"] is None, entry
    return entry["result"]["rows"]


async def two_people(session, acting_user):
    """A community admin who owns a private project with two tasks, and a
    member of the same initiative who cannot open it."""
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await dashboards_on(session, admin.initiative)
    reader = await acting_user(
        guild_role=CommunityRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )
    project = await create_project(session, admin.initiative, admin.user)
    await create_task(session, project)
    await create_task(session, project)
    return admin, reader


async def set_mode(client, actor, dashboard_id: int, mode: str):
    return await client.put(
        actor.g(f"/dashboards/{dashboard_id}/view-mode"),
        json={"mode": mode},
        headers=actor.headers,
    )


async def share_for_writing(client, owner, dashboard_id: int, editor) -> None:
    shared = await client.put(
        owner.g(f"/dashboards/{dashboard_id}/grants"),
        json=[
            {"all_initiative_members": True, "level": "read"},
            {"user_id": editor.user.id, "level": "write"},
        ],
        headers=owner.headers,
    )
    assert shared.status_code in (200, 204), shared.text


async def a_role_that_may(client, admin, *, may: bool) -> str:
    """A custom role, holding the permission or not."""
    created = await client.post(
        admin.g(f"/initiatives/{admin.initiative.id}/roles"),
        json={
            "name": "leads",
            "display_name": "Leads",
            "permissions": {
                "dashboards_enabled": True,
                "dashboards_run_as_initiative": may,
            },
        },
        headers=admin.headers,
    )
    assert created.status_code == 201, created.text
    return "leads"


async def canvas_rows(client, actor, dashboard_id: int):
    response = await client.get(
        actor.g(f"/dashboards/{dashboard_id}/data"), headers=actor.headers
    )
    assert response.status_code == 200, response.text
    return response.json()["widgets"]["w1"]["result"]["rows"]


class TestWhatAReaderSees:
    async def test_everyone_sees_the_whole_initiative(
        self, client, session, acting_user
    ):
        admin, reader = await two_people(session, acting_user)
        dashboard_id = await make_dashboard(client, admin)
        assert await widget_rows(client, reader, dashboard_id) == [[0]]

        response = await set_mode(client, admin, dashboard_id, "initiative")
        assert response.status_code == 200, response.text
        assert response.json()["view_mode"] == "initiative"

        assert await widget_rows(client, reader, dashboard_id) == [[2]]
        assert await canvas_rows(client, reader, dashboard_id) == [[2]]

        back = await set_mode(client, admin, dashboard_id, "individual")
        assert back.status_code == 200
        assert back.json()["view_mode"] == "individual"
        assert await widget_rows(client, reader, dashboard_id) == [[0]]

    async def test_it_does_not_depend_on_who_turned_it_on(
        self, client, session, acting_user
    ):
        """It is the dashboard's access, not a person's: the one who switched
        it on leaving, or being suspended, changes nothing."""
        admin, reader = await two_people(session, acting_user)
        setter = await acting_user(
            guild_role=CommunityRole.member,
            guild=admin.guild,
            initiative=admin.initiative,
            initiative_role="project_manager",
        )
        dashboard_id = await make_dashboard(client, setter)
        assert (
            await set_mode(client, setter, dashboard_id, "initiative")
        ).status_code == 200
        assert await widget_rows(client, reader, dashboard_id) == [[2]]

        setter.user.status = UserStatus.suspended
        session.add(setter.user)
        await session.delete(setter.membership)
        await session.commit()

        assert await widget_rows(client, reader, dashboard_id) == [[2]]

    async def test_it_reaches_tools_the_readers_role_cannot_view(
        self, client, session, acting_user
    ):
        """Full read means every tool the initiative has switched on, not only
        those the reader's own role may open."""
        admin, reader = await two_people(session, acting_user)
        admin.initiative.counter_groups_enabled = True
        session.add(admin.initiative)
        await session.commit()
        await create_counter_group(session, admin.initiative, admin.user)

        dashboard_id = await make_dashboard(
            client, admin, "SELECT count(*) AS n FROM counter_groups"
        )
        assert await widget_rows(client, reader, dashboard_id) == [[0]]
        await set_mode(client, admin, dashboard_id, "initiative")
        assert await widget_rows(client, reader, dashboard_id) == [[1]]

    async def test_it_answers_nowhere_but_that_dashboard(
        self, client, session, acting_user
    ):
        admin, reader = await two_people(session, acting_user)
        dashboard_id = await make_dashboard(client, admin)
        await set_mode(client, admin, dashboard_id, "initiative")

        direct = await client.post(
            reader.g("/query"),
            json={"sql": COUNT_TASKS, "initiative_id": admin.initiative.id},
            headers=reader.headers,
        )
        assert direct.status_code == 200
        assert direct.json()["rows"] == [[0]]
        other = await make_dashboard(client, admin)
        assert await widget_rows(client, reader, other) == [[0]]

    async def test_me_is_still_the_reader(self, client, session, acting_user):
        """Running as the initiative widens what is counted, not who is asking:
        a tile about "me" is about whoever is looking."""
        admin, reader = await two_people(session, acting_user)
        dashboard_id = await make_dashboard(
            client, admin, "SELECT count(*) AS n FROM tasks WHERE created_by = me"
        )
        await set_mode(client, admin, dashboard_id, "initiative")
        assert await widget_rows(client, reader, dashboard_id) == [[0]]


class TestWhoMayChooseIt:
    async def test_a_reader_cannot_turn_it_on(self, client, session, acting_user):
        admin, reader = await two_people(session, acting_user)
        dashboard_id = await make_dashboard(client, admin)
        response = await set_mode(client, reader, dashboard_id, "initiative")
        assert response.status_code in (403, 404)

    async def test_an_editor_needs_the_role_permission(
        self, client, session, acting_user
    ):
        admin, _ = await two_people(session, acting_user)
        role = await a_role_that_may(client, admin, may=False)
        editor = await acting_user(
            guild_role=CommunityRole.member,
            guild=admin.guild,
            initiative=admin.initiative,
            initiative_role=role,
        )
        dashboard_id = await make_dashboard(client, admin)
        await share_for_writing(client, admin, dashboard_id, editor)

        detail = await client.get(
            editor.g(f"/dashboards/{dashboard_id}"), headers=editor.headers
        )
        assert detail.json()["can_run_as_initiative"] is False
        refused = await set_mode(client, editor, dashboard_id, "initiative")
        assert refused.status_code == 403
        assert refused.json()["detail"] == DashboardMessages.VIEW_MODE_NOT_ALLOWED

    async def test_a_role_holding_the_permission_may(
        self, client, session, acting_user
    ):
        admin, reader = await two_people(session, acting_user)
        role = await a_role_that_may(client, admin, may=True)
        editor = await acting_user(
            guild_role=CommunityRole.member,
            guild=admin.guild,
            initiative=admin.initiative,
            initiative_role=role,
        )
        dashboard_id = await make_dashboard(client, admin)
        await share_for_writing(client, admin, dashboard_id, editor)

        response = await set_mode(client, editor, dashboard_id, "initiative")
        assert response.status_code == 200, response.text
        assert response.json()["can_run_as_initiative"] is True
        assert await widget_rows(client, reader, dashboard_id) == [[2]]

    async def test_a_manager_always_may(self, client, session, acting_user):
        admin, _ = await two_people(session, acting_user)
        manager = await acting_user(
            guild_role=CommunityRole.member,
            guild=admin.guild,
            initiative=admin.initiative,
            initiative_role="project_manager",
        )
        created = await client.post(
            manager.g("/dashboards/"),
            json={
                "name": "Status",
                "initiative_id": manager.initiative.id,
                "definition": dashboard_body(),
            },
            headers=manager.headers,
        )
        assert created.status_code == 201, created.text
        assert created.json()["can_run_as_initiative"] is True
        response = await set_mode(client, manager, created.json()["id"], "initiative")
        assert response.status_code == 200, response.text

    async def test_widgets_change_only_with_the_permission(
        self, client, session, acting_user
    ):
        admin, _ = await two_people(session, acting_user)
        role = await a_role_that_may(client, admin, may=False)
        editor = await acting_user(
            guild_role=CommunityRole.member,
            guild=admin.guild,
            initiative=admin.initiative,
            initiative_role=role,
        )
        dashboard_id = await make_dashboard(client, admin)
        await share_for_writing(client, admin, dashboard_id, editor)
        await set_mode(client, admin, dashboard_id, "initiative")

        edit = await client.patch(
            editor.g(f"/dashboards/{dashboard_id}"),
            json={"definition": dashboard_body("SELECT title FROM tasks")},
            headers=editor.headers,
        )
        assert edit.status_code == 403
        assert edit.json()["detail"] == DashboardMessages.VIEW_MODE_EDIT_NOT_ALLOWED

        # A rename is not what the widgets ask, and is allowed.
        rename = await client.patch(
            editor.g(f"/dashboards/{dashboard_id}"),
            json={"name": "Renamed"},
            headers=editor.headers,
        )
        assert rename.status_code == 200, rename.text

        # Anyone who can edit may switch it back, and then edit.
        assert (
            await set_mode(client, editor, dashboard_id, "individual")
        ).status_code == 200
        edit = await client.patch(
            editor.g(f"/dashboards/{dashboard_id}"),
            json={"definition": dashboard_body("SELECT title FROM tasks")},
            headers=editor.headers,
        )
        assert edit.status_code == 200, edit.text
