from __future__ import annotations

import re

from datetime import datetime
from typing import Any, List, Optional, TYPE_CHECKING

from pydantic import AwareDatetime, ConfigDict, Field, model_validator

from app.core.identity_boundary import PersonId, with_mention_markup
from app.schemas.base import LexicalState, MentionStr, SanitizedBaseModel, TitleStr
from app.schemas.tenant.property import PropertiesOnCreate
from app.schemas.query import PageMeta
from app.schemas.platform.user import ProfileDecorations
from app.schemas.tenant.comment import CommentAuthor
from app.schemas.tenant.post_poll import PollRead, PollWrite, serialize_poll
from app.schemas.tenant.reaction import ReactionGroup
from app.schemas.tenant.resource_grant import ResourceGrantSchema, initiative_readable
from app.schemas.tenant.tool import ToolSummaryBase

if TYPE_CHECKING:  # pragma: no cover
    from app.db.guild_standing import ActorContext


# How much of a post the one-line surfaces get. Long enough to tell two
# notices apart in a recents tab, short enough that a list of them stays a
# list.
EXCERPT_CHARS = 280

# How long a notice may be. A board is read, not studied: this is roughly
# 1,500 words, which is far more than any notice needs and still short enough
# that a page of twenty stays a page. Something longer is a file, and the
# initiative already has those.
MAX_POST_TEXT_CHARS = 10_000

# A structural ceiling on the stored state, independent of how much of it is
# words. Images and files are references rather than embedded data, so a
# legitimate notice is nowhere near this; it is here so a hand-made payload of
# deeply nested empty nodes cannot be stored at all.
MAX_POST_BODY_BYTES = 256 * 1024


class PostBase(SanitizedBaseModel):
    name: str = Field(..., min_length=1, max_length=255)


class PostCreate(PostBase, PropertiesOnCreate):
    name: TitleStr = Field(..., min_length=1, max_length=255)
    initiative_id: int
    # A Lexical editor state, the same shape a native file stores — which
    # is what lets a post carry inline images and smart chips. Empty is
    # allowed: a headline with a picture under it is a legitimate notice.
    body: LexicalState = Field(default_factory=dict)
    tag_ids: Optional[List[int]] = None
    # Initial sharing — the same grant list the PUT /grants endpoint takes.
    # A board notice defaults to readable by the whole initiative, which is the
    # point of posting it.
    grants: List[ResourceGrantSchema] = Field(default_factory=initiative_readable)
    #: When the notice should go up. Omitted (or in the past) posts it now.
    #: Until then it is a draft: only the people who could edit it see it, and
    #: nobody is notified.
    scheduled_for: Optional[AwareDatetime] = None
    #: The question the notice asks, if it asks one. Written with the post
    #: rather than added afterwards, so a notice and its question are one
    #: submission and there is no window where the poll failed to attach.
    poll: Optional[PollWrite] = None


class PostUpdate(SanitizedBaseModel):
    name: Optional[TitleStr] = Field(default=None, min_length=1, max_length=255)
    body: Optional[LexicalState] = None
    #: Move or clear a *pending* schedule. ``null`` publishes the draft now; a
    #: new instant moves it. Meaningless once the notice is up — a published
    #: post cannot be unpublished, because the people it was announced to have
    #: already been told.
    scheduled_for: Optional[AwareDatetime] = None


class PostReactionSettings(SanitizedBaseModel):
    """The reactions switch on one notice — the body and the reply of
    ``PUT /posts/{post_id}/reactions``.

    The comment switch has a generic route because every tool is commentable;
    this one does not, because only a post takes reactions of its own.
    """

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    reactions_enabled: bool


class PostPinUpdate(SanitizedBaseModel):
    """Pin or unpin one post. ``pinned`` false clears the expiry with it —
    an expiry belongs to a pin, and keeping a stale one around would silently
    apply to the next pin."""

    pinned: bool = True
    #: Optional; when set the pin lapses at this instant and the post falls
    #: back into the feed by date. Must be in the future.
    expires_at: Optional[AwareDatetime] = None

    @model_validator(mode="after")
    def validate_expiry(self) -> "PostPinUpdate":
        if not self.pinned and self.expires_at is not None:
            raise ValueError("An expiry only means something on a pin")
        return self


