"""Content ownership — who owns a tool, and what happens when they leave.

Ownership and authorship are different things, and this module only deals with
the first:

- **Author** — who wrote it: ``created_by``, one column on every guild table
  that records one (:class:`CreatedByMixin`). A historical fact. Nothing here
  ever changes one.
- **Owner** — who owns it: the ``resource_grants`` row at
  ``level='owner'``. A live permission, and the only thing this module moves.

Comments, tasks and uploads have an author and no owner at all; they take
their permissions from the tool that holds them. The members of :class:`Tool` are
exactly the things that have an owner, so :data:`OWNABLE` derives from that enum
and ``ownership_test.py`` fails if a tool is ever missing from it.

**Ownership is optional.** There is no "ownerless" grant row — the
``resource_grants_one_grantee`` constraint requires every row to name one
grantee — so having no owner is the *absence* of an owner grant, which is also
the honest way to say it. The owner row names a person or an installed plug-in
(:class:`Owner`), and one rule follows:

    An owner is a current member of the guild, a live install, or nobody.

A live install is one that is switched on. What a plug-in owns stays its own while
it is off, and is listed as unowned until it is switched back on; uninstalling
removes its owner rows with it (the foreign key cascades), so its content
becomes unowned like a departed member's.

Leaving a guild drops the person's owner grants rather than handing them to
someone else: nobody inherits privilege they did not ask for, which matters most
in a guild with heavy turnover. Guild admins still administer unowned content
through their guild-admin authority, and can claim it whenever they choose, or
hand it to a plug-in that may own it (:func:`eligible_plugin_owners`).
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import or_
from sqlalchemy import select as sa_select
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.plugin_scopes import (
    PluginScopeResource,
    UnknownPluginScope,
    expand,
    tool_resource,
)
from app.core.audit_events import AuditEventType
from app.core.messages import UserMessages
from app.core.tools import Tool
import app.db.base  # noqa: F401 — registers every model, so each tool's is found by table
from app.db.session import install_context
from app.models.tenant._mixins import tool_models
from app.models.platform.guild import GuildMembership
from app.models.tenant.plugin_placement import PluginPlacement
from app.models.tenant.guild_plugin import GuildPlugin
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.schemas.tenant.ownership import OwnerPluginSummary
from app.services import audit as audit_service
from app.services import permissions as permissions_service
from app.services.marketplace import catalog as catalog_service


@dataclass(frozen=True)
class OwnableSpec:
    """Where one tool's rows live.

    That is the whole per-tool variation: no model carries an owner column, so
    finding who owns a row is the same query for every tool. The label shown for
    a row comes from ``SoftDeleteMixin.display_field()``, which already names it
    for the trash can and the recents bar.
    """

    model: Any

    @property
    def display_column(self) -> str:
        return self.model.display_field()


#: Derived from the enum rather than listed: a tool's table is its plural, so the
#: model is found by that name and the pairing cannot drift. A tool with no model
#: fails here at import, naming its table, rather than going quietly unowned.
OWNABLE: dict[Tool, OwnableSpec] = {
    tool: OwnableSpec(tool_models()[tool.plural]) for tool in Tool
}


# Reverse of OWNABLE, so a row can name its own tool.
TOOL_BY_MODEL: dict[Any, Tool] = {spec.model: tool for tool, spec in OWNABLE.items()}


def tool_for_row(row: Any) -> Optional[Tool]:
    """The :class:`Tool` this row is an instance of, or None if it is not one.

    Tasks, comments and uploads land here as None — they have an author and no
    owner, and take their permissions from the tool that holds them.
    """
    return TOOL_BY_MODEL.get(type(row))


@dataclass(frozen=True)
class OwnedItem:
    tool: Tool
    id: int
    name: str
    #: The initiative the row belongs to, which a plug-in owner must be placed in.
    initiative_id: Optional[int] = None


@dataclass(frozen=True)
class Owner:
    """Who holds a resource's owner grant: a person or an installed plug-in.
    Exactly one of the two is set."""

    user_id: Optional[int] = None
    plugin_install_id: Optional[int] = None

    def __post_init__(self) -> None:
        if (self.user_id is None) == (self.plugin_install_id is None):
            raise ValueError("an owner is a person or a plug-in, and exactly one")


def _grant_owner(grant: Any) -> Optional[Owner]:
    """The owner an owner-level grant row names, or None for any other row."""
    if grant.level != ResourceAccessLevel.owner:
        return None
    if grant.user_id is not None:
        return Owner(user_id=grant.user_id)
    if grant.plugin_install_id is not None:
        return Owner(plugin_install_id=grant.plugin_install_id)
    return None


def owner_of(row: Any) -> Optional[Owner]:
    """Who holds this resource's owner grant, or None if nobody does.

    Reads ``row.grants``, which the caller must have eagerly loaded — this is
    deliberately a function rather than a model property so that requirement is
    visible at the call site instead of turning into a lazy load that fails
    under async.
    """
    for grant in row.grants or []:
        owner = _grant_owner(grant)
        if owner is not None:
            return owner
    return None


def owner_user_id_of(row: Any) -> Optional[int]:
    """The person holding this resource's owner grant, or None when nobody
    does or a plug-in does. Reads ``row.grants`` as :func:`owner_of` does."""
    owner = owner_of(row)
    return owner.user_id if owner is not None else None


#: Where :func:`annotate_owner_plugins` leaves a row's owning plug-in.
_OWNER_PLUGIN_ATTRIBUTE = "_owner_plugin"


def owner_plugin_of(row: Any) -> Optional[OwnerPluginSummary]:
    """The installed plug-in that owns ``row``, as :func:`annotate_owner_plugins`
    left it; None when a person owns it, nobody does, or it was not
    annotated."""
    return getattr(row, _OWNER_PLUGIN_ATTRIBUTE, None)


async def annotate_owner_plugins(session: AsyncSession, rows: Iterable[Any]) -> None:
    """Set the owning plug-in on each row an installed plug-in owns, for its serializer
    (:func:`owner_plugin_of`). Reads each row's eagerly loaded ``grants``.

    One query for the installs, and none when no row is plugin-owned. The picture
    is the listing's, read from the catalog for a person's request; an
    installed plug-in's response names the plug-in without it.
    """
    owned: list[tuple[Any, int]] = []
    for row in rows:
        if row is None:
            continue
        owner = owner_of(row)
        install_id = owner.plugin_install_id if owner is not None else None
        object.__setattr__(row, _OWNER_PLUGIN_ATTRIBUTE, None)
        if install_id is not None:
            owned.append((row, install_id))
    if not owned:
        return
    installs = (
        await session.exec(
            select(GuildPlugin.id, GuildPlugin.name, GuildPlugin.listing_uid).where(
                GuildPlugin.id.in_({install_id for _row, install_id in owned})
            )
        )
    ).all()
    avatars: dict[str, str] = {}
    if install_context(session) is None:
        avatars = await catalog_service.listing_avatars(
            session, [listing_uid for _id, _name, listing_uid in installs]
        )
    summaries = {
        install_id: OwnerPluginSummary(
            id=install_id, name=name, avatar_url=avatars.get(listing_uid)
        )
        for install_id, name, listing_uid in installs
    }
    for row, install_id in owned:
        object.__setattr__(row, _OWNER_PLUGIN_ATTRIBUTE, summaries.get(install_id))


# ── Reading what is owned ────────────────────────────────────────────────────


def _owner_grant_resource_ids(tool: Tool, user_id: Optional[int] = None):
    stmt = sa_select(ResourceGrant.resource_id).where(
        ResourceGrant.resource_type == tool.value,
        ResourceGrant.level == ResourceAccessLevel.owner,
    )
    if user_id is not None:
        stmt = stmt.where(ResourceGrant.user_id == user_id)
    else:
        stmt = stmt.where(ResourceGrant.user_id.is_not(None))
    return stmt


async def _owned_rows(session: AsyncSession, tool: Tool, user_id: int) -> list[Any]:
    """Rows of ``tool`` whose owner grant names this user."""
    model = OWNABLE[tool].model
    stmt = select(model).where(model.id.in_(_owner_grant_resource_ids(tool, user_id)))
    return list((await session.exec(stmt)).unique().all())


async def _unowned_rows(
    session: AsyncSession, tool: Tool, *, guild_id: int
) -> list[Any]:
    """Rows of ``tool`` that no current member of the guild and no live
    install owns.

    Three situations, one condition, because they are the same problem: the
    resource has no owner grant at all (a member left and released it), its
    owner grant names someone who is no longer in the guild (content orphaned
    before ownership was released on departure), or it names a plug-in that is
    switched off. Either way nobody who can act on it owns it, and an admin
    claiming it is the same click.
    """
    member_ids = sa_select(GuildMembership.user_id).where(
        GuildMembership.guild_id == guild_id
    )
    live_installs = sa_select(GuildPlugin.id).where(GuildPlugin.enabled.is_(True))
    owned = sa_select(ResourceGrant.resource_id).where(
        ResourceGrant.resource_type == tool.value,
        ResourceGrant.level == ResourceAccessLevel.owner,
        or_(
            ResourceGrant.user_id.in_(member_ids),
            ResourceGrant.plugin_install_id.in_(live_installs),
        ),
    )
    stmt = select(OWNABLE[tool].model).where(OWNABLE[tool].model.id.not_in(owned))
    return list((await session.exec(stmt)).unique().all())


def _as_items(tool: Tool, rows: list[Any]) -> list[OwnedItem]:
    column = OWNABLE[tool].display_column
    return [
        OwnedItem(
            tool=tool,
            id=row.id,
            name=getattr(row, column, None) or "",
            initiative_id=row.initiative_id,
        )
        for row in rows
    ]


async def summarize_owned_content(
    session: AsyncSession, user_id: int
) -> list[OwnedItem]:
    """Everything this user owns in the routed guild, tool by tool. The session
    must already be routed into the guild's schema."""
    items: list[OwnedItem] = []
    for tool in OWNABLE:
        items.extend(_as_items(tool, await _owned_rows(session, tool, user_id)))
    return items


