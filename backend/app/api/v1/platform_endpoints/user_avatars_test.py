"""Integration tests for profile pictures.

Covers who may fetch a picture (anyone), who may set one (only its owner), and
who may take one down (its owner, or a platform moderator).
"""

import pytest
from httpx2 import AsyncClient
from sqlalchemy import text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.image_headers import validate_image
from app.db.public_rls import platform_tier, role_name
from app.models.platform.notification import Notification, NotificationType
from app.models.platform.user import User, UserRole
from app.models.platform.user_avatar import AVATAR_SPEC, UserAvatar
from app.services.platform import user_avatars as service
from app.services.platform.user_avatars_test import jpeg, png
from app.testing import drain_notices
from app.testing.factories import (
    create_federated_identity,
    create_user,
    get_auth_headers,
)


async def _assume(session, tier: str, user_id: int) -> None:
    """Drop the connection to a real platform role with a request context, so
    the policies decide rather than the superuser fixture.

    Transaction-scoped, like ``set_rls_context``: this session is an
    ``app_user`` one, which reaches Postgres through the pooler, where a
    connection is only ever this caller's for the length of a transaction. So
    the read that follows has to stay inside the one this opens — no commit
    between the two.
    """
    await session.exec(
        text(
            "SELECT set_config('app.current_user_id', :uid, true), "
            "set_config('role', :role, true)"
        ),
        params={"uid": str(user_id), "role": role_name(platform_tier(tier))},
    )


async def _upload(client: AsyncClient, headers: dict, data: bytes | None = None):
    return await client.put(
        "/api/v1/me/avatar",
        headers=headers,
        files={"file": ("avatar.png", data or png(256, 256), "image/png")},
    )


async def test_upload_stores_the_picture_and_names_it_on_the_user(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session)
    await create_federated_identity(session, user)

    response = await _upload(client, get_auth_headers(user))

    assert response.status_code == 200
    body = response.json()
    digest = validate_image(AVATAR_SPEC, png(256, 256)).sha256
    assert body["avatar_url"] == f"/api/v1/users/{user.id}/avatar/{digest}"
    # The blob does not travel in the payload any more.
    assert "avatar_base64" not in body
    # The account's own record, as /me gives it: how it confirms a change.
    assert body["has_federated_identity"] is True
    assert body["has_password"] is True
    assert body["password_required"] is True


async def test_anyone_may_fetch_a_picture_without_a_session(
    client: AsyncClient, session: AsyncSession
):
    """A name and a face are public information here, so the serve route asks
    for nothing — which is what lets the response be cached by a shared proxy
    rather than only by the browser that asked."""
    user = await create_user(session)
    await _upload(client, get_auth_headers(user))
    digest = validate_image(AVATAR_SPEC, png(256, 256)).sha256

    response = await client.get(f"/api/v1/users/{user.id}/avatar/{digest}")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.content == png(256, 256)


async def test_a_stale_digest_is_not_served_the_current_picture(
    client: AsyncClient, session: AsyncSession
):
    """The response is cached under the URL that was asked for, so a digest
    that is no longer current must not return whatever is."""
    user = await create_user(session)
    await _upload(client, get_auth_headers(user))
    stale = validate_image(AVATAR_SPEC, png(256, 256)).sha256
    await _upload(client, get_auth_headers(user), jpeg(128, 128))

    response = await client.get(f"/api/v1/users/{user.id}/avatar/{stale}")

    assert response.status_code == 404


async def test_removing_a_picture_makes_its_url_stop_working(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session)
    await _upload(client, get_auth_headers(user))
    digest = validate_image(AVATAR_SPEC, png(256, 256)).sha256

    deleted = await client.delete("/api/v1/me/avatar", headers=get_auth_headers(user))

    assert deleted.status_code == 204
    assert (
        await client.get(f"/api/v1/users/{user.id}/avatar/{digest}")
    ).status_code == 404


