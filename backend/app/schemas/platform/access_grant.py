from datetime import datetime, timezone
from typing import Any, List, Optional

from pydantic import (
    AliasChoices,
    ConfigDict,
    Field,
    computed_field,
)

from app.models.platform.access_grant import (
    AccessGrantStatus,
    CommunityNotice,
    grant_is_live,
    AccessLevel,
    SettingsLevel,
)
from app.core.intake import CommunityNoticeRule, IntakeStream
from app.models.platform.guild import CommunityStatus
from app.schemas.base import SanitizedBaseModel
from app.schemas.platform.user import UserIdentity
from app.schemas.query import PageMeta


class AccessGrantCreate(SanitizedBaseModel):
    """A request for time-bound access to one guild.

    Two axes, and a request may name either or both. **Content** reaches what
    is inside the community, at ``read`` or ``read_write``. **Settings**
    reaches its configuration and nothing inside it, at ``admin`` or
    ``superadmin``.

    Asking for both is a real errand rather than a mistake: clearing up after
    an incident takes write access to the content *and* the settings that
    govern it, which is the same pair breaking glass issues. Each axis becomes
    its own grant, so what was exercised is recorded separately even when both
    were asked for at once.

    Naming neither is read-only content — what a bare request has always
    meant.
    """

    community_id: int
    #: The content rung, or ``None`` to ask for no content access.
    access_level: Optional[AccessLevel] = None
    #: The settings rung, or ``None`` to ask for no settings access. There is
    #: no default: nothing sits between what an admin runs and what the seat
    #: holds.
    settings_level: Optional[SettingsLevel] = None
    # Omit to use the platform default; capped server-side to the configured
    # maximum regardless of what's requested.
    requested_duration_minutes: Optional[int] = Field(default=None, gt=0)
    reason: str = Field(min_length=1, max_length=2000)
    #: The operations case this access is for. Required wherever the
    #: operations community takes cases a grant may serve.
    case_task_id: Optional[int] = Field(default=None, gt=0)
    #: Whether, and when, the community's superadmins are emailed about the
    #: access. Chosen only for a case whose stream leaves it open; a support
    #: case always tells them when it starts.
    community_notice: Optional[CommunityNotice] = None

    @property
    def wanted(self) -> list[tuple[str, str]]:
        """``(purpose, level)`` for each grant this request asks for, content
        first — the one a caller routes in under."""
        asked: list[tuple[str, str]] = []
        if self.access_level is not None or self.settings_level is None:
            asked.append(("content", (self.access_level or AccessLevel.read).value))
        if self.settings_level is not None:
            asked.append(("settings", self.settings_level.value))
        return asked


class SecondFactorAnswer(SanitizedBaseModel):
    """The account's own second factor, presented with a self-issued grant.

    Asked for when the account holds one, or the deployment requires one of
    its rung. Any of the three answers is accepted: a code from the
    authenticator, one of the recovery codes, or an assertion from one of the
    account's passkeys — begun at
    ``POST /access-grants/break-glass/passkey`` so the challenge it answers
    belongs to this request.
    """

    code: Optional[str] = Field(default=None, max_length=64)
    recovery_code: Optional[str] = Field(default=None, max_length=64)
    #: ``AuthenticationResponseJSON`` — the assertion as the browser returned it.
    passkey: Optional[dict[str, Any]] = None


class BreakGlassCreate(SecondFactorAnswer):
    """A self-approved, time-bound break-glass grant to one guild.

    Issued by a ``data.bypass`` holder who needs emergency access without
    waiting for a second-person approval. It is not a dial: breaking glass
    issues write access to the community's content **and** a settings grant at
    ``superadmin``, because that is what an emergency is for. Somebody who
    wants less asks for less through the ordinary request flow. The window is
    short and capped server-side — re-issue to extend.
    """

    community_id: int
    # Omit to use the break-glass default; capped server-side to the
    # break-glass maximum regardless of what's requested.
    requested_duration_minutes: Optional[int] = Field(default=None, gt=0)
    reason: str = Field(min_length=1, max_length=2000)
    #: The operations case this is for, where there is one. Optional: an
    #: emergency may come before its case, and the steps are then written on
    #: the case by hand.
    case_task_id: Optional[int] = Field(default=None, gt=0)
    #: As on a request: whether, and when, the community is told.
    community_notice: Optional[CommunityNotice] = None


