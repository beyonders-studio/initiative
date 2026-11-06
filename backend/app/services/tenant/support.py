"""Asking whoever runs this deployment for help.

Two kinds of question, told apart by topic (``SupportTopic``):

- **About a community** (``community``, ``data_request``). Whether its members
  can ask is an **operator** entitlement
  (the paid rule ``help_requests``), not something the community's
  own admins switch on: the deployment that would receive the requests is the
  one that decides it is staffing them. Off is the default, and the "Ask for
  help" control then offers the support address. A ``data_request`` — a copy
  of the community's data, or its erasure — is its seat holder's to make.
- **About themselves** (``account``, ``billing``, ``other``). Anybody signed
  in may ask wherever support is taken at all: a person locked out of
  something has no community to ask from.

Where a request lands is not this module's business either — it becomes a case
in the ``support`` stream, and the binding says which project that is.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional, Sequence

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.intake import COMMUNITY_SUPPORT_TOPICS, IntakeStream, SupportTopic
from app.services.platform import rules
from app.models.platform.user import User
from app.db import cohorts
from app.services.platform.intake import CaseFiler, CaseRefs, open_case

if TYPE_CHECKING:
    from app.services.platform.evidence import PreparedEvidence

#: Longest a request's summary and its body may be. The case is a task, whose
#: title is a line; the body is a description somebody reads, not a log.
SUBJECT_LENGTH = 200
BODY_LENGTH = 5000


class SupportUnavailable(Exception):
    """This deployment does not take this help request from this person."""


class NowhereToSend(Exception):
    """The entitlement is on, but no project is bound to receive support."""


async def _entitled(session: AsyncSession, guild_id: int) -> bool:
    """Whether this community's members may ask: its ``help_requests`` rule.

    Read on the caller's own guild-routed session: the table admits a member to
    their own community's rules, so this is the same answer the settings page
    gets.
    """
    return await rules.community_value(session, guild_id, "help_requests")


async def community_topics(requester: User, guild_id: int) -> frozenset[SupportTopic]:
    """The community topics ``requester`` may ask about from ``guild_id``:
    none where the community takes no help requests or they are not in it,
    and ``data_request`` only for its seat holder.

    Asked on a session of their own, routed into the community through the
    ordinary entry point, so membership and every gate apply exactly as they
    do on a read: somebody who cannot reach the community cannot ask from it.
    A platform grant into it is not membership, and asks nothing here.
    """
    from app.api.deps import GuildAccessError, establish_guild_access

    async with cohorts.request_sessionmaker(guild_id)() as session:
        account = await session.merge(requester, load=False)
        try:
            context = await establish_guild_access(session, account, guild_id)
        except GuildAccessError:
            return frozenset()
        if context.membership is None or not await _entitled(session, guild_id):
            return frozenset()
        if context.guild_seat:
            return COMMUNITY_SUPPORT_TOPICS
        return frozenset({SupportTopic.community})


async def entitled(requester: User, guild_id: int) -> bool:
    """Whether ``requester`` may ask for help about ``guild_id``."""
    return SupportTopic.community in await community_topics(requester, guild_id)


def offered_topics(
    community: frozenset[SupportTopic],
) -> list[SupportTopic]:
    """Every topic a person may ask about, given the community topics open to
    them where they are standing: their own always, in declaration order."""
    return [
        topic
        for topic in SupportTopic
        if topic not in COMMUNITY_SUPPORT_TOPICS or topic in community
    ]


async def request_help(
    *,
    guild_id: Optional[int],
    requester: User,
    subject: str,
    body: str,
    topic: SupportTopic = SupportTopic.community,
    evidence: Sequence["PreparedEvidence"] = (),
    now: Optional[datetime] = None,
) -> int:
    """File one help request as a support case. Returns the case's task id.

    The case names who asked, and for a question about a community which one,
    as the weak refs every case carries, and records them as its filer: their
    subject and their words open the case, said to them, so the conversation
    starts where they started it. The description is the platform's summary.
    What they attached is stored with it.

    A question about a community is held to what that community lets them
    ask (:func:`community_topics`); a question about themselves is not about
    any community, and records none.
    """
    about_community = topic in COMMUNITY_SUPPORT_TOPICS
    if about_community and (
        guild_id is None or topic not in await community_topics(requester, guild_id)
    ):
        raise SupportUnavailable
    subject_guild = guild_id if about_community else None

    moment = now or datetime.now(timezone.utc)
    summary = f"Help request ({topic.value}) from account {requester.id}"
    outcome = await open_case(
        IntakeStream.support,
        title=subject,
        body=(
            f"{summary}, about community {subject_guild}."
            if subject_guild is not None
            else f"{summary}."
        ),
        refs=CaseRefs(
            subject_user=requester.id,
            subject_guild=subject_guild,
            reported_at=moment,
        ),
        now=moment,
        filer=CaseFiler(user_id=requester.id, subject=subject, words=body),
        evidence=evidence,
        topic=topic.value,
    )
    if outcome is None:
        # Nothing is bound to receive it. Said plainly rather than answering
        # "we have it" to a request that reached nobody.
        raise NowhereToSend
    return outcome.task_id