@pytest.mark.parametrize(
    "data,filename,status,detail",
    [
        (
            b'<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256"/>',
            "a.svg",
            400,
            "USER_AVATAR_INVALID_IMAGE",
        ),
        (png(512, 512), "big.png", 400, "USER_AVATAR_TOO_LARGE_DIMENSIONS"),
        (png(256, 100), "wide.png", 400, "USER_AVATAR_NOT_SQUARE"),
        (b"", "empty.png", 400, "IMAGE_EMPTY"),
        (
            png(256, 256, pad=AVATAR_SPEC.max_bytes),
            "heavy.png",
            413,
            "IMAGE_TOO_LARGE",
        ),
    ],
)
async def test_refused_uploads(
    client: AsyncClient,
    session: AsyncSession,
    data: bytes,
    filename: str,
    status: int,
    detail: str,
):
    user = await create_user(session)

    response = await client.put(
        "/api/v1/me/avatar",
        headers=get_auth_headers(user),
        files={"file": (filename, data, "image/png")},
    )

    assert response.status_code == status
    assert response.json()["detail"] == detail
    assert (
        await session.exec(select(UserAvatar).where(UserAvatar.user_id == user.id))
    ).first() is None


async def test_a_moderator_takes_a_picture_down_and_the_owner_is_told(
    client: AsyncClient, session: AsyncSession
):
    owner = await create_user(session)
    moderator = await create_user(session, role=UserRole.moderator)
    await _upload(client, get_auth_headers(owner))

    response = await client.delete(
        f"/api/v1/operator/users/{owner.id}/avatar", headers=get_auth_headers(moderator)
    )

    assert response.status_code == 204
    assert (
        await session.exec(select(UserAvatar).where(UserAvatar.user_id == owner.id))
    ).first() is None
    await drain_notices()
    notifications = (
        await session.exec(select(Notification).where(Notification.user_id == owner.id))
    ).all()
    assert [n.type for n in notifications] == [NotificationType.avatar_removed]


async def test_below_moderator_cannot_take_a_picture_down(
    client: AsyncClient, session: AsyncSession
):
    owner = await create_user(session)
    actor = await create_user(session)
    await _upload(client, get_auth_headers(owner))

    response = await client.delete(
        f"/api/v1/operator/users/{owner.id}/avatar", headers=get_auth_headers(actor)
    )

    assert response.status_code == 403
    assert (
        await session.exec(select(UserAvatar).where(UserAvatar.user_id == owner.id))
    ).first() is not None


async def test_a_read_payload_url_cannot_be_written_back_as_an_external_one(
    client: AsyncClient, session: AsyncSession
):
    """``avatar_url`` reads as the path this API serves and writes as a picture
    hosted elsewhere at an https address, so a read payload handed straight
    back, or any other address, is refused."""
    user = await create_user(session)

    response = await client.patch(
        "/api/v1/me",
        headers=get_auth_headers(user),
        json={"avatar_url": f"/api/v1/users/{user.id}/avatar/{'ab' * 32}"},
    )
    assert response.status_code == 422

    for elsewhere in ("http://example.com/me.png", "data:image/png;base64,AAAA"):
        response = await client.patch(
            "/api/v1/me",
            headers=get_auth_headers(user),
            json={"avatar_url": elsewhere},
        )
        assert response.status_code == 422


async def test_setting_an_external_picture_drops_the_uploaded_one(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session)
    await _upload(client, get_auth_headers(user))

    response = await client.patch(
        "/api/v1/me",
        headers=get_auth_headers(user),
        json={"avatar_url": "https://idp.example/pic.png"},
    )

    assert response.status_code == 200
    assert response.json()["avatar_url"] == "https://idp.example/pic.png"
    assert (
        await session.exec(select(UserAvatar).where(UserAvatar.user_id == user.id))
    ).first() is None


# --- the row policies, exercised under the real privilege boundary -----------


async def test_the_request_path_cannot_write_someone_elses_picture(
    client: AsyncClient, session: AsyncSession, role_session
):
    """Own-row is a database rule, not an endpoint check.

    Asserted as ``app_user`` with another user's id in the request context, so
    a handler that forgot to scope the write would still be stopped here.
    """
    owner = await create_user(session)
    other = await create_user(session)
    await _upload(client, get_auth_headers(owner))

    s = await role_session("app_user")
    await _assume(s, "member", other.id)

    deleted = await s.exec(
        text("DELETE FROM public.user_avatars WHERE user_id = :uid"),
        params={"uid": owner.id},
    )
    updated = await s.exec(
        text("UPDATE public.user_avatars SET sha256 = 'x' WHERE user_id = :uid"),
        params={"uid": owner.id},
    )
    await s.commit()

    assert deleted.rowcount == 0
    assert updated.rowcount == 0
    assert (
        await session.exec(select(UserAvatar).where(UserAvatar.user_id == owner.id))
    ).first() is not None


