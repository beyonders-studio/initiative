from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING, List, TypeVar


from sqlalchemy import ColumnElement, Select, String, and_, cast, func, or_, update
from sqlmodel import select, delete
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.errors import CodedError
from app.core.messages import AuthMessages, GuildMessages, UserMessages
from app.core.audit_events import AuditEventType
from app.core.capabilities import Capability, roles_with_capability
from app.core.config import settings
from app.core import usernames
from app.core.security import has_usable_password
from app.core.encryption import (
    SALT_BIRTHDATE,
    decrypt_field,
    encrypt_field,
    hash_email,
)
from app.db import cohorts, post_commit
from app.db.session import set_rls_context
from app.models.platform.user import (
    ABSENT_STATUSES,
    User,
    UserRole,
    UserStatus,
)
from app.models.platform.app_setting import AppSetting
from app.models.platform.user_birthdate import UserBirthdate
from app.models.platform.user_notification_prefs import UserNotificationPrefs
from app.models.platform.user_profile_view import MemberProfile
from app.models.platform.guild import GuildMembership, CommunityRole
from app.services import audit as audit_service
from app.services import email as email_service
from app.services.auth import addresses
from app.services.auth import identity as identity_service
from app.services.auth import sessions as session_service
from app.services.auth import challenges as challenge_service
from app.services.auth import totp as totp_service
from app.services.platform import api_keys as api_keys_service
from app.services.platform import billing_ping
from app.services.platform import identity_refs
from app.services.platform.retention import ACCOUNT_DELETION
from app.services.platform import user_avatars as user_avatars_service
from app.models.tenant.resource_grant import ResourceGrant
from app.models.tenant.task import TaskAssignee
from app.models.platform.notification import Notification
from app.models.tenant.project_order import ProjectOrder
from app.models.tenant.project_favorite import ProjectFavorite
from app.models.tenant.recent_view import RecentView
from app.models.tenant.reaction_digest import ReactionDigestItem
from app.models.tenant.ai_member_key import GuildAIMemberKey

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.models.platform.sign_in_lock import SignInLock
    from app.schemas.platform.user import OperatorUserRead, UserRead, UserSummary
from app.models.tenant.ai_member_pref import GuildAIMemberPref
from app.models.platform.api_key import UserApiKey
from app.models.platform.account_change_hold import AccountChangeHold
from app.models.platform.user_token import UserToken
from app.models.tenant.event_reminder_dispatch import EventReminderDispatch
from app.models.tenant.task_assignment_digest import TaskAssignmentDigestItem
from app.db.request_context import SystemGuild, SystemMaintenance

_S = TypeVar("_S", bound=Select)


class SeatWouldBeEmptied(CodedError):
    """Removing this account would leave a community with no superadmin.

    Raised from the membership drop rather than from an eligibility check,
    because that is where it can be true at the moment it matters: the check
    an endpoint runs first is a report, and two accounts can each pass it by
    seeing the other.
    """

    def __init__(self, guild_names: List[str]) -> None:
        super().__init__(GuildMessages.CANNOT_VACATE_LAST_SUPERADMIN)
        self.guild_names = guild_names


async def _hold_seats_or_refuse(session: AsyncSession, user_id: int) -> None:
    """Take every seat lock this removal touches, then check under it.

    Ordered by guild id so two accounts leaving the same pair of communities
    queue behind each other instead of each holding what the other wants. The
    locks last to the end of the caller's transaction, which is the one that
    removes the memberships — so the answer is still true when it does.
    """
    from app.services.platform.guilds import lock_guild_seats, stranded_seats

    guild_ids = sorted(
        (
            await session.exec(
                select(GuildMembership.guild_id).where(
                    GuildMembership.user_id == user_id,
                    GuildMembership.role == CommunityRole.superadmin,
                )
            )
        ).all()
    )
    for guild_id in guild_ids:
        await lock_guild_seats(session, guild_id)
    if guild_ids and (stranded := await stranded_seats(session, user_id=user_id)):
        raise SeatWouldBeEmptied([name for _, name in stranded])


async def is_last_guild_superadmin(session: AsyncSession, user_id: int) -> List[str]:
    """Names of the communities where this account holds the only superadmin
    seat.

    Holding one is the only thing that stops this account being deleted.
    Owning content does not: ownership is released on the way out and the
    content is left unowned for a guild admin to claim.

    An ordinary admin does not count: a community left with admins but no
    seat has nobody inside who can appoint one, reach its billing, or change
    its sign-in. A community whose only member is this account
    does not count either — there is nobody there to strand.
    """
    from app.services.platform.guilds import stranded_seats

    return [name for _, name in await stranded_seats(session, user_id=user_id)]


async def _end_plugin_access(
    session: AsyncSession, guild_id: int, *, user_id: int
) -> None:
    """End everything this account let a plug-in do, in one guild.

    Every plug-in credential they connected, and every answer they gave a plug-in
    asking to act as them. Losing the account has to end the vendor access it
    opened, and consent to carry somebody's name has nothing left to mean once
    the account it named is gone.

    ``session`` is a system session routed into ``guild_id``.
    """
    from app.services.tenant import plugin_connections as plugin_connections_service
    from app.services.tenant import plugin_member_consents as consents_service

    await plugin_connections_service.delete_member_connections(
        session, user_id=user_id, reason="account_closed"
    )
    await consents_service.delete_member_consents(session, user_id=user_id)


async def _in_each_guild(
    guild_ids: Iterable[int],
    work: Callable[..., Awaitable[None]],
    *,
    user_id: int,
) -> None:
    """Run ``work(guild_session, guild_id, user_id=user_id)`` in each guild in
    turn, on a system session from the guild's cohort routed into it, committing
    each and telling plug-ins of the credentials it ended. Stops at the first
    failure, so the caller's shared half never runs ahead of a guild's."""
    for guild_id in guild_ids:
        async with cohorts.system_session(guild_id) as guild_session:
            await set_rls_context(guild_session, SystemGuild(guild_id))
            await work(guild_session, guild_id, user_id=user_id)
            await guild_session.commit()
            await post_commit.settle(guild_session)


async def _member_guild_ids(session: AsyncSession, user_id: int) -> list[int]:
    return list(
        (
            await session.exec(
                select(GuildMembership.guild_id).where(
                    GuildMembership.user_id == user_id
                )
            )
        ).all()
    )


