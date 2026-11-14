from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlmodel import Field, SQLModel


class PlatformProviderDefault(SQLModel, table=True):
    """How one provider is arranged for a community that has not said.

    Some deployments are one organisation: one identity provider, one tenant,
    and communities that are its teams. Asking each of two hundred teams to
    repeat the same arrangement makes the operator their queue, which is the
    thing this design is built to avoid. So an operator may answer once, and a
    community inherits the answer until it gives its own.

    **The unit of override is the connection.** A community's own row in
    ``guild_provider_connections`` shadows this one entirely — one row
    shadowing one row, nothing to merge — and that includes a community
    connecting with ``enabled`` off, which is how it declines a default. What
    the community says wins outright, because which provider is theirs and who
    on it counts as theirs is an arrangement, not a floor.

    Deliberately its own table rather than columns on ``auth_providers``. The
    gate reads this on the request path, and the registry is not readable
    there — it holds the operator's configuration, and a default holds none of
    it: a provider id, a claim name, a list of values.
    """

    __tablename__ = "platform_provider_defaults"

    #: One answer per provider, so the primary key is the provider itself.
    provider_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("auth_providers.id", ondelete="CASCADE"),
            primary_key=True,
        )
    )

    #: Which verified claim decides whether an arrival belongs, for a community
    #: that has not narrowed this provider itself. NULL together with
    #: ``claim_values`` inherits nothing to check, which is right where the
    #: deployment's provider already holds only its own people.
    claim: str | None = Field(default=None, sa_column=Column(String(64), nullable=True))
    claim_values: list[str] | None = Field(
        default=None, sa_column=Column(ARRAY(String(256)), nullable=True)
    )

    #: Off keeps the arrangement while withdrawing it — no community inherits
    #: it, and the ones that wrote their own are untouched.
    enabled: bool = Field(
        sa_column=Column(Boolean, nullable=False, server_default=text("true"))
    )

    # There is deliberately no ``auto_join`` here. A default is per provider
    # and names no community, so joining on it would place an arrival in every
    # community that had not spoken — and a community deciding who joins it is
    # exactly the decision this design leaves with the community. A community
    # that wants it writes its own connection, seeded from this.

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            onupdate=lambda: datetime.now(UTC),
        ),
    )
