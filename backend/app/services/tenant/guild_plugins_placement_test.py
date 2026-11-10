"""Where an installed plug-in appears: ``plugin_placements`` rows.

Placement is one row per (install, initiative): where the plug-in appears. Who
reaches it there is the initiative's roles' answer. These tests hold the
service helpers that read and write placements, the decision behind opening a
surface, and the export that carries both.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, ClassVar

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.guild_standing import GuildContext
from app.models.platform.guild import Guild
from app.models.tenant.initiative import InitiativeRule
from app.models.tenant.plugin_placement import PluginPlacement
from app.models.tenant.tool_layout import ToolLayout
from app.services.export.guild_sections import SectionContext, _build_plugins
from app.services.tenant.guild_plugins import (
    PlacementError,
    SurfaceAccess,
    is_placed,
    placed_initiative_ids,
    set_placed_initiatives,
    show_on_saved_layouts,
    surface_access,
)
from app.services.tenant.initiatives import get_member_role
from app.services.tenant.task_types import get_default_type
from app.testing import (
    create_guild,
    create_guild_plugin,
    create_initiative,
    create_marketplace_listing,
    create_project,
    create_user,
    marketplace_uid,
    route_session_to_guild,
)

PLACED_ID = "platform.placed"
PLACED_UID = marketplace_uid("placed")

DEFINITION = {
    "plugin_kind": "service",
    "service": {"public_id": PLACED_ID, "protocol": 1},
    "features": [],
    "default_name": "Placed plug-in",
}


async def _rows(session: AsyncSession, guild_id: int, install_id: int) -> set[int]:
    await route_session_to_guild(session, guild_id)
    rows = await session.exec(
        select(PluginPlacement).where(PluginPlacement.install_id == install_id)
    )
    return {row.initiative_id for row in rows.all()}


async def _guild_with_two_initiatives(session: AsyncSession):
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    first = await create_initiative(session, guild, user, name="First")
    second = await create_initiative(session, guild, user, name="Second")
    return user, guild, first, second


class TestSetPlacedInitiatives:
    async def test_it_places_exactly_these_and_answers_the_new_ones(
        self, session: AsyncSession
    ):
        user, guild, first, second = await _guild_with_two_initiatives(session)
        plugin = await create_guild_plugin(session, guild, user, definition=DEFINITION)

        await route_session_to_guild(session, guild.id)
        assert await set_placed_initiatives(session, plugin, {first.id}) == [first.id]
        await session.commit()
        assert await _rows(session, guild.id, plugin.id) == {first.id}

        await route_session_to_guild(session, guild.id)
        assert await set_placed_initiatives(session, plugin, {first.id, second.id}) == [
            second.id
        ]
        await session.commit()

        await route_session_to_guild(session, guild.id)
        await set_placed_initiatives(session, plugin, {second.id})
        await session.commit()
        assert await _rows(session, guild.id, plugin.id) == {second.id}

        await route_session_to_guild(session, guild.id)
        await set_placed_initiatives(session, plugin, set())
        await session.commit()
        assert await _rows(session, guild.id, plugin.id) == set()

        # None is every initiative there is: what installing a mandatory
        # plug-in does.
        await route_session_to_guild(session, guild.id)
        await set_placed_initiatives(session, plugin, None)
        await session.commit()
        assert await _rows(session, guild.id, plugin.id) == {first.id, second.id}

    async def test_it_may_only_name_this_guild_s_initiatives(
        self, session: AsyncSession
    ):
        user, guild, first, _ = await _guild_with_two_initiatives(session)
        plugin = await create_guild_plugin(session, guild, user, definition=DEFINITION)

        await route_session_to_guild(session, guild.id)
        with pytest.raises(PlacementError, match="not one of this guild"):
            await set_placed_initiatives(session, plugin, {first.id + 10_000})


class TestIsPlaced:
    async def test_it_reads_the_rows(self, session: AsyncSession):
        user, guild, first, second = await _guild_with_two_initiatives(session)
        plugin = await create_guild_plugin(session, guild, user, definition=DEFINITION)

        await route_session_to_guild(session, guild.id)
        assert await is_placed(session, plugin.id, first.id) is False
        await set_placed_initiatives(session, plugin, {first.id})
        await session.commit()

        await route_session_to_guild(session, guild.id)
        assert await is_placed(session, plugin.id, first.id) is True
        assert await is_placed(session, plugin.id, second.id) is False
        assert await placed_initiative_ids(session, plugin.id) == {first.id}

    async def test_the_guild_wide_reading_is_always_placed(self, session: AsyncSession):
        user = await create_user(session)
        guild = await create_guild(session, creator=user)
        plugin = await create_guild_plugin(session, guild, user, definition=DEFINITION)

        await route_session_to_guild(session, guild.id)
        assert await is_placed(session, plugin.id, None) is True


class TestExport:
    async def test_the_plugins_section_carries_placements_and_who_holds_what(
        self, session: AsyncSession
    ):
        await create_marketplace_listing(
            session,
            uid=PLACED_UID,
            public_id=PLACED_ID,
            kind="plugin",
            name="Placed plug-in",
            definition=DEFINITION,
        )
        user, guild, first, _ = await _guild_with_two_initiatives(session)
        plugin = await create_guild_plugin(
            session, guild, user, definition=DEFINITION, listing_uid=PLACED_UID
        )
        await route_session_to_guild(session, guild.id)
        await set_placed_initiatives(session, plugin, {first.id})
        member = await get_member_role(session, initiative_id=first.id)
        assert member is not None
        session.add(
            InitiativeRule(
                initiative_id=first.id,
                initiative_role_id=member.id,
                install_id=plugin.id,
                key="use",
                enabled=True,
            )
        )
        session.add(InitiativeRule(install_id=plugin.id, key="use", enabled=False))
        await session.commit()

        await route_session_to_guild(session, guild.id)
        built = await _build_plugins(
            SectionContext(session=session, user=user, guild_id=guild.id)
        )
        assert built is not None
        payload, count = built
        assert count == 1
        assert payload["schema_version"] == 3
        [entry] = payload["plugins"]
        assert entry["placed_initiative_ids"] == [first.id]
        assert entry["permissions"] == [
            {
                "initiative_id": first.id,
                "role": "member",
                "permission": "use",
                "enabled": True,
            },
            {
                "initiative_id": None,
                "role": None,
                "permission": "use",
                "enabled": False,
            },
        ]


class TestSurfaceAccess:
    """The one decision behind opening a surface, without a database: the
    install's permissions held as the community's own are, read off the
    reader's standing."""

    PAGE: ClassVar[dict[str, Any]] = {
        "id": "e",
        "path": "/e",
        "scopes": ["community", "initiative"],
    }
    PRICES: ClassVar[dict[str, Any]] = {**PAGE, "permission": "prices"}
    PLUGIN = SimpleNamespace(
        id=3,
        definition={
            "permissions": [
                {"id": "prices", "level": "initiative", "name": {"en": "Prices"}},
                {"id": "prices", "level": "community", "name": {"en": "Prices"}},
                {"id": "open", "level": "initiative", "members": True, "name": {}},
            ]
        },
    )

    @classmethod
    def _decide(cls, page, *, initiative_id=1, placed=True, **standing):
        return surface_access(
            cls.PLUGIN,
            page,
            context=GuildContext(
                guild=Guild(id=7, name="g"),
                user_id=11,
                guild_id=7,
                **{"member_initiatives": (1,), **standing},
            ),
            initiative_id=initiative_id,
            placed=placed,
        )

    def test_inside_an_initiative_a_role_holds_it_by_its_rule(self):
        assert self._decide(self.PAGE) is SurfaceAccess.refused
        assert self._decide(self.PAGE, plugin_grants=("1:3:use",)) is SurfaceAccess.open
        assert (
            self._decide(self.PRICES, plugin_grants=("1:3:use",))
            is SurfaceAccess.refused
        )
        # A rule in another initiative, or naming another install, is not one here.
        assert (
            self._decide(self.PAGE, plugin_grants=("2:3:use", "1:4:use"))
            is SurfaceAccess.refused
        )

    def test_with_no_rule_a_role_takes_the_plug_in_s_default(self):
        opens = {**self.PAGE, "permission": "open"}
        assert self._decide(opens) is SurfaceAccess.open
        assert self._decide(opens, plugin_denies=("1:3:open",)) is SurfaceAccess.refused
        # Not a member of the initiative: no role there to hold it.
        assert self._decide(opens, member_initiatives=()) is SurfaceAccess.refused

    def test_admins_and_the_initiative_s_managers_always_hold_it(self):
        assert self._decide(self.PRICES, guild_admin=True) is SurfaceAccess.open
        assert self._decide(self.PRICES, manager_initiatives=(1,)) is SurfaceAccess.open
        assert (
            self._decide(self.PRICES, manager_initiatives=(2,)) is SurfaceAccess.refused
        )

    def test_at_the_community_level_it_is_held_as_an_admin_surface(self):
        community = {"initiative_id": None}
        # The admin rung with no custom role holds every one.
        assert (
            self._decide(self.PRICES, **community, held_plugin_permissions=("*",))
            is SurfaceAccess.open
        )
        # A custom role keeps some.
        narrowed = ("3:use",)
        assert (
            self._decide(self.PAGE, **community, held_plugin_permissions=narrowed)
            is SurfaceAccess.open
        )
        assert (
            self._decide(self.PRICES, **community, held_plugin_permissions=narrowed)
            is SurfaceAccess.refused
        )
        # A member holds none, whatever they hold inside initiatives.
        assert (
            self._decide(
                self.PAGE, **community, plugin_grants=("1:3:use",), guild_admin=False
            )
            is SurfaceAccess.refused
        )

    def test_not_placed_or_not_rendered_here_is_not_here(self):
        assert (
            self._decide(self.PAGE, placed=False, guild_admin=True)
            is SurfaceAccess.not_here
        )
        inside_only = {**self.PAGE, "scopes": ["initiative"]}
        assert (
            self._decide(
                inside_only, initiative_id=None, held_plugin_permissions=("*",)
            )
            is SurfaceAccess.not_here
        )


