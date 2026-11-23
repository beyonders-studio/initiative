"""Ownership: what it is, where it lives, and what happens when someone leaves."""

from datetime import UTC, datetime

from sqlalchemy import delete
from sqlmodel import select

from app.core.tool_set import ToolRecord
from app.core.tools import Tool
from app.db.plugin_tools import provisioned_tools
from app.db.tool_rows import load_row, locate
from app.models.platform.guild import CommunityRole, GuildMembership
from app.models.tenant.metadata import MetadataType
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.services.tenant import initiatives as initiatives_service
from app.services.tenant import ownership as ownership_service
from app.services.tenant.soft_delete import trash
from app.testing import (
    TOOL_FACTORIES,
    add_counter,
    create_guild,
    create_guild_membership,
    create_initiative,
    create_initiative_member,
    create_property_definition,
    create_property_value,
    create_resource_grant,
    create_user,
    install_tool_plugin,
    route_session_to_guild,
)

# ── Behaviour ───────────────────────────────────────────────────────────────


async def _owner_grant(session, tool: Tool | ToolRecord, resource_id: int):
    return (
        await session.exec(
            select(ResourceGrant).where(
                ResourceGrant.resource_type == tool.value,
                ResourceGrant.resource_id == resource_id,
                ResourceGrant.level == ResourceAccessLevel.owner,
            )
        )
    ).one_or_none()


async def _one_of_every_tool(session, initiative, creator):
    """An instance of each tool, keyed by tool — derived from the enum."""
    return {
        tool: await TOOL_FACTORIES[tool](session, initiative, creator) for tool in Tool
    }


async def test_departure_releases_ownership_and_keeps_authorship(session):
    """Leaving the guild releases ownership rather than handing it on. The
    author wrote it, and the signer signed it; leaving does not change who
    did. A person field naming them is emptied."""
    admin = await create_user(session)
    guild = await create_guild(session, creator=admin)
    leaver = await create_user(session)
    await create_guild_membership(session, leaver, guild, CommunityRole.member)
    initiative = await create_initiative(session, guild, admin)
    await create_initiative_member(session, initiative, leaver, "project_manager")

    rows = await _one_of_every_tool(session, initiative, leaver)
    authors = {tool: row.created_by for tool, row in rows.items()}
    signed, named = [
        await create_property_value(
            session,
            rows[Tool.project],
            await create_property_definition(
                session, initiative, name=kind.value, type=kind
            ),
            value_user_id=leaver.id,
            value_text="L.",
            value_datetime=datetime.now(UTC),
        )
        for kind in (MetadataType.signature, MetadataType.user_reference)
    ]

    await initiatives_service.remove_user_from_guild_initiatives(
        session, guild_id=guild.id, user_id=leaver.id
    )
    await session.commit()

    await route_session_to_guild(session, guild.id)
    for tool, expected in authors.items():
        assert await _owner_grant(session, tool, rows[tool].id) is None, (
            f"{tool.value} still has an owner after its owner left the guild"
        )
        await session.refresh(rows[tool])
        assert rows[tool].created_by == expected, (
            f"{tool.value} authorship changed on departure"
        )
    await session.refresh(signed)
    await session.refresh(named)
    assert (signed.value_user_id, named.value_user_id) == (leaver.id, None)


async def test_transfer_moves_every_tool(session):
    """The admin action re-homes each tool, upgrading rather than duplicating."""
    admin = await create_user(session)
    guild = await create_guild(session, creator=admin)
    holder = await create_user(session)
    await create_guild_membership(session, holder, guild, CommunityRole.member)
    initiative = await create_initiative(session, guild, admin)
    await create_initiative_member(session, initiative, holder, "project_manager")

    rows = await _one_of_every_tool(session, initiative, holder)

    await route_session_to_guild(session, guild.id)
    counts = await ownership_service.transfer_content_ownership(
        session, from_user_id=holder.id, to=ownership_service.Owner(user_id=admin.id)
    )
    await session.commit()

    assert {tool.kind for tool in counts} == set(Tool)
    for tool, row in rows.items():
        grant = await _owner_grant(session, tool, row.id)
        assert grant is not None and grant.user_id == admin.id