async def _end_plugin_access_everywhere(session: AsyncSession, *, user_id: int) -> None:
    """The same, across every community the account belongs to.

    For the paths that keep the roster: a deleted account holds its memberships
    for its whole window, so there is no membership loop to hang this off, and
    the guilds have to be enumerated for it.
    """

    await _in_each_guild(
        await _member_guild_ids(session, user_id), _end_plugin_access, user_id=user_id
    )


async def _leave_guild(
    guild_session: AsyncSession, guild_id: int, *, user_id: int
) -> None:
    """Take an account out of one guild's content and its plug-ins.

    ``guild_session`` is a system session routed into ``guild_id``.
    """
    from app.services.tenant import initiatives as initiatives_service

    await initiatives_service.remove_user_from_guild_initiatives(
        guild_session, guild_id=guild_id, user_id=user_id
    )
    await _end_plugin_access(guild_session, guild_id, user_id=user_id)


async def _erase_in_guild(
    guild_session: AsyncSession, guild_id: int, *, user_id: int
) -> None:
    """Erase an account from one guild: its half of every account erasure.

    Leaves the guild as :func:`_leave_guild` does, takes the account's name out
    of content that embedded it as literal text, and deletes or un-attributes
    every per-person row the guild holds. Authorship stays: ``created_by`` is a
    weak reference — a plain integer, with no foreign key that fires across the
    schema boundary — so the id stays and the rows keep telling one departed
    author from another. ``account_erasure_rows_test`` asserts the outcome for
    each table.

    ``guild_session`` is a system session routed into ``guild_id``.
    """
    from app.models.tenant.calendar_event import CalendarEventAttendee
    from app.models.tenant.property import PropertyValue
    from app.models.tenant.queue import QueueItem
    from app.services.tenant.mention_parser import anonymize_user_mentions

    # Releases their owner grants (content is left unowned) and drops their
    # initiative memberships and plug-in access.
    await _leave_guild(guild_session, guild_id, user_id=user_id)
    # Written under the guild role that staged them, before the switch below.
    await guild_session.flush()

    # Scrub the display name out of content that embedded it as literal text
    # (@-mentions in comments, file mention nodes, digest name snapshots).
    await set_rls_context(guild_session, SystemMaintenance(guild_id))
    await anonymize_user_mentions(guild_session, user_id=user_id)
    await set_rls_context(guild_session, SystemGuild(guild_id))

    await guild_session.exec(
        delete(ProjectOrder).where(ProjectOrder.user_id == user_id)
    )
    await guild_session.exec(
        delete(ProjectFavorite).where(ProjectFavorite.user_id == user_id)
    )
    await guild_session.exec(delete(RecentView).where(RecentView.user_id == user_id))
    # The ledger that stops an event reminder being sent twice: one row per
    # (event, person), of no use to anyone once the person is gone.
    await guild_session.exec(
        delete(EventReminderDispatch).where(EventReminderDispatch.user_id == user_id)
    )
    # AI credentials (member API keys) + connection preference for this
    # guild — held in custody for them, so erasure removes them.
    await guild_session.exec(
        delete(GuildAIMemberKey).where(GuildAIMemberKey.user_id == user_id)
    )
    await guild_session.exec(
        delete(GuildAIMemberPref).where(GuildAIMemberPref.user_id == user_id)
    )
    await guild_session.exec(
        delete(TaskAssignmentDigestItem).where(
            TaskAssignmentDigestItem.user_id == user_id
        )
    )
    await guild_session.exec(
        update(TaskAssignmentDigestItem)
        .where(TaskAssignmentDigestItem.assigned_by_id == user_id)
        .values(assigned_by_id=None)
    )
    await guild_session.exec(
        delete(ReactionDigestItem).where(ReactionDigestItem.user_id == user_id)
    )
    await guild_session.exec(
        update(ReactionDigestItem)
        .where(ReactionDigestItem.reactor_id == user_id)
        .values(reactor_id=None)
    )
    # All per-user DAC grants (project, file, queue, counter group, calendar
    # event) live in the polymorphic resource_grants table; one delete clears
    # every resource type for this user in the schema.
    await guild_session.exec(
        delete(ResourceGrant).where(ResourceGrant.user_id == user_id)
    )
    await guild_session.exec(
        delete(TaskAssignee).where(TaskAssignee.user_id == user_id)
    )
    # Queue items: assigned-to is nullable, so just clear the pointer.
    await guild_session.exec(
        update(QueueItem).where(QueueItem.user_id == user_id).values(user_id=None)
    )
    await guild_session.exec(
        delete(CalendarEventAttendee).where(CalendarEventAttendee.user_id == user_id)
    )
    # Person-valued properties: NULL the reference (a value belongs to the
    # initiative, not to the person it names).
    await guild_session.exec(
        update(PropertyValue)
        .where(PropertyValue.value_user_id == user_id)
        .values(value_user_id=None)
    )


async def _drop_user_memberships(
    session: AsyncSession,
    user_id: int,
    *,
    actor_user_id: int | None = None,
    erase: bool = False,
) -> User:
    """Remove the user from every guild and initiative they belong to.
    Returns the loaded ``User`` row but does NOT commit — the caller is
    responsible for issuing exactly one commit so its own status / PII writes
    land in the same transaction as the membership cleanup.

    ``actor_user_id`` is who closed the account — the person themselves, or an
    operator doing it for them — and is what each departure record names.

    ``erase`` runs :func:`_erase_in_guild` in EVERY guild schema rather than
    :func:`_leave_guild` in the guilds they belong to: an erased account's
    content survives leaving a guild, and an account anonymized earlier has no
    membership rows left to enumerate (issue #794).

    Each guild's half is done and committed first, guild by guild, and the
    shared membership rows are deleted in the caller's transaction after. A
    guild that fails stops the closure before any membership goes, and running
    it again finishes it.
    """
    from app.models.platform.guild import Guild

    if erase:
        guild_ids = list((await session.exec(select(Guild.id))).all())
    else:
        guild_ids = await _member_guild_ids(session, user_id)

    # Every community this account holds the seat of keeps it. Asked here, under
    # the same locks the leave and demotion paths take, because this is the
    # transaction that removes the rows.
    await _hold_seats_or_refuse(session, user_id)

    await _in_each_guild(
        guild_ids, _erase_in_guild if erase else _leave_guild, user_id=user_id
    )

    memberships = (
        await session.exec(
            select(GuildMembership).where(GuildMembership.user_id == user_id)
        )
    ).all()
    for membership in memberships:
        await audit_service.record(
            session,
            event_type=AuditEventType.GUILD_MEMBER_REMOVED,
            actor_user_id=actor_user_id,
            target_user_id=user_id,
            guild_id=membership.guild_id,
            target_type="guild",
            target_id=membership.guild_id,
            detail={"role": membership.role.value, "via": "account_closed"},
        )
        await session.delete(membership)
        billing_ping.notify_membership_changed(membership.guild_id)

    return (await session.exec(select(User).where(User.id == user_id))).one()


