"""Endpoint tests for comments across every commentable surface."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete as sa_delete
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.messages import CommentMessages
from app.core.tools import Tool
from app.models.platform.guild import CommunityRole
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.testing import (
    create_comment,
    create_resource_grant,
    create_task,
    create_wiki_page,
    guild_of,
)

# One factory per tool, uniform (session, initiative, creator) shape. The
# canonical registry rather than a copy of it: that one is checked against the
# Tool enum at import time, so a new tool cannot reach these parametrized cases
# without a factory behind it.
from app.testing.factories import TOOL_FACTORIES
from app.testing.schema_harness import route_session_to_guild


async def _tool_entity(session, tool: Tool, initiative, creator):
    """A tool entity whose only grant is the creator's owner grant, so each
    test states the sharing it needs explicitly (some factories seed an
    all-members read grant). Toggleable tools are switched on for the
    initiative first."""
    if not getattr(initiative, tool.view_permission, True):
        setattr(initiative, tool.view_permission, True)
        session.add(initiative)
        await session.commit()
    entity = await TOOL_FACTORIES[tool](session, initiative, creator)
    await route_session_to_guild(session, guild_of(initiative))
    await session.exec(
        sa_delete(ResourceGrant).where(
            ResourceGrant.resource_type == tool.value,
            ResourceGrant.resource_id == entity.id,
            ResourceGrant.level != ResourceAccessLevel.owner,
        )
    )
    await session.commit()
    return entity


def _param(tool: Tool) -> str:
    return f"{tool.value}_id"


class TestToolComments:
    """The comment surface every tool carries: posting takes write access on
    the entity, reading its thread takes read access — the same DAC decision
    the entity's own endpoints make."""

    @pytest.mark.parametrize("tool", list(Tool))
    async def test_creator_posts_and_lists(self, client, session, acting_user, tool):
        a = await acting_user(guild_role=CommunityRole.member, initiative=True)
        entity = await _tool_entity(session, tool, a.initiative, a.user)

        created = await client.post(
            a.g("/comments/"),
            headers=a.headers,
            json={"content": "First!", _param(tool): entity.id},
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body[_param(tool)] == entity.id
        if tool is Tool.project:
            assert body["project_id"] == entity.id

        listed = await client.get(
            a.g("/comments/"), headers=a.headers, params={_param(tool): entity.id}
        )
        assert listed.status_code == 200, listed.text
        assert [c["id"] for c in listed.json()["comments"]] == [body["id"]]

    @pytest.mark.parametrize("tool", list(Tool))
    async def test_member_without_grant_is_denied(
        self, client, session, acting_user, tool
    ):
        a = await acting_user(guild_role=CommunityRole.member, initiative=True)
        entity = await _tool_entity(session, tool, a.initiative, a.user)
        b = await acting_user(
            guild_role=CommunityRole.member,
            guild=a.guild,
            initiative=a.initiative,
            initiative_role="member",
        )

        listed = await client.get(
            a.g("/comments/"), headers=b.headers, params={_param(tool): entity.id}
        )
        assert listed.status_code == 403
        assert listed.json()["detail"] == CommentMessages.PERMISSION_DENIED

        posted = await client.post(
            a.g("/comments/"),
            headers=b.headers,
            json={"content": "Hi", _param(tool): entity.id},
        )
        assert posted.status_code == 403

    @pytest.mark.parametrize("tool", list(Tool))
    async def test_any_grant_level_joins_the_discussion(
        self, client, session, acting_user, tool
    ):
        # The rule tasks and files have always had: any grant level on the
        # parent (read included) lets a member read AND post to its thread.
        a = await acting_user(guild_role=CommunityRole.member, initiative=True)
        entity = await _tool_entity(session, tool, a.initiative, a.user)
        b = await acting_user(
            guild_role=CommunityRole.member,
            guild=a.guild,
            initiative=a.initiative,
            initiative_role="member",
        )
        await create_resource_grant(
            session, entity, user=b.user, level=ResourceAccessLevel.read
        )

        listed = await client.get(
            a.g("/comments/"), headers=b.headers, params={_param(tool): entity.id}
        )
        assert listed.status_code == 200

        posted = await client.post(
            a.g("/comments/"),
            headers=b.headers,
            json={"content": "Hi", _param(tool): entity.id},
        )
        assert posted.status_code == 201, posted.text

    @pytest.mark.parametrize("tool", list(Tool))
    async def test_guild_admin_reaches_every_thread(
        self, client, session, acting_user, tool
    ):
        a = await acting_user(guild_role=CommunityRole.member, initiative=True)
        entity = await _tool_entity(session, tool, a.initiative, a.user)
        admin = await acting_user(guild_role=CommunityRole.admin, guild=a.guild)

        listed = await client.get(
            a.g("/comments/"), headers=admin.headers, params={_param(tool): entity.id}
        )
        assert listed.status_code == 200

        posted = await client.post(
            a.g("/comments/"),
            headers=admin.headers,
            json={"content": "Hello", _param(tool): entity.id},
        )
        assert posted.status_code == 201, posted.text

    @pytest.mark.parametrize("tool", list(Tool))
    async def test_a_non_member_finds_nothing(self, client, session, acting_user, tool):
        a = await acting_user(guild_role=CommunityRole.member, initiative=True)
        entity = await _tool_entity(session, tool, a.initiative, a.user)
        outsider = await acting_user(guild_role=CommunityRole.member, guild=a.guild)

        listed = await client.get(
            a.g("/comments/"),
            headers=outsider.headers,
            params={_param(tool): entity.id},
        )
        assert listed.status_code == 404

    @pytest.mark.parametrize("tool", list(Tool))
    async def test_a_disabled_tool_takes_no_comments(
        self, client, session, acting_user, tool
    ):
        a = await acting_user(guild_role=CommunityRole.member, initiative=True)
        entity = await _tool_entity(session, tool, a.initiative, a.user)
        setattr(a.initiative, tool.view_permission, False)
        session.add(a.initiative)
        await session.commit()

        listed = await client.get(
            a.g("/comments/"), headers=a.headers, params={_param(tool): entity.id}
        )
        assert listed.status_code == 403

    async def test_a_reply_must_share_the_parent(self, client, session, acting_user):
        a = await acting_user(guild_role=CommunityRole.member, initiative=True)
        group = await _tool_entity(session, Tool.counter_group, a.initiative, a.user)
        other = await _tool_entity(session, Tool.counter_group, a.initiative, a.user)

        root = await client.post(
            a.g("/comments/"),
            headers=a.headers,
            json={"content": "Root", "counter_group_id": group.id},
        )
        assert root.status_code == 201

        mismatch = await client.post(
            a.g("/comments/"),
            headers=a.headers,
            json={
                "content": "Reply",
                "counter_group_id": other.id,
                "parent_comment_id": root.json()["id"],
            },
        )
        assert mismatch.status_code == 400
        assert mismatch.json()["detail"] == CommentMessages.PARENT_MISMATCH

        reply = await client.post(
            a.g("/comments/"),
            headers=a.headers,
            json={
                "content": "Reply",
                "counter_group_id": group.id,
                "parent_comment_id": root.json()["id"],
            },
        )
        assert reply.status_code == 201

    async def test_exactly_one_target(self, client, session, acting_user):
        a = await acting_user(guild_role=CommunityRole.member, initiative=True)
        project = await _tool_entity(session, Tool.project, a.initiative, a.user)
        group = await _tool_entity(session, Tool.counter_group, a.initiative, a.user)

        two = await client.post(
            a.g("/comments/"),
            headers=a.headers,
            json={
                "content": "Hi",
                "project_id": project.id,
                "counter_group_id": group.id,
            },
        )
        assert two.status_code == 422

        none = await client.post(
            a.g("/comments/"), headers=a.headers, json={"content": "Hi"}
        )
        assert none.status_code == 422

    async def test_a_task_comment_reports_its_project(
        self, client, session, acting_user
    ):
        a = await acting_user(
            guild_role=CommunityRole.member, initiative=True, project=True
        )
        task = await create_task(session, a.project)

        created = await client.post(
            a.g("/comments/"),
            headers=a.headers,
            json={"content": "On the task", "task_id": task.id},
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["task_id"] == task.id
        assert body["project_id"] == a.project.id

    async def test_recent_carries_tool_comments(self, client, session, acting_user):
        a = await acting_user(
            guild_role=CommunityRole.member, initiative=True, project=True
        )
        group = await _tool_entity(session, Tool.counter_group, a.initiative, a.user)
        task = await create_task(session, a.project)

        for payload in (
            {"content": "On the counter group", "counter_group_id": group.id},
            {"content": "On the task", "task_id": task.id},
        ):
            posted = await client.post(
                a.g("/comments/"), headers=a.headers, json=payload
            )
            assert posted.status_code == 201, posted.text

        recent = await client.get(a.g("/comments/recent"), headers=a.headers)
        assert recent.status_code == 200, recent.text
        by_type = {e["entity_type"]: e for e in recent.json()}
        assert by_type["counter_group"]["entity_id"] == group.id
        assert by_type["counter_group"]["entity_name"] == group.name
        assert by_type["counter_group"]["initiative_id"] == a.initiative.id
        assert by_type["task"]["entity_id"] == task.id
        assert by_type["task"]["project_id"] == a.project.id


async def test_a_trashed_resource_reads_back_for_its_deleted_event(
    client, session, acting_user
):
    """A ``deleted`` event is unactionable unless its id still resolves.

    The row survives in the trash until retention, so a read-back may ask for
    it — access checked exactly as for a live one. That is what makes the
    ``deleted`` half of the bus actionable: the id still resolves.
    """
    from datetime import datetime

    from app.models.platform.guild import CommunityRole
    from app.testing import create_task

    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project)
    task_id = task.id

    task.deleted_at = datetime.now(UTC)
    session.add(task)
    await session.commit()

    gone = await client.get(a.g(f"/tasks/{task_id}"), headers=a.headers)
    assert gone.status_code == 404, "a trashed task should be hidden by default"

    found = await client.get(
        a.g(f"/tasks/{task_id}"), params={"include_deleted": "true"}, headers=a.headers
    )
    assert found.status_code == 200, found.text
    assert found.json()["id"] == task_id
    # The event already said it was deleted; what the read-back supplies is the
    # content to act on. Read payloads do not carry deleted_at today.


async def test_guild_calendar_comments_reach_every_member(client, session, acting_user):
    """A guild calendar names no initiative; its everyone-grant reads as the
    whole guild, so any member can join its thread — same rule, wider room."""
    from app.testing import create_guild_calendar

    admin = await acting_user(guild_role=CommunityRole.admin)
    calendar = await create_guild_calendar(session, admin.guild, admin.user)
    member = await acting_user(guild_role=CommunityRole.member, guild=admin.guild)

    posted = await client.post(
        admin.g("/comments/"),
        headers=member.headers,
        json={"content": "Game night?", "calendar_id": calendar.id},
    )
    assert posted.status_code == 201, posted.text

    listed = await client.get(
        admin.g("/comments/"),
        headers=member.headers,
        params={"calendar_id": calendar.id},
    )
    assert listed.status_code == 200
    assert [c["content"] for c in listed.json()["comments"]] == ["Game night?"]


async def test_a_comment_is_its_authors_to_change(
    client, session, acting_user, reading_as
):
    """In the database, neither another member who can edit the task nor the
    community's admin rewrites someone's comment, trashes it on its own or
    writes one in their name; trashing the task takes it along."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    task = await create_task(session, a.project)
    comment = await create_comment(session, a.user, task=task)
    other = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    await create_resource_grant(
        session, a.project, user=other.user, level=ResourceAccessLevel.write
    )
    admin = await acting_user(guild_role=CommunityRole.admin, guild=a.guild)
    params = {"id": comment.id, "task": task.id, "author": a.user.id}
    rewrite = text("UPDATE comments SET content = 'Not what I said' WHERE id = :id")
    trash = text(
        "UPDATE comments SET deleted_at = now(),"
        " deleted_by = NULLIF(current_setting('app.current_user_id'), '')::int"
        " WHERE id = :id"
    )
    forge = text(
        "INSERT INTO comments (task_id, content, created_by, created_at, updated_at)"
        " VALUES (:task, 'Said for you', :author, now(), now()) RETURNING created_by"
    )

    for outsider in (other, admin):
        asking = await reading_as(outsider.user.id, a.guild.id)
        with pytest.raises(DBAPIError, match="only its author changes a comment"):
            await asking.exec(rewrite, params=params)
        await asking.rollback()
        await asking.exec(trash, params=params)
        with pytest.raises(DBAPIError, match="goes to the trash with what it is on"):
            await asking.commit()
        await asking.rollback()
        written = await asking.exec(forge, params=params)
        assert written.scalar_one() == outsider.user.id
        await asking.rollback()
    asking = await reading_as(a.user.id, a.guild.id)
    assert (await asking.exec(rewrite, params=params)).rowcount == 1
    await asking.rollback()

    deleted = await client.delete(a.g(f"/tasks/{task.id}"), headers=other.headers)
    assert deleted.status_code in (200, 204), deleted.text


async def test_a_thread_pages_by_conversation(client, session, acting_user):
    """A page is ``limit`` conversations, newest first, each carrying every
    reply under it however late or deep; the cursor walks the rest with
    nothing skipped or repeated."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    task = await create_task(session, a.project)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    roots = [
        await create_comment(
            session, a.user, task=task, created_at=start + timedelta(minutes=minute)
        )
        for minute in range(5)
    ]
    # Written in the same instant as the newest: the id decides between them.
    twin = await create_comment(
        session, a.user, task=task, created_at=start + timedelta(minutes=4)
    )
    reply = await create_comment(
        session,
        a.user,
        task=task,
        parent_comment_id=roots[0].id,
        created_at=start + timedelta(hours=1),
    )
    nested = await create_comment(
        session,
        a.user,
        task=task,
        parent_comment_id=reply.id,
        created_at=start + timedelta(hours=2),
    )

    pages = []
    params = {"task_id": task.id, "limit": 2}
    while True:
        listed = await client.get(a.g("/comments/"), headers=a.headers, params=params)
        assert listed.status_code == 200, listed.text
        body = listed.json()
        pages.append([c["id"] for c in body["comments"]])
        if body["next_cursor"] is None:
            break
        params["cursor"] = body["next_cursor"]

    assert pages == [
        [roots[4].id, twin.id],
        [roots[2].id, roots[3].id],
        [roots[0].id, roots[1].id, reply.id, nested.id],
    ]