async def summarize_unowned_content(
    session: AsyncSession, *, guild_id: int
) -> list[OwnedItem]:
    """Everything in the guild that no current member owns — what a guild admin
    watches accumulate as people leave, and can claim in one go."""
    items: list[OwnedItem] = []
    for tool in OWNABLE:
        items.extend(
            _as_items(tool, await _unowned_rows(session, tool, guild_id=guild_id))
        )
    return items


# ── Which plug-ins may own ───────────────────────────────────────────────────────


def _written_resources(scopes: Iterable[str]) -> frozenset[PluginScopeResource]:
    """The resources ``scopes`` let a plug-in write. A scope the vocabulary no
    longer names grants nothing."""
    known: list[str] = []
    for scope in scopes or ():
        try:
            expand([scope])
        except UnknownPluginScope:
            continue
        known.append(scope)
    return expand(known)[1]


async def eligible_plugin_owners(
    session: AsyncSession, items: Sequence[OwnedItem]
) -> list[OwnerPluginSummary]:
    """The installed plug-ins that may own every one of ``items``, by name.

    An install may own a resource when it is switched on, the community's
    grant to it holds that tool's write scope, and it is placed in the
    resource's initiative: the same test the install passes when it creates
    one. A resource that belongs to no initiative is placed nowhere, so no plug-in
    may own it. Nothing to own is nobody's to offer.
    """
    if not items:
        return []
    installs = (
        await session.exec(
            select(
                GuildPlugin.id,
                GuildPlugin.name,
                GuildPlugin.listing_uid,
                GuildPlugin.granted_scopes,
            )
            .where(GuildPlugin.enabled.is_(True))
            .order_by(GuildPlugin.name, GuildPlugin.id)
        )
    ).all()
    if not installs:
        return []
    placed: dict[int, set[int]] = {}
    for install_id, initiative_id in (
        await session.exec(
            select(PluginPlacement.install_id, PluginPlacement.initiative_id).where(
                PluginPlacement.install_id.in_([row[0] for row in installs])
            )
        )
    ).all():
        placed.setdefault(install_id, set()).add(initiative_id)

    eligible: list[tuple[int, str, str]] = []
    for install_id, name, listing_uid, granted_scopes in installs:
        written = _written_resources(granted_scopes)
        where = placed.get(install_id, set())
        if all(
            tool_resource(item.tool) in written
            and item.initiative_id is not None
            and item.initiative_id in where
            for item in items
        ):
            eligible.append((install_id, name, listing_uid))
    if not eligible:
        return []
    avatars = await catalog_service.listing_avatars(
        session, [listing_uid for _id, _name, listing_uid in eligible]
    )
    return [
        OwnerPluginSummary(
            id=install_id, name=name, avatar_url=avatars.get(listing_uid)
        )
        for install_id, name, listing_uid in eligible
    ]