async def deactivate_user(
    session: AsyncSession, user_id: int, *, actor_user_id: int | None = None
) -> None:
    """Reversibly deactivate a user account.

    Sets ``status = deactivated``, drops the user from every guild and
    initiative they belong to, and bumps ``token_version`` so any
    outstanding JWTs stop authenticating. PII (name, email, avatar) is
    left intact so the user can be reactivated by an operator later.

    ``actor_user_id`` is who asked for it — the account holder, or somebody
    acting on the account.
    """
    user = await _drop_user_memberships(session, user_id, actor_user_id=actor_user_id)
    # Owned content is released (left unowned for a guild admin to claim)
    # inside ``_drop_user_memberships`` above.
    user.status = UserStatus.deactivated
    user.token_version += 1
    user.updated_at = datetime.now(timezone.utc)
    session.add(user)
    await audit_service.record(
        session,
        event_type=AuditEventType.USER_DEACTIVATED,
        actor_user_id=actor_user_id,
        target_user_id=user_id,
        target_type="user",
        target_id=user_id,
        detail={"self": actor_user_id == user_id},
    )
    await session.commit()


async def request_account_deletion(
    session: AsyncSession, user_id: int, *, actor_user_id: int | None = None
) -> User:
    """Mark an account for erasure and keep it until the window runs out.

    The account stops existing for everybody else — absent from rosters,
    pickers and search, and its sessions end — while everything it holds stays
    exactly where it is. Memberships, initiative roles and owned files are
    **not** dropped, which is the whole difference from ``deactivate_user``:
    coming back restores the account whole rather than to an empty one.

    ``status_changed_at`` is the moment it was asked for, and so what the
    erasure date is counted from. Stamped unconditionally rather than through a
    general status setter — an account asked for twice would otherwise keep the
    first stamp and be erased early.

    Nothing is erased here. ``account_purge`` runs :func:`soft_delete_user` when
    the window ends, which is the erasure this used to do immediately.

    ``actor_user_id`` is who asked — the account holder, or somebody acting on
    the account.
    """
    user = await session.get(User, user_id)
    if user is None:
        raise ValueError(AuthMessages.USER_NOT_FOUND)
    # The account has withdrawn what it let plug-ins do, so they are told now
    # rather than in a month's time — the same call the community deletion
    # makes, for the same reason. A restored account comes back with its plug-in
    # connections gone, and reconnects them.
    await _end_plugin_access_everywhere(session, user_id=user_id)
    user.status = UserStatus.deleted
    user.status_changed_at = datetime.now(timezone.utc)
    # Every session this account holds ends here. Getting back in is what calls
    # the deletion off, so the way back has to start from a sign-in.
    user.token_version += 1
    user.updated_at = datetime.now(timezone.utc)
    session.add(user)
    await audit_service.record(
        session,
        event_type=AuditEventType.USER_DELETION_SCHEDULED,
        actor_user_id=actor_user_id,
        target_user_id=user_id,
        target_type="user",
        target_id=user_id,
        detail={"self": actor_user_id == user_id},
    )
    await session.commit()
    return user


async def cancel_account_deletion(
    session: AsyncSession,
    user_id: int,
    *,
    actor_user_id: int | None = None,
    via: str,
) -> bool:
    """Call off a pending erasure. Returns whether there was one to call off.

    ``via`` says how it was called off — ``sign_in`` when the holder simply
    came back, ``operator`` when somebody restored it from the users table.

    Does not commit: a sign-in cancelling a deletion is part of opening that
    session, and the two land together or not at all.
    """
    user = await session.get(User, user_id)
    if user is None or user.status != UserStatus.deleted:
        return False
    user.status = UserStatus.active
    user.status_changed_at = datetime.now(timezone.utc)
    user.updated_at = datetime.now(timezone.utc)
    session.add(user)
    await audit_service.record(
        session,
        event_type=AuditEventType.USER_DELETION_CANCELLED,
        actor_user_id=actor_user_id,
        target_user_id=user_id,
        target_type="user",
        target_id=user_id,
        detail={"via": via},
    )
    await session.flush()
    return True


async def _scrub_invites_addressed_to(
    session: AsyncSession, *, email_hashes: set[str]
) -> None:
    """Erase a user's addresses from any guild invite addressed to them.

    Every address the account held, not only the one on ``users``: an invite
    bound to a secondary address keeps the same recoverable trace.

    ``GuildInvite.invitee_email_encrypted`` holds the invited person's address
    as *reversible* Fernet ciphertext, so a lingering (unexpired or already
    consumed) invite is a recoverable PII trace that survives user erasure —
    the one gap that otherwise makes anonymize/hard-delete not airtight.

    Fernet output is non-deterministic (the same address encrypts differently
    every time), so there is no indexed equality lookup: we load every bound
    invite and compare the decrypted address the same way redemption does
    (via ``hash_email``, matching how an address is hashed everywhere else).

    A match is NULLed (removing the PII) *and* neutralised (``max_uses = 0``, so
    ``invite_is_active`` returns False). Nulling alone is not enough: an invite
    with no bound address is treated as an open shareable link, so a
    still-active single-recipient invite would degrade into one anyone with the
    code could redeem. The system engine (``app_admin``) holds UPDATE but
    deliberately not DELETE on ``guild_invites`` (row removal rides the guild
    FK cascade — see ``SHARED_TABLE_REGISTRY``), so this scrubs the row in
    place rather than deleting it.
    """
    from app.models.platform.guild import GuildInvite

    bound_invites = (
        await session.exec(
            select(GuildInvite).where(GuildInvite.invitee_email_encrypted.is_not(None))
        )
    ).all()
    for invite in bound_invites:
        bound_email = invite.invitee_email  # decrypts invitee_email_encrypted
        if bound_email and hash_email(bound_email) in email_hashes:
            invite.invitee_email_encrypted = None
            invite.max_uses = 0
            session.add(invite)