async def test_recent_drops_comments_of_a_disabled_tool(client, session, acting_user):
    """Switching a tool off takes its threads out of the recent feed, exactly
    as it takes the threads themselves away."""
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    group = await _tool_entity(session, Tool.counter_group, a.initiative, a.user)

    posted = await client.post(
        a.g("/comments/"),
        headers=a.headers,
        json={"content": "Counter talk", "counter_group_id": group.id},
    )
    assert posted.status_code == 201, posted.text

    recent = await client.get(a.g("/comments/recent"), headers=a.headers)
    assert any(e["entity_type"] == "counter_group" for e in recent.json())

    setattr(a.initiative, Tool.counter_group.view_permission, False)
    session.add(a.initiative)
    await session.commit()

    recent = await client.get(a.g("/comments/recent"), headers=a.headers)
    assert recent.status_code == 200
    assert not any(e["entity_type"] == "counter_group" for e in recent.json())


def _detail_path(tool: Tool, entity_id: int) -> str:
    """The tool's own detail route — kebab plural, the one spelling every tool
    endpoint is registered under."""
    return f"/{tool.route_segment}/{entity_id}"


class TestToolCommentSwitch:
    """``comments_enabled`` — the Details setting that takes a tool entity's
    thread off its page. Set through the generic
    ``PUT /tools/{tool}/{tool_id}/comments`` route, reported on the entity's own
    read, and honored by every comment surface."""

    @pytest.mark.parametrize("tool", list(Tool))
    async def test_switch_hides_the_thread_and_comes_back(
        self, client, session, acting_user, tool
    ):
        a = await acting_user(guild_role=CommunityRole.member, initiative=True)
        entity = await _tool_entity(session, tool, a.initiative, a.user)

        posted = await client.post(
            a.g("/comments/"),
            headers=a.headers,
            json={"content": "Before", _param(tool): entity.id},
        )
        assert posted.status_code == 201, posted.text

        detail = await client.get(a.g(_detail_path(tool, entity.id)), headers=a.headers)
        assert detail.status_code == 200, detail.text
        assert detail.json()["comments_enabled"] is True

        off = await client.put(
            a.g(f"/tools/{tool.value}/{entity.id}/comments"),
            headers=a.headers,
            json={"comments_enabled": False},
        )
        assert off.status_code == 200, off.text
        assert off.json() == {"comments_enabled": False}

        detail = await client.get(a.g(_detail_path(tool, entity.id)), headers=a.headers)
        assert detail.json()["comments_enabled"] is False

        listed = await client.get(
            a.g("/comments/"), headers=a.headers, params={_param(tool): entity.id}
        )
        assert listed.status_code == 403
        assert listed.json()["detail"] == CommentMessages.COMMENTS_DISABLED

        blocked = await client.post(
            a.g("/comments/"),
            headers=a.headers,
            json={"content": "After", _param(tool): entity.id},
        )
        assert blocked.status_code == 403
        assert blocked.json()["detail"] == CommentMessages.COMMENTS_DISABLED

        recent = await client.get(a.g("/comments/recent"), headers=a.headers)
        assert recent.status_code == 200
        assert not any(
            e["entity_type"] == tool.value and e["entity_id"] == entity.id
            for e in recent.json()
        )

        # Nothing was deleted: turning it back on restores the thread whole.
        on = await client.put(
            a.g(f"/tools/{tool.value}/{entity.id}/comments"),
            headers=a.headers,
            json={"comments_enabled": True},
        )
        assert on.status_code == 200
        listed = await client.get(
            a.g("/comments/"), headers=a.headers, params={_param(tool): entity.id}
        )
        assert listed.status_code == 200
        assert [c["content"] for c in listed.json()["comments"]] == ["Before"]

    async def test_a_wiki_thread_belongs_to_the_page(
        self, client, session, acting_user
    ):
        """A wiki's conversation happens on its pages: two pages of one wiki
        hold two threads, and neither is the wiki's own."""
        a = await acting_user(guild_role=CommunityRole.member, initiative=True)
        wiki = await _tool_entity(session, Tool.wiki, a.initiative, a.user)
        rota = await create_wiki_page(session, wiki, a.user, title="Rota")
        rules = await create_wiki_page(session, wiki, a.user, title="Rules")

        for page, said in ((rota, "Who is on Tuesday?"), (rules, "Rule 3 is stale")):
            posted = await client.post(
                a.g("/comments/"),
                headers=a.headers,
                json={"content": said, "wiki_page_id": page.id},
            )
            assert posted.status_code == 201, posted.text
            assert posted.json()["wiki_page_id"] == page.id

        listed = await client.get(
            a.g("/comments/"), headers=a.headers, params={"wiki_page_id": rota.id}
        )
        assert listed.status_code == 200, listed.text
        assert [c["content"] for c in listed.json()["comments"]] == [
            "Who is on Tuesday?"
        ]

        # The wiki's own thread is a different thread, and empty.
        wiki_thread = await client.get(
            a.g("/comments/"), headers=a.headers, params={"wiki_id": wiki.id}
        )
        assert wiki_thread.status_code == 200
        assert wiki_thread.json()["comments"] == []
        assert wiki_thread.json()["next_cursor"] is None

        # The feed names the page, not the wiki it is filed in.
        recent = await client.get(a.g("/comments/recent"), headers=a.headers)
        pages = [e for e in recent.json() if e["entity_type"] == "wiki_page"]
        assert {e["entity_id"] for e in pages} == {rota.id, rules.id}
        assert {e["entity_name"] for e in pages} == {"Rota", "Rules"}
        assert all(e["initiative_id"] == a.initiative.id for e in pages)

    async def test_a_wiki_switch_governs_its_pages(self, client, session, acting_user):
        """Unlike a task, a page has no switch of its own — the wiki is where
        that choice is made, so it reaches the pages."""
        a = await acting_user(guild_role=CommunityRole.member, initiative=True)
        wiki = await _tool_entity(session, Tool.wiki, a.initiative, a.user)
        page = await create_wiki_page(session, wiki, a.user)

        posted = await client.post(
            a.g("/comments/"),
            headers=a.headers,
            json={"content": "Before", "wiki_page_id": page.id},
        )
        assert posted.status_code == 201, posted.text

        off = await client.put(
            a.g(f"/tools/{Tool.wiki.value}/{wiki.id}/comments"),
            headers=a.headers,
            json={"comments_enabled": False},
        )
        assert off.status_code == 200, off.text

        listed = await client.get(
            a.g("/comments/"), headers=a.headers, params={"wiki_page_id": page.id}
        )
        assert listed.status_code == 403
        assert listed.json()["detail"] == CommentMessages.COMMENTS_DISABLED

        posted = await client.post(
            a.g("/comments/"),
            headers=a.headers,
            json={"content": "After", "wiki_page_id": page.id},
        )
        assert posted.status_code == 403

        recent = await client.get(a.g("/comments/recent"), headers=a.headers)
        assert not [e for e in recent.json() if e["entity_type"] == "wiki_page"]

    async def test_a_page_thread_takes_the_wikis_sharing(
        self, client, session, acting_user
    ):
        """The page is not shared separately: reaching its thread is reaching
        the wiki."""
        a = await acting_user(guild_role=CommunityRole.member, initiative=True)
        wiki = await _tool_entity(session, Tool.wiki, a.initiative, a.user)
        page = await create_wiki_page(session, wiki, a.user)
        b = await acting_user(
            guild_role=CommunityRole.member,
            guild=a.guild,
            initiative=a.initiative,
            initiative_role="member",
        )

        denied = await client.get(
            a.g("/comments/"), headers=b.headers, params={"wiki_page_id": page.id}
        )
        assert denied.status_code == 403
        assert denied.json()["detail"] == CommentMessages.PERMISSION_DENIED

        await create_resource_grant(
            session, wiki, user=b.user, level=ResourceAccessLevel.read
        )

        allowed = await client.get(
            a.g("/comments/"), headers=b.headers, params={"wiki_page_id": page.id}
        )
        assert allowed.status_code == 200, allowed.text

        posted = await client.post(
            a.g("/comments/"),
            headers=b.headers,
            json={"content": "Joining in", "wiki_page_id": page.id},
        )
        assert posted.status_code == 201, posted.text

    async def test_a_project_switch_leaves_task_threads_alone(
        self, client, session, acting_user
    ):
        """Tasks are their own flow: a project with comments off still has task
        threads."""
        a = await acting_user(guild_role=CommunityRole.member, initiative=True)
        project = await _tool_entity(session, Tool.project, a.initiative, a.user)
        task = await create_task(session, project)

        off = await client.put(
            a.g(f"/tools/{Tool.project.value}/{project.id}/comments"),
            headers=a.headers,
            json={"comments_enabled": False},
        )
        assert off.status_code == 200, off.text

        posted = await client.post(
            a.g("/comments/"),
            headers=a.headers,
            json={"content": "Still talking", "task_id": task.id},
        )
        assert posted.status_code == 201, posted.text

        listed = await client.get(
            a.g("/comments/"), headers=a.headers, params={"task_id": task.id}
        )
        assert listed.status_code == 200
        assert [c["content"] for c in listed.json()["comments"]] == ["Still talking"]

        recent = await client.get(a.g("/comments/recent"), headers=a.headers)
        assert any(e["entity_type"] == "task" for e in recent.json())

    @pytest.mark.parametrize("tool", list(Tool))
    async def test_read_access_cannot_flip_the_switch(
        self, client, session, acting_user, tool
    ):
        a = await acting_user(guild_role=CommunityRole.member, initiative=True)
        entity = await _tool_entity(session, tool, a.initiative, a.user)
        b = await acting_user(
            guild_role=CommunityRole.member,
            guild=a.guild,
            initiative=a.initiative,
            initiative_role="member",
        )
        await create_resource_grant(
            session, entity, user=b.user, level=ResourceAccessLevel.read
        )

        denied = await client.put(
            a.g(f"/tools/{tool.value}/{entity.id}/comments"),
            headers=b.headers,
            json={"comments_enabled": False},
        )
        assert denied.status_code == 403, denied.text


