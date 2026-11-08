"""Binding a stream to a project, and setting one up from a blueprint.

The platform holds one pointer — ``app_settings.operations_guild_id`` — and
everything else is ordinary per-guild config inside the guild it names. This
module is what the owner's settings page calls to read and change both.

Every write here is the platform owner's (``config.manage``): binding a stream
is deployment configuration of the same class as OIDC, SMTP and branding.
Reaching the guild's own schema is a system session from the guild's cohort
routed into it by the guild alone, the same way every other platform surface
that reads guild rows does.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator, Optional

from fastapi import HTTPException, status as http_status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.intake import (
    Conversation,
    IntakeStream,
    Source,
    meta,
    offered_streams,
)
from app.core.tools import Tool
from app.core.messages import GuildMessages, InitiativeMessages, IntakeMessages
from app.db import cohorts, operations_schema
from app.db.advisory_locks import LockNamespace, advisory_lock
from app.db.session import routed_guild_id, set_rls_context
from app.models.platform.app_setting import AppSetting
from app.models.platform.guild import Guild, CommunityStatus
from app.models.platform.user import User
from app.models.tenant.initiative import Initiative
from app.models.tenant.intake import IntakeBinding, IntakeCase
from app.models.tenant.project import Project
from app.models.tenant.task import Task, TaskStatus, TaskType
from app.services.tenant import task_types as task_types_service
from app.services.marketplace.registration_lookup import invalidate_registrations
from app.services.platform.intake import operations_guild_id
from app.db.request_context import SystemGuild


@dataclass(frozen=True)
class BindingView:
    """One stream's binding, with the names the settings page shows."""

    stream: IntakeStream
    binding_id: Optional[int]
    project_id: Optional[int]
    project_name: Optional[str]
    #: Whether the bound project has been archived or trashed since. Archived
    #: content takes no writes, so a stream pointed at one receives nothing
    #: until it is brought back or pointed somewhere else.
    project_archived: bool
    initiative_id: Optional[int]
    initiative_name: Optional[str]
    default_status_id: Optional[int]
    default_status_name: Optional[str]
    task_type_id: Optional[int]
    task_type_name: Optional[str]
    #: Which status means "waiting on whoever filed it", and which one a case
    #: returns to when they answer.
    awaiting_filer_status_id: Optional[int]
    active_status_id: Optional[int]
    isolated: bool
    #: Shares its initiative with another stream where one of the two keeps
    #: its initiative to itself. Flagged, never undone.
    shares_initiative: bool
    enabled: bool
    #: The most recent case this stream opened. The monitoring that matters on
    #: this page: is the thing on.
    last_case_at: Optional[str]


@asynccontextmanager
async def _route(guild_id: int) -> AsyncIterator[AsyncSession]:
    """A system session from the guild's cohort, routed into its schema. The
    caller commits what it writes."""
    async with cohorts.system_session(guild_id) as session:
        await set_rls_context(session, SystemGuild(guild_id))
        yield session


async def set_operations_guild(
    session: AsyncSession, guild_id: Optional[int]
) -> Optional[int]:
    """Point this deployment's operations work at ``guild_id``, or at nothing.

    ``None`` unsets it, which stops every stream at once without touching the
    bindings inside the guild — so pointing back restores exactly what was
    there. An ordinary guild is required: a suspended one could not be worked
    in, so it is refused rather than silently accepted.
    """
    if guild_id is not None:
        guild = (
            await session.exec(select(Guild).where(Guild.id == guild_id))
        ).one_or_none()
        if guild is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=GuildMessages.COMMUNITY_NOT_FOUND,
            )
        if guild.status != CommunityStatus.active.value:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=IntakeMessages.GUILD_NOT_ACTIVE,
            )

    # The operations tables and the filer role follow the choice: created in
    # the community chosen before work is routed there, and dropped from the
    # one it replaces with its cases' files. Unsetting it keeps the tables, so
    # pointing back restores them. One choice at a time; boot finishes a move
    # this process did not.
    async with operations_schema.choice_turn():
        if guild_id is not None:
            await operations_schema.provision_operations(guild_id)
        row = await _settings_row(session)
        row.operations_guild_id = guild_id
        session.add(row)
        await session.commit()
        # A plug-in limited to the operations community follows the choice too.
        invalidate_registrations()
        await operations_schema.follow_choice(guild_id)
    return guild_id


