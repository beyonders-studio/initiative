"""The demo deployment's routes. Every one answers 404 unless the deployment
runs as the demo (``DEMO_MODE``).

* ``POST /demo/redeem`` — opening a demo link, with an address to leave.
* ``POST /demo/lead`` and ``GET /demo/copy`` — a visitor's own copy: leaving
  an address, and whether the copy is ready.
* ``POST /c/{community_id}/demo/publish`` and ``GET …/demo/pitch`` — a pitch's
  admins publishing it, and what the page needs to offer that.
* ``POST /c/{community_id}/demo/personas``, ``…/pitches``,
  ``…/pitches/find``, ``…/pitches/delete``, ``…/links``, ``…/links/read`` and ``…/links/revoke``
  — the demo plug-in's API, answered only to an installation token from the
  operations community holding the community-admin standing there. As on
  every route a plug-in calls, the community is the token's. Pitches and
  links are named by that install's references, in the body. Not part of the
  OpenAPI document: only the plug-in calls them.
"""

from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import GuildContextDep, SystemSessionDep, get_current_active_user
from app.api.v1.platform_endpoints.plugin_installation import InstallationDep
from app.api.v1.platform_endpoints.session_opening import open_session
from app.core import audit_context, webhook_events
from app.core.body_limit import MULTIPART_SLACK_BYTES, max_body
from app.core.config import settings
from app.core.messages import DemoMessages, ImportEngineMessages, PluginMessages
from app.db.holds import HoldsInForce
from app.db.request_context import Unattributed
from app.db.session import set_rls_context
from app.demo import accounts, copies, pitches, sales
from app.models.platform.guild import CommunityRole
from app.models.platform.guild_image import IMAGE_SPECS, GuildImageVariant
from app.models.platform.identity_ref import IdentityEntity
from app.models.platform.user import User
from app.schemas.platform.demo import (
    DemoCopyRead,
    DemoDirectoryCard,
    DemoLeadCreate,
    DemoLeadRead,
    DemoLinkCreate,
    DemoLinkCreated,
    DemoLinkReport,
    DemoLinkReports,
    DemoLinkRevoke,
    DemoLinksRead,
    DemoPersonasEnsure,
    DemoPersonasEnsured,
    DemoPitchCreated,
    DemoPitchDelete,
    DemoPitchesFind,
    DemoPitchesFound,
    DemoPitchFound,
    DemoPitchRead,
    DemoRedeem,
    DemoRedemption,
)
from app.services import captcha as captcha_service
from app.services.import_engine import limits as import_limits
from app.services.import_engine.engine import spooled_upload
from app.services.platform.intake import configured_operations_guild_id

router = APIRouter()
#: Mounted under ``/c/{community_id}/demo``.
community_router = APIRouter()
#: The demo plug-in's API, mounted under ``/c/{community_id}/demo``.
sales_router = APIRouter(include_in_schema=False)

_ICON = IMAGE_SPECS[GuildImageVariant.icon]


def _not_found(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def _demo_only() -> None:
    if not settings.DEMO_MODE:
        raise _not_found(DemoMessages.DEMO_LINK_NOT_FOUND)


DemoOnly = Annotated[None, Depends(_demo_only)]
CurrentUserDep = Annotated[User, Depends(get_current_active_user)]


@router.post("/redeem", response_model=DemoRedemption)
async def redeem_demo_link(
    request: Request,
    response: Response,
    payload: DemoRedeem,
    session: SystemSessionDep,
    _demo: DemoOnly,
) -> DemoRedemption:
    """Open a demo link: a new account in a new copy of the link's pitch,
    signed in for as long as the copy lasts, with ``email`` kept for a
    follow-up when one is given. Answers 503 ``DEMO_BUSY`` when no copy is
    free."""
    await captcha_service.verify_or_raise(
        payload.captcha_token, remote_ip=audit_context.client_ip()
    )
    try:
        opened = await copies.redeem(session, payload.token, payload.email)
    except copies.LinkNotLive:
        raise _not_found(DemoMessages.DEMO_LINK_NOT_FOUND)
    except copies.PoolBusy:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=DemoMessages.DEMO_BUSY,
            headers={"Retry-After": "60"},
        )
    token = await open_session(
        request,
        response,
        session,
        user_id=opened.user_id,
        token_version=opened.token_version,
        amr=(),
        audit_detail={"method": "demo"},
        ends_by=opened.expires_at,
    )
    return DemoRedemption(
        **token.model_dump(),
        community_id=opened.guild_id,
        import_job_id=opened.import_job_id,
    )