class PostSummary(PostBase, ToolSummaryBase):
    """A post without its body — for the surfaces that show one in a line.

    The board is not one of them: it renders notices, so its list returns
    :class:`PostRead`. This shape is for the guild-wide table, recents, and
    anywhere else a post is a row rather than a thing being read.
    """

    #: Who wrote it, ready to draw: handle, picture, what they wear around it,
    #: and how they are appearing. The same shape a comment's author takes, so
    #: a person looks the same wherever the app shows them.
    author: Optional[CommentAuthor] = None
    #: The first line or so of the body as plain text. Derived on the way out,
    #: never stored — the body is the truth, and a stored copy would go stale
    #: the first time somebody edited it.
    excerpt: MentionStr = ""
    pinned_at: Optional[datetime] = None
    pinned_by: Optional[PersonId] = None
    pin_expires_at: Optional[datetime] = None
    #: Whether the pin above is in force *right now*. Served rather than
    #: recomputed client-side so the board and the API agree on the boundary
    #: case of an expiry that has just passed.
    is_pinned: bool = False
    #: When the notice went up, or ``null`` while it is still a scheduled
    #: draft. A reader only ever sees this set — a draft reaches its writers
    #: alone.
    published_at: Optional[datetime] = None
    #: When it is due to go up. Set only on a draft; publishing clears nothing,
    #: so a notice that was scheduled keeps the record of when it was meant to
    #: land.
    scheduled_for: Optional[datetime] = None
    #: Whether it is live. The one-field form of ``published_at is not null``,
    #: served so the board and the API agree at the boundary.
    is_published: bool = True
    #: Whether THIS reader has read it. The board marks a notice read once it
    #: has been on screen, so for most rows on most pages this is true; it is
    #: served per-reader and means nothing about anybody else.
    is_read: bool = False
    #: How many people have read it. Everyone who can see the notice can see
    #: this — a board is a place things are said out loud, and knowing whether
    #: a notice landed is the point of saying it there.
    read_count: int = 0
    #: When false the notice takes no reactions — the board renders no bar and
    #: the API refuses to read or add one. The reactions already on it are kept,
    #: the same way turning a thread off keeps its comments.
    reactions_enabled: bool = True
    #: When a moderator closed its comments: they still read, and nothing is
    #: added or edited until it is reopened. Null while it is open.
    comments_locked_at: Optional[datetime] = None
    #: How many comments the post has. Served with the board so a reader can
    #: see there is a conversation without opening the post to find out — and
    #: so an empty thread can invite the first one.
    comment_count: int = 0
    #: Reactions ride along with the post rather than costing a request per
    #: row: a board renders its chips from the one list call.
    reactions: List[ReactionGroup] = Field(default_factory=list)

    @classmethod
    def derived_fields(
        cls, row: Any, *, context: ActorContext, user_id: Optional[int]
    ) -> dict[str, Any]:
        # Local import avoids a schema -> service import cycle.
        from app.services.tenant import reactions as reactions_service

        reaction_rows = getattr(row, "_reactions", None)
        return {
            "author": row.creator,
            "excerpt": post_excerpt(row.body),
            "is_pinned": row.is_pinned_now(),
            "reactions": (
                reactions_service.summarize(reaction_rows, viewer_id=user_id)
                if reaction_rows and row.reactions_enabled
                else []
            ),
        }


class PostRead(PostSummary):
    #: The Lexical editor state. Present on the board list too, because a board
    #: renders its notices rather than a table of headlines — which is why that
    #: list pages small.
    body: LexicalState = Field(default_factory=dict)
    #: The question this notice asks, if it asks one — tallies, this reader's
    #: own ballot and all. Carried with the post rather than fetched per card:
    #: a board renders its polls, and five cards must not be five more requests.
    #: Absent from :class:`PostSummary` on purpose — a one-line surface shows a
    #: notice, not a ballot paper.
    poll: Optional[PollRead] = None

    @classmethod
    def derived_fields(
        cls, row: Any, *, context: ActorContext, user_id: Optional[int]
    ) -> dict[str, Any]:
        poll = getattr(row, "poll", None)
        return {
            **super().derived_fields(row, context=context, user_id=user_id),
            "poll": serialize_poll(poll) if poll is not None else None,
        }


#: How many notices one "I have seen these" request may carry. A page of the
#: board is twenty; this leaves room for a reader who scrolled several pages
#: before the batch flushed, and refuses a list nobody's screen produced.
MAX_READ_MARKS = 200


