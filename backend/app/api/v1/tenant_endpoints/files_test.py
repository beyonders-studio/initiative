"""
Integration tests for file endpoints — create with permissions.
"""

from pathlib import Path
from types import SimpleNamespace
import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import Tool
from app.core.file_types import FileType
from app.models.tenant.file import (
    File,
)
from app.models.platform.guild import CommunityRole
from app.models.tenant.initiative import InitiativeRoleModel
from app.models.tenant.resource_grant import ResourceAccessLevel
from app.core.search import SearchEntityType
from app.services import editor_engine
from app.services.storage import USER_CONTENT_CSP
from app.services.tenant.collaboration import collaboration_manager
from app.testing import (
    guild_of,
    create_file,
    create_initiative,
    create_resource_grant,
    lexical_body,
    route_as,
)


async def _create_uploaded_file(
    session: AsyncSession,
    *,
    initiative,
    owner,
    filename: str,
) -> File:
    """An uploaded file with a dummy file on disk, made the way every
    test file is made: through the factory, which routes by the
    initiative and writes the owner grant."""
    # Stage the blob via the real resolver so it lands where the serve path reads
    # it (UPLOADS_DIR/guild_<id>/), and use the canonical guild-scoped URL.
    from app.services.storage import get_guild_storage

    get_guild_storage(guild_of(initiative)).write(filename, b"%PDF-1.4 test")
    content_type = {".html": "text/html", ".svg": "image/svg+xml"}.get(
        Path(filename).suffix, "application/pdf"
    )

    return await create_file(
        session,
        initiative,
        owner,
        name="Test File Doc",
        file_url=f"/uploads/{guild_of(initiative)}/{filename}",
        original_filename=filename,
        file_content_type=content_type,
        file_size=13,
    )