async def _own_copy(user: User) -> copies.AccountCopy:
    copy = await copies.account_copy(user.id)
    if copy is None:
        raise _not_found(DemoMessages.DEMO_COPY_NOT_FOUND)
    return copy


@router.get("/copy", response_model=DemoCopyRead)
async def read_demo_copy(current_user: CurrentUserDep, _demo: DemoOnly) -> DemoCopyRead:
    """The signed-in visitor's copy, and whether the import filling it has
    finished. 404 for an account not made for a copy."""
    copy = await _own_copy(current_user)
    return DemoCopyRead(
        community_id=copy.guild_id,
        ready=await copies.copy_ready(copy),
        expires_at=copy.expires_at,
    )


@router.post("/lead", status_code=status.HTTP_204_NO_CONTENT)
async def leave_demo_lead(
    payload: DemoLeadCreate,
    current_user: CurrentUserDep,
    session: SystemSessionDep,
    _demo: DemoOnly,
) -> Response:
    """Leave an address for a follow-up about the visitor's demo, on the link
    their copy was opened from. Kept apart from the account."""
    copy = await _own_copy(current_user)
    if copy.link_id is None:
        raise _not_found(DemoMessages.DEMO_LINK_NOT_FOUND)
    await set_rls_context(session, Unattributed())
    new_lead = await sales.keep_lead(session, copy.link_id, payload.email)
    await session.commit()
    if new_lead:
        await sales.announce(webhook_events.DEMO_LEAD_LEFT, copy.link_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- a pitch's admins -----------------------------------------------------------


async def _is_pitch(session: AsyncSession, guild_id: int) -> bool:
    await set_rls_context(session, Unattributed())
    return settings.DEMO_MODE and await pitches.is_pitch(session, guild_id)


@community_router.get("/pitch", response_model=DemoPitchRead)
async def read_demo_pitch(
    guild_context: GuildContextDep, session: SystemSessionDep
) -> DemoPitchRead:
    """Whether this community is a pitch, and when it was last published:
    the version visitors get. ``is_pitch`` is false everywhere else."""
    if not await _is_pitch(session, guild_context.guild_id):
        return DemoPitchRead(is_pitch=False)
    newest = await pitches.newest_export(guild_context.guild_id)
    return DemoPitchRead(
        is_pitch=True, last_published_at=None if newest is None else newest[1]
    )


@community_router.post("/publish", status_code=status.HTTP_202_ACCEPTED)
async def publish_demo_pitch(
    guild_context: GuildContextDep, session: SystemSessionDep
) -> Response:
    """Publish this pitch: export it, so the copies opened from now on get it
    as it is. For the pitch's admins; 404 for a community that is not a
    pitch."""
    if not await _is_pitch(session, guild_context.guild_id):
        raise _not_found(DemoMessages.DEMO_PITCH_NOT_FOUND)
    if not guild_context.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=DemoMessages.DEMO_PITCH_ADMIN_REQUIRED,
        )
    host = await accounts.demo_host(session)
    await pitches.publish(guild_context.guild_id, host)
    return Response(status_code=status.HTTP_202_ACCEPTED)


# --- the demo plug-in -----------------------------------------------------------