class TestEditingAComment:
    """The edit reply is the client's read-back: it has to carry the whole
    comment, author and reactions included, on every surface."""

    @pytest.mark.parametrize("tool", list(Tool))
    async def test_author_edits_and_gets_the_whole_comment_back(
        self, client, session, acting_user, tool
    ):
        a = await acting_user(guild_role=CommunityRole.member, initiative=True)
        entity = await _tool_entity(session, tool, a.initiative, a.user)

        posted = await client.post(
            a.g("/comments/"),
            headers=a.headers,
            json={"content": "Before", _param(tool): entity.id},
        )
        assert posted.status_code == 201, posted.text
        comment_id = posted.json()["id"]

        edited = await client.patch(
            a.g(f"/comments/{comment_id}"),
            headers=a.headers,
            json={"content": "After"},
        )
        assert edited.status_code == 200, edited.text
        body = edited.json()
        assert body["content"] == "After"
        assert body["author"] is not None
        assert body["author"]["id"] == a.user.id
        assert body[_param(tool)] == entity.id
        if tool is Tool.project:
            assert body["project_id"] == entity.id

        listed = await client.get(
            a.g("/comments/"), headers=a.headers, params={_param(tool): entity.id}
        )
        assert [c["content"] for c in listed.json()["comments"]] == ["After"]

    async def test_an_edit_keeps_the_reactions(self, client, session, acting_user):
        a = await acting_user(guild_role=CommunityRole.member, initiative=True)
        project = await _tool_entity(session, Tool.project, a.initiative, a.user)
        task = await create_task(session, project)

        posted = await client.post(
            a.g("/comments/"),
            headers=a.headers,
            json={"content": "Before", "task_id": task.id},
        )
        assert posted.status_code == 201, posted.text
        comment_id = posted.json()["id"]

        reacted = await client.put(
            a.g(f"/reactions/comment/{comment_id}"),
            headers=a.headers,
            json={"emoji": "🎉"},
        )
        assert reacted.status_code == 200, reacted.text

        edited = await client.patch(
            a.g(f"/comments/{comment_id}"),
            headers=a.headers,
            json={"content": "After"},
        )
        assert edited.status_code == 200, edited.text
        body = edited.json()
        assert body["author"] is not None
        # A task comment reports its task's project, same as the list reply.
        assert body["project_id"] == project.id
        assert [(g["emoji"], g["count"]) for g in body["reactions"]] == [("🎉", 1)]

    async def test_only_the_author_may_edit(self, client, session, acting_user):
        a = await acting_user(guild_role=CommunityRole.member, initiative=True)
        project = await _tool_entity(session, Tool.project, a.initiative, a.user)
        b = await acting_user(
            guild_role=CommunityRole.member,
            guild=a.guild,
            initiative=a.initiative,
            initiative_role="member",
        )
        await create_resource_grant(
            session, project, user=b.user, level=ResourceAccessLevel.write
        )

        posted = await client.post(
            a.g("/comments/"),
            headers=a.headers,
            json={"content": "Mine", "project_id": project.id},
        )
        assert posted.status_code == 201, posted.text

        denied = await client.patch(
            a.g(f"/comments/{posted.json()['id']}"),
            headers=b.headers,
            json={"content": "Yours"},
        )
        assert denied.status_code == 403
        assert denied.json()["detail"] == CommentMessages.AUTHOR_ONLY_EDIT


