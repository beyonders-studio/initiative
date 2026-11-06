"""Integration tests for the collaboration HTTP endpoints.

Focused on the handover — ``POST`` on a body's ``…/collaborate`` path — which a
leaving tab fires as a ``keepalive`` fetch when its socket is already gone,
carrying the Yjs edits the room never saw. It authenticates as every other
write does: the HttpOnly session cookie on web, the Authorization header on
native. A ``?token=`` in the URL authenticates nothing here.
"""

import asyncio
import base64
import json
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient
from pycrdt import Doc, Text
from sqlalchemy.orm import undefer
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import Tool
from app.api.content_socket import MSG_AUTH
from app.api.v1.tenant_endpoints.collaboration import MSG_AWARENESS
from app.core.security import create_upload_token
from app.core.user_display import handle_of
from app.models.platform.access_grant import AccessGrant
from app.core.file_types import FileType
from app.models.tenant.file import File
from app.models.tenant.wiki import WikiPage
from app.testing import (
    create_file,
    create_user,
    create_wiki,
    create_wiki_page,
    get_auth_headers,
    get_auth_token,
)
from app.core.search import SearchEntityType
from app.services import editor_engine
from app.services.tenant import body_states
from app.services.tenant.collaboration import (
    CollaborationManager,
    collaboration_manager,
)
from app.services.tenant import collaboration as collaboration_module
from app.services.tenant.collaborative_resources import resource_for
from app.services.content_sockets import resource_room
from app.models.platform.guild import CommunityRole
from app.models.platform.user import UserRole
from app.services import permissions as permissions_service
from app.testing import route_as
from app.core.login_methods import LoginMethod
from app.core.rules import SignInRequirement
from app.services.platform import rules

WHITEBOARD = {"elements": [], "appState": {}, "files": {}}


def _lexical(words: str) -> dict:
    """A file holding one paragraph of ``words``."""
    return {
        "root": {
            "type": "root",
            "version": 1,
            "children": [
                {
                    "type": "paragraph",
                    "version": 1,
                    "children": [{"type": "text", "text": words, "version": 1}],
                }
            ],
        }
    }


def _words(content: dict) -> str:
    return "".join(
        node.get("text", "")
        for block in content["root"]["children"]
        for node in block.get("children", [])
    )


def _file_url(guild_id: int, file_id: int) -> str:
    return f"/api/v1/c/{guild_id}/collaboration/files/{file_id}/collaborate"


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _typed(text: str, doc: Doc | None = None) -> Doc:
    """A Yjs doc holding ``text``, as a tab's would after typing it."""
    doc = doc or Doc()
    body = doc.get("body", type=Text)
    body += text
    return doc


def _handover(doc: Doc) -> dict:
    return {"update": _b64(doc.get_update())}


def _text_of(yjs_state: bytes) -> str:
    doc = Doc()
    doc.apply_update(yjs_state)
    return str(doc.get("body", type=Text))


async def test_collaboration_guild_admin_gets_full_access(
    session: AsyncSession, acting_user, role_session
) -> None:
    """A guild admin must get full collaboration access to a restricted file
    they hold no grant on and aren't an initiative member of — mirroring the REST
    guild-admin bypass. The collaboration paths resolve access straight through
    the shared DAC engine (``permissions.allows``), which reads the
    active guild-role context that ``establish_guild_access`` records."""
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    # admin is deliberately NOT a member of this initiative and holds no grant.
    admin = await acting_user(guild_role=CommunityRole.admin, guild=owner.guild)
    doc = await create_file(session, owner.initiative, owner.user)
    # The socket resolves a body through the resource registry, so the test
    # asks the same way the endpoint does: on the request login, routed
    # through the seam as the admin, the row arrives with the level the
    # standing gives — owner, grant or no grant.
    s = await role_session("app_user")
    await route_as(s, user_id=admin.user.id, guild_id=owner.guild.id)
    resolved = await resource_for(SearchEntityType.file.value).load(
        s, doc.id, owner.guild.id
    )
    assert resolved is not None
    assert permissions_service.allows(resolved.body, permissions_service.Action.edit)


