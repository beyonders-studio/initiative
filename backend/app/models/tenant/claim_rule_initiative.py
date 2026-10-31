"""Where a sign-in rule places somebody inside the community: one of its
initiatives, at one of that initiative's roles.

The rule itself is ``public.oidc_claim_mappings``, which the sign-in reads
across communities to say which ones a person lands in. Which initiative it
names is read only once the sign-in is inside the community, so it is kept here,
beside the initiatives, under the rule's id and the version the rule names
(``placement_version``). Its keys hold it to an initiative and a role of that
initiative: deleting either deletes the row, and the rule goes on placing
people in the community alone.
"""

from sqlalchemy import Column, ForeignKey, ForeignKeyConstraint, Integer
from sqlmodel import Field, SQLModel


class ClaimRuleInitiative(SQLModel, table=True):
    __tablename__ = "claim_rule_initiatives"
    __table_args__ = (
        # The role is the initiative's own.
        ForeignKeyConstraint(
            ["initiative_role_id", "initiative_id"],
            ["initiative_roles.id", "initiative_roles.initiative_id"],
            ondelete="CASCADE",
            name="fk_claim_rule_initiatives_role",
        ),
    )

    #: A ``public.oidc_claim_mappings`` id, which no key in a community's
    #: schema reaches. Deleting the rule deletes this row with it.
    rule_id: int = Field(
        sa_column=Column(Integer, primary_key=True, autoincrement=False)
    )
    #: Moving a rule writes its next version here before the rule names it,
    #: so a sign-in reads the place that goes with the claims it matched.
    version: int = Field(
        default=0, sa_column=Column(Integer, primary_key=True, autoincrement=False)
    )
    initiative_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("initiatives.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    initiative_role_id: int = Field(
        sa_column=Column(Integer, nullable=False, index=True)
    )
