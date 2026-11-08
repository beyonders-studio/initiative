from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import (
    ConfigDict,
    Field,
    computed_field,
    create_model,
    field_validator,
    model_validator,
)

from app.core.identity_boundary import PersonId
from app.core.moderation import RemovalReason
from app.core.tools import COMMENT_TARGETS
from app.models.platform.user import Presence
from app.models.tenant.comment import CommentAudience
from app.schemas.base import RichMentionStr, RichTextStr, SanitizedBaseModel
from app.schemas.platform.user import PersonShape, ProfileDecorations
from app.schemas.tenant.created_by import CreatedByRead
from app.schemas.tenant.reaction import ReactionGroup
from app.services.platform import presence


class CommentAuthor(PersonShape):
    """Who wrote a comment.

    An address never reaches a guild, so there is none here; the handle names
    the author, and ``display_name`` is the name they set in this guild.

    It carries what a picture needs to be drawn the way it is drawn everywhere
    else — the decorations and how they are appearing — because a comment is
    one of the places a person appears at a size where both are legible.
    Neither is private: the same two are on the public profile.
    """

    model_config = ConfigDict(from_attributes=True)

    id: PersonId
    username: str
    discriminator: int
    display_name: str | None = None
    avatar_url: str | None = None
    profile_decorations: ProfileDecorations = Field(default_factory=ProfileDecorations)

    @computed_field(return_type=Presence)  # type: ignore[misc]
    @property
    def presence(self) -> Presence:
        """How they appear, at the moment this was serialized.

        Computed rather than stamped by each endpoint: a comment author is
        built in nine places, and what a reader is shown is not a column
        anything could select — it is what the account picked narrowed by which
        sockets are open. So it is read where the shape is made rather than
        passed down to it.
        """
        return presence.online.presence_of(self.id)


class CommentBase(SanitizedBaseModel):
    content: RichMentionStr

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Content is required")
        return normalized


# Every comment parent, in one place: one field per tool plus the content-level
# extras. The comments table carries a matching FK per entry, and the
# create/list surfaces take exactly one of them.
# Derived from the registry: a new parent's field joins by existing.
COMMENT_TARGET_FIELDS: tuple[str, ...] = tuple(
    f"{target}_id" for target in COMMENT_TARGETS
)

_CommentCreateTargets = create_model(
    "_CommentCreateTargets",
    __base__=CommentBase,
    **{
        field: (int | None, Field(default=None, gt=0))
        for field in COMMENT_TARGET_FIELDS
    },
)
_CommentReadParents = create_model(
    "_CommentReadParents",
    __base__=CommentBase,
    **{field: (int | None, None) for field in COMMENT_TARGET_FIELDS},
)


class CommentCreate(_CommentCreateTargets):
    parent_comment_id: int | None = Field(default=None, gt=0)
    #: Who it is said to. ``filer`` only on an operations case somebody filed,
    #: where it is the reply they are shown; ``members`` everywhere else.
    audience: CommentAudience = CommentAudience.members

    @model_validator(mode="after")
    def validate_target(self) -> CommentCreate:
        provided = [
            field for field in COMMENT_TARGET_FIELDS if getattr(self, field) is not None
        ]
        if len(provided) != 1:
            raise ValueError("Provide exactly one comment target")
        return self

    def target_ids(self) -> dict[str, int | None]:
        """The target fields as service kwargs."""
        return {field: getattr(self, field) for field in COMMENT_TARGET_FIELDS}


class ToolCommentSettings(SanitizedBaseModel):
    """The comment switch on one tool entity — the body and the reply of the
    generic ``PUT /tools/{tool}/{tool_id}/comments`` route."""

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    comments_enabled: bool


class CommentUpdate(CommentBase):
    """Schema for updating a comment. Only content can be changed."""


class RemovedBy(str, Enum):
    """Who took a comment out of the conversation."""

    #: A moderator, with a reason.
    moderator = "moderator"
    #: The person who wrote it.
    author = "author"


class CommentRemoval(SanitizedBaseModel):
    """What a tombstone says in place of a comment: who took it out, and,
    for a moderator, why. Never what it said, or who wrote it."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    by: RemovedBy
    reason: RemovalReason | None = None


class CommentRead(_CommentReadParents, CreatedByRead):
    """One comment. ``project_id`` is its own for a comment on a project and
    the task's for a task comment (filled by the service's serializer)."""

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    parent_comment_id: int | None = None
    created_at: datetime
    updated_at: datetime | None = None
    author: CommentAuthor | None = None
    # Who said this where it came from, when an import could not match them
    # to an account here. Display text: the client shows this name instead of
    # the author's, with no avatar and no profile link, because it names a
    # person rather than an account. Null on everything written in this app.
    imported_author_name: str | None = None
    # Reactions ride along with the comment rather than costing a request per
    # row: a thread renders its chips from one list call. Empty until the
    # loader stamps them (see ``comments_service.attach_reactions``).
    reactions: list[ReactionGroup] = Field(default_factory=list)
    # Whether the reader may delete this comment: their own. A moderator takes
    # others' down from the thread's moderation actions instead. Filled by the
    # service's serializer from the same rule the delete route applies.
    can_remove: bool = False
    # Set on a tombstone: a comment a moderator took down, or one its author
    # deleted with replies under it. Its content is empty, and it names no
    # author.
    removed: CommentRemoval | None = None
    # Who it is said to. ``filer`` on the part of an operations case that is
    # said to the person who filed it; ``members`` on everything else.
    audience: CommentAudience = CommentAudience.members
    # What the platform posted it as, on a note the platform wrote on an
    # operations case. Null on everything a person or a plug-in wrote — which
    # is how a client tells the platform's notes from a plug-in's.
    system_kind: str | None = None

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        """Read back as stored: a tombstone's is empty."""
        return value


class CommentListResponse(SanitizedBaseModel):
    """One page of a thread: ``limit`` conversations, newest first, each with
    every reply under it."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    #: The page's comments, in the order they were written.
    comments: list[CommentRead]
    #: The next page, or null at the end of the thread.
    next_cursor: str | None = None
    #: A moderator closed the thread: it reads as before, and only the
    #: moderation set adds to it.
    locked: bool = False
    #: Whether the reader is in the moderation set of the thread's initiative:
    #: they take comments down, and write in a locked thread.
    can_moderate: bool = False


class RecentActivityEntry(SanitizedBaseModel):
    # Same as the other read schemas here: a field with a default is still
    # always sent, so the generated client should see it as present rather than
    # optional.
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    comment_id: int
    content: RichTextStr
    created_at: datetime
    author: CommentAuthor | None = None
    # The project a task comment's task is in. None for any other parent.
    project_id: int | None = None
    project_name: str | None = None
    # What the comment is on: "task", "wiki_page" or a Tool value, with the
    # entity's id and display name.
    entity_type: str | None = None
    entity_id: int | None = None
    entity_name: str | None = None
    # The initiative the commented-on entity lives in, so the row can link at
    # its real address. None when the parent is gone or unreadable (or the
    # parent is a guild-level calendar, which belongs to no initiative).
    initiative_id: int | None = None
    # The same chips the thread shows. The feed is where a guild sees what is
    # going on, and a comment that drew six reactions reads differently from
    # one that drew none — so the row carries them rather than looking like a
    # quieter comment than it was.
    reactions: list[ReactionGroup] = Field(default_factory=list)
