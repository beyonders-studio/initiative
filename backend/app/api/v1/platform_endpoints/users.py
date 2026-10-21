import logging
from datetime import datetime, timezone
from typing import Annotated, List, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import JSONResponse
from sqlalchemy import case, func, literal
from sqlmodel import select

from app.api.actor_route import ActorRoute
from app.api.deps import (
    NotDemoSample,
    refuse_demo_sample,
    ActorContext,
    ActorSessionDep,
    plugin_scope,
    FactorExemptAccountHolder,
    FactorExemptAccountHolderSessionDep,
    RLSSessionDep,
    SettingsContextDep,
    SettingsRLSSessionDep,
    SessionDep,
    UserSessionDep,
    get_current_active_user,
    holds_guild_role,
    require_first_party_session,
    SystemSessionDep,
    GuildAdminContext,
    GuildContextDep,
)
from app.api.v1.platform_endpoints.password_recheck import (
    require_password_or_recent_proof,
)
from app.api.v1.platform_endpoints.change_assessment import is_risky
from app.api.v1.platform_endpoints.held_changes import (
    HELD,
    HELD_OUTCOME,
    held_response,
    hold_change,
)
from app.api.v1.platform_endpoints.session_opening import set_password
from app.core.capabilities import Capability
from app.core.password_policy import validate_new_password
from app.core.identity_boundary import PersonId
from app.core.user_display import handle_of
from app.db import cohorts
from app.db.guild_standing import InstallContext
from app.core import usernames
from app.core.rate_limit import limiter
from app.core.security import read_handle_offer
from app.core.user_input_validators import (
    normalize_reminder_minutes,
    normalize_timezone,
    normalize_time_format,
    normalize_week_starts_on,
)
from sqlmodel.ext.asyncio.session import AsyncSession
from app.models.platform.guild import (
    GUILD_ADMIN_ROLES,
    GuildMembership,
    CommunityRole,
)
from app.models.platform.guild_image import GuildImageVariant
from app.core.intake import IntakeStream
from app.models.platform.user import Presence, User, UserStatus
from app.models.tenant.initiative import InitiativeMember
from app.services.platform import intake as intake_service
from app.models.platform.user_cookie_consent import UserCookieConsent
from app.schemas.platform.guild import (
    DirectoryCommunityRead,
    CommunityBannerRead,
    CommunityCategory,
)
from app.schemas.platform.user import (
    HeldChangeOutcome,
    AccountTimeOutRead,
    CookieConsentRead,
    CookieConsentUpdate,
    UserEmailChange,
    UserEmailCreate,
    UserEmailListResponse,
    UserEmailRead,
    AgeConfirmation,
    DecorationPack,
    DecorationPackListResponse,
    OwnedDecoration,
    OwnedDecorationsResponse,
    ProfileDecorations,
    UsernameClaim,
    CommunityRosterMember,
    CommunityRosterResponse,
    UserCommunityMember,
    UserCommunityMemberListResponse,
    UserProfile,
    UserRead,
    UserSelfUpdate,
    UserSummary,
    UserSummaryListResponse,
    AccountDeletionRequest,
    AccountDeletionResponse,
    DeletionEligibilityResponse,
)
from app.schemas.platform.api_key import (
    ApiKeyCreateRequest,
    ApiKeyCreateResponse,
    ApiKeyListResponse,
)
from app.schemas.tenant.ownership import (
    OwnedContentItem,
    OwnedContentResponse,
    OwnerPluginSummary,
    OwnershipTransferRequest,
    OwnershipTransferResponse,
)
from app.schemas.tenant.stats import UserStatsResponse
from app.core.encryption import SALT_EMAIL, decrypt_field
from app.core.messages import (
    AuthMessages,
    GuildMessages,
    ImageMessages,
    InitiativeMessages,
    LegalMessages,
    UserMessages,
)
from app.models.platform.account_change_hold import HeldChangeKind
from app.services.auth import addresses, held_changes

from app.core.audit_events import AuditEventType
from app.services import audit as audit_service
from app.services import sweep_timers
from app.services.cross_guild import member_guild_ids
from app.core.tools import Tool
from app.api import resource_access
from app.services.tenant import initiatives as initiatives_service
from app.services.tenant import named_people
from app.services.tenant import ownership as ownership_service
from app.services.platform import cookie_consent as cookie_consent_service
from app.services.platform import guild_entitlements
from app.services.platform import guilds as guilds_service
from app.services.platform import guild_images as images_service
from app.services.platform import legal as legal_service
from app.services.content_sockets import sockets as content_sockets
from app.services.platform import presence
from app.services.platform import usernames as username_service
from app.models.platform.user_avatar import AVATAR_SPEC
from app.services.tenant.attachments import FileTooLargeError, read_upload_bounded
from app.models.platform.user_profile_view import (
    GuildMember,
    MemberProfile,
    user_profiles,
)
from app.services.platform import user_avatars as user_avatars_service
from app.services.platform import profile_decorations as profile_decorations_service
from app.services.platform import users as users_service
from app.services.platform import api_keys as api_keys_service
from app.services.tenant.plugin_age import request_country
from app.services.platform import csv_export
from app.services.tenant import stats_service
from app.models.platform.user_token import UserTokenPurpose
from app.schemas.platform.auth import VerificationSendResponse
from app.services import email as email_service
from app.services.platform import app_settings as app_settings_service
from app.services.platform import auth_posture
from app.services.platform import user_tokens as user_tokens_service
from app.services.tenant import personal_items as personal_items_service
from app.db.query import (
    MAX_ID_FILTER_VALUES,
    apply_pagination,
    build_paginated_response,
    ids_in,
    paginated_query,
)

# Allowed values for the optional "task completion visual feedback" effect.
# Mirrored on the frontend in src/lib/taskCompletionVisualFeedback.ts; keep
# the two lists in sync if you add a new effect.
TASK_COMPLETION_VISUAL_FEEDBACK_VALUES: frozenset[str] = frozenset(
    {"none", "confetti", "heart", "d20", "gold_coin", "random"}
)

logger = logging.getLogger(__name__)

# Other people's public profiles. Mounted under /api/v1/users.
router = APIRouter()
# The signed-in account: its profile, settings and stats. Mounted under
# /api/v1/me; user-scoped (no guild context).
me_router = APIRouter()
# Guild-scoped member management (guild-admin lists/creates/approves/removes
# members of one guild). Mounted under /c/{community_id}/users. The member
# search is also what an installed plug-in reads people through, under
# ``members:read``.
guild_router = APIRouter(route_class=ActorRoute)
# A member's picture, by the reference an installed plug-in knows them by. Mounted
# under /c/{community_id}/members.
members_router = APIRouter(route_class=ActorRoute)

MembersRead = Annotated[ActorContext, Depends(plugin_scope("members:read"))]


@me_router.get("/time-out", response_model=AccountTimeOutRead)
async def read_my_time_out(
    session: FactorExemptAccountHolderSessionDep,
    current_user: FactorExemptAccountHolder,
) -> AccountTimeOutRead:
    """What a suspended account is told on its time-out screen: why, where a
    reason was given, whom to contact, and whether it can appeal here — with
    the appeal it already made, which it follows on the same screen.

    Answers for an active account too — nobody to contact, since there is
    nothing to lift — so the screen can ask without first knowing the status.
    """
    from app.core.intake import APPEAL
    from app.services.platform import tickets as tickets_service

    if current_user.status != UserStatus.suspended:
        return AccountTimeOutRead()
    appeals = [
        ticket
        for ticket in await tickets_service.list_filed(current_user)
        if ticket.stream is IntakeStream.moderation and ticket.topic == APPEAL
    ]
    latest = max(appeals, key=lambda ticket: ticket.opened_at, default=None)
    return AccountTimeOutRead(
        contact_email=await intake_service.contact_for(
            session, IntakeStream.moderation
        ),
        since=current_user.status_changed_at,
        reason=current_user.status_reason,
        can_appeal=await intake_service.stream_is_bound(IntakeStream.moderation),
        appeal_task_id=latest.task_id if latest is not None else None,
    )


