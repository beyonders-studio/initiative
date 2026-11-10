"""Migration 20261110_0605: a placement's roles become each role's answer for
the plug-in's ``use``, and a stored ``admin_only`` becomes a permission members
do not hold. Loaded by path; one community's schema is taken back to the
earlier shape, given roles the earlier way, and brought forward again."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.db.pre_075_shapes_migration_test import _load, _run, _sql
from app.models.tenant.initiative import InitiativeRoleModel
from app.models.tenant.plugin_placement import PluginPlacement
from app.services.tenant.initiatives import get_member_role
from app.testing import (
    create_guild,
    create_guild_plugin,
    create_initiative,
    create_user,
    route_session_to_guild,
)

migration = _load("20261110_0605_plug_ins_answer_to_the_communitys_roles.py")


@pytest.mark.fresh_guild_schema
async def test_every_non_manager_role_keeps_its_answer(session) -> None:
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    initiative = await create_initiative(session, guild, user)
    plugin = await create_guild_plugin(session, guild, user, definition={})
    await route_session_to_guild(session, guild.id)
    session.add(PluginPlacement(install_id=plugin.id, initiative_id=initiative.id))
    custom = InitiativeRoleModel(
        initiative_id=initiative.id, name="viewer", display_name="Viewer"
    )
    session.add(custom)
    await session.commit()
    member = await get_member_role(session, initiative_id=initiative.id)
    assert member is not None
    schema = f"guild_{guild.id}"

    await session.run_sync(_run(migration._downgrade, schema))
    await _sql(
        session,
        text(
            f"UPDATE {schema}.plugin_placements SET role_ids = ARRAY[CAST(:role AS integer)]"
        ),
        {"role": member.id},
    )
    await session.run_sync(_run(migration._upgrade, schema))
    await session.commit()

    rows = (
        await _sql(
            session,
            text(
                f"SELECT r.name, x.enabled FROM {schema}.initiative_rules x"
                f" JOIN {schema}.initiative_roles r ON r.id = x.initiative_role_id"
                " WHERE x.install_id = :install AND x.key = 'use'"
            ),
            {"install": plugin.id},
        )
    ).all()
    # The managers hold it whatever a row says, so they get none.
    assert dict(rows) == {"member": True, "viewer": False}


def test_admin_only_names_a_permission_members_do_not_hold() -> None:
    earlier = {
        "pages": [
            {"id": "settings", "scopes": ["community"], "admin_only": True},
            {"id": "board", "scopes": ["community", "initiative"], "admin_only": True},
            {"id": "open", "scopes": ["initiative"], "admin_only": False},
        ],
        "actions": [{"id": "close", "admin_only": True}],
        "endpoints": [{"id": "report", "admin_only": False}],
    }
    named = migration._named(earlier)
    assert named == {
        "pages": [
            {"id": "settings", "scopes": ["community"]},
            {
                "id": "board",
                "scopes": ["community", "initiative"],
                "permission": "admin_only",
            },
            {"id": "open", "scopes": ["initiative"]},
        ],
        "actions": [{"id": "close", "permission": "admin_only"}],
        "endpoints": [{"id": "report"}],
        "permissions": [
            {"id": "admin_only", "name": {"en": "Admins only"}, "level": "community"},
            {"id": "admin_only", "name": {"en": "Admins only"}, "level": "initiative"},
        ],
    }
    assert migration._named(named) is None
    assert migration._unnamed(named) == {
        "pages": [
            {"id": "settings", "scopes": ["community"]},
            {"id": "board", "scopes": ["community", "initiative"], "admin_only": True},
            {"id": "open", "scopes": ["initiative"]},
        ],
        "actions": [{"id": "close", "admin_only": True}],
        "endpoints": [{"id": "report"}],
    }
