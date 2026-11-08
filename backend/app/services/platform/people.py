"""What the people roster reads.

The rosters of the reader's own guilds, gathered the way every other ``/me``
aggregate is: one routed visit per guild, via ``gather_across_guilds``.
"""

from collections.abc import Iterable, Sequence

from sqlalchemy import exists, func, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.db.query import apply_pagination, ids_in, page_has_next
from app.db.request_context import Platform
from app.db.session import set_rls_context
from app.models.platform.guild import (
    LIVE_STATUS_VALUES,
    CommunityRole,
    Guild,
    GuildMembership,
)
from app.models.platform.guild_image import GuildImageVariant
from app.models.platform.user import User, UserStatus
from app.models.platform.user_profile_view import MemberProfile
from app.schemas.platform.people import (
    PeopleCommunitySection,
    PersonRead,
)
from app.services.cross_guild import gather_across_guilds
from app.services.membership import live_membership_clause
from app.services.platform import guild_images as guild_images_service
from app.services.platform import presence as presence_service
from app.services.platform import users as users_service

#: Members per guild section. Small enough that somebody in a dozen guilds gets
#: a sane first response, and every section pages from there.
DEFAULT_PAGE_SIZE = 20

#: ``(guild_id, name, icon_url)`` — one of the reader's guilds, as a section.
GuildRow = tuple[int, str, str | None]


async def ordered_member_guilds(
    session: AsyncSession, *, user_id: int
) -> list[GuildRow]:
    """The reader's guilds in rail order.

    ``GuildMembership.position`` is the order they dragged the rail into, so
    this is the same rule the rail uses rather than a second one. A suspended
    guild is left out, matching ``member_guild_ids`` and the ``/c/{community_id}``
    path it stands in for, and so is one the reader is only a guest of: a guest
    reads nobody's place in it.
    """
    await set_rls_context(session, Platform(user_id=user_id))
    rows = (
        await session.exec(
            select(Guild.id, Guild.name)
            .join(GuildMembership, GuildMembership.guild_id == Guild.id)
            .join(User, User.id == GuildMembership.user_id)
            .where(
                GuildMembership.user_id == user_id,
                GuildMembership.role != CommunityRole.guest,
                live_membership_clause(),
                Guild.status.in_(LIVE_STATUS_VALUES),
                User.status != UserStatus.suspended,
            )
            .order_by(col(GuildMembership.position).asc(), col(Guild.id).asc())
        )
    ).all()
    # One query for every section's icon, projected to the digest — a list
    # payload names images rather than carrying them.
    icons = await guild_images_service.image_urls(
        session, [row[0] for row in rows], GuildImageVariant.icon
    )
    return [
        (row[0], row[1], icons.get(row[0], {}).get(GuildImageVariant.icon))
        for row in rows
    ]


def _reads(users: Iterable[MemberProfile]) -> list[PersonRead]:
    """Validate inside the caller's current guild context.

    Each ``MemberProfile`` was read in its guild's routed context, so its
    ``display_name`` is the name the person set there.
    """
    reads = []
    for user in users:
        read = PersonRead.model_validate(user)
        read.presence = presence_service.online.presence_of(user.id)
        reads.append(read)
    return reads


