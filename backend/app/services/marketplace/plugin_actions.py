"""A plug-in's actions on items: a reader runs one, and the plug-in does it.

An action is declared in the install's pinned definition and offered on some
kinds of item. Initiative checks, in order, that it may run:

1. the pinned definition declares the action on this kind of item, the
   community's content is not frozen, and the connections the action requires
   hold a value: the community's, and the reader's own;
2. the reader can read the item, through the ordinary resource path;
3. the install is placed in the item's initiative with a role the reader holds
   (:func:`~app.services.tenant.guild_plugins.surface_access`, as a page
   opened there is);
4. the install can read the item itself, routed as the install.

A container plug-in's action names one of its write endpoints, which is then
called as the installation, with the reader as ``viewer`` (by this install's
reference for them) and the item as ``subject`` in the call's token. What it
changes, and whether this reader may, is the plug-in's to decide; Initiative
writes nothing for it.

A declarative plug-in has no code, so Initiative does what its action
declares: the call its endpoint makes, when it names one, on the credential
the endpoint's ``actors`` say (:func:`_actor`), its expressions reading the
item; then the change its ``write`` answers, when it has one, from the
plug-in's values on the item as they stand once the call is answered, made to
them as the install. The checks above and the endpoint's own terms are all
that decide who may run it.

An action may ask the reader for some of its endpoint's parameters first,
and a list field may offer an action on each of its elements. Either way the
endpoint is sent what the reader answered and nothing else, and a declarative
plug-in's expressions read the answers as ``params`` and the element's
``ref`` as ``element``; a container's handler is handed the item alone.

Either way the answer is the values the install shows on the item as they
stand afterwards, and every other reader hears that the item changed from its
own values' change capture.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Optional

import httpx
from sqlalchemy import exists
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import resource_access
from app.api.deps import InstallAccessError, VerifiedInstall, establish_install_access
from app.core.messages import GuildPluginMessages, PluginDataMessages
from app.core.tools import KINDS
from app.db import cohorts
from app.db.guild_standing import GuildContext
from app.models.tenant.guild_plugin import GuildPlugin
from app.services.marketplace import plugin_data
from app.services.marketplace.declarative import (
    action_change,
    request_refusal,
    typed_params,
)
from app.services.marketplace.expressions import UNDEFINED
from app.services.marketplace.plugin_data import PluginDataError
from app.services.marketplace.plugin_refs import PluginNameRefused, ensure_plugin_ref
from app.services.marketplace.registration_lookup import (
    RegistrationSnapshot,
    is_declarative,
)
from app.services.marketplace.service_plugins import PLATFORM_CODES, is_admin_only
from app.services.tenant import guild_plugins, metadata, plugin_config
from app.services.tenant.guild_plugins import SurfaceAccess
from app.services.tenant.plugin_channels import PluginChannelError

__all__ = ["run_action"]


async def _reads(
    plugin: GuildPlugin,
    registration: RegistrationSnapshot,
    *,
    guild_id: int,
    kind: str,
    entity_id: int,
) -> bool:
    """Whether the install can read the item: asked of the database on a
    session of its own routed as the install, with the scopes its tokens
    carry, so the answer is the one its own reads get."""
    table = SQLModel.metadata.tables[KINDS[kind].table]
    async with cohorts.request_sessionmaker(guild_id)() as session:
        try:
            await establish_install_access(
                session,
                VerifiedInstall(
                    guild_id=guild_id,
                    install_id=int(plugin.id or 0),
                    client_id=registration.public_id,
                    scopes=guild_plugins.install_scopes(plugin, registration),
                ),
            )
        except InstallAccessError:
            return False
        return bool(
            await session.scalar(exists().where(table.c.id == entity_id).select())
        )


async def _item(
    session: AsyncSession, kind: str, entity_id: int, context: GuildContext
) -> tuple[int, str]:
    """The item's initiative and what it is called, once the reader is found
    to read it as its own routes would let them (404 or 403 otherwise). An
    item of the community's own tool, which no initiative holds, has no
    plug-in placed on it."""
    row = await resource_access.load_kind(session, kind, entity_id, None, context)
    tool = row if KINDS[kind].parent is None else resource_access.parent_of(row)
    if tool.initiative_id is None:
        raise _not_offered()
    # A tool's name, or the column its sub-tool keeps what it is called in.
    column = "name" if tool is row else resource_access.SUB_TOOLS[type(row)].name
    return int(tool.initiative_id), getattr(row, column) or ""


def _not_offered() -> PluginDataError:
    return PluginDataError(PluginDataMessages.ACTION_NOT_OFFERED, 403)


def _failed(detail: str) -> PluginDataError:
    """The plug-in's work failing, answered as a container's failed call is."""
    return PluginDataError(PluginDataMessages.SERVICE_UNAVAILABLE, 502, detail)


def _answers(
    action: Mapping[str, Any],
    endpoint: Optional[Mapping[str, Any]],
    params: Optional[Mapping[str, Any]],
) -> dict[str, Any]:
    """What the reader answered for the parameters the action asks for, held
    to the endpoint's declaration of them (:func:`plugin_data.validate_params`,
    as a widget's parameters are). An answer the action did not ask for, or
    one the endpoint requires and the reader left out, is refused."""
    answered = dict(params or {})
    if any(key not in (action.get("params") or ()) for key in answered):
        raise PluginDataError(PluginDataMessages.INVALID_PARAMS, 400)
    if endpoint is None:
        return {}
    sent, _ = plugin_data.validate_params(
        endpoint, json.dumps(answered) if answered else None
    )
    return sent


def _on_elements(
    definition: Optional[Mapping[str, Any]], action_id: str, kind: str, element: str
) -> bool:
    """Whether a list field on this kind of item offers the action on each of
    its elements, and ``element`` is one's ``ref``."""
    fields = (definition or {}).get("fields")
    return metadata.is_ref(element) and any(
        isinstance(field, dict)
        and field.get("list") is True
        and action_id in (field.get("actions") or ())
        and kind in (field.get("on") or ())
        for field in (fields if isinstance(fields, list) else [])
    )


