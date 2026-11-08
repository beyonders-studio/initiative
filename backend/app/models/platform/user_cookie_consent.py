"""What an account has said may be kept in a browser.

One row per account, holding the current answer rather than a history of
answers: the question is "what applies now", and changing your mind replaces
the old answer rather than qualifying it. (``legal_acceptances`` is the other
shape, and is the other shape on purpose — agreeing to a revision of the terms
is an event that happened, not a setting.)

A browser keeps its own copy, because somebody reading the landing page has no
account yet. This is what carries the answer to the next browser, and what
carries a change of mind back to the first one.
"""

from datetime import UTC, datetime

from pydantic import ConfigDict
from sqlalchemy import ARRAY, Column, DateTime, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import ENUM as PGEnum
from sqlmodel import Field, SQLModel

from app.core.cookie_categories import CookieCategory


class UserCookieConsent(SQLModel, table=True):
    __tablename__ = "user_cookie_consent"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    user_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        )
    )
    #: The optional categories this account allows. A Postgres enum array for
    #: the reason ``login_methods`` is one: the database validates the
    #: elements, and a category added later is a value on the type rather than
    #: a column here. Empty means "asked, and allowed none" -- which is a real
    #: answer and not the same as having no row.
    granted: list[str] = Field(
        default_factory=list,
        sa_column=Column(
            ARRAY(PGEnum(CookieCategory, name="cookie_category", create_type=False)),
            nullable=False,
            server_default="{}",
        ),
    )
    #: Which version of the question was answered. An answer to an older one
    #: stops counting, and the question is put again -- see
    #: ``CONSENT_VERSION`` on the frontend, which is what a client sends.
    version: int = Field(sa_column=Column(Integer, nullable=False))
    #: Stamped by the server on every write, so two browsers comparing their
    #: answers are comparing one clock rather than their own.
    decided_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
