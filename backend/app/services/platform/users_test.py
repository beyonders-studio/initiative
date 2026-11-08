"""
Unit tests for user service functions.

Tests the business logic in app.services.users including:
- System user management
- Deletion eligibility checks
- Project ownership transfers
- User content reassignment
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import undefer
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.capabilities import Capability
from app.core.errors import CodedError
from app.core.messages import UserMessages
from app.models.platform.guild import CommunityRole
from app.services.auth import addresses
from app.models.platform.user import User, UserStatus
from app.services.platform import users as user_service
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_user,
)
from app.db.request_context import SystemGuild, Unattributed


async def test_the_sole_seat_is_reported(session: AsyncSession):
    """A community whose only superadmin is this account."""
    seat = await create_user(session)
    guild = await create_guild(session, creator=seat)
    await create_guild_membership(
        session, user=seat, guild=guild, role=CommunityRole.superadmin
    )
    # Somebody to strand: a community of one is the exception, tested below.
    await create_guild_membership(
        session, user=await create_user(session), guild=guild, role=CommunityRole.member
    )

    assert await user_service.is_last_guild_superadmin(session, seat.id) == [guild.name]


async def test_another_seat_holder_clears_it(session: AsyncSession):
    """Two superadmins, so neither is the last one."""
    first = await create_user(session, email="first@example.com")
    second = await create_user(session, email="second@example.com")
    guild = await create_guild(session, creator=first)
    for user in (first, second):
        await create_guild_membership(
            session, user=user, guild=guild, role=CommunityRole.superadmin
        )

    assert await user_service.is_last_guild_superadmin(session, first.id) == []


async def test_an_ordinary_admin_is_not_a_seat(session: AsyncSession):
    """An admin does not count, which is the whole point of the split: their
    leaving never strands a community, because its seat is still there."""
    seat = await create_user(session, email="seat@example.com")
    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, creator=seat)
    await create_guild_membership(
        session, user=seat, guild=guild, role=CommunityRole.superadmin
    )
    await create_guild_membership(
        session, user=admin, guild=guild, role=CommunityRole.admin
    )

    assert await user_service.is_last_guild_superadmin(session, admin.id) == []


async def test_seats_are_reported_per_community(session: AsyncSession):
    """One community where they are the only seat, one where they are not."""
    seat = await create_user(session)
    alone = await create_guild(session, name="Alone", creator=seat)
    await create_guild_membership(
        session, user=seat, guild=alone, role=CommunityRole.superadmin
    )
    await create_guild_membership(
        session, user=await create_user(session), guild=alone, role=CommunityRole.member
    )
    other = await create_user(session, email="other@example.com")
    shared = await create_guild(session, name="Shared", creator=other)
    for user in (seat, other):
        await create_guild_membership(
            session, user=user, guild=shared, role=CommunityRole.superadmin
        )

    assert await user_service.is_last_guild_superadmin(session, seat.id) == ["Alone"]


async def test_removing_the_only_seat_is_refused_where_the_rows_go(
    session: AsyncSession,
):
    """The refusal lives in the drop, not only in the check an endpoint runs
    first: that check is a report, and two accounts can each pass it by seeing
    the other still there."""
    seat = await create_user(session)
    guild = await create_guild(session, name="Stranded", creator=seat)
    await create_guild_membership(
        session, user=seat, guild=guild, role=CommunityRole.superadmin
    )
    await create_guild_membership(
        session, user=await create_user(session), guild=guild, role=CommunityRole.member
    )

    with pytest.raises(user_service.SeatWouldBeEmptied) as refusal:
        await user_service.deactivate_user(session, seat.id)
    assert refusal.value.guild_names == ["Stranded"]

    # The account is untouched by the refusal.
    await session.refresh(seat)
    assert seat.status == UserStatus.active


async def test_the_only_member_of_a_community_may_go(session: AsyncSession):
    """Nobody to strand, and no remedy to offer: appointing another superadmin
    takes somebody to appoint. The community is left with no members."""
    alone = await create_user(session)
    guild = await create_guild(session, name="Just Me", creator=alone)
    await create_guild_membership(
        session, user=alone, guild=guild, role=CommunityRole.superadmin
    )

    assert await user_service.is_last_guild_superadmin(session, alone.id) == []

    alone_id = alone.id
    await user_service.deactivate_user(session, alone_id)
    reloaded = (await session.exec(select(User).where(User.id == alone_id))).one()
    assert reloaded.status == UserStatus.deactivated


async def test_one_other_member_brings_the_block_back(session: AsyncSession):
    """Somebody else is there, so there is somebody to appoint — and somebody
    to strand by not appointing them."""
    seat = await create_user(session, email="seat@example.com")
    member = await create_user(session, email="member@example.com")
    guild = await create_guild(session, name="Not Just Me", creator=seat)
    await create_guild_membership(
        session, user=seat, guild=guild, role=CommunityRole.superadmin
    )
    await create_guild_membership(
        session, user=member, guild=guild, role=CommunityRole.member
    )

    assert await user_service.is_last_guild_superadmin(session, seat.id) == [
        "Not Just Me"
    ]
    with pytest.raises(user_service.SeatWouldBeEmptied):
        await user_service.deactivate_user(session, seat.id)


async def test_a_second_seat_lets_the_account_go(session: AsyncSession):
    """Somebody else holds it, so nothing is stranded."""
    leaving = await create_user(session, email="leaving@example.com")
    staying = await create_user(session, email="staying@example.com")
    guild = await create_guild(session, creator=leaving)
    for user in (leaving, staying):
        await create_guild_membership(
            session, user=user, guild=guild, role=CommunityRole.superadmin
        )

    leaving_id = leaving.id
    await user_service.deactivate_user(session, leaving_id)

    reloaded = (await session.exec(select(User).where(User.id == leaving_id))).one()
    assert reloaded.status == UserStatus.deactivated


async def test_deactivate_user(session: AsyncSession, monkeypatch):
    """Deactivation flips status, drops memberships (telling billing),
    bumps token_version, and leaves PII intact so an operator can later
    reactivate."""
    from app.testing.billing_boundary import change_rows
    from app.testing.billing_managed import billing_manages_plans

    user = await create_user(session, email="todeactivate@example.com")
    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, creator=admin)

    await create_guild_membership(
        session, user=admin, guild=guild, role=CommunityRole.admin
    )
    await create_guild_membership(
        session, user=user, guild=guild, role=CommunityRole.member
    )

    original_token_version = user.token_version
    guild_id, user_id = guild.id, user.id

    async with billing_manages_plans(session):
        await user_service.deactivate_user(session, user_id)
        await session.commit()
        # Billing is told the count changed; it is counted when served.
        assert await change_rows(session, guild_id, kinds=("community.members",)) == [
            ("community.members", {})
        ]

    stmt = select(User).where(User.id == user_id)
    result = await session.exec(stmt)
    deactivated = result.one()

    assert deactivated.status == UserStatus.deactivated
    assert deactivated.token_version == original_token_version + 1
    # PII preserved — an operator can reactivate.
    assert await addresses.holds_address(
        session, user_id=deactivated.id, email="todeactivate@example.com"
    )


async def test_soft_delete_user_anonymizes_pii(session: AsyncSession, role_session):
    """Soft delete (anonymize) clears PII, blocks login, drops memberships,
    demotes platform staff to member, revokes auth artifacts, and keeps
    the row so historical FKs resolve."""
    from app.models.platform.api_key import UserApiKey
    from app.models.platform.federated_identity import FederatedIdentity
    from app.models.platform.federated_identity_secret import FederatedIdentitySecret
    from app.models.platform.push_token import PushToken
    from app.models.platform.user_avatar import UserAvatar
    from app.models.platform.user_token import UserToken
    from app.models.platform.user import UserRole
    from app.testing.factories import create_federated_identity

    user = await create_user(
        session,
        email="toanonymize@example.com",
        avatar_url="https://example.com/avatar.png",
        role=UserRole.operator,
    )
    # SSO link + stored IdP refresh token — both must be severed by anonymize.
    identity = await create_federated_identity(session, user, subject="anon-sub")
    session.add(
        FederatedIdentitySecret(
            identity_id=identity.id, refresh_token_encrypted="ciphertext"
        )
    )
    await session.commit()
    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, creator=admin)

    await create_guild_membership(
        session, user=admin, guild=guild, role=CommunityRole.admin
    )
    await create_guild_membership(
        session, user=user, guild=guild, role=CommunityRole.member
    )

    # Seed auth artifacts that should be revoked.
    session.add(
        UserApiKey(
            user_id=user.id,
            name="key",
            token_prefix="ppk_xxxx",
            token_hash="hash-1",
        )
    )
    session.add(
        UserToken(
            user_id=user.id,
            token="utoken-1",
            purpose="password_reset",
            expires_at=datetime.now(timezone.utc),
        )
    )
    session.add(PushToken(user_id=user.id, push_token="device-token", platform="web"))
    await session.commit()

    original_id = user.id
    original_token_version = user.token_version

    system_session = await role_session("app_admin")
    await user_service.soft_delete_user(system_session, original_id)

    stmt = select(User).where(User.id == original_id)
    result = await session.exec(stmt)
    anonymized = result.one()

    # The row stays — same id, same created_at — so FKs resolve.
    assert anonymized.id == original_id
    assert anonymized.status == UserStatus.anonymized
    # Platform staff role demoted to member so the husk doesn't carry
    # elevated privileges.
    assert anonymized.role == UserRole.member
    # PII gone.
    assert anonymized.avatar_url is None
    # The picture is a row of its own, so the column going null is not enough.
    assert (
        await session.exec(select(UserAvatar).where(UserAvatar.user_id == original_id))
    ).first() is None
    # No password: the husk can never authenticate again.
    assert anonymized.hashed_password is None
    # The SSO link and its stored refresh token are gone.
    remaining_identities = (
        await session.exec(
            select(FederatedIdentity).where(FederatedIdentity.user_id == original_id)
        )
    ).all()
    assert remaining_identities == []
    assert (await session.get(FederatedIdentitySecret, identity.id)) is None
    # Every address the account held was replaced with the sentinel, so the one
    # it signed in with reaches nobody and the password hash is fresh nonsense.
    assert not await addresses.holds_address(
        session, user_id=anonymized.id, email="toanonymize@example.com"
    )
    # Token version bumped (deactivate already bumped, anonymize keeps it).
    assert anonymized.token_version >= original_token_version + 1

    # Auth artifacts revoked.
    api_keys = (
        await session.exec(select(UserApiKey).where(UserApiKey.user_id == original_id))
    ).all()
    user_tokens_left = (
        await session.exec(select(UserToken).where(UserToken.user_id == original_id))
    ).all()
    push_tokens_left = (
        await session.exec(select(PushToken).where(PushToken.user_id == original_id))
    ).all()
    assert api_keys == []
    assert user_tokens_left == []
    assert push_tokens_left == []


async def test_erasing_a_user_stops_their_references_resolving(
    session: AsyncSession,
):
    """The names outside parties know somebody by are part of the erasure.

    Billing holds one and keeps it — it is the key an account's history hangs
    on — and each installed plug-in holds its own. Once the person is gone, none of
    them has anyone left to resolve to, and the mapping is the only thing that
    could still join them back to a row.

    Anonymizing counts: the row survives so old content stays legible, but the
    person does not, and a reference is a name for the person.
    """
    from app.models.platform.identity_ref import IdentityEntity, IdentityPurpose
    from app.services.platform.identity_refs import ensure_ref, resolve_ref

    victim = await create_user(session, email="forgetme@example.com")
    bystander = await create_user(session, email="stays@example.com")

    billing_ref = await ensure_ref(
        session,
        entity_type=IdentityEntity.user,
        entity_id=victim.id,
        purpose=IdentityPurpose.billing,
    )
    plugin_ref = await ensure_ref(
        session,
        entity_type=IdentityEntity.user,
        entity_id=victim.id,
        purpose=IdentityPurpose.plugin,
        sector_guild_id=1,
        sector_plugin="acme.tracker",
    )
    kept = await ensure_ref(
        session,
        entity_type=IdentityEntity.user,
        entity_id=bystander.id,
        purpose=IdentityPurpose.billing,
    )
    await session.commit()

    await user_service.soft_delete_user(session, victim.id)

    assert await resolve_ref(session, ref=billing_ref) is None
    assert await resolve_ref(session, ref=plugin_ref) is None
    # One person's erasure is not everybody's.
    assert await resolve_ref(session, ref=kept) is not None


async def test_soft_delete_user_scrubs_addressed_invites(
    session: AsyncSession, role_session
):
    """Anonymizing a user must erase their address from any guild invite bound
    to it — a lingering invite otherwise keeps a reversible copy of the very
    email the erasure was meant to remove. The matched invite is also
    neutralised so nulling its bound address can't demote a single-recipient
    invite into an open shareable link. Invites for other people, and unbound
    (shareable-link) invites, are left untouched."""
    from app.models.platform.guild import GuildInvite
    from app.services.platform import guilds as guild_service

    victim = await create_user(session, email="scrubme@example.com")
    admin = await create_user(session, email="inviteadmin@example.com")
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(
        session, user=victim, guild=guild, role=CommunityRole.member
    )

    # Active invite addressed to the victim — the recoverable PII trace.
    victim_invite, victim_invite_code = await guild_service.create_guild_invite(
        session,
        guild_id=guild.id,
        created_by=admin.id,
        invitee_email="scrubme@example.com",
        max_uses=1,
        expires_at=None,
    )
    # Invite for someone else — must be untouched.
    other_invite, other_invite_code = await guild_service.create_guild_invite(
        session,
        guild_id=guild.id,
        created_by=admin.id,
        invitee_email="keep@example.com",
        max_uses=1,
        expires_at=None,
    )
    # Unbound shareable link (no address) — must be untouched.
    open_invite, open_invite_code = await guild_service.create_guild_invite(
        session,
        guild_id=guild.id,
        created_by=admin.id,
        invitee_email=None,
        max_uses=5,
        expires_at=None,
    )
    victim_invite_id = victim_invite.id
    other_invite_id = other_invite.id
    open_invite_id = open_invite.id

    # Sanity: the victim's invite is active/bound before erasure.
    assert guild_service.invite_is_active(victim_invite) is True
    await session.commit()

    system_session = await role_session("app_admin")
    await user_service.soft_delete_user(system_session, victim.id)
    session.expunge_all()

    scrubbed = (
        await session.exec(
            select(GuildInvite).where(GuildInvite.id == victim_invite_id)
        )
    ).one()
    # Address erased, and the invite neutralised so it can't act as an open link.
    assert scrubbed.invitee_email_encrypted is None
    assert scrubbed.invitee_email is None
    assert scrubbed.max_uses == 0
    assert guild_service.invite_is_active(scrubbed) is False

    # Someone else's invite is untouched.
    other_after = (
        await session.exec(select(GuildInvite).where(GuildInvite.id == other_invite_id))
    ).one()
    assert other_after.invitee_email == "keep@example.com"
    assert other_after.max_uses == 1

    # Unbound shareable-link invites are untouched.
    open_after = (
        await session.exec(select(GuildInvite).where(GuildInvite.id == open_invite_id))
    ).one()
    assert open_after.invitee_email is None
    assert open_after.max_uses == 5


async def test_hard_delete_user_scrubs_addressed_invites(
    session: AsyncSession, role_session
):
    """Hard delete has the same residual-PII gap: an invite addressed to the
    removed user keeps a reversible copy of their email. The invitee address
    must be scrubbed — distinct from the ``created_by`` NULLing, which
    only covers invites the user *sent* (here the inviter is a different
    admin, so only the invitee-scrub can clear it)."""
    from app.models.platform.guild import GuildInvite
    from app.services.platform import guilds as guild_service

    victim = await create_user(session, email="hardscrub@example.com")
    admin = await create_user(session, email="hardadmin@example.com")
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(
        session, user=victim, guild=guild, role=CommunityRole.member
    )

    invite, invite_code = await guild_service.create_guild_invite(
        session,
        guild_id=guild.id,
        created_by=admin.id,
        invitee_email="hardscrub@example.com",
        max_uses=1,
        expires_at=None,
    )
    invite_id = invite.id
    victim_id = victim.id
    await session.commit()

    system_session = await role_session("app_admin")
    await user_service.hard_delete_user(system_session, victim_id)
    session.expunge_all()

    # User row is gone...
    assert (
        await session.exec(select(User).where(User.id == victim_id))
    ).one_or_none() is None
    # ...and no invite retains their recoverable address.
    scrubbed = (
        await session.exec(select(GuildInvite).where(GuildInvite.id == invite_id))
    ).one()
    assert scrubbed.invitee_email_encrypted is None
    assert scrubbed.invitee_email is None
    # ...and it's neutralised so nulling the bound address can't leave it as an
    # open shareable link.
    assert scrubbed.max_uses == 0
    assert guild_service.invite_is_active(scrubbed) is False


async def test_users_table_has_rls_delete_deny_policy(session: AsyncSession):
    """``users`` carries FORCE RLS, the ``users_no_delete`` restrictive policy,
    and the per-role policy set that leaves every request-path write on the
    caller's own row (migrations 0109, 0144, 0202). User rows are removed on
    the system engine only."""
    from sqlalchemy import text

    rls_enabled = await session.exec(
        text(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = 'users'"
        )
    )
    enabled, forced = rls_enabled.one()
    assert enabled is True
    assert forced is True

    policies = await session.exec(
        text(
            "SELECT polname, polcmd, polpermissive FROM pg_policy "
            "WHERE polrelid = 'users'::regclass ORDER BY polname"
        )
    )
    rows = list(policies)
    names = {row[0] for row in rows}
    assert "users_no_delete" in names
    # Phase 2 decomposed the broad open policy into per-tier policies.
    assert "users_open" not in names
    assert {
        # Read legs: the request path names other people all the time.
        "users_app_user_read",
        "users_platform_read",
        # Write legs: each one scoped to the caller's own row.
        "users_app_user_self_update",
        "users_platform_self",
    } <= names
    # 0221 took the guild path off this table entirely — it reads people from
    # ``public.guild_member_profiles`` now — so its two legs are gone with it.
    assert {
        "users_app_guild_base_read",
        "users_app_guild_base_self_update",
    } & names == set()
    # 0202 retired the table-wide floors and the moderator+ update-all leg.
    assert {
        "users_app_floor",
        "users_guild_floor",
        "users_platform_manage",
    }.isdisjoint(names)
    deny_policy = next(row for row in rows if row[0] == "users_no_delete")
    # polcmd '6' = DELETE; polpermissive False = restrictive.
    # See: https://www.postgresql.org/docs/current/catalog-pg-policy.html
    assert deny_policy[2] is False  # restrictive


async def test_is_last_config_manager_ignores_inactive_targets(session: AsyncSession):
    """An owner whose status isn't ``active`` doesn't contribute to the
    active config-manager count, so they can never be "the last owner".

    ``is_last_capability_holder`` tracks holders of ``config.manage``
    (owners) — the invariant that keeps the platform able to manage its own
    configuration.
    """
    from app.models.platform.user import UserRole

    active_owner = await create_user(
        session, email="active-owner@example.com", role=UserRole.owner
    )
    deact_owner = await create_user(
        session, email="deact-owner@example.com", role=UserRole.owner
    )
    await user_service.deactivate_user(session, deact_owner.id)

    # The active owner really is the last *active* config manager.
    assert (
        await user_service.is_last_capability_holder(
            session, active_owner.id, Capability.CONFIG_MANAGE
        )
        is True
    )
    with pytest.raises(CodedError) as refusal:
        await user_service.ensure_config_manager_remains(session, active_owner.id)
    assert refusal.value.code == UserMessages.CANNOT_REMOVE_LAST_OWNER

    # The deactivated owner is never "the last owner" — they're not in
    # the count to begin with, so removing them changes nothing.
    assert (
        await user_service.is_last_capability_holder(
            session, deact_owner.id, Capability.CONFIG_MANAGE
        )
        is False
    )
    await user_service.ensure_config_manager_remains(session, deact_owner.id)


async def test_is_last_config_manager_with_other_active_owner(session: AsyncSession):
    """When a second active owner exists, neither is the last owner."""
    from app.models.platform.user import UserRole

    a = await create_user(session, email="a@example.com", role=UserRole.owner)
    b = await create_user(session, email="b@example.com", role=UserRole.owner)

    assert (
        await user_service.is_last_capability_holder(
            session, a.id, Capability.CONFIG_MANAGE
        )
        is False
    )
    assert (
        await user_service.is_last_capability_holder(
            session, b.id, Capability.CONFIG_MANAGE
        )
        is False
    )


async def test_is_last_config_manager_excludes_operator(session: AsyncSession):
    """An operator does not hold ``config.manage``, so they are not counted
    as a config manager and are never "the last owner"."""
    from app.models.platform.user import UserRole

    await create_user(session, email="owner@example.com", role=UserRole.owner)
    operator = await create_user(
        session, email="operator@example.com", role=UserRole.operator
    )

    assert (
        await user_service.is_last_capability_holder(
            session, operator.id, Capability.CONFIG_MANAGE
        )
        is False
    )


async def test_soft_delete_removes_membership_in_guild_schema(
    session: AsyncSession, role_session
):
    """Production-faithful routing check (schema-per-guild).

    The membership-drop cascade must operate on the GUILD schema where the
    rows actually live. Factories write the
    InitiativeMember into ``guild_<id>`` (via the test routing harness), and
    soft_delete resets the session to ``public`` on the way out (as a real
    request would). So this asserts by EXPLICITLY re-routing into the guild
    schema afterwards: if the cascade had run unrouted against ``public``, the
    guild-schema row would still be here and this would fail."""
    from app.db.session import set_rls_context
    from app.models.tenant.initiative import InitiativeMember
    from app.testing.factories import create_initiative, create_initiative_member

    creator = await create_user(session, email="guild-creator@example.com")
    guild = await create_guild(session, creator=creator)
    initiative = await create_initiative(session, guild=guild, creator=creator)

    member = await create_user(session, email="departing-member@example.com")
    await create_guild_membership(session, user=member, guild=guild)
    await create_initiative_member(session, initiative=initiative, user=member)

    # Sanity: the membership exists in the guild schema before deletion.
    await set_rls_context(session, SystemGuild(guild.id))
    before = (
        await session.exec(
            select(InitiativeMember).where(InitiativeMember.user_id == member.id)
        )
    ).all()
    assert len(before) == 1

    system_session = await role_session("app_admin")
    await user_service.soft_delete_user(system_session, member.id)

    # Re-route into the guild schema and confirm the row is gone THERE.
    session.expunge_all()
    await set_rls_context(session, SystemGuild(guild.id))
    after = (
        await session.exec(
            select(InitiativeMember).where(InitiativeMember.user_id == member.id)
        )
    ).all()
    assert after == []

    # And the user row itself (shared/public) is anonymized.
    await set_rls_context(session, Unattributed())
    refreshed = (await session.exec(select(User).where(User.id == member.id))).one()
    assert refreshed.status == UserStatus.anonymized


async def test_soft_delete_takes_their_name_out_of_collaboration(
    session: AsyncSession, role_session
):
    """Anonymizing a user leaves content as it is, since a mention holds no
    name, and takes the names out of the collaboration state of every file
    and wiki page that mentions them, archived ones included: an editor from
    before names were left out can have written one into it. A state that
    cannot be read is left as it is. Batched lines lose
    the assigner's name snapshot and id (issue #794)."""
    from sqlalchemy import text

    from app.db.session import set_rls_context
    from app.models.tenant.file import File
    from app.models.tenant.batched_notice import BatchedNotice, BatchedNoticeKind
    from app.models.tenant.wiki import WikiPage
    from app.services.tenant.mention_parser import (
        ANONYMIZED_MENTION_NAME,
        nameless_state,
    )
    from app.testing import MENTIONING_YJS_STATE
    from app.testing.factories import (
        create_file,
        create_initiative,
        create_initiative_member,
        create_project,
        create_task,
        create_wiki,
        create_wiki_page,
        enable_all_tools,
        lexical_body,
    )
    from app.testing.schema_harness import route_session_to_guild

    author = await create_user(session, email="author@example.com")
    victim = await create_user(session, email="victim@example.com")
    guild = await create_guild(session, creator=author)
    await create_guild_membership(session, user=victim, guild=guild)
    initiative = await create_initiative(session, guild, author)
    await create_initiative_member(session, initiative=initiative, user=victim)
    project = await create_project(session, initiative, author)
    task = await create_task(session, project)
    mentioning = lexical_body("Thanks ", mentioning=victim.id)
    file = await create_file(
        session, initiative, author, content=mentioning, yjs_state=MENTIONING_YJS_STATE
    )
    archived = await create_file(
        session,
        initiative,
        author,
        content=mentioning,
        yjs_state=MENTIONING_YJS_STATE,
        archived_at=datetime.now(timezone.utc),
    )
    elsewhere = await create_file(
        session,
        initiative,
        author,
        content=lexical_body("Thanks ", mentioning=author.id),
        yjs_state=b"kept-state",
    )
    unreadable = await create_file(
        session, initiative, author, content=mentioning, yjs_state=b"unreadable"
    )
    await enable_all_tools(session, initiative)
    page = await create_wiki_page(
        session,
        await create_wiki(session, initiative, author),
        author,
        content=mentioning,
        yjs_state=MENTIONING_YJS_STATE,
    )
    line = BatchedNotice(
        user_id=author.id,
        kind=BatchedNoticeKind.task_assignment,
        actor_id=victim.id,
        actor_name="Vic Tim",
        target_type="task",
        target_id=task.id,
        target_path=f"/go/task/{task.id}",
        title=task.title,
        project_id=project.id,
        project_name=project.name,
    )
    session.add(line)
    await session.commit()
    line_id = line.id
    victim_id = victim.id

    # Account erasure is trusted system work and must not be narrowed by an
    # evolving tenant UPDATE policy. This restrictive policy independently
    # proves the lifecycle path retains its system identity while routed into
    # the guild schema.
    await set_rls_context(session, Unattributed())
    await session.exec(
        text(
            f'CREATE POLICY test_erasure_system_path ON "guild_{guild.id}".files '
            "AS RESTRICTIVE FOR UPDATE USING (false) WITH CHECK (false)"
        )
    )
    await session.commit()

    system_session = await role_session("app_admin")
    await user_service.soft_delete_user(system_session, victim_id)

    session.expunge_all()
    await route_session_to_guild(session, guild.id)
    states = dict(
        (
            await session.exec(
                select(File.id, File.yjs_state)
                .where(
                    File.id.in_(  # type: ignore[union-attr]
                        [file.id, archived.id, elsewhere.id, unreadable.id]
                    )
                )
                .execution_options(include_archived=True)
            )
        ).all()
    )
    assert states.pop(elsewhere.id) == b"kept-state"
    assert states.pop(unreadable.id) == b"unreadable"
    refreshed_page = (
        await session.exec(
            select(WikiPage)
            .where(WikiPage.id == page.id)
            .options(undefer(WikiPage.content), undefer(WikiPage.yjs_state))
        )
    ).one()
    assert refreshed_page.content == mentioning
    for state in (*states.values(), refreshed_page.yjs_state):
        assert state != MENTIONING_YJS_STATE and nameless_state(state) is None

    line_name, line_by = (
        await session.exec(
            select(BatchedNotice.actor_name, BatchedNotice.actor_id).where(
                BatchedNotice.id == line_id
            )
        )
    ).one()
    assert line_name == ANONYMIZED_MENTION_NAME
    assert line_by is None


