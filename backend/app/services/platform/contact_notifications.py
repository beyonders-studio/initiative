"""Telling somebody that somebody else is asking to reach them.

Four moments, one per direction of the two grants: a connection asked for and
answered, and permission to message asked for and answered. Each is a decision
waiting on a person, which is the whole reason they are worth interrupting for
-- a request nobody is told about sits in a list nobody opens, and the account
that sent it is left reading silence as a refusal.

Unlike a message, none of this is opaque to the server: a grant row names both
parties in the clear. So these carry the other account's handle and push to
every installation, not only the ones holding a message key store -- there is
nothing here to decrypt.

This runs on the system engine rather than the actor's session. Writing a
notification and reading push tokens are both things the recipient's account
owns, and the account doing the asking has no business reaching either.
"""

from __future__ import annotations

import logging

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.email_i18n import translate
from app.core.user_display import handle_of
from app.models.platform.contact_grant import ContactGrantKind
from app.models.platform.notification import NotificationType
from app.models.platform.user import User
from app.services.platform import (
    notice_outbox,
    user_ignores,
)

logger = logging.getLogger(__name__)

#: Which line each moment writes, and where tapping it lands. A connection is
#: answered from privacy settings and a message request from the inbox,
#: because that is where each one is acted on.
_MOMENTS: dict[tuple[ContactGrantKind, bool], tuple[NotificationType, str, str]] = {
    (ContactGrantKind.connection, False): (
        NotificationType.connection_requested,
        "contact.connectionRequested",
        "/profile/privacy",
    ),
    (ContactGrantKind.connection, True): (
        NotificationType.connection_accepted,
        "contact.connectionAccepted",
        "/profile/privacy",
    ),
    (ContactGrantKind.message, False): (
        NotificationType.message_request_received,
        "contact.messageRequested",
        "/messages",
    ),
    (ContactGrantKind.message, True): (
        NotificationType.message_request_accepted,
        "contact.messageAccepted",
        "/messages",
    ),
}


def _locale(user: User) -> str:
    return getattr(user, "locale", None) or "en"


async def notify(
    *,
    recipient_id: int,
    actor_id: int,
    kind: ContactGrantKind,
    accepted: bool,
) -> None:
    """Tell ``recipient_id`` that ``actor_id`` asked, or said yes.

    Failures here are logged and swallowed: the grant row is already written,
    and being told about it is not worth failing the request over.
    """
    from app.db.session import SystemSessionLocal

    try:
        async with SystemSessionLocal() as session:
            recipient = await session.get(User, recipient_id)
            actor = await session.get(User, actor_id)
            if recipient is None or actor is None:
                return
            # An ignored account's request is stored and stays out of the
            # recipient's sight; a notification would say what the hidden row
            # does not. Asked here rather than at the call site because the
            # answer is the recipient's own row, which the account doing the
            # asking cannot read from its own session. Not asked of an accept:
            # the one being told there started this.
            if not accepted and await user_ignores.ignores(
                session, user_id=recipient_id, other_user_id=actor_id
            ):
                return
            await _write(
                session,
                recipient=recipient,
                actor=actor,
                kind=kind,
                accepted=accepted,
            )
            await session.commit()
    except Exception:
        logger.exception("contact-grant notification failed")


async def _write(
    session: AsyncSession,
    *,
    recipient: User,
    actor: User,
    kind: ContactGrantKind,
    accepted: bool,
) -> None:
    notification_type, key, target_path = _MOMENTS[(kind, accepted)]
    actor_name = handle_of(actor)
    locale = _locale(recipient)
    title = translate(
        f"{key}.title", locale, namespace="notifications", actor=actor_name
    )
    body = translate(f"{key}.body", locale, namespace="notifications", actor=actor_name)
    data = {
        "actor_id": actor.id,
        "actor_name": actor_name,
        "target_path": target_path,
    }

    await notice_outbox.enqueue(
        session,
        [
            await notice_outbox.notice(
                session,
                recipient,
                notification_type,
                data,
                guild_id=None,
                push=(title, body),
                push_data={"type": notification_type.value, **data},
            )
        ],
    )