def _on_items(*fields: tuple[str, str], parts: tuple[str, ...] = ()) -> dict:
    """A definition declaring fields (key, the kind of item) and task parts."""
    return {
        **DEFINITION,
        "fields": [
            {"key": key, "name": key, "kind": "text", "on": [on]} for key, on in fields
        ],
        "parts": [
            {"id": part, "name": part, "on": ["task"], "tree": {"type": "stack"}}
            for part in parts
        ],
    }


class TestShowingOnSavedDetails:
    async def test_placing_adds_its_task_fields_then_parts_to_saved_details(
        self, session: AsyncSession
    ):
        user, guild, first, second = await _guild_with_two_initiatives(session)
        project = await create_project(session, first, user)
        plugin = await create_guild_plugin(
            session,
            guild,
            user,
            definition=_on_items(
                ("build", "task"),
                ("venue", "calendar_event"),
                parts=("one", "two", "three", "four"),
            ),
        )
        await route_session_to_guild(session, guild.id)
        priority = {"type": "field", "props": {"field": "priority"}}
        layout = ToolLayout(
            initiative_id=first.id,
            tool="project",
            tool_id=project.id,
            kind="task",
            task_type_id=(await get_default_type(session, project.id)).id,
            definition={"header": [], "main": [], "side": [priority]},
        )
        session.add(layout)
        await session.commit()

        await route_session_to_guild(session, guild.id)
        await set_placed_initiatives(session, plugin, {first.id, second.id})
        await session.commit()

        await route_session_to_guild(session, guild.id)
        await session.refresh(layout)
        build = {"type": "field", "props": {"field": f"plugin:{plugin.id}:build"}}
        # Up to the parts a layout holds of one plug-in; the other initiative
        # has nothing saved, and draws them as shipped.
        assert layout.definition["side"] == [
            priority,
            build,
            *(
                {"type": "plugin", "props": {"plugin": plugin.id, "part": name}}
                for name in ("one", "two", "three")
            ),
        ]
        rows = await session.exec(
            select(ToolLayout).where(ToolLayout.initiative_id == second.id)
        )
        assert rows.all() == []

        # Taken off, a part stays off; a version adds only what is new.
        layout.definition = {**layout.definition, "side": [priority, build]}
        session.add(layout)
        await session.commit()
        previous = plugin.definition
        plugin.definition = _on_items(
            ("build", "task"), ("commit", "task"), parts=("one", "two", "three", "four")
        )
        await route_session_to_guild(session, guild.id)
        await show_on_saved_layouts(session, plugin, [first.id], previous=previous)
        await session.commit()

        await route_session_to_guild(session, guild.id)
        await session.refresh(layout)
        assert layout.definition["side"] == [
            priority,
            build,
            {"type": "field", "props": {"field": f"plugin:{plugin.id}:commit"}},
        ]

    async def test_placing_adds_its_task_fields_to_saved_boards_and_tables(
        self, session: AsyncSession
    ):
        user, guild, first, _ = await _guild_with_two_initiatives(session)
        project = await create_project(session, first, user)
        plugin = await create_guild_plugin(
            session,
            guild,
            user,
            definition=_on_items(("build", "task"), ("venue", "calendar_event")),
        )
        await route_session_to_guild(session, guild.id)
        title = {"type": "field", "props": {"field": "title"}}
        board, table, shipped = (
            ToolLayout(
                initiative_id=first.id,
                tool="project",
                tool_id=project.id,
                kind=kind,
                definition=definition,
            )
            for kind, definition in (
                ("board", {"card": {"type": "card", "children": [title]}}),
                ("table", {"columns": ["title"]}),
                ("calendar", {}),
            )
        )
        session.add_all([board, table, shipped])
        await session.commit()

        await route_session_to_guild(session, guild.id)
        await set_placed_initiatives(session, plugin, {first.id})
        await session.commit()

        await route_session_to_guild(session, guild.id)
        for layout in (board, table, shipped):
            await session.refresh(layout)
        build = f"plugin:{plugin.id}:build"
        assert board.definition["card"]["children"] == [
            title,
            {"type": "field", "props": {"field": build}},
        ]
        assert table.definition["columns"] == ["title", build]
        # What a list does not keep of its own it draws as shipped, with them.
        assert shipped.definition == {}

    async def test_placing_adds_its_event_fields_to_the_saved_event_detail(
        self, session: AsyncSession
    ):
        user, guild, first, _ = await _guild_with_two_initiatives(session)
        plugin = await create_guild_plugin(
            session,
            guild,
            user,
            definition=_on_items(("build", "task"), ("venue", "calendar_event")),
        )
        await route_session_to_guild(session, guild.id)
        layout = ToolLayout(
            initiative_id=first.id,
            tool="calendar",
            tool_id=None,
            kind="calendar_event",
            definition={"header": [], "main": [], "side": []},
        )
        session.add(layout)
        await session.commit()

        await route_session_to_guild(session, guild.id)
        await set_placed_initiatives(session, plugin, {first.id})
        await session.commit()

        await route_session_to_guild(session, guild.id)
        await session.refresh(layout)
        assert layout.definition["side"] == [
            {"type": "field", "props": {"field": f"plugin:{plugin.id}:venue"}}
        ]
