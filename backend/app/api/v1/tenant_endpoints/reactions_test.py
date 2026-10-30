"""Endpoint tests for emoji reactions.

The gate under test is the one the design turns on: a reaction is reached
through the thing it is on. Reacting is answering rather than editing, so
reaching the target is the whole gate — read access shows the chips AND adds
one. What stops a reaction is a switch: a thread turned off, or a notice not
taking them.
"""

import pytest
from sqlalchemy import delete as sa_delete

from app.core.messages import ReactionMessages
from app.core.tools import Tool
from app.models.platform.guild import CommunityRole
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.schemas.tenant.reaction import SUGGESTED_EMOJI
from app.services.tenant.reactions import MAX_REACTIONS_PER_USER
from app.testing import (
    create_comment,
    create_reaction,
    create_post,
    create_project,
    create_resource_grant,
    create_task,
    guild_of,
    drain_notices,
)
from app.testing.schema_harness import route_session_to_guild

THUMBS = "\N{THUMBS UP SIGN}"
PARTY = "\N{PARTY POPPER}"


async def _posts_enabled(session, initiative) -> None:
    """Posts are off on a fresh initiative, so a notice test turns them on."""
    initiative.posts_enabled = True
    session.add(initiative)
    await session.commit()
    await session.refresh(initiative)


async def _strip_grants(session, tool: Tool, entity):
    """Leave only the creator's owner grant, so each test states the sharing
    it needs."""
    await route_session_to_guild(session, guild_of(entity))
    await session.exec(
        sa_delete(ResourceGrant).where(
            ResourceGrant.resource_type == tool.value,
            ResourceGrant.resource_id == entity.id,
            ResourceGrant.level != ResourceAccessLevel.owner,
        )
    )
    await session.commit()