async def _actor(
    session: AsyncSession,
    *,
    plugin: GuildPlugin,
    endpoint: dict[str, Any],
    user_id: int,
) -> tuple[str, dict[str, str], dict[str, dict[str, Any]]]:
    """Whose credential a declarative action's call runs on, and the handles
    and non-secret fields it runs with
    (:func:`~app.services.marketplace.plugin_data._resolve_connections`): the
    first of the endpoint's ``actors`` the reader's call can run as,
    ``member`` on the reader's own connections and ``installation`` on the
    community's: its ``requires`` met, and every connection its requests name
    for that actor able to travel
    (:func:`~app.services.marketplace.declarative.request_refusal`).
    An endpoint naming no actors runs as the reader when its
    first request carries an interactive connection, and as the installation
    when it carries a static one. When none can, the best one's refusal is
    the answer."""
    actors = endpoint.get("actors")
    if not isinstance(actors, list) or not actors:
        request = (endpoint.get("steps") or [endpoint])[0]["request"]
        connection = plugin_config.connection_by_id(
            plugin.definition, request.get("connection")
        )
        interactive = (connection or {}).get("scope") == "interactive"
        actors = ["member" if interactive else "installation"]
    refusals: list[PluginDataError] = []
    for actor in actors:
        try:
            refs, fields = await plugin_data._resolve_connections(
                session,
                plugin=plugin,
                endpoint=endpoint,
                user_id=user_id if actor == "member" else None,
                actor=actor,
            )
        except PluginDataError as exc:
            refusals.append(exc)
            continue
        refused = request_refusal(plugin.definition, endpoint, refs, actor)
        if refused is not None:
            refusals.append(refused)
            continue
        return actor, refs, fields
    raise refusals[0]


