from typing import Optional, TYPE_CHECKING

from sqlalchemy import BigInteger, Column, ForeignKey, Integer, String
from sqlmodel import Field, SQLModel, Relationship
from pydantic import ConfigDict

if TYPE_CHECKING:  # pragma: no cover
    from app.models.platform.guild import Guild


class GuildAdministration(SQLModel, table=True):
    """Billing's half of a guild, kept off the guild row itself.

    ``public.guilds`` is a guild's **identity** — id, name, description, icon.
    Those are not private: an invite preview shows them before sign-in, every
    member's sidebar renders them, and a public directory listing will read them
    without any membership at all. This table holds the plan label a billing
    service writes and its bookkeeping. What the plan gives — the caps and the
    entitlements — is the community's paid rules (``app.core.rules``), written
    only by the deployment.

    One row per guild, created with the guild and dropped with it. No request
    path writes it: the operator endpoints run on the system engine and the
    verified billing path holds its own column-scoped grant. A guild's own
    admins read it (their settings page shows usage against the caps) and can
    write none of it.

    ``status`` deliberately stays on ``guilds``: it is consulted on every single
    guild request, and paying for a join there is not worth it.
    """

    __tablename__ = "guild_administration"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: Optional[int] = Field(default=None, primary_key=True)
    # The row is meaningless without its guild, and one guild has exactly one of
    # these — so NOT NULL, UNIQUE, and dropped with the guild.
    guild_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("guilds.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
            index=True,
        )
    )
    # Display/audit label of the paid tier (NULL = none). CONTRACT: never an
    # enforcement input — enforcement reads only the paid rules and
    # guilds.status, so the FOSS app enforces numbers, not plans. A test pins
    # tier_name to the billing surface (billing_foss_test.py).
    tier_name: Optional[str] = Field(
        default=None, sa_column=Column(String(64), nullable=True)
    )
    #: The status billing last wrote, whether or not it landed on the guild.
    #: A suspended guild takes no status from billing; lifting the suspension
    #: on a billing-managed deployment returns it here (``active`` when
    #: billing never wrote one).
    billing_status: Optional[str] = Field(
        default=None, sa_column=Column(String(16), nullable=True)
    )
    #: The version of billing's state this guild holds: a write at a version
    #: no newer than this is answered with it and changes nothing. 0 until
    #: billing first writes.
    billing_version: int = Field(
        default=0,
        sa_column=Column(BigInteger, nullable=False, server_default="0"),
    )

    guild: Optional["Guild"] = Relationship(
        back_populates="administration",
        sa_relationship_kwargs={"uselist": False},
    )