@me_router.get("", response_model=UserRead)
async def read_me(
    session: FactorExemptAccountHolderSessionDep,
    current_user: FactorExemptAccountHolder,
) -> UserRead:
    """Who you are. Reachable while the deployment's second-factor rule is
    unmet, because every screen that could answer it is drawn from this."""
    # No initiative_roles enrichment: initiative membership is guild-schema
    # content, which a platform-path request cannot (and must not) read.
    # Guild-scoped rosters (/c/{community_id}/users/) still serve it; clients
    # derive per-guild manager state from guild-scoped initiative data.
    payload = await users_service.to_self_read(session, current_user)
    # The hosted deployment's terms. Short-circuits on the deployment switch
    # for every self-hoster, and costs one indexed count everywhere else.
    payload.legal_acceptance_required = await legal_service.acceptance_outstanding(
        session, user=current_user
    )
    # Own-row read on the routed session. Null where this account has never
    # answered, which is what lets a browser tell "never asked" from "asked,
    # and allowed nothing".
    payload.cookie_consent = _cookie_consent_read(
        await cookie_consent_service.get_consent(session, user_id=current_user.id)
    )
    return payload


@me_router.get("/stats", response_model=UserStatsResponse)
async def get_user_stats(
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_id: Optional[int] = Query(
        default=None,
        description="Optional guild ID to filter stats",
        alias="community_id",
    ),
    days: int = Query(
        default=90, ge=1, le=365, description="Number of days to analyze"
    ),
) -> UserStatsResponse:
    """Get comprehensive statistics for the current user."""
    stats = await stats_service.get_user_stats(
        session,
        user=current_user,
        guild_id=guild_id,
        days=days,
    )
    return stats


