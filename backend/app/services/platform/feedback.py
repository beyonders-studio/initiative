"""Telling whoever runs this server what somebody thinks.

Feedback is one-way until the team answers: a case in the feedback stream that
its sender follows under their tickets, and may write on once the team has
written to them. Where the app was when they sent it travels with it, as they
saw it before sending and could remove: the version, the platform, the
language, the theme, the page's route with every id left out, and the width
of the window.

A problem that needs an answer is not feedback. The sheet sends that to
support instead, before it is filed, so nothing here moves a case between
streams.
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


def _title(topic: FeedbackTopic, body: str) -> str:
    """The case's name on the board: the kind, and how what they wrote
    begins."""
    first = body.strip().splitlines()[0].strip()
    if len(first) > TITLE_LENGTH:
        first = first[: TITLE_LENGTH - 1].rstrip() + "…"
    return f"{topic.value.capitalize()}: {first}"


async def send(
    *,
    filer: User,
    topic: FeedbackTopic,
    body: str,
    context: Optional["DeviceContext"] = None,
    evidence: Sequence["PreparedEvidence"] = (),
    now: Optional[datetime] = None,
) -> int:
    """File feedback as a case its sender follows. Returns the case's task id.

    Their words open the case, said to them; the description is the
    platform's summary, with the app's context where they sent it.
    """
    moment = now or datetime.now(timezone.utc)
    outcome = await open_case(
        IntakeStream.feedback,
        title=_title(topic, body),
        body=f"Feedback ({topic.value}) from account {filer.id}.",
        refs=CaseRefs(subject_user=filer.id, reported_at=moment),
        now=moment,
        filer=CaseFiler(user_id=filer.id, subject=None, words=body, device=context),
        evidence=evidence,
        topic=topic.value,
    )
    if outcome is None:
        raise NowhereToSend
    return outcome.task_id