async def sales_install(
    _demo: DemoOnly, installation: InstallationDep
) -> sales.SalesInstall:
    """The install the token names, when it is in the operations community
    and holds the community-admin standing there: its token asked for it and
    the seat's grant holds it, as the install standing read them for this
    request. 403 otherwise. The path's community is not read: an install's
    community is its token's."""
    if (
        not installation.context.guild_admin
        or installation.guild_id != await configured_operations_guild_id()
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=PluginMessages.SCOPE_REQUIRED,
        )
    return sales.SalesInstall(installation.guild_id, installation.install_id)


SalesInstallDep = Annotated[sales.SalesInstall, Depends(sales_install)]


@sales_router.post("/personas", response_model=DemoPersonasEnsured)
async def ensure_demo_personas(
    payload: DemoPersonasEnsure, _install: SalesInstallDep, session: SystemSessionDep
) -> DemoPersonasEnsured:
    """Make each persona that is missing, accounts nobody signs in to that
    bundles name by handle, and call each by its display name in every
    community it is in. 409 ``DEMO_PERSONA_TAKEN`` for a handle that is an
    account somebody signs in to, and nothing is made."""
    await set_rls_context(session, Unattributed())
    for persona in payload.personas:
        try:
            await accounts.ensure_persona(
                session, handle=persona.handle, display_name=persona.display_name
            )
        except accounts.HandleTaken:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=DemoMessages.DEMO_PERSONA_TAKEN,
            )
    await session.commit()
    return DemoPersonasEnsured(handles=[persona.handle for persona in payload.personas])


def _directory_card(raw: str | None) -> DemoDirectoryCard | None:
    if raw is None:
        return None
    try:
        return DemoDirectoryCard.model_validate_json(raw)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc


@sales_router.post("/pitches", response_model=DemoPitchCreated)
@max_body(
    lambda: (
        import_limits.IMPORT_MAX_BACKUP_UPLOAD_BYTES
        + _ICON.max_bytes
        + MULTIPART_SLACK_BYTES
    ),
    ImportEngineMessages.IMPORT_TOO_LARGE,
)
async def make_demo_pitch(
    install: SalesInstallDep,
    name: Annotated[str, Form(min_length=1, max_length=100)],
    bundle: Annotated[UploadFile, File()],
    logo: Annotated[Optional[UploadFile], File()] = None,
    editors: Annotated[list[str], Form(max_length=50)] = [],
    directory: Annotated[Optional[str], Form(max_length=2000)] = None,
) -> DemoPitchCreated:
    """Make a pitch from an uploaded ``bundle``, named ``name``, with ``logo``
    as its icon, and publish it. Each ``editors`` field names by handle an
    account made its admin. ``directory``, a directory card as JSON
    (``{categories, join_policy}``), lists it in the community directory and
    gives its initiatives that join policy."""
    card = _directory_card(directory)
    icon = await logo.read(_ICON.max_bytes + 1) if logo is not None else None
    try:
        async with spooled_upload(
            bundle.file, max_bytes=import_limits.IMPORT_MAX_BACKUP_UPLOAD_BYTES
        ) as path:
            pitch_id = await pitches.make_pitch(
                name=name, bundle=path, logo=icon, editors=editors, directory=card
            )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=DemoMessages.DEMO_PITCH_SOURCE_INVALID,
        )
    return DemoPitchCreated(
        pitch_ref=await install.name(IdentityEntity.guild, pitch_id)
    )


@sales_router.post("/pitches/find", response_model=DemoPitchesFound)
async def find_demo_pitches(
    payload: DemoPitchesFind, install: SalesInstallDep, session: SystemSessionDep
) -> DemoPitchesFound:
    """The pitches still kept whose name is exactly one of ``names``, oldest
    first, each with when its community was made."""
    await set_rls_context(session, Unattributed())
    found = await pitches.find_pitches(session, payload.names)
    return DemoPitchesFound(
        pitches=[
            DemoPitchFound(
                pitch_ref=await install.name(IdentityEntity.guild, pitch_id),
                name=name,
                created_at=created_at,
            )
            for pitch_id, name, created_at in found
        ]
    )