async def test_hard_delete_anonymized_user_cleans_guild_data(
    session: AsyncSession, role_session
):
    """Hard-deleting an already-anonymized user must still clean their
    guild-scoped rows. Anonymize drops the membership rows, so enumerating
    memberships found no guilds and silently left everything behind
    (issue #794) — the sweep now covers every guild."""
    from app.models.tenant.resource_grant import ResourceGrant
    from app.models.tenant.task import Task, TaskAssignee
    from app.testing.factories import (
        create_initiative,
        create_initiative_member,
        create_project,
        create_task,
    )
    from app.testing.schema_harness import route_session_to_guild

    admin = await create_user(session, email="keeper@example.com")
    victim = await create_user(session, email="husk@example.com")
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(session, user=victim, guild=guild)
    initiative = await create_initiative(session, guild, admin)
    await create_initiative_member(session, initiative=initiative, user=victim)
    project = await create_project(session, initiative, admin)
    task = await create_task(session, project, assignees=[victim])
    guild_id = guild.id
    victim_id = victim.id
    task_id = task.id

    # Anonymize first — this drops the guild membership rows.
    system_session = await role_session("app_admin")
    await user_service.soft_delete_user(system_session, victim_id)
    session.expunge_all()

    await user_service.hard_delete_user(system_session, victim_id)
    session.expunge_all()

    # The users row is gone.
    remaining_user = (
        await session.exec(select(User).where(User.id == victim_id))
    ).one_or_none()
    assert remaining_user is None

    # And so are their guild-scoped rows, even though they had no
    # membership left at hard-delete time.
    await route_session_to_guild(session, guild_id)
    assignees = (
        await session.exec(
            select(TaskAssignee).where(TaskAssignee.user_id == victim_id)
        )
    ).all()
    assert assignees == []
    grants = (
        await session.exec(
            select(ResourceGrant).where(ResourceGrant.user_id == victim_id)
        )
    ).all()
    assert grants == []
    # The task itself survives.
    assert (
        await session.exec(select(Task).where(Task.id == task_id))
    ).one_or_none() is not None


async def test_soft_delete_user_removes_sign_in_sessions(session: AsyncSession):
    """Erasure empties the account of its sign-in sessions too — those rows
    carry a device label, a user agent and an address."""
    from app.models.platform.auth_session import AuthSession
    from app.services.auth import sessions as session_service

    user = await create_user(session)
    bystander = await create_user(session)
    mine = await session_service.create_session(
        session,
        user_id=user.id,
        amr=["pwd"],
        satisfied_providers=[],
        user_agent="Mozilla/5.0",
        ip="203.0.113.7",
        device_name="Laptop",
    )
    theirs = await session_service.create_session(
        session, user_id=bystander.id, amr=["pwd"], satisfied_providers=[]
    )
    await session.commit()
    mine_id, theirs_id, user_id = mine.session.id, theirs.session.id, user.id

    await user_service.soft_delete_user(session, user_id)

    session.expire_all()
    assert await session.get(AuthSession, mine_id) is None
    assert await session.get(AuthSession, theirs_id) is not None


async def test_soft_delete_user_removes_the_second_factor(session: AsyncSession):
    """Erasure empties the account of its factor, the seed behind it, the codes
    that stand in for it, and any sign-in held part-way through."""
    import pyotp

    from app.models.platform.auth_challenge import AuthChallenge
    from app.models.platform.mfa_recovery_code import MfaRecoveryCode
    from app.models.platform.user_totp import UserTotp
    from app.models.platform.user_totp_secret import UserTotpSecret
    from app.services.auth import challenges as challenge_service
    from app.services.auth import totp as totp_service

    user = await create_user(session)
    bystander = await create_user(session)
    for holder in (user, bystander):
        enrolment = await totp_service.begin_enrolment(
            session, user_id=holder.id, account="a@example.com", issuer="Initiative"
        )
        await totp_service.confirm_enrolment(
            session, user_id=holder.id, code=pyotp.TOTP(enrolment.secret).now()
        )
        await totp_service.issue_recovery_codes(session, user_id=holder.id)
        await challenge_service.create(
            session,
            user_id=holder.id,
            purpose=challenge_service.ChallengePurpose.sign_in,
        )
    await session.commit()
    user_id, bystander_id = user.id, bystander.id

    await user_service.soft_delete_user(session, user_id)
    session.expire_all()

    assert await session.get(UserTotp, user_id) is None
    assert await session.get(UserTotpSecret, user_id) is None
    for model in (MfaRecoveryCode, AuthChallenge):
        rows = (await session.exec(select(model).where(model.user_id == user_id))).all()
        assert rows == [], f"{model.__tablename__} kept a row"

    # The account beside it is untouched.
    assert await session.get(UserTotp, bystander_id) is not None
    assert (
        await totp_service.remaining_recovery_codes(session, user_id=bystander_id)
        == totp_service.RECOVERY_CODE_COUNT
    )


async def test_soft_delete_user_empties_the_shared_tables(
    session: AsyncSession, role_session
):
    """Everything a hard delete takes by cascade, anonymizing takes by hand:
    the row stays, so no cascade fires. Run on the system engine, which is what
    the purge worker erases on, so a missing grant fails here too."""
    import uuid

    from app.models.platform.announcement import AnnouncementReadReceipt
    from app.models.platform.contact_grant import (
        ContactGrant,
        ContactGrantKind,
        canonical_pair,
    )
    from app.models.platform.dm_conversation import (
        DmConversation,
        DmConversationMember,
    )
    from app.models.platform.dm_device import DmDevice
    from app.models.platform.email_outbox import EmailOutboxItem
    from app.models.platform.notification import Notification
    from app.models.platform.user_birthdate import UserBirthdate
    from app.models.platform.user_cookie_consent import UserCookieConsent
    from app.models.platform.user_decoration import UserDecoration
    from app.models.platform.user_dm_guild_optout import UserDmGuildOptout
    from app.models.platform.user_dm_settings import UserDmSettings
    from app.models.platform.user_ignore import UserIgnore
    from app.models.platform.user_passkey import UserPasskey

    user = await create_user(session)
    other = await create_user(session)
    guild = await create_guild(session, creator=other)
    user.profile_decorations = {"trophies": ["core.first-task"]}
    user.custom_status = {"text": "on holiday in Lisbon"}
    session.add(user)
    conversation = DmConversation()
    session.add(conversation)
    await session.flush()
    low, high = canonical_pair(user.id, other.id)
    session.add_all(
        [
            UserDecoration(
                user_id=user.id, decoration_id="core.first-task", kind="trophy"
            ),
            UserPasskey(
                user_id=user.id,
                credential_id=uuid.uuid4().bytes,
                public_key=b"key",
                rp_id="example.com",
                name="Work laptop",
            ),
            Notification(user_id=user.id, data={"task_title": "Secret plan"}),
            EmailOutboxItem(
                user_id=user.id,
                category="task",
                subject="Secret plan",
                headline="Secret plan",
                body="Secret plan",
            ),
            AnnouncementReadReceipt(user_id=user.id, announcement_key="builtin:x"),
            UserCookieConsent(user_id=user.id, version=1),
            UserBirthdate(user_id=user.id, birthdate_encrypted="sealed"),
            DmDevice(user_id=user.id, identity_key=b"i", fingerprint_key=b"f"),
            DmConversationMember(conversation_id=conversation.id, user_id=user.id),
            DmConversationMember(conversation_id=conversation.id, user_id=other.id),
            UserDmGuildOptout(user_id=user.id, guild_id=guild.id),
            UserIgnore(user_id=user.id, ignored_user_id=other.id),
            UserIgnore(user_id=other.id, ignored_user_id=user.id),
            ContactGrant(
                user_id_low=low,
                user_id_high=high,
                kind=ContactGrantKind.connection,
                requested_by=other.id,
            ),
        ]
    )
    await session.commit()
    user_id, other_id = user.id, other.id

    await user_service.soft_delete_user(await role_session("app_admin"), user_id)
    session.expire_all()

    husk = await session.get(User, user_id)
    assert husk.profile_decorations == {}
    assert husk.custom_status == {}
    for model, column in (
        (UserDecoration, UserDecoration.user_id),
        (UserPasskey, UserPasskey.user_id),
        (Notification, Notification.user_id),
        (EmailOutboxItem, EmailOutboxItem.user_id),
        (AnnouncementReadReceipt, AnnouncementReadReceipt.user_id),
        (UserCookieConsent, UserCookieConsent.user_id),
        (UserBirthdate, UserBirthdate.user_id),
        (DmDevice, DmDevice.user_id),
        (DmConversationMember, DmConversationMember.user_id),
        (UserDmSettings, UserDmSettings.user_id),
        (UserDmGuildOptout, UserDmGuildOptout.user_id),
        (UserIgnore, UserIgnore.user_id),
        (UserIgnore, UserIgnore.ignored_user_id),
        (ContactGrant, ContactGrant.user_id_low),
        (ContactGrant, ContactGrant.user_id_high),
    ):
        rows = (await session.exec(select(model).where(column == user_id))).all()
        assert rows == [], f"{column} kept a row"

    # The other side of the conversation is still on it.
    assert (
        await session.exec(
            select(DmConversationMember).where(DmConversationMember.user_id == other_id)
        )
    ).all()


# ---------------------------------------------------------------------------
# The erasure receipt
# ---------------------------------------------------------------------------


async def test_erasure_is_acknowledged_at_every_proved_address(session, monkeypatch):
    """The letter goes to the addresses the account proved, read before the
    erasure takes them away."""
    from app.services import email as email_service
    from app.services.auth import addresses
    from app.services.platform import users as users_service

    sent: list[list[str]] = []

    async def _capture(session_, *, recipients, locale="en"):
        sent.append(list(recipients))

    monkeypatch.setattr(email_service, "announce_account_erased", _capture)

    user = await create_user(session, email="erased-primary@example.com")
    addresses.record_address(
        session,
        user_id=user.id,
        email="erased-work@example.com",
        source=addresses.SOURCE_ADDED,
        is_primary=False,
        verified=True,
    )
    await session.commit()

    await users_service.soft_delete_user(session, user.id, actor_user_id=user.id)

    assert sent == [["erased-primary@example.com", "erased-work@example.com"]]


async def test_an_erasure_with_nowhere_to_write_still_happens(session, monkeypatch):
    """No proved address means no letter and no failure — the account is gone
    either way."""
    from app.models.platform.user import UserStatus
    from app.services import email as email_service
    from app.services.platform import users as users_service

    calls: list[str] = []

    async def _boom(session_, *, recipients, locale="en"):
        calls.append("called")
        raise RuntimeError("no mail here")

    monkeypatch.setattr(email_service, "send_account_erased_email", _boom)

    user = await create_user(session, email="erased-quiet@example.com")
    user_id = user.id

    await users_service.soft_delete_user(session, user_id, actor_user_id=user_id)

    session.expire_all()
    after = await session.get(type(user), user_id)
    assert after.status == UserStatus.anonymized


async def test_a_kept_birthdate_is_never_replaced(session: AsyncSession):
    """Keeping is one insert: of two answers, exactly one is kept, and a second
    leaves the first as it is."""
    from datetime import date

    from app.db.session import SystemSessionLocal

    user = await create_user(session)
    async with SystemSessionLocal() as system_session:
        first = await user_service.keep_birthdate(
            system_session, user_id=user.id, birthdate=date(1990, 5, 4)
        )
        second = await user_service.keep_birthdate(
            system_session, user_id=user.id, birthdate=date(2015, 1, 1)
        )
        await system_session.commit()
        kept = await user_service.birthdate_of(system_session, user_id=user.id)

    assert first is not None and second is None
    assert kept == date(1990, 5, 4)


async def test_taking_back_a_date_leaves_a_newer_one(session: AsyncSession):
    """A failed answer takes back only the date it kept, never one a later
    answer kept after a reset."""
    from datetime import date

    from app.db.session import SystemSessionLocal

    user = await create_user(session)
    async with SystemSessionLocal() as system_session:
        failed = await user_service.keep_birthdate(
            system_session, user_id=user.id, birthdate=date(1990, 5, 4)
        )
        await user_service.forget_birthdate(system_session, user_id=user.id)
        await user_service.keep_birthdate(
            system_session, user_id=user.id, birthdate=date(1991, 6, 5)
        )
        await user_service.forget_birthdate(
            system_session, user_id=user.id, only=failed
        )
        await system_session.commit()
        kept = await user_service.birthdate_of(system_session, user_id=user.id)

    assert kept == date(1991, 6, 5)
