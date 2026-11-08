"""One member's answer to an installed plug-in asking to act as them.

A plug-in asks to act as a member for one **purpose**: an opaque id of its own
choosing, such as the automation step that needs a person's name, described by
a ``label`` in the plug-in's own words. A purpose may be bound to one initiative.
With no purpose the request is plug-in-wide: the plug-in acts as the member for
whatever it does.

The row is the request and the member's answer together. It is written when the
plug-in asks (``requested_*``) and answered by the member alone, from a first-party
session (``granted_*``, ``confirmed_factor``):

* **pending**: ``granted_access`` and ``revoked_at`` are both empty;
* **granted**: ``granted_access`` says at which level, never more than was
  asked for;
* **declined**: ``revoked_at`` is set on a request that was never granted;
* **revoked**: ``revoked_at`` is set on one that was.

A member token is issued only while the row is granted and not revoked, and
the install standing reads the row again on every request, so an answer
changes the next request.

The row hangs off ``guild_plugins``, so removing the plug-in removes every answer
with it. It is an own-row table: the member reads and answers their own, and
the community's administration reads them and revokes (the ``own_row_*``
policies in ``app.db.tenancy.OWN_ROW_TABLES``).
"""

from datetime import UTC, datetime
from enum import Enum

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlmodel import Field, SQLModel

#: The longest ``purpose`` a plug-in may name.
PURPOSE_MAX_LENGTH = 128
#: The longest ``label`` a plug-in may write.
LABEL_MAX_LENGTH = 200

#: The characters a ``purpose`` is written in: an opaque id of the plug-in's own,
#: such as an automation step's key or a UUID.
PURPOSE_CHARACTERS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.:/@"
)


def is_valid_purpose(value: object) -> bool:
    """Whether ``value`` is a purpose a plug-in may name."""
    return (
        isinstance(value, str)
        and 0 < len(value) <= PURPOSE_MAX_LENGTH
        and set(value) <= PURPOSE_CHARACTERS
    )


class ConsentAccess(str, Enum):
    """How deeply a plug-in may act as the member."""

    read = "read"
    read_write = "read_write"

    def covers(self, other: "ConsentAccess") -> bool:
        """Whether this level includes ``other``."""
        return self is ConsentAccess.read_write or other is ConsentAccess.read


class ConsentStatus(str, Enum):
    """Where a request stands, read off its columns."""

    pending = "pending"
    granted = "granted"
    declined = "declined"
    revoked = "revoked"


_ACCESS_VALUES = "('read', 'read_write')"


class PluginMemberConsent(SQLModel, table=True):
    __tablename__ = "plugin_member_consents"

    __table_args__ = (
        # One row per member per purpose per install, the app-wide one
        # included: a repeated request finds the row it made before.
        UniqueConstraint(
            "install_id",
            "user_id",
            "purpose",
            name="plugin_member_consents_unique_purpose",
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint(
            f"requested_access IN {_ACCESS_VALUES}",
            name="plugin_member_consents_requested_access",
        ),
        CheckConstraint(
            f"granted_access IS NULL OR granted_access IN {_ACCESS_VALUES}",
            name="plugin_member_consents_granted_access",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)

    install_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("guild_plugins.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    user_id: int = Field(
        sa_column=Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    )

    #: The plug-in's own id for what it wants to do as the member. ``None`` asks
    #: for app-wide consent.
    purpose: str | None = Field(
        default=None,
        sa_column=Column(String(PURPOSE_MAX_LENGTH), nullable=True),
    )
    #: What the plug-in says the purpose is, in its own words.
    label: str = Field(sa_column=Column(String(LABEL_MAX_LENGTH), nullable=False))
    #: The one initiative the purpose is bound to, when it is.
    initiative_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("initiatives.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )

    requested_access: str = Field(sa_column=Column(String(16), nullable=False))
    #: What the member allowed, never more than ``requested_access``. ``None``
    #: until they answer yes.
    granted_access: str | None = Field(
        default=None, sa_column=Column(String(16), nullable=True)
    )

    requested_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    granted_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    #: When the member declined or withdrew it, or the community's
    #: administration withdrew it for them.
    revoked_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    revoked_by_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("users.id"), nullable=True),
    )

    #: How the member was signed in when they granted it.
    confirmed_factor: str | None = Field(
        default=None, sa_column=Column(String(32), nullable=True)
    )

    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    @property
    def status(self) -> ConsentStatus:
        if self.revoked_at is not None:
            return (
                ConsentStatus.revoked
                if self.granted_access is not None
                else ConsentStatus.declined
            )
        if self.granted_access is not None:
            return ConsentStatus.granted
        return ConsentStatus.pending