@guild_router.get("/", response_model=UserCommunityMemberListResponse)
async def list_users(
    session: SettingsRLSSessionDep,
    _current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: SettingsContextDep,
    search: Optional[str] = Query(
        default=None,
        description=(
            "Matches members the way ``/search`` does: the handle, a whole "
            "handle pinning one member, and the display names members set "
            "here."
        ),
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    guests: bool = Query(
        default=False,
        description="The community's guests instead of its members. For its "
        "administrators.",
    ),
) -> UserCommunityMemberListResponse:
    """The community's roster, a page at a time.

    On the configuration session rather than the content one: who is in a
    community is part of running it, which is what a settings grant reaches
    and what an administrator keeps while its content is closed.

    Ordered like ``/search``: nearest first while searching, otherwise by name
    where the guild shows names, then by handle.
    """
    if guests and not holds_guild_role(
        guild_context, CommunityRole.admin, settings=True
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=GuildMessages.COMMUNITY_ADMIN_REQUIRED,
        )
    narrow = users_service.guild_guests if guests else users_service.guild_members
    base = narrow(
        select(
            MemberProfile,
            GuildMembership.role,
            GuildMembership.oidc_provider_id,
            GuildMembership.display_name,
            GuildMembership.api_keys_allowed,
            GuildMembership.guest_until,
        ),
        guild_id=guild_context.guild_id,
    )
    closest = None
    if search and (term := search.strip()):
        matches, closest = users_service.member_match(term)
        base = base.where(matches)

    count_stmt = select(func.count()).select_from(base.subquery())
    data_stmt = base.order_by(
        *users_service.member_order(closest),
        MemberProfile.username.asc(),
        MemberProfile.discriminator.asc(),
        MemberProfile.id.asc(),
    )
    rows, total_count, actual_page = await paginated_query(
        session, data_stmt, count_stmt, page=page, page_size=page_size
    )
    users = [row[0] for row in rows]
    await initiatives_service.load_user_initiative_roles(session, users)

    # ``oidc_managed`` stays a yes/no on the wire: a roster wants to know that
    # SSO placed somebody, not which provider did. API access is the seat's to
    # set, so only the seat is told it.
    seat = guild_context.guild_seat
    items = []
    for (
        user,
        guild_role,
        oidc_provider_id,
        display_name,
        api_keys_allowed,
        guest_until,
    ) in rows:
        member = UserCommunityMember.model_validate(user)
        member.guest_until = guest_until
        member.community_role = guild_role.value
        member.oidc_managed = oidc_provider_id is not None
        member.display_name = display_name
        member.api_keys_allowed = api_keys_allowed if seat else None
        member.initiative_roles = getattr(user, "initiative_roles", [])
        items.append(member)
    return UserCommunityMemberListResponse(
        **build_paginated_response(items, total_count, actual_page, page_size)
    )


def _in_initiative(initiative_id: int):
    """Members of one initiative, as a filter on ``MemberProfile``."""
    return MemberProfile.id.in_(
        select(InitiativeMember.user_id).where(
            InitiativeMember.initiative_id == initiative_id
        )
    )


async def _search_members_for_plugin(
    session: AsyncSession,
    *,
    search: Optional[str],
    user_id: Optional[list[int]],
    initiative_id: Optional[int],
    page: int,
    page_size: int,
) -> UserSummaryListResponse:
    """The member search, for an installed plug-in.

    Read through ``current_guild_members``, the projection of the routed
    community's own members, so it needs nothing of the membership table. The
    handle is what it matches and orders by: whether the guild shows real
    names is the guild row's to say, which a plug-in does not read; a name the
    guild shows still comes back on each row.
    """
    base = select(MemberProfile).where(
        MemberProfile.id.in_(select(GuildMember.id)),
        users_service.visible_to_other_people(),
    )
    if initiative_id is not None:
        base = base.where(_in_initiative(initiative_id))
    closest = None
    if search and (term := search.strip()):
        matches, closest = users_service.member_match(term, match_names=False)
        base = base.where(matches)
    if user_id:
        base = base.where(MemberProfile.id.in_(user_id))

    count_stmt = select(func.count()).select_from(base.subquery())
    data_stmt = base.order_by(
        *users_service.member_order(closest, match_names=False),
        MemberProfile.username.asc(),
        MemberProfile.discriminator.asc(),
        MemberProfile.id.asc(),
    )
    users, total_count, actual_page = await paginated_query(
        session, data_stmt, count_stmt, page=page, page_size=page_size
    )
    items = [UserSummary.model_validate(user) for user in users]
    return UserSummaryListResponse(
        **build_paginated_response(items, total_count, actual_page, page_size)
    )


def _membership_standing(role: CommunityRole | None) -> dict[str, object]:
    """The membership field a picker row carries: the rung, which is both what
    a row shows and what a surface asks the ladder about."""
    return {"community_role": role.value if role is not None else None}


@guild_router.get("/search", response_model=UserSummaryListResponse)
async def search_users(
    session: ActorSessionDep,
    guild_context: MembersRead,
    search: Optional[str] = Query(
        default=None,
        description=(
            "Matches the handle's name part. Type the whole handle "
            "(`foobar#1234`) to pin one member; a partial number after `#` is a "
            "prefix of the four digits as rendered. Display names members set "
            "here are matched too."
        ),
    ),
    user_id: Annotated[
        list[PersonId] | None, Query(max_length=MAX_ID_FILTER_VALUES)
    ] = None,
    initiative_id: Optional[int] = Query(
        default=None,
        description=(
            "Only members of this initiative. The caller must reach it: be in "
            "it, administer the community, or (a plug-in) be placed there."
        ),
    ),
    tool: Optional[Tool] = Query(
        default=None,
        description=(
            "With ``resource_id``: only the people who can open that row, which "
            "is who may be named on content inside it (assignees, attendees, "
            "person properties). The caller must be able to open it too. For a "
            "person's picker; an installed plug-in's search does not take it."
        ),
    ),
    resource_id: Optional[int] = Query(default=None),
    self_first: bool = Query(
        default=False,
        description=(
            "List the caller first, wherever the rest of the order would put "
            "them. For the community's members page, where your own row is "
            "where you set your name."
        ),
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=0, le=100),
) -> UserSummaryListResponse:
    """Slim, searchable, paginated roster for typeahead/pickers.

    Same authorization as the full member list (``RLSSessionDep`` +
    ``GuildContextDep``, membership re-validated per request): the params
    are additive filters on an already-RLS-gated query, so they only ever
    narrow the row set. Returns :class:`UserSummary` (no email, roles, or
    ``initiative_roles`` enrichment) instead of the heavy ``UserCommunityMember``.

    Pass ``user_id`` one or more times to resolve a known selection (a picker
    rehydrating stored ids into names/avatars) rather than searching.

    An installed plug-in (``members:read``) names members by its own references
    and reads each as an :class:`PluginPerson`: the reference, the handle and the
    display name set in the community.
    """
    if initiative_id is not None and not (
        initiative_id in guild_context.member_initiatives
        or (
            not isinstance(guild_context, InstallContext)
            and (guild_context.is_admin or guild_context.is_pam)
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=InitiativeMessages.NOT_A_MEMBER,
        )
    if isinstance(guild_context, InstallContext):
        return await _search_members_for_plugin(
            session,
            search=search,
            user_id=user_id,
            initiative_id=initiative_id,
            page=page,
            page_size=page_size,
        )
    # Scoped to content, or naming people already chosen, the picker lists the
    # community's guests too; across the whole community it is the roster.
    scoped = (
        initiative_id is not None
        or bool(user_id)
        or (tool is not None and resource_id is not None)
    )
    base = users_service.guild_members(
        select(MemberProfile), guild_id=guild_context.guild_id, guests=scoped
    )
    if initiative_id is not None:
        base = base.where(_in_initiative(initiative_id))
    if tool is not None and resource_id is not None:
        row = await resource_access.load_authorized(
            session, tool, resource_id, None, guild_context
        )
        base = base.where(
            MemberProfile.id.in_(
                named_people.readers_of(
                    named_people.Governing.of(tool, row), guild_context.guild_id
                )
            )
        )
    #: Set while searching by name, and then what the page is ordered by.
    closest = None
    if search and (term := search.strip()):
        matches, closest = users_service.member_match(term)
        base = base.where(matches)
    if user_id:
        base = base.where(MemberProfile.id.in_(user_id))

    count_stmt = select(func.count()).select_from(base.subquery())
    you_first = (
        ((MemberProfile.id == guild_context.user_id).desc(),) if self_first else ()
    )
    data_stmt = base.order_by(
        *you_first,
        *users_service.member_order(closest),
        MemberProfile.username.asc(),
        MemberProfile.discriminator.asc(),
        MemberProfile.id.asc(),
    )

    users, total_count, actual_page = await paginated_query(
        session, data_stmt, count_stmt, page=page, page_size=page_size
    )

    # One extra read for the page just fetched, bounded by ``page_size``: the
    # roster join above filters by guild rather than projecting from it, and
    # widening that projection would change what ``paginated_query`` returns.
    roles = (
        dict(
            (
                await session.exec(
                    select(GuildMembership.user_id, GuildMembership.role).where(
                        GuildMembership.guild_id == guild_context.guild_id,
                        GuildMembership.user_id.in_([user.id for user in users]),
                    )
                )
            ).all()
        )
        if users
        else {}
    )

    items = [
        UserSummary.model_validate(user).model_copy(
            update=_membership_standing(roles.get(user.id))
        )
        for user in users
    ]
    return UserSummaryListResponse(
        **build_paginated_response(items, total_count, actual_page, page_size)
    )


#: The roster's groups, in the order they are listed.
ROSTER_PRESENCE_ORDER = (
    Presence.online,
    Presence.idle,
    Presence.busy,
    Presence.offline,
)


@guild_router.get("/roster", response_model=CommunityRosterResponse)
async def list_roster(
    session: RLSSessionDep,
    guild_context: GuildContextDep,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
) -> CommunityRosterResponse:
    """The people in this community, as the sidebar lists them.

    Grouped by presence (online, idle, busy, then everyone else) and
    alphabetical within a group. ``presence_counts`` sizes each group across
    every page.

    Nobody whose direct message policy is private is listed, the reader
    included. Where the deployment offers no direct messages there is no policy
    to keep, and everyone is listed.
    """
    shown = presence.online.shown()
    ranked = [
        (ids_in(MemberProfile.id, ids), rank)
        for rank, appears in enumerate(ROSTER_PRESENCE_ORDER)
        if (ids := [user_id for user_id, p in shown.items() if p is appears])
    ]
    offline_rank = ROSTER_PRESENCE_ORDER.index(Presence.offline)
    group = case(*ranked, else_=offline_rank) if ranked else literal(offline_rank)

    where = []
    if await app_settings_service.direct_messages_enabled(session):
        where.append(MemberProfile.id.in_(select(func.public.roster_listed_members())))

    groups = (
        users_service.guild_members(
            select(group.label("presence_rank")).select_from(MemberProfile),
            guild_id=guild_context.guild_id,
        )
        .where(*where)
        .subquery()
    )
    counts = dict(
        (
            await session.exec(
                select(groups.c.presence_rank, func.count()).group_by(
                    groups.c.presence_rank
                )
            )
        ).all()
    )
    presence_counts = {
        appears: counts.get(rank, 0)
        for rank, appears in enumerate(ROSTER_PRESENCE_ORDER)
    }

    rows = (
        await session.exec(
            apply_pagination(
                users_service.guild_members(
                    select(MemberProfile, GuildMembership.role),
                    guild_id=guild_context.guild_id,
                )
                .where(*where)
                .order_by(
                    group,
                    *users_service.member_order(None),
                    MemberProfile.username.asc(),
                    MemberProfile.discriminator.asc(),
                    MemberProfile.id.asc(),
                ),
                page,
                page_size,
            )
        )
    ).all()

    items = [
        CommunityRosterMember.model_validate(user).model_copy(
            update={
                **_membership_standing(role),
                "presence": shown.get(user.id, Presence.offline),
            }
        )
        for user, role in rows
    ]
    return CommunityRosterResponse(
        **build_paginated_response(
            items,
            sum(presence_counts.values()),
            page,
            page_size,
            presence_counts=presence_counts,
        )
    )


@me_router.get("/decorations", response_model=OwnedDecorationsResponse)
async def list_my_decorations(
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> OwnedDecorationsResponse:
    """Everything the caller may dress their profile in.

    What ships with the app plus what this account acquired, which is what the
    pickers on Settings > Profile offer and exactly what the write path
    accepts. Own-row: ``public.user_decorations`` is readable only by the
    account whose library it is.
    """
    return OwnedDecorationsResponse(
        items=await profile_decorations_service.owned_decorations(
            session, current_user.id
        )
    )


async def _pack_or_404(
    session: AsyncSession, uid: str
) -> profile_decorations_service.Pack:
    pack = await profile_decorations_service.pack_by_uid(session, uid)
    if pack is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=UserMessages.DECORATION_PACK_NOT_FOUND,
        )
    return pack


def _pack_entry(
    pack: profile_decorations_service.Pack, *, installed: bool
) -> DecorationPack:
    listing = pack.listing
    return DecorationPack(
        uid=listing.uid,
        public_id=listing.public_id,
        name=listing.name,
        publisher=listing.publisher,
        description=listing.description,
        avatar_url=listing.avatar_url,
        contents=[
            OwnedDecoration(
                id=decoration_id,
                kind=kind,
                name=None,
                source=listing.uid,
                image_url=pack.images.get(decoration_id),
            )
            for decoration_id, kind in pack.decorations.items()
        ],
        installed=installed,
    )


@me_router.get("/decoration-packs", response_model=DecorationPackListResponse)
async def list_decoration_packs(
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> DecorationPackListResponse:
    """The store: every profile pack this deployment offers, and which you have.

    The shelf is the marketplace catalog, so a pack that ships with the build
    and one published to it read the same here.
    """
    installed = await profile_decorations_service.installed_pack_ids(
        session, current_user.id
    )
    packs = await profile_decorations_service.available_packs(session)
    return DecorationPackListResponse(
        items=[_pack_entry(pack, installed=pack.uid in installed) for pack in packs]
    )


@me_router.post("/decoration-packs/{uid}", response_model=DecorationPack)
async def install_decoration_pack(
    uid: str,
    session: UserSessionDep,
    system_session: SystemSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> DecorationPack:
    """Take a pack, putting its decorations in your library.

    The catalog is read on the request path; the grant is written on the system
    engine, because a grant is issued rather than self-served — the request path
    holds no write verb on ``public.user_decorations``. What makes it the
    caller's own is that the only account it ever names is theirs.
    """
    pack = await _pack_or_404(session, uid)
    conflicting = await profile_decorations_service.install_pack(
        system_session, user_id=current_user.id, pack=pack
    )
    if conflicting:
        # Another pack already gave this library one of these ids. A decoration
        # id names one thing, so the row belongs to whoever granted it first
        # and this install would have been a partial one reported as whole.
        await system_session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=UserMessages.DECORATION_ALREADY_GRANTED,
        )
    await system_session.commit()
    return _pack_entry(pack, installed=True)


@me_router.delete("/decoration-packs/{uid}", response_model=DecorationPack)
async def remove_decoration_pack(
    uid: str,
    session: UserSessionDep,
    system_session: SystemSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> DecorationPack:
    """Give a pack back, taking its decorations out of your library.

    Anything from it that was being worn comes off in the same transaction —
    a profile must not be left wearing what the account no longer has, and
    two commits would leave a window where it was.
    """
    pack = await _pack_or_404(session, uid)
    await profile_decorations_service.remove_pack(
        system_session, user_id=current_user.id, pack=pack
    )
    await system_session.commit()
    return _pack_entry(pack, installed=False)


@router.get("/{handle}/profile", response_model=UserProfile)
async def read_user_profile(
    handle: str,
    session: UserSessionDep,
    _current_user: Annotated[User, Depends(get_current_active_user)],
) -> UserProfile:
    """One person's profile, addressed by their handle.

    ``jordan1234`` — the name and the number it is always written with, run
    together. ``#`` never survives a URL, and the number's four digits are
    fixed width, so the two come apart again exactly.

    A profile is public and has no guild in it: it carries the handle, the
    face, the status, the look and how they appear, and it is the same page
    whoever opens it. That is why it is not reached through a guild — no
    part of the answer depends on one.

    Read from ``public.user_profiles``, the view that *is* the public
    projection: which columns are public is decided by the view and the column
    grant behind it (migration 0214), not here. An ordinary platform-tier
    session, RLS enforced. A suspended account has no profile.
    """
    parsed = usernames.parse_url_handle(handle)
    if parsed is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=AuthMessages.USER_NOT_FOUND,
        )
    name, discriminator = parsed
    # Named one by one rather than as the whole view: a single-entity select
    # comes back scalarized to its first column.
    stmt = select(
        user_profiles.c.id,
        user_profiles.c.username,
        user_profiles.c.discriminator,
        user_profiles.c.avatar_url,
        user_profiles.c.status,
        user_profiles.c.custom_status,
        user_profiles.c.profile_decorations,
        user_profiles.c.created_at,
    ).where(
        func.lower(user_profiles.c.username) == name,
        user_profiles.c.discriminator == discriminator,
        users_service.visible_to_other_people(user_profiles.c.status),
    )
    row = (await session.exec(stmt)).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=AuthMessages.USER_NOT_FOUND,
        )
    return UserProfile(
        id=row.id,
        username=row.username,
        discriminator=row.discriminator,
        avatar_url=row.avatar_url,
        status=row.status,
        custom_status=row.custom_status or {},
        profile_decorations=row.profile_decorations or {},
        presence=presence.online.presence_of(row.id),
        joined_at=row.created_at,
    )


@router.get("/{handle}/communities", response_model=List[DirectoryCommunityRead])
async def read_user_communities(
    handle: str,
    system_session: SystemSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> List[DirectoryCommunityRead]:
    """The listed communities one person belongs to.

    A separate read from the profile on purpose: the profile is the public
    projection of ``public.users`` and this is not about that row at all. It
    also cannot run on the same session — ``guild_memberships`` is scoped to
    the caller's own rows on the request path, and the question is about
    somebody else — so it takes the system engine, exactly as the directory
    does, with the same service-side filters deciding what may appear.

    Only guilds that opted into the directory. One someone is in that did not
    is nobody else's business, and does not appear here for anyone.
    """
    parsed = usernames.parse_url_handle(handle)
    if parsed is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=AuthMessages.USER_NOT_FOUND,
        )
    name, discriminator = parsed
    subject = (
        await system_session.exec(
            select(User).where(
                func.lower(User.username) == name,
                User.discriminator == discriminator,
                users_service.visible_to_other_people(User.status),
            )
        )
    ).first()
    if subject is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=AuthMessages.USER_NOT_FOUND,
        )

    guilds = await guilds_service.list_profile_communities(
        system_session, user_id=subject.id
    )
    mine = {
        row.guild_id
        for row in (
            await system_session.exec(
                select(GuildMembership).where(
                    GuildMembership.user_id == current_user.id
                )
            )
        ).all()
    }
    online = content_sockets.present_counts(guild.id for guild in guilds)
    # How many people are in each, which the card names and this read has to
    # ask for: nothing about a guild row carries it.
    members = await guilds_service.count_members_by_guild(
        system_session, guild_ids=[guild.id for guild in guilds]
    )
    # Digests only, in one query: a card names its pictures, never carries them.
    images = await images_service.image_urls(
        system_session,
        [guild.id for guild in guilds],
        GuildImageVariant.icon,
        GuildImageVariant.card,
    )
    return [
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
            member_count=members.get(guild.id, 0),
            online_count=online.get(guild.id, 0),
            already_member=guild.id in mine,
        )
        for guild in guilds
    ]


