import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import SharingMessages
from app.models.tenant.guild_plugin import GuildPlugin
from app.models.tenant.project import Project
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.schemas.tenant.resource_grant import ResourceGrantSchema
from app.services import permissions as permissions_service
from app.testing import (
    create_guild,
    create_guild_plugin,
    create_initiative,
    create_project,
    create_user,
    route_session_to_guild,
)

_SERVICE_DEFINITION = {
    "plugin_kind": "service",
    "service": {"public_id": "tests.plugin"},
}


async def test_grants_polymorphic_relationship_loads(session: AsyncSession):
    """The viewonly grants relationship returns only this resource's grants."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    initiative = await create_initiative(session, guild, user)
    project = await create_project(session, initiative, user)
    other = await create_project(session, initiative, user, name="Other")

    # create_project already seeded an owner user-grant on BOTH projects (one grant
    # per user per resource). `other`'s grant is itself a cross-resource_id decoy.
    # Add a same-id, different-resource_type decoy that must also be excluded.
    session.add(
        ResourceGrant(
            initiative_id=initiative.id,
            resource_type="file",
            resource_id=project.id,
            user_id=user.id,
            level=ResourceAccessLevel.read,
        )
    )
    await session.commit()

    loaded = (
        await session.exec(
            select(Project)
            .where(Project.id == project.id)
            .options(selectinload(Project.grants))
        )
    ).one()
    # Only this project's grants: the factory's owner grant, neither decoy
    # (not `other`'s project grant, not the same-id file grant).
    assert all(
        g.resource_type == "project" and g.resource_id == project.id
        for g in loaded.grants
    )
    assert all(g.resource_id != other.id for g in loaded.grants)
    assert any(
        g.user_id == user.id and g.level == ResourceAccessLevel.owner
        for g in loaded.grants
    )


async def _project_and_install(session: AsyncSession):
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    initiative = await create_initiative(session, guild, user)
    project = await create_project(session, initiative, user)
    install = await create_guild_plugin(
        session, guild, user, definition=_SERVICE_DEFINITION
    )
    await route_session_to_guild(session, guild.id)
    return user, guild, initiative, project, install


def _install_grant(
    project: Project, install: GuildPlugin, **overrides
) -> ResourceGrant:
    return ResourceGrant(
        **{
            "initiative_id": project.initiative_id,
            "resource_type": "project",
            "resource_id": project.id,
            "plugin_install_id": install.id,
            "level": ResourceAccessLevel.write,
            **overrides,
        }
    )


async def test_a_grant_may_name_a_plugin_install_alone(session: AsyncSession):
    """An installed plug-in is a grantee kind of its own: a row naming it and
    nothing else satisfies the one-grantee check."""
    _, _, _, project, install = await _project_and_install(session)

    session.add(_install_grant(project, install))
    await session.commit()

    stored = (
        await session.exec(
            select(ResourceGrant).where(ResourceGrant.plugin_install_id == install.id)
        )
    ).one()
    assert stored.user_id is None
    assert stored.role_id is None
    assert stored.all_initiative_members is False


async def test_a_grant_naming_a_user_and_an_install_is_refused(
    session: AsyncSession,
):
    user, _, _, project, install = await _project_and_install(session)

    session.add(_install_grant(project, install, user_id=user.id))
    with pytest.raises(IntegrityError, match="resource_grants_one_grantee"):
        await session.commit()
    await session.rollback()


async def test_an_install_holds_one_grant_per_resource(session: AsyncSession):
    _, guild, _, project, install = await _project_and_install(session)

    session.add(_install_grant(project, install))
    await session.commit()
    await route_session_to_guild(session, guild.id)
    session.add(_install_grant(project, install, level=ResourceAccessLevel.read))
    with pytest.raises(IntegrityError, match="resource_grants_unique_grantee"):
        await session.commit()
    await session.rollback()


async def test_uninstalling_removes_the_installs_grants(session: AsyncSession):
    """Deleting the install row takes every grant made to it, and leaves the
    other grants on the same resource alone."""
    user, guild, _, project, install = await _project_and_install(session)
    session.add(_install_grant(project, install))
    await session.commit()

    await route_session_to_guild(session, guild.id)
    row = (
        await session.exec(select(GuildPlugin).where(GuildPlugin.id == install.id))
    ).one()
    await session.delete(row)
    await session.commit()

    await route_session_to_guild(session, guild.id)
    remaining = (
        await session.exec(
            select(ResourceGrant).where(
                ResourceGrant.resource_type == "project",
                ResourceGrant.resource_id == project.id,
            )
        )
    ).all()
    assert all(g.plugin_install_id is None for g in remaining)
    # The owner grant the factory made is still there.
    assert any(
        g.user_id == user.id and g.level == ResourceAccessLevel.owner for g in remaining
    )


async def test_saving_the_sharing_panel_keeps_an_installs_grant(
    session: AsyncSession,
):
    """The panel's list rebuilds the people and roles a resource is shared
    with. An install's grant is not in that list and stays as it was, and the
    grants a resource reports include it."""
    user, guild, initiative, project, install = await _project_and_install(session)
    session.add(_install_grant(project, install))
    await session.commit()

    await route_session_to_guild(session, guild.id)
    await permissions_service.replace_resource_grants(
        session,
        resource_type="project",
        resource_id=project.id,
        guild_id=guild.id,
        initiative_id=initiative.id,
        owner_id=user.id,
        grants=[ResourceGrantSchema(all_initiative_members=True, level="read")],
    )
    await session.commit()

    await route_session_to_guild(session, guild.id)
    loaded = (
        await session.exec(
            select(Project)
            .where(Project.id == project.id)
            .options(selectinload(Project.grants))
        )
    ).one()
    reported = permissions_service.serialize_grants(loaded, context=None)
    assert any(
        g.plugin_install_id == install.id and g.level == "write" for g in reported
    )
    assert any(g.all_initiative_members for g in reported)


async def test_the_sharing_panel_cannot_grant_an_install(session: AsyncSession):
    user, guild, initiative, project, install = await _project_and_install(session)

    with pytest.raises(HTTPException) as excinfo:
        await permissions_service.replace_resource_grants(
            session,
            resource_type="project",
            resource_id=project.id,
            guild_id=guild.id,
            initiative_id=initiative.id,
            owner_id=user.id,
            grants=[ResourceGrantSchema(plugin_install_id=install.id, level="write")],
        )
    assert excinfo.value.status_code == 422
    assert excinfo.value.detail == SharingMessages.PLUGIN_INSTALL_GRANT_NOT_SET_HERE


def test_the_grant_shape_counts_an_install_as_a_grantee():
    assert ResourceGrantSchema(plugin_install_id=3, level="read").plugin_install_id == 3
    with pytest.raises(ValueError):
        ResourceGrantSchema(plugin_install_id=3, user_id=4, level="read")
