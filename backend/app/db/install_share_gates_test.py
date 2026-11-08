"""An installed plug-in shares what it may share, at the database.

The plug-in role's policies on ``resource_grants`` admit a share row only with
``sharing:write`` and the tool's write scope in the standing, on a resource
where the install holds write, and only as a read or write share with a
person, a role or all initiative members. Each case is run on the real
request login, routed as the install.
"""

from __future__ import annotations

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import DBAPIError
from sqlmodel import select

from app.core.tools import Tool
from app.db.install_standing_test import _install, _route
from app.core.file_types import FileType
from app.models.tenant.file import File
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.testing import (
    create_file,
    create_resource_grant,
    route_as,
    route_session_to_guild,
)


_SHARES = ["files:write", "sharing:write"]


async def _made_by_the_install(s, install) -> File:
    made = File(
        initiative_id=install.a.id,
        name="Made by the plug-in",
        file_type=FileType.lexical,
    )
    s.add(made)
    await s.flush()
    return made


def _share(file_id: int, initiative_id: int, **grantee) -> ResourceGrant:
    return ResourceGrant(
        resource_type=Tool.file.value,
        resource_id=file_id,
        initiative_id=initiative_id,
        level=grantee.pop("level", ResourceAccessLevel.read),
        **grantee,
    )


async def test_an_install_shares_what_it_owns(session, acting_user, role_session):
    install = await _install(session, acting_user, role_session, granted=_SHARES)
    s, _ = await _route(role_session, install, _SHARES)
    made = await _made_by_the_install(s, install)
    s.add(_share(made.id, install.a.id, all_initiative_members=True))
    s.add(
        _share(
            made.id,
            install.a.id,
            user_id=install.seat.user.id,
            level=ResourceAccessLevel.write,
        )
    )
    await s.flush()

    rows = (
        await s.exec(
            select(ResourceGrant.level, ResourceGrant.all_initiative_members).where(
                ResourceGrant.resource_type == Tool.file.value,
                ResourceGrant.resource_id == made.id,
                ResourceGrant.plugin_install_id.is_(None),
            )
        )
    ).all()
    assert sorted(rows) == [
        (ResourceAccessLevel.read, True),
        (ResourceAccessLevel.write, False),
    ]

    # And takes a share away again, while its own owner row stays.
    await s.exec(
        delete(ResourceGrant).where(
            ResourceGrant.resource_type == Tool.file.value,
            ResourceGrant.resource_id == made.id,
        )
    )
    left = (
        await s.exec(
            select(ResourceGrant.level, ResourceGrant.plugin_install_id).where(
                ResourceGrant.resource_type == Tool.file.value,
                ResourceGrant.resource_id == made.id,
            )
        )
    ).all()
    assert left == [(ResourceAccessLevel.owner, install.plugin.id)]
    await s.rollback()


@pytest.mark.parametrize(
    ("granted", "token"),
    [
        (["files:write"], ["files:write"]),
        (_SHARES, ["files:write"]),
        (["files:read", "sharing:write"], ["files:read", "sharing:write"]),
    ],
    ids=["not_granted", "not_in_token", "no_tool_write"],
)
async def test_without_both_write_scopes_an_install_shares_nothing(
    session, acting_user, role_session, granted, token
):
    install = await _install(session, acting_user, role_session, granted=granted)
    if "files:write" in token:
        s, _ = await _route(role_session, install, token)
        target = (await _made_by_the_install(s, install)).id
    else:
        # Owned by the install without its creating it.
        file = await create_file(session, install.a, install.seat.user)
        await route_session_to_guild(session, install.guild.id)
        await session.exec(
            delete(ResourceGrant).where(
                ResourceGrant.resource_type == Tool.file.value,
                ResourceGrant.resource_id == file.id,
            )
        )
        await create_resource_grant(
            session,
            file,
            plugin_install_id=install.plugin.id,
            level=ResourceAccessLevel.owner,
        )
        target = file.id
        s, _ = await _route(role_session, install, token)
    s.add(_share(target, install.a.id, all_initiative_members=True))
    with pytest.raises(DBAPIError, match="row-level security"):
        await s.flush()
    await s.rollback()


async def test_reading_a_resource_is_not_enough_to_share_it(
    session, acting_user, role_session
):
    install = await _install(session, acting_user, role_session, granted=_SHARES)
    readable = await create_file(session, install.a, install.seat.user)
    await create_resource_grant(session, readable, all_initiative_members=True)

    s, _ = await _route(role_session, install, _SHARES)
    assert (await s.exec(select(File.id).where(File.id == readable.id))).all() == [
        readable.id
    ]
    s.add(_share(readable.id, install.a.id, user_id=install.seat.user.id))
    with pytest.raises(DBAPIError, match="row-level security"):
        await s.flush()
    await s.rollback()

    # Nor may it take the share it reads by away.
    s, _ = await _route(role_session, install, _SHARES)
    await s.exec(
        delete(ResourceGrant).where(
            ResourceGrant.resource_type == Tool.file.value,
            ResourceGrant.resource_id == readable.id,
        )
    )
    await s.commit()
    await route_session_to_guild(session, install.guild.id)
    kept = (
        await session.exec(
            select(ResourceGrant.id).where(
                ResourceGrant.resource_type == Tool.file.value,
                ResourceGrant.resource_id == readable.id,
            )
        )
    ).all()
    assert len(kept) == 2  # the seat's owner row and the members' share


@pytest.mark.parametrize("row", ["owner_for_a_person", "owner_for_itself", "to_itself"])
async def test_a_share_is_never_ownership_or_a_plugin_grant(
    session, acting_user, role_session, row
):
    """On a file open to its initiative for writing and owned by nobody,
    the install holds write, and writes no owner row, no grant naming a plug-in,
    and, since sharing is the owner's, no share either."""
    install = await _install(session, acting_user, role_session, granted=_SHARES)
    file = await create_file(session, install.a, install.seat.user)
    await route_session_to_guild(session, install.guild.id)
    await session.exec(
        delete(ResourceGrant).where(
            ResourceGrant.resource_type == Tool.file.value,
            ResourceGrant.resource_id == file.id,
        )
    )
    session.add(
        _share(
            file.id,
            install.a.id,
            all_initiative_members=True,
            level=ResourceAccessLevel.write,
        )
    )
    await session.commit()

    s, _ = await _route(role_session, install, _SHARES)
    grantee = (
        {"user_id": install.seat.user.id}
        if row == "owner_for_a_person"
        else {"plugin_install_id": install.plugin.id}
    )
    level = (
        ResourceAccessLevel.write if row == "to_itself" else ResourceAccessLevel.owner
    )
    s.add(_share(file.id, install.a.id, level=level, **grantee))
    with pytest.raises(DBAPIError, match="row-level security"):
        await s.flush()
    await s.rollback()

    s, _ = await _route(role_session, install, _SHARES)
    s.add(_share(file.id, install.a.id, user_id=install.seat.user.id))
    with pytest.raises(DBAPIError, match="row-level security"):
        await s.flush()
    await s.rollback()


async def test_a_person_shares_as_before(session, acting_user, role_session):
    """The legs leave a person's request as it was: a member of the
    initiative writes a share on a resource the database lets them reach."""
    install = await _install(session, acting_user, role_session, granted=_SHARES)
    file = await create_file(session, install.a, install.seat.user)
    person = await role_session("app_user")
    await route_as(person, user_id=install.seat.user.id, guild_id=install.guild.id)
    person.add(_share(file.id, install.a.id, all_initiative_members=True))
    await person.flush()
    await person.rollback()
