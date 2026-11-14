"""A person's views of one community's lists — filter sets, sort orders, layouts.

The community's half of the view-preference store: the same key/value/JSON
shape as ``/user-view-preferences``, kept in the community's own schema for the
lists inside it (a project's, an initiative tool's, the roster). The
key names the list inside the community, so it carries no community id
(``view:project:12``). Every read and write is the caller's own row.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Response, status
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import col, select

from app.api.deps import CurrentUser, GuildContextDep, RLSSessionDep
from app.api.v1.platform_endpoints.user_view_preferences import ScopeKeyPath
from app.models.tenant.view_preference import ViewPreference
from app.schemas.platform.user_view_preference import (
    UserViewPreferencesMap,
    UserViewPreferenceWrite,
)

router = APIRouter()


@router.get("", response_model=UserViewPreferencesMap)
async def list_community_view_preferences(
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
) -> UserViewPreferencesMap:
    """Return the caller's views of this community's lists as a
    ``{scope_key: value}`` map."""
    del guild_context  # validation + routing happen in the dependency
    rows = (
        await session.exec(
            select(ViewPreference).where(col(ViewPreference.user_id) == current_user.id)
        )
    ).all()
    return UserViewPreferencesMap(items={row.scope_key: row.value for row in rows})


@router.put("/{scope_key}", status_code=status.HTTP_204_NO_CONTENT)
async def put_community_view_preference(
    scope_key: ScopeKeyPath,
    payload: UserViewPreferenceWrite,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
) -> Response:
    """Upsert the caller's view under ``scope_key`` (last write wins). A platform
    grantee is not a member, and a ``read_only`` community takes no writes, so
    nothing is kept for either."""
    if not (guild_context.is_pam or guild_context.content_read_only):
        now = datetime.now(UTC)
        stmt = pg_insert(ViewPreference).values(
            user_id=current_user.id,
            scope_key=scope_key,
            value=payload.value,
            updated_at=now,
        )
        await session.exec(
            stmt.on_conflict_do_update(
                index_elements=[ViewPreference.user_id, ViewPreference.scope_key],
                set_={"value": stmt.excluded.value, "updated_at": now},
            )
        )
        await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
