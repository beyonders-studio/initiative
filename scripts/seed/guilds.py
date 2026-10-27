"""Communities: the shared rows, the roster, the artwork, and the route into a
community's own schema before its content is written."""

from __future__ import annotations

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.image_headers import validate_image
from app.db.schema_provisioning import provision_guild
from app.db.request_context import SystemGuild, Unattributed
from app.db.session import set_rls_context
from app.db.tenancy import GUILD_SCOPED_TABLES
from app.models.platform.guild import (
    Guild,
    CommunityCategory,
    GuildMembership,
    CommunityRole,
)
from app.models.platform.guild_image import IMAGE_SPECS
from app.models.platform.user import User
from app.services.platform import guild_images
from app.services.platform import guilds as guilds_service
from app.services.platform.app_settings import (
    get_app_settings,
    get_or_create_guild_settings,
)

from seed.common import Community, photo

#: The three communities with real content, in the order they are seeded.
#: ``primary`` is the community init_db already made; the others are created
#: here by ``creator``. Admins are also in ``members``.
COMMUNITIES: dict[str, dict] = {
    "primary": {
        "title": "Community 1: Primary Community (TTRPG Campaign)",
        "photo": "fantasy-map",
        # kael joins the community but no initiative in it: his view of it
        # must be empty (initiative RLS hides everything; content 404s).
        "members": [
            "Guildmaster Aldric",
            "Archivist Okoro",
            "Dungeon Master",
            "Thorn Ironforge",
            "Elara Moonwhisper",
            "Vex Shadowstep",
            "Seraphina Dawnlight",
            "Kael Windrunner",
            "Platform Operator",
            "Platform Support",
        ],
        "admins": ["Guildmaster Aldric", "Archivist Okoro"],
    },
    "starforge": {
        "title": "Community 2: Starforge Collective (Sci-Fi)",
        "name": "Starforge Collective",
        "description": "A science fiction tabletop campaign set in the far reaches of the galaxy",
        "creator": "Admin User",
        "photo": "robot",
        "members": [
            "Overseer Nova",
            "Finley Goldtongue",
            "Kael Windrunner",
            "Aurelia Brightshield",
            "Vex Shadowstep",
            "Elara Moonwhisper",
            "Platform Moderator",
            "Platform Member",
        ],
        "admins": ["Overseer Nova"],
    },
    "tides": {
        "title": "Community 3: Realm of Tides (Pirate Campaign)",
        "name": "Realm of Tides",
        "description": "A nautical fantasy campaign across the Shattered Seas",
        # admin3 creates (and therefore holds) this community; the platform
        # owner superuser is deliberately a plain member here.
        "creator": "Harbormaster Marisol",
        "photo": "instruments",
        "members": [
            "Archivist Okoro",
            "Admin User",
            "Finley Goldtongue",
            "Dungeon Master",
            "Thorn Ironforge",
            "Kael Windrunner",
            "Aurelia Brightshield",
            "Seraphina Dawnlight",
            "Platform Owner",
            "Platform Operator",
        ],
        "admins": ["Archivist Okoro"],
    },
}


async def open_community(
    session: AsyncSession, ids: dict[str, list], users: dict[str, User], key: str
) -> Community:
    """Make (or find) a community, seat its roster, and route into its schema.

    The order is the one every community here follows: commit the shared rows,
    provision the schema, add the roster — a shared-table write, so before
    routing — then route in to write the content.
    """
    spec = COMMUNITIES[key]
    if "name" in spec:
        guild = await create_guild(
            session,
            ids,
            name=spec["name"],
            description=spec["description"],
            creator=users[spec["creator"]],
        )
    else:
        guild = await guilds_service.get_primary_guild(session)
    await set_images(session, guild, spec["photo"])
    await session.commit()
    expunge_guild_scoped(session)
    if "name" in spec:
        await provision_guild(guild.id)
    await add_members(
        session,
        guild,
        [users[name] for name in spec["members"]],
        admins=[users[name] for name in spec["admins"]],
    )
    await set_rls_context(session, SystemGuild(guild.id))
    # Normally one row is inserted when a community is made, but the startup
    # back-fill can leave the table empty — create the row if it isn't there.
    await get_or_create_guild_settings(session, guild.id)
    return Community(key=key, session=session, ids=ids, users=users, guild=guild)


