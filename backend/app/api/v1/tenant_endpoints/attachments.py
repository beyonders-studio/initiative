from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.api.deps import (
    RLSSessionDep,
    get_current_active_user,
    GuildContextDep,
)
from app.core.messages import ImageMessages, AttachmentMessages
from app.models.platform.user import User
from app.schemas.tenant.attachment import AttachmentUploadResponse
from app.services.tenant.attachments import (
    IMAGE_SUFFIXES,
    MAX_IMAGE_BYTES,
    detect_document_image_type,
    FileTooLargeError,
    PASTED_IMAGE_PREFIX,
    enforce_storage_quota,
    new_upload_filename,
    read_upload_bounded,
    store_upload,
)
from app.services import storage_config
from app.services.tenant import attachments as attachments_service
from app.services.storage import get_guild_storage

router = APIRouter()

ImageUploadUser = Annotated[User, Depends(get_current_active_user)]


async def _store_image(
    *,
    current_user: User,
    session: RLSSessionDep,
    guild_id: int,
    file: UploadFile,
    prefix: str = "",
) -> AttachmentUploadResponse:
    """Check, store and record one pasted or chosen image.

    ``prefix`` leads the stored name, which the server alone chooses — so it
    can say what the image was uploaded for, and nothing a client sends can
    make an image claim to be one.
    """
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AttachmentMessages.IMAGE_ONLY,
        )

    try:
        contents = await read_upload_bounded(file, MAX_IMAGE_BYTES)
    except FileTooLargeError:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=AttachmentMessages.TOO_LARGE,
        )
    if not contents:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ImageMessages.IMAGE_EMPTY,
        )

    content_type = detect_document_image_type(contents)
    if content_type is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AttachmentMessages.INVALID_IMAGE,
        )

    # The stored name carries the detected format, so the suffix the serve path
    # reads and the type recorded on the row describe the same bytes.
    filename = new_upload_filename(IMAGE_SUFFIXES[content_type], prefix=prefix)

    await enforce_storage_quota(
        session, guild_id=guild_id, incoming_bytes=len(contents)
    )

    # Pick up a backend/credential change saved in another worker before writing,
    # so the blob lands in the configured store (TTL-gated; usually a no-op).
    await storage_config.ensure_storage_config_fresh(session)
    url = await store_upload(
        session,
        guild_id=guild_id,
        filename=filename,
        data=contents,
        content_type=content_type,
        created_by=current_user.id,
    )
    await session.commit()

    return AttachmentUploadResponse(
        filename=file.filename or filename,
        # Guild in the path so the served media self-describes its guild.
        url=url,
        content_type=content_type,
        size=len(contents),
    )


@router.post(
    "/", response_model=AttachmentUploadResponse, status_code=status.HTTP_201_CREATED
)
async def upload_attachment(
    current_user: ImageUploadUser,
    session: RLSSessionDep,
    guild_context: GuildContextDep,
    file: UploadFile = File(...),
) -> AttachmentUploadResponse:
    return await _store_image(
        current_user=current_user,
        session=session,
        guild_id=guild_context.guild_id,
        file=file,
    )


@router.post(
    "/pasted",
    response_model=AttachmentUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_pasted_image(
    current_user: ImageUploadUser,
    session: RLSSessionDep,
    guild_context: GuildContextDep,
    file: UploadFile = File(...),
) -> AttachmentUploadResponse:
    """Store a picture pasted into markdown — a task's description, a comment.

    The picture belongs to the text it is written into: taking it back out, or
    purging what it is in, deletes it once nothing else shows it.
    """
    return await _store_image(
        current_user=current_user,
        session=session,
        guild_id=guild_context.guild_id,
        file=file,
        prefix=PASTED_IMAGE_PREFIX,
    )


@router.delete("/pasted/{filename}", status_code=status.HTTP_204_NO_CONTENT)
async def discard_pasted_image(
    filename: str,
    current_user: ImageUploadUser,
    session: RLSSessionDep,
    guild_context: GuildContextDep,
) -> None:
    """Discard a picture that was pasted and never saved.

    Asked by the page that pasted it, as it is left. A picture something saved
    shows, or that somebody else uploaded, stays — and says so no differently,
    so the answer is the same whatever the name.
    """
    discarded = await attachments_service.discard_pasted_image(
        session, filename, user_id=current_user.id
    )
    await session.commit()
    if discarded is not None:
        get_guild_storage(guild_context.guild_id).delete(discarded)