async def test_transfer_to_an_existing_grantee_upgrades_one_row(session):
    """A recipient who already had access ends up with one row, at owner."""
    admin = await create_user(session)
    guild = await create_guild(session, creator=admin)
    holder = await create_user(session)
    await create_guild_membership(session, holder, guild, CommunityRole.member)
    initiative = await create_initiative(session, guild, admin)
    await create_initiative_member(session, initiative, holder, "project_manager")

    project = await TOOL_FACTORIES[Tool.project](session, initiative, holder)

    await create_resource_grant(session, project, user=admin)

    await ownership_service.transfer_content_ownership(
        session, from_user_id=holder.id, to=ownership_service.Owner(user_id=admin.id)
    )
    await session.commit()

    grants = (
        await session.exec(
            select(ResourceGrant).where(
                ResourceGrant.resource_type == Tool.project.value,
                ResourceGrant.resource_id == project.id,
                ResourceGrant.user_id == admin.id,
            )
        )
    ).all()
    assert len(grants) == 1
    assert grants[0].level == ResourceAccessLevel.owner


async def test_unowned_covers_released_and_orphaned(session):
    """Content nobody can act on shows up whether it was released or orphaned."""
    admin = await create_user(session)
    guild = await create_guild(session, creator=admin)
    leaver = await create_user(session)
    await create_guild_membership(session, leaver, guild, CommunityRole.member)
    initiative = await create_initiative(session, guild, admin)
    await create_initiative_member(session, initiative, leaver, "project_manager")

    released = await TOOL_FACTORIES[Tool.project](session, initiative, leaver)
    orphaned = await TOOL_FACTORIES[Tool.wiki](session, initiative, leaver)

    await route_session_to_guild(session, guild.id)
    # Released: no owner row at all.
    await ownership_service.set_resource_owner(
        session, tool=Tool.project, row=released, new_owner=None
    )
    await session.commit()

    # Orphaned: an owner row naming someone who is no longer a member. This is
    # the shape left behind before departures released ownership.
    membership = (
        await session.exec(
            select(GuildMembership).where(
                GuildMembership.user_id == leaver.id,
                GuildMembership.guild_id == guild.id,
            )
        )
    ).one()
    await session.delete(membership)
    await session.commit()

    await route_session_to_guild(session, guild.id)
    items = await ownership_service.summarize_unowned_content(
        session, guild_id=guild.id
    )
    found = {(i.tool.kind, i.id) for i in items}
    assert (Tool.project, released.id) in found
    assert (Tool.wiki, orphaned.id) in found


async def test_restore_leaves_content_unowned_when_the_author_has_gone(session):
    """No author in the guild, no guess — it stays unowned."""
    admin = await create_user(session)
    guild = await create_guild(session, creator=admin)
    author = await create_user(session)
    await create_guild_membership(session, author, guild, CommunityRole.member)
    initiative = await create_initiative(session, guild, admin)
    await create_initiative_member(session, initiative, author, "project_manager")

    file = await TOOL_FACTORIES[Tool.file](session, initiative, author)

    await initiatives_service.remove_user_from_guild_initiatives(
        session, guild_id=guild.id, user_id=author.id
    )
    membership = (
        await session.exec(
            select(GuildMembership).where(
                GuildMembership.user_id == author.id,
                GuildMembership.guild_id == guild.id,
            )
        )
    ).one()
    await session.delete(membership)
    await session.commit()

    await route_session_to_guild(session, guild.id)
    claimed = await ownership_service.restore_ownership_to_author(
        session, row=file, guild_id=guild.id
    )
    await session.commit()

    assert claimed is False
    assert await _owner_grant(session, Tool.file, file.id) is None