async def require_plugin_owner_eligible(
    session: AsyncSession, *, install_id: int, items: Sequence[OwnedItem]
) -> None:
    """Raise 422 ``OWNER_PLUGIN_NOT_ELIGIBLE`` unless ``install_id`` may own
    every one of ``items`` (:func:`eligible_plugin_owners`)."""
    eligible = await eligible_plugin_owners(session, items)
    if not items or install_id not in {plugin.id for plugin in eligible}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=UserMessages.OWNER_PLUGIN_NOT_ELIGIBLE,
        )


# ── Changing it ──────────────────────────────────────────────────────────────


async def _clear_owner_grants(session: AsyncSession, *, tool: Tool, row: Any) -> None:
    """Leave the resource with no owner grant at all.

    Every one, whoever holds it. Two shapes turn up beyond the single user row
    the caller has in mind: several user rows at owner level (the re-homing
    paths this replaced could upgrade every initiative manager at once), and a
    row whose grantee is a *role* or the whole initiative, which the calendar
    backfill in migration 0157 seeded before there was an index saying a
    resource has one owner. That index counts a role's owner row like anyone
    else's, so leaving one standing made the next owner collide with it.

    A user's owner row is deleted: the caller is about to say who holds
    ownership now. A role's or everyone's is demoted to ``write`` instead —
    dropping it would take editing away from people who have it today, and the
    sharing panel skips owner rows, so no admin ever saw one to decide about.
    An installed plug-in's is demoted to ``write`` too: it is the owner being
    replaced, and it keeps editing what it managed. Nothing can collide with the
    demoted row: ``resource_grants_unique_grantee`` already allows each grantee
    one grant per resource.

    Callers reach this only for a resource whose owner they are replacing, so
    a live install's content is never cleared by a claim: the unowned list does
    not hold it.
    """
    grants = (
        await session.exec(
            select(ResourceGrant).where(
                ResourceGrant.resource_type == tool.value,
                ResourceGrant.resource_id == row.id,
                ResourceGrant.level == ResourceAccessLevel.owner,
            )
        )
    ).all()
    for grant in grants:
        if grant.user_id is not None:
            await session.delete(grant)
        else:
            grant.level = ResourceAccessLevel.write
            session.add(grant)
    # Flush before any new owner row is added. The unit of work orders INSERTs
    # ahead of DELETEs, so without this the incoming owner collides with the
    # outgoing one on the single-owner index.
    if grants:
        await session.flush()