async def _settings_row(session: AsyncSession) -> AppSetting:
    row = (await session.exec(select(AppSetting).where(AppSetting.id == 1))).first()
    return row if row is not None else AppSetting(id=1)


async def set_general_contact(session: AsyncSession, email: Optional[str]) -> None:
    """Set the deployment's catch-all contact address, or clear it."""
    row = await _settings_row(session)
    row.intake_general_contact = email
    session.add(row)
    await session.commit()


async def set_stream_contact(
    session: AsyncSession, stream: IntakeStream, email: Optional[str]
) -> None:
    """Set one stream's contact address, or clear it back to the general one."""
    row = await _settings_row(session)
    contacts = dict(row.intake_contacts or {})
    if email is None:
        contacts.pop(stream.value, None)
    else:
        contacts[stream.value] = email
    # A fresh dict, so the JSONB column is seen as changed.
    row.intake_contacts = contacts
    session.add(row)
    await session.commit()


async def contacts(session: AsyncSession) -> tuple[Optional[str], dict[str, str]]:
    """The general address and the own address of every stream this server
    takes, as set."""
    row = (await session.exec(select(AppSetting).where(AppSetting.id == 1))).first()
    if row is None:
        return None, {}
    taken = {
        stream.value
        for stream in offered_streams()
        if Source.submitted in meta(stream).sources
    }
    own = {k: v for k, v in (row.intake_contacts or {}).items() if k in taken}
    return row.intake_general_contact, own


async def _resolve_project(
    session: AsyncSession, project_id: int
) -> tuple[Project, Initiative]:
    """The project a binding names, and the initiative that will read its cases.

    Routed session; both rows must be in this guild's schema, which the schema
    boundary already guarantees for anything this query can see.
    """
    project = (
        await session.exec(
            select(Project)
            .where(Project.id == project_id)
            .execution_options(populate_existing=True)
        )
    ).one_or_none()
    if project is None:
        raise Tool.project.not_found()
    if project.archived_at is not None or project.deleted_at is not None:
        # Archived and trashed content takes no writes, so a case could not be
        # filed here. Refused at the moment of binding rather than discovered
        # the first time something needs to land.
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=IntakeMessages.PROJECT_NOT_LIVE,
        )
    initiative = (
        await session.exec(
            select(Initiative)
            .where(Initiative.id == project.initiative_id)
            .execution_options(populate_existing=True)
        )
    ).one_or_none()
    if initiative is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=InitiativeMessages.NOT_FOUND,
        )
    return project, initiative


async def _write_binding(
    session: AsyncSession,
    *,
    stream: IntakeStream,
    project: Project,
    project_id: int,
    default_status_id: Optional[int],
    task_type_id: Optional[int] = None,
    awaiting_filer_status_id: Optional[int] = None,
    active_status_id: Optional[int] = None,
    enabled: bool,
) -> IntakeBinding:
    """Create or update the binding row. Routed session; flushes, no commit.

    Every named status must belong to the named project; anything else is
    refused here rather than quietly ignored, because the page that sent it
    showed the owner a list of that project's statuses.
    """
    named = {
        s
        for s in (default_status_id, awaiting_filer_status_id, active_status_id)
        if s is not None
    }
    if named:
        found = set(
            (
                await session.exec(
                    select(TaskStatus.id)
                    .where(TaskStatus.id.in_(named))  # type: ignore[union-attr]
                    .where(TaskStatus.project_id == project.id)
                )
            ).all()
        )
        if found != named:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=IntakeMessages.STATUS_NOT_IN_PROJECT,
            )
    if (
        task_type_id is not None
        and await task_types_service.get_project_type(session, task_type_id, project_id)
        is None
    ):
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=IntakeMessages.TYPE_NOT_IN_PROJECT,
        )
    await _ensure_isolation(session, stream=stream, initiative_id=project.initiative_id)

    binding = (
        await session.exec(
            select(IntakeBinding)
            .where(IntakeBinding.stream == stream.value)
            .execution_options(populate_existing=True)
        )
    ).one_or_none()
    # ``project_id`` rather than ``project.id``: the row was fetched by that id,
    # so they are the same value and only one of them is known to be an int.
    if binding is None:
        binding = IntakeBinding(stream=stream, project_id=project_id)
    binding.project_id = project_id
    binding.default_status_id = default_status_id
    binding.task_type_id = task_type_id
    binding.awaiting_filer_status_id = awaiting_filer_status_id
    binding.active_status_id = active_status_id
    binding.enabled = enabled
    session.add(binding)
    await session.flush()
    return binding