#: A guild exports what it knows about its own members. An account's platform
#: tier and whether it has confirmed its address are the platform's business,
#: not a guild's, so neither is a column here.
_GUILD_CSV_HEADERS = [
    "user_id",
    "handle",
    "display_name",
    "community_role",
    "oidc_managed",
    "status",
    "created_at",
    "initiative_roles",
]


@guild_router.get("/export.csv")
async def export_users_csv(
    session: RLSSessionDep,
    guild_context: GuildAdminContext,
    user_id: Annotated[list[int] | None, Query()] = None,
) -> Response:
    """Export guild members as a CSV file. Pass `user_id` one or more times to
    restrict the export to a subset. Without `user_id`, all visible members are
    included. Guild-admin only."""
    stmt = users_service.guild_members(
        select(MemberProfile, GuildMembership.role, GuildMembership.oidc_provider_id),
        guild_id=guild_context.guild_id,
    ).order_by(MemberProfile.created_at.asc())
    if user_id:
        stmt = stmt.where(MemberProfile.id.in_(user_id))
    result = await session.exec(stmt)
    rows = result.all()

    if user_id and not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=AuthMessages.USER_NOT_FOUND
        )

    users = [row[0] for row in rows]
    await initiatives_service.load_user_initiative_roles(session, users)

    csv_rows = []
    for user, guild_role, oidc_provider_id in rows:
        csv_rows.append(
            [
                user.id,
                handle_of(user),
                user.display_name or "",
                guild_role.value,
                oidc_provider_id is not None,
                user.status.value if hasattr(user.status, "value") else user.status,
                user.created_at.isoformat() if user.created_at else "",
                csv_export.format_initiative_roles(user),
            ]
        )

    csv_bytes = csv_export.build_csv(_GUILD_CSV_HEADERS, csv_rows)

    # Nothing changed, so the endpoint has no commit of its own to ride: the
    # record is the whole write.
    await audit_service.record(
        session,
        event_type=AuditEventType.GUILD_MEMBERS_EXPORTED,
        actor_user_id=guild_context.membership.user_id,
        guild_id=guild_context.guild_id,
        target_type="guild",
        target_id=guild_context.guild_id,
        detail={"count": len(rows)},
    )
    await session.commit()

    if len(rows) == 1 and user_id:
        single_user = rows[0][0]
        filename = (
            f"user-{single_user.id}-"
            f"{csv_export.safe_filename_component(single_user.username)}.csv"
        )
    else:
        guild_slug = csv_export.safe_filename_component(
            guild_context.guild.name or "guild"
        )
        datestamp = datetime.now(timezone.utc).date().isoformat()
        filename = f"{guild_slug}-users-{datestamp}.csv"

    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@me_router.patch("/username", response_model=UserRead)
async def claim_my_username(
    payload: UsernameClaim,
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> UserRead:
    """Pick the handle for an account that was assigned one.

    Every account created without a form — provisioned from SSO claims, or
    carried over from before handles existed — starts with one it did not
    choose, and picks its own here. Once picked, a handle changes only through
    a moderator.
    """
    if current_user.username_chosen:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=UserMessages.USERNAME_ALREADY_CHOSEN,
        )

    await username_service.claim_for_user(
        session,
        user=current_user,
        name=payload.username,
        prefer=read_handle_offer(payload.offer, payload.username),
    )

    current_user.updated_at = datetime.now(timezone.utc)
    session.add(current_user)
    await session.commit()
    await session.refresh(current_user)
    return await users_service.to_self_read(session, current_user)


