"""Integration tests for /api/v1/user-view-preferences."""

from __future__ import annotations

from httpx2 import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.user_view_preference import MAX_VALUE_JSON_BYTES
from app.testing.factories import create_user, get_auth_headers


async def test_put_overwrites_and_reads_back_only_your_own(
    client: AsyncClient, session: AsyncSession
):
    """A PUT overwrites what was kept under its key, and user A's PUT does not
    surface in user B's GET."""
    user_a = await create_user(session, email="a@example.com")
    user_b = await create_user(session, email="b@example.com")
    headers = get_auth_headers(user_a)

    empty = await client.get("/api/v1/user-view-preferences", headers=headers)
    assert empty.status_code == 200
    assert empty.json() == {"items": {}}

    kept = {"statusFilters": ["todo", "doing"], "showArchived": False}
    for value in ({"v": 1}, kept):
        put_resp = await client.put(
            "/api/v1/user-view-preferences/project:42:tasks",
            headers=headers,
            json={"value": value},
        )
        assert put_resp.status_code == 204

    a_get = await client.get("/api/v1/user-view-preferences", headers=headers)
    b_get = await client.get(
        "/api/v1/user-view-preferences", headers=get_auth_headers(user_b)
    )
    assert a_get.status_code == 200
    assert a_get.json() == {"items": {"project:42:tasks": kept}}
    assert b_get.json() == {"items": {}}


async def test_scope_key_pattern_rejects_invalid(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session)
    headers = get_auth_headers(user)
    # URL-safe characters that fall outside our allowed pattern. (Slashes
    # would short-circuit at the routing layer with a 405 — also fine,
    # but tested separately by routing itself.)
    bad_keys = [
        "bad@key",
        "bang!key",
        "star*key",
        "plus+key",
        "tilde~key",
        # MAX is 128.
        "x" * 129,
    ]
    for key in bad_keys:
        resp = await client.put(
            f"/api/v1/user-view-preferences/{key}",
            headers=headers,
            json={"value": {}},
        )
        assert resp.status_code == 422, (
            f"expected 422 for key={key!r}, got {resp.status_code}"
        )


async def test_a_communitys_view_is_not_kept_with_the_account(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session)
    headers = get_auth_headers(user)
    refused = await client.put(
        "/api/v1/user-view-preferences/view:5:project:12",
        headers=headers,
        json={"value": {}},
    )
    assert refused.status_code == 400
    assert refused.json()["detail"] == "VIEW_KEPT_IN_THE_COMMUNITY"
    kept = await client.put(
        "/api/v1/user-view-preferences/view:me:tasks",
        headers=headers,
        json={"value": {}},
    )
    assert kept.status_code == 204


async def test_value_size_cap(client: AsyncClient, session: AsyncSession):
    user = await create_user(session)
    headers = get_auth_headers(user)

    # Just under the cap should pass.
    big_but_ok = {"data": "a" * (MAX_VALUE_JSON_BYTES - 64)}
    resp = await client.put(
        "/api/v1/user-view-preferences/big-ok",
        headers=headers,
        json={"value": big_but_ok},
    )
    assert resp.status_code == 204

    # Over the cap must 422.
    too_big = {"data": "a" * (MAX_VALUE_JSON_BYTES + 1)}
    resp = await client.put(
        "/api/v1/user-view-preferences/too-big",
        headers=headers,
        json={"value": too_big},
    )
    assert resp.status_code == 422
