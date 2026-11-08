import uuid
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, String, Uuid
from sqlmodel import Field, Index, SQLModel


class PushToken(SQLModel, table=True):
    """Push notification tokens for mobile devices.

    Stores FCM (Firebase Cloud Messaging) tokens for both Android and iOS.
    iOS tokens are forwarded through FCM to APNS.
    """

    __tablename__ = "push_tokens"
    __table_args__ = (
        # One row per (device, token): re-registering the same token for a user
        # updates the existing row rather than fanning out duplicate pushes.
        Index("ix_push_tokens_user_device_token", "user_id", "push_token", unique=True),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(
        foreign_key="users.id", ondelete="CASCADE", nullable=False, index=True
    )
    # FCM registration token (Android) or APNS device token (iOS)
    # The session that registered this device, followed along its rotation
    # chain to the live row. A plain uuid, as ``auth_sessions.parent_id`` is:
    # session rows are purged on their own schedule.
    session_id: uuid.UUID | None = Field(
        default=None, sa_column=Column(Uuid, nullable=True, index=True)
    )
    push_token: str = Field(
        sa_column=Column(String(512), nullable=False, index=True),
    )
    # Platform identifier: 'android' or 'ios'
    platform: str = Field(
        sa_column=Column(String(32), nullable=False),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    # Track last successful push delivery for monitoring
    last_used_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
