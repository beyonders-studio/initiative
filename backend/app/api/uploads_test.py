"""Integration tests for authenticated /uploads/* file serving."""

from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.testing.schema_harness import route_session_to_guild
from app.core.config import settings
from app.core.security import create_upload_token
from app.services.storage import USER_CONTENT_CSP
from app.testing.factories import (
    create_access_grant,
    create_auth_provider,
    create_guild,
    create_guild_auth_policy,
    create_guild_membership,
    create_initiative,
    create_initiative_member,
    create_upload,
    create_user,
    get_auth_headers,
    get_auth_token,
)


def _uploads_dir() -> Path:
    path = Path(settings.UPLOADS_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture(autouse=True)
def _isolated_uploads_dir(tmp_path, monkeypatch):
    """Point UPLOADS_DIR at a throwaway dir so staged blobs don't litter the repo
    and never leak across tests."""
    monkeypatch.setattr(settings, "UPLOADS_DIR", str(tmp_path / "uploads"))


def _stage_upload(guild_id: int, filename: str, content: bytes = b"hello") -> None:
    """Write a blob where the per-guild storage backend serves it from
    (``UPLOADS_DIR/guild_<id>/``), via the real resolver — so tests track the
    production layout instead of hardcoding it."""
    from app.services.storage import get_guild_storage

    get_guild_storage(guild_id).write(filename, content)


async def test_upload_unauthenticated_returns_401(client: AsyncClient) -> None:
    """GET /uploads/<file> without any auth token returns 401."""
    uploads_dir = _uploads_dir()
    test_file = uploads_dir / "test_security_unauth.txt"
    test_file.write_text("secret")
    try:
        response = await client.get("/uploads/1/test_security_unauth.txt")
        assert response.status_code == 401
    finally:
        test_file.unlink(missing_ok=True)


async def test_upload_accessible_with_auth_header(
    client: AsyncClient, session: AsyncSession
) -> None:
    """GET /uploads/<file> with Authorization Bearer header returns 200."""
    from app.models.tenant.upload import Upload

    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await create_guild_membership(session, user=user, guild=guild)
    _stage_upload(guild.id, "test_auth_header.txt")
    await route_session_to_guild(session, guild.id)
    session.add(
        Upload(
            filename="test_auth_header.txt",
            created_by=user.id,
            size_bytes=5,
        )
    )
    await session.commit()

    headers = get_auth_headers(user)
    response = await client.get(
        f"/uploads/{guild.id}/test_auth_header.txt", headers=headers
    )
    assert response.status_code == 200


async def test_a_served_upload_is_cacheable_but_not_indefinitely(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A stored blob never changes under its name, so a browser may keep it —
    but the decision above it is read per request, and a long-lived entry
    would let a reader who lost access go on drawing what they fetched. So
    the window is bounded, private to that browser, and not reusable once
    stale."""
    from app.models.tenant.upload import Upload

    from app.main import UPLOAD_CACHE_SECONDS

    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await create_guild_membership(session, user=user, guild=guild)
    _stage_upload(guild.id, "test_cache_header.txt")
    await route_session_to_guild(session, guild.id)
    session.add(
        Upload(
            filename="test_cache_header.txt",
            created_by=user.id,
            size_bytes=5,
        )
    )
    await session.commit()

    response = await client.get(
        f"/uploads/{guild.id}/test_cache_header.txt", headers=get_auth_headers(user)
    )

    assert response.status_code == 200
    cache = response.headers["cache-control"]
    assert "private" in cache
    assert "must-revalidate" in cache
    assert f"max-age={UPLOAD_CACHE_SECONDS}" in cache
    # Not for a year, and never past its window: the authorization above this
    # file is a fact about now.
    assert "immutable" not in cache
    assert UPLOAD_CACHE_SECONDS <= 3600


async def test_upload_session_jwt_rejected_in_query_param(
    client: AsyncClient, session: AsyncSession
) -> None:
    """The long-lived session JWT must NOT be accepted via ?token=; only a
    scoped upload token is."""
    uploads_dir = _uploads_dir()
    test_file = uploads_dir / "test_query_session_jwt.txt"
    test_file.write_text("hello")
    try:
        user = await create_user(session)
        token = get_auth_token(user)  # full 7-day session JWT
        response = await client.get(
            f"/uploads/1/test_query_session_jwt.txt?token={token}"
        )
        assert response.status_code == 401
    finally:
        test_file.unlink(missing_ok=True)


async def test_upload_accessible_with_scoped_upload_token(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A short-lived, uploads-scoped token IS accepted via ?token=."""
    from app.models.tenant.upload import Upload

    user = await create_user(session)
    # Files are only served with a matching Upload row and
    # guild membership — the scoped token answers "who", not "may".
    guild = await create_guild(session, creator=user)
    await create_guild_membership(session, user=user, guild=guild)
    _stage_upload(guild.id, "test_query_upload_token.txt")
    await route_session_to_guild(session, guild.id)
    session.add(
        Upload(
            filename="test_query_upload_token.txt",
            created_by=user.id,
            size_bytes=5,
        )
    )
    await session.commit()
    token, _ = create_upload_token(user_id=user.id)
    response = await client.get(
        f"/uploads/{guild.id}/test_query_upload_token.txt?token={token}",
    )
    assert response.status_code == 200


async def test_scoped_upload_token_rejected_as_general_api_credential(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A scoped upload token must not authenticate general API calls."""
    user = await create_user(session)
    token, _ = create_upload_token(user_id=user.id)
    response = await client.get(
        "/api/v1/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401


async def test_issue_upload_token_endpoint(
    client: AsyncClient, session: AsyncSession
) -> None:
    """POST /auth/upload-token mints a token that opens /uploads."""
    from app.models.tenant.upload import Upload

    user = await create_user(session)
    # Serving requires a matching Upload row + membership.
    guild = await create_guild(session, creator=user)
    await create_guild_membership(session, user=user, guild=guild)
    _stage_upload(guild.id, "test_minted_token.txt")
    await route_session_to_guild(session, guild.id)
    session.add(
        Upload(
            filename="test_minted_token.txt",
            created_by=user.id,
            size_bytes=5,
        )
    )
    await session.commit()
    mint = await client.post(
        "/api/v1/auth/upload-token", headers=get_auth_headers(user)
    )
    assert mint.status_code == 200
    body = mint.json()
    assert body["token_type"] == "upload_token"
    assert body["expires_in"] > 0
    token = body["upload_token"]
    response = await client.get(
        f"/uploads/{guild.id}/test_minted_token.txt?token={token}"
    )
    assert response.status_code == 200


async def test_an_upload_token_ends_with_the_session_that_asked(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A session with two minutes left gets an upload token for two minutes at
    most, not the usual ten."""
    from datetime import timedelta

    import jwt

    from app.testing.factories import get_auth_token

    user = await create_user(session)
    access = get_auth_token(user, expires_in=timedelta(minutes=2))
    mint = await client.post(
        "/api/v1/auth/upload-token", headers={"Authorization": f"Bearer {access}"}
    )
    assert mint.status_code == 200, mint.text
    assert 0 < mint.json()["expires_in"] <= 120
    minted = jwt.decode(
        mint.json()["upload_token"], options={"verify_signature": False}
    )
    asked_with = jwt.decode(access, options={"verify_signature": False})
    assert minted["exp"] <= asked_with["exp"]


async def test_issue_upload_token_requires_auth(client: AsyncClient) -> None:
    """The mint endpoint itself requires an authenticated session."""
    response = await client.post("/api/v1/auth/upload-token")
    assert response.status_code == 401


async def test_upload_missing_file_returns_404(
    client: AsyncClient, session: AsyncSession
) -> None:
    """GET /uploads/<nonexistent> with valid auth returns 404."""
    user = await create_user(session)
    headers = get_auth_headers(user)
    response = await client.get("/uploads/1/does_not_exist_xyz.txt", headers=headers)
    assert response.status_code == 404


async def test_upload_path_traversal_rejected(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Path traversal via ../ is rejected with 404."""
    user = await create_user(session)
    headers = get_auth_headers(user)
    response = await client.get("/uploads/1/../app/core/config.py", headers=headers)
    # The client collapses ``1/..``, so the guild segment becomes a non-int (422);
    # a ``..`` that did reach the handler would fail the uploads-dir containment
    # check (404). Either way the escape is rejected and the file is never served.
    assert response.status_code in (404, 422)


async def test_upload_guild_member_can_access_file(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Authenticated guild member can access a file uploaded by that guild."""
    from app.models.tenant.upload import Upload

    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await create_guild_membership(session, user=user, guild=guild)
    _stage_upload(guild.id, "test_guild_access.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)

    await route_session_to_guild(session, guild.id)
    upload = Upload(
        filename="test_guild_access.png",
        created_by=user.id,
        size_bytes=16,
    )
    session.add(upload)
    await session.commit()

    headers = get_auth_headers(user)
    response = await client.get(
        f"/uploads/{guild.id}/test_guild_access.png", headers=headers
    )
    assert response.status_code == 200


async def test_upload_non_member_cannot_access_file(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Authenticated user NOT in the owning guild gets 403."""
    from app.models.tenant.upload import Upload

    uploads_dir = _uploads_dir()
    test_file = uploads_dir / "test_guild_forbidden.png"
    test_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
    try:
        owner = await create_user(session)
        guild = await create_guild(session, creator=owner)
        await create_guild_membership(session, user=owner, guild=guild)

        await route_session_to_guild(session, guild.id)
        upload = Upload(
            filename="test_guild_forbidden.png",
            created_by=owner.id,
            size_bytes=16,
        )
        session.add(upload)
        await session.commit()

        # A second user not in that guild — addressing the guild's upload
        # path is still rejected, since membership is validated per request
        # against the path-addressed guild.
        outsider = await create_user(session)
        headers = get_auth_headers(outsider)
        response = await client.get(
            f"/uploads/{guild.id}/test_guild_forbidden.png", headers=headers
        )
        # 404, not 403: existence is never confirmed to non-members,
        # matching the guild-schema lookup path.
        assert response.status_code == 404
    finally:
        test_file.unlink(missing_ok=True)


async def test_upload_without_db_record_returns_404(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A blob on disk with no Upload row fails closed (404), not the bytes.

    Without an Upload row there is no owning guild to authorize against, so
    the file is not served.
    """
    uploads_dir = _uploads_dir()
    test_file = uploads_dir / "test_orphan_file.txt"
    test_file.write_text("orphan content")
    try:
        user = await create_user(session)
        guild = await create_guild(session, creator=user)
        await create_guild_membership(session, user=user, guild=guild)
        headers = get_auth_headers(user)
        response = await client.get(
            f"/uploads/{guild.id}/test_orphan_file.txt", headers=headers
        )
        assert response.status_code == 404
        assert b"orphan content" not in response.content
    finally:
        test_file.unlink(missing_ok=True)


async def test_security_headers_on_api_response(client: AsyncClient):
    """Every API response must carry baseline security headers."""
    response = await client.get("/api/v1/auth/bootstrap")
    assert response.status_code == 200
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert response.headers.get("x-frame-options") == "DENY"
    assert response.headers.get("referrer-policy") == "strict-origin-when-cross-origin"


async def test_upload_row_in_guild_schema_is_served(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Regression: under schema-per-guild, Upload rows written through a guild
    request live in guild_<id>.uploads — NOT public.uploads. The serve route
    runs on the system session (search_path=public) and must still find the row
    by routing into the requester's ACTIVE guild schema (server-held context),
    otherwise every newly uploaded image 404s (failing closed turned the
    old silent fail-open into a visible regression)."""
    from sqlalchemy import text

    from app.db.schema_provisioning import guild_schema_name

    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await create_guild_membership(session, user=user, guild=guild)
    _stage_upload(guild.id, "test_guild_schema_row.txt")
    schema = guild_schema_name(guild.id)
    # Insert the row into the guild schema ONLY (mimicking the production
    # request path, where set_rls_context routes search_path there).
    await session.exec(
        text(
            f'INSERT INTO "{schema}".uploads'
            " (filename, created_by, size_bytes, created_at)"
            " VALUES (:fn, :uid, 5, now())"
        ),
        params={"fn": "test_guild_schema_row.txt", "uid": user.id},
    )
    await session.commit()
    # Prove the row can't live in public: under schema-per-guild there is no
    # public.uploads copy at all (uploads is guild-scoped), so the row exists
    # only in guild_<id>.uploads.
    public_table = (
        await session.exec(text("SELECT to_regclass('public.uploads')"))
    ).scalar()
    assert public_table is None

    response = await client.get(
        f"/uploads/{guild.id}/test_guild_schema_row.txt",
        headers=get_auth_headers(user),
    )
    assert response.status_code == 200
    assert response.text == "hello"

    # A user outside the guild fails membership validation → 404
    # (existence not confirmed), not the file — even with their flag
    # pointed at the guild.
    outsider = await create_user(session, email="outsider-schema@example.com")
    response = await client.get(
        f"/uploads/{guild.id}/test_guild_schema_row.txt",
        headers=get_auth_headers(outsider),
    )
    assert response.status_code == 404


async def test_upload_suspended_guild_member_404_grant_still_served(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A member of a SUSPENDED guild can no longer fetch its uploads (404, the
    route's fail-closed shape), while a live PAM grant still serves — the
    seam's member-only status gate."""
    from datetime import datetime, timedelta, timezone

    from app.models.platform.access_grant import AccessGrant
    from app.models.platform.guild import CommunityStatus

    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await create_guild_membership(session, user=user, guild=guild)
    initiative = await create_initiative(session, guild, user)
    _stage_upload(guild.id, "suspended_guild.txt")
    await create_upload(
        session,
        guild,
        user,
        filename="suspended_guild.txt",
        initiative_id=initiative.id,
        claimed_at=datetime.now(timezone.utc),
    )
    guild.status = CommunityStatus.suspended.value
    await session.commit()

    resp = await client.get(
        f"/uploads/{guild.id}/suspended_guild.txt", headers=get_auth_headers(user)
    )
    assert resp.status_code == 404, "member must not read a suspended guild's blobs"

    # A scoped PAM read grantee is unaffected (PAM overrides suspension).
    grantee = await create_user(session, role="support")
    now = datetime.now(timezone.utc)
    session.add(
        AccessGrant(
            user_id=grantee.id,
            guild_id=guild.id,
            access_level="read",
            status="approved",
            reason="ticket",
            requested_duration_minutes=60,
            requested_by_id=grantee.id,
            approved_by_id=user.id,
            decided_at=now,
            expires_at=now + timedelta(hours=1),
        )
    )
    await session.commit()

    resp = await client.get(
        f"/uploads/{guild.id}/suspended_guild.txt", headers=get_auth_headers(grantee)
    )
    assert resp.status_code == 200, resp.text


async def test_an_upload_is_reached_the_way_the_community_is(
    client: AsyncClient, session: AsyncSession
) -> None:
    """The media path is a way into the community like any other: it asks what
    the community asks of the session, and a settings grant, which reaches the
    community's configuration and none of its work, is not served its files."""
    from app.models.tenant.upload import Upload

    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await create_guild_membership(session, user=user, guild=guild)
    _stage_upload(guild.id, "rule.txt")
    await route_session_to_guild(session, guild.id)
    session.add(Upload(filename="rule.txt", created_by=user.id, size_bytes=5))
    await session.commit()
    path = f"/uploads/{guild.id}/rule.txt"

    settings_grantee = await create_user(session, role="support")
    await create_access_grant(
        session,
        user=settings_grantee,
        guild=guild,
        access_level="admin",
        purpose="settings",
    )
    resp = await client.get(path, headers=get_auth_headers(settings_grantee))
    assert resp.status_code == 404

    provider = await create_auth_provider(session, slug="corp")
    await create_guild_auth_policy(session, guild, provider)
    resp = await client.get(path, headers=get_auth_headers(user))
    assert resp.status_code == 401
    assert resp.json()["detail"] == "COMMUNITY_AUTH_STEP_UP_REQUIRED"


async def test_a_served_upload_is_typed_from_its_row(
    client: AsyncClient, session: AsyncSession
) -> None:
    """The response describes what the row says the file is, and a file that is
    not a raster picture is handed over as a download with scripts off — read
    from the recorded type rather than from the name the blob was stored under.
    """
    from app.models.tenant.upload import Upload

    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await create_guild_membership(session, user=user, guild=guild)
    _stage_upload(
        guild.id,
        "recorded_as_svg.png",
        b'<svg xmlns="http://www.w3.org/2000/svg"></svg>',
    )
    await route_session_to_guild(session, guild.id)
    session.add(
        Upload(
            filename="recorded_as_svg.png",
            created_by=user.id,
            size_bytes=44,
            content_type="image/svg+xml",
        )
    )
    await session.commit()

    response = await client.get(
        f"/uploads/{guild.id}/recorded_as_svg.png", headers=get_auth_headers(user)
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert response.headers["content-disposition"] == "attachment"
    assert response.headers["content-security-policy"] == USER_CONTENT_CSP
    assert response.headers["x-content-type-options"] == "nosniff"


async def test_a_served_raster_stays_inline(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A picture is still drawn where it was placed."""
    from app.models.tenant.upload import Upload

    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await create_guild_membership(session, user=user, guild=guild)
    _stage_upload(guild.id, "picture.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
    await route_session_to_guild(session, guild.id)
    session.add(
        Upload(
            filename="picture.png",
            created_by=user.id,
            size_bytes=16,
            content_type="image/png",
        )
    )
    await session.commit()

    response = await client.get(
        f"/uploads/{guild.id}/picture.png", headers=get_auth_headers(user)
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")
    assert "content-disposition" not in response.headers


async def test_a_row_without_a_recorded_type_falls_back_to_its_name(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Rows written before the type column existed carry no type; their stored
    name is all there is to go on, and it still decides the same way."""
    from app.models.tenant.upload import Upload

    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await create_guild_membership(session, user=user, guild=guild)
    for name in ("legacy.png", "legacy.svg"):
        _stage_upload(guild.id, name, b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
        await route_session_to_guild(session, guild.id)
        session.add(
            Upload(
                filename=name,
                created_by=user.id,
                size_bytes=16,
            )
        )
    await session.commit()
    headers = get_auth_headers(user)

    raster = await client.get(f"/uploads/{guild.id}/legacy.png", headers=headers)
    assert raster.status_code == 200
    assert "content-disposition" not in raster.headers

    markup = await client.get(f"/uploads/{guild.id}/legacy.svg", headers=headers)
    assert markup.status_code == 200
    assert markup.headers["content-disposition"] == "attachment"
    assert markup.headers["content-security-policy"] == USER_CONTENT_CSP


async def test_an_upload_is_reached_through_the_initiative_that_shows_it(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Not yet saved anywhere, a file is its uploader's alone. Saved into an
    initiative's content, that initiative's members read it and nobody else
    in the guild does. Saved into content of the whole guild, every member
    does."""
    from datetime import datetime, timezone

    uploader = await create_user(session)
    guild = await create_guild(session, creator=uploader)
    await create_guild_membership(session, user=uploader, guild=guild)
    member = await create_user(session)
    await create_guild_membership(session, user=member, guild=guild)
    outsider = await create_user(session)
    await create_guild_membership(session, user=outsider, guild=guild)
    initiative = await create_initiative(session, guild, uploader)
    await create_initiative_member(session, initiative, member)
    now = datetime.now(timezone.utc)
    kept = {
        "draft.txt": {},
        "initiative.txt": {"initiative_id": initiative.id, "claimed_at": now},
        "guild.txt": {"claimed_at": now},
    }
    for name, overrides in kept.items():
        _stage_upload(guild.id, name)
        await create_upload(session, guild, uploader, filename=name, **overrides)

    async def status(user, name: str) -> int:
        response = await client.get(
            f"/uploads/{guild.id}/{name}", headers=get_auth_headers(user)
        )
        return response.status_code

    assert [await status(uploader, name) for name in kept] == [200, 200, 200]
    assert [await status(member, name) for name in kept] == [404, 200, 200]
    assert [await status(outsider, name) for name in kept] == [404, 404, 200]
