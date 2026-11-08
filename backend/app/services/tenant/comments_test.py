"""Tests for PAM-grant awareness in comment access checks.

A live grant lets a grantee read a guild's comment threads (read) and, for a
read_write grant, post to them — without any DAC permission row. A read-only
grant must NOT be able to post.
"""

import pytest
from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import Tool
from app.models.platform.user import UserRole
from app.models.tenant.file import File
from app.services.tenant.comments import (
    _ensure_parent_access,
    _load_parent,
)
from app.testing.factories import TOOL_FACTORIES
from app.testing import (
    create_access_grant,
    create_comment,
    create_guild,
    create_guild_membership,
    create_initiative,
    create_project,
    create_task,
    create_user,
    route_as,
)


async def test_task_comment_access_honors_grant(session: AsyncSession, reading_as):
    owner = await create_user(session, email="owner-cmt@example.com")
    grantee = await create_user(
        session, email="grantee-cmt@example.com", role=UserRole.support
    )
    guild = await create_guild(session, creator=owner)
    init = await create_initiative(session, guild, owner)
    project = await create_project(session, init, owner, name="P")
    task = await create_task(session, project)

    ctx = await _load_parent(
        session, column="task_id", entity_id=task.id, guild_id=guild.id
    )
    assert ctx is not None

    # No grant: there is no way into the community at all.
    from app.api.deps import GuildAccessError

    with pytest.raises(GuildAccessError):
        await reading_as(grantee.id, guild.id)

    # Read grant: may read comments.
    grant = await create_access_grant(session, user=grantee, guild=guild)
    reader = await reading_as(grantee.id, guild.id)
    await _ensure_parent_access(reader, ctx, user=grantee, access="read")
    await reader.rollback()

    # The same grant at read_write: may post.
    grant.access_level = "read_write"
    session.add(grant)
    await session.commit()
    reader = await reading_as(grantee.id, guild.id)
    await _ensure_parent_access(reader, ctx, user=grantee, access="write")
    await reader.rollback()


async def test_file_comment_access_honors_grant(session: AsyncSession, reading_as):
    """The other branch of the parent check: a tool entity answers for itself,
    where a task answers through its project."""
    owner = await create_user(session, email="owner-cmt2@example.com")
    grantee = await create_user(
        session, email="grantee-cmt2@example.com", role=UserRole.support
    )
    guild = await create_guild(session, creator=owner)
    init = await create_initiative(session, guild, owner)
    file = File(
        initiative_id=init.id,
        name="Doc",
        content={},
        created_by=owner.id,
    )
    session.add(file)
    await session.commit()
    await session.refresh(file)

    ctx = await _load_parent(
        session, column="file_id", entity_id=file.id, guild_id=guild.id
    )
    assert ctx is not None

    from app.api.deps import GuildAccessError

    with pytest.raises(GuildAccessError):
        await reading_as(grantee.id, guild.id)

    grant = await create_access_grant(session, user=grantee, guild=guild)
    reader = await reading_as(grantee.id, guild.id)
    await _ensure_parent_access(reader, ctx, user=grantee, access="read")
    await reader.rollback()

    grant.access_level = "read_write"
    session.add(grant)
    await session.commit()
    reader = await reading_as(grantee.id, guild.id)
    await _ensure_parent_access(reader, ctx, user=grantee, access="write")
    await reader.rollback()


async def test_a_read_only_grant_cannot_post(session: AsyncSession, reading_as):
    """The half of the rule the parent check no longer answers.

    Reaching a thread and adding to it are different questions, and only the
    first is "can this request see the parent". Posting is a write, and a
    read-only window is routed into the SELECT-only guild role — so the refusal
    is the insert's, and this is where it has to be asked.

    Under the real ``app_user`` login, like the RLS legs below: a session that
    reaches Postgres as a superuser would accept the insert whatever the
    window said.

    The assertion is on the outcome rather than on which layer produced it.
    Both are real refusals, and pinning the message would make this fail the
    day the grant layer changes without the rule changing.
    """
    owner = await create_user(session, email="owner-cmt-ro@example.com")
    support = await create_user(
        session, email="support-cmt-ro@example.com", role=UserRole.support
    )
    guild = await create_guild(session, creator=owner)
    init = await create_initiative(session, guild, owner)
    project = await create_project(session, init, owner, name="P")
    task = await create_task(session, project)

    insert = text(
        "INSERT INTO comments (task_id, content, created_by,"
        " created_at, updated_at)"
        " VALUES (:t, 'let me in', :u, now(), now())"
    ).bindparams(t=task.id, u=support.id)

    # A grantee reaches the community through the row, and the row says at
    # what level.
    grant = await create_access_grant(session, user=support, guild=guild)
    reader = await reading_as(support.id, guild.id)
    with pytest.raises(Exception) as refused:
        await reader.exec(insert)
    message = str(refused.value).lower()
    assert "permission denied" in message or "row-level security" in message, (
        refused.value
    )
    await reader.rollback()

    # The same window at write level is what posting takes.
    grant.access_level = "read_write"
    session.add(grant)
    await session.commit()
    writer = await reading_as(support.id, guild.id)
    await writer.exec(insert)
    await writer.rollback()


# The canonical per-tool factory registry rather than a copy of it: that one
# is checked against the Tool enum at import time, so a new tool cannot reach
# these parametrized cases without a factory behind it.
_TOOL_FACTORIES = TOOL_FACTORIES


class TestCommentRlsLegs:
    """Comments carry one RLS leg per parent, rendered from the same
    declaration for every tool. These run under the real ``app_user`` login,
    because the subject is what the policy itself returns."""

    @pytest.mark.parametrize("tool", list(Tool))
    async def test_a_tool_comment_is_scoped_to_its_initiative(
        self, session, role_session, tool
    ):
        owner = await create_user(session)
        guild = await create_guild(session, creator=owner)
        init = await create_initiative(session, guild, owner)
        entity = await _TOOL_FACTORIES[tool](session, init, owner)
        comment = await create_comment(session, owner, **{tool.value: entity})

        outsider = await create_user(session)
        await create_guild_membership(session, user=outsider, guild=guild)

        count_sql = text(
            f"SELECT count(*) FROM comments WHERE {tool.value}_id = :eid"  # noqa: S608 — column name from the Tool enum
        ).bindparams(eid=entity.id)

        s = await role_session("app_user")
        await route_as(s, user_id=outsider.id, guild_id=guild.id)
        assert (await s.exec(count_sql)).scalar() == 0

        member = await role_session("app_user")
        await route_as(member, user_id=owner.id, guild_id=guild.id)
        assert (await s.exec(count_sql)).scalar() == 0  # outsider still sees none
        assert (await member.exec(count_sql)).scalar() == 1
        assert comment.id is not None