@sales_router.post("/pitches/delete", status_code=status.HTTP_204_NO_CONTENT)
async def delete_demo_pitch(
    payload: DemoPitchDelete, install: SalesInstallDep, session: SystemSessionDep
) -> Response:
    """End a pitch's links and delete its community now. Copies already
    opened from it last their day. 404 ``DEMO_PITCH_NOT_FOUND`` once it is
    gone; 409 ``DEMO_PITCH_HELD`` while the platform holds content in it."""
    await set_rls_context(session, Unattributed())
    pitch_id = (
        await install.resolve(session, IdentityEntity.guild, [payload.pitch_ref])
    ).get(payload.pitch_ref)
    try:
        deleted = pitch_id is not None and await pitches.delete_pitch(session, pitch_id)
    except HoldsInForce:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=DemoMessages.DEMO_PITCH_HELD
        )
    if not deleted:
        raise _not_found(DemoMessages.DEMO_PITCH_NOT_FOUND)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@sales_router.post("/links", response_model=DemoLinkCreated)
async def make_demo_link(
    payload: DemoLinkCreate, install: SalesInstallDep, session: SystemSessionDep
) -> DemoLinkCreated:
    """Make a link to a pitch: each opening gets its own copy, with ``role``.
    It ends at ``expires_at``, 30 days from now by default. The URL is shown
    once."""
    now = datetime.now(timezone.utc)
    if payload.expires_at is not None and payload.expires_at <= now:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=DemoMessages.DEMO_LINK_EXPIRY_INVALID,
        )
    await set_rls_context(session, Unattributed())
    pitch_id = (
        await install.resolve(session, IdentityEntity.guild, [payload.pitch_ref])
    ).get(payload.pitch_ref)
    try:
        if pitch_id is None:
            raise ValueError("unknown pitch")
        link, token = await pitches.make_link(
            session,
            pitch_id=pitch_id,
            role=CommunityRole(payload.role),
            lifetime=pitches.LINK_LIFETIME
            if payload.expires_at is None
            else payload.expires_at - now,
            label=payload.label,
            max_redemptions=payload.max_redemptions,
        )
    except ValueError:
        raise _not_found(DemoMessages.DEMO_PITCH_NOT_FOUND)
    link_id = link.id
    await session.commit()
    return DemoLinkCreated(
        link_ref=await install.name(IdentityEntity.demo_link, link_id),
        url=pitches.link_url(token),
    )


@sales_router.post("/links/read", response_model=DemoLinkReports)
async def read_demo_links(
    payload: DemoLinksRead, install: SalesInstallDep, session: SystemSessionDep
) -> DemoLinkReports:
    """What happened on each link: its state, how often it was opened and
    when last, and the addresses left on it in the last 30 days, the same on
    every read. A reference that names no link is left out."""
    await set_rls_context(session, Unattributed())
    named = await install.resolve(session, IdentityEntity.demo_link, payload.link_refs)
    reports = await sales.read_links(session, list(set(named.values())))
    by_link = {report.link_id: report for report in reports}
    return DemoLinkReports(
        links=[
            DemoLinkReport(
                link_ref=ref,
                state=report.state,
                redemption_count=report.redemption_count,
                last_redeemed_at=report.last_redeemed_at,
                leads=[
                    DemoLeadRead(
                        id=lead.id, email=lead.email, created_at=lead.created_at
                    )
                    for lead in report.leads
                ],
            )
            for ref, link_id in named.items()
            if (report := by_link.get(link_id)) is not None
        ]
    )


@sales_router.post("/links/revoke", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_demo_link(
    payload: DemoLinkRevoke, install: SalesInstallDep, session: SystemSessionDep
) -> Response:
    """End a link now. Copies already opened from it last their day."""
    await set_rls_context(session, Unattributed())
    link_id = (
        await install.resolve(session, IdentityEntity.demo_link, [payload.link_ref])
    ).get(payload.link_ref)
    if link_id is None or not await pitches.revoke_link(session, link_id):
        raise _not_found(DemoMessages.DEMO_LINK_NOT_FOUND)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