async def test_a_handover_merges_into_the_room_and_saves_both_views(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    """A whiteboard drawn on offline: the drawing lands in the Yjs state, and
    the content column is the server's rendering of it."""
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    stored = await body_states.WHITEBOARD.bootstrap(WHITEBOARD)
    doc = await create_file(
        session,
        owner.initiative,
        owner.user,
        file_type=FileType.excalidraw,
        content=WHITEBOARD,
        yjs_state=stored,
    )
    drawn = {**WHITEBOARD, "elements": [{"id": "drawn offline"}]}
    stamped = doc.updated_at
    offline = Doc()
    offline.apply_update(stored)
    offline.apply_update(await body_states.WHITEBOARD.apply(stored, drawn))

    response = await client.post(
        _file_url(owner.guild.id, doc.id),
        json=_handover(offline),
        headers=owner.headers,
    )

    assert response.status_code == 204, response.text
    saved = (
        await session.exec(
            select(File)
            .where(File.id == doc.id)
            .options(undefer(File.content), undefer(File.yjs_state))
        )
    ).one()
    assert saved.content == drawn
    assert await body_states.WHITEBOARD.render(saved.yjs_state or b"") == drawn
    # Saved as an edit is, so a device's older unsaved copy reads as older.
    assert saved.updated_at > stamped


async def test_an_editor_body_is_rendered_by_the_server_not_the_tab(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    """A native file's content is what the server reads its Yjs state
    as, offline edits included."""
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    doc = await create_file(
        session, owner.initiative, owner.user, content=_lexical("on the server")
    )
    # A paragraph the tab wrote while its socket was gone, as Lexical writes it.
    offline = Doc()
    offline.apply_update(await editor_engine.bootstrap(_lexical("written offline")))

    response = await client.post(
        _file_url(owner.guild.id, doc.id),
        json=_handover(offline),
        headers=owner.headers,
    )

    assert response.status_code == 204, response.text
    saved = (
        await session.exec(
            select(File).where(File.id == doc.id).options(undefer(File.content))
        )
    ).one()
    words = _words(saved.content)
    assert "on the server" in words and "written offline" in words


async def test_an_editor_body_with_no_state_has_it_made_once(
    session: AsyncSession, acting_user, role_session
) -> None:
    """Rooms opening a native file with no Yjs state together make it on
    the server once, from the file's content."""
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    doc = await create_file(
        session, owner.initiative, owner.user, content=_lexical("as it was saved")
    )

    async def open_room():
        routed = await role_session("app_user")
        await route_as(routed, user_id=owner.user.id, guild_id=owner.guild.id)
        return await CollaborationManager().get_or_create_room(
            owner.guild.id, SearchEntityType.file.value, doc.id, routed
        )

    first, second = await asyncio.gather(open_room(), open_room())

    saved = (
        await session.exec(
            select(File).where(File.id == doc.id).options(undefer(File.yjs_state))
        )
    ).one()
    assert saved.yjs_state is not None
    assert first.get_state() == second.get_state() == saved.yjs_state
    assert _words(await editor_engine.render(saved.yjs_state)) == "as it was saved"


async def _a_process_editing(owner, doc_id: int, role_session):
    """One process's manager and its room for a spreadsheet, as a second
    replica of the server would hold it."""
    routed = await role_session("app_user")
    await route_as(routed, user_id=owner.user.id, guild_id=owner.guild.id)
    manager = CollaborationManager()
    room = await manager.get_or_create_room(
        owner.guild.id, SearchEntityType.file.value, doc_id, routed
    )
    room.hold()  # somebody is in it
    return manager, room


async def _set_cell(room, cell: str, value: str) -> None:
    workbook = await body_states.SPREADSHEET.render(room.get_state())
    assert workbook is not None
    workbook["sheets"][0]["cells"][cell] = value
    room.apply_update(await body_states.SPREADSHEET.apply(room.get_state(), workbook))


async def test_two_processes_saving_one_body_keep_each_others_edits(
    session: AsyncSession, acting_user, role_session
) -> None:
    """Each save merges what the other saved before writing, so the row ends
    up holding both processes' edits, not the last writer's."""
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    doc = await create_file(
        session, owner.initiative, owner.user, file_type=FileType.sheet
    )
    one, room_one = await _a_process_editing(owner, doc.id, role_session)
    two, room_two = await _a_process_editing(owner, doc.id, role_session)
    await _set_cell(room_one, "0:0", "from one")
    await _set_cell(room_two, "1:1", "from two")

    await one.save(room_one)
    await two.save(room_two)

    saved = (
        await session.exec(
            select(File)
            .where(File.id == doc.id)
            .options(undefer(File.content), undefer(File.yjs_state))
        )
    ).one()
    assert saved.content["sheets"][0]["cells"] == {"0:0": "from one", "1:1": "from two"}
    rendered = await body_states.SPREADSHEET.render(saved.yjs_state or b"")
    assert rendered == saved.content


async def test_a_room_takes_what_another_process_saved_on_the_next_sweep(
    session: AsyncSession, acting_user, role_session, monkeypatch
) -> None:
    """Editors on one replica see a save made on another within a sweep, and
    the room has nothing of its own to write back for it."""
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    doc = await create_file(
        session, owner.initiative, owner.user, file_type=FileType.sheet
    )
    here, watching = await _a_process_editing(owner, doc.id, role_session)
    elsewhere, editing = await _a_process_editing(owner, doc.id, role_session)
    sent: list[tuple] = []
    monkeypatch.setattr(
        collaboration_module.sockets,
        "emit_bytes",
        lambda key, data, exclude=None: sent.append((key, data)),
    )
    await _set_cell(editing, "2:2", "from elsewhere")
    await elsewhere.save(editing)

    await here.persist_dirty_rooms()

    workbook = await body_states.SPREADSHEET.render(watching.get_state())
    assert workbook is not None
    assert workbook["sheets"][0]["cells"] == {"2:2": "from elsewhere"}
    assert [key for key, _ in sent] == [
        resource_room(owner.guild.id, SearchEntityType.file.value, doc.id)
    ]
    assert watching.is_dirty is False


async def test_a_wiki_page_takes_a_handover_too(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    owner.initiative.wikis_enabled = True
    session.add(owner.initiative)
    await session.commit()
    wiki = await create_wiki(session, owner.initiative, owner.user)
    page = await create_wiki_page(session, wiki, owner.user)

    response = await client.post(
        f"/api/v1/c/{owner.guild.id}/collaboration/wiki-pages/{page.id}/collaborate",
        json=_handover(_typed("a page written offline")),
        headers={"Authorization": f"Bearer {get_auth_token(owner.user)}"},
    )

    assert response.status_code == 204, response.text
    saved = (await session.exec(select(WikiPage).where(WikiPage.id == page.id))).one()
    assert _text_of(saved.yjs_state or b"") == "a page written offline"


async def test_an_unreadable_update_is_refused(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    doc = await create_file(session, owner.initiative, owner.user)

    response = await client.post(
        _file_url(owner.guild.id, doc.id),
        json={"update": _b64(b"not yjs"), "state_vector": _b64(b"\x00")},
        headers={"Authorization": f"Bearer {get_auth_token(owner.user)}"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "FILE_COLLABORATION_UPDATE_INVALID"
    # The room it opened to try is not left behind for the next caller.
    key = (owner.guild.id, SearchEntityType.file.value, doc.id)
    assert key not in collaboration_manager._rooms


async def test_a_refused_handover_leaves_the_next_one_the_saved_file(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    """A handover that is refused loads the room and takes nothing; the next one
    still merges into what the row holds, not into a room left behind."""
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    doc = await create_file(
        session,
        owner.initiative,
        owner.user,
        yjs_state=_typed("from a peer. ").get_update(),
    )
    headers = {"Authorization": f"Bearer {get_auth_token(owner.user)}"}

    refused = await client.post(
        _file_url(owner.guild.id, doc.id),
        json={"update": _b64(b"not yjs"), "state_vector": _b64(b"\x00")},
        headers=headers,
    )
    assert refused.status_code == 400
    # The row changes underneath, as another tab's save would change it.
    doc.yjs_state = _typed("saved since. ").get_update()
    session.add(doc)
    await session.commit()

    taken = await client.post(
        _file_url(owner.guild.id, doc.id),
        json=_handover(_typed("offline")),
        headers=headers,
    )

    assert taken.status_code == 204, taken.text
    saved = (
        await session.exec(
            select(File).where(File.id == doc.id).options(undefer(File.yjs_state))
        )
    ).one()
    merged = _text_of(saved.yjs_state or b"")
    assert "saved since." in merged and "offline" in merged


async def test_a_token_in_the_query_is_refused(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    """The handover is a write: a ``?token=`` authenticates none, the
    uploads-scoped one included."""
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    doc = await create_file(session, owner.initiative, owner.user)
    token, _ = create_upload_token(user_id=owner.user.id)

    response = await client.post(
        f"{_file_url(owner.guild.id, doc.id)}?token={token}",
        json=_handover(_typed("x")),
    )

    assert response.status_code == 401


async def test_a_handover_answers_a_community_that_asks_for_a_passkey(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    """What the session proved about the person reaches the guild gate here as
    it does on a page: the session opened with a passkey writes, the one
    opened with a password is refused."""
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    doc = await create_file(session, owner.initiative, owner.user)
    await rules.put(
        session,
        "auth_policy",
        SignInRequirement("required", None, frozenset({LoginMethod.passkey})),
        guild_id=owner.guild.id,
    )
    await session.commit()

    with_a_password = await client.post(
        _file_url(owner.guild.id, doc.id),
        json=_handover(_typed("x")),
        headers={"Authorization": f"Bearer {get_auth_token(owner.user, amr=['pwd'])}"},
    )
    assert with_a_password.status_code == 401, with_a_password.text

    with_a_passkey = await client.post(
        _file_url(owner.guild.id, doc.id),
        json=_handover(_typed("x")),
        headers={
            "Authorization": (
                f"Bearer {get_auth_token(owner.user, amr=['pwd', 'hwk', 'mfa'])}"
            )
        },
    )
    assert with_a_passkey.status_code == 204, with_a_passkey.text


async def test_a_non_member_is_refused(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    doc = await create_file(session, owner.initiative, owner.user)
    outsider = await create_user(session)
    response = await client.post(
        _file_url(owner.guild.id, doc.id),
        json=_handover(_typed("x")),
        headers=get_auth_headers(outsider),
    )

    assert response.status_code == 403


async def _approved_grant(session, *, user, guild, owner, level: str) -> AccessGrant:
    """An approved, currently-live access grant for ``user`` on ``guild``."""
    now = datetime.now(timezone.utc)
    grant = AccessGrant(
        user_id=user.id,
        guild_id=guild.id,
        access_level=level,
        status="approved",
        reason="test",
        requested_duration_minutes=60,
        requested_by_id=user.id,
        approved_by_id=owner.id,
        decided_at=now,
        expires_at=now + timedelta(hours=1),
    )
    session.add(grant)
    await session.commit()
    return grant


async def test_a_break_glass_grantee_can_hand_over(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    """A platform operator who is not a member but holds a live ``read_write``
    break-glass grant edits existing content for the grant's window."""
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    doc = await create_file(session, owner.initiative, owner.user)
    grantee = await create_user(session, role=UserRole.operator)
    await _approved_grant(
        session, user=grantee, guild=owner.guild, owner=owner.user, level="read_write"
    )
    response = await client.post(
        _file_url(owner.guild.id, doc.id),
        json=_handover(_typed("x")),
        headers=get_auth_headers(grantee),
    )

    assert response.status_code == 204, response.text


async def test_a_read_grant_cannot_hand_over(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    """A read grant reaches the guild but not the write level the handover
    needs."""
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    doc = await create_file(session, owner.initiative, owner.user)
    grantee = await create_user(session, role=UserRole.support)
    await _approved_grant(
        session, user=grantee, guild=owner.guild, owner=owner.user, level="read"
    )
    response = await client.post(
        _file_url(owner.guild.id, doc.id),
        json=_handover(_typed("x")),
        headers=get_auth_headers(grantee),
    )

    assert response.status_code == 403
    assert response.json() == Tool.file.write_required().body


async def test_the_roster_names_a_collaborator_as_their_community_does(
    session: AsyncSession, acting_user, socket_client
) -> None:
    """Who is editing reads the same as everywhere else in the community: the
    name set there, the handle where there is none."""
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    doc = await create_file(session, owner.initiative, owner.user)
    path = _file_url(owner.guild.id, doc.id)

    def roster_name() -> str:
        with socket_client.websocket_connect(path) as ws:
            auth = {"token": get_auth_token(owner.user)}
            ws.send_bytes(bytes([MSG_AUTH]) + json.dumps(auth).encode())
            while True:
                frame = ws.receive().get("bytes") or b""
                if frame[:1] == bytes([MSG_AWARENESS]):
                    return json.loads(frame[1:])["data"][0]["name"]

    assert roster_name() == handle_of(owner.user)
    owner.membership.display_name = "Quill"
    session.add(owner.membership)
    await session.commit()
    assert roster_name() == "Quill"
