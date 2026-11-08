"""What an account agreed to, and when.

A row is one acceptance of one document by one account: an event, not a state.
Re-consent to a later revision appends another row; nothing here is ever
updated, and nothing is deleted except by the cascade when the account goes.

Written only where the deployment has terms of its own. The documents are
served by the external portal it names; this side keeps the record of what
was accepted, never the text.
"""

from datetime import UTC, datetime

from pydantic import ConfigDict
from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlmodel import Field, SQLModel


class LegalAcceptance(SQLModel, table=True):
    __tablename__ = "legal_acceptances"
    __table_args__ = (
        # The one read there is: has this account accepted this document.
        Index("ix_legal_acceptances_user_document", "user_id", "document"),
    )
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: int | None = Field(
        default=None, sa_column=Column(BigInteger, primary_key=True, autoincrement=True)
    )
    user_id: int = Field(
        sa_column=Column(
            Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        )
    )
    #: The document's slug, as the portal's legal index names it. Permanent:
    #: it is what an acceptance is recorded against, so renaming one would
    #: rewrite what people agreed to.
    document: str = Field(sa_column=Column(String(32), nullable=False))
    #: What the portal called that revision at the time. Null when the portal
    #: could not be reached — the acceptance still happened, and the portal's
    #: own history says what the document said on the day.
    version: str | None = Field(
        default=None, sa_column=Column(String(32), nullable=True)
    )
    #: The digest of the exact bytes that were current, which is a stronger
    #: answer than the version string to "what did they agree to". Null under
    #: the same circumstances as ``version``.
    document_sha256: str | None = Field(
        default=None, sa_column=Column(String(64), nullable=True)
    )
    accepted_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