async def set_resource_owner(
    session: AsyncSession, *, tool: Tool, row: Any, new_owner: Optional[Owner]
) -> None:
    """Make ``new_owner`` the resource's owner, or leave it unowned when None.
    Caller commits, and has decided the new owner may hold it (a plug-in, by
    :func:`require_plugin_owner_eligible`).

    A person's owner row changes hands in place — one ``UPDATE`` — so the
    request writing it holds the owner's rung for the whole of the change, as
    the share gate on ``resource_grants`` asks. Any lower grant the recipient
    already holds is removed first, so the row does not collide with it on
    ``resource_grants_unique_grantee``. With no person's owner row to hand on,
    the others are cleared (:func:`_clear_owner_grants`) and a new one is
    written. Author columns are not touched: who wrote the thing does not
    change when who owns it does.
    """
    if new_owner is None:
        await _clear_owner_grants(session, tool=tool, row=row)
        await session.flush()
        return

    grants = (
        await session.exec(
            select(ResourceGrant).where(
                ResourceGrant.resource_type == tool.value,
                ResourceGrant.resource_id == row.id,
            )
        )
    ).all()
    is_recipient = (
        (lambda g: g.user_id == new_owner.user_id)
        if new_owner.user_id is not None
        else (lambda g: g.plugin_install_id == new_owner.plugin_install_id)
    )
    held = next((g for g in grants if is_recipient(g)), None)
    if held is not None and held.level == ResourceAccessLevel.owner:
        return
    handover = next(
        (
            g
            for g in grants
            if g.level == ResourceAccessLevel.owner and g.user_id is not None
        ),
        None,
    )
    if handover is None:
        await _clear_owner_grants(session, tool=tool, row=row)
        if held is not None:
            held.level = ResourceAccessLevel.owner
            session.add(held)
        else:
            session.add(
                ResourceGrant(
                    resource_type=tool.value,
                    resource_id=row.id,
                    user_id=new_owner.user_id,
                    plugin_install_id=new_owner.plugin_install_id,
                    role_id=None,
                    level=ResourceAccessLevel.owner,
                    initiative_id=row.initiative_id,
                )
            )
        await session.flush()
        return
    if held is not None:
        await session.delete(held)
        await session.flush()
    handover.user_id = new_owner.user_id
    handover.plugin_install_id = new_owner.plugin_install_id
    # The owner row is scoped as its resource is, which moving a contact into
    # the community's changes.
    handover.initiative_id = row.initiative_id
    session.add(handover)
    await session.flush()