class PostReadMarks(SanitizedBaseModel):
    """The notices a reader has just had on screen."""

    post_ids: List[int] = Field(..., min_length=1, max_length=MAX_READ_MARKS)


class PostReadReceipt(SanitizedBaseModel):
    """How many of them were not already read. The client does not need this to
    render anything — it is what makes the call answerable and testable."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    marked: int = 0


class PostReader(SanitizedBaseModel):
    """One person on a notice's roster, named the way reactors are named."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    discriminator: int
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    #: What they have put around their picture. Carried on the person rather
    #: than fetched per row, so the roster dresses its avatars the way every
    #: other list of people in the app does.
    profile_decorations: ProfileDecorations = Field(default_factory=ProfileDecorations)
    #: When they read it. Absent for somebody who has not.
    read_at: Optional[datetime] = None


class PostReaders(SanitizedBaseModel):
    """Who has read a notice and who it is still waiting on.

    "Waiting" is the people the notice was *shared with*, not everybody in the
    initiative: a board of a hundred where a notice went to five is not
    ninety-five people ignoring it. The author is in neither list — writing a
    notice is not reading it.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    read: List[PostReader] = Field(default_factory=list)
    unread: List[PostReader] = Field(default_factory=list)


def post_reader(profile: Any, *, read_at: Optional[datetime] = None) -> PostReader:
    """One roster entry from a member profile. Built through the model rather
    than copied onto it, so the guild's name-visibility rule runs."""
    return PostReader(
        id=profile.id,
        username=profile.username,
        discriminator=profile.discriminator,
        display_name=getattr(profile, "display_name", None),
        avatar_url=getattr(profile, "avatar_url", None),
        profile_decorations=ProfileDecorations.model_validate(
            getattr(profile, "profile_decorations", None) or {}
        ),
        read_at=read_at,
    )


class PostListResponse(PageMeta):
    items: List[PostRead]


def post_text(body: Any) -> str:
    """The words in a Lexical editor state, whitespace-collapsed.

    Walks every node collecting ``text``, which is where a text node, a
    mention and a smart chip's label all keep their words — the same field the
    search extractor reads in SQL, so a post reads the same way in a search
    result, in a recents tab, and to the length check. Anything with no words
    of its own (an image, a divider) contributes nothing rather than a
    placeholder.
    """
    parts: list[str] = []

    def walk(node: Any) -> None:
        if not isinstance(node, dict):
            return
        text = node.get("text")
        if isinstance(text, str) and text:
            parts.append(text)
        children = node.get("children")
        if isinstance(children, list):
            for child in children:
                walk(child)

    if isinstance(body, dict):
        walk(body.get("root"))

    return " ".join(" ".join(parts).split())


def post_body_too_long(body: Any) -> bool:
    """Whether a body breaks either ceiling a post is held to.

    THE rule, in one place, because there are two ways in — the endpoints and
    an import — and they were allowed to disagree once already: the envelope
    checked the character count and let a large, low-text Lexical structure
    through, which the endpoints would then refuse to save again.

    Two ceilings because they answer different questions. The character count
    is the product rule — a board is read, not studied, and something this long
    is a file. The byte size is structural, and independent of how much of
    it is words: images and files are references rather than embedded data, so
    a legitimate notice is nowhere near it and only a hand-made payload of
    deeply nested empty nodes trips it.
    """
    import json

    clean = body or {}
    if len(post_text(clean)) > MAX_POST_TEXT_CHARS:
        return True
    return len(json.dumps(clean).encode("utf-8")) > MAX_POST_BODY_BYTES


#: A mention the excerpt's cut goes through.
_CUT_MENTION = re.compile(r"@\[\]\(\d*$")


def post_excerpt(body: Any, *, limit: int = EXCERPT_CHARS) -> str:
    """The first line or so of a post, for the surfaces that show one in a
    line — recents, search, the guild table. A mention reads as its markdown,
    ``@[](42)``, which the client names."""
    joined = post_text(with_mention_markup(body))
    if len(joined) <= limit:
        return joined
    # Cut on a word boundary where there is one nearby, so the excerpt does not
    # end mid-word, and leave out a mention the cut goes through.
    cut = joined[: limit - 1]
    space = cut.rfind(" ")
    if space > limit // 2:
        cut = cut[:space]
    return _CUT_MENTION.sub("", cut) + "…"
