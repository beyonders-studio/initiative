"""The owner's intake settings: which guild, and which project per stream.

Every route is ``config.manage``. Binding a stream is deployment configuration
of the same class as OIDC, SMTP and branding, and sits at the same capability.

The session is the platform system engine, which reads and writes the shared
singleton. The guild's own schema is reached on a system session from that
guild's cohort (``app.services.platform.intake_setup``).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.v1.platform_endpoints.operator import ConfigManageDep
from app.core.intake import IntakeStream, meta, offered_streams
from app.core.messages import IntakeMessages
from app.models.platform.guild import Guild
from app.models.platform.user import User
from app.schemas.platform.intake import (
    FeedbackSwitchUpdate,
    IntakeBindingRead,
    IntakeBindingUpsert,
    IntakeBlueprintImport,
    IntakeContactUpdate,
    IntakeOptionsRead,
    IntakeSettingsRead,
    OperationsCommunityUpdate,
)
from app.services.platform import app_settings as app_settings_service
from app.services.platform import auth_posture, intake_setup
from app.services.platform.intake_setup import BindingView
from app.api.deps import get_current_active_user, SystemSessionDep

router = APIRouter()


def _read(view: BindingView) -> IntakeBindingRead:
    return IntakeBindingRead(
        stream=view.stream,
        binding_id=view.binding_id,
        project_id=view.project_id,
        project_name=view.project_name,
        project_archived=view.project_archived,
        initiative_id=view.initiative_id,
        initiative_name=view.initiative_name,
        default_status_id=view.default_status_id,
        default_status_name=view.default_status_name,
        task_type_id=view.task_type_id,
        task_type_name=view.task_type_name,
        awaiting_filer_status_id=view.awaiting_filer_status_id,
        active_status_id=view.active_status_id,
        conversation=meta(view.stream).conversation,
        isolated=view.isolated,
        shares_initiative=view.shares_initiative,
        enabled=view.enabled,
        last_case_at=view.last_case_at,
    )


def _stream_or_404(raw: str) -> IntakeStream:
    """The stream named, where this server takes it."""
    stream = next((s for s in offered_streams() if s.value == raw), None)
    if stream is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=IntakeMessages.UNKNOWN_STREAM,
        )
    return stream


def _address(payload: IntakeContactUpdate) -> str | None:
    return None if payload.email is None else str(payload.email)


async def _settings(session: AsyncSession) -> IntakeSettingsRead:
    guild_id, views = await intake_setup.list_bindings(session)
    guild_name = None
    if guild_id is not None:
        guild_name = (
            await session.exec(select(Guild.name).where(Guild.id == guild_id))
        ).one_or_none()
    general, per_stream = await intake_setup.contacts(session)
    return IntakeSettingsRead(
        operations_community_id=guild_id,
        operations_community_name=guild_name,
        bindings=[_read(view) for view in views],
        general_contact_email=general,
        contact_emails={IntakeStream(key): email for key, email in per_stream.items()},
        feedback_enabled=await app_settings_service.feedback_enabled(session),
    )


@router.get("/intake", response_model=IntakeSettingsRead)
async def read_intake_settings(
    session: SystemSessionDep,
    _owner: ConfigManageDep,
) -> IntakeSettingsRead:
    """Where each stream lands, and when it last opened a case.

    Every stream is listed whether bound or not, so the page shows the full set
    rather than only what somebody already configured.
    """
    return await _settings(session)


@router.get("/intake/options", response_model=IntakeOptionsRead)
async def read_intake_options(
    session: SystemSessionDep,
    _owner: ConfigManageDep,
) -> IntakeOptionsRead:
    """What the settings page can bind a stream to.

    The operations guild's initiatives, their projects and each project's
    statuses — names and ids, enough to fill the pickers. Empty before a guild
    has been named.
    """
    return IntakeOptionsRead.model_validate(
        {"initiatives": await intake_setup.list_options(session)}
    )


@router.put("/intake/community", response_model=IntakeSettingsRead)
async def update_operations_community(
    payload: OperationsCommunityUpdate,
    session: SystemSessionDep,
    _owner: ConfigManageDep,
) -> IntakeSettingsRead:
    """Name the guild that receives this deployment's operations work.

    Clearing it stops every stream at once and touches no binding inside the
    guild, so pointing back restores exactly what was there.
    """
    await intake_setup.set_operations_guild(session, payload.community_id)
    return await _settings(session)


@router.put("/intake/contact", response_model=IntakeSettingsRead)
async def update_general_contact(
    payload: IntakeContactUpdate,
    session: SystemSessionDep,
    _owner: ConfigManageDep,
) -> IntakeSettingsRead:
    """Set the deployment's catch-all contact address, or clear it.

    Named wherever somebody is told who to contact and the stream in question
    has no address of its own.
    """
    await intake_setup.set_general_contact(session, _address(payload))
    return await _settings(session)


@router.put("/intake/feedback-enabled", response_model=IntakeSettingsRead)
async def update_feedback_switch(
    payload: FeedbackSwitchUpdate,
    session: SystemSessionDep,
    owner: ConfigManageDep,
) -> IntakeSettingsRead:
    """Let people here send feedback to the Initiative team, or stop. Off,
    nothing offers it and nothing is sent."""
    await auth_posture.change(
        auth_posture.RuleContext.platform(session, owner),
        {"feedback_enabled": payload.enabled},
    )
    return await _settings(session)


@router.put("/intake/{stream}/contact", response_model=IntakeSettingsRead)
async def update_stream_contact(
    stream: str,
    payload: IntakeContactUpdate,
    session: SystemSessionDep,
    _owner: ConfigManageDep,
) -> IntakeSettingsRead:
    """Set one stream's contact address, or clear it back to the general one."""
    await intake_setup.set_stream_contact(
        session, _stream_or_404(stream), _address(payload)
    )
    return await _settings(session)


@router.put("/intake/{stream}", response_model=IntakeBindingRead)
async def upsert_binding(
    stream: str,
    payload: IntakeBindingUpsert,
    session: SystemSessionDep,
    _owner: ConfigManageDep,
) -> IntakeBindingRead:
    """Route one stream into a project of the operations guild."""
    view = await intake_setup.bind(
        session,
        stream=_stream_or_404(stream),
        project_id=payload.project_id,
        default_status_id=payload.default_status_id,
        task_type_id=payload.task_type_id,
        awaiting_filer_status_id=payload.awaiting_filer_status_id,
        active_status_id=payload.active_status_id,
        enabled=payload.enabled,
    )
    return _read(view)


@router.post("/intake/{stream}/blueprint", response_model=IntakeBindingRead)
async def import_blueprint(
    stream: str,
    payload: IntakeBlueprintImport,
    session: SystemSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    _owner: ConfigManageDep,
) -> IntakeBindingRead:
    """Set a stream up from its blueprint, and bind it to what that produced.

    An ordinary project import. The result is a project the team can rename and
    restructure; the binding only names it.
    """
    view = await intake_setup.provision_from_blueprint(
        session,
        stream=_stream_or_404(stream),
        initiative_id=payload.initiative_id,
        importer=current_user,
    )
    return _read(view)


@router.delete("/intake/{stream}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_binding(
    stream: str,
    session: SystemSessionDep,
    _owner: ConfigManageDep,
) -> None:
    """Stop routing a stream. The project and every case in it stay."""
    await intake_setup.unbind(session, _stream_or_404(stream))
