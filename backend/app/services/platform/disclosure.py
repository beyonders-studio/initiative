"""Telling whoever runs this server about a security problem.

Three ways in, one stream:

- **The form**, for a signed-in person who found something: a case in the
  security stream, which they follow under their tickets and talk on with the
  team.
- **"This wasn't me"**, the link in every email about a change to how an
  account signs in (``app.services.auth.security_links``): it ends every
  session and files an ``account_compromise`` case about the account.
- **``/.well-known/security.txt``** (RFC 9116), for somebody outside: the
  security contact, and the form when the stream is bound.

A problem with the *software* rather than this server goes to the project
(``SECURITY.md``); operators forward what they receive with the case's
``tracker_key``.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from app.core.intake import IntakeStream, SecurityTopic
from app.models.platform.user import User
from app.services.platform.intake import CaseFiler, CaseRefs, open_case

if TYPE_CHECKING:
    from app.services.platform.evidence import PreparedEvidence

#: How long a published ``security.txt`` says it holds, from when it is read.
SECURITY_TXT_LIFETIME = timedelta(days=180)


class NowhereToSend(Exception):
    """No project is bound to receive security reports."""


async def report(
    *,
    filer: User,
    topic: SecurityTopic,
    subject: str,
    body: str,
    evidence: Sequence[PreparedEvidence] = (),
    now: datetime | None = None,
) -> int:
    """File a security report as a case the filer follows. Returns the
    case's task id. Their subject and words open the case, said to them; the
    description is the platform's summary."""
    moment = now or datetime.now(UTC)
    outcome = await open_case(
        IntakeStream.security,
        title=subject,
        body=f"Security report ({topic.value}) from account {filer.id}.",
        refs=CaseRefs(
            subject_user=filer.id,
            reported_at=moment,
            severity=topic.value,
        ),
        now=moment,
        filer=CaseFiler(user_id=filer.id, subject=subject, words=body),
        evidence=evidence,
        topic=topic.value,
    )
    if outcome is None:
        raise NowhereToSend
    return outcome.task_id


async def account_compromised(
    *, user_id: int, what_changed: str, now: datetime | None = None
) -> int | None:
    """File that ``user_id`` says a change to their credentials wasn't
    theirs. One case per account while it is open: a second link joins it.
    Returns the case's task id, or ``None`` where nothing is bound."""
    moment = now or datetime.now(UTC)
    outcome = await open_case(
        IntakeStream.security,
        title="An account says a credential change wasn't theirs",
        body=(
            f"Account {user_id} followed the 'This wasn't me' link in the "
            f"email about: {what_changed}. Every session it had was ended."
        ),
        refs=CaseRefs(
            subject_user=user_id,
            reported_at=moment,
            severity=SecurityTopic.account_compromise.value,
        ),
        dedupe_key=f"compromise:{user_id}",
        topic=SecurityTopic.account_compromise.value,
        detail=f"Followed again, about: {what_changed}.",
        now=moment,
    )
    return outcome.task_id if outcome is not None else None


def security_txt(
    *, contact: str | None, form_url: str | None, now: datetime | None = None
) -> str | None:
    """This server's ``security.txt``, or ``None`` with no address to name.

    A ``Contact`` line for the address, one for the form where security
    reports are taken, an ``Expires`` 180 days out, and the language.
    """
    if not contact:
        return None
    moment = now or datetime.now(UTC)
    address = contact if ":" in contact else f"mailto:{contact}"
    lines = [f"Contact: {address}"]
    if form_url:
        lines.append(f"Contact: {form_url}")
    expires = (moment + SECURITY_TXT_LIFETIME).replace(microsecond=0)
    lines.append(f"Expires: {expires.strftime('%Y-%m-%dT%H:%M:%SZ')}")
    lines.append("Preferred-Languages: en")
    return "\n".join(lines) + "\n"
