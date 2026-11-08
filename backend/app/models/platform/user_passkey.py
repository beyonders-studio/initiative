import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    ARRAY,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlmodel import Field, SQLModel


class UserPasskey(SQLModel, table=True):
    """One WebAuthn credential an account may sign in with.

    Its own table rather than a row in ``federated_identities``: that one is
    keyed ``(provider_id, subject)`` and means "an identity provider asserted
    this person". A passkey has no provider and asserts nothing about a person
    — it is a key this deployment registered — so sharing the table would make
    ``provider_id`` nullable and that docstring false.

    ``app_admin``-only: RLS enabled and forced with no policies, the shape the
    second-factor tables use. The request path reaches a passkey only through a
    route running on the system engine.
    """

    __tablename__ = "user_passkeys"

    id: uuid.UUID | None = Field(
        default_factory=uuid.uuid4,
        sa_column=Column(UUID(as_uuid=True), primary_key=True),
    )
    user_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    # The credential's own id, as the authenticator minted it. Unique across the
    # deployment: it is what an assertion arrives naming, before any account is
    # known.
    credential_id: bytes = Field(
        sa_column=Column(LargeBinary, nullable=False, unique=True, index=True)
    )
    #: COSE-encoded public key. Verification material, not a secret.
    public_key: bytes = Field(sa_column=Column(LargeBinary, nullable=False))

    # The relying-party id the credential was registered under — the host from
    # ``APP_URL`` at the time. Kept on the row rather than derived at every
    # assertion because a deployment that changes its domain changes what it
    # would derive, and a credential made under the old one cannot answer under
    # the new. Stored, the refusal can say that; derived, it would look like a
    # signature that failed to verify.
    rp_id: str = Field(sa_column=Column(Text, nullable=False))

    #: Counter the authenticator reports. Some never move it off zero, which is
    #: allowed; what matters is that it does not go backwards.
    sign_count: int = Field(default=0, sa_column=Column(Integer, nullable=False))

    #: How the authenticator can be reached — usb, nfc, ble, internal, hybrid.
    #: Handed back to the browser so it can offer the right prompt.
    transports: list[str] = Field(
        default_factory=list,
        sa_column=Column(ARRAY(Text), nullable=False, server_default="{}"),
    )
    #: The authenticator model's identifier, as it reports it. Recorded for the
    #: person's own benefit — it is what lets the list say "YubiKey" rather than
    #: "credential 3" — and never trusted as a claim.
    aaguid: str | None = Field(default=None, sa_column=Column(Text, nullable=True))

    # Whether the ceremony proved the person as well as the device — a PIN, a
    # fingerprint, a face. This is what makes one credential answer for two
    # factors and another for one, so a requirement can ask for it later.
    user_verified: bool = Field(
        default=False, sa_column=Column(Boolean, nullable=False, server_default="false")
    )
    #: Whether the credential syncs between the person's devices. Recorded so
    #: the list can say which of somebody's keys leaves the device it was made
    #: on, which is the thing people actually want to know about a passkey.
    backed_up: bool = Field(
        default=False, sa_column=Column(Boolean, nullable=False, server_default="false")
    )

    #: What the person calls it. They name it; nothing derives it.
    name: str = Field(sa_column=Column(String(64), nullable=False))

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    last_used_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