@me_router.post("/age-confirmation", response_model=UserRead)
async def confirm_my_age(
    request: Request,
    payload: AgeConfirmation,
    session: UserSessionDep,
    system_session: SystemSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> UserRead:
    """Answer, once, whether this account is old enough for the open parts.

    Asked where somebody is about to join a community anyone on the deployment
    can find, and nowhere else. The answer lives on the account rather than per
    community: it is a fact about the person, and the second listed community
    they join asks nothing.

    **It gates the directory, not the deployment.** A community somebody was
    invited to is theirs and whoever runs it to answer for, so nothing here
    stands between them and it — an account that has never answered, or
    answered under age, keeps every private community it belongs to and
    everything in them.

    **The date is kept, encrypted** (``user_birthdates``, system engine only),
    because a plug-in's minimum age differs by country and one "old enough"
    answer cannot say whether somebody may use it. Nothing logs it, no audit
    record carries it, and no response returns it — ``birthdate_on_file`` says
    only that it is there. Beside it is the timestamp saying the question was
    answered, which is what shows the deployment asked.

    **A kept date stands.** Answering again once one is on file is refused, as
    an under-age answer is. Putting it right is the same support ticket.

    The comparison is the server's because it is the one that decides. A client
    could work out the same answer, and a client's answer is not evidence.

    **An answer of "under age" also stands.** It is recorded — the fact, not the
    date — and the question is not asked again, because a question you can
    re-answer until it comes out right is not one. Putting it right takes
    somebody with ``users.age_unblock``, which is a support ticket rather than
    an appeal to the same form.

    **Under the minimum for an account where they are, there is no account.**
    Sign-up refuses a date like that at the door, and an account that was made
    without a date (a sign-in provider asked for none, or the field was left
    empty) meets the same rule here, late: the minimum for the country the
    request comes from (``users.ACCOUNT_MINIMUM_AGE``, 13 in the US, 16 in
    Germany; the highest of them where the country is not known), applied
    before the directory's. The answer stands, the date is not kept, and the
    account is closed and scheduled for erasure
    (:func:`~app.services.platform.users.refuse_account_for_age`) — not merely
    kept out of the directory, which is the answer for sixteen.
    """
    if current_user.age_below_minimum_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=UserMessages.AGE_ANSWER_STANDS,
        )

    # A date nobody was born on is refused before anything is decided on it:
    # a year in the future would otherwise read as an age below every minimum
    # and close the account over a typo.
    try:
        users_service.check_birthdate(payload.birthdate)
    except users_service.InvalidBirthdateError as exc:
        # Refused separately from being too young, so the reply says which.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=UserMessages.AGE_INVALID_BIRTHDATE,
        ) from exc

    # Too young for an account at all, where they are. Only while the
    # deployment checks age: with the check off nothing is asked, and nothing
    # answered here may close an account.
    if await app_settings_service.community_age_gate_enabled(
        system_session
    ) and users_service.below_account_minimum(
        payload.birthdate, request_country(request)
    ):
        await users_service.refuse_account_for_age(session, current_user)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=UserMessages.AGE_BELOW_ACCOUNT_MINIMUM,
        )

    # The date is kept first, and only one answer per account is kept.
    try:
        kept = await users_service.keep_birthdate(
            system_session, user_id=current_user.id, birthdate=payload.birthdate
        )
    except users_service.InvalidBirthdateError as exc:
        # Not a date anybody was born on. Refused separately from being too
        # young, so the reply says which it was.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=UserMessages.AGE_INVALID_BIRTHDATE,
        ) from exc
    if kept is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=UserMessages.AGE_ANSWER_STANDS,
        )
    await system_session.commit()

    # Then the answer. If it does not save, the date goes too, so the person can
    # answer again.
    try:
        old_enough = users_service.record_age_answer(current_user, payload.birthdate)
        current_user.updated_at = datetime.now(timezone.utc)
        session.add(current_user)
        await session.commit()
    except BaseException:
        await users_service.forget_birthdate(
            system_session, user_id=current_user.id, only=kept
        )
        await system_session.commit()
        raise
    if not old_enough:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=UserMessages.AGE_BELOW_MINIMUM,
        )
    await session.refresh(current_user)

    return await users_service.to_self_read(session, current_user)


def _cookie_consent_read(row: UserCookieConsent | None) -> CookieConsentRead | None:
    return None if row is None else CookieConsentRead.model_validate(row)


