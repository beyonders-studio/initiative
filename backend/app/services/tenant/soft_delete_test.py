"""Unit tests for the generic soft-delete service.

Covers cascade-stamp on parent deletion, dedup-by-deleted_at on restore,
the needs-reassignment branch, and the upload-preservation invariants for
uploaded and native files.
"""

from typing import Any

import pytest
from sqlalchemy.orm import undefer
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.file_types import FileType
from app.core.tool_set import BUILTIN_TOOLS
from app.db.soft_delete_filter import SOFT_DELETE_MODELS, select_including_deleted
from app.db.tenancy import GUILD_SCOPED_TABLES
from app.models.platform.user import User
from app.models.tenant._mixins import ActorKind
from app.models.tenant.file import File
from app.models.tenant.initiative import Initiative
from app.models.tenant.task import Task
from app.models.tenant.upload import Upload
from app.services.tenant.lifecycle_tree import CASCADE_CHILDREN, CASCADE_PARENTS, Edge
from app.services.tenant.soft_delete import (
    restore_entity,
    soft_delete_entity,
)
from app.testing.factories import (
    create_file,
    create_guild,
    create_initiative,
    create_project,
    create_task,
    create_upload,
    create_user,
)

# ---------------------------------------------------------------------------
# Cascade stamp / unstamp
# ---------------------------------------------------------------------------


async def test_soft_delete_wiki_page_takes_its_thread(session: AsyncSession):
    """A page's conversation is the page's, so it goes into the bin with it —
    and its wiki's own thread, which is a different thread, stays where it is."""
    from app.models.tenant.comment import Comment
    from app.models.tenant.wiki import WikiPage
    from app.testing.factories import create_comment, create_wiki, create_wiki_page

    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    initiative = await create_initiative(session, guild, user)
    wiki = await create_wiki(session, initiative, user)
    page = await create_wiki_page(session, wiki, user)
    on_page = await create_comment(session, user, wiki_page=page)
    on_wiki = await create_comment(session, user, wiki=wiki)

    await soft_delete_entity(
        session, page, deleted_by_user_id=user.id, retention_days=30
    )
    await session.commit()

    trashed_page = (
        await session.exec(
            select_including_deleted(WikiPage).where(WikiPage.id == page.id)
        )
    ).one()
    trashed_comment = (
        await session.exec(
            select_including_deleted(Comment).where(Comment.id == on_page.id)
        )
    ).one()
    untouched = (
        await session.exec(
            select_including_deleted(Comment).where(Comment.id == on_wiki.id)
        )
    ).one()

    assert trashed_page.deleted_at is not None
    assert trashed_comment.deleted_at == trashed_page.deleted_at
    assert untouched.deleted_at is None


