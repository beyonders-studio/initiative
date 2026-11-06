"""Shapes for the people roster.

A person here is somebody the reader can already see — someone in one of their
guilds. ``PersonRead`` is ``UserSummary`` plus the
few things only this roster asks for, kept off the shared picker projection so
every other caller of that shape is untouched.
"""

from typing import List, Optional

from pydantic import AliasChoices, ConfigDict, Field

from app.schemas.base import SanitizedBaseModel
from app.models.platform.user import Presence
from app.schemas.platform.user import ProfileDecorations, UserSummary


class PersonRead(UserSummary):
    """One person, on one row of the roster.

    Inherits ``UserSummary``'s ``display_name``: the name the person set in
    the guild this row was read under, which the cross-guild loop reads per
    guild.
    """

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    #: How this person appears right now, from the one roll that decides it.
    presence: Presence = Presence.offline
    #: What they have put around their picture, so a row draws them the way
    #: every other surface does. Public, like the profile it comes from.
    profile_decorations: ProfileDecorations = Field(default_factory=ProfileDecorations)
    #: The reader's *own* guilds this person is also in, in the same order the
    #: sections come in. Never names a guild the reader is not in — it is built
    #: from their own guild list. The section a row sits in is included; the
    #: chip drops it, because a row's own guild is not "also in".
    shared_community_ids: List[int] = Field(
        default_factory=list,
        validation_alias=AliasChoices("shared_community_ids", "shared_guild_ids"),
    )


class PeopleCommunitySection(SanitizedBaseModel):
    """One guild's roster, as one accordion section."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    community_id: int = Field(validation_alias=AliasChoices("community_id", "guild_id"))
    community_name: str = Field(
        validation_alias=AliasChoices("community_name", "guild_name")
    )
    icon_url: Optional[str] = None
    #: Everyone in the guild the reader may be shown, not just this page.
    total_count: int
    items: List[PersonRead]
    has_next: bool


class PeopleSectionsResponse(SanitizedBaseModel):
    """Every guild section, in the reader's own rail order.

    Paginated *within* each section rather than across a merged list: the
    response is grouped, so a flat offset would not mean anything.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    sections: List[PeopleCommunitySection]
    page: int
    page_size: int
