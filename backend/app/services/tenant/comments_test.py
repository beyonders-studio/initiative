"""PAM grants on comment threads, and the per-tool RLS legs of ``comments``.

A live grant lets a grantee read a guild's comment threads (read) and, for a
read_write grant, post to them — without any DAC permission row. A read-only
grant must NOT be able to post.
"""

import pytest
from httpx2 import AsyncClient
from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import Tool
from app.models.platform.user import UserRole
from app.testing import (
    create_access_grant,
    create_comment,
    create_file,
    create_guild,
    create_guild_membership,
    create_initiative,
    create_project,
    create_task,
    create_user,
    get_auth_headers,
    guild_url,
    route_as,
    thread_path,
)
from app.testing.factories import TOOL_FACTORIES


@pytest.mark.parametrize("kind", ["task", "file"])
async def test_a_grant_reads_threads_and_only_read_write_posts(
    client: AsyncClient, session: AsyncSession, kind: str
):
    """Both branches of the parent check: a task answers through its project,
    a tool entity answers for itself."""
    owner = await create_user(session)
    grantee = await create_user(session, role=UserRole.support)
    guild = await create_guild(session, creator=owner)
    init = await create_initiative(session, guild, owner)
    if kind == "task":
        subject = await create_task(session, await create_project(session, init, owner))
    else:
        subject = await create_file(session, init, owner)
    subject_id = subject.id
    headers = get_auth_headers(grantee)
    thread = guild_url(guild.id, thread_path(kind, subject_id))

    async def post():
        return await client.post(
            guild_url(guild.id, "/comments/"),
            headers=headers,
            json={"subject_type": kind, "subject_id": subject_id, "content": "Hi"},
        )

    # No grant: there is no way into the community at all.
    assert (await client.get(thread, headers=headers)).status_code == 403

    grant = await create_access_grant(session, user=grantee, guild=guild)
    assert (await client.get(thread, headers=headers)).status_code == 200
    refused = await post()
    assert refused.status_code == 403, refused.text

    grant.access_level = "read_write"
    session.add(grant)
    await session.commit()
    posted = await post()
    assert posted.status_code == 201, posted.text


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
        entity = await TOOL_FACTORIES[tool](session, init, owner)
        comment = await create_comment(session, owner, **{tool.value: entity})

        outsider = await create_user(session)
        await create_guild_membership(session, user=outsider, guild=guild)

        count_sql = text(
            "SELECT count(*) FROM comments WHERE subject_type = :kind"
            " AND subject_id = :eid"
        ).bindparams(kind=tool.value, eid=entity.id)

        s = await role_session("app_user")
        await route_as(s, user_id=outsider.id, guild_id=guild.id)
        assert (await s.exec(count_sql)).scalar() == 0

        member = await role_session("app_user")
        await route_as(member, user_id=owner.id, guild_id=guild.id)
        assert (await s.exec(count_sql)).scalar() == 0  # outsider still sees none
        assert (await member.exec(count_sql)).scalar() == 1
        assert comment.id is not None