@me_router.put("/cookie-consent", response_model=CookieConsentRead)
async def set_cookie_consent(
    payload: CookieConsentUpdate,
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> CookieConsentRead:
    """Record what this account allows to be kept in a browser.

    The browser it was answered in keeps its own copy — a visitor who has not
    signed in has no account to attach one to, and the answer is about that
    browser either way. This is what carries it to a browser that has never
    been asked, and carries a change of mind back to one that has.

    Replaces rather than appends: the question is what applies now. Sending it
    again with the same answer is a no-op apart from the stamp, which is what
    two browsers compare to tell whose answer is the later one.
    """
    row = await cookie_consent_service.record_consent(
        session,
        user_id=current_user.id,
        granted=payload.granted,
        version=payload.version,
    )
    await session.commit()
    await session.refresh(row)
    return CookieConsentRead.model_validate(row)


@me_router.post("/legal-acceptance", response_model=UserRead)
async def accept_legal_documents(
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> UserRead:
    """Agree to this deployment's terms and privacy policy.

    For an account that never met the signup form — one an identity provider
    provisioned on first sign-in. The form's own notice is the agreement for
    everybody else, recorded as the account is created.

    Saying it again appends: the table records acceptances, not a state, and
    agreeing to a newer revision is a real event rather than a correction to
    an old one. The screen only appears while something is outstanding, so in
    practice this is written once.

    A deployment with no terms of its own has nothing to accept, so this
    answers 404 rather than writing an empty record.
    """
    if not legal_service.legal_documents_enabled():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=LegalMessages.NOT_CONFIGURED,
        )
    if await legal_service.acceptance_outstanding(session, user=current_user):
        await legal_service.record_acceptance(session, user_id=current_user.id)
        await session.commit()
    payload = await users_service.to_self_read(session, current_user)
    payload.legal_acceptance_required = False
    return payload


def _address_read(row) -> UserEmailRead:
    """One stored address in the shape its owner reads."""
    return UserEmailRead(
        id=row.id,
        email=decrypt_field(row.email_encrypted, SALT_EMAIL),
        verified=row.verified_at is not None,
        is_primary=row.is_primary,
        source=row.source,
        created_at=row.created_at,
        last_login_at=row.last_login_at,
    )


@me_router.get("/emails", response_model=UserEmailListResponse)
async def list_my_addresses(
    system_session: SystemSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> UserEmailListResponse:
    """Every address this account holds.

    On the system engine: ``user_emails`` carries no request-path grants,
    because resolving an address happens before anybody is authenticated.
    """
    rows = await addresses.list_for_user(system_session, user_id=current_user.id)
    return UserEmailListResponse(
        items=[_address_read(row) for row in rows],
        password_required=await auth_posture.password_confirms(
            system_session, current_user
        ),
    )


@me_router.post(
    "/emails",
    response_model=VerificationSendResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[NotDemoSample],
)
@limiter.limit("5/15minutes")
async def add_my_address(
    request: Request,
    payload: UserEmailCreate,
    session: UserSessionDep,
    system_session: SystemSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    _first_party: Annotated[str, Depends(require_first_party_session)],
) -> VerificationSendResponse:
    """Start holding another address, and write to it to prove it.

    The password is asked for first, where there is one, and a recent sign-in
    otherwise, as for every change to how the account is signed into.

    The answer is the same whoever holds the address already. What differs is
    where the mail goes: a free address gets a link to confirm it, and one that
    is taken gets nothing.
    """
    await require_password_or_recent_proof(
        request, system_session, current_user, payload.current_password
    )
    # Whether this deployment can send at all is settled before the address is
    # looked at, so the refusal is about the server rather than about who holds
    # what. Everything after this point answers identically.
    if not await email_service.email_configured(session):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.SMTP_NOT_CONFIGURED,
        )

    added = await addresses.add_for_user(
        system_session, user_id=current_user.id, email=payload.email
    )
    # ``added`` is the new claim, or the one this account already had — asking
    # again is how a letter that did not arrive is sent again. ``None`` means
    # somebody has proven the address, and nothing is written.
    if added is not None:
        await system_session.commit()
        await system_session.refresh(added)
        token = await user_tokens_service.create_token(
            system_session,
            user_id=current_user.id,
            purpose=UserTokenPurpose.email_verification,
            user_email_id=added.id,
            # Whether the change was risky is a fact about this request, and
            # the address is proved by a link that carries no session.
            change={"risky": await is_risky(request, system_session, current_user)},
        )
        try:
            await email_service.send_address_verification_email(
                session, current_user, address=payload.email, token=token
            )
        except Exception:
            # The address is held and unproven either way; a send that failed
            # is retried by adding it again.
            logger.exception(
                "verification mail for a new address could not be sent (user %s)",
                current_user.id,
            )
    return VerificationSendResponse(status="sent")


@me_router.post(
    "/emails/{address_id}/remove",
    response_model=HeldChangeOutcome,
    responses=HELD_OUTCOME,
    dependencies=[NotDemoSample],
)
@limiter.limit("10/15minutes")
async def remove_my_address(
    request: Request,
    address_id: int,
    payload: UserEmailChange,
    system_session: SystemSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    _first_party: Annotated[str, Depends(require_first_party_session)],
) -> HeldChangeOutcome | JSONResponse:
    """Stop holding one address. The password is asked for again, as it is for
    a password change. A proved address removed from somewhere the account
    does not yet know waits two days (``202``)."""
    await require_password_or_recent_proof(
        request, system_session, current_user, payload.current_password
    )
    target = await addresses.removable(
        system_session, user_id=current_user.id, address_id=address_id
    )
    if target.verified_at is not None and await is_risky(
        request, system_session, current_user
    ):
        held = await hold_change(
            request,
            system_session,
            current_user,
            kind=HeldChangeKind.remove_address,
            address_id=address_id,
        )
        return held_response(HeldChangeOutcome(held=held))
    await held_changes.remove_address(
        system_session, current_user, address_id=address_id, risky=False
    )
    return HeldChangeOutcome()


@me_router.put(
    "/emails/{address_id}/primary",
    response_model=UserEmailRead,
    responses=HELD,
    dependencies=[NotDemoSample],
)
@limiter.limit("10/15minutes")
async def make_my_address_primary(
    request: Request,
    address_id: int,
    payload: UserEmailChange,
    system_session: SystemSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    _first_party: Annotated[str, Depends(require_first_party_session)],
) -> UserEmailRead | JSONResponse:
    """Move where account mail goes. The password is asked for again, and every
    address the account has proved is told, the one that was primary among
    them. Asked for from somewhere the account does not yet know, the move
    waits two days (``202``)."""
    await require_password_or_recent_proof(
        request, system_session, current_user, payload.current_password
    )
    target = await addresses.primary_candidate(
        system_session, user_id=current_user.id, address_id=address_id
    )
    if not target.is_primary and await is_risky(request, system_session, current_user):
        return held_response(
            await hold_change(
                request,
                system_session,
                current_user,
                kind=HeldChangeKind.primary,
                address_id=address_id,
            )
        )
    row = await held_changes.make_primary(
        system_session, current_user, address_id=address_id, risky=False
    )
    return _address_read(row)


@me_router.patch("", response_model=UserRead)
async def update_me(
    request: Request,
    user_in: UserSelfUpdate,
    session: UserSessionDep,
    system_session: SystemSessionDep,
    response: Response,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> UserRead:
    update_data = user_in.model_dump(exclude_unset=True)
    password = update_data.get("password")
    if password:
        await refuse_demo_sample(current_user)
        # Re-authenticate with the current password before changing it. An
        # account that holds none answers with a recent sign-in instead.
        password_proved = await require_password_or_recent_proof(
            request,
            system_session,
            current_user,
            update_data.get("current_password"),
        )
        await validate_new_password(password)
        # A request of its own (``UserSelfUpdate`` holds it to that), committed
        # with the session that keeps this device signed in. Its commit is the
        # request's only write; the account is read back for the answer.
        await set_password(
            request,
            system_session,
            user=current_user,
            password=password,
            via="self_service",
            response=response,
            password_proved=password_proved,
        )
        await session.refresh(current_user)

    if password or not update_data:
        return await users_service.to_self_read(session, current_user)

    if "avatar_url" in update_data:
        url_value = update_data["avatar_url"]
        if url_value:
            # A linked picture and an uploaded one are alternatives; taking one
            # drops the other.
            await user_avatars_service.delete_avatar(session, user_id=current_user.id)
            current_user.avatar_url = url_value
        else:
            await user_avatars_service.delete_avatar(session, user_id=current_user.id)
            current_user.avatar_url = None
    if "week_starts_on" in update_data:
        normalized_week_start = normalize_week_starts_on(update_data["week_starts_on"])
        if normalized_week_start is not None:
            current_user.week_starts_on = normalized_week_start
    if "time_format" in update_data:
        normalized_time_format = normalize_time_format(update_data["time_format"])
        if normalized_time_format is not None:
            current_user.time_format = normalized_time_format
    if "recent_tabs_limit" in update_data:
        current_user.recent_tabs_limit = personal_items_service.clamp_recent_limit(
            update_data["recent_tabs_limit"]
        )
    if update_data.get("count_toward_engagement_ranking") is not None:
        current_user.count_toward_engagement_ranking = update_data[
            "count_toward_engagement_ranking"
        ]
    # Sweeps a change can bring due sooner in the person's communities.
    sooner: list[str] = []
    if "timezone" in update_data:
        normalized_timezone = normalize_timezone(update_data["timezone"])
        if normalized_timezone:
            if normalized_timezone != current_user.timezone:
                # The overdue digest goes out at a time of their day.
                sooner.append("overdue")
            current_user.timezone = normalized_timezone
    if "event_reminder_minutes_before" in update_data:
        # ``None`` is a valid value here (reminders off), so assign directly.
        lead = normalize_reminder_minutes(update_data["event_reminder_minutes_before"])
        before = current_user.event_reminder_minutes_before
        if lead is not None and (before is None or lead > before):
            sooner.append("reminders")
        current_user.event_reminder_minutes_before = lead
    if "color_theme" in update_data:
        current_user.color_theme = update_data["color_theme"]
    if "task_completion_visual_feedback" in update_data:
        candidate = update_data["task_completion_visual_feedback"]
        if candidate not in TASK_COMPLETION_VISUAL_FEEDBACK_VALUES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=UserMessages.INVALID_TASK_COMPLETION_VISUAL_FEEDBACK,
            )
        current_user.task_completion_visual_feedback = candidate
    if "task_completion_audio_feedback" in update_data:
        current_user.task_completion_audio_feedback = bool(
            update_data["task_completion_audio_feedback"]
        )
    if "task_completion_haptic_feedback" in update_data:
        current_user.task_completion_haptic_feedback = bool(
            update_data["task_completion_haptic_feedback"]
        )
    if "locale" in update_data:
        current_user.locale = update_data["locale"]
    if "custom_status" in update_data:
        # Already held to shape by ``CustomStatus``; ``None`` is the status
        # taken off, which is the empty object rather than a null column.
        current_user.custom_status = update_data["custom_status"] or {}
    if "presence" in update_data:
        # The column is the standing preference. The roll is told separately
        # below, once the write is safely down.
        current_user.presence = Presence(update_data["presence"])
    if "profile_decorations" in update_data:
        # The payload validated it into ``ProfileDecorations``, so what lands
        # in the column is a known set of keys holding catalog ids and nothing
        # else. ``None`` is the bare profile.
        decorations = user_in.profile_decorations or ProfileDecorations()
        worn = decorations.worn()
        if worn:
            # The same row lock giving a pack back takes, and taken before the
            # library is read: the check and the write then sit in one
            # serialized window, so the two orderings are the only ones —
            # either this look is saved and the pack is given back after
            # (undressing it), or the pack goes first and this is refused.
            await session.exec(
                select(User.id).where(User.id == current_user.id).with_for_update()
            )
            # You wear what you have. The library is the authority for both
            # halves of that — whether the account has the decoration at all,
            # and whether it has it for the slot it is being put in.
            owned = await profile_decorations_service.owned_kinds(
                session, current_user.id
            )
            if profile_decorations_service.unwearable(worn, owned):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=UserMessages.DECORATION_NOT_OWNED,
                )
        current_user.profile_decorations = decorations.model_dump()

    current_user.updated_at = datetime.now(timezone.utc)
    session.add(current_user)
    await session.commit()
    await session.refresh(current_user)
    if "presence" in update_data:
        # A change made from an open tab takes effect for readers immediately,
        # rather than at the next reconnect. Told after the commit, so nothing
        # is shown on the strength of a write that did not land.
        presence.online.chose(current_user.id, current_user.presence)
    if sooner:
        communities = await member_guild_ids(session, current_user.id)
        for kind in sooner:
            await sweep_timers.arm_in(kind, communities)
    # Platform path — no initiative_roles enrichment (see read_me).
    return await users_service.to_self_read(session, current_user)


