"""Feedback: how the app is working for somebody, filed as a case on the
team's board.

Feedback is a rating out of five and two optional answers: what they like most
and what they wish it did. A sender who ticks that the team may contact them is
the case's filer: the team starts the conversation, and the case reaches their
tickets once the team has written to them. Any other sender's answers are the
case's description.

The app context they chose to send goes into the description: the version,
the platform, the language, the theme, the page's route with every id left
out, and the width of the window.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional, Sequence

from app.core.intake import IntakeStream
from app.models.platform.user import User
from app.services.platform.intake import CaseFiler, CaseRefs, open_case

if TYPE_CHECKING:
    from app.schemas.platform.ticket import FeedbackContext
    from app.services.platform.evidence import PreparedEvidence

#: How much of what they wrote names the case on the team's board.
TITLE_LENGTH = 80

#: The context's fields, in the order the team reads them, with their labels.
_CONTEXT_LABELS = (
    ("app_version", "App version"),
    ("platform", "Platform"),
    ("locale", "Language"),
    ("theme", "Theme"),
    ("route", "Page"),
    ("viewport", "Window"),
)


class NowhereToSend(Exception):
    """No project is bound to receive feedback."""


async def send(
    *,
    sender: User,
    rating: int,
    likes: Optional[str],
    wishes: Optional[str],
    contactable: bool,
    context: Optional["FeedbackContext"] = None,
    evidence: Sequence["PreparedEvidence"] = (),
    now: Optional[datetime] = None,
) -> None:
    """File feedback as a case on the team's board.

    The title is the stars and the first line of the wish, or of what they
    like. The answers, under the questions they answer, open the conversation
    with a contactable sender and go into the description for any other.
    """
    moment = now or datetime.now(timezone.utc)
    stars = "★" * rating + "☆" * (5 - rating)
    words = "\n\n".join(
        [f"{stars} ({rating} of 5)"]
        + [
            f"**{question}**\n{answer}"
            for question, answer in (
                ("What do you like most?", likes),
                ("What do you wish it did?", wishes),
            )
            if answer
        ]
    )
    title = stars
    if said := wishes or likes:
        first = said.splitlines()[0].strip()
        if len(first) > TITLE_LENGTH:
            first = first[: TITLE_LENGTH - 1].rstrip() + "…"
        title = f"{stars} {first}"

    lines = [
        f"Feedback from account {sender.id}, who "
        + (
            "may be contacted about it."
            if contactable
            else "did not offer to be contacted."
        )
    ]
    if not contactable:
        lines += ["", words]
    if context is not None:
        sent = [
            f"- {label}: `{value}`"
            for name, label in _CONTEXT_LABELS
            if (value := getattr(context, name))
        ]
        if sent:
            lines += ["", "Where the app was:", *sent]

    outcome = await open_case(
        IntakeStream.feedback,
        title=title,
        body="\n".join(lines),
        # A scale runs 0 to 100: a fifth for each star.
        refs=CaseRefs(subject_user=sender.id, reported_at=moment, rating=rating * 20),
        now=moment,
        filer=(
            CaseFiler(user_id=sender.id, subject=None, words=words)
            if contactable
            else None
        ),
        evidence=evidence,
        evidence_by=sender.id,
    )
    if outcome is None:
        raise NowhereToSend
