"""Ownership: what it is, where it lives, and what happens when someone leaves."""

from sqlmodel import select

from app.core.tools import Tool
from app.models.tenant._mixins import CreatedByMixin
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.services.tenant import ownership as ownership_service
from app.services.tenant import initiatives as initiatives_service
from app.testing import (
    create_resource_grant,
    TOOL_FACTORIES,
    create_guild,
    create_guild_membership,
    create_initiative,
    create_initiative_member,
    create_user,
    route_session_to_guild,
)
from app.models.platform.guild import GuildMembership, CommunityRole


# ── Invariants over the Tool enum ───────────────────────────────────────────


def test_every_tool_is_ownable():
    """A tool is a thing someone can own, so every Tool needs an entry here.

    Fails naming the newcomer rather than letting it ship with ownership that
    silently does nothing.
    """
    missing = set(Tool) - set(ownership_service.OWNABLE)
    extra = set(ownership_service.OWNABLE) - set(Tool)
    assert not missing, (
        f"tools with no OWNABLE entry: {sorted(t.value for t in missing)}"
    )
    assert not extra, f"OWNABLE entries that are not tools: {extra}"


def test_no_tool_has_an_owner_column():
    """Ownership is recorded in ``resource_grants`` and nowhere else.

    A second copy on the model is what let "the owner" drift from the answer
    access control actually reads, so no tool table may reintroduce one. The
    ``created_by`` column is a different fact and stays.
    """
    for tool, spec in ownership_service.OWNABLE.items():
        columns = set(spec.model.__table__.columns.keys())
        assert "owner_id" not in columns, (
            f"{tool.value} carries an owner_id column; ownership belongs in "
            f"resource_grants so there is one record of it"
        )


def test_every_tool_records_an_author():
    """Ownership can move; authorship cannot — so every tool must record one.

    It is what the restore fallback hands content back to, and what erasure
    sweeps. ``CreatedByMixin`` supplies it; a tool that skipped the mixin would
    silently drop out of both.
    """
    for tool, spec in ownership_service.OWNABLE.items():
        assert issubclass(spec.model, CreatedByMixin), (
            f"{tool.value} does not carry CreatedByMixin, so it records no author"
        )


def test_ownership_can_always_be_absent():
    """Every tool must be able to have no owner at all.

    Nobody inherits a departing member's content, so "unowned" is an ordinary
    state — a tool that could not express it would strand content the moment
    someone left.
    """
    grant_columns = ResourceGrant.__table__.columns
    assert grant_columns["user_id"].nullable, (
        "resource_grants.user_id must stay nullable — a resource with no owner "
        "is the absence of an owner row, not a row pointing at nobody"
    )


def test_one_owner_per_resource_is_enforced_in_the_schema():
    """A resource has one owner or none, and the schema says so."""
    index = next(
        (
            i
            for i in ResourceGrant.__table__.indexes
            if i.name == "ix_resource_grants_single_owner"
        ),
        None,
    )
    assert index is not None, "the single-owner index is missing"
    assert index.unique
    assert [c.name for c in index.columns] == ["resource_type", "resource_id"]


def test_a_grantee_holds_one_grant_per_resource():
    """One row per grantee, whatever level it is at.

    This is what makes stepping an owner row down to ``write`` safe without
    looking for a second row to merge it into: there cannot be one.
    """
    from sqlalchemy import UniqueConstraint

    constraint = next(
        (
            c
            for c in ResourceGrant.__table__.constraints
            if isinstance(c, UniqueConstraint)
            and c.name == "resource_grants_unique_grantee"
        ),
        None,
    )
    assert constraint is not None, "the unique-grantee constraint is missing"
    assert [c.name for c in constraint.columns] == [
        "resource_type",
        "resource_id",
        "user_id",
        "role_id",
        "plugin_install_id",
    ]


# ── Behaviour ───────────────────────────────────────────────────────────────


async def _owner_grant(session, tool: Tool, resource_id: int):
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


async def test_departure_leaves_every_tool_unowned(session):
    """Leaving the guild releases ownership rather than handing it on."""
    admin = await create_user(session)
    guild = await create_guild(session, creator=admin)
    leaver = await create_user(session)
    await create_guild_membership(session, leaver, guild, CommunityRole.member)
    initiative = await create_initiative(session, guild, admin)
    await create_initiative_member(session, initiative, leaver, "project_manager")

    rows = await _one_of_every_tool(session, initiative, leaver)

    await initiatives_service.remove_user_from_guild_initiatives(
        session, guild_id=guild.id, user_id=leaver.id
    )
    await session.commit()

    await route_session_to_guild(session, guild.id)
    for tool, row in rows.items():
        assert await _owner_grant(session, tool, row.id) is None, (
            f"{tool.value} still has an owner after its owner left the guild"
        )