async def _erase_personal_rows(session: AsyncSession, *, user_id: int) -> None:
    """Delete the shared-table rows that are about this person and nobody else.

    A hard delete gets all of these from the ``users`` foreign key. Anonymizing
    keeps the row, so the cascade never fires and each one is deleted here.
    Rows that pair this account with somebody else go from both sides: a husk
    on another person's contacts, ignore list or conversation is a trace of
    the account just the same.
    """
    from app.models.platform.announcement import AnnouncementReadReceipt
    from app.models.platform.contact_grant import ContactGrant
    from app.models.platform.dm_conversation import DmConversationMember
    from app.models.platform.dm_device import DmDevice
    from app.models.platform.email_outbox import EmailOutboxItem
    from app.models.platform.profile_favorite import ProfileFavorite
    from app.models.platform.user_cookie_consent import UserCookieConsent
    from app.models.platform.user_decoration import UserDecoration
    from app.models.platform.user_dm_guild_optout import UserDmGuildOptout
    from app.models.platform.user_dm_settings import UserDmSettings
    from app.models.platform.user_ignore import UserIgnore
    from app.models.platform.user_passkey import UserPasskey

    # The date of birth kept for age limits, which is about nobody else.
    await session.exec(delete(UserBirthdate).where(UserBirthdate.user_id == user_id))
    # What the profile was dressed in: every decoration an installed pack
    # granted. What it was wearing is on the ``users`` row, cleared by the caller.
    await session.exec(delete(UserDecoration).where(UserDecoration.user_id == user_id))
    # Passkeys name the device they live on, and a husk signs in with nothing.
    await session.exec(delete(UserPasskey).where(UserPasskey.user_id == user_id))
    # Notifications quote the content they point at; the email queued behind
    # them quotes it again, and would otherwise still be sent.
    await session.exec(
        delete(EmailOutboxItem).where(EmailOutboxItem.user_id == user_id)
    )
    await session.exec(delete(Notification).where(Notification.user_id == user_id))
    await session.exec(
        delete(AnnouncementReadReceipt).where(
            AnnouncementReadReceipt.user_id == user_id
        )
    )
    await session.exec(
        delete(UserCookieConsent).where(UserCookieConsent.user_id == user_id)
    )
    # Direct messages: the devices (their keys and queued ciphertext go with
    # them by cascade), the account's place on each conversation, and its
    # settings.
    await session.exec(delete(DmDevice).where(DmDevice.user_id == user_id))
    await session.exec(
        delete(DmConversationMember).where(DmConversationMember.user_id == user_id)
    )
    await session.exec(delete(UserDmSettings).where(UserDmSettings.user_id == user_id))
    await session.exec(
        delete(UserDmGuildOptout).where(UserDmGuildOptout.user_id == user_id)
    )
    # The social graph, both directions.
    await session.exec(
        delete(ProfileFavorite).where(
            or_(
                ProfileFavorite.user_id == user_id,
                ProfileFavorite.favorite_user_id == user_id,
            )
        )
    )
    await session.exec(
        delete(UserIgnore).where(
            or_(UserIgnore.user_id == user_id, UserIgnore.ignored_user_id == user_id)
        )
    )
    await session.exec(
        delete(ContactGrant).where(
            or_(
                ContactGrant.user_id_low == user_id,
                ContactGrant.user_id_high == user_id,
            )
        )
    )


