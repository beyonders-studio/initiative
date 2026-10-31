from datetime import datetime, timezone
from enum import Enum
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import Column, DateTime, Integer, String
from sqlmodel import Field, SQLModel
from pydantic import ConfigDict


class OIDCMappingTargetType(str, Enum):
    guild = "guild"
    initiative = "initiative"


class ClaimRuleAuthor(str, Enum):
    """Who wrote a rule, and so who may change it.

    A community writes rules for itself on its own Security tab. The platform
    writes a provider's rules, which place people in whichever community they
    name where that community lets them (or the deployment says they apply
    everywhere). Each surface reads and writes only its own author's rows.
    """

    community = "community"
    provider = "provider"


class OIDCClaimMapping(SQLModel, table=True):
    __tablename__ = "oidc_claim_mappings"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: Optional[int] = Field(default=None, primary_key=True)
    #: Whose claim this rule reads. Two providers spell their groups their own
    #: way, so a rule is about one of them; the sign-in that evaluates rules
    #: evaluates only the ones belonging to the provider it came through.
    provider_id: int = Field(
        sa_column=Column(
            Integer,
            sa.ForeignKey("auth_providers.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    #: Who wrote the rule — see :class:`ClaimRuleAuthor`.
    author: ClaimRuleAuthor = Field(
        default=ClaimRuleAuthor.community,
        sa_column=Column(String(16), nullable=False, server_default="community"),
    )
    #: The group the rule places. Null only on a provider rule that names a
    #: directory instead, which places everybody arriving from it.
    claim_value: Optional[str] = Field(
        default=None,
        max_length=500,
        sa_column=Column(String(500), nullable=True),
    )
    #: On a provider rule, the verified claim and value that name which of the
    #: provider's directories the rule is about — for a provider that signs in
    #: people from more than one, such as a bridge in front of several. Both or
    #: neither.
    scope_claim: Optional[str] = Field(
        default=None, sa_column=Column(String(64), nullable=True)
    )
    scope_value: Optional[str] = Field(
        default=None, sa_column=Column(String(256), nullable=True)
    )
    #: Whether the rule also places people in one of the community's
    #: initiatives. Which one is the community's own, kept in its schema under
    #: the rule's id (``claim_rule_initiatives``) and read there.
    target_type: OIDCMappingTargetType = Field(
        sa_column=Column(String(20), nullable=False),
    )
    guild_id: int = Field(
        sa_column=Column(
            Integer,
            sa.ForeignKey("guilds.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    guild_role: str = Field(
        max_length=20,
        sa_column=Column(String(20), nullable=False, server_default="member"),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
