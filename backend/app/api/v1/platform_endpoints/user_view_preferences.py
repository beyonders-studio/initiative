"""Per-user view preferences — filter sets, sort orders, view modes.

A generic key/value/JSON store keyed by ``(user_id, scope_key)``. The
frontend uses one of these per "view" (e.g. ``my-tasks``,
``project:42:tasks``, ``files``) and the server keeps the blob
verbatim. RLS confines every read/write to ``current_user_id``.

These are the account's own views, which name no community. A community's
lists keep theirs in that community (``/c/{community_id}/view-preferences``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status
from sqlmodel import select

from app.api.deps import UserSessionDep, get_current_active_user
from app.core.messages import ViewPreferenceMessages
from app.models.platform.user import User
from app.models.platform.user_view_preference import UserViewPreference
from app.schemas.platform.user_view_preference import (
    SCOPE_KEY_MAX_LENGTH,
    UserViewPreferencesMap,
    UserViewPreferenceWrite,
)

router = APIRouter()


ScopeKeyPath = Annotated[
    str,
    Path(
        min_length=1,
        max_length=SCOPE_KEY_MAX_LENGTH,
        # Allow alphanumerics plus the few separators our frontend uses
        # ('-', '_', ':'); refuse slashes, spaces, and other oddities to
        # keep keys stable across clients.
        pattern=r"^[A-Za-z0-9_:\-\.]+$",
        description="Scope identifier — e.g. 'my-tasks' or 'project:42:tasks'.",
    ),
]


@router.get("", response_model=UserViewPreferencesMap)
async def list_view_preferences(
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> UserViewPreferencesMap:
    """Return every preference for the current user as a ``{scope_key: value}`` map."""
    stmt = select(UserViewPreference).where(
        UserViewPreference.user_id == current_user.id
    )
    result = await session.exec(stmt)
    rows = result.all()
    return UserViewPreferencesMap(items={row.scope_key: row.value for row in rows})


@router.put("/{scope_key}", status_code=status.HTTP_204_NO_CONTENT)
async def put_view_preference(
    scope_key: ScopeKeyPath,
    payload: UserViewPreferenceWrite,
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Response:
    """Upsert the preference for the given ``scope_key`` (last write wins).
    A view of a community's list (``view:<community id>:…``) is refused: it
    is kept in that community."""
    names = scope_key.split(":")
    if len(names) > 2 and names[0] == "view" and names[1].isdigit():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ViewPreferenceMessages.VIEW_KEPT_IN_THE_COMMUNITY,
        )
    stmt = select(UserViewPreference).where(
        UserViewPreference.user_id == current_user.id,
        UserViewPreference.scope_key == scope_key,
    )
    result = await session.exec(stmt)
    existing = result.one_or_none()
    now = datetime.now(UTC)
    if existing is None:
        session.add(
            UserViewPreference(
                user_id=current_user.id,
                scope_key=scope_key,
                value=payload.value,
                updated_at=now,
            )
        )
    else:
        existing.value = payload.value
        existing.updated_at = now
        session.add(existing)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