async def soft_delete_user(
    session: AsyncSession, user_id: int, *, actor_user_id: int | None = None
) -> None:
    """Soft-delete (anonymize) a user account.

    Runs the per-guild erasure ``hard_delete_user`` runs (:func:`_erase_in_guild`,
    in EVERY guild schema: content survives leaving a guild) and drops the
    memberships, then strips every PII field on the row, replaces every address
    the account held with a sentinel, blanks the password hash, and removes auth
    artifacts (API keys, push tokens, user_tokens, sign-in sessions). The row
    stays so authorship (comment authors, ``created_by``, …) continues to
    resolve and the UI can render the placeholder "Deleted user #{id}" wherever
    the original user was referenced.

    Every guild's half is done and committed first, guild by guild, and the
    shared rows are erased in one transaction after. A guild that fails stops
    the erasure before anything shared changes, and the next attempt runs the
    guilds again and finishes it.

    ``actor_user_id`` is who asked for it — the account holder, or somebody
    acting on the account.

    This is irreversible — there is no undo.
    """
    import secrets
    from app.models.platform.push_token import PushToken

    user = await _drop_user_memberships(
        session, user_id, actor_user_id=actor_user_id, erase=True
    )

    # Captured before ``replace_all`` below overwrites them — it is how a guild
    # invite bound to one of this person's addresses is found.
    original_email_hashes = await addresses.held_hashes(session, user_id=user_id)
    # The addresses the receipt goes to, read before the erasure takes them.
    # Proved ones only: an address nobody confirmed is not somewhere this
    # account's own news should be sent.
    receipt_recipients = await addresses.proven_addresses(session, user_id=user_id)
    receipt_locale = getattr(user, "locale", None) or "en"

    user.status = UserStatus.anonymized
    user.token_version += 1
    # The handle stays — it is a pseudonym and a unique identifier, and what
    # keeps an old thread legible after the person behind it is gone. One that
    # was *assigned* rather than picked was seeded from a first name, so it is
    # replaced with a generated one; a handle its owner chose is theirs to be
    # left holding.
    if not user.username_chosen:
        user.username = usernames.random_name()
        user.discriminator = usernames.random_discriminator()
    # Drop any platform role back to member. The row is now an empty husk
    # that can't act on anything; leaving a staff role on it would be
    # misleading in audit views and would inflate any role-only count
    # that doesn't also filter by status.
    user.role = UserRole.member

    # Every address the account held is replaced with one sentinel. It reads as
    # obvious nonsense if it is ever decrypted, and its domain is RFC 2606
    # example.com so EmailStr serialization on user-facing endpoints (the operator
    # user list, and so on) does not reject the row.
    sentinel_email = (
        f"anonymized-{user_id}-{secrets.token_hex(8)}@anonymized.example.com"
    )
    await addresses.replace_all(
        session,
        user_id=user_id,
        email=sentinel_email,
        source=addresses.SOURCE_SYNTHETIC,
    )

    # No password: a NULL hash never verifies, so the husk cannot authenticate.
    user.hashed_password = None

    # Strip the rest of the PII surface. The IdP subject and refresh token
    # live on the identity links — remove the links themselves.
    await identity_service.delete_user_identities(session, user_id=user_id)
    user.avatar_url = None
    # The picture is a row of its own now, so nulling the column is not enough
    # — the husk must not keep a face.
    await user_avatars_service.delete_avatar(session, user_id=user_id)
    # Nor a look: the banner, frame and trophies it wore, and the status it set.
    user.profile_decorations = {}
    user.custom_status = {}
    await _erase_personal_rows(session, user_id=user_id)

    # Drop the notification settings document so the account leaves no
    # behavioural profile behind. Absent reads as every default, which is where
    # a fresh account starts.
    await session.exec(
        delete(UserNotificationPrefs).where(UserNotificationPrefs.user_id == user_id)
    )

    user.updated_at = datetime.now(timezone.utc)
    session.add(user)

    # Revoke auth artifacts. Whatever short-lived tokens existed are now
    # meaningless because token_version was bumped, but we still drop the
    # rows so they don't sit in the DB attributed to a "Deleted user".
    await session.exec(delete(UserApiKey).where(UserApiKey.user_id == user_id))
    await session.exec(delete(UserToken).where(UserToken.user_id == user_id))
    await session.exec(
        delete(AccountChangeHold).where(AccountChangeHold.user_id == user_id)
    )
    await session.exec(delete(PushToken).where(PushToken.user_id == user_id))
    # The session rows too: a husk keeps no record of the devices, addresses
    # and user agents its account signed in from. A hard delete gets this from
    # the ``users`` foreign key; the row survives here, so it is explicit.
    await session_service.delete_all_for_user(session, user_id=user_id)
    # And the second factor, its seed and the codes that stand in for it. The
    # seed goes with the factor by cascade; the rest are the account's, so a
    # husk that keeps its ``users`` row would otherwise keep them.
    await totp_service.disable(session, user_id=user_id)
    await challenge_service.revoke_for_user(session, user_id=user_id)

    # Scrub the user's address out of any guild invite bound to it. Without
    # this, an unexpired/lingering invite keeps a recoverable copy of the very
    # email this erasure was meant to remove. Runs in the same public,
    # ``app_admin`` context as the auth-artifact deletes above.
    if original_email_hashes:
        await _scrub_invites_addressed_to(session, email_hashes=original_email_hashes)

    await audit_service.record(
        session,
        event_type=AuditEventType.USER_ANONYMIZED,
        actor_user_id=actor_user_id,
        target_user_id=user_id,
        target_type="user",
        target_id=user_id,
        detail={"self": actor_user_id == user_id},
    )

    # Single commit: membership removal + PII wipe + auth-artifact
    # revocation either all succeed or all roll back together.
    await session.commit()
    # The receipt, once the erasure is a fact. Never allowed to fail it: the
    # account is gone whether or not the letter goes.
    await email_service.announce_account_erased(
        session, recipients=receipt_recipients, locale=receipt_locale
    )
    # Last, because the revocations sent from each guild above name this
    # person to each plug-in by the very references this removes.
    await identity_refs.forget_user(user_id=user_id)


async def is_last_capability_holder(
    session: AsyncSession,
    user_id: int,
    capability: Capability,
    *,
    for_update: bool = False,
) -> bool:
    """True iff removing this user would leave zero active holders of ``capability``.

    A target whose role doesn't grant the capability, or whose ``status`` isn't
    ``active``, doesn't contribute to the count, so removing them can't drop it
    to zero — return False in those cases. Otherwise count OTHER active holders
    and return True iff none exist.
    """
    roles = list(roles_with_capability(capability))
    if for_update:
        stmt = select(User).where(User.id == user_id).with_for_update()
    else:
        stmt = select(User).where(User.id == user_id)
    result = await session.exec(stmt)
    user = result.one_or_none()
    if not user or user.role not in roles or user.status != UserStatus.active:
        return False

    # PostgreSQL rejects ``SELECT COUNT(...) FOR UPDATE`` (aggregates
    # can't take row locks), so the for_update path locks the candidate
    # rows themselves and counts them in Python.
    if for_update:
        others_stmt = (
            select(User)
            .where(
                User.role.in_(roles),
                User.status == UserStatus.active,
                User.id != user_id,
            )
            .with_for_update()
        )
        others = (await session.exec(others_stmt)).all()
        return len(others) == 0
    others_stmt = select(func.count(User.id)).where(
        User.role.in_(roles),
        User.status == UserStatus.active,
        User.id != user_id,
    )
    return (await session.exec(others_stmt)).one() == 0


async def ensure_config_manager_remains(
    session: AsyncSession, user_id: int, *, for_update: bool = False
) -> None:
    """Refuse a change that takes ``config.manage`` from its last active
    holder, so the platform keeps somebody who can configure it."""
    if await is_last_capability_holder(
        session, user_id, Capability.CONFIG_MANAGE, for_update=for_update
    ):
        raise CodedError(UserMessages.CANNOT_REMOVE_LAST_OWNER)


