"""Initiatives: each community's default initiative, provisioned the way the
app does it, and the campaigns the rest of its content hangs off."""

from __future__ import annotations

from sqlalchemy import update
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import Tool
from app.models.platform.user import User
from app.models.tenant.initiative import (
    Initiative,
    InitiativeJoinPolicy,
    InitiativeMember,
    InitiativeRoleModel,
    InitiativeRolePermission,
)
from app.services.tenant.initiatives import create_builtin_roles, creator_role

from seed.common import Community

#: What the seeder calls the initiative it hangs each community's content
#: off. Nothing in the app knows this name — it is the seeder's own.
SEED_INITIATIVE_NAME = "Default Initiative"
SEED_INITIATIVE_COLOR = "#2563eb"

_SMALL_KIT = (Tool.queue, Tool.counter_group, Tool.calendar, Tool.wiki)

#: Who makes each community's default initiative, and who else is in it on
#: which built-in role.
DEFAULTS: dict[str, tuple[str, list[tuple[str, str]]]] = {
    "primary": ("Admin User", [("Dungeon Master", "project_manager")]),
    "starforge": (
        "Admin User",
        [("Finley Goldtongue", "member"), ("Kael Windrunner", "member")],
    ),
    # finley must be a member here: he owns the Campaign Notes project in this
    # initiative, and a DAC owner grant is useless without passing the
    # initiative gate first.
    "tides": (
        "Harbormaster Marisol",
        [
            ("Admin User", "member"),
            ("Dungeon Master", "member"),
            ("Finley Goldtongue", "member"),
        ],
    ),
}

#: The campaigns, keyed by the short name the other areas' tables use.
#: ``tools`` are switched on for the initiative and ``member_tools`` (default:
#: the same) for its member role, which is what lets a non-PM member see the
#: seeded content.
INITIATIVES: dict[str, dict[str, dict]] = {
    "primary": {
        "strahd": {
            "name": "Campaign: Curse of Strahd",
            "description": "A gothic horror adventure in the demiplane of Barovia",
            "color": "#7C3AED",
            "pm": "Dungeon Master",
            "members": [
                "Thorn Ironforge",
                "Elara Moonwhisper",
                "Vex Shadowstep",
                "Seraphina Dawnlight",
                "Platform Operator",
            ],
            # Invite-only on purpose: kael is in the community and in no
            # initiative, which is the view that has to come back empty.
            "join_policy": InitiativeJoinPolicy.private,
            "tools": tuple(Tool),
        },
        "lmop": {
            "name": "Campaign: Lost Mine of Phandelver",
            "description": "A classic introductory adventure in the Sword Coast",
            "color": "#059669",
            "pm": "Admin User",
            "members": [
                "Dungeon Master",
                "Thorn Ironforge",
                "Elara Moonwhisper",
                "Platform Support",
            ],
            "join_policy": InitiativeJoinPolicy.request,
            "tools": tuple(Tool),
        },
    },
    "starforge": {
        "starfall": {
            "name": "Starfall: The Exodus Protocol",
            "description": "Humanity's last fleet searches for a new homeworld after Earth's collapse",
            "color": "#0EA5E9",
            "pm": "Admin User",
            "members": [
                "Finley Goldtongue",
                "Kael Windrunner",
                "Aurelia Brightshield",
                "Vex Shadowstep",
                "Elara Moonwhisper",
                "Platform Member",
            ],
            "join_policy": InitiativeJoinPolicy.open,
            "tools": (*_SMALL_KIT, Tool.dashboard, Tool.library),
        },
        "fringe": {
            "name": "Side Missions: Fringe Space",
            "description": "One-shots and side adventures in the frontier sectors",
            "color": "#F59E0B",
            "pm": "Finley Goldtongue",
            "members": [
                "Kael Windrunner",
                "Aurelia Brightshield",
                "Vex Shadowstep",
                "Platform Moderator",
            ],
            "join_policy": InitiativeJoinPolicy.request,
            "tools": _SMALL_KIT,
            "member_tools": (Tool.counter_group, Tool.calendar, Tool.wiki),
        },
    },
    "tides": {
        "crimson": {
            "name": "The Crimson Tide Campaign",
            "description": "A pirate crew sails the Shattered Seas in search of the Leviathan's Heart",
            "color": "#DC2626",
            "pm": "Finley Goldtongue",
            "members": [
                "Admin User",
                "Dungeon Master",
                "Thorn Ironforge",
                "Kael Windrunner",
                "Aurelia Brightshield",
                "Seraphina Dawnlight",
                "Platform Owner",
            ],
            "join_policy": InitiativeJoinPolicy.open,
            "auto_join": True,
            "tools": (*_SMALL_KIT, Tool.dashboard, Tool.library),
        },
        "navy": {
            "name": "Royal Navy Conflicts",
            "description": "Encounters and battles with the Imperial Navy",
            "color": "#1E40AF",
            "pm": "Dungeon Master",
            "members": [
                "Finley Goldtongue",
                "Thorn Ironforge",
                "Kael Windrunner",
                "Platform Operator",
            ],
            "join_policy": InitiativeJoinPolicy.private,
            "tools": _SMALL_KIT,
            "member_tools": (Tool.counter_group, Tool.calendar, Tool.wiki),
        },
    },
}


