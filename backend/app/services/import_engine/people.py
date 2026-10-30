"""Who each name in a bundle is, in the community it is being imported into.

An envelope names people by **handle** — ``foobar#1234``, the one identifier
that means the same thing in every community — because an id means nothing on
the far side and an address is not a person's identifier here. Matching those
handles to real accounts is the one part of an import nobody can do from the
data alone: two people can carry the same display name, one person can carry
different handles on two servers, and an export from somewhere else carries
names that were never accounts here at all.

So it is asked, not guessed. The plan lists every person the bundle mentions
with a suggestion where an exact handle matched, the importer confirms or
changes each row in the wizard, and the confirmed answer is what this map
holds. A row left unmapped stays unmapped: a name nobody claimed is reported,
never attached to whoever looked closest.

The mapping is re-checked here, at apply time, against real guild membership
on the caller's own routed session — the confirm may have been hours ago, and
somebody named in it may have left since.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import delete as sa_delete
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import require_guild_context
from app.models.platform.guild import AdminSurface
from app.models.tenant.initiative import InitiativeMember
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.services.import_engine.common import handle_key
from app.services.tenant import initiatives as initiatives_service
from app.services.tenant import named_people

logger = logging.getLogger(__name__)


@dataclass
class PeopleMap:
    """Source handle → the account it was confirmed to be.

    Empty is the ordinary case, not a failure: an import nobody mapped anybody
    for behaves exactly as it did before there was a mapping step.
    """

    _by_handle: dict[str, int] = field(default_factory=dict)

    def user_id(self, handle: str | None) -> int | None:
        """The account this handle was mapped to, or None if nobody claimed
        it. A handle matches however it was capitalised, because a handle is
        one name however it is typed."""
        if not handle:
            return None
        return self._by_handle.get(handle_key(handle))

    def __bool__(self) -> bool:
        return bool(self._by_handle)

    def __len__(self) -> int:
        return len(self._by_handle)


async def resolve_people_map(
    session: AsyncSession, *, guild_id: int, raw: Any
) -> PeopleMap:
    """Build the map the importers read from what the confirm recorded.

    ``raw`` is ``{source_handle: user_id}`` as it was stored on the job row,
    so it is JSON that round-tripped through a request: every value is
    validated rather than trusted. An id naming somebody who is not a member
    of this guild **now** is dropped and logged — the confirm proved they were
    reachable when it was made, and this proves it again at the moment the
    rows are actually written.
    """
    if not isinstance(raw, dict) or not raw:
        return PeopleMap()

    wanted: dict[str, int] = {}
    for source_handle, user_id in raw.items():
        if not isinstance(source_handle, str):
            continue
        try:
            wanted[handle_key(source_handle)] = int(user_id)
        except (TypeError, ValueError):
            continue
    if not wanted:
        return PeopleMap()

    members = set(
        await guild_member_ids(
            session, guild_id=guild_id, user_ids=set(wanted.values())
        )
    )
    resolved = {
        handle: user_id for handle, user_id in wanted.items() if user_id in members
    }
    dropped = len(wanted) - len(resolved)
    if dropped:
        logger.info(
            "import people map dropped %s entr%s naming non-members guild=%s",
            dropped,
            "y" if dropped == 1 else "ies",
            guild_id,
        )
    return PeopleMap(resolved)


async def guild_member_ids(
    session: AsyncSession, *, guild_id: int, user_ids: set[int]
) -> list[int]:
    """Which of these accounts are members of this guild, as the caller can
    see it. Read on the routed session, so RLS answers the question."""
    from app.models.platform.guild import GuildMembership

    if not user_ids:
        return []
    return list(
        await session.exec(
            select(GuildMembership.user_id).where(
                GuildMembership.guild_id == guild_id,
                GuildMembership.user_id.in_(user_ids),
            )
        )
    )


def initiative_member_id(
    handle: str | None,
    *,
    people: PeopleMap,
    member_handles: Mapping[str, int],
) -> int | None:
    """Which account a source handle names as somebody working on the thing:
    an assignee, an attendee, a person property.

    The account somebody mapped this handle to in the wizard's people step,
    else a member of the target initiative whose handle is the same string. A
    mapped account need not be in the initiative yet: naming them on an
    imported tool brings them in, as :func:`bring_in_named` settles once the
    tool is written.

    Returns ``None`` when neither answer lands, and the caller counts the
    handle as unmatched.
    """
    if not handle:
        return None
    mapped = people.user_id(handle)
    if mapped is not None:
        return mapped
    return member_handles.get(handle_key(handle))


async def bring_in_named(
    session: AsyncSession, governing: named_people.Governing, *, initiative_id: int
) -> set[int]:
    """Let everyone an imported tool names open it, and answer who could not.

    Somebody named on what an import brings in is somebody the importer means
    to work on it. So a person outside the initiative is added to it as a
    member, where the importer manages the initiative, and the tool is shared
    with everyone it names at read. Anybody who still cannot open it (the
    importer could not add them, or their role does not show the tool) is
    taken off it, and returned.
    """
    named = await named_people.named_on(session, governing)
    if not named:
        return set()
    members = set(
        (
            await session.exec(
                select(InitiativeMember.user_id).where(
                    InitiativeMember.initiative_id == initiative_id,
                    InitiativeMember.user_id.in_(named),
                )
            )
        ).all()
    )
    context = require_guild_context(session)
    if (
        context.holds_surface(AdminSurface.initiatives)
        or initiative_id in context.manager_initiatives
    ):
        role = await initiatives_service.get_member_role(
            session, initiative_id=initiative_id
        )
        joining = (
            named
            - members
            - await named_people.readers(session, governing, named - members)
        )
        session.add_all(
            InitiativeMember(
                initiative_id=initiative_id,
                user_id=user_id,
                role_id=role.id if role is not None else None,
            )
            for user_id in joining
        )
        members |= joining
    shared = members - await named_people.readers(session, governing, members)
    session.add_all(
        ResourceGrant(
            resource_type=governing.tool.value,
            resource_id=governing.resource_id,
            user_id=user_id,
            level=ResourceAccessLevel.read,
            initiative_id=initiative_id,
        )
        for user_id in shared
    )
    await session.flush()
    gone = await named_people.sweep(session, governing)
    if gone & shared:
        # Shared with, and still unable to open it: the grant does nothing.
        await session.exec(
            sa_delete(ResourceGrant).where(
                ResourceGrant.resource_type == governing.tool.value,
                ResourceGrant.resource_id == governing.resource_id,
                ResourceGrant.user_id.in_(gone & shared),
            )
        )
    return gone


def quoted_account(
    handle: str | None,
    *,
    people: PeopleMap,
    member_handles: Mapping[str, int],
) -> int | None:
    """Who a handle quoted in some writing — its author, somebody it
    mentions — is here.

    The account the people step mapped it to, else a member of the target
    initiative whose handle is the same string. Unlike
    :func:`initiative_member_id` the mapped account need not be in the
    initiative: who wrote or was named in something is a fact about the past,
    and can be recorded about anybody the community knows.
    """
    if not handle:
        return None
    mapped = people.user_id(handle)
    if mapped is not None:
        return mapped
    return member_handles.get(handle_key(handle))


def user_reference_handles(payload: Any) -> list[str]:
    """Every handle a user-type property value in ``payload`` names.

    ``payload`` is an envelope as plain data — a dict from a zip, or a model
    dumped to JSON — walked whole, because property values sit at different
    depths in different tools' envelopes (a task's, a file's, an event's)
    and all of them are the same shape: ``property_type`` of
    ``user_reference`` beside a ``value_handle``.

    First-seen order, one entry per person, keyed the way handles are
    matched. It is the inventory half of the people step: whoever a value
    names has to be asked about, or it resolves by name alone.
    """
    found: dict[str, str] = {}

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("property_type") == "user_reference":
                handle = node.get("value_handle")
                if isinstance(handle, str) and handle.strip():
                    found.setdefault(handle_key(handle), handle.strip())
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(payload)
    return list(found.values())
