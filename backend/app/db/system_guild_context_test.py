"""The narrow, fail-closed guild route used by account erasure."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.db.request_context import SystemMaintenance
from app.db.session import set_rls_context
from app.testing.factories import (
    create_comment,
    create_guild,
    create_initiative,
    create_project,
    create_task,
    create_user,
)


async def test_system_guild_route_keeps_app_admin_bypass_and_denies_app_user(
    session, role_session
) -> None:
    owner = await create_user(session)
    guild = await create_guild(session, creator=owner)
    initiative = await create_initiative(session, guild, owner)
    project = await create_project(session, initiative, owner)
    task = await create_task(session, project)
    await create_comment(session, owner, task=task, content="private")

    admin = await role_session("app_admin")
    await set_rls_context(admin, SystemMaintenance(guild.id))
    identity = (
        await admin.exec(
            text(
                "SELECT current_user, session_user, rolbypassrls, current_schema() "
                "FROM pg_roles WHERE rolname = current_user"
            )
        )
    ).one()
    assert identity == ("app_admin", "app_admin", True, f"guild_{guild.id}")
    assert (await admin.exec(text("SELECT count(*) FROM comments"))).one()[0] == 1

    request_session = await role_session("app_user")
    with pytest.raises(
        PermissionError,
        match="system guild routing requires the configured system login",
    ):
        await set_rls_context(request_session, SystemMaintenance(guild.id))