async def seed(c: Community) -> None:
    creator, others = DEFAULTS[c.key]
    default = await seed_initiative(c.session, c.users[creator], guild_id=c.guild.id)
    c.initiatives["default"] = default
    c.ids["initiatives"].append(default.id)
    for name, role_name in others:
        role = (
            await c.session.exec(
                select(InitiativeRoleModel).where(
                    InitiativeRoleModel.initiative_id == default.id,
                    InitiativeRoleModel.name == role_name,
                )
            )
        ).one()
        c.session.add(
            InitiativeMember(
                initiative_id=default.id, user_id=c.users[name].id, role_id=role.id
            )
        )
    await c.session.flush()
    for key, d in INITIATIVES[c.key].items():
        await create_initiative(c, key, d)


async def seed_initiative(
    session: AsyncSession,
    creator: User,
    *,
    guild_id: int,
    name: str = SEED_INITIATIVE_NAME,
) -> Initiative:
    """An initiative for a demo community, provisioned the way the app does it.

    The same sequence as ``POST /initiatives``: the row, its built-in roles,
    then the creator joined on whichever built-in role ``creator_role`` gives
    them. A guild admin lands on moderator, which is what these seeded
    communities want.

    Looked up by name first so the seeder can be re-run against a community it
    already populated — including the case where a startup back-fill created
    ``guild_<id>``'s empty tables and left no initiative in them.
    """
    existing = (
        await session.exec(select(Initiative).where(Initiative.name == name))
    ).one_or_none()
    if existing is not None:
        await session.refresh(existing, attribute_names=["memberships"])
        return existing

    initiative = Initiative(
        name=name,
        description="Seeded by scripts/seed_dev_data.py",
        color=SEED_INITIATIVE_COLOR,
    )
    session.add(initiative)
    await session.flush()

    roles = await create_builtin_roles(session, initiative_id=initiative.id)
    role = await creator_role(
        session, guild_id=guild_id, user_id=creator.id, roles=roles
    )
    session.add(
        InitiativeMember(
            initiative_id=initiative.id,
            user_id=creator.id,
            role_id=role.id,
        )
    )
    await session.flush()
    await session.refresh(initiative, attribute_names=["memberships"])
    return initiative


async def create_initiative(c: Community, key: str, d: dict) -> Initiative:
    """An initiative with its built-in roles, its PM and its members.

    ``join_policy`` decides how a community member without a membership row
    gets one: ``private`` is invite-only, ``request`` puts them in the
    manager's queue, ``open`` is one click. ``auto_join`` enrols every new
    arrival and the check constraint only allows it on an ``open`` one. Tools
    not named keep the model's own default.
    """
    tools = d.get("tools", ())
    initiative = Initiative(
        name=d["name"],
        description=d["description"],
        color=d["color"],
        join_policy=d.get("join_policy", InitiativeJoinPolicy.private).value,
        auto_join=d.get("auto_join", False),
        **{tool.view_permission: True for tool in tools},
    )
    c.session.add(initiative)
    await c.session.flush()
    c.ids["initiatives"].append(initiative.id)

    roles = await create_builtin_roles(c.session, initiative_id=initiative.id)
    member_role = roles["member"]
    c.session.add(
        InitiativeMember(
            initiative_id=initiative.id,
            user_id=c.users[d["pm"]].id,
            role_id=roles["project_manager"].id,
        )
    )
    for name in d.get("members", ()):
        c.session.add(
            InitiativeMember(
                initiative_id=initiative.id,
                user_id=c.users[name].id,
                role_id=member_role.id,
            )
        )
    # Built-in member roles start with the view keys off.
    member_tools = d.get("member_tools", tools)
    if member_tools:
        await c.session.exec(
            update(InitiativeRolePermission)
            .where(
                InitiativeRolePermission.initiative_role_id == member_role.id,
                InitiativeRolePermission.permission_key.in_(
                    [tool.view_permission for tool in member_tools]
                ),
            )
            .values(enabled=True)
        )
    await c.session.flush()
    c.initiatives[key] = initiative
    c.member_roles[key] = member_role
    return initiative