async def give_to_install(
    session: AsyncSession,
    tool: Tool,
    row: Any,
    *,
    install_id: int,
    guild_id: int,
    grants: Sequence[Any],
    actor_user_id: Optional[int] = None,
) -> None:
    """Make a row of the whole community the install's that mounts its tool,
    shared by ``grants``. Uninstalling trashes what the install owns; the owner
    grant names the install row, so an uninstall holding that row finishes
    first and this write fails. At community scope an everyone grant reads as
    every member of the community."""
    await set_resource_owner(
        session, tool=tool, row=row, new_owner=Owner(plugin_install_id=install_id)
    )
    await permissions_service.replace_resource_grants(
        session,
        resource_type=tool.value,
        resource_id=row.id,
        guild_id=guild_id,
        initiative_id=None,
        owner_id=None,
        grants=grants,
        actor_user_id=actor_user_id,
    )


async def current_owner(
    session: AsyncSession, *, tool: Tool, resource_id: int
) -> Optional[Owner]:
    """Who owns this resource right now, straight from the grants.

    Unlike :func:`owner_of` this issues a query, for callers holding a row
    whose grants were never loaded.
    """
    grant = (
        await session.exec(
            select(ResourceGrant).where(
                ResourceGrant.resource_type == tool.value,
                ResourceGrant.resource_id == resource_id,
                ResourceGrant.level == ResourceAccessLevel.owner,
            )
        )
    ).one_or_none()
    return _grant_owner(grant) if grant is not None else None


async def restore_ownership_to_author(
    session: AsyncSession, *, row: Any, guild_id: int
) -> bool:
    """Give an unowned resource back to whoever wrote it, if they are still here.

    A convenience for restoring from the trash: content trashed before its owner
    left the guild comes back unowned, and the author is the one non-arbitrary
    person to hand it to. Does nothing when the row already has an owner, when
    the row records no author, or when that author has since left — there is no
    second-guess, the content simply stays unowned.

    Returns whether an owner was set. Caller commits.
    """
    tool = tool_for_row(row)
    if tool is None:
        return False

    # Every tool carries CreatedByMixin, so once tool_for_row has answered there
    # is a created_by to read (ownership_test pins that).
    author_id = row.created_by
    if author_id is None:
        return False

    if await current_owner(session, tool=tool, resource_id=row.id) is not None:
        return False

    still_a_member = (
        await session.exec(
            select(GuildMembership.user_id).where(
                GuildMembership.guild_id == guild_id,
                GuildMembership.user_id == author_id,
            )
        )
    ).one_or_none()
    if still_a_member is None:
        return False

    await set_resource_owner(
        session, tool=tool, row=row, new_owner=Owner(user_id=author_id)
    )
    return True