async def test_the_request_path_may_read_any_picture(
    client: AsyncClient, session: AsyncSession, role_session
):
    """Reads are deliberately unconditional — the picture is public."""
    owner = await create_user(session)
    other = await create_user(session)
    await _upload(client, get_auth_headers(owner))

    s = await role_session("app_user")
    await _assume(s, "member", other.id)

    found = (
        await s.exec(
            text("SELECT sha256 FROM public.user_avatars WHERE user_id = :uid"),
            params={"uid": owner.id},
        )
    ).first()

    assert found is not None


async def test_deleting_a_user_takes_their_picture_with_them(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session)
    await _upload(client, get_auth_headers(user))

    await session.exec(
        text("DELETE FROM public.users WHERE id = :uid"), params={"uid": user.id}
    )
    await session.commit()

    assert (
        await session.exec(select(UserAvatar).where(UserAvatar.user_id == user.id))
    ).first() is None


async def test_anonymizing_a_user_leaves_no_face(
    client: AsyncClient, session: AsyncSession
):
    from app.services.platform import users as users_service

    user = await create_user(session)
    await _upload(client, get_auth_headers(user))

    await users_service.soft_delete_user(session, user.id)
    await session.commit()

    assert (
        await session.exec(select(UserAvatar).where(UserAvatar.user_id == user.id))
    ).first() is None
    refreshed = (await session.exec(select(User).where(User.id == user.id))).first()
    assert refreshed is not None and refreshed.avatar_url is None


# --- the three things a review caught -----------------------------------------


async def test_storing_does_not_depend_on_what_the_read_saw(
    session: AsyncSession, monkeypatch
):
    """The row is keyed by user alone, so the write must not be conditional on
    a read that another request can invalidate.

    Two uploads landing together — a double-click, two tabs — both looked,
    both found nothing, and the second lost to the primary key. The stale read
    is forced here rather than raced for, so this fails deterministically if
    the write stops being an upsert.
    """
    user = await create_user(session)
    await service.store_avatar(
        session, user=user, avatar=validate_image(AVATAR_SPEC, png(256, 256))
    )
    await session.commit()

    # The picture is there, but this request's read happened before it landed.
    async def saw_nothing(*args, **kwargs):
        return None

    monkeypatch.setattr(service, "get_avatar", saw_nothing)

    await service.store_avatar(
        session, user=user, avatar=validate_image(AVATAR_SPEC, jpeg(256, 256))
    )
    await session.commit()

    rows = (
        await session.exec(select(UserAvatar).where(UserAvatar.user_id == user.id))
    ).all()
    assert len(rows) == 1
    # Last writer wins, which is what "replace my picture" means.
    assert rows[0].content_type == "image/jpeg"


async def test_a_stored_picture_is_named_on_the_user_row(
    client: AsyncClient, session: AsyncSession
):
    """``users.avatar_url`` is what every payload naming a person carries, so a
    ``user_avatars`` row nothing points at is a picture that has disappeared.
    This is the invariant the backfill has to preserve too."""
    user = await create_user(session)
    await _upload(client, get_auth_headers(user))

    row = (
        await session.exec(select(UserAvatar).where(UserAvatar.user_id == user.id))
    ).first()
    stored = (await session.exec(select(User).where(User.id == user.id))).first()

    assert row is not None and stored is not None
    assert stored.avatar_url == f"/api/v1/users/{user.id}/avatar/{row.sha256}"
    # And that URL actually serves.
    assert (await client.get(stored.avatar_url)).status_code == 200


async def test_a_takedown_and_its_notice_are_one_write(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """The person being told is part of the takedown, not a step after it."""
    from app.services.platform import notice_outbox

    owner = await create_user(session)
    moderator = await create_user(session, role=UserRole.moderator)
    await _upload(client, get_auth_headers(owner))

    async def boom(*args, **kwargs):
        raise RuntimeError("notification store is down")

    monkeypatch.setattr(notice_outbox, "enqueue", boom)

    with pytest.raises(RuntimeError):
        await client.delete(
            f"/api/v1/operator/users/{owner.id}/avatar",
            headers=get_auth_headers(moderator),
        )

    # The picture is still there: it is not taken down without the notice.
    assert (
        await session.exec(select(UserAvatar).where(UserAvatar.user_id == owner.id))
    ).first() is not None