async def hard_delete_user(
    session: AsyncSession,
    user_id: int,
    *,
    actor_user_id: int | None = None,
) -> None:
    """
    Permanently delete a user account.

    Ownership and authorship part ways here. Each guild's erasure
    (:func:`_erase_in_guild`, the one ``soft_delete_user`` runs) releases the
    owner grants, leaving that content unowned for a guild admin to claim, and
    leaves authorship exactly where it is. A guild that could once see who did
    what still can.

    Args:
        session: Database session
        user_id: ID of user to delete
        actor_user_id: Who asked for it, for the record
    """
    from app.models.platform.push_token import PushToken
    from app.models.platform.guild import Guild, GuildInvite

    # Phase 1 — each guild's half, the same erasure ``soft_delete_user`` runs,
    # in EVERY guild schema, committed guild by guild; then the membership rows
    # go, each one recorded. A guild that fails stops the delete before the
    # shared half, and running it again finishes it.
    user = await _drop_user_memberships(
        session, user_id, actor_user_id=actor_user_id, erase=True
    )

    # Phase 2 — shared/public cleanup.
    await session.exec(delete(Notification).where(Notification.user_id == user_id))
    await session.exec(delete(UserApiKey).where(UserApiKey.user_id == user_id))
    await session.exec(delete(UserToken).where(UserToken.user_id == user_id))
    await session.exec(delete(PushToken).where(PushToken.user_id == user_id))

    # Clear nullable creator references on shared guild rows.
    await session.exec(
        update(Guild).where(Guild.created_by == user_id).values(created_by=None)
    )
    await session.exec(
        update(GuildInvite)
        .where(GuildInvite.created_by == user_id)
        .values(created_by=None)
    )

    # Scrub the user's address out of any guild invite bound to it before the
    # row goes — a bound invite otherwise keeps a recoverable copy of the email
    # (the ``created_by`` NULLing above only covers invites this user
    # *sent*, not ones addressed *to* them).
    held = await addresses.held_hashes(session, user_id=user.id)
    if held:
        await _scrub_invites_addressed_to(session, email_hashes=held)

    await session.delete(user)

    # Recorded in phase 2, on the reset context: the record outlives the row it
    # names, so it is written where every other shared-table write of this
    # delete is written.
    await audit_service.record(
        session,
        event_type=AuditEventType.USER_DELETED,
        actor_user_id=actor_user_id,
        target_user_id=user_id,
        target_type="user",
        target_id=user_id,
        detail={"self": actor_user_id == user_id},
    )

    await session.commit()
    # After the commit: the row is gone, so what outside parties were given to
    # name this person by should stop resolving to anybody.
    await identity_refs.forget_user(user_id=user_id)


# The member-lookup helpers below bind to ``MemberProfile`` — the guild
# projection — by default, because every surface that looks a member up is
# inside a guild, and a guild-routed session does not read ``public.users``.
# The operator roster passes ``User``, which carries the same columns.


#: How close a typed name has to be to a member's to be worth offering.
#: Separate from the content-search threshold on purpose: a name is a short
#: string and a title is a sentence, so the two are tuned against different
#: things even where the number happens to agree.
MEMBER_MATCH_THRESHOLD = 0.4


async def summaries_with_guild_role(
    session: AsyncSession,
    guild_id: int,
    users,
) -> List["UserSummary"]:
    """``UserSummary`` per user, with the guild role actually filled in.

    ``UserSummary`` defaults ``guild_role`` to ``None``, and
    ``model_validate`` over a profile row carries nothing that could correct
    it -- the rung lives on ``GuildMembership``, not on the profile. So a
    guild admin came back from the roster endpoints looking like an ordinary
    member, and a key-set assertion could not see it: the field was present,
    and wrong.

    One query for the whole batch, so this does not reintroduce an N+1 on a
    typeahead.
    """
    from app.schemas.platform.user import UserSummary
    from app.services import membership as membership_service

    users = list(users)
    roles = await membership_service.guild_role_map(
        session, guild_id, [user.id for user in users]
    )
    summaries: List[UserSummary] = []
    for user in users:
        summary = UserSummary.model_validate(user)
        role = roles.get(user.id)
        if role is not None:
            summary.community_role = role.value
        summaries.append(summary)
    return summaries


def name_closeness(
    term: str, *, match_names: bool = True, profile=MemberProfile
) -> ColumnElement[float]:
    """How close a member's name is to what was typed, as a rankable number.

    Measured against the closest RUN of the name rather than the whole of it,
    so a surname matches a member listed by both names. Answers the misspelling
    that substring matching cannot — and its real work is the ORDER, putting the
    nearest name at the top of a page rather than whoever sorts first.

    ``match_names`` reads the profile's ``display_name`` too: on the guild
    projection, the name the member set there, so a name is matched exactly
    where it is shown and nowhere else.
    """
    closest = func.word_similarity(term, profile.username)
    if match_names:
        closest = func.greatest(
            closest,
            func.word_similarity(term, func.coalesce(profile.display_name, "")),
        )
    return closest


def member_match(
    term: str, *, match_names: bool = True, profile=MemberProfile
) -> tuple[ColumnElement[bool], ColumnElement[float] | None]:
    """How a typed name selects members, and what to order the answer by.

    One implementation for every surface that looks people up — the guild
    roster, an initiative's, a project's, the picker behind an @mention. The
    handle always; the name alongside it where the guild shows one; a
    whole ``foobar#1234`` pinning the one person who owns it; and a name typed
    nearly right still finding them.

    Returns the predicate, and the closeness to order by — ``None`` when a
    whole handle was typed, which names one person and has nothing to rank.
    """
    name_part, number = usernames.parse_handle(term)
    if number is not None:
        return (
            and_(
                func.lower(profile.username) == name_part.lower(),
                func.lpad(cast(profile.discriminator, String), 4, "0").like(
                    f"{number}%"
                ),
            ),
            None,
        )
    matches = profile.username.ilike(f"%{name_part}%")
    if match_names:
        matches = or_(matches, profile.display_name.ilike(f"%{name_part}%"))
    closest = name_closeness(name_part, match_names=match_names, profile=profile)
    return or_(matches, closest >= MEMBER_MATCH_THRESHOLD), closest


def member_order(
    closest: ColumnElement[float] | None, *, match_names: bool = True
) -> tuple[ColumnElement, ...]:
    """Nearest first while searching, alphabetical by the name shown while
    reading a roster."""
    if closest is not None:
        return (closest.desc(),)
    if not match_names:
        return ()
    return (func.coalesce(MemberProfile.display_name, MemberProfile.username).asc(),)


def visible_to_other_people(status_column=None):
    """Rows that may appear where a person is listed as someone to work with.

    A suspended account is not one: it vanishes from rosters, pickers, search,
    mention candidates and presence for as long as the suspension lasts. Nor is
    an account whose holder has asked for it to go — for the window before the
    erasure, it is as absent as if the erasure had already happened.

    Neither vanishes from work it already touched: a comment either wrote still
    says who wrote it. Both states are reversible, and neither removes the
    account from anything.

    Stated against :data:`~app.models.platform.user.ABSENT_STATUSES` rather
    than by naming one status, so a state added later is a decision about which
    side of this line it falls on.

    A clause rather than a filtered query, so each surface keeps its own
    joins and its own gates and only borrows the predicate. It reads the guild
    projection by default, which is what every surface that lists people reads;
    pass ``status_column`` to apply it to ``public.users`` or to the
    ``user_profiles`` view, which carry the same column and the same rule.
    """
    column = MemberProfile.status if status_column is None else status_column
    return column.notin_(sorted(ABSENT_STATUSES, key=lambda s: s.value))


