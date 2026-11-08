"""Work waiting in the operations community, so its surfaces have something
on them on a fresh dev database.

Somebody who isn't staff files a ticket in each stream they can file in
(support and security, and feedback on Initiative Cloud), reports a comment to a community's
moderators, and reports another as illegal, which reaches the platform too
and is the moderation case they follow. A community's moderator then holds a
third comment for the platform, which opens a case of its own.

Everything is filed through the services the app's own routes call, so what
lands is what a person filing it would have left.
"""

from __future__ import annotations

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import establish_guild_access
from app.core.intake import (
    FeedbackTopic,
    IntakeStream,
    SecurityTopic,
    SupportTopic,
    offered_streams,
)
from app.core.moderation import HoldReason, LegalBasis, ReportReason
from app.core.search import SearchEntityType
from app.db import cohorts
from app.models.platform.guild import Guild
from app.models.platform.user import User
from app.models.tenant.comment import Comment
from app.services.platform import disclosure, feedback, holds
from app.services.tenant import moderation, support

#: Who files: a member of the primary community, not on the platform's staff.
FILER = "Elara Moonwhisper"
#: Who holds content for the platform: one of the primary community's admins.
MODERATOR = "Guildmaster Aldric"


async def _comments_seen_by(user: User, guild_id: int, *, skip: set[int]) -> list[int]:
    """Comments ``user`` can read in ``guild_id`` that neither they nor
    anybody in ``skip`` wrote, oldest first."""
    session = cohorts.request_sessionmaker(guild_id)()
    try:
        account = await session.merge(user, load=False)
        await establish_guild_access(session, account, guild_id)
        return list(
            (
                await session.exec(
                    select(Comment.id)
                    .where(Comment.created_by.not_in(skip | {user.id}))  # type: ignore[union-attr]
                    .order_by(Comment.id)
                    .limit(3)
                )
            ).all()
        )
    finally:
        await session.close()


async def seed(session: AsyncSession, users: dict[str, User], primary: Guild) -> int:
    """File the tickets, the reports and the hold. Returns how many cases
    were opened."""
    filer = users[FILER]
    moderator = users[MODERATOR]
    opened = 0

    await support.request_help(
        guild_id=None,
        requester=filer,
        topic=SupportTopic.account,
        subject="I can't change my email",
        body="The confirmation link says it expired, every time I try.",
    )
    await disclosure.report(
        filer=filer,
        topic=SecurityTopic.vulnerability,
        subject="A shared link shows more than it should",
        body="Opening a shared file's link while signed out shows its comments.",
    )
    opened += 2
    # Feedback lands only on Initiative Cloud.
    if IntakeStream.feedback in offered_streams():
        await feedback.send(
            sender=filer,
            topic=FeedbackTopic.idea,
            body="It would help to pin a comment to the top of a task.",
            contactable=True,
        )
        opened += 1

    targets = await _comments_seen_by(filer, primary.id, skip={moderator.id})
    if len(targets) < 3:
        print("  Fewer than three comments to report and hold; skipped those.")
        return opened
    spam, unlawful, held = targets
    await moderation.file_report(
        session,
        reporter=filer,
        target=SearchEntityType.comment,
        target_id=spam,
        reason=ReportReason.spam,
        detail="The same link, posted on every task.",
        guild_id=primary.id,
    )
    await moderation.file_report(
        session,
        reporter=filer,
        target=SearchEntityType.comment,
        target_id=unlawful,
        reason=ReportReason.illegal,
        legal_basis=LegalBasis.privacy,
        detail="It posts somebody's home address.",
        guild_id=primary.id,
    )
    opened += 1

    acting = cohorts.request_sessionmaker(primary.id)()
    try:
        account = await acting.merge(moderator, load=False)
        context = await establish_guild_access(acting, account, primary.id)
        await holds.place(
            acting,
            context,
            guild_id=primary.id,
            placed_by=moderator.id,
            request=holds.HoldRequest(
                target_type=SearchEntityType.comment.value,
                target_id=held,
                reason=HoldReason.legal_request,
                note="Kept at the request of the police, reference 2026-1142.",
            ),
        )
    finally:
        await acting.close()
    opened += 1
    return opened
