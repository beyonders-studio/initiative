"""Schemas for the question a notice asks.

A poll is offered inline with its post — the board renders the question under
the body, and a card that had to fetch a poll per row would be a board that
fetches five polls per page. So :class:`PollRead` is nested in the post's own
read schema, complete with this reader's ballot, and the only thing that costs
a request of its own is the roster of who chose what.

Two settings decide how much of it a given reader is shown, and they are
different questions:

* ``hide_results`` withholds the **numbers** until the reader has voted or the
  poll has closed, so early answers do not steer later ones. It is served as
  ``results_visible`` rather than inferred client-side, because the reader's
  own ballot is part of the answer and the client should not have to
  re-derive it.
* ``is_anonymous`` withholds the **names** behind the numbers, permanently.
  Counts are shown either way.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import AwareDatetime, ConfigDict, Field, model_validator

from app.models.tenant.post_poll import (
    MAX_POLL_OPTION_CHARS,
    MAX_POLL_OPTIONS,
    MIN_POLL_OPTIONS,
)
from app.schemas.base import SanitizedBaseModel
from app.schemas.platform.user import ProfileDecorations


class PollOptionWrite(SanitizedBaseModel):
    """One answer, as the author typed it."""

    text: str = Field(..., min_length=1, max_length=MAX_POLL_OPTION_CHARS)


class PollWrite(SanitizedBaseModel):
    """A whole poll, sent as one thing.

    Options are a list rather than individually addressable rows: a poll is
    written and read as a unit, and "the third choice" only means anything in
    the context of the other two. Sending it again replaces it — which the
    service refuses once anybody has voted on a different set of options,
    because a ballot cast for "Tuesday" must not silently become a ballot for
    whatever took third place.
    """

    question: str | None = Field(default=None, max_length=255)
    options: list[PollOptionWrite] = Field(
        ..., min_length=MIN_POLL_OPTIONS, max_length=MAX_POLL_OPTIONS
    )
    allows_multiple: bool = False
    is_anonymous: bool = False
    hide_results: bool = False
    #: When voting stops. Omitted leaves it open for as long as the notice
    #: stands; a time that has already passed is refused rather than creating a
    #: poll nobody can answer.
    closes_at: AwareDatetime | None = None


class PollVoteWrite(SanitizedBaseModel):
    """A ballot. One id on a single-choice poll, any number on a multiple one;
    an empty list is a retraction, which the DELETE route also expresses."""

    option_ids: list[int] = Field(default_factory=list, max_length=MAX_POLL_OPTIONS)

    @model_validator(mode="after")
    def distinct_choices(self) -> PollVoteWrite:
        if len(set(self.option_ids)) != len(self.option_ids):
            raise ValueError("The same choice cannot be picked twice")
        return self


class PollOptionRead(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: int
    text: str
    position: int
    #: How many people chose it, or ``null`` while the results are withheld.
    #: Null rather than zero, so a client renders "not yet" instead of a
    #: confident nought.
    vote_count: int | None = None
    #: Whether THIS reader chose it. Always answered — a voter can see their own
    #: ballot even on a poll whose numbers are hidden.
    voted_by_me: bool = False


class PollRead(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: int
    question: str | None = None
    allows_multiple: bool = False
    is_anonymous: bool = False
    hide_results: bool = False
    closes_at: datetime | None = None
    #: Whether voting has stopped. Served rather than recomputed client-side so
    #: the card and the API agree on a close time that has just passed.
    is_closed: bool = False
    options: list[PollOptionRead] = Field(default_factory=list)
    #: Whether this reader has answered.
    has_voted: bool = False
    #: Whether the numbers are being shown. False only on a ``hide_results``
    #: poll that is still open and that this reader has not answered.
    results_visible: bool = True
    #: How many people have answered — not how many boxes were ticked, which on
    #: a multiple-choice poll is a larger and less meaningful number. ``null``
    #: while the results are withheld.
    total_voters: int | None = None
    #: Whether anybody has answered, and so whether the choices and the two
    #: switches that can only tighten are now fixed.
    #:
    #: Answered even while the results are withheld, which ``total_voters`` is
    #: not: this is what an author needs to know before they start editing, and
    #: it discloses only that the question has been answered — never by how
    #: many, or by whom. Without it the editor would offer edits the server
    #: refuses, on exactly the polls whose numbers are hidden.
    is_locked: bool = False


class PollVoter(SanitizedBaseModel):
    """One person on a poll's roster, named the way readers and reactors are."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    discriminator: int
    display_name: str | None = None
    avatar_url: str | None = None
    profile_decorations: ProfileDecorations = Field(default_factory=ProfileDecorations)


class PollOptionVoters(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    option_id: int
    voters: list[PollVoter] = Field(default_factory=list)


class PollVoters(SanitizedBaseModel):
    """Who chose what, and who has not answered.

    "Not answered" is the people the notice was **shared with**, the same
    denominator the read roster uses — a board of a hundred where a notice went
    to five is not ninety-five people ignoring the question. Unlike that roster
    the author is included: writing a notice is not reading it, but writing a
    question does not stop you answering it.

    Served only for a poll that is not anonymous, and only once the results are
    visible to the caller.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    options: list[PollOptionVoters] = Field(default_factory=list)
    not_voted: list[PollVoter] = Field(default_factory=list)


def poll_voter(profile: Any) -> PollVoter:
    """One roster entry from a member profile. Built through the model rather
    than copied onto it, so the guild's name-visibility rule runs."""
    return PollVoter(
        id=profile.id,
        username=profile.username,
        discriminator=profile.discriminator,
        display_name=getattr(profile, "display_name", None),
        avatar_url=getattr(profile, "avatar_url", None),
        profile_decorations=ProfileDecorations.model_validate(
            getattr(profile, "profile_decorations", None) or {}
        ),
    )


def serialize_poll(poll: Any) -> PollRead:
    """One poll, as this reader may see it.

    The tallies are stamped on the row by
    ``services.tenant.post_polls.annotate_poll_state`` — one query per page
    rather than per card — and this only decides how much of them to hand over.
    A poll nothing has annotated reads as one nobody has answered, which is what
    a freshly written poll is.
    """
    counts: dict[int, int] = getattr(poll, "_vote_counts", None) or {}
    mine: set[int] = getattr(poll, "_my_option_ids", None) or set()
    voters: int = int(getattr(poll, "_total_voters", 0) or 0)
    answered: bool = bool(getattr(poll, "_has_votes", voters > 0))
    closed = poll.is_closed()
    # Withheld only while there is still something to steer: once somebody has
    # answered, or the poll has closed, the numbers are theirs to see.
    visible = not poll.hide_results or bool(mine) or closed
    return PollRead(
        id=poll.id,
        question=poll.question,
        allows_multiple=poll.allows_multiple,
        is_anonymous=poll.is_anonymous,
        hide_results=poll.hide_results,
        closes_at=poll.closes_at,
        is_closed=closed,
        options=[
            PollOptionRead(
                id=option.id,
                text=option.text,
                position=option.position,
                vote_count=counts.get(option.id, 0) if visible else None,
                voted_by_me=option.id in mine,
            )
            for option in sorted(poll.options or [], key=lambda o: (o.position, o.id))
        ],
        has_voted=bool(mine),
        results_visible=visible,
        total_voters=voters if visible else None,
        is_locked=answered,
    )