async def _act(
    session: AsyncSession,
    *,
    plugin: GuildPlugin,
    registration: RegistrationSnapshot,
    action: dict[str, Any],
    endpoint: Optional[dict[str, Any]],
    item: dict[str, Any],
    params: Mapping[str, Any],
    element: Optional[str],
    guild_id: int,
    user_id: int,
    transport: httpx.AsyncBaseTransport | None,
) -> None:
    """Do what a declarative action declares, as the SDK's ``runAction``
    does: the call its endpoint makes, when it names one, with ``params``,
    on the credential :func:`_actor` picks, its expressions reading ``item``
    and ``element``; then the change its ``write`` answers, when it has one
    (:func:`action_change`), reading the plug-in's values on the item as
    they stand once the call is answered, made to them as the install
    (:func:`~app.services.tenant.metadata.change_item`).

    The endpoint refusing or answering unavailable, a ``write`` answering
    what is not a change, and a change that is refused, the install no longer
    reading the item included, each fail the action as a container's failed
    call does, and the plug-in's values stay as they were.
    """
    result: Any = UNDEFINED
    if endpoint is not None:
        actor, refs, fields = await _actor(
            session, plugin=plugin, endpoint=endpoint, user_id=user_id
        )
    # Nothing is held open while the vendor works and the values change, and
    # what was read stays readable; the next statement routes the session again.
    session.expunge_all()
    await session.rollback()
    if endpoint is not None:

        async def read(
            request: httpx.Request | plugin_data.Answered,
        ) -> dict[str, Any]:
            return await plugin_data._read_body(request, transport=transport)

        try:
            body = await plugin_data._call_plugin(
                registration=registration,
                plugin=plugin,
                guild_id=guild_id,
                endpoint_id=str(endpoint["id"]),
                params=params,
                refs=refs,
                fields=fields,
                transport=transport,
                read=read,
                actor=actor,
                item=item,
                element=element,
            )
        except PluginDataError as exc:
            # A write the vendor refused answers one of the endpoint's codes.
            if exc.code not in {*PLATFORM_CODES, *(endpoint.get("unavailable") or ())}:
                raise
            raise _failed(f"{endpoint['id']} answered {exc.code}") from exc
        result = body["result"]
        if set(result) == {"unavailable"}:
            raise _failed(f"{endpoint['id']} answered {result['unavailable']}")
    if not action.get("write"):
        return

    installed = plugin_config.install_settings(plugin)
    answered = typed_params(endpoint, params) if endpoint is not None else {}

    async def made(held: dict[str, Any]) -> Optional[dict[str, Any]]:
        return await action_change(
            action["write"],
            item=item,
            held=held,
            installed=installed,
            result=result,
            params=answered,
            element=element,
        )

    try:
        await metadata.change_item(
            plugin, registration, item["kind"], item["id"], made, guild_id=guild_id
        )
    except PluginChannelError as exc:
        raise _failed(f"the change was refused: {exc.code}") from exc