async def _isolation_conflicts(
    session: AsyncSession, *, stream: IntakeStream, initiative_id: int
) -> list[IntakeStream]:
    """The other streams bound into ``initiative_id`` that ``stream`` may not
    share it with: every one, if ``stream`` keeps its initiative to itself,
    and otherwise the ones that do."""
    others = (
        await session.exec(
            select(IntakeBinding.stream)
            .join(Project, Project.id == IntakeBinding.project_id)
            .where(Project.initiative_id == initiative_id)
            .where(IntakeBinding.stream != stream.value)
        )
    ).all()
    isolated = meta(stream).isolated
    return [
        IntakeStream(other)
        for other in others
        if isolated or meta(IntakeStream(other)).isolated
    ]


async def _ensure_isolation(
    session: AsyncSession, *, stream: IntakeStream, initiative_id: int
) -> None:
    """Refuse a binding that would put a stream that keeps its initiative to
    itself beside another stream.

    Bindings are written one at a time: the check holds a transaction lock
    every binding write in this community takes, so two streams bound into
    one initiative at once see each other rather than both passing.
    """
    await advisory_lock(
        session, LockNamespace.INTAKE_BINDINGS, routed_guild_id(session)
    )
    if await _isolation_conflicts(session, stream=stream, initiative_id=initiative_id):
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=IntakeMessages.INITIATIVE_SHARED,
        )


async def _blueprint_status_roles(
    session: AsyncSession, stream: IntakeStream, project_id: int
) -> dict[str, Optional[int]]:
    """The statuses a project set up from ``stream``'s blueprint plays each
    role with. None for a stream with no conversation, where nobody is ever
    waited on."""
    from app.blueprints.intake import REQUESTER_REPLIED, WAITING_ON_REQUESTER

    roles: dict[str, Optional[int]] = {
        "awaiting_filer_status_id": None,
        "active_status_id": None,
    }
    if meta(stream).conversation is Conversation.none:
        return roles
    rows = (
        await session.exec(
            select(TaskStatus.name, TaskStatus.id).where(
                TaskStatus.project_id == project_id
            )
        )
    ).all()
    by_name = {name: status_id for name, status_id in rows}
    # A case can only be waiting on its filer if answering moves it on.
    if by_name.get(WAITING_ON_REQUESTER) and by_name.get(REQUESTER_REPLIED):
        roles["awaiting_filer_status_id"] = by_name[WAITING_ON_REQUESTER]
        roles["active_status_id"] = by_name[REQUESTER_REPLIED]
    return roles


async def bind(
    session: AsyncSession,
    *,
    stream: IntakeStream,
    project_id: int,
    default_status_id: Optional[int] = None,
    task_type_id: Optional[int] = None,
    awaiting_filer_status_id: Optional[int] = None,
    active_status_id: Optional[int] = None,
    enabled: bool = True,
) -> BindingView:
    """Route ``stream`` into ``project_id``, replacing any existing binding.

    Cases are keyed by project, so repointing a stream starts fresh in the new
    project and leaves the old one's history where the work is.
    """
    guild_id = await _require_operations_guild(session)
    async with _route(guild_id) as routed:
        project, initiative = await _resolve_project(routed, project_id)
        binding = await _write_binding(
            routed,
            stream=stream,
            project=project,
            project_id=project_id,
            default_status_id=default_status_id,
            task_type_id=task_type_id,
            awaiting_filer_status_id=awaiting_filer_status_id,
            active_status_id=active_status_id,
            enabled=enabled,
        )
        await routed.commit()
        await routed.refresh(binding)
        return await _view(routed, stream, binding, project, initiative)


