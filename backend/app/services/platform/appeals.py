"""Asking for an account's suspension to be lifted.

A suspended account reaches its time-out screen and nothing else. An appeal is
the one thing it may file from there: a moderation case about itself, which it
follows on that screen and talks on with the team, one open at a time.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.core.intake import APPEAL, IntakeStream
from app.models.platform.user import User, UserStatus
from app.services.platform.intake import CaseFiler, CaseRefs, open_case

if TYPE_CHECKING:
    from app.services.platform.evidence import PreparedEvidence


class NotSuspended(Exception):
    """The account is not suspended, so there is nothing to appeal."""


class NowhereToSend(Exception):
    """No project is bound to receive moderation cases."""


def _description(account: User) -> str:
    lines = [f"Account {account.id} asks for its suspension to be lifted."]
    if account.status_changed_at is not None:
        lines.append(f"Suspended since {account.status_changed_at.date().isoformat()}.")
    if account.status_reason:
        lines += ["", f"Reason it was given: {account.status_reason}"]
    return "\n".join(lines)


async def appeal(
    *,
    account: User,
    body: str,
    evidence: Sequence[PreparedEvidence] = (),
    now: datetime | None = None,
) -> int:
    """File ``account``'s appeal against its suspension. Returns the case's
    task id. Raises ``CaseCapReached`` while an earlier appeal is still open.
    """
    if account.status != UserStatus.suspended:
        raise NotSuspended
    moment = now or datetime.now(UTC)
    outcome = await open_case(
        IntakeStream.moderation,
        title=f"Suspension appeal from account {account.id}",
        body=_description(account),
        refs=CaseRefs(subject_user=account.id, reported_at=moment),
        now=moment,
        filer=CaseFiler(user_id=account.id, subject=None, words=body),
        evidence=evidence,
        topic=APPEAL,
    )
    if outcome is None:
        raise NowhereToSend
    return outcome.task_id