async def test_departure_does_not_touch_authorship(session):
    """The author wrote it; leaving does not change who did."""
    admin = await create_user(session)
    guild = await create_guild(session, creator=admin)
    leaver = await create_user(session)
    await create_guild_membership(session, leaver, guild, CommunityRole.member)
    initiative = await create_initiative(session, guild, admin)
    await create_initiative_member(session, initiative, leaver, "project_manager")

    rows = await _one_of_every_tool(session, initiative, leaver)
    authors = {tool: row.created_by for tool, row in rows.items()}

    await initiatives_service.remove_user_from_guild_initiatives(
        session, guild_id=guild.id, user_id=leaver.id
    )
    await session.commit()

    await route_session_to_guild(session, guild.id)
    for tool, expected in authors.items():
        await session.refresh(rows[tool])
        assert rows[tool].created_by == expected, (
            f"{tool.value} authorship changed on departure"
        )


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

    assert set(counts) == set(Tool)
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
    orphaned = await TOOL_FACTORIES[Tool.counter_group](session, initiative, leaver)

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
    found = {(i.tool, i.id) for i in items}
    assert (Tool.project, released.id) in found
    assert (Tool.counter_group, orphaned.id) in found


async def test_restore_gives_content_back_to_a_present_author(session):
    """Restoring unowned content hands it to its author, if they are still here."""
    admin = await create_user(session)
    guild = await create_guild(session, creator=admin)
    author = await create_user(session)
    await create_guild_membership(session, author, guild, CommunityRole.member)
    initiative = await create_initiative(session, guild, admin)
    await create_initiative_member(session, initiative, author, "project_manager")

    file = await TOOL_FACTORIES[Tool.file](session, initiative, author)

    await route_session_to_guild(session, guild.id)
    await ownership_service.set_resource_owner(
        session, tool=Tool.file, row=file, new_owner=None
    )
    await session.commit()

    claimed = await ownership_service.restore_ownership_to_author(
        session, row=file, guild_id=guild.id
    )
    await session.commit()

    assert claimed is True
    grant = await _owner_grant(session, Tool.file, file.id)
    assert grant is not None and grant.user_id == author.id


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


async def test_a_projects_author_gets_it_back_on_restore(session):
    """Projects record an author too, so the restore fallback reaches them."""
    admin = await create_user(session)
    guild = await create_guild(session, creator=admin)
    author = await create_user(session)
    await create_guild_membership(session, author, guild, CommunityRole.member)
    initiative = await create_initiative(session, guild, admin)
    await create_initiative_member(session, initiative, author, "project_manager")

    project = await TOOL_FACTORIES[Tool.project](session, initiative, author)

    await route_session_to_guild(session, guild.id)
    project.created_by = author.id
    session.add(project)
    await ownership_service.set_resource_owner(
        session, tool=Tool.project, row=project, new_owner=None
    )
    await session.commit()

    claimed = await ownership_service.restore_ownership_to_author(
        session, row=project, guild_id=guild.id
    )
    await session.commit()

    assert claimed is True
    grant = await _owner_grant(session, Tool.project, project.id)
    assert grant is not None and grant.user_id == author.id


async def test_general_access_does_not_displace_the_owner(session):
    """Sharing with the whole initiative leaves the owner grant standing.

    General access is an all-members row at read/write; the owner is a separate
    user row at ``owner``. Rebuilding a resource's sharing replaces the first
    and preserves the second, so opening something up never leaves it ownerless.
    """
    from app.services import permissions as permissions_service
    from app.schemas.tenant.resource_grant import ResourceGrantSchema

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
    owner collide with it and the claim fail outright.
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
    assert (Tool.calendar, calendar.id) in {(i.tool, i.id) for i in items}

    counts = await ownership_service.claim_unowned_content(
        session, guild_id=guild.id, to=ownership_service.Owner(user_id=admin.id)
    )
    await session.commit()

    assert counts.get(Tool.calendar) == 1
    grant = await _owner_grant(session, Tool.calendar, calendar.id)
    assert grant is not None and grant.user_id == admin.id


async def test_claiming_leaves_the_role_able_to_edit(session):
    """The role that held the owner row keeps write, not nothing.

    Its grant was never visible in the sharing panel, so dropping it would take
    editing away from people with no record of why.
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
    await ownership_service.claim_unowned_content(
        session, guild_id=guild.id, to=ownership_service.Owner(user_id=admin.id)
    )
    await session.commit()

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