async def unbind(session: AsyncSession, stream: IntakeStream) -> None:
    """Stop routing ``stream`` anywhere. The project and its cases stay."""
    guild_id = await _require_operations_guild(session)
    async with _route(guild_id) as routed:
        binding = (
            await routed.exec(
                select(IntakeBinding).where(IntakeBinding.stream == stream.value)
            )
        ).one_or_none()
        if binding is not None:
            await routed.delete(binding)
            await routed.commit()


async def _require_operations_guild(session: AsyncSession) -> int:
    guild_id = await operations_guild_id(session)
    if guild_id is None:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=IntakeMessages.NO_OPERATIONS_GUILD,
        )
    return guild_id


async def _view(
    session: AsyncSession,
    stream: IntakeStream,
    binding: Optional[IntakeBinding],
    project: Optional[Project],
    initiative: Optional[Initiative],
) -> BindingView:
    if binding is None:
        return BindingView(
            stream=stream,
            binding_id=None,
            project_id=None,
            project_name=None,
            project_archived=False,
            initiative_id=None,
            initiative_name=None,
            default_status_id=None,
            default_status_name=None,
            task_type_id=None,
            task_type_name=None,
            awaiting_filer_status_id=None,
            active_status_id=None,
            isolated=meta(stream).isolated,
            shares_initiative=False,
            enabled=False,
            last_case_at=None,
        )
    status_name = None
    if binding.default_status_id is not None:
        status_name = (
            await session.exec(
                select(TaskStatus.name).where(
                    TaskStatus.id == binding.default_status_id
                )
            )
        ).one_or_none()
    type_name = None
    if binding.task_type_id is not None:
        type_name = (
            await session.exec(
                select(TaskType.name).where(TaskType.id == binding.task_type_id)
            )
        ).one_or_none()
    # Cases only — the seed task a blueprint imports and anything the team adds
    # by hand are ordinary tasks in the project, not cases this stream opened.
    # Joined through the task, which is where the project a case is in lives.
    last_case_at = (
        await session.exec(
            select(IntakeCase.opened_at)
            .join(Task, Task.id == IntakeCase.task_id)
            .where(Task.project_id == binding.project_id)
            .where(IntakeCase.stream == binding.stream)
            .order_by(IntakeCase.opened_at.desc())
            .limit(1)
        )
    ).one_or_none()
    return BindingView(
        stream=stream,
        binding_id=binding.id,
        project_id=binding.project_id,
        project_name=project.name if project else None,
        project_archived=bool(
            project is not None
            and (project.archived_at is not None or project.deleted_at is not None)
        ),
        initiative_id=initiative.id if initiative else None,
        initiative_name=initiative.name if initiative else None,
        default_status_id=binding.default_status_id,
        default_status_name=status_name,
        task_type_id=binding.task_type_id,
        task_type_name=type_name,
        awaiting_filer_status_id=binding.awaiting_filer_status_id,
        active_status_id=binding.active_status_id,
        isolated=meta(stream).isolated,
        shares_initiative=bool(
            initiative is not None
            and await _isolation_conflicts(
                session, stream=stream, initiative_id=int(initiative.id)
            )
        ),
        enabled=binding.enabled,
        last_case_at=last_case_at.isoformat() if last_case_at else None,
    )


async def list_bindings(
    session: AsyncSession,
) -> tuple[Optional[int], list[BindingView]]:
    """Every stream this server takes and where it currently lands.

    Returns one view per stream, bound or not, so the settings page renders the
    full set rather than only what somebody has already configured.
    """
    streams = offered_streams()
    guild_id = await operations_guild_id(session)
    if guild_id is None:
        return None, [await _view(session, s, None, None, None) for s in streams]

    async with _route(guild_id) as routed:
        bindings = {
            IntakeStream(row.stream): row
            for row in await routed.exec(select(IntakeBinding))
        }
        views: list[BindingView] = []
        for stream in streams:
            binding = bindings.get(stream)
            project = initiative = None
            if binding is not None:
                # No live-only filter: a binding to a project that has since
                # been archived is exactly what the page has to be able to show.
                project = (
                    await routed.exec(
                        select(Project).where(Project.id == binding.project_id)
                    )
                ).one_or_none()
                if project is not None:
                    initiative = (
                        await routed.exec(
                            select(Initiative).where(
                                Initiative.id == project.initiative_id
                            )
                        )
                    ).one_or_none()
            views.append(await _view(routed, stream, binding, project, initiative))
    return guild_id, views