async def _record_ownership_move(
    session: AsyncSession,
    *,
    actor_user_id: Optional[int],
    from_user_id: Optional[int],
    to: Owner,
    guild_id: Optional[int],
    counts: dict[Tool, int],
) -> None:
    """One record for one move, with what it moved counted by tool.

    A move that found nothing to move is left unrecorded, and a caller that
    names no actor is too — ``set_resource_owner`` is reached by the restore
    and release paths as well, which are their own events.
    """
    if actor_user_id is None or not counts:
        return
    await audit_service.record(
        session,
        event_type=AuditEventType.CONTENT_OWNERSHIP_TRANSFERRED,
        actor_user_id=actor_user_id,
        target_user_id=from_user_id,
        guild_id=guild_id,
        detail={
            "from_user_id": from_user_id,
            "to_user_id": to.user_id,
            "to_plugin_install_id": to.plugin_install_id,
            "counts": {tool.value: count for tool, count in counts.items()},
        },
    )


async def _move(
    session: AsyncSession,
    rows_by_tool: dict[Tool, list[Any]],
    to: Owner,
) -> dict[Tool, int]:
    """Hand every row to ``to``, refusing a plug-in that may not own all of them.
    Returns a per-tool count; moving nothing is nothing to refuse."""
    items = [
        item for tool, rows in rows_by_tool.items() for item in _as_items(tool, rows)
    ]
    if to.plugin_install_id is not None and items:
        await require_plugin_owner_eligible(
            session, install_id=to.plugin_install_id, items=items
        )
    moved: dict[Tool, int] = {}
    for tool, rows in rows_by_tool.items():
        for row in rows:
            await set_resource_owner(session, tool=tool, row=row, new_owner=to)
        if rows:
            moved[tool] = len(rows)
    return moved


async def transfer_content_ownership(
    session: AsyncSession,
    *,
    from_user_id: int,
    to: Owner,
    guild_id: Optional[int] = None,
    actor_user_id: Optional[int] = None,
) -> dict[Tool, int]:
    """Move everything ``from_user_id`` owns in the routed guild to ``to``.
    Returns a per-tool count of what moved. Caller commits.

    A plug-in receives it only when it may own every item; otherwise nothing
    moves and the answer is 422 ``OWNER_PLUGIN_NOT_ELIGIBLE``. ``actor_user_id``
    is who did it; without one the move is unrecorded."""
    rows_by_tool = {
        tool: await _owned_rows(session, tool, from_user_id) for tool in OWNABLE
    }
    moved = await _move(session, rows_by_tool, to)
    await _record_ownership_move(
        session,
        actor_user_id=actor_user_id,
        from_user_id=from_user_id,
        to=to,
        guild_id=guild_id,
        counts=moved,
    )
    return moved


async def claim_unowned_content(
    session: AsyncSession,
    *,
    guild_id: int,
    to: Owner,
    actor_user_id: Optional[int] = None,
) -> dict[Tool, int]:
    """Give every resource no current member or live install owns to ``to``.
    Returns a per-tool count. Caller commits.

    A plug-in receives it only when it may own every item, as for a transfer.
    ``actor_user_id`` is who did it; without one the claim is unrecorded."""
    rows_by_tool = {
        tool: await _unowned_rows(session, tool, guild_id=guild_id) for tool in OWNABLE
    }
    claimed = await _move(session, rows_by_tool, to)
    await _record_ownership_move(
        session,
        actor_user_id=actor_user_id,
        # Nobody held it, so there is no previous owner to name.
        from_user_id=None,
        to=to,
        guild_id=guild_id,
        counts=claimed,
    )
    return claimed


__all__ = [
    "OWNABLE",
    "Owner",
    "annotate_owner_plugins",
    "current_owner",
    "eligible_plugin_owners",
    "owner_plugin_of",
    "owner_of",
    "owner_user_id_of",
    "require_plugin_owner_eligible",
    "restore_ownership_to_author",
    "tool_for_row",
    "OwnableSpec",
    "OwnedItem",
    "claim_unowned_content",
    "set_resource_owner",
    "summarize_owned_content",
    "summarize_unowned_content",
    "transfer_content_ownership",
]