async def test_restore_project_unstamps_only_matching_descendants(
    session: AsyncSession,
):
    """Soft-deleting a project stamps its own deleted_at on every live task, so
    children are hidden behind the parent. If a task was independently
    soft-deleted earlier, restoring its project must NOT bring that task back —
    it has its own deleted_at and belongs in the trash on its own."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    initiative = await create_initiative(session, guild, user)
    project = await create_project(session, initiative, user)
    independently_trashed = await create_task(session, project, title="indep")
    cascaded = await create_task(session, project, title="cascaded")

    # 1. Trash the first task on its own.
    await soft_delete_entity(
        session, independently_trashed, deleted_by_user_id=user.id, retention_days=30
    )
    await session.commit()

    # 2. Trash the project — this stamps `cascaded` but leaves the
    #    already-trashed task's deleted_at intact (different timestamp).
    await soft_delete_entity(
        session, project, deleted_by_user_id=user.id, retention_days=30
    )
    await session.commit()
    stamped = (
        await session.exec(select_including_deleted(Task).where(Task.id == cascaded.id))
    ).one()
    assert stamped.deleted_at == project.deleted_at is not None
    assert stamped.deleted_by == user.id
    assert stamped.purge_at is not None

    # 3. Restore the project.
    await restore_entity(session, project)
    await session.commit()

    refreshed_indep = (
        await session.exec(
            select_including_deleted(Task).where(Task.id == independently_trashed.id)
        )
    ).one()
    refreshed_cascaded = (
        await session.exec(select_including_deleted(Task).where(Task.id == cascaded.id))
    ).one()

    assert refreshed_indep.deleted_at is not None  # still trashed
    assert refreshed_cascaded.deleted_at is None  # restored


# ---------------------------------------------------------------------------
# Upload preservation
# ---------------------------------------------------------------------------


async def test_soft_delete_file_preserves_uploads(session: AsyncSession):
    """Soft-deleting a native file leaves its referenced Upload row
    alone so the image still works after a restore."""
    from sqlmodel import select

    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    initiative = await create_initiative(session, guild, user)
    await create_upload(session, guild, user, filename="abc123.png")
    doc = await create_file(
        session,
        initiative,
        user,
        file_type=FileType.lexical,
        content={"text": "uses /uploads/abc123.png"},
        featured_image_url="/uploads/abc123.png",
    )

    await soft_delete_entity(
        session, doc, deleted_by_user_id=user.id, retention_days=30
    )
    await session.commit()

    upload_row = (
        await session.exec(select(Upload).where(Upload.filename == "abc123.png"))
    ).one_or_none()
    assert upload_row is not None


async def test_purge_file_uploads_escapes_like_wildcards(session: AsyncSession):
    """Filenames legitimately contain '_' (a LIKE metacharacter that means
    'any single character'). The orphan check must escape it before
    interpolating into the LIKE pattern, otherwise a doomed file
    referencing /uploads/file_v2.png could appear pinned by an unrelated
    file referencing /uploads/fileXv2.png — and we'd skip cleanup.

    Regression: the previous implementation interpolated the URL directly
    into the pattern without escaping, leaking blobs on disk."""
    from sqlmodel import select

    from app.services.tenant.attachments import purge_file_uploads

    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    initiative = await create_initiative(session, guild, user)

    upload = Upload(
        filename="file_v2.png",
        created_by=user.id,
        created_by_kind=ActorKind.member,
        size_bytes=1234,
        content_type="image/png",
    )
    session.add(upload)
    await session.commit()

    # The doomed doc references /uploads/file_v2.png — pinned via
    # featured_image_url so extract_upload_urls picks it up cleanly.
    doomed = File(
        initiative_id=initiative.id,
        name="Doomed",
        file_type=FileType.lexical,
        content={},
        featured_image_url="/uploads/file_v2.png",
        created_by=user.id,
        created_by_kind=ActorKind.member,
    )
    # The decoy uses /uploads/fileXv2.png embedded in content. Without
    # escaping, the LIKE pattern '%/uploads/file_v2.png%' matches the
    # decoy's content (since '_' is "any single char"), and the doomed
    # doc's URL appears pinned by an unrelated file.
    decoy = File(
        initiative_id=initiative.id,
        name="Decoy",
        file_type=FileType.lexical,
        content={"src": "/uploads/fileXv2.png"},
        created_by=user.id,
        created_by_kind=ActorKind.member,
    )
    session.add(doomed)
    session.add(decoy)
    await session.commit()

    await purge_file_uploads(session, [doomed])
    await session.commit()

    # The Upload row backing /uploads/file_v2.png had no other reference,
    # so it should be gone. With the bug, the decoy's URL would have
    # matched and the Upload would have been left behind.
    remaining = (
        await session.exec(select(Upload).where(Upload.filename == "file_v2.png"))
    ).one_or_none()
    assert remaining is None


async def test_purging_a_file_keeps_a_version_a_page_shows(session: AsyncSession):
    """A picture picked from Files into a page of the same initiative is the
    version's own stored file, so purging the file leaves it to the page."""
    from app.services.tenant import file_versions
    from app.services.tenant.attachments import purge_file_uploads

    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    initiative = await create_initiative(session, guild, user)
    for name in ("shown.png", "alone.png"):
        await create_upload(session, guild, user, filename=name)
    doomed = await create_file(
        session,
        initiative,
        user,
        file_url=f"/uploads/{guild.id}/shown.png",
        file_content_type="image/png",
    )
    await file_versions.add_version(
        session,
        doomed,
        created_by=user.id,
        created_by_kind=ActorKind.member,
        file_url=f"/uploads/{guild.id}/alone.png",
        file_content_type="image/png",
    )
    await create_file(
        session, initiative, user, content={"src": f"/uploads/{guild.id}/shown.png"}
    )

    assert await purge_file_uploads(session, [doomed]) == {"alone.png"}