async def provision_from_blueprint(
    session: AsyncSession,
    *,
    stream: IntakeStream,
    initiative_id: int,
    importer: User,
) -> BindingView:
    """Import the stream's blueprint into ``initiative_id`` and bind to it.

    The import and the binding are one transaction, so a deployment either
    gains a set-up stream or is left exactly as it was. ``import_project``
    flushes without committing, which is what lets the two compose.

    An ordinary project import otherwise: what it produces is a project the
    team can rename, restructure and add to, and the binding only names it.
    """
    from app.blueprints.intake import blueprint_for
    from app.services.tenant.project_import import import_project

    guild_id = await _require_operations_guild(session)
    async with _route(guild_id) as routed:
        initiative = (
            await routed.exec(select(Initiative).where(Initiative.id == initiative_id))
        ).one_or_none()
        if initiative is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=InitiativeMessages.NOT_FOUND,
            )
        # Before the import, so a refused stream leaves no project behind.
        await _ensure_isolation(routed, stream=stream, initiative_id=initiative_id)

        result = await import_project(
            routed,
            envelope=blueprint_for(stream),
            target_initiative=initiative,
            importer=importer,
        )
        project, _ = await _resolve_project(routed, result.entity_id)
        binding = await _write_binding(
            routed,
            stream=stream,
            project=project,
            project_id=result.entity_id,
            default_status_id=None,
            **await _blueprint_status_roles(routed, stream, result.entity_id),
            enabled=True,
        )
        await routed.commit()
        await routed.refresh(binding)
        return await _view(routed, stream, binding, project, initiative)


async def list_options(session: AsyncSession) -> list[dict]:
    """The operations guild's initiatives, their projects, and each project's
    statuses and types — what the settings page's pickers offer.

    Names and ids only, for the one guild the deployment has named. Empty when
    it has named none, which is what the page shows before anything is set up.
    """
    guild_id = await operations_guild_id(session)
    if guild_id is None:
        return []

    async with _route(guild_id) as routed:
        initiatives = (
            await routed.exec(
                select(Initiative)
                .where(Initiative.deleted_at.is_(None))
                .order_by(Initiative.name)
            )
        ).all()
        projects = (
            await routed.exec(
                select(Project)
                .where(Project.deleted_at.is_(None))
                .where(Project.archived_at.is_(None))
                .order_by(Project.name)
            )
        ).all()
        statuses = (
            await routed.exec(
                select(TaskStatus).order_by(TaskStatus.project_id, TaskStatus.position)
            )
        ).all()
        types = (
            await routed.exec(
                select(TaskType).order_by(
                    TaskType.project_id, TaskType.position, TaskType.id
                )
            )
        ).all()

    by_project: dict[int, list[dict]] = {}
    for status in statuses:
        by_project.setdefault(status.project_id, []).append(
            {"id": status.id, "name": status.name}
        )
    types_by_project: dict[int, list[dict]] = {}
    for task_type in types:
        types_by_project.setdefault(task_type.project_id, []).append(
            {"id": task_type.id, "name": task_type.name}
        )
    by_initiative: dict[int, list[dict]] = {}
    for project in projects:
        by_initiative.setdefault(project.initiative_id, []).append(
            {
                "id": project.id,
                "name": project.name,
                "statuses": by_project.get(project.id, []),
                "task_types": types_by_project.get(project.id, []),
            }
        )
    return [
        {
            "id": initiative.id,
            "name": initiative.name,
            "projects": by_initiative.get(initiative.id, []),
        }
        for initiative in initiatives
    ]