def guild_members(statement: _S, *, guild_id: int) -> _S:
    """``statement`` narrowed to the people listed as members of one community.

    ``MemberProfile`` joined to each person's membership row there, so a caller
    may select its columns beside the profile, and the people
    :func:`visible_to_other_people` leaves out left out here too. A statement
    that selects no profile column names ``MemberProfile`` in ``select_from``.
    """
    return statement.join(
        GuildMembership, GuildMembership.user_id == MemberProfile.id
    ).where(GuildMembership.guild_id == guild_id, visible_to_other_people())


async def _reach(user_ids: List[int]) -> tuple[dict[int, str], set[int]]:
    """Each account's address and whether it has proved one.

    On its own system-engine session: ``user_emails`` carries no request-path
    grants, so the role a request runs as cannot read it. Two queries for the
    whole page rather than two per row.

    Private, and deliberately so. It returns addresses in the clear for
    whatever ids it is handed, and decides nothing about who may see them —
    that belongs to the two shapes below, which is the only thing that calls
    it: ``to_self_read`` for the address's own holder, ``to_operator_read`` for
    everybody else, masked.
    """
    from app.db.session import SystemSessionLocal

    async with SystemSessionLocal() as system_session:
        return (
            await addresses.primary_addresses(system_session, user_ids=user_ids),
            await addresses.accounts_with_a_proven_address(
                system_session, user_ids=user_ids
            ),
        )


async def _credential_state(
    user_ids: List[int],
) -> tuple[dict[int, "SignInLock"], set[int], dict[int, int]]:
    """The sign-in locks standing on these accounts, which of them hold a
    second factor, and how many working API keys each holds, on the system
    engine.

    ``sign_in_locks``, ``user_totp`` and ``user_api_keys`` carry no
    request-path grants, for the reason ``user_emails`` does not. One query
    each for the whole page.
    """
    from app.db.session import SystemSessionLocal
    from app.services.auth import sign_in_locks

    async with SystemSessionLocal() as system_session:
        return (
            await sign_in_locks.closed(system_session, user_ids),
            await totp_service.enrolled_among(system_session, user_ids=user_ids),
            await api_keys_service.live_counts(system_session, user_ids=user_ids),
        )


async def to_self_read(session: AsyncSession, user: User) -> "UserRead":
    """An account's own record, with the address it is reached at, in full.

    For handing somebody their *own* account and nothing else — the address is
    unmasked. Reading somebody else's account gets ``to_operator_read``.

    The address and whether one has been proved both live in ``user_emails``,
    so the ``users`` row cannot answer either on its own. This is where the two
    are put back together, with how the account confirms a change (a linked
    identity, a usable password, whether a confirmation asks for it), for
    every endpoint that hands somebody their own account. ``session`` is the
    request's: the identity link is the caller's own row, and the deployment's
    sign-in methods are read from its settings.
    """
    from app.schemas.platform.user import UserRead
    from app.services.platform import app_settings as app_settings_service
    from app.services.platform import auth_posture

    primary, proven = await _reach([user.id])
    payload = UserRead.model_validate(user)
    payload.email = primary.get(user.id)
    payload.email_verified = user.id in proven
    payload.birthdate_on_file = await _birthdate_on_file(user.id)
    payload.birthdate_required = (
        not payload.birthdate_on_file
        and user.age_below_minimum_at is None
        and await app_settings_service.community_age_gate_enabled(session)
    )
    payload.has_federated_identity = await identity_service.has_federated_identity(
        session, user_id=user.id
    )
    payload.has_password = has_usable_password(user.hashed_password)
    payload.password_required = await auth_posture.password_confirms(session, user)
    if settings.DEMO_MODE:
        from app.demo.copies import account_copy

        copy = await account_copy(user.id)
        if copy is not None:
            payload.demo_community_id = copy.guild_id
            payload.demo_expires_at = copy.expires_at
    return payload


async def _birthdates_on_file(user_ids: List[int]) -> set[int]:
    """Which of these accounts have a date of birth kept. One query for the
    page, on the system engine, and never the dates."""
    from app.db.session import SystemSessionLocal

    if not user_ids:
        return set()
    async with SystemSessionLocal() as system_session:
        rows = await system_session.exec(
            select(UserBirthdate.user_id).where(UserBirthdate.user_id.in_(user_ids))
        )
        return set(rows.all())


async def _birthdate_on_file(user_id: int) -> bool:
    """Whether this account's date of birth is kept — never the date itself.

    On its own system-engine session, like :func:`_reach`: ``user_birthdates``
    carries no request-path grants.
    """
    from app.db.session import SystemSessionLocal

    async with SystemSessionLocal() as system_session:
        return await birthdate_of(system_session, user_id=user_id) is not None


async def to_operator_read(users: List[User]) -> List["OperatorUserRead"]:
    """The same, for staff reading other people's accounts.

    The shape masks the address itself.
    """
    from app.schemas.platform.user import OperatorUserRead

    primary, proven = await _reach([u.id for u in users])
    locks, enrolled, key_counts = await _credential_state([u.id for u in users])
    # Only asked when somebody on this page is actually waiting out a window,
    # which on an ordinary roster is nobody.
    deployment = (
        await _app_settings()
        if any(u.status == UserStatus.deleted for u in users)
        else None
    )
    dated = await _birthdates_on_file([u.id for u in users])
    out: List[OperatorUserRead] = []
    for user in users:
        payload = OperatorUserRead.model_validate(user)
        payload.email = primary.get(user.id) or ""
        payload.email_verified = user.id in proven
        payload.birthdate_on_file = user.id in dated
        if deployment is not None:
            payload.purge_at = ACCOUNT_DELETION.ends_at(user, deployment)
        payload.second_factor_enrolled = user.id in enrolled
        payload.api_key_count = key_counts.get(user.id, 0)
        lock = locks.get(user.id)
        if lock is not None:
            payload.sign_in_locked_until = lock.locked_until
        out.append(payload)
    return out


