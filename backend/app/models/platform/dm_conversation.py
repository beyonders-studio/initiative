"""A set of accounts with an open channel, and who is on it.

The conversation row carries an id, a creation time and the roster it was made
with. There is no title, no last-message column and no unread count, because all
three would be facts about content the server does not hold -- and no title
because a thread is the people on it, which is also how it is found again.

**A roster is the identity.** ``roster_key`` is the sorted member ids as text,
written once at creation and never updated, and its unique index is what makes
"one thread per set of people" true rather than merely intended: two people
proposing the same roster at the same moment would both find nothing and both
insert, and a unique index is the same test taken at the moment it matters. It
is composite with ``kind`` so a pair's ``direct`` thread cannot contend for a
key with a group.

Never updated is the load-bearing half. Somebody leaving does not rename the
conversation and does not free the name: the thread is still there, with its
history, for the people still on it.

A membership check cannot be a plain own-row policy, because knowing who the
*other* parties are requires reading rows that are not yours.
``public.dm_in_conversation`` answers that question without handing the rows
over, on the same ``SECURITY DEFINER`` pattern the rest of the DM rules use.
"""

import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from enum import Enum

from pydantic import ConfigDict
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    Uuid,
    text,
)
from sqlmodel import Field, SQLModel


class DmConversationKind(str, Enum):
    """How many people a conversation was made for.

    Two values rather than a member count, because the count changes when
    somebody leaves and what this records does not: a group whose roster has
    shrunk to two is still a group, not the pair's own thread.
    """

    #: Exactly two accounts. One per pair, forever.
    direct = "direct"
    #: Three or more at creation. One per roster, forever.
    group = "group"


def roster_key(user_ids: Iterable[int]) -> str:
    """The identity of a roster: its member ids, sorted, comma-joined.

    Sorted so the same people produce the same key whoever proposes them, and
    de-duplicated so a caller that names somebody twice does not get a key no
    roster could ever match.
    """
    return ",".join(str(i) for i in sorted(set(user_ids)))


class DmConversation(SQLModel, table=True):
    __tablename__ = "dm_conversations"
    __table_args__ = (
        CheckConstraint("kind IN ('direct', 'group')", name="ck_dm_conversations_kind"),
        # One thread per set of people. Nulls are distinct in a unique index, so
        # the conversations that predate this and have no roster left to key on
        # neither collide nor reserve a key a live roster could want.
        Index("uq_dm_conversations_roster", "kind", "roster_key", unique=True),
    )
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        sa_column=Column(
            Uuid, primary_key=True, server_default=text("gen_random_uuid()")
        ),
    )
    kind: DmConversationKind = Field(
        default=DmConversationKind.direct,
        sa_column=Column(Text, nullable=False, server_default=text("'direct'")),
    )
    #: The sorted member ids the conversation was made with. Null only on a
    #: conversation that predates roster identity and that everybody has left.
    roster_key: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class DmConversationMember(SQLModel, table=True):
    __tablename__ = "dm_conversation_members"
    __table_args__ = (
        # "my conversations", which is the list page's only query.
        Index("ix_dm_conversation_members_user", "user_id"),
    )
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    conversation_id: uuid.UUID = Field(
        sa_column=Column(
            Uuid,
            ForeignKey("dm_conversations.id", ondelete="CASCADE"),
            primary_key=True,
        )
    )
    user_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        )
    )
    joined_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    #: When this account answered. Null while it has been asked and has not --
    #: a row that exists but is not yet on the thread. ``dm_in_conversation``
    #: reads this, so a pending row reaches nothing.
    accepted_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