async def test_create_refuses_when_files_are_switched_off(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Files are a tool like any other now: an initiative that has turned
    them off refuses to hold one, and names the reason instead of failing at
    the row."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    a.initiative.files_enabled = False
    session.add(a.initiative)
    await session.commit()

    response = await client.post(
        a.g("/files/"),
        headers=a.headers,
        json={"name": "Nope", "initiative_id": a.initiative.id},
    )

    assert response.status_code == 403
    assert response.json() == Tool.file.disabled().body


async def test_a_guild_admin_does_not_list_files_of_a_switched_off_initiative(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The mirror of the projects case: the RLS leg keeps a guild admin and a
    PAM reader able to reach the rows for maintenance, and the list declines to
    be the place that shows them."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    doc = await create_file(session, a.initiative, a.user)

    listed = await client.get(a.g("/files/"), headers=a.headers)
    assert listed.status_code == 200
    assert doc.id in [d["id"] for d in listed.json()["items"]]

    a.initiative.files_enabled = False
    session.add(a.initiative)
    await session.commit()

    listed = await client.get(a.g("/files/"), headers=a.headers)
    assert listed.status_code == 200
    assert listed.json()["items"] == []


async def test_create_file_with_permissions(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test creating a file with both role and user permissions."""
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    member = await acting_user(
        guild_role=CommunityRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )
    initiative = admin.initiative

    # Find the member role
    result = await session.exec(
        select(InitiativeRoleModel).where(
            InitiativeRoleModel.initiative_id == initiative.id,
            InitiativeRoleModel.name == "member",
        )
    )
    member_role = result.one()

    payload = {
        "name": "Doc With Permissions",
        "initiative_id": initiative.id,
        "grants": [
            {"role_id": member_role.id, "level": "read"},
            {"user_id": member.user.id, "level": "write"},
        ],
    }

    response = await client.post(
        admin.g("/files/"), headers=admin.headers, json=payload
    )

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Doc With Permissions"

    grants = data["grants"]
    # Owner grant + member's write user grant.
    user_grants = {g["user_id"]: g["level"] for g in grants if g["user_id"]}
    assert user_grants.get(admin.user.id) == "owner"
    assert user_grants.get(member.user.id) == "write"
    # Role grant for the member role at read.
    role_grants = [g for g in grants if g["role_id"] is not None]
    assert len(role_grants) == 1
    assert role_grants[0]["role_id"] == member_role.id
    assert role_grants[0]["level"] == "read"


async def test_create_file_defaults_to_all_members_viewer(
    client: AsyncClient, acting_user
):
    """Omitting `grants` defaults to Viewer for all initiative members (+ owner)."""
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)

    payload = {
        "name": "Doc Default Share",
        "initiative_id": admin.initiative.id,
    }

    response = await client.post(
        admin.g("/files/"), headers=admin.headers, json=payload
    )

    assert response.status_code == 201
    data = response.json()
    assert any(
        g["user_id"] == admin.user.id and g["level"] == "owner" for g in data["grants"]
    )
    assert any(
        g["all_initiative_members"] and g["level"] == "read" for g in data["grants"]
    )


# ---------------------------------------------------------------------------
# Duplicate / copy / create-from-template tests
# ---------------------------------------------------------------------------


async def test_duplicate_is_held_to_create_and_keeps_the_sources_sharing(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A duplicate is a new file: its maker needs the right to create
    files, its name must be free, and it is shared with the same people
    as the file it copies."""
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    writer = await acting_user(
        guild_role=CommunityRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )
    doc = await create_file(session, owner.initiative, owner.user, name="Plan")
    await create_resource_grant(
        session, doc, user=writer.user, level=ResourceAccessLevel.write
    )
    await create_resource_grant(session, doc, all_initiative_members=True)

    refused = await client.post(
        writer.g(f"/files/{doc.id}/duplicate"), headers=writer.headers
    )
    assert refused.status_code == 403
    assert refused.json() == Tool.file.create_denied().body

    duplicated = await client.post(
        owner.g(f"/files/{doc.id}/duplicate"), headers=owner.headers
    )
    assert duplicated.status_code == 201, duplicated.text
    assert duplicated.json()["name"] == "Plan (Copy)"
    assert {
        (g["user_id"], g["all_initiative_members"], g["level"])
        for g in duplicated.json()["grants"]
    } == {
        (owner.user.id, False, "owner"),
        (writer.user.id, False, "write"),
        (None, True, "read"),
    }

    again = await client.post(
        owner.g(f"/files/{doc.id}/duplicate"), headers=owner.headers
    )
    assert again.status_code == 409
    assert again.json()["detail"] == "FILE_NAME_ALREADY_EXISTS"


# ---------------------------------------------------------------------------
# Download endpoint tests
# ---------------------------------------------------------------------------


async def test_download_owner_can_download(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    """File owner can download their uploaded file."""
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)

    doc = await _create_uploaded_file(
        session, initiative=owner.initiative, owner=owner.user, filename="dl_owner.pdf"
    )
    response = await client.get(
        owner.g(f"/files/{doc.id}/download"), headers=owner.headers
    )
    assert response.status_code == 200
    assert "attachment" in response.headers.get("content-disposition", "")
    assert response.headers.get("x-content-type-options") == "nosniff"


async def test_download_unauthenticated_returns_401(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    """Unauthenticated request returns 401."""
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)

    doc = await _create_uploaded_file(
        session, initiative=owner.initiative, owner=owner.user, filename="dl_unauth.pdf"
    )
    response = await client.get(owner.g(f"/files/{doc.id}/download"))
    assert response.status_code == 401


async def test_download_guild_member_without_permission_returns_403(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    """Guild member with no file permission gets 403."""
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    other = await acting_user(
        guild_role=CommunityRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )

    doc = await _create_uploaded_file(
        session,
        initiative=owner.initiative,
        owner=owner.user,
        filename="dl_no_perm.pdf",
    )
    response = await client.get(
        other.g(f"/files/{doc.id}/download"), headers=other.headers
    )
    assert response.status_code == 403


async def test_version_download_answers_like_the_file_download(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    """Both download routes load the file the same way, so an initiative
    member the sharing does not reach is answered the same way by each."""
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    other = await acting_user(
        guild_role=CommunityRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )

    doc = await _create_uploaded_file(
        session,
        initiative=owner.initiative,
        owner=owner.user,
        filename="dl_version_no_perm.pdf",
    )
    current = await client.get(
        other.g(f"/files/{doc.id}/download"), headers=other.headers
    )
    stored = await client.get(
        other.g(f"/files/{doc.id}/versions/1/download"),
        headers=other.headers,
    )
    assert current.status_code == 403
    assert stored.status_code == current.status_code


async def test_download_non_guild_member_returns_404(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    """User from a different guild gets 404 (file not visible)."""
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    outsider = await acting_user("member")

    doc = await _create_uploaded_file(
        session,
        initiative=owner.initiative,
        owner=owner.user,
        filename="dl_outsider.pdf",
    )
    response = await client.get(
        owner.g(f"/files/{doc.id}/download"), headers=outsider.headers
    )
    assert response.status_code == 404


async def test_download_read_permission_grants_access(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    """User with explicit read permission can download."""
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    reader = await acting_user(
        guild_role=CommunityRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )

    doc = await _create_uploaded_file(
        session, initiative=owner.initiative, owner=owner.user, filename="dl_reader.pdf"
    )
    await create_resource_grant(session, doc, user=reader.user)

    response = await client.get(
        owner.g(f"/files/{doc.id}/download"), headers=reader.headers
    )
    assert response.status_code == 200


async def test_download_inline_returns_no_attachment_header(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    """?inline=1 serves the file without Content-Disposition: attachment."""
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)

    doc = await _create_uploaded_file(
        session, initiative=owner.initiative, owner=owner.user, filename="dl_inline.pdf"
    )
    response = await client.get(
        owner.g(f"/files/{doc.id}/download?inline=1"),
        headers={**owner.headers, "Sec-Fetch-Dest": "document"},
    )
    assert response.status_code == 200
    assert "attachment" not in response.headers.get("content-disposition", "")
    assert "sandbox" not in response.headers.get("content-security-policy", "")


@pytest.mark.parametrize("filename", ["dl_inline.html", "dl_inline.svg"])
async def test_download_inline_html_svg_is_same_origin_framable_but_scriptless(
    client: AsyncClient, session: AsyncSession, acting_user, filename: str
) -> None:
    """Inline HTML/SVG can be framed by the same-origin viewer but cannot run scripts."""
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)

    doc = await _create_uploaded_file(
        session, initiative=owner.initiative, owner=owner.user, filename=filename
    )
    response = await client.get(
        owner.g(f"/files/{doc.id}/download?inline=1"),
        headers=owner.headers,
    )
    assert response.status_code == 200
    # Same-origin framing allowed (overrides the global DENY middleware)
    assert response.headers.get("x-frame-options") == "SAMEORIGIN"
    assert response.headers.get("content-security-policy") == (
        f"{USER_CONTENT_CSP}; frame-ancestors 'self'"
    )
    assert "attachment" not in response.headers.get("content-disposition", "")

    opened = await client.get(
        owner.g(f"/files/{doc.id}/download?inline=1"),
        headers={**owner.headers, "Sec-Fetch-Dest": "document"},
    )
    assert "attachment" in opened.headers.get("content-disposition", "")


@pytest.mark.parametrize("filename", ["dl_attach.html", "dl_attach.svg"])
async def test_download_non_inline_html_svg_keeps_global_deny(
    client: AsyncClient, session: AsyncSession, acting_user, filename: str
) -> None:
    """Non-inline HTML/SVG downloads stay attachments and do not relax framing."""
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)

    doc = await _create_uploaded_file(
        session, initiative=owner.initiative, owner=owner.user, filename=filename
    )
    response = await client.get(
        owner.g(f"/files/{doc.id}/download"), headers=owner.headers
    )
    assert response.status_code == 200
    # Served as an attachment; the framing relaxation must not apply here
    assert "attachment" in response.headers.get("content-disposition", "")
    assert response.headers.get("x-frame-options") != "SAMEORIGIN"
    assert response.headers.get("content-security-policy") == USER_CONTENT_CSP


async def test_download_native_file_returns_404(
    client: AsyncClient, acting_user
) -> None:
    """A native file (not an upload) returns 404 from the download endpoint."""
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)

    response = await client.post(
        owner.g("/files/"),
        headers=owner.headers,
        json={"name": "Native Doc", "initiative_id": owner.initiative.id},
    )
    assert response.status_code == 201
    doc_id = response.json()["id"]

    response = await client.get(
        owner.g(f"/files/{doc_id}/download"), headers=owner.headers
    )
    assert response.status_code == 404


async def _words(state: bytes) -> str:
    rendered = await editor_engine.render(state)
    return "".join(
        node["text"]
        for block in rendered["root"]["children"]
        for node in block["children"]
    )


async def test_update_content_is_written_into_yjs_state(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    """PATCH /files/{id} with content writes it into the stored Yjs state,
    which the next collaborative session opens on."""
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    before, after = lexical_body("before"), lexical_body("after")
    doc = await create_file(
        session,
        owner.initiative,
        owner.user,
        content=before,
        yjs_state=await editor_engine.bootstrap(before),
    )

    patch_resp = await client.patch(
        owner.g(f"/files/{doc.id}"), headers=owner.headers, json={"content": after}
    )
    assert patch_resp.status_code == 200

    await session.refresh(doc, ["yjs_state"])
    assert doc.yjs_state is not None
    rendered = await editor_engine.render(doc.yjs_state)
    (paragraph,) = rendered["root"]["children"]
    assert [node["text"] for node in paragraph["children"]] == ["after"]


async def test_a_write_naming_a_version_since_changed_is_refused(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    doc = await create_file(
        session, owner.initiative, owner.user, content=lexical_body("first")
    )
    url = owner.g(f"/files/{doc.id}")
    version = (await client.get(url, headers=owner.headers)).json()["content_version"]

    taken = await client.patch(
        url,
        headers=owner.headers,
        json={"content": lexical_body("second"), "content_version": version},
    )
    stale = await client.patch(
        url,
        headers=owner.headers,
        json={"content": lexical_body("third"), "content_version": version},
    )

    assert taken.status_code == 200, taken.text
    assert taken.json()["content_version"] != version
    assert stale.status_code == 409
    assert stale.json()["detail"] == "CONTENT_CHANGED"


async def test_a_versioned_write_goes_into_a_live_session(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
) -> None:
    """A write naming the session's current content reaches the room, where
    the editors are; one naming no version is still refused."""
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    doc = await create_file(
        session, owner.initiative, owner.user, content=lexical_body("in the session")
    )
    routed = await role_session("app_user")
    await route_as(routed, user_id=owner.user.id, guild_id=owner.guild.id)
    room = await collaboration_manager.get_or_create_room(
        owner.guild.id, SearchEntityType.file.value, doc.id, routed
    )
    room.hold()  # somebody is in it
    try:
        url = owner.g(f"/files/{doc.id}")
        read = (await client.get(url, headers=owner.headers)).json()

        unversioned = await client.patch(
            url, headers=owner.headers, json={"content": lexical_body("ignored")}
        )
        versioned = await client.patch(
            url,
            headers=owner.headers,
            json={
                "content": lexical_body("from the API"),
                "content_version": read["content_version"],
            },
        )
        stale = await client.patch(
            url,
            headers=owner.headers,
            json={
                "content": lexical_body("from a second writer"),
                "content_version": read["content_version"],
            },
        )

        assert unversioned.status_code == 409
        assert unversioned.json()["detail"] == "LIVE_SESSION_OWNS_CONTENT"
        assert versioned.status_code == 200, versioned.text
        assert stale.status_code == 409
        assert stale.json()["detail"] == "CONTENT_CHANGED"
        assert await _words(room.get_state()) == "from the API"
    finally:
        room.release()
        await collaboration_manager.leave(
            owner.guild.id, SearchEntityType.file.value, doc.id
        )


async def test_create_whiteboard_file(client: AsyncClient, acting_user) -> None:
    """POST /files/ with file_type='excalidraw' creates a whiteboard doc.

    The response's content should be the empty Excalidraw scene shape
    ({elements, appState, files}) rather than the Lexical root shape. This
    guards against normalize_file_content corrupting whiteboard payloads.
    An uploaded file is not made here: it comes from uploading its file.
    """
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)

    response = await client.post(
        owner.g("/files/"),
        headers=owner.headers,
        json={
            "name": "My Whiteboard",
            "initiative_id": owner.initiative.id,
            "file_type": "excalidraw",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["file_type"] == "excalidraw"
    assert body["content"] == {"elements": [], "appState": {}, "files": {}}
    # Ensure the Lexical shape was NOT force-injected
    assert "root" not in body["content"]

    file_doc = await client.post(
        owner.g("/files/"),
        headers=owner.headers,
        json={
            "name": "Not a file",
            "initiative_id": owner.initiative.id,
            "file_type": "pdf",
        },
    )
    assert file_doc.status_code == 422


def test_normalize_whiteboard_preserves_shape() -> None:
    """normalize_file_content must not inject Lexical root into whiteboards."""
    from app.services.tenant.files import normalize_file_content

    scene = {
        "elements": [{"id": "el1", "type": "rectangle"}],
        "appState": {"viewBackgroundColor": "#ffffff"},
        "files": {},
    }
    result = normalize_file_content(scene, file_type=FileType.excalidraw)
    assert result["elements"] == scene["elements"]
    assert result["appState"] == scene["appState"]
    assert result["files"] == scene["files"]
    assert "root" not in result


def test_normalize_native_still_injects_root() -> None:
    """Regression: native docs still get a root shape when content is empty."""
    from app.services.tenant.files import normalize_file_content

    result = normalize_file_content({}, file_type=FileType.lexical)
    assert "root" in result
    assert isinstance(result["root"], dict)


async def test_create_smart_link_file(client: AsyncClient, acting_user) -> None:
    """POST /files/ with file_type='url' stores only the URL,
    and the list reports the URL without the body."""
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    url = "https://www.figma.com/design/abc/Example"

    response = await client.post(
        owner.g("/files/"),
        headers=owner.headers,
        json={
            "name": "Design file",
            "initiative_id": owner.initiative.id,
            "file_type": "url",
            "content": {"url": url},
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["file_type"] == "url"
    assert body["content"] == {"url": url}
    assert body["smart_link_url"] == url

    listed = await client.get(owner.g("/files/"), headers=owner.headers)
    assert listed.status_code == 200, listed.text
    [row] = listed.json()["items"]
    assert row["smart_link_url"] == url
    assert "content" not in row


async def test_create_smart_link_rejects_missing_url(
    client: AsyncClient, acting_user
) -> None:
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)

    response = await client.post(
        owner.g("/files/"),
        headers=owner.headers,
        json={
            "name": "Bad link",
            "initiative_id": owner.initiative.id,
            "file_type": "url",
            "content": {},
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "FILE_SMART_LINK_URL_REQUIRED"


async def test_create_smart_link_rejects_non_http_url(
    client: AsyncClient, acting_user
) -> None:
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)

    response = await client.post(
        owner.g("/files/"),
        headers=owner.headers,
        json={
            "name": "Bad scheme",
            "initiative_id": owner.initiative.id,
            "file_type": "url",
            "content": {"url": "ftp://example.com/file"},
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "FILE_SMART_LINK_URL_INVALID"


def test_normalize_smart_link_returns_only_url() -> None:
    """normalize_file_content should strip any extra fields."""
    from app.services.tenant.files import normalize_file_content

    result = normalize_file_content(
        {"url": "https://youtu.be/dQw4w9WgXcQ", "extra": "ignored"},
        file_type=FileType.url,
    )
    assert result == {"url": "https://youtu.be/dQw4w9WgXcQ"}


def test_normalize_smart_link_raises_on_missing_url() -> None:
    """normalize_file_content should raise a domain error for missing URL,
    not an HTTPException (transport concern lives at the endpoint layer)."""
    from app.services.tenant.files import (
        FileContentError,
        normalize_file_content,
    )

    with pytest.raises(FileContentError) as exc_info:
        normalize_file_content({}, file_type=FileType.url)
    assert exc_info.value.code == "FILE_SMART_LINK_URL_REQUIRED"

    with pytest.raises(FileContentError) as exc_info:
        normalize_file_content(None, file_type=FileType.url)
    assert exc_info.value.code == "FILE_SMART_LINK_URL_REQUIRED"


def test_normalize_smart_link_raises_on_bad_scheme() -> None:
    from app.services.tenant.files import (
        FileContentError,
        normalize_file_content,
    )

    with pytest.raises(FileContentError) as exc_info:
        normalize_file_content(
            {"url": "ftp://example.com/file"},
            file_type=FileType.url,
        )
    assert exc_info.value.code == "FILE_SMART_LINK_URL_INVALID"


def test_file_content_error_is_value_error() -> None:
    """FileContentError inherits from ValueError so generic
    ``except ValueError`` handlers still work."""
    from app.services.tenant.files import FileContentError

    exc = FileContentError("SOME_CODE")
    assert isinstance(exc, ValueError)
    assert exc.code == "SOME_CODE"


async def test_list_files_filters_by_template_and_type(
    client: AsyncClient, session, acting_user
):
    """``is_template``/``file_type`` narrow the listing in SQL so the
    template picker doesn't walk the whole corpus."""
    actor = await acting_user(guild_role=CommunityRole.admin, initiative=True)

    native_template = await create_file(
        session, actor.initiative, actor.user, is_template=True
    )
    whiteboard_template = await create_file(
        session,
        actor.initiative,
        actor.user,
        is_template=True,
        file_type=FileType.excalidraw,
    )
    plain = await create_file(session, actor.initiative, actor.user)

    response = await client.get(
        actor.g("/files/"),
        headers=actor.headers,
        params={"is_template": True},
    )
    assert response.status_code == 200
    assert {item["id"] for item in response.json()["items"]} == {
        native_template.id,
        whiteboard_template.id,
    }

    response = await client.get(
        actor.g("/files/"),
        headers=actor.headers,
        params={"is_template": True, "file_type": "lexical"},
    )
    assert response.status_code == 200
    data = response.json()
    assert [item["id"] for item in data["items"]] == [native_template.id]
    assert data["total_count"] == 1

    response = await client.get(
        actor.g("/files/"),
        headers=actor.headers,
        params={"is_template": True, "kind": "whiteboard"},
    )
    assert [item["id"] for item in response.json()["items"]] == [whiteboard_template.id]

    response = await client.get(
        actor.g("/files/"),
        headers=actor.headers,
        params={"is_template": False},
    )
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [plain.id]


async def test_a_list_reads_its_files_in_one_statement(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Each uploaded file in a list reports its current version's file, read
    for the whole page at once rather than once per row."""
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    actor = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    names = [f"page-{n}.pdf" for n in range(3)]
    for name in names:
        await create_file(
            session,
            actor.initiative,
            actor.user,
            name=name,
            file_url=f"/uploads/{guild_of(actor.initiative)}/{name}",
            original_filename=name,
        )
    url = actor.g("/files/")
    sent: list[str] = []

    def record(_conn, _cursor, statement, _params, _context, _many) -> None:
        sent.append(statement)

    event.listen(Engine, "before_cursor_execute", record)
    try:
        listed = await client.get(
            url, headers=actor.headers, params={"file_type": "pdf"}
        )
    finally:
        event.remove(Engine, "before_cursor_execute", record)
    assert listed.status_code == 200, listed.text
    items = listed.json()["items"]
    assert sorted(item["original_filename"] for item in items) == names
    assert len([s for s in sent if "FROM file_versions" in s]) == 1, sent


async def test_the_tag_tree_narrows_by_file_type(
    client: AsyncClient, session, acting_user
):
    """The one filter of its own the counts route reads for files: the
    tag tree honors the type the list beside it is narrowed to."""
    actor = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await create_file(session, actor.initiative, actor.user, is_template=True)
    await create_file(
        session,
        actor.initiative,
        actor.user,
        is_template=True,
        file_type=FileType.excalidraw,
    )
    await create_file(session, actor.initiative, actor.user)

    async def untagged(**params) -> int:
        response = await client.get(
            actor.g("/tools/file/counts"),
            headers=actor.headers,
            params={**params, "include_tags": True},
        )
        assert response.status_code == 200, response.text
        return response.json()["untagged_count"]

    assert await untagged(view="templates") == 2
    assert await untagged(view="templates", filters='{"file_type": "excalidraw"}') == 1
    assert await untagged(filters='{"file_type": "lexical"}') == 1


async def test_file_counts_by_initiative(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Grouped counts follow the same visibility rules as the file list."""
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    member = await acting_user(
        guild_role=CommunityRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )
    other_initiative = await create_initiative(session, admin.guild, admin.user)

    await create_file(session, admin.initiative, member.user)
    await create_file(session, admin.initiative, member.user)
    await create_file(session, admin.initiative, admin.user)
    await create_file(session, other_initiative, admin.user)

    # The counts span initiatives, so they answer what reaches the reader —
    # a guild admin included. Theirs is the one file they hold in each,
    # not the member's two alongside it.
    response = await client.get(
        admin.g("/tools/counts/by-initiative"), headers=admin.headers
    )
    assert response.status_code == 200
    assert response.json()["counts"]["file"] == {
        str(admin.initiative.id): 1,
        str(other_initiative.id): 1,
    }

    # A member counts only files shared with them, and gets no entry
    # at all for initiatives they are not in.
    response = await client.get(
        member.g("/tools/counts/by-initiative"), headers=member.headers
    )
    assert response.status_code == 200
    assert response.json()["counts"]["file"] == {str(admin.initiative.id): 2}


async def test_reading_a_file_can_leave_the_body_out(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A file's body is the largest thing this API returns, and a caller
    reacting to a change usually does not need it. Everything else is
    unchanged, so one request still answers "what is this file now"."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    file = await create_file(session, a.initiative, a.user)
    file.content = {"root": {"children": [{"type": "paragraph"}]}}
    session.add(file)
    await session.commit()
    file_id = file.id

    full = await client.get(a.g(f"/files/{file_id}"), headers=a.headers)
    assert full.status_code == 200, full.text
    assert full.json()["content"] == {"root": {"children": [{"type": "paragraph"}]}}

    slim = await client.get(
        a.g(f"/files/{file_id}"),
        params={"include_content": "false"},
        headers=a.headers,
    )
    assert slim.status_code == 200, slim.text
    body = slim.json()
    assert body["content"] == {}
    assert body["id"] == file_id
    assert body["name"] == full.json()["name"]
    assert body["updated_at"] == full.json()["updated_at"]


async def test_a_content_patch_against_a_live_file_is_refused(
    client: AsyncClient, session: AsyncSession, acting_user, monkeypatch
) -> None:
    """A file being edited live has its room as the writer of its content.

    Editors inside the session report their rendering to the room over their
    own sockets. A rendering arriving over REST belongs to a tab outside it,
    and is refused rather than taken and reported as saved.
    """
    from app.services.tenant.collaboration import collaboration_manager

    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    doc = await create_file(session, owner.initiative, owner.user)
    original = doc.content

    monkeypatch.setattr(
        collaboration_manager,
        "live_room",
        # A room somebody is in; reads leave a room the browser renders alone.
        lambda *_a: SimpleNamespace(renders_content=False),
    )

    response = await client.patch(
        owner.g(f"/files/{doc.id}"),
        headers=owner.headers,
        json={"content": {"root": "written outside the session"}},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "LIVE_SESSION_OWNS_CONTENT"
    await session.refresh(doc, ["content"])
    assert doc.content == original


async def test_a_live_file_can_still_be_renamed(
    client: AsyncClient, session: AsyncSession, acting_user, monkeypatch
) -> None:
    """Only the content column belongs to the room; the rest of a file
    is unrelated to what its editors are doing and still applies."""
    from app.services.tenant.collaboration import collaboration_manager

    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    doc = await create_file(session, owner.initiative, owner.user)

    monkeypatch.setattr(
        collaboration_manager,
        "live_room",
        # A room somebody is in; reads leave a room the browser renders alone.
        lambda *_a: SimpleNamespace(renders_content=False),
    )

    response = await client.patch(
        owner.g(f"/files/{doc.id}"),
        headers=owner.headers,
        json={"name": "Renamed while live"},
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Renamed while live"
