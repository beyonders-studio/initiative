"""Feedback: an idea, something that got in somebody's way, or what they love,
filed as a case on the team's board.

A sender who ticks that the team may contact them is the case's filer: the team
starts the conversation, and the case reaches their tickets once the team has
written to them. Any other sender's words are the case's description.

The app context they chose to send goes into the description: the version,
the platform, the language, the theme, the page's route with every id left
out, and the width of the window.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional, Sequence

from app.core.intake import FeedbackTopic, IntakeStream
from app.models.platform.user import User
from app.services.platform.intake import CaseFiler, CaseRefs, open_case

if TYPE_CHECKING:
    from app.schemas.platform.ticket import DeviceContext
    from app.services.platform.evidence import PreparedEvidence

#: How much of what they wrote names the case on the team's board.
TITLE_LENGTH = 80


class NowhereToSend(Exception):
    """No project is bound to receive feedback."""


async def send(
    *,
    sender: User,
    topic: FeedbackTopic,
    body: str,
    contactable: bool,
    context: Optional["DeviceContext"] = None,
    evidence: Sequence["PreparedEvidence"] = (),
    now: Optional[datetime] = None,
    idea_task_id: Optional[int] = None,
) -> None:
    """File feedback as a case on the team's board, titled by its kind and how
    what they wrote begins. Their words open the conversation with a
    contactable sender and go into the description for any other. Sent with
    the published idea they voted for while writing it, it is joined to that
    idea."""
    moment = now or datetime.now(timezone.utc)
    first = body.strip().splitlines()[0].strip()
    if len(first) > TITLE_LENGTH:
        first = first[: TITLE_LENGTH - 1].rstrip() + "…"

    lines = [
        f"Feedback ({topic.value}) from account {sender.id}, who "
        + (
            "may be contacted about it."
            if contactable
            else "did not offer to be contacted."
        )
    ]
    if not contactable:
        lines += ["", body]

    outcome = await open_case(
        IntakeStream.feedback,
        title=f"{topic.value.capitalize()}: {first}",
        body="\n".join(lines),
        refs=CaseRefs(subject_user=sender.id, reported_at=moment),
        now=moment,
        filer=(
            CaseFiler(user_id=sender.id, subject=None, words=body)
            if contactable
            else None
        ),
        evidence=evidence,
        evidence_by=sender.id,
        topic=topic.value,
        device=context,
    )
    if outcome is None:
        raise NowhereToSend
    if idea_task_id is not None:
        from app.services.platform import ideas

        await ideas.join_sent(outcome.task_id, idea_task_id, sender)
