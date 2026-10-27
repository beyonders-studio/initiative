"""Resumable uploads (tus 1.0): a file sent in pieces, staged until the
endpoint it is for takes it. The protocol is :mod:`app.services.resumable`;
each route establishes the reader in the community through the seam before
anything of the request's body is read. Not in the API schema: a tus client
speaks the protocol, not generated operations."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from app.api.deps import GuildContextDep, RLSSessionDep, get_current_active_user
from app.core.body_limit import max_body
from app.core.rate_limit import limiter
from app.models.platform.user import User
from app.services import resumable

router = APIRouter(include_in_schema=False)

UserDep = Annotated[User, Depends(get_current_active_user)]


@router.options("")
async def describe(guild_context: GuildContextDep) -> Response:
    return resumable.options()


@router.post("")
async def create_upload(
    request: Request,
    session: RLSSessionDep,
    guild_context: GuildContextDep,
    current_user: UserDep,
) -> Response:
    return await resumable.create(request, session, guild_context, current_user)


@router.head("/{upload_id}")
async def upload_offset(
    upload_id: str, session: RLSSessionDep, guild_context: GuildContextDep
) -> Response:
    return await resumable.head(session, guild_context.guild_id, upload_id)


@router.patch("/{upload_id}")
# A large file is many requests.
@limiter.limit("600/minute")
@max_body(lambda: resumable.MAX_CHUNK_BYTES)
async def append_to_upload(
    request: Request,
    upload_id: str,
    session: RLSSessionDep,
    guild_context: GuildContextDep,
    current_user: UserDep,
) -> Response:
    return await resumable.patch(
        request, session, guild_context, current_user, upload_id
    )


@router.delete("/{upload_id}")
async def cancel_upload(
    upload_id: str, session: RLSSessionDep, guild_context: GuildContextDep
) -> Response:
    return await resumable.terminate(session, guild_context.guild_id, upload_id)