async def _app_settings() -> AppSetting:
    """The deployment's settings, on its own session.

    Same reason as :func:`_reach`: this shape is built outside any particular
    request's session, and the setting is one row read once for the whole page.
    """
    from app.db.session import SystemSessionLocal
    from app.services.platform import app_settings as app_settings_service

    async with SystemSessionLocal() as system_session:
        return await app_settings_service.get_app_settings(system_session)


async def to_operator_read_one(user: User) -> "OperatorUserRead":
    """``to_operator_read`` for the routes that return one account."""
    return (await to_operator_read([user]))[0]


#: The age below which somebody may not take part in the parts of the platform
#: that are open to people they have not met.
MINIMUM_AGE_YEARS = 16

#: The age below which somebody may not have an account here at all, by ISO
#: 3166-1 country: the age of digital consent where they are. ``default`` is
#: every country not listed. Where the country is not known, the highest age
#: listed applies, so not knowing where somebody is never lets them in
#: younger. Asked only while the deployment checks age.
ACCOUNT_MINIMUM_AGE: dict[str, int] = {
    "default": 13,
    # The GDPR's age of consent, as each EU and EEA state set it.
    "AT": 14,
    "BE": 13,
    "BG": 14,
    "CY": 14,
    "CZ": 15,
    "DE": 16,
    "DK": 13,
    "EE": 13,
    "ES": 14,
    "FI": 13,
    "FR": 15,
    "GR": 15,
    "HR": 16,
    "HU": 16,
    "IE": 16,
    "IS": 13,
    "IT": 14,
    "LI": 16,
    "LT": 14,
    "LU": 16,
    "LV": 13,
    "MT": 13,
    "NL": 16,
    "NO": 13,
    "PL": 16,
    "PT": 13,
    "RO": 16,
    "SE": 13,
    "SI": 15,
    "SK": 16,
    # The UK GDPR.
    "GB": 13,
    # COPPA.
    "US": 13,
    # PIPL and PIPA.
    "CN": 14,
    "KR": 14,
}

#: A bound on what counts as a date somebody could have been born on. Not a
#: judgement about anyone — it is what separates a real answer from a typo.
MAX_PLAUSIBLE_AGE_YEARS = 120


def _years_since(birthdate: date, today: date) -> int:
    """Whole years between two dates — an age, counted the way people count it.

    A birthday that has not come round yet this year does not count, which is
    the whole of the arithmetic.
    """
    had_birthday = (today.month, today.day) >= (birthdate.month, birthdate.day)
    return today.year - birthdate.year - (0 if had_birthday else 1)


def below_account_minimum(birthdate: date, country: str | None) -> bool:
    """Whether somebody born on ``birthdate`` is too young for an account in
    ``country`` (None when it is not known)."""
    from app.services.tenant.plugin_age import minimum_in

    minimum = minimum_in(ACCOUNT_MINIMUM_AGE, country) or 0
    return _years_since(birthdate, datetime.now(timezone.utc).date()) < minimum


class InvalidBirthdateError(ValueError):
    """A date nobody could have been born on."""


def check_birthdate(birthdate: date) -> None:
    """Raise :class:`InvalidBirthdateError` for a date nobody was born on."""
    today = datetime.now(timezone.utc).date()
    if birthdate > today or birthdate < today.replace(
        year=today.year - MAX_PLAUSIBLE_AGE_YEARS
    ):
        raise InvalidBirthdateError(birthdate)


def record_age_answer(user: User, birthdate: date) -> bool:
    """Write onto the account what a birthdate says about it, and whether it
    is old enough.

    Records when the question was first answered, or that it was answered
    under age. The date itself is kept beside it by :func:`keep_birthdate`, on
    the system engine.
    """
    check_birthdate(birthdate)
    if _years_since(birthdate, datetime.now(timezone.utc).date()) < MINIMUM_AGE_YEARS:
        user.age_below_minimum_at = datetime.now(timezone.utc)
        # One question, one answer (``ck_users_age_answer``): an under-age
        # answer replaces any confirmation.
        user.age_confirmed_at = None
        return False
    if user.age_confirmed_at is None:
        user.age_confirmed_at = datetime.now(timezone.utc)
    return True


async def keep_birthdate(
    session: AsyncSession, *, user_id: int, birthdate: date
) -> str | None:
    """Keep this account's date of birth, encrypted. The stored ciphertext when
    it was kept — unique to this keeping, so :func:`forget_birthdate` can take
    back exactly this one — or ``None`` when one is already on file, which is
    left as it is.

    A plug-in's minimum age differs by country, so one "old enough" answer
    cannot say whether somebody may use a given plug-in; the date can. One
    insert, so of two answers arriving together exactly one is kept. On the
    system engine — ``user_birthdates`` has no request-path grants — and the
    caller commits. Checked first with :func:`check_birthdate`, like the answer
    it accompanies.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    check_birthdate(birthdate)
    now = datetime.now(timezone.utc)
    ciphertext = encrypt_field(birthdate.isoformat(), SALT_BIRTHDATE)
    kept = await session.exec(
        pg_insert(UserBirthdate)
        .values(
            user_id=user_id,
            birthdate_encrypted=ciphertext,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_nothing(index_elements=["user_id"])
        .returning(UserBirthdate.user_id)
    )
    return ciphertext if kept.first() is not None else None


async def birthdate_of(session: AsyncSession, *, user_id: int) -> date | None:
    """The kept date of birth, or None. System engine only; it decides nothing
    about who may know it, so it is read to check an age and never handed out."""
    stored = (
        await session.exec(
            select(UserBirthdate).where(UserBirthdate.user_id == user_id)
        )
    ).first()
    if stored is None:
        return None
    return date.fromisoformat(decrypt_field(stored.birthdate_encrypted, SALT_BIRTHDATE))


async def forget_birthdate(
    session: AsyncSession, *, user_id: int, only: str | None = None
) -> None:
    """Drop the kept date of birth, so the account answers again. With ``only``
    (what :func:`keep_birthdate` returned), drop it only if it is still that
    one. System engine; the caller commits."""
    statement = delete(UserBirthdate).where(UserBirthdate.user_id == user_id)
    if only is not None:
        statement = statement.where(UserBirthdate.birthdate_encrypted == only)
    await session.exec(statement)


def years_old(birthdate: date) -> int:
    """Whole years since ``birthdate`` as of today (UTC)."""
    return _years_since(birthdate, datetime.now(timezone.utc).date())
