"""The rules the deployment and each community store. See ``app.core.rules``."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, ENUM as PGEnum
from sqlmodel import Field, SQLModel

from app.core.login_methods import LoginMethod

#: A row holds its value in exactly one slot; ``app.core.rules`` says which.
_ONE_SLOT = "num_nonnulls(enabled, amount, choice, methods) = 1"
#: The deployment's ways in include one that can begin a session.
_BEGINS_A_SESSION = (
    "methods IS NULL OR methods && '{password,sso,passkey}'::login_method[]"
)
#: A community's may also hold a sign-in requirement: its methods, and beside
#: them, only there, the provider it names.
_ONE_COMMUNITY_SLOT = (
    "num_nonnulls(enabled, amount, methods) = 1"
    " AND (provider_id IS NULL OR methods IS NOT NULL)"
)
#: A sign-in requirement asks for something, and never for a password or an
#: emailed code: whether those exist is the deployment's question.
_REQUIREMENT = (
    "methods IS NULL OR ("
    "NOT ('password'::login_method = ANY (methods))"
    " AND NOT ('email_otp'::login_method = ANY (methods))"
    " AND (provider_id IS NOT NULL OR cardinality(methods) > 0))"
)


def _updated_at() -> Column:
    return Column(
        DateTime(timezone=True),
        nullable=False,
        onupdate=lambda: datetime.now(timezone.utc),
    )


def _methods() -> Column:
    return Column(
        ARRAY(PGEnum(LoginMethod, name="login_method", create_type=False)),
        nullable=True,
    )


class RuleChoice(SQLModel, table=True):
    """One value a ``choice`` rule may take (``app.core.rules.choices``).

    Written by the migrations, with the rule it belongs to, and held to the
    catalog by ``rules_test``. Read by nothing but the foreign key that
    holds each ``choice`` to its own rule's values.
    """

    __tablename__ = "rule_choices"

    key: str = Field(sa_column=Column(String(64), primary_key=True))
    value: str = Field(sa_column=Column(String(64), primary_key=True))


class RuleKeyWriter(SQLModel, table=True):
    """Who may write one community rule: the community, the deployment, or
    both (``app.core.rules.writers``). A paid key has the deployment alone.

    Written by the migrations, with the rule it belongs to, and held to the
    catalog by ``rules_test``. Read by nothing but the foreign key that holds
    each community row's ``(key, set_by)`` to them.
    """

    __tablename__ = "rule_key_writers"

    key: str = Field(sa_column=Column(String(64), primary_key=True))
    set_by: str = Field(sa_column=Column(String(16), primary_key=True))


class PlatformRule(SQLModel, table=True):
    """One of the deployment's rules that says something other than its
    default."""

    __tablename__ = "platform_rules"
    __table_args__ = (
        CheckConstraint(_ONE_SLOT, name="ck_platform_rules_one_slot"),
        CheckConstraint(_BEGINS_A_SESSION, name="ck_platform_rules_begins_a_session"),
        ForeignKeyConstraint(
            ["key", "choice"],
            ["rule_choices.key", "rule_choices.value"],
            name="fk_platform_rules_choice",
        ),
    )

    key: str = Field(sa_column=Column(String(64), primary_key=True))
    enabled: Optional[bool] = Field(
        default=None, sa_column=Column(Boolean, nullable=True)
    )
    amount: Optional[int] = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    choice: Optional[str] = Field(
        default=None, sa_column=Column(String(64), nullable=True)
    )
    methods: Optional[list[str]] = Field(default=None, sa_column=_methods())
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), sa_column=_updated_at()
    )


class CommunityRule(SQLModel, table=True):
    """One of a community's rules that says something other than its default,
    for the whole community or for one member of it, written by the community
    or by the deployment (``set_by``). A deployment row wins.

    Goes with its community, and a member's with their membership.
    """

    __tablename__ = "community_rules"
    __table_args__ = (
        CheckConstraint(_ONE_COMMUNITY_SLOT, name="ck_community_rules_one_slot"),
        CheckConstraint(_REQUIREMENT, name="ck_community_rules_requirement"),
        # Every figure a community's rule holds is a count, a size or a
        # length: none is below zero.
        CheckConstraint(
            "amount IS NULL OR amount >= 0",
            name="ck_community_rules_amount_nonnegative",
        ),
        ForeignKeyConstraint(
            ["guild_id", "user_id"],
            ["guild_memberships.guild_id", "guild_memberships.user_id"],
            ondelete="CASCADE",
            name="fk_community_rules_member",
        ),
        ForeignKeyConstraint(
            ["key", "set_by"],
            ["rule_key_writers.key", "rule_key_writers.set_by"],
            name="fk_community_rules_writer",
        ),
        UniqueConstraint(
            "guild_id",
            "key",
            "user_id",
            "set_by",
            name="uq_community_rules_subject",
            postgresql_nulls_not_distinct=True,
        ),
    )

    id: Optional[int] = Field(
        default=None, sa_column=Column(BigInteger, Identity(), primary_key=True)
    )
    guild_id: int = Field(
        sa_column=Column(
            Integer, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False
        )
    )
    key: str = Field(sa_column=Column(String(64), nullable=False))
    #: The member the row is about, or ``None`` for the whole community.
    user_id: Optional[int] = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    #: Who wrote it (``app.core.rules.SetBy``).
    set_by: str = Field(
        default="community",
        sa_column=Column(String(16), nullable=False, server_default="community"),
    )
    enabled: Optional[bool] = Field(
        default=None, sa_column=Column(Boolean, nullable=True)
    )
    #: Wide enough for a storage cap in bytes.
    amount: Optional[int] = Field(
        default=None, sa_column=Column(BigInteger, nullable=True)
    )
    methods: Optional[list[str]] = Field(default=None, sa_column=_methods())
    #: RESTRICT: deleting a provider a community requires must surface the
    #: conflict, never silently reopen the community.
    provider_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("auth_providers.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), sa_column=_updated_at()
    )
