"""What the security rules have counted, per key and window.

Every instance counts in memory and adds its counts here every few seconds
(``app.services.platform.security_signals``), so a rule sees the whole
deployment's total however many processes serve it, and an attack costs one
write per rule per flush rather than one per attempt.

Keys are kept only as an HMAC of what they counted by — an address, an
account — so this table names nobody. The system engine's alone.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, PrimaryKeyConstraint, String
from sqlmodel import Field, SQLModel


class SecuritySignalWindow(SQLModel, table=True):
    """One rule's count of one key in one window."""

    __tablename__ = "security_signal_windows"
    __table_args__ = (PrimaryKeyConstraint("rule", "key", "window_start"),)

    #: The rule's name (``app.core.security_rules``).
    rule: str = Field(sa_column=Column(String(length=64), nullable=False))
    #: An HMAC of what was counted by, or ``*`` for everything past the cap.
    key: str = Field(sa_column=Column(String(length=64), nullable=False))
    window_start: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True)
    )
    count: int = Field(sa_column=Column(Integer, nullable=False))
    #: When the count reached the rule's threshold and a case was opened. Set
    #: once, by whichever instance's flush took it over.
    crossed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
