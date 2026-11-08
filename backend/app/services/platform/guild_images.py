"""Guild icons and banners: who may see one, and how they are stored.

These are the only guild media a stranger can be shown. A listed guild's icon
and its banner's card rendition appear on its community-directory card, which
is served to any signed-in user; the full banner appears on the guild's own
front page, which is not. That asymmetry is the whole of this module:

    published variants (icon, card) — the guild listed itself, OR you belong
    the rest (full)                 — you belong
    neither                         — nothing exists as far as you are concerned

"belong" throughout includes a live PAM/break-glass grantee, who reaches the
guild for their window exactly as a member does. Which variants are published
is read from ``PUBLISHED_VARIANTS`` rather than restated here, so adding one is
a single edit beside the registry.

The check runs on the system engine for the reason the directory itself does:
the caller is a stranger to the guild, so there is no guild-scoped role to read
it under, and ``public.guilds`` is scoped by RLS to the caller's own
memberships. The request path holds no grant on the image bytes at all — this
function is their only reader, which is why the rule lives here in one piece
rather than spread across the endpoints that serve it.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import insert
from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.image_headers import ValidatedImage
from app.models.platform.guild import LIVE_STATUS_VALUES, Guild
from app.models.platform.guild_image import (
    PUBLISHED_VARIANTS,
    GuildImage,
    GuildImageVariant,
)

# --- reading -----------------------------------------------------------------


async def may_read_image(
    session: AsyncSession,
    *,
    guild_id: int,
    user_id: int,
    variant: GuildImageVariant,
) -> bool:
    """Whether ``user_id`` has somewhere to see this variant.

    Membership is checked first because it answers for every variant and is the
    common case. The listing leg is asked of the directory itself rather than
    inherited from whatever page produced the URL, so a guild that stops being
    listed stops serving its card in the same instant.
    """
    from app.services.platform import access_grants as access_grants_service
    from app.services.platform import guilds as guilds_service

    membership = await guilds_service.get_membership(
        session, guild_id=guild_id, user_id=user_id
    )
    if membership is not None:
        # A guild that is not live is unreadable to its own members,
        # matching the uploads route and the guild-context resolver.
        guild = await session.get(Guild, guild_id)
        return guild is not None and guild.status in LIVE_STATUS_VALUES

    if await access_grants_service.get_live_grants(
        session, user_id=user_id, guild_id=guild_id
    ):
        # PAM deliberately overrides lifecycle status, as everywhere else. A
        # grant of either purpose: the pictures are what the guild's front page
        # shows and part of the configuration its settings hold.
        return True

    if variant not in PUBLISHED_VARIANTS:
        return False
    # The directory's own question, not a copy of it: what a guild publishes by
    # being listed stops being published the moment it stops being listed —
    # including when an operator drops it below the seat floor, which is a way
    # out of the directory that has nothing to do with the guild.
    return await guilds_service.is_listed_in_directory(session, guild_id=guild_id)


async def read_image(
    session: AsyncSession, *, guild_id: int, sha256: str
) -> GuildImage | None:
    """The guild's image with these exact bytes, or None.

    Addressed by digest rather than by variant so a URL minted for an image
    that has since been replaced resolves to nothing, instead of serving
    different bytes under a cache key the browser was told is immutable.
    """
    return (
        await session.exec(
            select(GuildImage).where(
                GuildImage.guild_id == guild_id,
                GuildImage.sha256 == sha256,
            )
        )
    ).first()


def image_url(guild_id: int, sha256: str) -> str:
    """The serving URL for one image.

    A platform path, not ``/c/{community_id}/…``: these are public-plane identity,
    and the caller they are served to may hold no guild context at all.
    """
    return f"/api/v1/communities/{guild_id}/image/{sha256}"


async def image_urls(
    session: AsyncSession,
    guild_ids: list[int] | set[int],
    *variants: GuildImageVariant,
) -> dict[int, dict[GuildImageVariant, str]]:
    """``guild_id -> {variant: URL}`` across many guilds, in one query.

    Projected to the digest alone. A list payload names images; it never
    carries them, so this must not drag a page's worth of bytes through the ORM
    to build a page's worth of strings.
    """
    ids = [int(value) for value in guild_ids]
    if not ids or not variants:
        return {}
    wanted = [variant.value for variant in variants]
    rows = await session.exec(
        select(GuildImage.guild_id, GuildImage.variant, GuildImage.sha256).where(
            GuildImage.guild_id.in_(ids),
            GuildImage.variant.in_(wanted),
        )
    )
    found: dict[int, dict[GuildImageVariant, str]] = {}
    for guild_id, variant, digest in rows:
        found.setdefault(guild_id, {})[GuildImageVariant(variant)] = image_url(
            guild_id, digest
        )
    return found


async def image_urls_for(
    session: AsyncSession, guild_id: int, *variants: GuildImageVariant
) -> dict[GuildImageVariant, str]:
    """One guild's URLs, keyed by variant; missing variants are simply absent."""
    return (await image_urls(session, [guild_id], *variants)).get(guild_id, {})


# --- writing -----------------------------------------------------------------


async def set_images(
    session: AsyncSession,
    *,
    guild_id: int,
    renditions: dict[GuildImageVariant, ValidatedImage],
) -> dict[GuildImageVariant, str]:
    """Replace exactly the variants named by ``renditions``. Returns their URLs.

    Only those variants are touched: setting a guild's icon leaves its banner
    alone, and the two banner renditions are replaced together so a guild is
    never left showing a new card over an old front page.

    Written as statements rather than through the ORM, and in that order: a row
    here is only ever created or dropped, never edited — the primary key is
    (guild, variant), so "replace" means the old row leaves before the new one
    arrives. Handing both to the unit of work would let it reorder them, or
    reconcile them into an UPDATE, which is a statement this table grants
    nobody.
    """
    await clear_images(session, guild_id=guild_id, variants=list(renditions))
    now = datetime.now(UTC)
    rows = [
        {
            "guild_id": guild_id,
            "variant": variant.value,
            "sha256": image.sha256,
            "content_type": image.content_type,
            "byte_size": image.byte_size,
            "data": image.data,
            "created_at": now,
        }
        for variant, image in renditions.items()
    ]
    if rows:
        await session.exec(insert(GuildImage).values(rows))
    return {
        variant: image_url(guild_id, image.sha256)
        for variant, image in renditions.items()
    }


async def clear_images(
    session: AsyncSession,
    *,
    guild_id: int,
    variants: list[GuildImageVariant],
) -> int:
    """Remove the named variants of this guild's images. Returns how many.

    One statement, and deliberately not the ORM's load-then-delete: the rows
    hold the pictures, so loading them in order to throw them away would pull a
    third of a megabyte through the process for nothing.
    """
    if not variants:
        return 0
    result = await session.exec(
        delete(GuildImage).where(
            GuildImage.guild_id == guild_id,
            GuildImage.variant.in_([variant.value for variant in variants]),
        )
    )
    return int(result.rowcount or 0)
