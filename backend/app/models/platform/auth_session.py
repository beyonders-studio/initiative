import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlmodel import Field, Index, SQLModel


class AuthSession(SQLModel, table=True):
    """A server-side session backing one login — the rotating-refresh anchor.

    The access JWT is stateless (verified locally, no per-request DB hit); this
    row is what makes the refresh side revocable. ``id`` is the JWT ``sid`` — a
    uuid rather than a sequence. ``satisfied_providers``
    / ``amr`` record which providers/factors this session authenticated against,
    mirrored into the access token so the per-guild auth-policy gate and step-up
    read them locally without a lookup. ``provider_auth`` holds each satisfied
    provider's own account of its authentication event, kept per provider
    because one session can span several.

    **app_admin-only.** Session validation is a pre-auth lookup *by refresh-token
    hash* (the user is unknown until it resolves), so it structurally cannot run
    under own-row RLS — it runs on the system engine, exactly like access_grants.
    "List/revoke my sessions" also runs on the system engine (``SystemSessionDep``)
    filtered by the authenticated user, so the refresh-token hash never crosses the
    request path. The schema-default request-path DML is REVOKEd in the migration.
    """

    __tablename__ = "auth_sessions"
    __table_args__ = (
        UniqueConstraint(
            "refresh_token_hash", name="uq_auth_sessions_refresh_token_hash"
        ),
        # A row can't be its own rotation parent — a self-loop would hang the
        # theft-detection chain walk. Longer cycles can't form: the chain is
        # strictly backward in time (a new row's fresh uuid can't already be a
        # parent_id), so direct self-reference is the only reachable loop.
        CheckConstraint(
            "parent_id IS NULL OR parent_id <> id",
            name="ck_auth_sessions_parent_not_self",
        ),
        Index("ix_auth_sessions_user_id", "user_id"),
        # Supports the background expiry sweep (GC of past-expiry sessions).
        Index("ix_auth_sessions_expires_at", "expires_at"),
        # The chain walks go from a row to its children: revoking a chain, and
        # finding the live row a chain has reached.
        Index("ix_auth_sessions_parent_id", "parent_id"),
        # One installed copy of the app holds one live sign-in.
        Index(
            "uq_auth_sessions_live_install",
            "user_id",
            "install_id",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        sa_column=Column(
            Uuid, primary_key=True, server_default=text("gen_random_uuid()")
        ),
    )
    user_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        )
    )

    # SHA-256 of the raw refresh token — deterministic so a presented token maps
    # to one session by index lookup. The raw token is never stored.
    refresh_token_hash: bytes = Field(sa_column=Column(LargeBinary, nullable=False))

    # Providers/factors this session satisfied — drives the guild auth-policy gate
    # and step-up; mirrored into the access JWT so the check stays local.
    satisfied_providers: list[int] = Field(
        default_factory=list,
        sa_column=Column(ARRAY(Integer), nullable=False, server_default=text("'{}'")),
    )
    amr: list[str] = Field(
        default_factory=list,
        sa_column=Column(ARRAY(Text), nullable=False, server_default=text("'{}'")),
    )
    # What each satisfied provider said about the authentication it performed —
    # ``auth_time``/``amr``/``acr`` from its verified id_token, keyed by
    # provider id as a string. Per provider rather than per session: one
    # session can satisfy several guilds' identity sources, and each guild's
    # requirement is about its own provider's event. See
    # ``services.auth.assurance``.
    provider_auth: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    )

    # Rotation chain: each refresh mints a new row pointing at the one it replaced;
    # reuse of an already-rotated token revokes the whole chain (theft detection).
    # Plain uuid, app-managed — no self-FK.
    parent_id: uuid.UUID | None = Field(
        default=None, sa_column=Column(Uuid, nullable=True)
    )

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    last_used_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    # Set by the service to now + REFRESH_TTL at creation (no default here).
    expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    # The end of the whole chain, not of this row: how long somebody may stay
    # signed in before signing in again, as opposed to how long they may leave
    # the app alone (``expires_at``, which every rotation pushes forward).
    #
    # Stamped once when the sign-in happens and carried through every rotation
    # unchanged, so renewing costs no extra read. NULL means the deployment
    # asked for no limit.
    chain_expires_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    revoked_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )

    # Audit / "your active sessions" UX.
    user_agent: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    # INET (not text): canonical normalisation + subnet queries; NULL when unknown.
    # Rejects a raw X-Forwarded-For list, forcing the service to store one client IP.
    ip: str | None = Field(default=None, sa_column=Column(INET, nullable=True))
    device_name: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    #: The installed copy of the phone or desktop app that opened it; NULL for a
    #: browser. A device stays signed in for longer than a browser does, and a
    #: new sign-in from the same install continues this one. Carried across
    #: every renewal and step-up.
    install_id: uuid.UUID | None = Field(
        default=None, sa_column=Column(Uuid, nullable=True)
    )
    #: When the sign-in this session continues began, where it took the place
    #: of another (a step-up, a replacement). Its own chain starts afresh, so
    #: this is what still says how long the person has been signed in here.
    continues_since: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