class AccessGrantApprove(SanitizedBaseModel):
    """Approval payload. The approver may shorten/extend the window, still
    subject to the server-side cap."""

    duration_minutes: Optional[int] = Field(default=None, gt=0)


class AccessGrantRead(SanitizedBaseModel):
    # ``validate_assignment``: the enrichment fields below are assigned by
    # ``access_grants`` after the row has been validated, and are checked
    # against their types as they are.
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_serialization_defaults_required=True,
        validate_assignment=True,
    )

    id: int
    user_id: int
    community_id: int = Field(validation_alias=AliasChoices("community_id", "guild_id"))
    #: What this grant is for. ``purpose`` is what tells the two vocabularies
    #: below apart: a content grant's level is ``read``/``read_write``, a
    #: settings grant's is ``admin``/``superadmin``.
    purpose: str = "content"
    access_level: str
    status: AccessGrantStatus
    reason: str
    requested_duration_minutes: int
    requested_by_id: int
    approved_by_id: Optional[int] = None
    revoked_by_id: Optional[int] = None
    requested_at: datetime
    decided_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    #: The operations case this grant serves, where it names one.
    case_task_id: Optional[int] = None
    #: Whether, and when, the community's superadmins are told of it.
    community_notice: CommunityNotice = CommunityNotice.none

    # Enrichment populated by the service for display (avoids the client
    # re-fetching users/guilds). Optional so ``model_validate`` over a bare
    # ORM row still works.
    #: Who holds the grant, by handle: what an approver reads to decide on a
    #: request. Never their address.
    user: Optional[UserIdentity] = None
    community_name: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("community_name", "guild_name")
    )
    # The grant's guild lifecycle status, so an operator holding the grant sees
    # a suspended / read-only guild they're acting in (surfaced in the access
    # banner). Operators get this context — unlike a plain guild member.
    community_status: Optional[CommunityStatus] = Field(
        default=None, validation_alias=AliasChoices("community_status", "guild_status")
    )
    #: Who approved it, by handle.
    approved_by: Optional[UserIdentity] = None

    @computed_field(return_type=bool)  # type: ignore[misc]
    @property
    def is_live(self) -> bool:
        """Whether this grant currently confers access (approved, unexpired)."""
        return grant_is_live(self.status, self.expires_at, datetime.now(timezone.utc))


class BreakGlassRequirements(SanitizedBaseModel):
    """What a break-glass request will be asked for, before it is made.

    The form reads this to know whether to offer a code field, and whether the
    caller has a factor to answer with.
    """

    second_factor_required: bool
    #: The longest window, in minutes, the caller may break glass for.
    max_duration_minutes: int
    #: Whether the caller holds a confirmed authenticator to answer with.
    totp_enrolled: bool
    #: And whether they hold a passkey, which answers it just as well.
    passkey_enrolled: bool


class GrantCaseRead(SanitizedBaseModel):
    """An open operations case the reader may name as the reason for a grant."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    task_id: int
    title: str
    stream: IntakeStream
    #: The community the case is about, where it names one: a grant for the
    #: case reaches that community and no other.
    subject_community_id: Optional[int] = None
    #: Assigned to the reader.
    mine: bool = False
    #: Whether a grant for the case tells the community it reaches.
    community_notice: CommunityNoticeRule = CommunityNoticeRule.never


class GrantCaseList(SanitizedBaseModel):
    """The open cases the reader may name, theirs first. ``required`` says
    whether a request must name one here."""

    items: List[GrantCaseRead]
    required: bool


class AccessGrantLimits(SanitizedBaseModel):
    """What the caller may ask for through the request flow, as this
    deployment configures it — read by the request form to offer its
    durations."""

    #: The longest window, in minutes, the caller may request.
    max_duration_minutes: int


class AccessGrantListResponse(PageMeta):
    items: List[AccessGrantRead]
