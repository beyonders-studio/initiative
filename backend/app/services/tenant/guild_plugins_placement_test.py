"""Where an installed plug-in appears: ``plugin_placements`` rows.

Placement is one row per (install, initiative), carrying the initiative roles
allowed to open the plug-in there. These tests hold the service helpers that read
and write those rows, the trigger that places a plug-in following new
initiatives, and the export that carries them.
"""

from __future__ import annotations

from typing import Any, ClassVar

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.tenant.plugin_placement import PluginPlacement
from app.models.tenant.tool_layout import ToolLayout
from app.services.export.guild_sections import SectionContext, _build_plugins
from app.services.tenant.guild_plugins import (
    PlacementError,
    SurfaceAccess,
    is_placed,
    place_in_every_initiative,
    placed_initiative_ids,
    set_placed_initiatives,
    show_on_saved_layouts,
    surface_access,
)
from app.services.tenant.initiatives import get_moderator_role
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


async def _moderator_id(session: AsyncSession, initiative_id: int) -> int:
    role = await get_moderator_role(session, initiative_id=initiative_id)
    assert role is not None and role.id is not None
    return role.id


async def _rows(session: AsyncSession, guild_id: int, install_id: int) -> dict:
    await route_session_to_guild(session, guild_id)
    rows = await session.exec(
        select(PluginPlacement).where(PluginPlacement.install_id == install_id)
    )
    return {row.initiative_id: list(row.role_ids) for row in rows.all()}


async def _guild_with_two_initiatives(session: AsyncSession):
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    first = await create_initiative(session, guild, user, name="First")
    second = await create_initiative(session, guild, user, name="Second")
    return user, guild, first, second


class TestSetPlacedInitiatives:
    async def test_a_new_placement_starts_with_the_moderator_role(
        self, session: AsyncSession
    ):
        user, guild, first, _ = await _guild_with_two_initiatives(session)
        plugin = await create_guild_plugin(session, guild, user, definition=DEFINITION)

        await route_session_to_guild(session, guild.id)
        await set_placed_initiatives(session, plugin, {first.id})
        await session.commit()

        assert await _rows(session, guild.id, plugin.id) == {
            first.id: [await _moderator_id(session, first.id)]
        }

    async def test_a_kept_placement_keeps_its_roles_and_a_dropped_one_goes(
        self, session: AsyncSession
    ):
        user, guild, first, second = await _guild_with_two_initiatives(session)
        plugin = await create_guild_plugin(session, guild, user, definition=DEFINITION)

        await route_session_to_guild(session, guild.id)
        await set_placed_initiatives(session, plugin, {first.id})
        row = (
            await session.exec(
                select(PluginPlacement).where(PluginPlacement.install_id == plugin.id)
            )
        ).one()
        row.role_ids = [123_456]
        session.add(row)
        await session.commit()

        await route_session_to_guild(session, guild.id)
        await set_placed_initiatives(session, plugin, {first.id, second.id})
        await session.commit()
        assert await _rows(session, guild.id, plugin.id) == {
            first.id: [123_456],
            second.id: [await _moderator_id(session, second.id)],
        }

        await route_session_to_guild(session, guild.id)
        await set_placed_initiatives(session, plugin, {second.id})
        await session.commit()
        assert set(await _rows(session, guild.id, plugin.id)) == {second.id}

        await route_session_to_guild(session, guild.id)
        await set_placed_initiatives(session, plugin, set())
        await session.commit()
        assert await _rows(session, guild.id, plugin.id) == {}

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


class TestPlaceInEveryInitiative:
    async def test_place_in_every_initiative_covers_the_existing_ones(
        self, session: AsyncSession
    ):
        user, guild, first, second = await _guild_with_two_initiatives(session)
        plugin = await create_guild_plugin(session, guild, user, definition=DEFINITION)

        await route_session_to_guild(session, guild.id)
        await place_in_every_initiative(session, plugin)
        await session.commit()

        assert await _rows(session, guild.id, plugin.id) == {
            first.id: [await _moderator_id(session, first.id)],
            second.id: [await _moderator_id(session, second.id)],
        }


class TestExport:
    async def test_the_plugins_section_carries_each_install_s_placements(
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
        await session.commit()

        await route_session_to_guild(session, guild.id)
        built = await _build_plugins(
            SectionContext(session=session, user=user, guild_id=guild.id)
        )
        assert built is not None
        payload, count = built
        assert count == 1
        assert payload["schema_version"] == 2
        [entry] = payload["plugins"]
        assert "placement" not in entry
        assert entry["placements"] == [
            {
                "initiative_id": first.id,
                "role_ids": [await _moderator_id(session, first.id)],
            }
        ]


class TestSurfaceAccess:
    """The one decision behind opening a surface, without a database."""

    PAGE: ClassVar[dict[str, Any]] = {
        "id": "e",
        "path": "/e",
        "scopes": ["community", "initiative"],
    }
    ADMIN_ONLY: ClassVar[dict[str, Any]] = {**PAGE, "admin_only": True}

    @staticmethod
    def _decide(page, *, initiative_id=1, roles=(10,), admin=False, held=(10,)):
        return surface_access(
            page,
            initiative_id=initiative_id,
            placement_role_ids=roles,
            is_guild_admin=admin,
            member_role_ids=held,
        )

    def test_a_role_the_placement_allows_opens_it(self):
        assert self._decide(self.PAGE) is SurfaceAccess.open

    def test_a_role_it_does_not_allow_is_refused(self):
        assert self._decide(self.PAGE, held=(11,)) is SurfaceAccess.refused

    def test_not_placed_is_not_here_even_for_an_admin(self):
        for admin in (False, True):
            assert (
                self._decide(self.PAGE, roles=None, admin=admin)
                is SurfaceAccess.not_here
            )

    def test_the_community_level_is_for_admins(self):
        assert (
            self._decide(self.PAGE, initiative_id=None, roles=None)
            is SurfaceAccess.refused
        )
        assert (
            self._decide(self.PAGE, initiative_id=None, roles=None, admin=True)
            is SurfaceAccess.open
        )

    def test_admin_only_outranks_the_roles(self):
        assert self._decide(self.ADMIN_ONLY) is SurfaceAccess.refused
        assert self._decide(self.ADMIN_ONLY, admin=True) is SurfaceAccess.open

    def test_a_surface_that_does_not_render_here_is_not_here(self):
        inside_only = {**self.PAGE, "scopes": ["initiative"]}
        assert (
            self._decide(inside_only, initiative_id=None, roles=None, admin=True)
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