class TestRemovingAComment:
    """Who may delete a comment, and the thread saying so up front.

    The thread reports ``can_remove`` per comment from the same rule the delete
    route applies — its author, and nobody else — so the client offers Delete
    exactly where it would go through. Taking somebody else's words down is
    moderation (``moderation_acts``): the thread says who may, in
    ``can_moderate``, and a manager of the initiative is not among them.
    """

    @pytest.fixture
    async def thread(self, session, acting_user):
        owner = await acting_user(
            guild_role=CommunityRole.admin, initiative=True, project=True
        )
        joined = {
            name: await acting_user(
                guild_role=CommunityRole.member,
                guild=owner.guild,
                initiative=owner.initiative,
                initiative_role=role,
            )
            for name, role in (
                ("author", "member"),
                ("writer", "member"),
                ("manager", "project_manager"),
                ("moderator", "moderator"),
            )
        }
        await create_resource_grant(
            session,
            owner.project,
            all_initiative_members=True,
            level=ResourceAccessLevel.write,
        )
        task = await create_task(session, owner.project)
        comment = await create_comment(session, joined["author"].user, task=task)
        return {"admin": owner, **joined, "task": task, "comment": comment}

    @pytest.mark.parametrize(
        "reader,removes,moderates",
        [
            pytest.param("author", True, False, id="its-author"),
            pytest.param("admin", False, True, id="a-community-admin"),
            pytest.param("moderator", False, True, id="full-access-in-the-initiative"),
            pytest.param("manager", False, False, id="a-manager-of-the-initiative"),
            pytest.param("writer", False, False, id="somebody-who-can-only-write"),
        ],
    )
    async def test_the_thread_says_who_may_delete_and_the_route_agrees(
        self, client, thread, reader, removes, moderates
    ):
        actor = thread[reader]
        listed = await client.get(
            actor.g("/comments/"),
            headers=actor.headers,
            params={"task_id": thread["task"].id},
        )
        assert listed.status_code == 200, listed.text
        (shown,) = listed.json()["comments"]
        assert shown["can_remove"] is removes
        assert listed.json()["can_moderate"] is moderates

        deleted = await client.delete(
            actor.g(f"/comments/{thread['comment'].id}"), headers=actor.headers
        )
        if removes:
            assert deleted.status_code == 204, deleted.text
        else:
            assert deleted.status_code == 403, deleted.text
            assert deleted.json()["detail"] == CommentMessages.AUTHOR_ONLY_DELETE
