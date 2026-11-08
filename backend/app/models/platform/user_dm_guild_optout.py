"""The communities an account has switched off for direct messages.

A row means **off**. Storing the exceptions rather than a row per (account,
community) is what makes "all on by default" true by construction: a community
joined tomorrow counts with no write, leaving one drops the row through the
foreign key, and the table stays empty for everyone who never touched a toggle.

Only consulted while the account's policy is ``community``. Rows survive the
policy moving away and back, so a week on ``public`` does not cost somebody
their list.
"""

from datetime import UTC, datetime

from pydantic import ConfigDict
from sqlalchemy import Column, DateTime, ForeignKey, Integer
from sqlmodel import Field, SQLModel


class UserDmGuildOptout(SQLModel, table=True):
    __tablename__ = "user_dm_guild_optouts"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    user_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        )
    )
    guild_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("guilds.id", ondelete="CASCADE"),
            primary_key=True,
        )
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
