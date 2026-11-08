"""The dependencies a route resolves before it runs."""

from typing import Annotated

from fastapi import Depends, FastAPI
from httpx2 import ASGITransport, AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.requests import Request

from app.api.deps import get_active_user_exempt_from_factor
from app.core.plugin_access_token import seal_install_token
from app.db import cohorts
from app.db import session as db_session
from app.db.session import get_system_session
from app.models.platform.user import User, UserStatus
from app.testing import in_request_tasks


def _request() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": []})


async def test_the_request_is_told_whose_it_is():
    """Some things run before the endpoint does and have only the request to
    read — the per-account rate limit key among them — so the caller is put on
    it here.

    Asked of the exempt dependency because it needs no database: both it and
    ``get_current_active_user`` resolve the caller through the same body, and
    this is that body's job."""
    request = _request()
    user = User(id=7, username="someone", discriminator=1234, status=UserStatus.active)

    assert await get_active_user_exempt_from_factor(request, user) is user
    assert request.state.user_id == 7


async def test_a_system_session_is_from_the_cohort_of_the_community_served():
    """A community in the path, or an installation token's community, chooses
    the system session's cohort; a request that names neither gets the platform
    system pool."""
    app = FastAPI()
    seen: list[object] = []

    async def probe(
        session: Annotated[AsyncSession, Depends(get_system_session)],
    ) -> None:
        seen.append(session.bind)

    app.get("/c/{community_id}/probe")(probe)
    app.get("/probe")(probe)
    token, _ = seal_install_token(
        guild_id=4,
        install_id=1,
        client_id="a-plugin",
        scopes=frozenset(),
        initiative_id=None,
    )
    installed = {"Authorization": f"Bearer {token}"}

    async with AsyncClient(
        transport=ASGITransport(app=in_request_tasks(app)), base_url="http://test"
    ) as client:
        await client.get("/c/5/probe")
        await client.get("/probe")
        await client.get("/probe", headers=installed)
        await client.get("/c/5/probe", headers=installed)

    community_5 = cohorts.system_sessionmaker(5).kw["bind"]
    community_4 = cohorts.system_sessionmaker(4).kw["bind"]
    assert community_5 is not community_4
    assert seen == [
        community_5,
        db_session.SystemSessionLocal.kw["bind"],
        community_4,
        community_4,
    ]