async def test_a_tool_plugins_row_goes_back_to_its_author_on_restore(
    client, session, acting_user, reading_as
):
    """A tool plug-in's row taken out of the trash unowned goes back to its
    author, as a built-in tool's does."""
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    author = await acting_user(
        guild=admin.guild, initiative=admin.initiative, initiative_role="moderator"
    )
    await session.commit()
    seat = await acting_user(guild=author.guild, guild_role=CommunityRole.superadmin)
    await install_tool_plugin(client, session, seat)
    tools = await provisioned_tools(author.guild.id)
    kind = tools.installed[0].kind
    located = locate(tools, kind)
    assert located is not None
    mine = await reading_as(author.user.id, author.guild.id)
    group, _counter = (await add_counter(mine, author.guild.id, author.initiative.id))[
        1:
    ]
    row = await load_row(mine, located, tools, group)
    assert row is not None
    await trash(mine, row, deleted_by_user_id=author.user.id)
    await mine.commit()
    await route_session_to_guild(session, author.guild.id)
    await session.exec(
        delete(ResourceGrant).where(
            ResourceGrant.resource_type == kind,
            ResourceGrant.resource_id == group,
            ResourceGrant.level == ResourceAccessLevel.owner,
        )
    )
    await session.commit()

    response = await client.post(
        author.g(f"/trash/{kind}/{group}/restore"), headers=author.headers
    )
    assert response.status_code == 200, response.text
    await route_session_to_guild(session, author.guild.id)
    grant = await _owner_grant(session, tools.by_kind[kind], group)
    assert grant is not None and grant.user_id == author.user.id


async def test_general_access_does_not_displace_the_owner(session):
    """Sharing with the whole initiative leaves the owner grant standing.

    General access is an all-members row at read/write; the owner is a separate
    user row at ``owner``. Rebuilding a resource's sharing replaces the first
    and preserves the second, so opening something up never leaves it ownerless.
    """
    from app.schemas.tenant.resource_grant import ResourceGrantSchema
    from app.services import permissions as permissions_service

    admin = await create_user(session)
    guild = await create_guild(session, creator=admin)
    owner = await create_user(session)
    await create_guild_membership(session, owner, guild, CommunityRole.member)
    initiative = await create_initiative(session, guild, admin)
    await create_initiative_member(session, initiative, owner, "project_manager")

    for tool in Tool:
        row = await TOOL_FACTORIES[tool](session, initiative, owner)
        await route_session_to_guild(session, guild.id)

        await permissions_service.replace_resource_grants(
            session,
            resource_type=tool.value,
            resource_id=row.id,
            guild_id=guild.id,
            initiative_id=row.initiative_id,
            owner_id=owner.id,
            grants=[ResourceGrantSchema(all_initiative_members=True, level="write")],
        )
        await session.commit()

        grant = await _owner_grant(session, tool, row.id)
        assert grant is not None and grant.user_id == owner.id, (
            f"{tool.value} lost its owner when shared with the whole initiative"
        )

        # And the all-members row exists alongside it, not instead of it.
        shared = (
            await session.exec(
                select(ResourceGrant).where(
                    ResourceGrant.resource_type == tool.value,
                    ResourceGrant.resource_id == row.id,
                    ResourceGrant.all_initiative_members.is_(True),
                )
            )
        ).one()
        assert shared.level == ResourceAccessLevel.write


# ── Owner grants that name no user (issue #1858) ────────────────────────────


async def _make_role_the_owner(session, *, tool: Tool, row, role_id: int):
    """Replace a resource's user owner grant with one held by a role.

    The shape migration 20260804_0157 left on every calendar it backfilled:
    one owner row per manager role, no user named. Reproduced rather than
    depended on, because that migration has already run everywhere.
    """
    grant = await _owner_grant(session, tool, row.id)
    assert grant is not None
    await session.delete(grant)
    await session.flush()
    await create_resource_grant(
        session, row, role_id=role_id, level=ResourceAccessLevel.owner
    )


async def _manager_role_id(session, initiative) -> int:
    from app.models.tenant.initiative import InitiativeRoleModel

    return (
        await session.exec(
            select(InitiativeRoleModel.id).where(
                InitiativeRoleModel.initiative_id == initiative.id,
                InitiativeRoleModel.name == "project_manager",
            )
        )
    ).one()


async def _grants_for(session, tool: Tool, resource_id: int):
    return (
        await session.exec(
            select(ResourceGrant).where(
                ResourceGrant.resource_type == tool.value,
                ResourceGrant.resource_id == resource_id,
            )
        )
    ).all()


