"""The images a guild is known by: its icon, and its banner.

Guild identity, not guild content — the same class of thing as the guild's name
and description, and in ``public`` for the same reason those are: a guild that
lists itself in the community directory shows its card to people who are not in
it and hold no role that could read a ``guild_<id>`` schema.

Stored as bytes here rather than in the guild blob store because the public
plane has no object store to put them in: every S3 key is namespaced under a
guild, which is exactly the boundary these have to cross.
(``MarketplaceMedia`` is here for the same reason.) They therefore do not count
against the guild's storage quota.

One row per (guild, variant) — see :class:`GuildImageVariant`. Who may read
which is decided by ``app.services.platform.guild_images``, not here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

from pydantic import ConfigDict
from sqlalchemy import Column, DateTime, ForeignKey, Integer, LargeBinary, String
from sqlmodel import Field, SQLModel

from app.core.image_headers import RASTER_CONTENT_TYPES, ImageSpec


class GuildImageVariant(str, Enum):
    """The images a guild can have, and the renditions they are stored as.

    ``icon`` is the mark it is known by in a switcher, a card, a wizard. The
    two banner renditions come from one uploaded picture: ``full`` is what the
    guild's own front page shows, and ``card`` is the strip on its
    community-directory card — served to strangers and appearing up to sixty
    times on one page, which is why it is a separate, much smaller rendition
    rather than the full one scaled down in the browser.
    """

    icon = "icon"
    card = "card"
    full = "full"


#: Each variant's geometry and weight. The settings page resizes to it and the
#: upload endpoint holds an upload to it.
IMAGE_SPECS: dict[GuildImageVariant, ImageSpec] = {
    GuildImageVariant.icon: ImageSpec(256, 256, 64 * 1024, RASTER_CONTENT_TYPES),
    GuildImageVariant.card: ImageSpec(1040, 260, 60 * 1024, RASTER_CONTENT_TYPES),
    GuildImageVariant.full: ImageSpec(2400, 600, 350 * 1024, RASTER_CONTENT_TYPES),
}

#: The variants that are part of what a guild publishes by listing itself in
#: the directory, and so may be served to someone who is not in the guild. The
#: front-page banner is not — a stranger has no front page to see it on.
PUBLISHED_VARIANTS: frozenset[GuildImageVariant] = frozenset(
    {GuildImageVariant.icon, GuildImageVariant.card}
)

#: The renditions one banner upload produces, in the order they are stored.
BANNER_VARIANTS: tuple[GuildImageVariant, ...] = (
    GuildImageVariant.full,
    GuildImageVariant.card,
)


class GuildImage(SQLModel, table=True):
    __tablename__ = "guild_images"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    # CASCADE: a deleted guild takes its images with it, through the same
    # cascade off ``public.guilds`` that removes its memberships and invites.
    guild_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("guilds.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        )
    )
    variant: str = Field(sa_column=Column(String(8), primary_key=True, nullable=False))
    # Digest of these exact bytes. It is the last path segment of the serving
    # URL, so the URL changes whenever the image does and the response can be
    # cached for as long as the browser likes.
    sha256: str = Field(sa_column=Column(String(64), nullable=False))
    content_type: str = Field(sa_column=Column(String(64), nullable=False))
    byte_size: int = Field(sa_column=Column(Integer, nullable=False))
    data: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
