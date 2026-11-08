"""Payloads for the owner's intake settings page."""

from __future__ import annotations

from pydantic import AliasChoices, EmailStr, Field

from app.core.intake import Conversation, IntakeStream
from app.schemas.base import SanitizedBaseModel


class IntakeBindingRead(SanitizedBaseModel):
    """One stream and where it currently lands."""

    stream: IntakeStream
    binding_id: int | None = None
    project_id: int | None = None
    project_name: str | None = None
    #: The bound project has been archived or trashed. Archived content takes
    #: no writes, so the stream receives nothing until it is brought back or
    #: pointed at a live project.
    project_archived: bool = False
    initiative_id: int | None = None
    initiative_name: str | None = None
    default_status_id: int | None = None
    default_status_name: str | None = None
    #: The type a new case is; null for the project's default.
    task_type_id: int | None = None
    task_type_name: str | None = None
    #: The status that tells whoever filed a case it is waiting on them, and
    #: the one a case moves back to when they answer. Without the first, a
    #: filer sees Received, In progress and Closed, never Waiting on you.
    awaiting_filer_status_id: int | None = None
    active_status_id: int | None = None
    #: What the stream allows with whoever filed a case: with ``none`` there
    #: is nobody to wait on, and the status roles mean nothing.
    conversation: Conversation = Conversation.none
    #: Whether people file into the stream. One nobody files into, which the
    #: team fills by hand, has no contact address.
    filed: bool = True
    #: The stream keeps its initiative to itself.
    isolated: bool = False
    #: Another stream lands in the same initiative while one of the two keeps
    #: its initiative to itself — bound before that was refused, and left as
    #: it was rather than broken.
    shares_initiative: bool = False
    enabled: bool = False
    #: When this stream last opened a case. The one number worth watching on
    #: this page: whether the thing is on.
    last_case_at: str | None = None


class IntakeSettingsRead(SanitizedBaseModel):
    """The pointer, every stream whether bound or not, and who to contact."""

    operations_community_id: int | None = Field(
        default=None,
        validation_alias=AliasChoices("operations_community_id", "operations_guild_id"),
    )
    operations_community_name: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "operations_community_name", "operations_guild_name"
        ),
    )
    bindings: list[IntakeBindingRead]
    #: The deployment's catch-all contact address.
    general_contact_email: str | None = None
    #: Each stream's own contact address, for the streams that have one. A
    #: stream absent here falls back to the general address.
    contact_emails: dict[IntakeStream, str] = Field(default_factory=dict)
    #: Whether people here may send feedback to the Initiative team.
    feedback_enabled: bool


class FeedbackSwitchUpdate(SanitizedBaseModel):
    """Let people here send feedback to the Initiative team, or stop."""

    enabled: bool


class IntakeContactUpdate(SanitizedBaseModel):
    """Set a contact address, or clear it with ``null``."""

    email: EmailStr | None = None


class OperationsCommunityUpdate(SanitizedBaseModel):
    """Point this deployment's operations work at a guild, or at nothing."""

    community_id: int | None = None


class IntakeBindingUpsert(SanitizedBaseModel):
    """Route one stream into a project of the operations guild."""

    project_id: int
    default_status_id: int | None = None
    #: The type a new case is; null for the project's default.
    task_type_id: int | None = None
    awaiting_filer_status_id: int | None = None
    active_status_id: int | None = None
    enabled: bool = True


class IntakeBlueprintImport(SanitizedBaseModel):
    """Set a stream up from its committed blueprint, in this initiative."""

    initiative_id: int


class IntakeStatusOption(SanitizedBaseModel):
    """One column a case could land in."""

    id: int
    name: str


class IntakeTypeOption(SanitizedBaseModel):
    """One type a case could be."""

    id: int
    name: str


class IntakeProjectOption(SanitizedBaseModel):
    """One project a stream could be bound to, and where a case would start."""

    id: int
    name: str
    statuses: list[IntakeStatusOption]
    task_types: list[IntakeTypeOption] = []


class IntakeInitiativeOption(SanitizedBaseModel):
    """One initiative of the operations guild, and the projects in it."""

    id: int
    name: str
    projects: list[IntakeProjectOption]


class IntakeOptionsRead(SanitizedBaseModel):
    """What the settings page offers to bind to.

    The operations guild alone, names and ids only — enough to fill the
    pickers. Empty until a guild has been named.
    """

    initiatives: list[IntakeInitiativeOption]
