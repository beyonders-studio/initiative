from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlmodel import Field, SQLModel


class GuildProviderConnection(SQLModel, table=True):
    """A community signing its members in through one of the platform's
    providers, optionally narrowed to its own tenant.

    The division of labour: **the operator holds providers, a community
    connects to one.** An operator says this deployment can sign people in
    with Google; a community says its members come in through that, and only
    its own workspace. A community holds no issuer, no client id and no
    secret — so it names no address the deployment will fetch, and there is no
    provider configuration for it to get wrong on behalf of its members.

    A community bringing its own identity provider is the same shape: the
    operator registers it when they onboard them, and the community connects
    to it. Every row in ``auth_providers`` is the operator's.

    A connection says two things at once, because a community says both in
    one breath: which arrivals count as its own (``claim``/``claim_values``),
    and whether they join on arrival (``auto_join``).

    Lives in ``public`` beside the registry it points into. Written on the
    system engine; the request path reads it, scoped by policy to the reader's
    own community, because the guild-access gate consults the narrowing on
    every request rather than trusting an answer worked out at sign-in.
    """

    __tablename__ = "guild_provider_connections"
    __table_args__ = (
        # A community connects to a given provider once. Two different
        # narrowings of the same provider would be two answers to one
        # question.
        UniqueConstraint(
            "guild_id", "provider_id", name="uq_guild_provider_connections_pair"
        ),
    )

    id: int | None = Field(default=None, primary_key=True)

    guild_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("guilds.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    #: RESTRICT, for the reason the sign-in requirement uses it: withdrawing a
    #: provider a community signs in through has to surface the conflict, not
    #: quietly change who can get in.
    provider_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("auth_providers.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        )
    )

    #: Which verified claim decides whether somebody arriving through this
    #: provider belongs to this community — ``hd`` for a Google Workspace
    #: domain, ``tid`` for an Entra tenant. NULL together with
    #: ``claim_values`` admits nobody. A community says who on a provider
    #: counts as its own; saying nothing is not a way of saying everybody.
    #: An enabled connection is refused without both, and a disabled one may
    #: hold neither — that is how a community declines the deployment's
    #: default, and it admits nobody by being disabled.
    claim: str | None = Field(default=None, sa_column=Column(String(64), nullable=True))
    #: The values that admit somebody. Any one of them is enough.
    claim_values: list[str] | None = Field(
        default=None, sa_column=Column(ARRAY(String(256)), nullable=True)
    )

    #: Off keeps the connection and its narrowing while taking the button off
    #: the community's sign-in page.
    enabled: bool = Field(
        sa_column=Column(Boolean, nullable=False, server_default=text("true"))
    )

    #: Whether arriving through this connection joins somebody to the
    #: community. A community that admits its own people and still wants to
    #: choose who joins leaves it off.
    auto_join: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=text("false")),
    )

    #: Whether the platform's rules for this provider may place people in this
    #: community, beside the rules the community writes itself.
    accepts_provider_placement: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=text("false")),
    )

    #: When somebody outside the community agreed that these values are its
    #: to claim, and who. A community names its own ``claim_values`` and
    #: nothing here can tell whether it holds the domain or tenant they
    #: describe, so the answer comes from the deployment: support, through a
    #: case it raises, or the operator on the community's own page.
    #:
    #: Tied to the values rather than to the row — changing ``claim`` or
    #: ``claim_values`` clears it, so an agreement is always an agreement about
    #: what is written here now. ``auto_join`` waits for it; admitting people
    #: the community already has does not.
    narrowing_approved_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    narrowing_approved_by: int | None = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
    )

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

    def admits(self, claims: dict) -> bool:
        """Whether a verified id_token belongs to this community.

        A connection names a claim and the values that count, or it admits
        nobody: an arrangement that has not said who belongs is not read as
        everybody. A narrowed one reads the claim it names and asks whether
        the value is one of its own — the same dot-path reader the group rules
        use, so a nested claim works here too.

        Mirrors ``public.guild_connection_admits``; the two are one rule and
        a change to either belongs in both.
        """
        return narrowing_admits(self.claim, self.claim_values, claims)


def narrowing_admits(
    claim: str | None, claim_values: list[str] | None, claims: dict
) -> bool:
    """Whether a narrowing — a claim and the values that count — admits a set
    of verified claims.

    The rule behind ``GuildProviderConnection.admits``, stated once so the
    deployment's default for a provider, which narrows the same way, is read
    by it too. A narrowing that names no claim or no values admits nobody.
    """
    if not claim or not claim_values:
        return False
    # Imported here: the sync service imports models, not the other way.
    from app.services.oidc_sync import extract_claim_values

    found = extract_claim_values(claims, None, claim)
    return any(value.strip().lower() in found for value in claim_values)
