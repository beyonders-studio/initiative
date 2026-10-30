"""Reading a community's data jobs, imports and exports alike.

Starting, cancelling, confirming and downloading a job stay with its
direction (``imports``, ``exports``): who may start one differs, and so does
what each does. Reading one is the same for both: the ``own_row_*`` policies
show a person their own jobs and a community admin everyone's.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import col, select

from app.api.deps import GuildContextDep, RLSSessionDep, get_current_active_user
from app.core.messages import DataJobMessages
from app.models.platform.user import User
from app.models.tenant.data_job import DataJob
from app.schemas.tenant.data_job import DataJobRead, serialize_data_job

router = APIRouter()

_LIST_LIMIT = 50


@router.get("/", response_model=list[DataJobRead])
async def list_data_jobs(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> list[DataJobRead]:
    """The caller's imports and exports, newest first (RLS scopes the rows:
    own rows, or the whole community for its admin)."""
    jobs = await session.exec(
        select(DataJob).order_by(col(DataJob.created_at).desc()).limit(_LIST_LIMIT)
    )
    return [serialize_data_job(job, guild_id=guild_context.guild_id) for job in jobs]


@router.get("/{job_id}", response_model=DataJobRead)
async def get_data_job(
    job_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> DataJobRead:
    job = await session.get(DataJob, job_id)
    if job is None:  # includes rows RLS hides — 404, never 403
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=DataJobMessages.DATA_JOB_NOT_FOUND,
        )
    return serialize_data_job(job, guild_id=guild_context.guild_id)
