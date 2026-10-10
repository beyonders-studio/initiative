"""The demo deployment's links, copies, the accounts that hold them, and the
addresses visitors leave.

Only a deployment started with ``DEMO_MODE`` writes these; everywhere else
they stay empty. All four are the system engine's alone: a request-path role
reaches none of them.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    UniqueConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
)
from sqlmodel import Field, SQLModel

from app.core.encryption import EMAIL_HASH_COLUMN, FERNET_SALT, SALT_EMAIL
from app.models.platform.guild import CommunityRole


class DemoLink(SQLModel, table=True):
    """A link that hands a pitch out: each opening gets its own copy of the
    pitch community and its own account.

    Only the SHA-256 of the token is kept; the token itself is shown once.
    """

    __tablename__ = "demo_links"
    __table_args__ = (
        CheckConstraint(
            "role IN ('member', 'admin', 'superadmin')", name="ck_demo_links_role"
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    token_hash: bytes = Field(
        sa_column=Column(LargeBinary, nullable=False, unique=True)
    )
    #: The pitch community a copy is made from.
    source_guild_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("guilds.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    #: What the visitor is in their copy.
    role: CommunityRole = Field(
        default=CommunityRole.admin,
        sa_column=Column(String, nullable=False, server_default="admin"),
    )
    #: How many copies the link may ever open; ``None`` for no limit.
    max_redemptions: Optional[int] = Field(default=None)
    #: How many of its copies may be live at once; ``None`` for no limit.
    max_live: Optional[int] = Field(default=None)
    expires_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    revoked_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    #: An internal note saying who the link was for.
    label: Optional[str] = Field(default=None)
    redemption_count: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, server_default="0")
    )
    last_redeemed_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    created_by: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class LinkState(str, Enum):
    """Whether a link still opens copies, and if not, why."""

    live = "live"
    revoked = "revoked"
    expired = "expired"
    used_up = "used_up"


class DemoSandboxState(str, Enum):
    #: Built and waiting for a visitor.
    pooled = "pooled"
    #: Claimed by a link; deleted when it expires.
    live = "live"


class DemoSandbox(SQLModel, table=True):
    """A community built for the pool, and once claimed, a visitor's copy."""

    __tablename__ = "demo_sandboxes"
    __table_args__ = (
        CheckConstraint("state IN ('pooled', 'live')", name="ck_demo_sandboxes_state"),
    )

    guild_id: int = Field(
        sa_column=Column(
            Integer, ForeignKey("guilds.id", ondelete="CASCADE"), primary_key=True
        )
    )
    state: DemoSandboxState = Field(
        default=DemoSandboxState.pooled,
        sa_column=Column(String, nullable=False, index=True, server_default="pooled"),
    )
    link_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("demo_links.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    claimed_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    expires_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    #: The import filling the copy, in the copy's own schema.
    import_job_id: Optional[int] = Field(default=None)


class DemoAccount(SQLModel, table=True):
    """An account made for a visitor, tied to the copy it was made for."""

    __tablename__ = "demo_accounts"

    user_id: int = Field(
        sa_column=Column(
            Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        )
    )
    sandbox_guild_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("demo_sandboxes.guild_id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )


class DemoLead(SQLModel, table=True):
    """An address a visitor left on a link, kept for 30 days. Apart from any
    account: a demo account has no address."""

    __tablename__ = "demo_leads"
    __table_args__ = (
        UniqueConstraint("link_id", "email_hash", name="uq_demo_leads_link_email"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    link_id: int = Field(
        sa_column=Column(
            Integer, ForeignKey("demo_links.id", ondelete="CASCADE"), nullable=False
        )
    )
    #: Keyed hash of the normalised address (``encryption.hash_email``).
    email_hash: str = Field(sa_column=Column(String(64), nullable=False))
    email_encrypted: str = Field(
        sa_column=Column(
            String(2000),
            nullable=False,
            info={FERNET_SALT: SALT_EMAIL, EMAIL_HASH_COLUMN: "email_hash"},
        )
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )
