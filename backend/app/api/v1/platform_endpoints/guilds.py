from __future__ import annotations

import logging
import re
from typing import Annotated, List

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)

from app.api.deps import (
    CommunityIdPath,
    GuildContext,
    SeatPaymentSessionDep,
    SeatSessionDep,
    SeatWriteSessionDep,
    SettingsAdminContextDep,
    SettingsAdminWriteContextDep,
    SettingsContextDep,
    SettingsRLSSessionDep,
    SettingsSeatWriteContextDep,
    UploadUserDep,
    UserSessionDep,
    GuildAccessError,
    establish_guild_access,
    holds_guild_role,
    raise_for_guild_access,
    get_current_active_user,
    SystemSessionDep,
)
from app.api.v1.platform_endpoints.password_recheck import (
    require_password_or_recent_proof,
)
from app.core import auth_context
from app.core.intake import IntakeStream
from app.db.query import build_paginated_response
from app.core.capabilities import Capability, user_has_capability
from app.core.config import settings
from app.core.login_methods import SecondFactorRequirement
from app.core.image_headers import validate_image
from app.core.messages import BillingMessages, GuildMessages, ImageMessages
from app.core.rate_limit import limiter
from app.core.security import (
    HandoffSigningNotConfiguredError,
    create_billing_portal_handoff_token,
)
from app.services.platform.identity_refs import billing_refs
from app.db import cohorts, post_commit
from app.db.request_context import SystemGuild
from app.db.session import set_rls_context
from app.core.audit_events import AuditEventType
from app.services import audit as audit_service
from app.services import email as email_service
from app.models.platform.guild import (
    assignable_roles,
    Guild,
    CommunityCategory,
    GuildMembership,
    CommunityRole,
    CommunityStatus,
    LIVE_STATUS_VALUES,
)
from app.demo import samples as demo_samples
from app.demo.copies import account_copy as demo_account_copy
from app.models.platform.guild_administration import GuildAdministration
from app.models.platform.guild_image import (
    BANNER_VARIANTS,
    IMAGE_SPECS,
    GuildImageVariant,
)
from app.models.platform.user import User, UserStatus
from app.schemas.platform.billing import BillingPortalHandoffResponse
from app.schemas.platform.guild import (
    DirectoryCommunityPage,
    DirectoryCommunityRead,
    CommunityBannerRead,
    CommunityCan,
    CommunityEntitlementsRead,
    CommunityAuthSettingsRead,
    CommunityAuthSettingsUpdate,
    CommunityAuthPolicyRead,
    CommunityCreate,
    CommunityDeletionRequest,
    CommunityMembershipUpdate,
    CommunityRead,
    CommunityInviteAcceptRequest,
    CommunityInviteCreate,
    CommunityGuestExtend,
    CommunityInviteGrant,
    CommunityInviteCreated,
    CommunityInviteRead,
    CommunityPaymentIssueRead,
    CommunityBillingSummaryRead,
    CommunityInviteStatus,
    CommunityOrderUpdate,
    CommunityUpdate,
    LeaveCommunityEligibilityResponse,
    MemberApiAccessUpdate,
    MemberDisplayNameUpdate,
)
from app.models.platform.auth_provider import AuthProvider
from app.models.platform.guild_auth_policy import GuildAuthPolicy, SignInHalf
from app.core.guild_auth_options import CommunityAuthOption, effective_options
from app.services.platform import app_settings as app_settings_service
from app.services.platform import auth_posture
from app.services.platform import notification_policy
from app.services.platform import billing as billing_service
from app.services.platform import billing_ping
from app.services.platform import guild_images as images_service
from app.services.tenant.attachments import FileTooLargeError, read_upload_bounded
from app.services.platform import guild_entitlements
from app.services.platform import guilds as guilds_service
from app.services.platform import intake as intake_service
from app.services.content_sockets import sockets as content_sockets
from app.services.tenant import plugin_connections as plugin_connections_service
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession


router = APIRouter()
logger = logging.getLogger(__name__)


def _can_of(guild_context: GuildContext, *, use_api: bool) -> CommunityCan:
    """What the caller may do in the community, by the standing: each flag is
    what the guard on the routes that do the thing asks. ``use_api`` is
    :func:`guild_entitlements.accepts_api_keys` for the caller's membership."""
    return CommunityCan(
        # The seam admitted the request, which a community in time out refuses.
        enter=True,
        content=not guild_context.is_settings_only,
        administer=holds_guild_role(guild_context, CommunityRole.admin, settings=True),
        configure=guild_context.writes_settings,
        administer_content=holds_guild_role(guild_context, CommunityRole.admin),
        seat=guild_context.guild_seat,
        community_wide=not guild_context.routes_as_guest,
        use_api=use_api,
    )


def _can_of_membership(
    guild: Guild, role: CommunityRole, *, use_api: bool
) -> CommunityCan:
    """The same answers for a membership row read without a standing, as the
    caller's own list is: the row's rung asked of the ladder the standing's
    admin fact is rendered from, and the lifecycle status the seam admits a
    member by."""
    administers = role.reaches(CommunityRole.admin)
    return CommunityCan(
        enter=guild.status in LIVE_STATUS_VALUES,
        content=True,
        administer=administers,
        configure=administers,
        administer_content=administers,
        seat=role.reaches(CommunityRole.superadmin),
        community_wide=role is not CommunityRole.guest,
        use_api=use_api,
    )


def _serialize_guild(
    guild: Guild,
    *,
    role: CommunityRole,
    membership: GuildMembership | None,
    retention_days: int | None = None,
    member_count: int = 0,
    administration: GuildAdministration | None = None,
    can: CommunityCan,
    images: dict[GuildImageVariant, str] | None = None,
    closed_contact: str | None = None,
) -> CommunityRead:
    """Build one entry of the caller's own guild list.

    ``CommunityRead`` carries two kinds of information and this is the single seam
    that decides who gets which:

    - **Everyone in the guild** — the guild's identity (name, description,
      icon), the caller's own membership (role, position), the roster size, and
      ``content_read_only`` so the UI can drop write affordances.
    - **Guild admins only** — the administration fields: the operator-set caps
      and plan label, the trash retention window, the lifecycle status, and the
      per-guild sign-in entitlement. Each backs an admin-only surface (the whole
      guild settings section is admin-gated, as is ``/c/{id}/storage/usage``,
      the panel's other half), so a regular member's payload leaves them
      ``None``.

    Most of the second group now arrives as ``administration`` — a separate row
    the caller may read but no request path may write. Callers serving a member
    pass ``None`` for it and never read the row at all.

    ``membership`` is the caller's own row, where they have one; a grantee
    has no place in the list and no name of their own here.

    ``can`` is what the caller may do: :func:`_can_of` where the caller has a
    standing, :func:`_can_of_membership` where the row answers.

    ``closed_contact`` is who a suspended guild's admins are told to contact;
    it reaches the payload only for that guild and that rung.
    """
    # The rung decides, not the caller: passing the row for a member still
    # serves a member's payload, so this stays the one place the split is made.
    is_admin = role.reaches(CommunityRole.admin)
    admin_row = administration if is_admin else None
    return CommunityRead(
        id=guild.id,
        name=guild.name,
        description=guild.description,
        created_at=guild.created_at,
        updated_at=guild.updated_at,
        role=role,
        can=can,
        position=membership.position if membership is not None else 0,
        display_name=membership.display_name if membership is not None else None,
        # Trash retention window — set from the admin-only trash settings tab.
        retention_days=retention_days if is_admin else None,
        member_count=member_count,
        # Operator-set caps, shown against usage on the admin settings page.
        max_storage_bytes=admin_row.max_storage_bytes if admin_row else None,
        max_users=admin_row.max_users if admin_row else None,
        max_guests=admin_row.max_guests if admin_row else None,
        # Display-only plan label (never an enforcement input); the SPA shows
        # it only when a billing portal is configured.
        tier_name=admin_row.tier_name if admin_row else None,
        # Only guild admins learn the lifecycle status (for the closed entry
        # and the read-only notice); members get None so a moderation hold
        # isn't disclosed to them.
        status=CommunityStatus(guild.status) if is_admin else None,
        # Every member learns the *effect* of a read_only hold (their writes
        # already fail at the DB role level) so the UI can drop write
        # affordances — without disclosing the status itself.
        content_read_only=(guild.status == CommunityStatus.read_only.value),
        contact_email=(
            closed_contact
            if is_admin and guild.status == CommunityStatus.suspended.value
            else None
        ),
        # Admins only: lets their settings UI show/hide the Authentication tab.
        # Derived, not stored — an option ticked under a master nobody granted
        # is not one this guild holds.
        auth_options=sorted(effective_options(admin_row.auth_options))
        if admin_row
        else None,
        # Admins only: the state of the API-access control on that tab.
        # Admins only: and of the session-limit control beside it.
        enforce_compliance_session=(
            guild.enforce_compliance_session if is_admin else None
        ),
        # Admins only: and of the second-factor control beside that.
        require_second_factor=(guild.require_second_factor if is_admin else None),
        # Guild identity, not administration: the directory publishes both to
        # strangers, so withholding them from the guild's own members would
        # only mean the settings page could not render its own state.
        is_community=guild.is_community,
        categories=[CommunityCategory(value) for value in guild.categories],
        has_adult_content=guild.has_adult_content,
        location=guild.location,
        # Where the guild's pictures are, not the pictures. Callers that have
        # no reason to have looked them up pass nothing, which reads the same
        # as a guild without any. The rest of the banner is stored, so it needs
        # no such arrangement.
        icon_url=(images or {}).get(GuildImageVariant.icon),
        banner=CommunityBannerRead(
            image_url=(images or {}).get(GuildImageVariant.full), **guild.banner
        ),
        banner_card_url=(images or {}).get(GuildImageVariant.card),
        # Read here rather than passed in, so every payload that names a guild
        # carries the same figure without each call site remembering to ask.
        # It costs no query — presence is a dict this process already holds.
        online_count=content_sockets.present_count(guild.id),
    )


async def _guild_read(
    system_session: AsyncSession,
    guild: Guild,
    *,
    membership: GuildMembership | None = None,
    standing: GuildContext | None = None,
    guild_session: AsyncSession | None = None,
) -> CommunityRead:
    """One community's entry, with everything it is built from gathered here.

    ``standing`` and ``guild_session`` are the caller's standing in the
    community and their session routed into it, for the routes the seam
    admitted. ``membership`` is the caller's row, for the routes that run
    before there is a standing to route by (creating, joining).

    The roster size and the administration row are read on the routed session
    where there is one, and on the system engine where there is not. The
    retention window lives in the community's own schema, so it is read only on
    a routed session. The administration row and the window are read only for
    an admin, the only rung served them. The pictures are read on the system engine: a settings rung reads on the
    read-only floor, which holds no grant on the image digests, and the image
    route serves them to a grant holder as it does to a member.
    """
    if standing is not None:
        membership = standing.membership
    elif membership is None:
        raise TypeError("_guild_read needs a standing or a membership")
    # A grantee holds no membership, and a grant is never reached with a key.
    use_api = membership is not None and not (
        await guild_entitlements.refuses_api_keys(system_session, membership)
    )
    if standing is not None:
        role = standing.rung
        can = _can_of(standing, use_api=use_api)
    else:
        role = membership.role
        can = _can_of_membership(guild, role, use_api=use_api)
    is_admin = role.reaches(CommunityRole.admin)
    reader = guild_session if guild_session is not None else system_session
    return _serialize_guild(
        guild,
        role=role,
        membership=membership,
        can=can,
        retention_days=(
            await guilds_service.get_guild_retention_days(guild_session)
            if is_admin and guild_session is not None
            else None
        ),
        member_count=await guilds_service.count_members(reader, guild_id=guild.id),
        administration=(
            await guilds_service.get_administration(reader, guild_id=guild.id)
            if is_admin
            else None
        ),
        images=await images_service.image_urls_for(
            system_session, guild.id, *GuildImageVariant
        ),
    )


_GUILD_PROFILE_FIELDS = (
    "name",
    "description",
    "banner",
    "is_community",
    "categories",
    "has_adult_content",
    "location",
)


@router.get("/", response_model=List[CommunityRead])
async def list_communities(
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> List[CommunityRead]:
    """The communities the caller belongs to, in the order they keep them.

    Every community-scoped route takes one of these ids as its
    ``community_id``. A personal API key is shown the communities it can
    address: one limited to a community sees that one alone, and a community
    that turned off this member's API access is left out.
    """
    # A suspended account keeps every membership it had and reaches none of
    # them, so its guild list is empty — the same thing a suspended guild does
    # to its members' lists, and it keeps the app coherent rather than offering
    # doors that all refuse.
    if current_user.status == UserStatus.suspended:
        return []

    memberships = await guilds_service.list_memberships(
        session, user_id=current_user.id
    )
    # The same narrowing the cross-guild views apply
    # (``cross_guild.member_guild_ids``): a community ``/c/{community_id}``
    # would refuse this key is not one to offer it.
    recorded = auth_context.current()
    if recorded.api_key_credential:
        pinned = recorded.api_key_guild_id
        memberships = [
            (guild, *rest, accepts_api_keys)
            for guild, *rest, accepts_api_keys in memberships
            if accepts_api_keys and (pinned is None or guild.id == pinned)
        ]
    # One query for the whole list, and only the digests — a guild list is
    # every guild the caller is in, and a banner is a third of a megabyte.
    images = await images_service.image_urls(
        session, [guild.id for guild, *_ in memberships], *GuildImageVariant
    )
    # Asked once, and only when a suspended guild is on the list — the only
    # entry that names who to contact.
    closed_contact = (
        await intake_service.contact_for(session, IntakeStream.moderation)
        if any(
            guild.status == CommunityStatus.suspended.value for guild, *_ in memberships
        )
        else None
    )
    payloads: List[CommunityRead] = []
    for (
        guild,
        membership,
        retention_days,
        member_count,
        administration,
        accepts_api_keys,
    ) in memberships:
        payloads.append(
            _serialize_guild(
                guild,
                role=membership.role,
                membership=membership,
                can=_can_of_membership(
                    guild, membership.role, use_api=accepts_api_keys
                ),
                retention_days=retention_days,
                member_count=member_count,
                administration=administration,
                images=images.get(guild.id),
                closed_contact=closed_contact,
            )
        )
    return payloads


@router.put("/order", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def reorder_communities(
    payload: CommunityOrderUpdate,
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Response:
    await guilds_service.reorder_memberships(
        session,
        user_id=current_user.id,
        ordered_guild_ids=payload.community_ids,
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


#: Directory pages are card grids; a bigger page buys scrolling, not answers.
MAX_COMMUNITY_PAGE_SIZE = 60


@router.get("/directory", response_model=DirectoryCommunityPage)
async def list_directory_communities(
    session: SystemSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    search: str | None = Query(default=None, max_length=200),
    # The countries ``search`` names, as ISO codes. Country names are the
    # reader's language's business, so the client resolves them; a community
    # in one of these matches the search as if its text had.
    search_country: list[str] = Query(default=[], max_length=50),
    category: list[CommunityCategory] = Query(default=[]),
    # Where the reader is, to put the communities nearest them first: a
    # country, and the point they picked in it. None of it narrows the list.
    near_country: str | None = Query(default=None, pattern=r"^[A-Za-z]{2}$"),
    near_lat: float | None = Query(default=None, ge=-90, le=90),
    near_lon: float | None = Query(default=None, ge=-180, le=180),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=MAX_COMMUNITY_PAGE_SIZE),
) -> DirectoryCommunityPage:
    """Browse the guilds that opted into the community directory.

    Runs on the system engine for the reason ``GET /invite/{code}`` does: the
    caller is a stranger to every guild here, so no guild-scoped role exists to
    read them under, and the RLS policy that scopes ``guilds`` to the caller's
    own memberships would return an empty directory. What that engine may see
    is not what this returns — the filters live in the service (listed AND
    active, always), and :class:`DirectoryCommunityRead` carries only what a guild
    published by opting in: no lifecycle status, no administration, no roster,
    and nothing at all from inside the guild's own schema. How many people have
    it open is a count of live connections, named to nobody.

    The directory is a deployment-level feature an owner switches on; where it
    is off there is nothing to browse and the request is refused rather than
    answered with an empty page.
    """
    rows, total = await guilds_service.list_community_guilds(
        session,
        user_id=current_user.id,
        query=search,
        query_countries=[
            code.upper()
            for code in search_country
            if re.fullmatch(r"[A-Za-z]{2}", code)
        ],
        categories=[c.value for c in category],
        near=(
            guilds_service.NearPlace(
                country=near_country.upper(),
                # A point is used only whole.
                latitude=near_lat if near_lon is not None else None,
                longitude=near_lon if near_lat is not None else None,
            )
            if near_country
            else None
        ),
        page=page,
        page_size=page_size,
    )
    # Who is present is live state held by the process, not a column, so it is
    # read here for the page being returned rather than joined in the query.
    online = content_sockets.present_counts(guild.id for guild, _, _ in rows)
    # Digests only, in one query: a card names its pictures, never carries them.
    images = await images_service.image_urls(
        session,
        [guild.id for guild, _, _ in rows],
        GuildImageVariant.icon,
        GuildImageVariant.card,
    )
    return DirectoryCommunityPage(
        **build_paginated_response(
            [
                DirectoryCommunityRead(
                    id=guild.id,
                    name=guild.name,
                    description=guild.description,
                    icon_url=images.get(guild.id, {}).get(GuildImageVariant.icon),
                    banner=CommunityBannerRead(
                        image_url=images.get(guild.id, {}).get(GuildImageVariant.card),
                        **guild.banner,
                    ),
                    categories=[CommunityCategory(value) for value in guild.categories],
                    location=guild.location,
                    member_count=member_count,
                    online_count=online.get(guild.id, 0),
                    already_member=already_member,
                )
                for guild, member_count, already_member in rows
            ],
            total,
            page,
            page_size,
        )
    )


@router.post("/directory/{community_id}/join", response_model=CommunityRead)
async def join_directory_community(
    guild_id: CommunityIdPath,
    session: SystemSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> CommunityRead:
    """Join a listed community guild. Its listing is the authorization.

    The system engine for the same reason ``accept_invite`` uses it — the user
    has no membership yet, so there is no guild role to write one under. Joining
    an already-joined guild is not an error; it returns the guild the caller is
    already in.
    """
    guild = await guilds_service.join_community_guild(
        session, guild_id=guild_id, user=current_user
    )
    await session.commit()
    await post_commit.settle(session)
    membership = await guilds_service.get_membership(
        session, guild_id=guild.id, user_id=current_user.id
    )
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=GuildMessages.COMMUNITY_MEMBERSHIP_MISSING,
        )
    # Joining is how the caller first earns the full-size banner they were
    # shown a card of.
    return await _guild_read(session, guild, membership=membership)


@router.get("/invite/{code}", response_model=CommunityInviteStatus)
@limiter.limit("30/minute")
async def get_invite_status(
    request: Request,
    code: str,
    session: SystemSessionDep,
) -> CommunityInviteStatus:
    invite, guild, is_valid, reason = await guilds_service.describe_invite_code(
        session, code=code
    )
    return CommunityInviteStatus(
        code=code,
        community_id=guild.id if guild else None,
        community_name=guild.name if guild else None,
        is_valid=is_valid,
        reason=reason,
        expires_at=invite.expires_at if invite else None,
        max_uses=invite.max_uses if invite else None,
        uses=invite.uses if invite else None,
        guest_days=invite.guest_days if invite else None,
    )


async def _resolve_guild_owner(
    session: AsyncSession, guild_in: CommunityCreate, current_user: User
) -> User:
    """Who the new guild's admin will be — the caller, unless a
    ``communities.manage`` holder named someone else.

    Refused rather than ignored without that capability: creating the guild
    under the caller would answer 201 for a request that named another account.
    The named account must already exist and be active — this never creates
    one, and never hands a guild to an account that cannot sign in to run it.
    """
    requested = guild_in.owner_user_id
    if requested is None or requested == current_user.id:
        return current_user
    if not user_has_capability(current_user, Capability.COMMUNITIES_MANAGE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=GuildMessages.COMMUNITY_OWNER_REQUIRES_CAPABILITY,
        )
    owner = await session.get(User, requested)
    if owner is None or owner.status is not UserStatus.active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=GuildMessages.COMMUNITY_OWNER_NOT_FOUND,
        )
    return owner


@router.post("/", response_model=CommunityRead, status_code=status.HTTP_201_CREATED)
async def create_community(
    guild_in: CommunityCreate,
    session: SystemSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> CommunityRead:
    """Create a new guild. Uses the system session because the guild doesn't exist
    yet — no guild context or membership exists for RLS to match against.

    The caller becomes the guild's admin, unless they hold ``communities.manage``
    and name an ``owner_user_id``, which hands the guild to that account
    instead and leaves the caller holding nothing in it.
    """
    if settings.DISABLE_GUILD_CREATION and not user_has_capability(
        current_user, Capability.COMMUNITIES_MANAGE
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=GuildMessages.COMMUNITY_CREATION_DISABLED,
        )
    if settings.DEMO_MODE and (
        await demo_account_copy(current_user.id) is not None
        or await demo_samples.is_sample(current_user.id)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=GuildMessages.COMMUNITY_CREATION_DEMO_ACCOUNT,
        )
    name = guild_in.name

    if not user_has_capability(
        current_user, Capability.COMMUNITIES_MANAGE
    ) and not await guilds_service.may_create_another_guild(
        session, user_id=current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=GuildMessages.COMMUNITY_CREATION_LIMIT_REACHED,
        )

    owner = await _resolve_guild_owner(session, guild_in, current_user)

    if (
        billing_service.billing_inbound_enabled()
        and not user_has_capability(current_user, Capability.COMMUNITIES_MANAGE)
        and await guilds_service.holds_a_free_guild(session, user_id=owner.id)
    ):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=GuildMessages.FREE_COMMUNITY_ALREADY_HELD,
        )

    try:
        guild = await guilds_service.provision_new_guild(
            session,
            name=name,
            description=guild_in.description,
            creator=current_user,
            owner=owner,
            actor_user_id=current_user.id,
        )
    except guilds_service.GuildProvisionError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=GuildMessages.COMMUNITY_PROVISION_FAILED,
        )
    if owner.id != current_user.id:
        # Both identities: created_by holds the first, the admin
        # membership the second.
        logger.info(
            "guild %s created by user %s on behalf of user %s",
            guild.id,
            current_user.id,
            owner.id,
        )
    # Committed and seeded. Claimed for the owner — who holds the admin
    # membership — rather than the caller.
    await guilds_service.welcome_new_guild(
        guild.id, owner_user_id=owner.id, plan=guild_in.plan
    )

    # The owner's membership — the caller's own in the ordinary case. When the
    # guild was created for another account the caller holds none, so the
    # response describes the guild through its admin.
    membership = await guilds_service.get_membership(
        session, guild_id=guild.id, user_id=owner.id
    )
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=GuildMessages.COMMUNITY_MEMBERSHIP_CREATE_FAILED,
        )
    # The creator is the new guild's admin, so their payload carries the
    # administration row — freshly created with the guild, all defaults.
    return await _guild_read(session, guild, membership=membership)


@router.get("/{community_id}/invites", response_model=List[CommunityInviteRead])
async def list_community_invites(
    guild_id: CommunityIdPath,
    _guild_context: SettingsAdminWriteContextDep,
    session: SettingsRLSSessionDep,
) -> List[CommunityInviteRead]:
    invites = await guilds_service.list_guild_invites(session, guild_id=guild_id)
    grants = await guilds_service.guest_invite_grants(
        session, invite_ids=[invite.id for invite in invites if invite.guest_days]
    )
    return [
        CommunityInviteRead.model_validate(invite).model_copy(
            update={
                "grants": [
                    CommunityInviteGrant.model_validate(grant)
                    for grant in grants.get(invite.id, [])
                ]
            }
        )
        for invite in invites
    ]


@router.get("/{community_id}", response_model=CommunityRead)
async def read_community(
    guild_id: CommunityIdPath,
    guild_context: SettingsAdminContextDep,
    session: SettingsRLSSessionDep,
    system_session: SystemSessionDep,
) -> CommunityRead:
    """The community as the caller's standing sees it — how a community
    reached by a settings grant, which has no entry in ``GET /communities/``, gets
    its entry and the answer to what the caller may change there.
    """
    guild = await guilds_service.get_guild(session, guild_id=guild_id)
    return await _guild_read(
        system_session, guild, standing=guild_context, guild_session=session
    )


@router.patch("/{community_id}", response_model=CommunityRead)
async def update_community(
    guild_id: CommunityIdPath,
    guild_context: SettingsAdminWriteContextDep,
    updates: CommunityUpdate,
    session: SettingsRLSSessionDep,
    system_session: SystemSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> CommunityRead:
    # Moving onto the shelf is measured against the roster the guild built
    # while it was private, and only on the way in — asked before the request
    # routes into its guild, because the answer lives in ``public.users``,
    # which a guild-scoped role does not read. A guild already listed is not
    # re-asked: the ways in keep it true from here, and failing an unrelated
    # edit over a member's answer would leave an admin nothing to do but
    # remove them.
    if updates.is_community:
        listed_before = (
            await guilds_service.get_guild(system_session, guild_id=guild_id)
        ).is_community
        if not listed_before:
            await guilds_service.assert_may_list_with_members(
                system_session, guild_id=guild_id
            )
    retention_days_provided = "retention_days" in updates.model_fields_set
    categories_provided = "categories" in updates.model_fields_set
    has_adult_content_provided = "has_adult_content" in updates.model_fields_set
    banner_provided = "banner" in updates.model_fields_set
    location_provided = "location" in updates.model_fields_set
    # The state this PATCH is measured against. Read before the write, since the
    # service edits the row in place.
    before_profile = audit_service.snapshot(
        await guilds_service.get_guild(session, guild_id=guild_id),
        _GUILD_PROFILE_FIELDS,
    )
    retention_before = (
        await guilds_service.get_guild_retention_days(session)
        if retention_days_provided
        else None
    )
    guild = await guilds_service.update_guild(
        session,
        guild_id=guild_id,
        name=updates.name,
        description=updates.description,
        retention_days=updates.retention_days,
        retention_days_provided=retention_days_provided,
        is_community=updates.is_community,
        categories=(
            [category.value for category in updates.categories]
            if updates.categories
            else []
        ),
        categories_provided=categories_provided,
        has_adult_content=updates.has_adult_content,
        has_adult_content_provided=has_adult_content_provided,
        banner=(updates.banner.model_dump(mode="json") if updates.banner else None),
        banner_provided=banner_provided,
        location=(
            updates.location.model_dump(mode="json") if updates.location else None
        ),
        location_provided=location_provided,
    )
    await audit_service.record_settings_change(
        session,
        guild_id=guild_id,
        actor_user_id=current_user.id,
        area="profile",
        before=before_profile,
        after=audit_service.snapshot(guild, _GUILD_PROFILE_FIELDS),
    )
    if retention_days_provided:
        await audit_service.record_settings_change(
            session,
            guild_id=guild_id,
            actor_user_id=current_user.id,
            area="retention",
            before={"retention_days": retention_before},
            after={
                "retention_days": await guilds_service.get_guild_retention_days(session)
            },
        )
    await session.commit()
    return await _guild_read(
        system_session, guild, standing=guild_context, guild_session=session
    )


# --- icons and banners -------------------------------------------------------
#
# The pictures a guild is known by are the only guild media a stranger can be
# shown: a listed guild's icon and its banner's card rendition are what its
# community-directory card is made of. Which is why these routes are here on
# the platform router rather than under ``/c/{id}/…``, and why they run on the
# system engine — see ``guild_images.may_read_image`` for the rule and the
# reasoning.


@router.get("/{community_id}/entitlements", response_model=CommunityEntitlementsRead)
async def read_community_entitlements(
    guild_id: CommunityIdPath,
    _guild_context: SettingsAdminContextDep,
    session: SettingsRLSSessionDep,
) -> CommunityEntitlementsRead:
    """What an operator has turned on for this guild, for its own admins.

    Its own read rather than fields on the guild payload: these are decisions
    made *about* a guild rather than by it, they live on the separate
    ``guild_administration`` row, and a member has no use for them. A guild
    admin does — it is how their settings page knows to offer the banner
    colour alone rather than an upload that would come back refused.
    """
    administration = await guilds_service.get_administration(session, guild_id=guild_id)
    return CommunityEntitlementsRead(
        community_id=guild_id,
        banner_image_enabled=(
            administration.banner_image_enabled if administration else True
        ),
    )


@router.get("/{community_id}/image/{sha256}", include_in_schema=False)
@limiter.limit("600/minute")
async def read_community_image(
    request: Request,
    guild_id: CommunityIdPath,
    sha256: str,
    current_user: UploadUserDep,
    session: SystemSessionDep,
) -> Response:
    """Serve one of a guild's images.

    Authenticated like ``/uploads/*`` and for the same reason: this is an
    ``<img>`` src, so the credential is the HttpOnly session cookie on web and a
    short-lived uploads-scoped ``?token=`` in a native WebView.

    Everything that isn't served is a 404, whether the image does not exist,
    has since been replaced, or is not for this caller — a guild that has not
    published itself gives up nothing at all, its existence included.
    """
    image = await images_service.read_image(session, guild_id=guild_id, sha256=sha256)
    if image is None or not await images_service.may_read_image(
        session,
        guild_id=guild_id,
        user_id=current_user.id,
        variant=GuildImageVariant(image.variant),
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ImageMessages.IMAGE_NOT_FOUND,
        )
    return Response(
        content=image.data,
        media_type=image.content_type,
        headers={
            # The digest is in the path, so these bytes are these bytes
            # forever. ``private`` because who may have them is decided per
            # caller: a shared cache must never hand one viewer's copy on.
            "Cache-Control": "private, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )


async def _store_guild_images(
    session: AsyncSession,
    *,
    guild_id: int,
    uploads: list[tuple[GuildImageVariant, UploadFile]],
) -> None:
    """Validate every part, then store them — never one and then the other.

    Each is checked on its own before anything is written: format read from the
    bytes rather than from the client's claim about them, weight, and shape.
    The system engine writes; no request-path role holds an INSERT here, and
    the caller's authority to be doing this at all was established against a
    real membership before this is reached.
    """
    renditions = {}
    for variant, upload in uploads:
        spec = IMAGE_SPECS[variant]
        try:
            data = await read_upload_bounded(upload, spec.max_bytes)
        except FileTooLargeError:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=ImageMessages.IMAGE_TOO_LARGE,
            )
        renditions[variant] = validate_image(spec, data)

    await images_service.set_images(session, guild_id=guild_id, renditions=renditions)


@router.put("/{community_id}/icon", response_model=CommunityRead)
async def set_community_icon(
    guild_id: CommunityIdPath,
    guild_context: SettingsAdminWriteContextDep,
    session: SystemSessionDep,
    settings_session: SettingsRLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    icon: UploadFile = File(...),
) -> CommunityRead:
    """Replace the guild's icon. One square picture, resized by the client."""
    await _store_guild_images(
        session,
        guild_id=guild_id,
        uploads=[(GuildImageVariant.icon, icon)],
    )
    await session.commit()
    guild = await guilds_service.get_guild(settings_session, guild_id=guild_id)
    return await _guild_read(
        session, guild, standing=guild_context, guild_session=settings_session
    )


@router.delete("/{community_id}/icon", response_model=CommunityRead)
async def clear_community_icon(
    guild_id: CommunityIdPath,
    guild_context: SettingsAdminWriteContextDep,
    session: SystemSessionDep,
    settings_session: SettingsRLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> CommunityRead:
    """Remove the guild's icon. It falls back to its lettered avatar."""
    await images_service.clear_images(
        session, guild_id=guild_id, variants=[GuildImageVariant.icon]
    )
    await session.commit()
    guild = await guilds_service.get_guild(settings_session, guild_id=guild_id)
    return await _guild_read(
        session, guild, standing=guild_context, guild_session=settings_session
    )


@router.put("/{community_id}/banner", response_model=CommunityRead)
async def set_community_banner(
    guild_id: CommunityIdPath,
    guild_context: SettingsAdminWriteContextDep,
    session: SystemSessionDep,
    settings_session: SettingsRLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    full: UploadFile = File(...),
    card: UploadFile = File(...),
) -> CommunityRead:
    """Replace the guild's banner with the two renditions of one picture.

    The admin chooses a single image; the settings page resizes it to both
    renditions and sends them together, so a guild is never left showing a new
    card over an old front page.
    """
    administration = await guilds_service.get_administration(session, guild_id=guild_id)
    if administration is not None and not administration.banner_image_enabled:
        # Only uploading is gated. The banner surface stays, a banner the guild
        # already has keeps being served, and what a guild without artwork sets
        # instead is the colour on ``guilds.banner``, through PATCH.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=GuildMessages.BANNER_IMAGE_NOT_ENTITLED,
        )
    await _store_guild_images(
        session,
        guild_id=guild_id,
        uploads=list(zip(BANNER_VARIANTS, (full, card))),
    )
    await session.commit()
    guild = await guilds_service.get_guild(settings_session, guild_id=guild_id)
    return await _guild_read(
        session, guild, standing=guild_context, guild_session=settings_session
    )


@router.delete("/{community_id}/banner", response_model=CommunityRead)
async def clear_community_banner(
    guild_id: CommunityIdPath,
    guild_context: SettingsAdminWriteContextDep,
    session: SystemSessionDep,
    settings_session: SettingsRLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> CommunityRead:
    """Remove the guild's banner. Both surfaces fall back to their plain form."""
    await images_service.clear_images(
        session, guild_id=guild_id, variants=list(BANNER_VARIANTS)
    )
    await session.commit()
    guild = await guilds_service.get_guild(settings_session, guild_id=guild_id)
    return await _guild_read(
        session, guild, standing=guild_context, guild_session=settings_session
    )


@router.post(
    "/{community_id}/billing/handoff",
    response_model=BillingPortalHandoffResponse,
)
async def create_community_billing_handoff(
    guild_id: CommunityIdPath,
    seat_session: SeatPaymentSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> BillingPortalHandoffResponse:
    """Mint a billing-portal handoff. The guild's superadmin only.

    What a community pays for is the top seat's, like its sign-in: an ordinary
    admin runs the place without holding its card. The seat reaches it while
    the community is on hold too, since paying is how a hold is lifted.
    """
    if not settings.BILLING_URL:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=BillingMessages.PORTAL_NOT_CONFIGURED,
        )

    try:
        user_ref, guild_ref = await billing_refs(
            user_id=current_user.id, guild_id=guild_id
        )
        token, expires_in_seconds = create_billing_portal_handoff_token(
            # The portal's own vocabulary, which is not this enum: it knows
            # "the person who may act for this guild", and only the seat
            # reaches here to say so.
            guild_role=CommunityRole.admin.value,
            user_ref=user_ref,
            guild_ref=guild_ref,
        )
    except HandoffSigningNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=BillingMessages.PORTAL_SIGNING_NOT_CONFIGURED,
        ) from exc

    return BillingPortalHandoffResponse(
        handoff_token=token,
        expires_in_seconds=expires_in_seconds,
    )


@router.get(
    "/{community_id}/billing/payment-issue",
    response_model=CommunityPaymentIssueRead,
)
@limiter.limit("6/minute")
async def read_community_payment_issue(
    request: Request,
    guild_id: CommunityIdPath,
    seat_session: SeatSessionDep,
) -> CommunityPaymentIssueRead:
    guild = await seat_session.get(Guild, guild_id)
    if (
        guild is None
        or guild.status == CommunityStatus.active.value
        or not settings.BILLING_URL
    ):
        return CommunityPaymentIssueRead()
    return CommunityPaymentIssueRead(
        payment_failed=await billing_ping.guild_payment_failed(guild_id)
    )


@router.get(
    "/{community_id}/billing/summary",
    response_model=CommunityBillingSummaryRead,
)
@limiter.limit("30/minute")
async def read_community_billing_summary(
    request: Request,
    guild_id: CommunityIdPath,
    _seat_session: SeatWriteSessionDep,
) -> CommunityBillingSummaryRead:
    """The guild's plan, asked of billing for this response and kept nowhere.

    Display only: initiative never writes to billing, and nothing here changes
    a plan — every change, cancelation included, is made in the billing
    portal. The seat that may open the portal, as the handoff mint asks: the
    summary is what that seat would act on there.
    """
    if not settings.BILLING_URL:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=BillingMessages.PORTAL_NOT_CONFIGURED,
        )
    summary = await billing_ping.guild_plan_summary(guild_id)
    if summary is None:
        return CommunityBillingSummaryRead()
    return CommunityBillingSummaryRead(available=True, **summary.model_dump())


def _auth_policy_read(
    half: SignInHalf | None,
    provider_display_name: str | None = None,
    *,
    factor_required_by_platform: bool = False,
) -> CommunityAuthPolicyRead:
    if half is None or half.policy == "open":
        return CommunityAuthPolicyRead(
            policy="open", factor_required_by_platform=factor_required_by_platform
        )
    return CommunityAuthPolicyRead(
        policy="required",
        provider_id=half.provider_id,
        provider_slug=half.provider_slug,
        provider_display_name=provider_display_name,
        require_methods=list(half.require_methods),
        factor_required_by_platform=factor_required_by_platform,
    )


async def _platform_asks_everyone(session) -> bool:
    """Whether the deployment already asks every account for a second factor.

    The one level that makes a community's own box redundant: asking the
    platform rungs leaves a community's members untouched, so that box stays.
    """
    level = await auth_posture.second_factor_requirement(session)
    return level is SecondFactorRequirement.everyone


async def _auth_settings_response(
    seat_session: AsyncSession, system_session: AsyncSession, guild_id: int
) -> CommunityAuthSettingsRead:
    guild = await seat_session.get(Guild, guild_id)
    if guild is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=GuildMessages.COMMUNITY_NOT_FOUND,
        )
    administration = await guilds_service.get_administration(
        seat_session, guild_id=guild_id
    )
    platform = await notification_policy.resolve(seat_session, None)
    settings_row = await app_settings_service.get_app_settings(seat_session)
    return CommunityAuthSettingsRead(
        auth_options=sorted(effective_options(administration.auth_options))
        if administration
        else [],
        auth_policy=await _auth_policy_response(system_session, guild_id),
        guest_auth_policy=await _auth_policy_response(
            system_session, guild_id, guest=True
        ),
        enforce_compliance_session=guild.enforce_compliance_session,
        require_second_factor=guild.require_second_factor,
        allow_push_notifications=guild.allow_push_notifications,
        allow_email_notifications=guild.allow_email_notifications,
        redact_notification_content=guild.redact_notification_content,
        push_allowed_by_platform=platform.push,
        email_allowed_by_platform=platform.email,
        redacted_by_platform=platform.redact,
        allow_engagement_ranking=guild.allow_engagement_ranking,
        engagement_ranking_allowed_by_platform=settings_row.engagement_ranking_enabled,
        guest_max_days=guild.guest_max_days,
        guest_max_days_by_platform=settings_row.max_guest_days,
    )


@router.get("/{community_id}/auth-settings", response_model=CommunityAuthSettingsRead)
async def get_community_auth_settings(
    guild_id: CommunityIdPath,
    seat_session: SeatSessionDep,
    system_session: SystemSessionDep,
) -> CommunityAuthSettingsRead:
    """Read the controls held by this community's superadmin seat."""
    return await _auth_settings_response(seat_session, system_session, guild_id)


async def _auth_policy_response(
    system_session: AsyncSession, guild_id: int, *, guest: bool = False
) -> CommunityAuthPolicyRead:
    policy_row = await system_session.get(GuildAuthPolicy, guild_id)
    half = policy_row.half(guest) if policy_row is not None else None
    display_name = None
    if half is not None and half.provider_id is not None:
        provider = await system_session.get(AuthProvider, half.provider_id)
        display_name = provider.display_name if provider else None
    return _auth_policy_read(
        half,
        display_name,
        factor_required_by_platform=await _platform_asks_everyone(system_session),
    )


@router.patch("/{community_id}/auth-settings", response_model=CommunityAuthSettingsRead)
async def update_community_auth_settings(
    guild_id: CommunityIdPath,
    payload: CommunityAuthSettingsUpdate,
    seat_session: SeatWriteSessionDep,
    system_session: SystemSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> CommunityAuthSettingsRead:
    """Change what reaching this community asks of somebody, and what its
    notifications may leave the app carrying.

    These sit with the seat rather than with running the community: they say
    what may be used to reach it and what is done on its behalf. Tightening a
    rule needs the option it belongs to — ``providers`` for the sign-in
    requirement, ``restrictions`` for the rest; loosening one never does. A
    rule applies while the community holds that option.

    The sign-in requirement: ``open`` clears it. ``required`` names one of the
    community's own login-ready providers, asks for its own single sign-on, a
    second factor or a passkey, or several at once — and the account writing
    it must already meet it, which both proves a provider works end to end and
    keeps an admin from locking the community behind a sign-in they have not
    completed.

    The guests' requirement takes the same shapes and is asked of guests
    instead of the members' one. Its writer is not a guest, so is not asked
    to meet it.

    Nobody is signed out by a change. Existing API
    keys are left alone when keys are refused, so accepting them again
    restores them. Every notification answer only narrows what the deployment
    permits.
    """
    requirements = {"auth_policy", "guest_auth_policy"}
    changes: dict[str, object] = {
        key: value
        for key, value in payload.model_dump(exclude=requirements).items()
        if value is not None
        # ``null`` is an answer for the guests' limit: no limit of its own.
        or (key == "guest_max_days" and key in payload.model_fields_set)
    }
    for key in requirements:
        asked = getattr(payload, key)
        if asked is not None:
            changes[key] = (
                auth_posture.SignInRequirement(
                    "required", asked.provider_id, frozenset(asked.require_methods)
                )
                if asked.policy == "required"
                else auth_posture.SignInRequirement()
            )
    await auth_posture.change(
        auth_posture.RuleContext.community(
            seat_session, system_session, current_user, guild_id
        ),
        changes,
    )
    return await _auth_settings_response(seat_session, system_session, guild_id)


@router.delete(
    "/{community_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response
)
async def delete_community(
    guild_id: CommunityIdPath,
    _guild_context: SettingsSeatWriteContextDep,
    http_request: Request,
    request: CommunityDeletionRequest,
    session: SettingsRLSSessionDep,
    system_session: SystemSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    background_tasks: BackgroundTasks,
) -> Response:
    # The seat, not an ordinary admin. Deleting a community is the one action
    # an admin cannot undo and cannot be undone for them — only an operator
    # can, and only inside the retention window — so it sits with the seat
    # that is told about it and that a restore needs (``guild_has_seat``).
    guild = await guilds_service.get_guild(session, guild_id=guild_id)

    # Re-check the password, where the account holds one to re-check — the
    # same gate the account-deletion endpoint asks. An account that signs in
    # another way has none to supply, and answers with a recent sign-in and the
    # phrase. 400 not 401 so the SPA's axios interceptor doesn't treat a wrong
    # password as a session expiry and force-log-out the user
    # mid-confirmation.
    await require_password_or_recent_proof(
        http_request,
        system_session,
        current_user,
        request.password,
        detail=GuildMessages.INVALID_PASSWORD,
    )

    # The whole phrase is uppercased, including the name, so casing on
    # the guild name can't trip up the confirmation.
    expected = f"DELETE COMMUNITY {guild.name.upper()}"
    if request.confirmation_text != expected:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=GuildMessages.CONFIRMATION_MISMATCH,
        )

    # End the guild's plug-in access. The guild has withdrawn its authorization, so
    # each plug-in is told to let go now rather than at the end of the retention
    # window — a restored guild comes back with its plug-ins disconnected, and an
    # admin reconnects them.
    #
    # On the REQUEST session, which is the one that can reach these rows: they
    # live in the guild's own schema, and the grants that read and write them
    # belong to the guild role as the request path assumes it. The system
    # engine cannot stand in for it here.
    #
    # That makes this a separate transaction from the status write below, which
    # the guild role in turn cannot do (``app_guild_base`` holds UPDATE on the
    # identity columns a guild admin edits, and deliberately not on ``status``).
    # The connections go first: a guild left live with its integrations ended
    # is a thing its admin can see and put back. The plug-ins are told once
    # this commits.
    await plugin_connections_service.delete_guild_connections(session)
    await session.commit()

    # Move the guild to ``deleted`` and keep everything: the shared rows, the
    # guild_<id> schema and the stored blobs all stay, so a platform operator
    # can put the community back inside the retention window. Nothing is
    # destroyed until guild_purge runs, which is when the shared row, the
    # schema and the blobs go — the sequence this endpoint used to run inline.
    #
    # From here the guild is gone as far as everybody in it is concerned:
    # absent from their guild lists and refused on every path, admins included.
    # Locked and read again: the status may have moved since the access check,
    # and a community suspended in the meantime is the platform's now, not its
    # seat's to delete.
    guild_row = (
        await system_session.exec(
            select(Guild)
            .where(Guild.id == guild_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).one_or_none()
    if guild_row is None or guild_row.status not in LIVE_STATUS_VALUES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=GuildMessages.COMMUNITY_ACCESS_DENIED,
        )
    notice = await guilds_service.soft_delete_guild(
        system_session, guild_row, actor_user_id=current_user.id, via="admin"
    )
    await system_session.commit()
    # The receipt, once the deletion is a fact. Never allowed to fail it.
    await email_service.announce_community_deleted(system_session, notice)
    # See soft_delete_guild: these live on another connection, so they go after
    # the commit that made the deletion real. Billing and the community's
    # plug-ins keep their names for it until the purge, and billing is told to
    # go and read what happened to it.
    background_tasks.add_task(post_commit.settle, session)
    billing_ping.notify_lifecycle_changed(guild_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{community_id}/invites",
    response_model=CommunityInviteCreated,
    status_code=status.HTTP_201_CREATED,
)
async def create_community_invite(
    guild_id: CommunityIdPath,
    _guild_context: SettingsAdminWriteContextDep,
    invite_in: CommunityInviteCreate,
    session: SettingsRLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> CommunityInviteCreated:
    invite, code = await guilds_service.create_guild_invite(
        session,
        guild_id=guild_id,
        created_by=current_user.id,
        expires_at=invite_in.expires_at,
        max_uses=invite_in.max_uses,
        invitee_email=invite_in.invitee_email,
        guest_days=invite_in.guest_days,
        grants=invite_in.grants,
        actor_user_id=current_user.id,
    )
    await session.commit()
    return CommunityInviteCreated.model_validate(
        {
            **CommunityInviteRead.model_validate(invite).model_dump(),
            "code": code,
            "grants": invite_in.grants,
        }
    )


@router.delete(
    "/{community_id}/invites/{invite_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_community_invite(
    guild_id: CommunityIdPath,
    _guild_context: SettingsAdminWriteContextDep,
    invite_id: int,
    session: SettingsRLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Response:
    await guilds_service.delete_guild_invite(
        session,
        guild_id=guild_id,
        invite_id=invite_id,
        actor_user_id=current_user.id,
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/invite/accept", response_model=CommunityRead)
async def accept_invite(
    payload: CommunityInviteAcceptRequest,
    session: SystemSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> CommunityRead:
    """Accept a guild invite. Uses the system session because the user doesn't
    belong to the guild yet — the invite code is the authorization."""
    guild = await guilds_service.redeem_invite_for_user(
        session, code=payload.code, user=current_user
    )
    await session.commit()
    await post_commit.settle(session)
    membership = await guilds_service.get_membership(
        session, guild_id=guild.id, user_id=current_user.id
    )
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=GuildMessages.COMMUNITY_MEMBERSHIP_MISSING,
        )
    return await _guild_read(session, guild, membership=membership)


@router.patch(
    "/{community_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def update_community_membership(
    guild_id: CommunityIdPath,
    guild_context: SettingsAdminWriteContextDep,
    user_id: int,
    payload: CommunityMembershipUpdate,
    session: SystemSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Response:
    """Update a user's guild membership role. Guild admin only.

    Restrictions:
    - Cannot change your own role
    - Cannot demote the last guild admin
    """
    # Runs on the system engine (SystemSessionDep): the guild role holds no UPDATE
    # on guild_memberships, so a role change happens only here, after the
    # guild-admin check — never under a request-path role. See migration 0145.

    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=GuildMessages.CANNOT_CHANGE_OWN_ROLE,
        )

    # 'support' is a synthesized PAM identity, never a stored membership role.
    if payload.role == CommunityRole.support:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=GuildMessages.COMMUNITY_ROLE_NOT_ASSIGNABLE,
        )

    # The seat is passed on by whoever holds it, and by nobody below it. A
    # superadmin seats another — one by membership, or one holding the seat
    # through a settings grant, which is how a community whose only holder
    # cannot pass it on gets a new one. An ordinary admin may do neither,
    # which is the separation.
    if payload.role not in assignable_roles(guild_context.rung):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=GuildMessages.COMMUNITY_ROLE_NOT_ASSIGNABLE,
        )

    await guilds_service.lock_guild_seats(session, guild_id)
    target_membership = await guilds_service.get_membership(
        session, guild_id=guild_id, user_id=user_id, for_update=True
    )
    if target_membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=GuildMessages.USER_NOT_FOUND_IN_COMMUNITY,
        )
    # A guest's rung is set where guests are made; becoming a member is its
    # own step, which also ends the guest's time.
    if target_membership.guest_until is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=GuildMessages.COMMUNITY_ROLE_NOT_ASSIGNABLE,
        )

    # And taking the seat away is the same authority as giving it. Asked of the
    # *locked* row, so the role this decides on is the role as it stands now.
    if (
        target_membership.role == CommunityRole.superadmin
        and guild_context.rung != CommunityRole.superadmin
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=GuildMessages.COMMUNITY_ROLE_NOT_ASSIGNABLE,
        )

    # What a guild must keep is its seat. An ordinary admin is not counted:
    # every guild has a superadmin, and a superadmin is an admin, so "the last
    # admin" could only ever have been the seat — which the rule below holds.
    if (
        target_membership.role == CommunityRole.superadmin
        and payload.role != CommunityRole.superadmin
        and await guilds_service.must_keep_superadmin(
            session, guild_id=guild_id, user_id=user_id
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=GuildMessages.CANNOT_VACATE_LAST_SUPERADMIN,
        )

    previous_role = target_membership.role
    target_membership.role = payload.role
    session.add(target_membership)
    if CommunityRole.superadmin in (previous_role, payload.role):
        # The seat moving is its own event, apart from an ordinary role
        # change.
        await audit_service.record(
            session,
            event_type=AuditEventType.GUILD_SUPERADMIN_CHANGED,
            actor_user_id=current_user.id,
            target_user_id=user_id,
            guild_id=guild_id,
            target_type="guild",
            target_id=guild_id,
            detail={"from": previous_role.value, "to": payload.role.value},
        )
    elif previous_role != payload.role:
        await audit_service.record(
            session,
            event_type=AuditEventType.GUILD_MEMBER_ROLE_CHANGED,
            actor_user_id=current_user.id,
            target_user_id=user_id,
            guild_id=guild_id,
            target_type="guild",
            target_id=guild_id,
            detail={"from": previous_role.value, "to": payload.role.value},
        )
    # A promotion changes the guild role underneath initiative rows that already
    # exist; bring them up to the manager role an admin's row carries.
    guilds_service.align_admin_initiative_roles(
        session, guild_id=guild_id, user_id=user_id, role=payload.role
    )
    await session.commit()
    await post_commit.settle(session)
    # Guild-level access change (e.g. admin → member loses the guild-admin
    # bypass): re-check this user's live content streams now so the change takes
    # effect immediately, not on the next bounded re-auth tick.
    await content_sockets.revoke_user(guild_id, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch(
    "/{community_id}/guests/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def extend_community_guest(
    guild_id: CommunityIdPath,
    _guild_context: SettingsAdminWriteContextDep,
    user_id: int,
    payload: CommunityGuestExtend,
    session: SystemSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Response:
    """Set when a guest's time ends, ``days`` from now. On the system engine,
    as a role change is: the guild role holds no UPDATE on memberships."""
    await guilds_service.extend_guest(
        session,
        guild_id=guild_id,
        user_id=user_id,
        days=payload.days,
        actor_user_id=current_user.id,
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{community_id}/guests/{user_id}/member",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def make_community_guest_a_member(
    guild_id: CommunityIdPath,
    _guild_context: SettingsAdminWriteContextDep,
    user_id: int,
    session: SystemSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Response:
    """Make a guest a member. They take a seat, so the member cap applies."""
    await guilds_service.lock_guild_seats(session, guild_id)
    await guilds_service.make_guest_a_member(
        session, guild_id=guild_id, user_id=user_id, actor_user_id=current_user.id
    )
    await session.commit()
    await post_commit.settle(session)
    # Routed as a guest until now: their live streams re-check as a member.
    await content_sockets.revoke_user(guild_id, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/{community_id}/members/{user_id}/display-name",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def set_member_display_name(
    guild_id: CommunityIdPath,
    _guild_context: SettingsAdminWriteContextDep,
    user_id: int,
    payload: MemberDisplayNameUpdate,
    session: SystemSessionDep,
) -> Response:
    """Set what a member is called in this community, or clear it. Guild admin
    only, or a settings grant beside a read_write one.

    On the system engine, as a role change is: the guild role writes only the
    caller's own membership row."""
    if not await guilds_service.set_member_display_name(
        session,
        guild_id=guild_id,
        user_id=user_id,
        display_name=payload.display_name,
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=GuildMessages.USER_NOT_FOUND_IN_COMMUNITY,
        )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/{community_id}/members/{user_id}/api-access",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def set_member_api_access(
    guild_id: CommunityIdPath,
    _guild_context: SettingsSeatWriteContextDep,
    user_id: int,
    payload: MemberApiAccessUpdate,
    session: SystemSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Response:
    """Turn one member's personal API keys off or on for this community. The
    seat only.

    Turning them off needs the ``restrictions`` option, and applies while the
    community holds it; turning them back on never needs it. Keys the member
    already made are left alone either way: the gate refuses them here while
    access is off, and they reach the community again when it is turned back
    on.

    On the system engine, as a role change is: the guild role writes only the
    caller's own membership row."""
    if not payload.api_keys_allowed:
        await guild_entitlements.require_auth_option(
            session, guild_id, CommunityAuthOption.restrictions
        )
    membership = await guilds_service.get_membership(
        session, guild_id=guild_id, user_id=user_id, for_update=True
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=GuildMessages.USER_NOT_FOUND_IN_COMMUNITY,
        )
    if membership.api_keys_allowed == payload.api_keys_allowed:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    membership.api_keys_allowed = payload.api_keys_allowed
    session.add(membership)
    await audit_service.record(
        session,
        event_type=AuditEventType.GUILD_MEMBER_API_ACCESS_CHANGED,
        actor_user_id=current_user.id,
        target_user_id=user_id,
        guild_id=guild_id,
        target_type="guild",
        target_id=guild_id,
        detail={"api_keys_allowed": payload.api_keys_allowed},
    )
    await session.commit()
    # A stream opened with one of their keys is re-checked now rather than on
    # the next re-auth tick.
    await content_sockets.revoke_user(guild_id, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/{community_id}/membership/display-name",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def set_own_display_name(
    guild_id: CommunityIdPath,
    guild_context: SettingsContextDep,
    payload: MemberDisplayNameUpdate,
    session: SettingsRLSSessionDep,
) -> Response:
    """Set what the caller is called in this community, or clear it.

    Routed as the community's own configuration is, so a member keeps it while
    content is frozen and not while the community is in time out."""
    if guild_context.membership is None or not (
        await guilds_service.set_member_display_name(
            session,
            guild_id=guild_id,
            user_id=guild_context.membership.user_id,
            display_name=payload.display_name,
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=GuildMessages.NOT_COMMUNITY_MEMBER,
        )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{community_id}/leave/eligibility",
    response_model=LeaveCommunityEligibilityResponse,
)
async def check_leave_eligibility(
    guild_id: CommunityIdPath,
    session: UserSessionDep,
    system_session: SystemSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> LeaveCommunityEligibilityResponse:
    """Check if the current user can leave a guild.

    Holding its only superadmin seat is the one thing that stops them. Content
    they own is released on the way out and left unowned for a guild admin to
    claim, so there is nothing to hand over first.
    """
    membership = await guilds_service.get_membership(
        session, guild_id=guild_id, user_id=current_user.id
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=GuildMessages.NOT_COMMUNITY_MEMBER,
        )

    # Under the lock, so the answer still holds when the caller acts on it.
    # Counting a guild's seats is a question about the guild rather than about
    # the caller, so it is asked on the system engine.
    await guilds_service.lock_guild_seats(system_session, guild_id)
    is_last_superadmin = await guilds_service.would_strand_guild(
        system_session, guild_id=guild_id, user_id=current_user.id
    )

    return LeaveCommunityEligibilityResponse(
        can_leave=not is_last_superadmin,
        is_last_superadmin=is_last_superadmin,
    )


@router.delete(
    "/{community_id}/leave",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def leave_community(
    guild_id: CommunityIdPath,
    session: UserSessionDep,
    system_session: SystemSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Response:
    """Leave a guild.

    Being the guild's last admin is the only restriction. Content the leaver
    owns is released — left unowned for a guild admin to claim — rather than
    handed to someone who did not ask for it.
    """
    membership = await guilds_service.get_membership(
        session, guild_id=guild_id, user_id=current_user.id
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=GuildMessages.NOT_COMMUNITY_MEMBER,
        )

    # ``UserSessionDep`` only sets the user_id; releasing the leaver's owner
    # grants below writes to guild-scoped tables whose RLS is evaluated against
    # the current guild context. Now that membership is confirmed, set the full
    # context so those writes aren't filtered to zero rows. Leaving is about
    # the membership row rather than the community's content, so it routes the
    # way its configuration surface does — and, like that surface, not while
    # the community is suspended: its membership stays as it was until then.
    try:
        await establish_guild_access(session, current_user, guild_id, for_settings=True)
    except GuildAccessError as exc:
        raise_for_guild_access(exc)

    # Ahead of the check below, so its answer is still true when the departure
    # is written. Counting a guild's seats is a question about the guild rather
    # than about the caller, so it is asked on the system engine.
    await guilds_service.lock_guild_seats(system_session, guild_id)

    # The seat is what a guild has to keep. An ordinary admin may leave freely:
    # every guild has a superadmin, so the community is never left without one.
    # And the only member of a community may leave whatever they hold — there
    # is nobody there to strand.
    if await guilds_service.would_strand_guild(
        system_session, guild_id=guild_id, user_id=current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=GuildMessages.CANNOT_VACATE_LAST_SUPERADMIN,
        )

    if membership.guest_until is not None:
        # A guest's own role changes none of what leaving takes away, so their
        # departure runs as the expiry sweep runs it, on the community's
        # cohort, recorded as theirs.
        async with cohorts.system_session(guild_id) as guild_session:
            await set_rls_context(guild_session, SystemGuild(guild_id))
            await guilds_service.remove_user_from_guild(
                guild_session,
                guild_id=guild_id,
                user_id=current_user.id,
                actor_user_id=current_user.id,
            )
            await guild_session.commit()
        await content_sockets.revoke_user(guild_id, current_user.id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    # Ownership release happens inside remove_user_from_guild, while the
    # leaver's membership rows are still in place for RLS to match.
    await guilds_service.remove_user_from_guild(
        session,
        guild_id=guild_id,
        user_id=current_user.id,
        actor_user_id=current_user.id,
    )

    await session.commit()
    # Left the guild — drop this user's live content streams immediately.
    await content_sockets.revoke_user(guild_id, current_user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