async def guild_sections(
    session: AsyncSession,
    *,
    user_id: int,
    guilds: Sequence[GuildRow],
    search: str | None = None,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> list[PeopleCommunitySection]:
    """One section per guild, in the order given.

    Each guild is visited in its own routed context, which is what makes both
    reads below possible: ``guild_memberships`` answers for the current guild
    there, and ``display_name`` is the name each person set in that guild.
    """
    if not guilds:
        return []

    sections: dict[int, PeopleCommunitySection] = {}
    # The guilds the walk below could enter; one it cannot reach right now
    # contributes nothing, section or shared membership.
    visited: set[int] = set()
    named = {gid: (name, icon) for gid, name, icon in guilds}

    # Who, of each community, this reader may actually reach — asked here, on
    # the platform-tier session, because that is the only role the rule is
    # callable from. It has to happen before the walk below, which routes this
    # same session into each guild in turn.
    listable = await listable_by_guild(
        session, user_id=user_id, guilds=[gid for gid, _n, _i in guilds]
    )

    async def _fetch(guild_session: AsyncSession, guild_id: int) -> list[int]:
        visited.add(guild_id)

        # A community of one is not a section. Nobody is in it to list, and an
        # empty section there would read as a remark about people who are not
        # there — the reader is by themselves, which the page should not
        # dress up as everybody being unreachable.
        if not (
            await guild_session.exec(
                select(
                    exists().where(
                        GuildMembership.guild_id == guild_id,
                        GuildMembership.user_id != user_id,
                    )
                )
            )
        ).one():
            return []

        # Read from the guild projection, not from ``users``: this is a roster,
        # and a routed session has no reach into the account row behind it. The
        # predicates below already speak this shape — selecting the account and
        # filtering the projection is what left the two unjoined.
        base = users_service.guild_members(
            select(MemberProfile), guild_id=guild_id
        ).where(
            # You are not on your own roster.
            MemberProfile.id != user_id,
            # And everyone on it is somebody you could actually reach out to.
            ids_in(MemberProfile.id, listable.get(guild_id, set())),
        )
        closest = None
        if search and (term := search.strip()):
            # The name each guild shows, so the same person can be found by name
            # in one of the reader's communities and not in another.
            matches, closest = users_service.member_match(term)
            base = base.where(matches)

        total = (
            await guild_session.exec(select(func.count()).select_from(base.subquery()))
        ).one()

        rows = (
            await guild_session.exec(
                apply_pagination(
                    base.order_by(
                        *users_service.member_order(closest),
                        col(MemberProfile.username).asc(),
                        col(MemberProfile.discriminator).asc(),
                        col(MemberProfile.id).asc(),
                    ),
                    page,
                    page_size,
                )
            )
        ).all()

        name, icon = named[guild_id]
        sections[guild_id] = PeopleCommunitySection(
            community_id=guild_id,
            community_name=name,
            icon_url=icon,
            total_count=total,
            items=_reads(rows),
            has_next=page_has_next(page, page_size, total),
        )
        return []

    guild_ids = [gid for gid, _name, _icon in guilds]
    await gather_across_guilds(session, {user_id: guild_ids}, _fetch)

    # Which of the reader's guilds each listed person is also in, which the
    # paged rows cannot say: a person may be on page 1 of one section and page
    # 3 of another. Whether two people may message each other does not depend
    # on the guild, so anyone on a page is listable in exactly the reader's
    # guilds they belong to.
    shared: dict[int, list[int]] = {}
    for guild_id in guild_ids:
        if guild_id in visited:
            for member_id in listable.get(guild_id, ()):
                shared.setdefault(member_id, []).append(guild_id)

    ordered = [sections[gid] for gid in guild_ids if gid in sections]
    for section in ordered:
        for item in section.items:
            item.shared_community_ids = shared.get(item.id, [])
    return ordered


async def listable_by_guild(
    session: AsyncSession, *, user_id: int, guilds: Sequence[int]
) -> dict[int, set[int]]:
    """Per community, the members this reader may ask to message.

    One call per section rather than one per member: the rule does the join
    itself, so nothing large crosses the boundary in either direction.

    Deliberately **not** narrowed by who has ignored the reader: an ignore
    governs what arrives, not who is listed, so both rosters stay as they were.

    Nobody is listed where the deployment offers no direct messages: a person
    listed is somebody you could reach out to, and there is nothing to reach them
    with. Asked here, alongside the routes that refuse, because this is the one
    surface built on the messaging rule that is not itself a messaging route.
    """
    from app.services.platform import app_settings as app_settings_service

    if not await app_settings_service.direct_messages_enabled(session):
        return {}
    # The rule reads who is asking from the request context, so this runs on
    # the caller's own session rather than being told an id.
    await set_rls_context(session, Platform(user_id=user_id))
    result: dict[int, set[int]] = {}
    for guild_id in guilds:
        rows = await session.exec(
            text("SELECT public.dm_listable_in_guild(:g)").bindparams(g=guild_id)
        )
        result[guild_id] = {row[0] for row in rows}
    return result
