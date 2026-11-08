"""Integration tests for /api/v1/user-view-preferences."""

from __future__ import annotations

from httpx2 import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.user_view_preference import MAX_VALUE_JSON_BYTES
from app.testing.factories import create_user, get_auth_headers


async def test_list_empty(client: AsyncClient, session: AsyncSession):
    user = await create_user(session)
    response = await client.get(
        "/api/v1/user-view-preferences", headers=get_auth_headers(user)
    )
    assert response.status_code == 200
    assert response.json() == {"items": {}}


async def test_put_then_get_roundtrip(client: AsyncClient, session: AsyncSession):
    user = await create_user(session)
    headers = get_auth_headers(user)
    payload = {"value": {"statusFilters": ["todo", "doing"], "showArchived": False}}
    put_resp = await client.put(
        "/api/v1/user-view-preferences/my-tasks", headers=headers, json=payload
    )
    assert put_resp.status_code == 204

    get_resp = await client.get("/api/v1/user-view-preferences", headers=headers)
    assert get_resp.status_code == 200
    assert get_resp.json() == {"items": {"my-tasks": payload["value"]}}


async def test_put_overwrites_existing(client: AsyncClient, session: AsyncSession):
    user = await create_user(session)
    headers = get_auth_headers(user)
    await client.put(
        "/api/v1/user-view-preferences/my-tasks",
        headers=headers,
        json={"value": {"v": 1}},
    )
    await client.put(
        "/api/v1/user-view-preferences/my-tasks",
        headers=headers,
        json={"value": {"v": 2}},
    )
    get_resp = await client.get("/api/v1/user-view-preferences", headers=headers)
    assert get_resp.json() == {"items": {"my-tasks": {"v": 2}}}


async def test_cross_user_isolation_via_application_filter(
    client: AsyncClient, session: AsyncSession
):
    """User A's PUT must not surface in user B's GET.

    Note: the test `session` fixture connects as the database superuser,
    which bypasses RLS entirely. What this test actually exercises is the
    application-level ``WHERE user_id == current_user.id`` filter in the
    endpoint. The DB-level ``user_view_preferences_self_scope`` policy is
    not covered here — verifying it requires a fixture that connects as
    ``app_user`` (the role RLS is forced against).
    """
    user_a = await create_user(session, email="a@example.com")
    user_b = await create_user(session, email="b@example.com")

    await client.put(
        "/api/v1/user-view-preferences/project:42:tasks",
        headers=get_auth_headers(user_a),
        json={"value": {"belongs_to": "A"}},
    )

    a_get = await client.get(
        "/api/v1/user-view-preferences", headers=get_auth_headers(user_a)
    )
    b_get = await client.get(
        "/api/v1/user-view-preferences", headers=get_auth_headers(user_b)
    )

    assert a_get.json() == {"items": {"project:42:tasks": {"belongs_to": "A"}}}
    assert b_get.json() == {"items": {}}


async def test_scope_key_pattern_rejects_invalid(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session)
    headers = get_auth_headers(user)
    # URL-safe characters that fall outside our allowed pattern. (Slashes
    # would short-circuit at the routing layer with a 405 — also fine,
    # but tested separately by routing itself.)
    bad_keys = ["bad@key", "bang!key", "star*key", "plus+key", "tilde~key"]
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


async def test_scope_key_length_cap(client: AsyncClient, session: AsyncSession):
    user = await create_user(session)
    too_long = "x" * 129  # MAX is 128
    resp = await client.put(
        f"/api/v1/user-view-preferences/{too_long}",
        headers=get_auth_headers(user),
        json={"value": {}},
    )
    assert resp.status_code == 422


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