async def test_a_role_held_owner_grant_is_claimable(session):
    """Content whose owner row names a role can be claimed by an admin.

    Ownership means a person or nobody, but the single-owner index counts a
    role's owner row like anyone else's — so one left standing made the new
    owner collide with it and the claim fail outright. The role keeps write,
    not nothing: its grant was never visible in the sharing panel, so dropping
    it would take editing away from people with no record of why.
    """
    admin = await create_user(session)
    guild = await create_guild(session, creator=admin)
    initiative = await create_initiative(session, guild, admin)
    calendar = await TOOL_FACTORIES[Tool.calendar](session, initiative, admin)
    role_id = await _manager_role_id(session, initiative)

    await route_session_to_guild(session, guild.id)
    await _make_role_the_owner(
        session, tool=Tool.calendar, row=calendar, role_id=role_id
    )

    await route_session_to_guild(session, guild.id)
    items = await ownership_service.summarize_unowned_content(
        session, guild_id=guild.id
    )
    assert (Tool.calendar, calendar.id) in {(i.tool.kind, i.id) for i in items}

    counts = await ownership_service.claim_unowned_content(
        session, guild_id=guild.id, to=ownership_service.Owner(user_id=admin.id)
    )
    await session.commit()

    assert {tool.kind: n for tool, n in counts.items()}.get(Tool.calendar.value) == 1
    grant = await _owner_grant(session, Tool.calendar, calendar.id)
    assert grant is not None and grant.user_id == admin.id
    role_grants = [
        g
        for g in await _grants_for(session, Tool.calendar, calendar.id)
        if g.role_id == role_id
    ]
    assert len(role_grants) == 1
    assert role_grants[0].level == ResourceAccessLevel.write


async def test_releasing_content_clears_an_owner_row_that_names_no_user(session):
    """Every path through ``set_resource_owner`` ends with no owner row left."""
    admin = await create_user(session)
    guild = await create_guild(session, creator=admin)
    initiative = await create_initiative(session, guild, admin)
    calendar = await TOOL_FACTORIES[Tool.calendar](session, initiative, admin)
    role_id = await _manager_role_id(session, initiative)

    await route_session_to_guild(session, guild.id)
    await _make_role_the_owner(
        session, tool=Tool.calendar, row=calendar, role_id=role_id
    )

    await route_session_to_guild(session, guild.id)
    await ownership_service.set_resource_owner(
        session, tool=Tool.calendar, row=calendar, new_owner=None
    )
    await session.commit()

    assert await _owner_grant(session, Tool.calendar, calendar.id) is None


async def test_a_tool_plugins_row_is_transferred_and_claimed(
    client, session, acting_user, reading_as
):
    """A tool plug-in's row its author owns moves with the rest of what they
    own, and once nobody owns it, it is listed and claimed as unowned."""
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    author = await acting_user(
        guild=admin.guild, initiative=admin.initiative, initiative_role="moderator"
    )
    await session.commit()
    seat = await acting_user(guild=author.guild, guild_role=CommunityRole.superadmin)
    await install_tool_plugin(client, session, seat)
    mine = await reading_as(author.user.id, author.guild.id)
    tools, group, _counter = await add_counter(
        mine, author.guild.id, author.initiative.id
    )
    tool = tools.installed[0]
    await route_session_to_guild(session, author.guild.id)

    owned = await ownership_service.summarize_owned_content(session, author.user.id)
    assert (tool.kind, group) in {(i.tool.kind, i.id) for i in owned}
    moved = await ownership_service.transfer_content_ownership(
        session,
        from_user_id=author.user.id,
        to=ownership_service.Owner(user_id=admin.user.id),
    )
    assert {t.kind: n for t, n in moved.items()} == {tool.kind: 1}
    grant = await _owner_grant(session, tool, group)
    assert grant is not None and grant.user_id == admin.user.id

    own = tool.table
    row = (
        await session.exec(
            select(own.c.id, own.c.initiative_id).where(own.c.id == group)
        )
    ).one()
    await ownership_service.set_resource_owner(
        session, tool=tool, row=row, new_owner=None
    )
    unowned = await ownership_service.summarize_unowned_content(
        session, guild_id=author.guild.id
    )
    assert (tool.kind, group) in {(i.tool.kind, i.id) for i in unowned}
    claimed = await ownership_service.claim_unowned_content(
        session,
        guild_id=author.guild.id,
        to=ownership_service.Owner(user_id=author.user.id),
    )
    assert {t.kind: n for t, n in claimed.items()}.get(tool.kind) == 1
    await session.commit()
    grant = await _owner_grant(session, tool, group)
    assert grant is not None and grant.user_id == author.user.id
