"""Schemas for the platform operator surfaces."""

from typing import List, Literal, Optional

from pydantic import AliasChoices, ConfigDict, Field

from app.schemas.base import SanitizedBaseModel

from app.core.intake import IntakeStream
from app.models.platform.user import UserRole


class PlatformRoleUpdate(SanitizedBaseModel):
    """Schema for updating a user's platform role."""

    role: UserRole


class OperatorUserDeleteRequest(SanitizedBaseModel):
    """Request to deactivate, anonymize (soft delete), or hard delete another account."""

    action: Literal["deactivate", "soft_delete", "hard_delete"]


class CommunityBlockerInfo(SanitizedBaseModel):
    """Info about a guild blocking user deletion."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    community_id: int = Field(validation_alias=AliasChoices("community_id", "guild_id"))
    community_name: str = Field(
        validation_alias=AliasChoices("community_name", "guild_name")
    )


class OperatorDeletionEligibilityResponse(SanitizedBaseModel):
    """Enhanced eligibility response with actionable blocker details."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    can_delete: bool
    #: The account is the last active platform owner; another is promoted first.
    last_owner: bool = False
    community_blockers: List[CommunityBlockerInfo] = Field(
        default_factory=list,
        validation_alias=AliasChoices("community_blockers", "guild_blockers"),
    )


class OperatorUsernameUpdate(SanitizedBaseModel):
    """The name part a moderator sets on someone else's account.

    The number is not here and never will be: it is drawn, not chosen, by
    anyone. It is re-drawn only if the new pair is already held.
    """

    username: str = Field(max_length=64)


class OperatorSuspensionUpdate(SanitizedBaseModel):
    """Freeze an account, or let it go.

    ``reason`` is shown to the person it is about, so it is written for them
    rather than as an internal note.
    """

    suspended: bool
    reason: Optional[str] = Field(default=None, max_length=500)


class OperatorAccountCaseRead(SanitizedBaseModel):
    """An open case an account filed or is the subject of: where it lives, to
    link to it, and nothing of what it says. Opening it is the case's
    initiative's to allow."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    task_id: int
    stream: IntakeStream
    community_id: int
    initiative_id: int
    project_id: int
    #: Whether the account filed it, rather than being what it is about.
    filed: bool


#: The parts of how an account appears to others that staff may clear.
ProfileField = Literal["display_names", "custom_status", "decorations"]
