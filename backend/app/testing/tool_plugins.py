"""Counters, the tool plug-in this build's catalogue ships, as a manifest a
test registers, and the helpers that install it."""

from __future__ import annotations

import copy
import json
from functools import cache
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from httpx import AsyncClient
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.core.tool_set import ToolSet
    from app.testing.actor import Actor

__all__ = [
    "COUNTERS_UID",
    "add_counter",
    "convert_counters",
    "counters_conversion",
    "counters_follow_up",
    "counters_tool_manifest",
    "install_counters",
    "install_tool_plugin",
    "run_as_a_revision",
]

#: The uid the catalogue ships Counters under.
COUNTERS_UID = "TSJVTCM0S7GV2X"


@cache
def _catalogued() -> dict[str, Any]:
    from app.services.marketplace.builtin import CATALOG_DIR

    with (CATALOG_DIR / "core.counters.json").open(encoding="utf-8") as handle:
        return json.load(handle)["definition"]


def counters_tool_manifest() -> dict[str, Any]:
    """A fresh copy of the Counters tool plug-in's definition, as this build's
    catalogue ships it (``core.counters``)."""
    return copy.deepcopy(_catalogued())


async def install_tool_plugin(
    client: AsyncClient,
    session: AsyncSession,
    seat: Actor,
    *,
    uid: str = COUNTERS_UID,
    definition: dict[str, Any] | None = None,
    placements: str | list[int] = "all",
) -> dict[str, Any]:
    """List a tool plug-in (Counters unless ``definition`` says otherwise),
    give its kinds their codes as registering it does, and install it as
    ``seat``, the community's seat, placed in ``placements`` (every
    initiative there is, as the install dialog offers first). Returns the
    install as the API reads it.
    ``session`` is committed first, so it holds nothing the provisioning of
    the tool's tables waits on."""
    from app.db.kind_codes import assign_plugin_kind_codes
    from app.services.marketplace.tool_plugins import (
        normalize_tool_plugin_definition,
        tool_kinds,
    )
    from app.testing.factories import create_marketplace_listing

    declared = normalize_tool_plugin_definition(definition or counters_tool_manifest())
    await create_marketplace_listing(
        session,
        uid=uid,
        public_id=f"test.{uid.lower()}",
        kind="plugin",
        name=declared["default_name"],
        definition=declared,
    )
    await assign_plugin_kind_codes(session, tool_kinds(declared, listing_uid=uid))
    await session.commit()
    response = await client.post(
        seat.g("/plugins/"),
        headers=seat.headers,
        json={"listing_uid": uid, "placements": placements},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def install_counters(
    session: AsyncSession, guild_id: int, installer_id: int, placements: set[int]
) -> ToolSet:
    """Install the Counters this build's catalogue ships (``core.counters``)
    in ``guild_id`` as ``installer_id``, its seat, through the service the
    marketplace's install calls, placed in ``placements``; then make its
    tables and switch it on in every initiative, as the install route does
    once the install commits. Returns the community's tools. Committed."""
    from app.db.schema_provisioning import provision_community_tools
    from app.services.marketplace import catalog as catalog_service
    from app.services.marketplace.installs import resolve_listing_install
    from app.services.tenant import guild_plugins as guild_plugins_service
    from app.services.tenant.initiative_tools import write_installed_tools
    from app.testing.schema_harness import route_session_to_guild

    await route_session_to_guild(session, guild_id)
    found = await catalog_service.get_listing(session, "core.counters")
    assert found is not None, "core.counters is not in the catalogue"
    listing, version = await resolve_listing_install(session, found.uid, kind="plugin")
    definition = dict(version.definition)
    plugin = await guild_plugins_service.install_plugin(
        session,
        listing_uid=listing.uid,
        listing_version=version.version,
        definition=definition,
        guild_id=guild_id,
        name=definition["default_name"],
        created_by=installer_id,
        actor_user_id=installer_id,
    )
    await guild_plugins_service.set_placed_initiatives(session, plugin, placements)
    await session.commit()
    tools = await provision_community_tools(guild_id)
    await route_session_to_guild(session, guild_id)
    await write_installed_tools(session, tools)
    await session.commit()
    return tools


async def add_counter(
    session: AsyncSession, guild_id: int, initiative_id: int, **counter: Any
) -> tuple[ToolSet, int, int]:
    """A counter group of the installed Counters in ``initiative_id``, and a
    counter in it with ``counter``'s columns: the community's tool set, the
    group's id and the counter's id. Added on ``session`` as it is routed (a
    request's, whose person then makes and owns them), or routed into the
    community where it is not. Committed."""
    from app.db.plugin_tools import provisioned_tools
    from app.db.session import routed_guild_id
    from app.services.tenant.plugin_tool_rows import insert
    from app.testing.schema_harness import route_session_to_guild

    tools = await provisioned_tools(guild_id)
    (tool,) = tools.installed
    if routed_guild_id(session) is None:
        await route_session_to_guild(session, guild_id)
    group = await insert(
        session, tool.table, {"initiative_id": initiative_id, "name": "Scores"}
    )
    row = await insert(
        session,
        tool.items[0],
        {"counter_group_id": group, "name": "Laps", **counter},
    )
    await session.commit()
    return tools, group, row


#: The revision that turns the built-in Counters into its plug-in, and the one
#: that writes what it left behind.
_CONVERSION = "20261119_0619_counters_become_a_plug_in.py"
_FOLLOW_UP = "20261120_0621_counter_subscriptions_and_switches_follow_the_plug_in.py"


def _revision(name: str) -> Any:
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def counters_conversion() -> Any:
    """The revision that turns the built-in Counters into its plug-in,
    loaded by path."""
    return _revision(_CONVERSION)


def counters_follow_up() -> Any:
    """The revision that writes what the conversion left behind, loaded by
    path."""
    return _revision(_FOLLOW_UP)


async def run_as_a_revision(
    session: AsyncSession, guild_id: int, step: Callable[[], None]
) -> None:
    """``step``, a revision's work in ``guild_id``'s schema alone, as a
    revision runs it: on the provisioning login, which owns the tables and is
    neither a superuser nor exempt from row security, so a table it reads
    with row security forced hides what its policies hide. The suite builds a
    community's schema on its superuser, so the schema and what is in it are
    handed to that login first. ``session`` is committed first."""
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    from app.core.config import settings
    from app.db import session as db_session
    from app.db.schema_provisioning import guild_schema_name

    schema = guild_schema_name(guild_id)
    login = make_url(settings.DATABASE_URL)
    assert login.username is not None
    owner = session.get_bind().dialect.identifier_preparer.quote(login.username)
    await session.commit()
    connection = await session.connection()
    await connection.execute(sa.text(f'ALTER SCHEMA "{schema}" OWNER TO {owner}'))
    relations = await connection.execute(
        sa.text(
            "SELECT relname, CASE relkind WHEN 'v' THEN 'VIEW' ELSE 'TABLE' END"
            " FROM pg_class WHERE relkind IN ('r', 'p', 'v')"
            " AND relnamespace = CAST(:s AS regnamespace)"
        ),
        {"s": schema},
    )
    for name, what in relations.all():
        await connection.execute(
            sa.text(f'ALTER {what} "{schema}"."{name}" OWNER TO {owner}')
        )
    await session.commit()

    def apply(bind: Any) -> None:
        assert bind.execute(
            sa.text(
                "SELECT NOT rolsuper AND NOT rolbypassrls"
                " FROM pg_roles WHERE rolname = current_user"
            )
        ).scalar_one()
        bind.execute(
            sa.text("SELECT set_config('search_path', :sp, true)"),
            {"sp": f"{schema}, public"},
        )
        with Operations.context(MigrationContext.configure(bind)):
            step()

    engine = create_async_engine(
        login.set(database=db_session.provisioning_engine.url.database),
        poolclass=NullPool,
    )
    try:
        async with engine.begin() as conn:
            await conn.run_sync(apply)
    finally:
        await engine.dispose()


async def convert_counters(
    session: AsyncSession, guild_id: int, *, between: Any = None
) -> int | None:
    """Turn ``guild_id``'s Counters back into the built-in tool and convert it
    again, as an upgrade does in each community (the conversion, then the
    revision writing what it left behind, each as a revision runs), then
    provision what a start renders for it. ``between`` is awaited with
    ``session`` while the built-in tool is back, before the conversion.
    Returns the install's id afterwards, None where the community has none.
    ``session`` is committed."""
    from sqlmodel import select

    from app.db.kind_codes import ensure_kind_codes
    from app.db.schema_provisioning import provision_community_tools
    from app.models.tenant.guild_plugin import GuildPlugin
    from app.testing.schema_harness import route_session_to_guild

    conversion, follow_up = counters_conversion(), counters_follow_up()
    await run_as_a_revision(session, guild_id, follow_up._apply_downgrade)
    await run_as_a_revision(session, guild_id, conversion._apply_downgrade)
    if between is not None:
        await between(session)
        await session.commit()
    await run_as_a_revision(session, guild_id, conversion._apply_upgrade)
    await run_as_a_revision(session, guild_id, follow_up._apply_upgrade)
    await ensure_kind_codes()
    await provision_community_tools(guild_id)
    await route_session_to_guild(session, guild_id)
    found = await session.exec(
        select(GuildPlugin.id).where(GuildPlugin.listing_uid == COUNTERS_UID)
    )
    return found.first()