async def test_trash_listing_dedupes_nested_comment_replies(
    session: AsyncSession, client
):
    """Soft-deleting a top-level comment cascade-stamps every reply with
    the same deleted_at. The trash listing must hide the replies behind
    their parent (Comment is its own dedup parent via parent_comment_id);
    otherwise a user could click Restore on the reply, leaving its
    parent_comment_id pointing at a still-trashed row.
    """
    from app.models.platform.guild import CommunityRole
    from app.testing.factories import (
        create_comment,
        create_guild_membership,
        get_auth_headers,
    )

    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await create_guild_membership(
        session, user=user, guild=guild, role=CommunityRole.admin
    )
    initiative = await create_initiative(session, guild, user)
    project = await create_project(session, initiative, user)
    task = await create_task(session, project, title="Task with comments")

    parent = await create_comment(session, user, task=task)
    await create_comment(session, user, task=task, parent_comment_id=parent.id)

    # Soft-delete the parent; the cascade stamps the reply too.
    await soft_delete_entity(
        session, parent, deleted_by_user_id=user.id, retention_days=30
    )
    await session.commit()

    # Hit the listing endpoint and confirm only the parent appears. Guild context
    # is path-based now (/c/{community_id}); the headers just carry auth.
    headers = get_auth_headers(user)
    response = await client.get(f"/api/v1/c/{guild.id}/trash/", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    comment_items = [item for item in body["items"] if item["entity_type"] == "comment"]
    ids = {item["entity_id"] for item in comment_items}
    assert ids == {parent.id}, f"reply leaked into trash listing: {ids}"


async def test_trash_listings_page_newest_first(session: AsyncSession, client):
    """Both trash listings are windows over one order, newest first, and walking
    their pages meets every row once. ``/me/trash`` cuts its pages from the
    merge of each guild's newest rows."""
    from datetime import datetime

    from app.models.platform.guild import CommunityRole
    from app.testing.factories import create_guild_membership, get_auth_headers

    user = await create_user(session)
    headers = get_auth_headers(user)
    guilds, initiatives = [], []
    for _ in range(2):
        guild = await create_guild(session, creator=user)
        await create_guild_membership(
            session, user=user, guild=guild, role=CommunityRole.admin
        )
        guilds.append(guild)
        initiatives.append(await create_initiative(session, guild, user))
    # Trashed in turn across the two guilds, so the merge interleaves them.
    for _ in range(3):
        for guild, initiative in zip(guilds, initiatives):
            project = await create_project(session, initiative, user)
            response = await client.delete(
                f"/api/v1/c/{guild.id}/projects/{project.id}", headers=headers
            )
            assert response.status_code in (200, 204), response.text

    async def walk(path: str) -> tuple[int, list[dict]]:
        items: list[dict] = []
        page = 1
        while True:
            response = await client.get(
                path, params={"page": page, "page_size": 2}, headers=headers
            )
            assert response.status_code == 200, response.text
            body = response.json()
            items += body["items"]
            if not body["has_next"]:
                return body["total_count"], items
            page += 1

    def keyed(items: list[dict]) -> list[tuple[int, str, int]]:
        return [(i["community_id"], i["entity_type"], i["entity_id"]) for i in items]

    guild_total, guild_items = await walk(f"/api/v1/c/{guilds[0].id}/trash/")
    mine_total, mine_items = await walk("/api/v1/me/trash")

    assert (guild_total, len(guild_items)) == (3, 3)
    assert (mine_total, len(set(keyed(mine_items)))) == (6, 6)
    for items in (guild_items, mine_items):
        stamps = [datetime.fromisoformat(i["deleted_at"]) for i in items]
        assert stamps == sorted(stamps, reverse=True)
    assert keyed(guild_items) == [
        key for key in keyed(mine_items) if key[0] == guilds[0].id
    ]
    assert {i["deleted_by_id"] for i in mine_items} == {user.id}


async def test_purging_a_uploaded_file_takes_every_version(session: AsyncSession):
    """A purged uploaded file takes every version of its file with it — the
    version rows, the one it points at included, and their Upload rows."""
    from sqlmodel import select

    from app.models.tenant.file import FileVersion
    from app.services.tenant import file_versions
    from app.services.tenant.soft_delete import hard_purge_entity
    from app.testing.factories import create_file

    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    initiative = await create_initiative(session, guild, user)
    names = ["doc_v1.pdf", "doc_v2.pdf"]
    doomed = await create_file(
        session,
        initiative,
        user,
        name="Doomed file",
        file_url=f"/uploads/{names[0]}",
        original_filename=names[0],
    )
    session.add_all(
        Upload(
            filename=name,
            created_by=user.id,
            created_by_kind=ActorKind.member,
            size_bytes=10,
            content_type="image/png",
        )
        for name in names
    )
    newest = await file_versions.add_version(
        session,
        doomed,
        created_by=user.id,
        created_by_kind=ActorKind.member,
        file_url=f"/uploads/{names[1]}",
        file_content_type="application/pdf",
        original_filename=names[1],
    )
    await session.commit()
    assert (newest.version_number, doomed.current_version_id) == (2, newest.id)

    await soft_delete_entity(
        session, doomed, deleted_by_user_id=user.id, retention_days=30
    )
    await session.commit()
    await hard_purge_entity(session, doomed)
    await session.commit()

    uploads = await session.exec(select(Upload).where(Upload.filename.in_(names)))
    versions = await session.exec(
        select(FileVersion).where(FileVersion.file_id == doomed.id)
    )
    assert (uploads.all(), versions.all()) == ([], [])


# ---------------------------------------------------------------------------
# Unlinking references at hard purge
# ---------------------------------------------------------------------------


def _linking_content(target_file_id: int) -> dict:
    return {
        "root": {
            "type": "root",
            "children": [
                {
                    "type": "paragraph",
                    "children": [
                        {
                            "type": "entity-mention",
                            "entityType": "file",
                            "entityId": target_file_id,
                            "text": "Target",
                        }
                    ],
                }
            ],
        }
    }


def _unlinked(content: dict) -> bool:
    node = content["root"]["children"][0]["children"][0]
    return node["type"] == "text" and node["text"] == "Target"


async def test_hard_purge_unlinks_references_in_linking_files(
    session: AsyncSession,
):
    """Purging a file makes references to it in surviving files their words
    and takes the edges with it, so nothing dangles after the row is gone. A
    Yjs state the editor cannot read is cleared, and the next session makes it
    from the repaired content. A linking file sitting in the trash is unlinked
    too, so restoring it after the purge brings back no dangling link."""
    from sqlmodel import select

    from app.core.relationships import RelationshipType, node_id
    from app.core.search import SearchEntityType
    from app.models.tenant.relationship import EntityRelationship
    from app.services.tenant import content_references
    from app.services.tenant.relationships import Endpoint
    from app.services.tenant.soft_delete import hard_purge_entity

    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    initiative = await create_initiative(session, guild, user)
    target = await create_file(session, initiative, user, name="Target")
    linking, trashed = [
        await create_file(
            session,
            initiative,
            user,
            name=name,
            content=_linking_content(target.id),
            yjs_state=state,
        )
        for name, state in (("Linking", b"stale-collab-state"), ("Trashed", None))
    ]
    for row in (linking, trashed):
        await content_references.sync_for_entity(
            session,
            Endpoint(SearchEntityType.file, row.id),
            body=row.content,
            author_id=user.id,
        )
    await session.commit()

    for row in (trashed, target):
        await soft_delete_entity(
            session, row, deleted_by_user_id=user.id, retention_days=30
        )
    await session.commit()

    await hard_purge_entity(session, target)
    await session.commit()

    for row in (linking, trashed):
        refreshed = (
            await session.exec(
                select_including_deleted(File)
                .where(File.id == row.id)
                .options(undefer(File.content), undefer(File.yjs_state))
            )
        ).one()
        assert _unlinked(refreshed.content)
        assert refreshed.yjs_state is None

    edges = (
        await session.exec(
            select(EntityRelationship).where(
                EntityRelationship.target_node
                == node_id(SearchEntityType.file, target.id),
                EntityRelationship.relationship_type
                == RelationshipType.references.value,
            )
        )
    ).all()
    assert edges == []


# ---------------------------------------------------------------------------
# Restoring a tree that has archived content in it
# ---------------------------------------------------------------------------


async def test_restore_initiative_brings_back_archived_tools_children(
    session: AsyncSession,
):
    """An event carries no ``archived_at``, and archiving a file never touches
    the comments on it: inside an archived tool they are simply live, because
    that is the only state they have. Restoring the initiative has to put them
    back in exactly that state, and the tool back in its archive."""
    from app.models.tenant.calendar import Calendar
    from app.models.tenant.calendar_event import CalendarEvent
    from app.models.tenant.comment import Comment
    from app.services.tenant.archive import archive_entity
    from app.testing.factories import (
        create_calendar,
        create_calendar_event,
        create_comment,
    )

    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    initiative = await create_initiative(session, guild, user)
    calendar = await create_calendar(session, initiative, user)
    event = await create_calendar_event(session, calendar, user)
    file = await create_file(session, initiative, user)
    comment = await create_comment(session, user, file=file)
    await archive_entity(session, calendar)
    await archive_entity(session, file)
    await session.commit()

    await soft_delete_entity(
        session, initiative, deleted_by_user_id=user.id, retention_days=30
    )
    await session.commit()

    await restore_entity(session, initiative)
    await session.commit()

    for model, row_id in ((CalendarEvent, event.id), (Comment, comment.id)):
        refreshed = (
            await session.exec(
                select_including_deleted(model).where(model.id == row_id)
            )
        ).one()
        assert refreshed.deleted_at is None
    refreshed_calendar = (
        await session.exec(
            select_including_deleted(Calendar).where(Calendar.id == calendar.id)
        )
    ).one()
    assert refreshed_calendar.deleted_at is None
    assert refreshed_calendar.archived_at is not None


async def test_trash_listing_shows_a_trashed_wiki_alone(session: AsyncSession, client):
    """A wiki in the bin is one entry: its pages, the pages under them and both
    threads come back with it, so none of them is offered on its own.

    Restoring it puts each page back under the address it had."""
    from app.models.platform.guild import CommunityRole
    from app.models.tenant.wiki import WikiPage
    from app.testing.factories import (
        create_comment,
        create_guild_membership,
        create_wiki,
        create_wiki_page,
        get_auth_headers,
    )

    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await create_guild_membership(
        session, user=user, guild=guild, role=CommunityRole.admin
    )
    initiative = await create_initiative(session, guild, user)
    wiki = await create_wiki(session, initiative, user)
    page = await create_wiki_page(session, wiki, user, title="Step 1")
    child = await create_wiki_page(
        session, wiki, user, title="Step 2", parent_page_id=page.id
    )
    await create_comment(session, user, wiki=wiki)
    await create_comment(session, user, wiki_page=child)

    await soft_delete_entity(
        session, wiki, deleted_by_user_id=user.id, retention_days=30
    )
    await session.commit()

    headers = get_auth_headers(user)
    response = await client.get(f"/api/v1/c/{guild.id}/trash/", headers=headers)
    assert response.status_code == 200, response.text
    listed = {(i["entity_type"], i["entity_id"]) for i in response.json()["items"]}
    assert listed == {("wiki", wiki.id)}

    response = await client.post(
        f"/api/v1/c/{guild.id}/trash/wiki/{wiki.id}/restore", headers=headers
    )
    assert response.status_code == 200, response.text

    pages = await session.exec(
        select_including_deleted(WikiPage.slug, WikiPage.deleted_at).where(
            WikiPage.wiki_id == wiki.id
        )
    )
    assert sorted(pages.all()) == [("step-1", None), ("step-2", None)]


async def test_restored_siblings_do_not_take_the_same_name(session: AsyncSession):
    """Pages coming back together each take a name the others have not: a live
    page holding "foo" sends the first to "foo-2", which the second was about
    to take back, so the second has to see that and go on."""
    from app.models.tenant.wiki import WikiPage
    from app.testing.factories import create_wiki, create_wiki_page

    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    initiative = await create_initiative(session, guild, user)
    wiki = await create_wiki(session, initiative, user)
    page = await create_wiki_page(session, wiki, user, title="Steps")
    for title in ("foo", "foo 2"):
        await create_wiki_page(session, wiki, user, title=title, parent_page_id=page.id)
    await soft_delete_entity(
        session, page, deleted_by_user_id=user.id, retention_days=30
    )
    await session.commit()
    await create_wiki_page(session, wiki, user, title="foo")

    await restore_entity(session, page)
    await session.commit()

    children = await session.exec(
        select_including_deleted(WikiPage.slug).where(
            WikiPage.parent_page_id == page.id
        )
    )
    slugs = children.all()
    assert len(set(slugs)) == 2, slugs
    assert not any("~" in slug for slug in slugs), slugs


async def _file(
    session: AsyncSession,
    model: type,
    parent: SQLModel,
    edge: Edge,
    user: User,
    built: dict[type, SQLModel],
) -> SQLModel:
    """A row of ``model`` filed under ``parent`` through ``edge``. ``built`` holds
    the rows above ``parent``, by model, for a child that names one of them."""
    from app.core.tools import Tool
    from app.models.tenant._mixins import tool_models
    from app.models.tenant.calendar_event import CalendarEvent
    from app.models.tenant.collection import Collection
    from app.models.tenant.comment import Comment
    from app.models.tenant.wiki import Wiki, WikiPage
    from app.testing.factories import (
        TOOL_FACTORIES,
        create_calendar_event,
        create_collection,
        create_comment,
        create_task,
        create_wiki_page,
    )

    models = tool_models()
    tool = next((t for t in Tool if models.get(t.plural) is model), None)
    if tool is not None:
        return await TOOL_FACTORIES[tool](session, parent, user)
    if model is Task:
        return await create_task(session, parent)
    if model is CalendarEvent:
        if edge.column != "calendar_id":
            # An occurrence of a series, in the series' calendar.
            return await create_calendar_event(
                session,
                built[_model(_first_way_up(CalendarEvent).table)],
                user,
                **{edge.column: parent.id, "original_start": parent.start_at},
            )
        return await create_calendar_event(session, parent, user)
    if model is Collection:
        return await create_collection(session, parent, user)
    if model is WikiPage:
        if edge.column == "wiki_id":
            return await create_wiki_page(session, parent, user)
        return await create_wiki_page(
            session, built[Wiki], user, **{edge.column: parent.id}
        )
    if model is Comment and edge.kind is not None:
        return await create_comment(session, user, **{edge.kind: parent})
    raise AssertionError(f"this test has no way to file a {model.__name__}")


def _model(table: Any) -> type:
    from app.db.base import MODELS_BY_TABLE

    return MODELS_BY_TABLE[table.name]


def _first_way_up(model: type) -> Edge:
    table = model.__table__  # type: ignore[attr-defined]
    return next(edge for edge in CASCADE_PARENTS[table] if edge.table is not table)


async def _build(
    session: AsyncSession,
    model: type,
    initiative: Initiative,
    user: User,
    built: dict[type, SQLModel],
) -> SQLModel:
    """A row of ``model`` and what it is filed under, up to ``initiative``, by
    the first way up the trash tree names. Every row lands in ``built``."""
    if model is Initiative:
        built[Initiative] = initiative
        return initiative
    edge = _first_way_up(model)
    parent_model = _model(edge.table)
    parent = built.get(parent_model) or await _build(
        session, parent_model, initiative, user, built
    )
    built[model] = await _file(session, model, parent, edge, user, built)
    return built[model]


def _trash_kind(model: type) -> str:
    from app.api.v1.tenant_endpoints.trash import ENTITY_REGISTRY

    return next(
        kind
        for kind, (t, _) in ENTITY_REGISTRY.items()
        if t is model.__table__  # type: ignore[attr-defined]
    )


def _trash_edges() -> list:
    return [
        pytest.param(
            _model(parent),
            _model(edge.table),
            edge,
            id=f"{_model(edge.table).__name__}.{edge.kind or edge.column}",
        )
        for parent, children in CASCADE_CHILDREN.items()
        for edge in children
    ]


def _under_an_initiative() -> list:
    return [
        pytest.param(model, id=model.__name__)
        for model in (Initiative, *map(_model, CASCADE_PARENTS))
    ]


@pytest.mark.parametrize("archived", [False, True])
@pytest.mark.parametrize(("parent_model", "child_model", "edge"), _trash_edges())
async def test_nothing_comes_back_under_something_still_in_the_trash(
    session: AsyncSession, client, parent_model, child_model, edge, archived
):
    """A child binned before its parent keeps its own stamp, so it stays in the
    bin when the parent comes back — and until then it cannot come back at all,
    or it would be live under something in the bin. An archive over both, which
    stamps a child that can carry one, does not change that. Runs over every
    edge of the trash tree, so a new one is held to it."""
    from app.models.platform.guild import CommunityRole
    from app.services.tenant.archive import archive_entity, unarchive_entity
    from app.testing.factories import create_guild_membership, get_auth_headers

    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await create_guild_membership(
        session, user=user, guild=guild, role=CommunityRole.admin
    )
    initiative = await create_initiative(session, guild, user)
    built: dict[type, SQLModel] = {}
    parent = await _build(session, parent_model, initiative, user, built)
    child = await _file(session, child_model, parent, edge, user, built)
    for trashed in (child, parent):
        await soft_delete_entity(
            session, trashed, deleted_by_user_id=user.id, retention_days=30
        )
        await session.commit()
    if archived:
        await archive_entity(session, initiative)
        await session.commit()

    headers = get_auth_headers(user)
    trash = f"/api/v1/c/{guild.id}/trash"
    restore_child = f"{trash}/{_trash_kind(child_model)}/{child.id}/restore"
    response = await client.post(restore_child, headers=headers)
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "PARENT_IS_FROZEN"
    if archived:
        await unarchive_entity(session, initiative)
        await session.commit()

    response = await client.post(
        f"{trash}/{_trash_kind(parent_model)}/{parent.id}/restore", headers=headers
    )
    assert response.status_code == 200, response.text
    response = await client.post(restore_child, headers=headers)
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("model", _under_an_initiative())
async def test_the_trash_works_inside_an_archive(session: AsyncSession, client, model):
    """Archived content can still be thrown away and brought back: it comes
    back into the archive, as everything around it is. A tool nobody owns comes
    back to whoever wrote it, archived or not."""
    from app.models.platform.guild import CommunityRole
    from app.services.tenant import ownership as ownership_service
    from app.services.tenant.archive import archive_entity
    from app.testing.factories import (
        create_guild_membership,
        get_auth_headers,
        route_session_to_guild,
    )

    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await create_guild_membership(
        session, user=user, guild=guild, role=CommunityRole.admin
    )
    initiative = await create_initiative(session, guild, user)
    row = await _build(session, model, initiative, user, {})
    tool = ownership_service.tool_for_row(row, BUILTIN_TOOLS)
    if tool is not None:
        await route_session_to_guild(session, guild.id)
        await ownership_service.set_resource_owner(
            session, tool=tool, row=row, new_owner=None
        )
        await session.commit()
    await archive_entity(session, initiative)
    await session.commit()
    await soft_delete_entity(
        session, row, deleted_by_user_id=user.id, retention_days=30
    )
    await session.commit()

    response = await client.post(
        f"/api/v1/c/{guild.id}/trash/{_trash_kind(model)}/{row.id}/restore",
        headers=get_auth_headers(user),
    )
    assert response.status_code == 200, response.text
    await session.refresh(row)
    assert row.deleted_at is None
    assert getattr(row, "archived_at", True) is not None
    if tool is not None:
        owner = await ownership_service.current_owner(
            session, tool=tool, resource_id=row.id
        )
        assert owner == ownership_service.Owner(user_id=user.id)


async def test_every_tool_takes_its_thread_to_the_trash_and_back(
    session: AsyncSession, client
):
    """Whatever the tool, its conversation is filed under it: trashing it bins
    the thread, the trash lists only the tool, and restoring it brings the
    thread back. Runs over the ``Tool`` enum, so a new tool is held to it."""
    from app.core.tools import Tool
    from app.models.platform.guild import CommunityRole
    from app.models.tenant.comment import Comment
    from app.testing.factories import (
        TOOL_FACTORIES,
        create_comment,
        create_guild_membership,
        get_auth_headers,
    )

    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await create_guild_membership(
        session, user=user, guild=guild, role=CommunityRole.admin
    )
    initiative = await create_initiative(session, guild, user)

    threads: dict[Tool, tuple[int, int | None]] = {}
    for tool in Tool:
        entity = await TOOL_FACTORIES[tool](session, initiative, user)
        comment = await create_comment(session, user, **{tool.value: entity})
        threads[tool] = (entity.id, comment.id)
        await soft_delete_entity(
            session, entity, deleted_by_user_id=user.id, retention_days=30
        )
        await session.commit()

    async def live_comments() -> set[int]:
        comment_ids = [comment_id for _, comment_id in threads.values()]
        rows = await session.exec(
            select_including_deleted(Comment.id).where(
                Comment.id.in_(comment_ids), Comment.deleted_at.is_(None)
            )
        )
        return set(rows.all())

    assert await live_comments() == set()

    headers = get_auth_headers(user)
    response = await client.get(f"/api/v1/c/{guild.id}/trash/", headers=headers)
    assert response.status_code == 200, response.text
    listed = {(i["entity_type"], i["entity_id"]) for i in response.json()["items"]}
    assert listed == {
        (tool.value, entity_id) for tool, (entity_id, _) in threads.items()
    }

    for tool, (entity_id, _) in threads.items():
        response = await client.post(
            f"/api/v1/c/{guild.id}/trash/{tool.value}/{entity_id}/restore",
            headers=headers,
        )
        assert response.status_code == 200, (tool, response.text)

    assert await live_comments() == {comment_id for _, comment_id in threads.values()}


#: Keys into the trash that a purge lets go of itself, rather than the
#: database: an upload's file on disk has to go with its row.
_PURGED_BY_HAND = {("uploads", "initiative_id")}


@pytest.mark.always
def test_what_hangs_off_the_trash_goes_with_it():
    """A row outside the trash that keys on one in it goes with it at the
    database, or lets go of it, so purging a row is one DELETE per level."""
    trashable = {model.__tablename__ for model in SOFT_DELETE_MODELS}
    held = [
        f"{table.name}.{column.name} -> {key.column.table.name}"
        for table in SQLModel.metadata.tables.values()
        if table.name in GUILD_SCOPED_TABLES and table.name not in trashable
        for column in table.columns
        for key in column.foreign_keys
        if key.column.table.name in trashable
        and (key.ondelete or "").upper() not in ("CASCADE", "SET NULL")
        and (table.name, column.name) not in _PURGED_BY_HAND
    ]
    assert not held, held