async def _comment_on_task(client, actor, task_id: int, content: str = "Hello") -> int:
    created = await client.post(
        actor.g("/comments/"),
        headers=actor.headers,
        json={"content": content, "task_id": task_id},
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


class TestReactionToggle:
    async def test_put_adds_then_takes_back(self, client, session, acting_user):
        a = await acting_user(
            guild_role=CommunityRole.member, initiative=True, project=True
        )
        task = await create_task(session, a.project)
        comment_id = await _comment_on_task(client, a, task.id)

        added = await client.put(
            a.g(f"/reactions/comment/{comment_id}"),
            headers=a.headers,
            json={"emoji": THUMBS},
        )
        assert added.status_code == 200, added.text
        body = added.json()
        assert body["target_type"] == "comment"
        assert body["target_id"] == comment_id
        assert body["groups"] == [
            {
                "emoji": THUMBS,
                "count": 1,
                "reacted": True,
                "users": [body["groups"][0]["users"][0]],
            }
        ]
        assert body["groups"][0]["users"][0]["id"] == a.user.id

        removed = await client.put(
            a.g(f"/reactions/comment/{comment_id}"),
            headers=a.headers,
            json={"emoji": THUMBS},
        )
        assert removed.status_code == 200, removed.text
        assert removed.json()["groups"] == []

    async def test_counts_aggregate_across_people(self, client, session, acting_user):
        a = await acting_user(
            guild_role=CommunityRole.member, initiative=True, project=True
        )
        b = await acting_user(
            guild_role=CommunityRole.member,
            guild=a.guild,
            initiative=a.initiative,
            initiative_role="member",
        )
        await create_resource_grant(
            session, a.project, user=b.user, level=ResourceAccessLevel.write
        )
        task = await create_task(session, a.project)
        comment_id = await _comment_on_task(client, a, task.id)

        for actor in (a, b):
            resp = await client.put(
                a.g(f"/reactions/comment/{comment_id}"),
                headers=actor.headers,
                json={"emoji": THUMBS},
            )
            assert resp.status_code == 200, resp.text

        listed = await client.get(
            a.g("/comments/"), headers=a.headers, params={"task_id": task.id}
        )
        assert listed.status_code == 200
        [comment] = listed.json()["comments"]
        group = comment["reactions"][0]
        assert group["count"] == 2
        # "reacted" is answered for the caller, not for whoever reacted last.
        assert group["reacted"] is True
        assert {u["id"] for u in group["users"]} == {a.user.id, b.user.id}

    async def test_groups_hold_first_reacted_order(self, client, session, acting_user):
        a = await acting_user(
            guild_role=CommunityRole.member, initiative=True, project=True
        )
        task = await create_task(session, a.project)
        comment_id = await _comment_on_task(client, a, task.id)

        for emoji in (PARTY, THUMBS):
            seen = await client.put(
                a.g(f"/reactions/comment/{comment_id}"),
                headers=a.headers,
                json={"emoji": emoji},
            )
        assert [g["emoji"] for g in seen.json()["groups"]] == [PARTY, THUMBS]

    async def test_comment_read_carries_its_reactions(
        self, client, session, acting_user
    ):
        a = await acting_user(
            guild_role=CommunityRole.member, initiative=True, project=True
        )
        task = await create_task(session, a.project)
        comment_id = await _comment_on_task(client, a, task.id)
        await client.put(
            a.g(f"/reactions/comment/{comment_id}"),
            headers=a.headers,
            json={"emoji": THUMBS},
        )

        listed = await client.get(
            a.g("/comments/"), headers=a.headers, params={"task_id": task.id}
        )
        assert listed.status_code == 200
        [comment] = listed.json()["comments"]
        assert [g["emoji"] for g in comment["reactions"]] == [THUMBS]
        assert comment["reactions"][0]["reacted"] is True

    async def test_editing_a_comment_keeps_its_reactions(
        self, client, session, acting_user
    ):
        """The edit reply is what the client writes back into its cache, so a
        comment that comes back without its reactions blanks the chips."""
        a = await acting_user(
            guild_role=CommunityRole.member, initiative=True, project=True
        )
        task = await create_task(session, a.project)
        comment_id = await _comment_on_task(client, a, task.id)
        await client.put(
            a.g(f"/reactions/comment/{comment_id}"),
            headers=a.headers,
            json={"emoji": THUMBS},
        )

        edited = await client.patch(
            a.g(f"/comments/{comment_id}"),
            headers=a.headers,
            json={"content": "Hello, again"},
        )
        assert edited.status_code == 200, edited.text
        assert [g["emoji"] for g in edited.json()["reactions"]] == [THUMBS]

    async def test_the_recent_feed_carries_reactions(
        self, client, session, acting_user
    ):
        """The guild's activity feed is where reactions are most legible — a
        comment that drew six of them should not read like a quiet one."""
        a = await acting_user(
            guild_role=CommunityRole.member, initiative=True, project=True
        )
        task = await create_task(session, a.project)
        comment_id = await _comment_on_task(client, a, task.id)
        await client.put(
            a.g(f"/reactions/comment/{comment_id}"),
            headers=a.headers,
            json={"emoji": THUMBS},
        )

        feed = await client.get(a.g("/comments/recent"), headers=a.headers)
        assert feed.status_code == 200, feed.text
        [entry] = [e for e in feed.json() if e["comment_id"] == comment_id]
        assert [g["emoji"] for g in entry["reactions"]] == [THUMBS]
        assert entry["reactions"][0]["reacted"] is True

    async def test_a_duplicate_add_converges_instead_of_erroring(
        self, client, session, acting_user
    ):
        """A reaction button invites the double tap, and two requests can both
        find the reaction missing. The row already being there must read as the
        state converging, not as a duplicate-key crash."""
        from app.core.reactions import ReactionTarget
        from app.models.tenant.reaction import Reaction
        from sqlmodel import select

        a = await acting_user(
            guild_role=CommunityRole.member, initiative=True, project=True
        )
        task = await create_task(session, a.project)
        comment_id = await _comment_on_task(client, a, task.id)

        # Stand in for the request that got there first: the row exists, but
        # this call's own DELETE has already reported nothing to take back.
        await route_session_to_guild(session, a.guild.id)
        session.add(
            Reaction(
                target_type=ReactionTarget.comment.value,
                target_id=comment_id,
                emoji=THUMBS,
                created_by=a.user.id,
            )
        )
        await session.commit()

        again = await client.put(
            a.g(f"/reactions/comment/{comment_id}"),
            headers=a.headers,
            json={"emoji": THUMBS},
        )
        # Toggling one that is already there takes it back — no 500, and no
        # second row.
        assert again.status_code == 200, again.text
        assert again.json()["groups"] == []

        await route_session_to_guild(session, a.guild.id)
        rows = (
            await session.exec(select(Reaction).where(Reaction.target_id == comment_id))
        ).all()
        assert rows == []

    async def test_the_ceiling_survives_a_row_that_slipped_in(
        self, client, session, acting_user
    ):
        """The cap is counted after the insert rather than before, so a row
        that landed concurrently is still counted — and going over rolls the
        whole request back rather than leaving the extra behind."""
        from app.core.reactions import ReactionTarget
        from app.models.tenant.reaction import Reaction
        from sqlmodel import select

        a = await acting_user(
            guild_role=CommunityRole.member, initiative=True, project=True
        )
        task = await create_task(session, a.project)
        comment_id = await _comment_on_task(client, a, task.id)

        await route_session_to_guild(session, a.guild.id)
        # Fill the allowance behind the request's back. Keycap digits and the
        # regional indicators are the two cheap runs of distinct valid emoji.
        filler = [f"{n}\ufe0f\u20e3" for n in range(10)] + [
            chr(0x1F1E6 + n) for n in range(MAX_REACTIONS_PER_USER - 10)
        ]
        for emoji in filler:
            session.add(
                Reaction(
                    target_type=ReactionTarget.comment.value,
                    target_id=comment_id,
                    emoji=emoji,
                    created_by=a.user.id,
                )
            )
        await session.commit()

        refused = await client.put(
            a.g(f"/reactions/comment/{comment_id}"),
            headers=a.headers,
            json={"emoji": PARTY},
        )
        assert refused.status_code == 400
        assert refused.json()["detail"] == ReactionMessages.TOO_MANY

        await route_session_to_guild(session, a.guild.id)
        held = (
            await session.exec(select(Reaction).where(Reaction.target_id == comment_id))
        ).all()
        assert len(held) == MAX_REACTIONS_PER_USER, (
            "the refused row was not rolled back"
        )

    async def test_rejects_text_in_the_emoji_field(self, client, session, acting_user):
        a = await acting_user(
            guild_role=CommunityRole.member, initiative=True, project=True
        )
        task = await create_task(session, a.project)
        comment_id = await _comment_on_task(client, a, task.id)

        refused = await client.put(
            a.g(f"/reactions/comment/{comment_id}"),
            headers=a.headers,
            json={"emoji": "<b>gotcha</b>"},
        )
        assert refused.status_code == 422

    async def test_caps_one_person_per_target(self, client, session, acting_user):
        a = await acting_user(
            guild_role=CommunityRole.member, initiative=True, project=True
        )
        task = await create_task(session, a.project)
        comment_id = await _comment_on_task(client, a, task.id)

        # Distinct emoji: the keycap digits are cheap to generate and valid.
        emojis = [f"{n}️⃣" for n in range(10)] + [
            "\N{THUMBS UP SIGN}",
            "\N{THUMBS DOWN SIGN}",
            "\N{PARTY POPPER}",
            "\N{EYES}",
            "\N{ROCKET}",
            "\N{CONFUSED FACE}",
            "\N{FIRE}",
            "\N{SPARKLES}",
            "\N{CLAPPING HANDS SIGN}",
            "\N{RAISED HAND}",
            "\N{SNOWFLAKE}",
        ]
        assert len(emojis) > MAX_REACTIONS_PER_USER
        statuses = []
        for emoji in emojis:
            resp = await client.put(
                a.g(f"/reactions/comment/{comment_id}"),
                headers=a.headers,
                json={"emoji": emoji},
            )
            statuses.append(resp.status_code)
        assert statuses[MAX_REACTIONS_PER_USER - 1] == 200
        assert statuses[MAX_REACTIONS_PER_USER] == 400

    async def test_suggested_set_is_served(self, client, acting_user):
        a = await acting_user(guild_role=CommunityRole.member)
        resp = await client.get(a.g("/reactions/suggested"), headers=a.headers)
        assert resp.status_code == 200
        assert resp.json() == list(SUGGESTED_EMOJI)


class TestReactionAccess:
    async def test_a_share_reaches_the_chips_and_the_toggle(
        self, client, session, acting_user
    ):
        """A grant on the parent carries both halves, exactly as it does for
        the thread itself: seeing the reactions and adding one are the same
        decision the comment box already answers."""
        a = await acting_user(
            guild_role=CommunityRole.member, initiative=True, project=True
        )
        await _strip_grants(session, Tool.project, a.project)
        b = await acting_user(
            guild_role=CommunityRole.member,
            guild=a.guild,
            initiative=a.initiative,
            initiative_role="member",
        )
        await create_resource_grant(
            session, a.project, user=b.user, level=ResourceAccessLevel.read
        )
        task = await create_task(session, a.project)
        comment_id = await _comment_on_task(client, a, task.id)
        await client.put(
            a.g(f"/reactions/comment/{comment_id}"),
            headers=a.headers,
            json={"emoji": THUMBS},
        )

        listed = await client.get(
            a.g("/comments/"), headers=b.headers, params={"task_id": task.id}
        )
        assert listed.status_code == 200
        [comment] = listed.json()["comments"]
        assert comment["reactions"][0]["count"] == 1
        # "reacted" answers for the caller, who has not reacted here.
        assert comment["reactions"][0]["reacted"] is False

        added = await client.put(
            a.g(f"/reactions/comment/{comment_id}"),
            headers=b.headers,
            json={"emoji": PARTY},
        )
        assert added.status_code == 200, added.text
        assert {g["emoji"] for g in added.json()["groups"]} == {THUMBS, PARTY}

    async def test_unshared_member_reaches_nothing(self, client, session, acting_user):
        a = await acting_user(
            guild_role=CommunityRole.member, initiative=True, project=True
        )
        await _strip_grants(session, Tool.project, a.project)
        b = await acting_user(
            guild_role=CommunityRole.member,
            guild=a.guild,
            initiative=a.initiative,
            initiative_role="member",
        )
        task = await create_task(session, a.project)
        comment_id = await _comment_on_task(client, a, task.id)

        refused = await client.put(
            a.g(f"/reactions/comment/{comment_id}"),
            headers=b.headers,
            json={"emoji": THUMBS},
        )
        assert refused.status_code == 403

    async def test_outsider_to_the_initiative_gets_404(
        self, client, session, acting_user
    ):
        a = await acting_user(
            guild_role=CommunityRole.member, initiative=True, project=True
        )
        task = await create_task(session, a.project)
        comment_id = await _comment_on_task(client, a, task.id)
        # Same guild, different initiative: RLS hides the comment entirely.
        b = await acting_user(
            guild_role=CommunityRole.member, guild=a.guild, initiative=True
        )

        refused = await client.put(
            a.g(f"/reactions/comment/{comment_id}"),
            headers=b.headers,
            json={"emoji": THUMBS},
        )
        assert refused.status_code == 404
        assert refused.json()["detail"] == ReactionMessages.TARGET_NOT_FOUND

    async def test_other_guild_cannot_reach_the_target(
        self, client, session, acting_user
    ):
        a = await acting_user(
            guild_role=CommunityRole.member, initiative=True, project=True
        )
        task = await create_task(session, a.project)
        comment_id = await _comment_on_task(client, a, task.id)
        b = await acting_user(guild_role=CommunityRole.member)

        # Addressed at the outsider's OWN guild: the id belongs to another
        # schema entirely, so there is nothing there to react to.
        refused = await client.put(
            b.g(f"/reactions/comment/{comment_id}"),
            headers=b.headers,
            json={"emoji": THUMBS},
        )
        assert refused.status_code == 404

    async def test_comment_with_the_switch_off_refuses_reactions(
        self, client, session, acting_user
    ):
        """A project with comments off has no thread — reactions on it go too."""
        a = await acting_user(guild_role=CommunityRole.member, initiative=True)
        project = await create_project(session, a.initiative, a.user)
        created = await client.post(
            a.g("/comments/"),
            headers=a.headers,
            json={"content": "before", "project_id": project.id},
        )
        assert created.status_code == 201
        comment_id = created.json()["id"]

        await route_session_to_guild(session, guild_of(project))
        project.comments_enabled = False
        session.add(project)
        await session.commit()

        refused = await client.put(
            a.g(f"/reactions/comment/{comment_id}"),
            headers=a.headers,
            json={"emoji": THUMBS},
        )
        assert refused.status_code == 403

    async def test_a_notice_taking_no_reactions_refuses_them(
        self, client, session, acting_user
    ):
        """The post's own switch, the counterpart to a thread's."""
        a = await acting_user(guild_role=CommunityRole.member, initiative=True)
        await _posts_enabled(session, a.initiative)
        post = await create_post(session, a.initiative, a.user)

        allowed = await client.put(
            a.g(f"/reactions/post/{post.id}"),
            headers=a.headers,
            json={"emoji": THUMBS},
        )
        assert allowed.status_code == 200, allowed.text

        off = await client.put(
            a.g(f"/posts/{post.id}/reactions"),
            headers=a.headers,
            json={"reactions_enabled": False},
        )
        assert off.status_code == 200, off.text
        assert off.json()["reactions_enabled"] is False

        refused = await client.put(
            a.g(f"/reactions/post/{post.id}"),
            headers=a.headers,
            json={"emoji": PARTY},
        )
        assert refused.status_code == 409
        assert refused.json()["detail"] == ReactionMessages.DISABLED

    async def test_the_switch_hides_the_reactions_already_there(
        self, client, session, acting_user
    ):
        """Turning it off keeps the rows and stops serving them, the way a
        thread turned off keeps its comments."""
        a = await acting_user(guild_role=CommunityRole.member, initiative=True)
        await _posts_enabled(session, a.initiative)
        post = await create_post(session, a.initiative, a.user)
        await client.put(
            a.g(f"/reactions/post/{post.id}"),
            headers=a.headers,
            json={"emoji": THUMBS},
        )

        await client.put(
            a.g(f"/posts/{post.id}/reactions"),
            headers=a.headers,
            json={"reactions_enabled": False},
        )
        read = await client.get(a.g(f"/posts/{post.id}"), headers=a.headers)
        assert read.status_code == 200, read.text
        assert read.json()["reactions_enabled"] is False
        assert read.json()["reactions"] == []

        back_on = await client.put(
            a.g(f"/posts/{post.id}/reactions"),
            headers=a.headers,
            json={"reactions_enabled": True},
        )
        assert back_on.status_code == 200
        again = await client.get(a.g(f"/posts/{post.id}"), headers=a.headers)
        assert [g["emoji"] for g in again.json()["reactions"]] == [THUMBS]

    async def test_a_reader_cannot_flip_the_switch(self, client, session, acting_user):
        """Turning reactions off is editing the notice, which reacting is not."""
        a = await acting_user(guild_role=CommunityRole.member, initiative=True)
        await _posts_enabled(session, a.initiative)
        post = await create_post(session, a.initiative, a.user)
        await _strip_grants(session, Tool.post, post)
        b = await acting_user(
            guild_role=CommunityRole.member,
            guild=a.guild,
            initiative=a.initiative,
            initiative_role="member",
        )
        await create_resource_grant(
            session, post, user=b.user, level=ResourceAccessLevel.read
        )

        refused = await client.put(
            a.g(f"/posts/{post.id}/reactions"),
            headers=b.headers,
            json={"reactions_enabled": False},
        )
        assert refused.status_code == 403


class TestReactionNotifications:
    async def test_author_hears_about_a_reaction_once(
        self, client, session, acting_user
    ):
        from app.models.platform.notification import Notification, NotificationType
        from app.models.tenant.batched_notice import BatchedNotice
        from sqlmodel import select

        a = await acting_user(
            guild_role=CommunityRole.member, initiative=True, project=True
        )
        b = await acting_user(
            guild_role=CommunityRole.member,
            guild=a.guild,
            initiative=a.initiative,
            initiative_role="member",
        )
        await create_resource_grant(
            session, a.project, user=b.user, level=ResourceAccessLevel.write
        )
        task = await create_task(session, a.project)
        comment_id = await _comment_on_task(client, a, task.id)

        reacted = await client.put(
            a.g(f"/reactions/comment/{comment_id}"),
            headers=b.headers,
            json={"emoji": THUMBS},
        )
        assert reacted.status_code == 200, reacted.text

        await drain_notices()
        bell = (
            await session.exec(
                select(Notification).where(
                    Notification.user_id == a.user.id,
                    Notification.type == NotificationType.comment_reaction,
                )
            )
        ).all()
        assert len(bell) == 1
        assert bell[0].data["emoji"] == THUMBS

        await route_session_to_guild(session, a.guild.id)
        queued = (
            await session.exec(
                select(BatchedNotice).where(BatchedNotice.user_id == a.user.id)
            )
        ).all()
        assert len(queued) == 1
        assert queued[0].emoji == THUMBS

    async def test_reacting_to_your_own_post_notifies_nobody(
        self, client, session, acting_user
    ):
        from app.models.platform.notification import Notification, NotificationType
        from sqlmodel import select

        a = await acting_user(
            guild_role=CommunityRole.member, initiative=True, project=True
        )
        task = await create_task(session, a.project)
        comment_id = await _comment_on_task(client, a, task.id)
        await client.put(
            a.g(f"/reactions/comment/{comment_id}"),
            headers=a.headers,
            json={"emoji": THUMBS},
        )

        await drain_notices()
        bell = (
            await session.exec(
                select(Notification).where(
                    Notification.type == NotificationType.comment_reaction
                )
            )
        ).all()
        assert bell == []

    async def test_a_flurry_rolls_into_one_bell_line(
        self, client, session, acting_user
    ):
        """The point of the change: reactions digest on the bell too, so a
        second one on the same comment edits the line the first one wrote."""
        from app.models.platform.notification import Notification, NotificationType
        from sqlmodel import select

        a = await acting_user(
            guild_role=CommunityRole.member, initiative=True, project=True
        )
        b = await acting_user(
            guild_role=CommunityRole.member,
            guild=a.guild,
            initiative=a.initiative,
            initiative_role="member",
        )
        c = await acting_user(
            guild_role=CommunityRole.member,
            guild=a.guild,
            initiative=a.initiative,
            initiative_role="member",
        )
        for reactor in (b, c):
            await create_resource_grant(
                session, a.project, user=reactor.user, level=ResourceAccessLevel.write
            )
        task = await create_task(session, a.project)
        comment_id = await _comment_on_task(client, a, task.id)

        for reactor, emoji in ((b, THUMBS), (c, PARTY), (c, THUMBS)):
            reacted = await client.put(
                a.g(f"/reactions/comment/{comment_id}"),
                headers=reactor.headers,
                json={"emoji": emoji},
            )
            assert reacted.status_code == 200, reacted.text

        await drain_notices()
        bell = (
            await session.exec(
                select(Notification).where(
                    Notification.user_id == a.user.id,
                    Notification.type == NotificationType.comment_reaction,
                )
            )
        ).all()
        assert len(bell) == 1
        data = bell[0].data
        assert data["count"] == 3
        # Two people, three gestures — the sentence counts people.
        assert data["reactor_count"] == 2
        assert set(data["reactor_ids"]) == {b.user.id, c.user.id}
        assert [entry["emoji"] for entry in data["reactions"]] == [
            THUMBS,
            PARTY,
            THUMBS,
        ]
        # The top-level fields keep naming the most recent one, so a client
        # that predates the rollup still renders a true sentence.
        assert data["emoji"] == THUMBS
        assert data["reactor_id"] == c.user.id

    async def test_a_read_line_does_not_absorb_the_next_reaction(
        self, client, session, acting_user
    ):
        """Unread is the whole rollup window — once seen, the next reaction is
        news again."""
        from app.models.platform.notification import Notification, NotificationType
        from app.services.platform import user_notifications
        from sqlmodel import select

        a = await acting_user(
            guild_role=CommunityRole.member, initiative=True, project=True
        )
        b = await acting_user(
            guild_role=CommunityRole.member,
            guild=a.guild,
            initiative=a.initiative,
            initiative_role="member",
        )
        await create_resource_grant(
            session, a.project, user=b.user, level=ResourceAccessLevel.write
        )
        task = await create_task(session, a.project)
        comment_id = await _comment_on_task(client, a, task.id)

        await client.put(
            a.g(f"/reactions/comment/{comment_id}"),
            headers=b.headers,
            json={"emoji": THUMBS},
        )
        await drain_notices()
        await user_notifications.mark_all_notifications_read(session, user_id=a.user.id)
        await session.commit()
        await client.put(
            a.g(f"/reactions/comment/{comment_id}"),
            headers=b.headers,
            json={"emoji": PARTY},
        )

        await drain_notices()
        bell = (
            await session.exec(
                select(Notification).where(
                    Notification.user_id == a.user.id,
                    Notification.type == NotificationType.comment_reaction,
                )
            )
        ).all()
        assert len(bell) == 2

    async def test_taking_a_reaction_back_unsays_the_bell_line(
        self, client, session, acting_user
    ):
        """Un-reacting leaves no trace where the author has not looked yet —
        the same rule the queued digest line follows."""
        from app.models.platform.notification import Notification, NotificationType
        from sqlmodel import select

        a = await acting_user(
            guild_role=CommunityRole.member, initiative=True, project=True
        )
        b = await acting_user(
            guild_role=CommunityRole.member,
            guild=a.guild,
            initiative=a.initiative,
            initiative_role="member",
        )
        await create_resource_grant(
            session, a.project, user=b.user, level=ResourceAccessLevel.write
        )
        task = await create_task(session, a.project)
        comment_id = await _comment_on_task(client, a, task.id)

        for emoji in (THUMBS, PARTY):
            await client.put(
                a.g(f"/reactions/comment/{comment_id}"),
                headers=b.headers,
                json={"emoji": emoji},
            )

        async def _bell():
            await drain_notices()
            return (
                await session.exec(
                    select(Notification).where(
                        Notification.user_id == a.user.id,
                        Notification.type == NotificationType.comment_reaction,
                    )
                )
            ).all()

        [line] = await _bell()
        assert line.data["count"] == 2

        # Take the party popper back: the line keeps the other one and says so.
        await client.put(
            a.g(f"/reactions/comment/{comment_id}"),
            headers=b.headers,
            json={"emoji": PARTY},
        )
        session.expunge_all()
        [line] = await _bell()
        assert line.data["count"] == 1
        assert [entry["emoji"] for entry in line.data["reactions"]] == [THUMBS]

        # Take the last one back and the line has nothing left to say.
        await client.put(
            a.g(f"/reactions/comment/{comment_id}"),
            headers=b.headers,
            json={"emoji": THUMBS},
        )
        session.expunge_all()
        assert await _bell() == []

        # Reacted and taken back before anything was delivered: the line is
        # written and then taken back, in that order, and nothing is left.
        for _ in range(2):
            await client.put(
                a.g(f"/reactions/comment/{comment_id}"),
                headers=b.headers,
                json={"emoji": THUMBS},
            )
        session.expunge_all()
        assert await _bell() == []

    async def test_a_pre_rollup_line_can_still_be_un_said(
        self, client, session, acting_user
    ):
        """A line written before reactions rolled up carries no reaction id, so
        it has to be matched on who reacted and with what — otherwise the first
        un-react after the upgrade leaves it standing forever."""
        from app.models.platform.notification import Notification, NotificationType
        from sqlmodel import select

        a = await acting_user(
            guild_role=CommunityRole.member, initiative=True, project=True
        )
        b = await acting_user(
            guild_role=CommunityRole.member,
            guild=a.guild,
            initiative=a.initiative,
            initiative_role="member",
        )
        await create_resource_grant(
            session, a.project, user=b.user, level=ResourceAccessLevel.write
        )
        task = await create_task(session, a.project)
        comment_id = await _comment_on_task(client, a, task.id)

        await client.put(
            a.g(f"/reactions/comment/{comment_id}"),
            headers=b.headers,
            json={"emoji": THUMBS},
        )

        async def _bell():
            await drain_notices()
            return (
                await session.exec(
                    select(Notification).where(
                        Notification.user_id == a.user.id,
                        Notification.type == NotificationType.comment_reaction,
                    )
                )
            ).all()

        # Rewrite the line into the shape this feature replaced.
        [line] = await _bell()
        line.data = {
            key: value
            for key, value in line.data.items()
            if key not in {"count", "reactions", "reactor_count", "reactor_ids"}
        }
        session.add(line)
        await session.commit()

        await client.put(
            a.g(f"/reactions/comment/{comment_id}"),
            headers=b.headers,
            json={"emoji": THUMBS},
        )
        session.expunge_all()
        assert await _bell() == []

    async def test_taking_a_reaction_back_withdraws_the_queued_line(
        self, client, session, acting_user
    ):
        from app.models.tenant.batched_notice import BatchedNotice
        from sqlmodel import select

        a = await acting_user(
            guild_role=CommunityRole.member, initiative=True, project=True
        )
        b = await acting_user(
            guild_role=CommunityRole.member,
            guild=a.guild,
            initiative=a.initiative,
            initiative_role="member",
        )
        await create_resource_grant(
            session, a.project, user=b.user, level=ResourceAccessLevel.write
        )
        task = await create_task(session, a.project)
        comment_id = await _comment_on_task(client, a, task.id)

        for _ in range(2):  # on, then off
            resp = await client.put(
                a.g(f"/reactions/comment/{comment_id}"),
                headers=b.headers,
                json={"emoji": THUMBS},
            )
            assert resp.status_code == 200

        await route_session_to_guild(session, a.guild.id)
        queued = (
            await session.exec(
                select(BatchedNotice).where(BatchedNotice.user_id == a.user.id)
            )
        ).all()
        assert queued == []


async def test_a_reaction_is_its_reactors_to_change(session, acting_user, reading_as):
    """Another member and the community's admin see someone's reaction but
    neither take it off nor add one in their name in the database: what they
    add is theirs."""
    from app.models.tenant.reaction import Reaction
    from sqlalchemy.exc import DBAPIError
    from sqlmodel import select

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    task = await create_task(session, a.project)
    comment = await create_comment(session, a.user, task=task)
    await create_reaction(session, a.user, comment=comment)
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

    for outsider in (other, admin):
        asking = await reading_as(outsider.user.id, a.guild.id)
        assert (await asking.exec(select(Reaction.created_by))).all() == [a.user.id]
        gone = await asking.exec(sa_delete(Reaction))
        assert gone.rowcount == 0
        mine = Reaction(
            target_type="comment",
            target_id=comment.id,
            emoji=PARTY,
            created_by=a.user.id,
        )
        asking.add(mine)
        await asking.flush()
        await asking.refresh(mine)
        assert mine.created_by == outsider.user.id
        mine.created_by = a.user.id
        asking.add(mine)
        with pytest.raises(DBAPIError, match="an author does not change"):
            await asking.flush()


class TestReactionLifecycle:
    async def test_purging_a_post_takes_what_names_it(
        self, client, session, acting_user
    ):
        """Reactions on the post and on its comments, and opens of it,
        go with the post: they name it by id, and nothing could remove them
        once it is gone. They are a member's own, which the admin purging
        never reaches, and the purge takes them all the same."""
        from app.models.tenant.reaction import Reaction
        from app.models.tenant.personal_item import PersonalItem
        from sqlmodel import select

        a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
        await _posts_enabled(session, a.initiative)
        post = await create_post(session, a.initiative, a.user)
        comment = await create_comment(session, a.user, post=post)
        b = await acting_user(
            guild_role=CommunityRole.member,
            guild=a.guild,
            initiative=a.initiative,
            initiative_role="member",
        )
        for path in (
            f"/reactions/post/{post.id}",
            f"/reactions/comment/{comment.id}",
        ):
            resp = await client.put(
                a.g(path), headers=b.headers, json={"emoji": THUMBS}
            )
            assert resp.status_code == 200, resp.text
        viewed = await client.put(
            a.g(f"/personal-items/view/post/{post.id}"), headers=b.headers
        )
        assert viewed.status_code == 200, viewed.text

        trashed = await client.delete(a.g(f"/posts/{post.id}"), headers=a.headers)
        assert trashed.status_code in (200, 204), trashed.text
        purged = await client.delete(
            a.g(f"/trash/post/{post.id}/purge"), headers=a.headers
        )
        assert purged.status_code == 204, purged.text

        await route_session_to_guild(session, a.guild.id)
        assert (await session.exec(select(Reaction))).all() == []
        assert (await session.exec(select(PersonalItem))).all() == []