@me_router.get("/deletion-eligibility", response_model=DeletionEligibilityResponse)
async def check_deletion_eligibility(
    session: SystemSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> DeletionEligibilityResponse:
    """Check if the current user can be deleted and what blockers exist:
    the ones ``delete_own_account`` refuses on."""
    last_owner = await users_service.is_last_capability_holder(
        session, current_user.id, Capability.CONFIG_MANAGE
    )
    sole_seats = await users_service.is_last_guild_superadmin(session, current_user.id)
    return DeletionEligibilityResponse(
        can_delete=not last_owner and not sole_seats,
        last_owner=last_owner,
        sole_superadmin_communities=sole_seats,
    )


@me_router.post(
    "/delete-account",
    response_model=AccountDeletionResponse,
    dependencies=[NotDemoSample],
)
async def delete_own_account(
    http_request: Request,
    request: AccountDeletionRequest,
    session: SystemSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> AccountDeletionResponse:
    """Delete or deactivate the current user's account."""
    # Keep at least one owner, who is the only rung that can manage platform
    # configuration (FOR UPDATE to prevent a race).
    await users_service.ensure_config_manager_remains(
        session, current_user.id, for_update=True
    )

    # Re-check the password, where the account holds one to re-check. An
    # account that signs in another way — a passkey, an identity provider —
    # has none to supply, and answers with a recent sign-in and the
    # confirmation phrase.
    #
    # 400 (not 401): the user IS authenticated — they passed
    # ``get_current_active_user`` to reach this endpoint. The global axios
    # interceptor treats every 401 as a session expiry and force-logs-out the
    # SPA, so a wrong-password response on this form would knock the user out
    # of the session they were trying to confirm into. 400 keeps the error
    # scoped to the form's onError handler.
    await require_password_or_recent_proof(
        http_request,
        session,
        current_user,
        request.password,
        detail=UserMessages.INVALID_PASSWORD,
    )

    # The confirmation phrase is action-specific so the user can't accidentally
    # anonymize when they meant to deactivate, or vice versa.
    expected_phrase = (
        "DEACTIVATE MY ACCOUNT"
        if request.action == "deactivate"
        else "DELETE MY ACCOUNT"
    )
    if request.confirmation_text != expected_phrase:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=UserMessages.CONFIRMATION_MISMATCH,
        )

    # Holding a guild's only superadmin seat is the only blocker. Content the
    # user owns is released on the way out and left unowned for a guild admin to
    # claim, so there is nothing to hand over first.
    if await users_service.is_last_guild_superadmin(session, current_user.id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=GuildMessages.CANNOT_VACATE_LAST_SUPERADMIN,
        )

    if request.action == "deactivate":
        await users_service.deactivate_user(
            session, current_user.id, actor_user_id=current_user.id
        )
        return AccountDeletionResponse(
            success=True,
            action="deactivate",
            message=(
                "Your account has been deactivated. Contact whoever runs this "
                "server to reactivate it."
            ),
        )

    # action == "soft_delete"
    #
    # Nothing is erased here. The account moves to ``deleted`` and keeps
    # everything — memberships, initiative roles, the files it owns — so
    # that coming back restores it whole. It stops existing for everybody
    # else immediately, and ``account_purge`` erases it when the deployment's
    # window runs out. Signing in before then calls the whole thing off.
    await users_service.request_account_deletion(
        session, current_user.id, actor_user_id=current_user.id
    )
    return AccountDeletionResponse(
        success=True,
        action="soft_delete",
        message="Your account has been deleted.",
    )


@me_router.get("/api-keys", response_model=ApiKeyListResponse)
async def list_my_api_keys(
    session: SystemSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> ApiKeyListResponse:
    """List all API keys for the current user."""
    # user_api_keys is a system-engine-only table (no request-path grant, no
    # own-row policy), so key management runs on SystemSessionDep; the explicit
    # user_id filter in the service is the ownership scope.
    keys = await api_keys_service.list_api_keys(session, user=current_user)
    return ApiKeyListResponse(keys=keys)


@me_router.post(
    "/api-keys",
    response_model=ApiKeyCreateResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[NotDemoSample],
)
async def create_my_api_key(
    payload: ApiKeyCreateRequest,
    session: SystemSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    _first_party: Annotated[str, Depends(require_first_party_session)],
) -> ApiKeyCreateResponse:
    """Create a new API key for the current user."""
    # Runs on the system engine (user_api_keys has no request-path grant, see
    # list_my_api_keys); the current_user scoping below and in the service is
    # the ownership boundary.
    if payload.community_id is not None:
        # A guild-bound key must target a guild the caller belongs to. Membership
        # is in the public guild_memberships table (readable on the system
        # engine); the explicit user_id filter is the scope. Validating here also
        # turns an unknown guild into a 403 instead of a 500 (FK violation).
        membership = await guilds_service.get_membership(
            session, guild_id=payload.community_id, user_id=current_user.id
        )
        if membership is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=UserMessages.API_KEY_GUILD_FORBIDDEN,
            )
        # And the guild has to accept this member's keys at all. Asked here as
        # well as at the gate so a key that could never be used is never handed
        # over.
        if await guild_entitlements.refuses_api_keys(session, membership):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=GuildMessages.COMMUNITY_API_KEYS_REFUSED,
            )
    secret, api_key = await api_keys_service.create_api_key(
        session,
        user=current_user,
        name=payload.name,
        expires_at=payload.expires_at,
        read_only=payload.read_only,
        guild_id=payload.community_id,
        resource_type=payload.resource_type,
        resource_id=payload.resource_id,
    )
    return ApiKeyCreateResponse(api_key=api_key, secret=secret)


@me_router.delete("/api-keys/{api_key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_api_key(
    api_key_id: int,
    session: SystemSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    _first_party: Annotated[str, Depends(require_first_party_session)],
) -> None:
    """Delete an API key for the current user."""
    # System-engine session (see list_my_api_keys); the service's user_id filter
    # scopes the delete to the caller's own keys.
    deleted = await api_keys_service.delete_api_key(
        session, user=current_user, api_key_id=api_key_id
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=UserMessages.API_KEY_NOT_FOUND
        )


async def _require_receiving_admin(
    session: AsyncSession, *, guild_id: int, new_owner_id: int
) -> None:
    """Ownership may only be handed to an active admin of this guild.

    That restriction is what makes the action safe to expose: a guild admin
    already reads and writes every part of their guild, so an owner grant can
    never widen anyone's reach. An ordinary member could end up nominal owner of
    content in an initiative they are not in, which RLS would then hide from
    them.

    The caller has routed into the guild's schema, so the roster comes from
    ``MemberProfile`` — the view a guild session reads people through.
    """
    recipient = (
        await session.exec(
            users_service.guild_members(
                select(MemberProfile.id), guild_id=guild_id
            ).where(
                MemberProfile.id == new_owner_id,
                MemberProfile.status == UserStatus.active,
                GuildMembership.role.in_(GUILD_ADMIN_ROLES),
            )
        )
    ).one_or_none()
    if recipient is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=UserMessages.OWNER_MUST_BE_COMMUNITY_ADMIN,
        )


def _ownership_payload(
    items: list, eligible_plugins: list[OwnerPluginSummary]
) -> OwnedContentResponse:
    counts: dict[str, int] = {}
    for item in items:
        counts[item.tool.value] = counts.get(item.tool.value, 0) + 1
    return OwnedContentResponse(
        items=[
            OwnedContentItem(tool=item.tool, id=item.id, name=item.name)
            for item in items
        ],
        counts=counts,
        total=len(items),
        eligible_plugins=eligible_plugins,
    )


async def _recipient(
    session: AsyncSession, *, guild_id: int, payload: OwnershipTransferRequest
) -> ownership_service.Owner:
    """Who the request names to receive the content. A person must be an
    active admin of this guild; a plug-in's eligibility is asked of the content
    it would receive, by the move itself."""
    if payload.new_owner_plugin_id is not None:
        return ownership_service.Owner(plugin_install_id=payload.new_owner_plugin_id)
    person_id = payload.new_owner_id
    if person_id is None:
        # The schema requires one of the two; nobody named is nobody eligible.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=UserMessages.OWNER_MUST_BE_COMMUNITY_ADMIN,
        )
    await _require_receiving_admin(session, guild_id=guild_id, new_owner_id=person_id)
    return ownership_service.Owner(user_id=person_id)


def _transfer_payload(counts: dict) -> OwnershipTransferResponse:
    by_value = {tool.value: n for tool, n in counts.items()}
    return OwnershipTransferResponse(counts=by_value, total=sum(by_value.values()))