async def create_guild(
    session: AsyncSession,
    ids: dict[str, list],
    *,
    name: str,
    description: str,
    creator: User,
) -> Guild:
    """Create a guild and its creator's membership, through the service.

    So a seeded guild is built the way one made in the app is — in particular
    it gets the ``guild_administration`` companion every reader assumes
    exists. A bootstrap write with no community to be admin of yet, so it runs
    on the system engine at the bare login-role baseline.
    """
    await set_rls_context(session, Unattributed())
    guild = await guilds_service.create_guild(
        session, name=name, description=description, creator=creator
    )
    ids["guilds"].append(guild.id)
    await session.flush()
    return guild


async def add_members(
    session: AsyncSession,
    guild: Guild,
    users: list[User],
    *,
    admins: list[User] | None = None,
) -> None:
    """Add users to a guild as members, or admins where named.

    Membership rows carrying a role are a system-engine write, so any community
    routing left from a previous community is reset first.
    """
    await set_rls_context(session, Unattributed())
    admin_ids = {u.id for u in admins or []}
    for user in users:
        role = CommunityRole.admin if user.id in admin_ids else CommunityRole.member
        session.add(GuildMembership(guild_id=guild.id, user_id=user.id, role=role))
    await session.flush()


def expunge_guild_scoped(session: AsyncSession) -> None:
    """Drop guild-scoped objects from the session's identity map between guilds.

    Under schema-per-guild, ids restart per schema (every guild has Initiative
    id=1, Project id=1, ...), so one session reused across guilds collides them
    in the identity map. Shared rows (users, guilds) have global ids and stay.
    """
    sync = session.sync_session
    for obj in list(sync.identity_map.values()):
        # expunge cascades along relationships, so an object may already be
        # detached by the time the loop reaches it.
        if obj in sync and getattr(obj, "__tablename__", None) in GUILD_SCOPED_TABLES:
            sync.expunge(obj)


async def set_images(session: AsyncSession, guild: Guild, name: str) -> None:
    """Give a community an icon and a banner cut from photo ``name``, through
    the upload path itself.

    Each rendition is held to its ``IMAGE_SPECS`` entry, as an uploaded one
    is; the banner is stored as both of its renditions. Writes
    ``public.guild_images``, so the session must not be routed into a guild
    schema.
    """
    pictures = {
        variant: photo(name, spec.width, spec.height, max_bytes=spec.max_bytes)
        for variant, spec in IMAGE_SPECS.items()
    }
    renditions = {
        variant: validate_image(IMAGE_SPECS[variant], data)
        for variant, data in pictures.items()
    }
    await guild_images.set_images(session, guild_id=guild.id, renditions=renditions)


async def enable_directory(session: AsyncSession) -> None:
    """Switch the platform's community directory on; it ships off."""
    settings_row = await get_app_settings(session)
    settings_row.community_directory_enabled = True
    session.add(settings_row)
    await session.flush()


async def list_in_directory(
    session: AsyncSession, guild: Guild, *, categories: list[CommunityCategory]
) -> None:
    """Opt a community into the directory.

    A listing is the shelves plus the 18+ declaration together — the database
    refuses a listed guild missing either — and a listed guild shows handles
    rather than real names (ck_guilds_community_member_names). Writes
    ``public.guilds``, so the session must not be routed into a guild schema.
    """
    guild.is_community = True
    guild.categories = guilds_service.normalize_categories(
        [c.value for c in categories]
    )
    guild.has_adult_content = False
    session.add(guild)
    await session.flush()


async def seat_superadmin(session: AsyncSession, user: User) -> int:
    """Seat one account as ``superadmin`` of every community in the database.

    One pass over ``public.guilds`` rather than an argument threaded through
    each community's membership call, so a community added to this seeder later
    is covered — the primary community included, which the seed finds rather
    than creates. Idempotent: a re-run leaves the rows it already wrote.
    """
    await set_rls_context(session, Unattributed())
    guild_ids = (await session.exec(select(Guild.id).order_by(Guild.id))).all()
    seated = 0
    for guild_id in guild_ids:
        existing = (
            await session.exec(
                select(GuildMembership).where(
                    GuildMembership.guild_id == guild_id,
                    GuildMembership.user_id == user.id,
                )
            )
        ).first()
        if existing is not None:
            if existing.role != CommunityRole.superadmin:
                existing.role = CommunityRole.superadmin
                session.add(existing)
            continue
        session.add(
            GuildMembership(
                guild_id=guild_id, user_id=user.id, role=CommunityRole.superadmin
            )
        )
        seated += 1
    await session.flush()
    return seated