async def run_action(
    session: AsyncSession,
    *,
    plugin: GuildPlugin,
    action_id: str,
    kind: str,
    entity_id: int,
    context: GuildContext,
    user_id: int,
    age_allows: bool,
    params: Optional[Mapping[str, Any]] = None,
    element: Optional[str] = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """Run one of the install's actions on one item for the reader, and return
    the values the install shows on it afterwards, by key.

    ``session`` is the reader's, routed into the community, and ``context``
    their standing there. ``age_allows`` is whether the reader is old enough
    for the plug-in. ``params`` is what they answered for the parameters the
    action asks for, and ``element`` the ``ref`` of the list element they ran
    it from, when they did.
    """
    declarative = is_declarative(plugin.definition)
    declared = (plugin.definition or {}).get("actions")
    action = next(
        (
            entry
            for entry in (declared if isinstance(declared, list) else [])
            if isinstance(entry, dict)
            and entry.get("id") == action_id
            and kind in (entry.get("on") or ())
        ),
        {},
    )
    # A container's action names the write its handler answers; a declarative
    # plug-in's names a read or a write, its own ``write``, or both.
    endpoint = plugin_data.endpoint_by_id(
        plugin.definition,
        action.get("endpoint"),
        directions=("read", "write") if declarative else ("write",),
    )
    if endpoint is None and not (
        declarative and action.get("endpoint") is None and action.get("write")
    ):
        raise PluginDataError(PluginDataMessages.ACTION_NOT_FOUND, 404)
    sent = _answers(action, endpoint, params)
    if element is not None and not _on_elements(
        plugin.definition, action_id, kind, element
    ):
        raise PluginDataError(PluginDataMessages.INVALID_PARAMS, 400)
    if not plugin.enabled:
        raise PluginDataError(PluginDataMessages.PLUGIN_DISABLED, 409)
    # A frozen community's content changes through nothing, a plug-in's
    # write included.
    if context.content_read_only:
        raise _not_offered()
    # The connections the action itself requires, resolved as an endpoint's
    # are: the community's hold a value, and the reader has made their own.
    await plugin_data._resolve_connections(
        session, plugin=plugin, endpoint=action, user_id=user_id
    )
    registration = await plugin_data._load_registration(
        None, guild_id=context.guild_id, plugin=plugin
    )

    install_id = int(plugin.id or 0)
    initiative_id, title = await _item(session, kind, entity_id, context)
    offered = guild_plugins.surface_access(
        {
            **guild_plugins.ITEM_SURFACE,
            "admin_only": is_admin_only(action) or is_admin_only(endpoint),
        },
        initiative_id=initiative_id,
        placement_role_ids=await guild_plugins.placement_role_ids(
            session, install_id, initiative_id
        ),
        is_guild_admin=context.is_admin,
        member_role_ids=context.member_role_ids,
        age_allows=age_allows,
    )
    if offered is SurfaceAccess.too_young:
        raise PluginDataError(GuildPluginMessages.AGE_RESTRICTED, 403)
    if offered is not SurfaceAccess.open:
        raise _not_offered()
    if not await _reads(
        plugin, registration, guild_id=context.guild_id, kind=kind, entity_id=entity_id
    ):
        raise _not_offered()

    if declarative:
        await _act(
            session,
            plugin=plugin,
            registration=registration,
            action=action,
            endpoint=endpoint,
            item={"kind": kind, "id": entity_id, "title": title},
            params=sent,
            element=element,
            guild_id=context.guild_id,
            user_id=user_id,
            transport=transport,
        )
    else:
        assert endpoint is not None  # a container's action names its write
        refs, fields = await plugin_data._resolve_connections(
            session,
            plugin=plugin,
            endpoint=endpoint,
            user_id=None,
            actor="installation",
        )
        try:
            viewer = await ensure_plugin_ref(
                guild_id=context.guild_id,
                public_id=registration.public_id,
                user_id=user_id,
            )
        except PluginNameRefused as exc:
            raise PluginDataError(PluginDataMessages.PLUGIN_DISABLED, 409) from exc
        # Nothing is held open while the plug-in works, and what was read stays
        # readable; the next statement routes the session again.
        session.expunge_all()
        await session.rollback()

        async def read(request: httpx.Request | plugin_data.Answered) -> None:
            await plugin_data._read_body(request, transport=transport)

        await plugin_data._call_plugin(
            registration=registration,
            plugin=plugin,
            guild_id=context.guild_id,
            endpoint_id=str(endpoint["id"]),
            params=sent,
            refs=refs,
            fields=fields,
            transport=transport,
            read=read,
            viewer=viewer,
            subject={"type": kind, "id": entity_id},
        )
    # The action may have changed what the install's reads answer.
    plugin_data.clear_plugin_data_cache(guild_id=context.guild_id, plugin_id=install_id)

    return await metadata.shown_values(session, install_id, kind, entity_id)