@guild_router.get("/unowned-content", response_model=OwnedContentResponse)
async def list_unowned_content(
    session: SessionDep,
    current_admin: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildAdminContext,
) -> OwnedContentResponse:
    """Everything in this guild that no current member or live plug-in owns, and
    the plug-ins that may own all of it.

    Both the content released when someone left and anything orphaned before
    that — either way nobody who can act on it owns it.
    """
    items = await ownership_service.summarize_unowned_content(
        session, guild_id=guild_context.guild_id
    )
    return _ownership_payload(
        items, await ownership_service.eligible_plugin_owners(session, items)
    )


@guild_router.post("/unowned-content/claim", response_model=OwnershipTransferResponse)
async def claim_unowned_content(
    payload: OwnershipTransferRequest,
    session: SessionDep,
    current_admin: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildAdminContext,
) -> OwnershipTransferResponse:
    """Give everything nobody owns to one guild admin, or to a plug-in that may
    own all of it (422 ``OWNER_PLUGIN_NOT_ELIGIBLE`` otherwise)."""
    recipient = await _recipient(
        session, guild_id=guild_context.guild_id, payload=payload
    )
    counts = await ownership_service.claim_unowned_content(
        session,
        guild_id=guild_context.guild_id,
        to=recipient,
        actor_user_id=current_admin.id,
    )
    await session.commit()
    return _transfer_payload(counts)


@guild_router.get("/{user_id}/owned-content", response_model=OwnedContentResponse)
async def list_owned_content(
    user_id: int,
    session: SessionDep,
    current_admin: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildAdminContext,
) -> OwnedContentResponse:
    """What this user owns in this guild, for the transfer dialog to list,
    and the plug-ins that may own all of it.

    Works for anyone the grants still name, member or not — accounts get
    abandoned as often as they get closed.
    """
    items = await ownership_service.summarize_owned_content(session, user_id)
    return _ownership_payload(
        items, await ownership_service.eligible_plugin_owners(session, items)
    )


@guild_router.post(
    "/{user_id}/transfer-ownership", response_model=OwnershipTransferResponse
)
async def transfer_ownership(
    user_id: int,
    payload: OwnershipTransferRequest,
    session: SessionDep,
    current_admin: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildAdminContext,
) -> OwnershipTransferResponse:
    """Move everything ``user_id`` owns in this guild to a guild admin, or to
    a plug-in that may own all of it (422 ``OWNER_PLUGIN_NOT_ELIGIBLE`` otherwise).

    The only place ownership is moved by hand, and guild-admin only.
    """
    if user_id == payload.new_owner_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=UserMessages.OWNER_ALREADY_HOLDS_CONTENT,
        )
    recipient = await _recipient(
        session, guild_id=guild_context.guild_id, payload=payload
    )
    counts = await ownership_service.transfer_content_ownership(
        session,
        from_user_id=user_id,
        to=recipient,
        guild_id=guild_context.guild_id,
        actor_user_id=current_admin.id,
    )
    await session.commit()
    return _transfer_payload(counts)


@guild_router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    user_id: int,
    session: SessionDep,
    system_session: SystemSessionDep,
    current_admin: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildAdminContext,
) -> None:
    """Remove a member from this guild.

    Ends their memberships and the access those carried. It does not move
    ownership: content they own stays recorded as theirs and stops being
    reachable by them, until an admin re-homes it through
    ``POST /{user_id}/transfer-ownership``.
    """
    if user_id == current_admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=UserMessages.CANNOT_DELETE_SELF,
        )

    stmt = select(GuildMembership).where(
        GuildMembership.user_id == user_id,
        GuildMembership.guild_id == guild_context.guild_id,
    )
    result = await session.exec(stmt)
    membership = result.one_or_none()
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=UserMessages.NOT_IN_GUILD
        )

    # Removing the seat-holder ends the seat exactly as demoting them does, so
    # it answers to the same authority: only the seat passes the seat on.
    if (
        membership.role == CommunityRole.superadmin
        and guild_context.role != CommunityRole.superadmin
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=GuildMessages.COMMUNITY_ROLE_NOT_ASSIGNABLE,
        )
    await guilds_service.lock_guild_seats(system_session, guild_context.guild_id)
    # And the seat stays filled for as long as the guild requires a sign-in:
    # the requirement is lifted from the surface the seat holds.
    if await guilds_service.must_keep_superadmin(
        system_session, guild_id=guild_context.guild_id, user_id=user_id
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=GuildMessages.CANNOT_VACATE_LAST_SUPERADMIN,
        )

    await guilds_service.remove_user_from_guild(
        session,
        guild_id=guild_context.guild_id,
        user_id=user_id,
        actor_user_id=current_admin.id,
    )
    await session.commit()
    # Kicked from the guild — drop the user's live content streams immediately
    # (guild-level access change), consistent with the other removal paths.
    await content_sockets.revoke_user(guild_context.guild_id, user_id)


# --- profile pictures --------------------------------------------------------


def _image_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=ImageMessages.IMAGE_NOT_FOUND,
    )


async def _avatar_response(
    session: AsyncSession, user_id: int, digest: str
) -> Response:
    """``user_id``'s picture when ``digest`` is its current one, or a 404."""
    if not user_avatars_service.is_valid_digest(digest):
        raise _image_not_found()
    avatar = await user_avatars_service.get_avatar(session, user_id=user_id)
    if avatar is None or avatar.sha256 != digest:
        raise _image_not_found()
    return Response(
        content=avatar.data,
        media_type=avatar.content_type,
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/{user_id}/avatar/{digest}", include_in_schema=False)
async def read_user_avatar(user_id: int, digest: str, session: SessionDep) -> Response:
    """Serve one user's profile picture.

    No session required, and the same for everyone: a name and a face are
    public information in this product, so there is no membership check and no
    per-caller variation in the response — which is what lets it be cached by a
    shared proxy rather than only by the one browser that asked.

    Addressed by the digest of the bytes, so the content at a URL never
    changes. A digest that is not this user's current picture is a 404 rather
    than a redirect to whatever is current, because the response is cached
    under the URL that was asked for.
    """
    return await _avatar_response(session, user_id, digest)


@members_router.get(
    "/{person}/avatar/{digest}",
    response_class=Response,
    responses={
        200: {
            "description": "The picture.",
            "content": {media: {} for media in sorted(AVATAR_SPEC.content_types)},
        }
    },
)
async def read_member_avatar(
    person: PersonId,
    digest: str,
    session: ActorSessionDep,
    guild_context: MembersRead,
) -> Response:
    """Serve the picture a member of this community uploaded.

    Where an installed plug-in's ``avatar_url`` for a person points: the person is
    named by the plug-in's reference for them. The same bytes and caching as the
    profile picture route, and a 404 for a digest that is not the member's
    current picture, or for somebody who is not a member here.
    """
    current = (
        await session.exec(
            select(GuildMember.avatar_url).where(GuildMember.id == person)
        )
    ).first()
    if user_avatars_service.uploaded_digest(person, current) != digest:
        raise _image_not_found()
    # Membership is settled. The picture is read the way the profile picture
    # route reads it, on a session of its own, once this one's connection is
    # back in the pool.
    await session.close()
    async with cohorts.community_session(session, guild_context.guild_id) as reader:
        return await _avatar_response(reader, person, digest)


@me_router.put("/avatar", response_model=UserRead)
async def upload_my_avatar(
    file: Annotated[UploadFile, File()],
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> UserRead:
    """Replace the caller's profile picture.

    Multipart rather than a base64 field on ``PATCH /me``: sending the
    image inside JSON is the thing this endpoint exists to stop. The body is
    read under the cap so an oversized upload is refused rather than buffered
    whole, and the format and dimensions are read from the header — nothing
    here decodes the image.

    Runs on the request-path session, where the row policies allow the caller
    to write their own avatar and no other.
    """
    try:
        data = await read_upload_bounded(file, AVATAR_SPEC.max_bytes)
    except FileTooLargeError:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=ImageMessages.IMAGE_TOO_LARGE,
        )
    validated = user_avatars_service.validate_avatar(data)

    # Records the serving URL on the user row too, so every payload that
    # carries a person can name the picture without a second query.
    await user_avatars_service.store_avatar(
        session, user=current_user, avatar=validated
    )
    await session.commit()
    await session.refresh(current_user)
    return await users_service.to_self_read(session, current_user)


@me_router.delete("/avatar", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_avatar(
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Response:
    """Remove the caller's profile picture."""
    await user_avatars_service.delete_avatar(
        session, user_id=current_user.id, user=current_user
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
