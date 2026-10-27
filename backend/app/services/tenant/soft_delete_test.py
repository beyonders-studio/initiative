"""Unit tests for the generic soft-delete service.

Covers cascade-stamp on parent deletion, dedup-by-deleted_at on restore,
the needs-reassignment branch, and the upload-preservation invariants for
uploaded and native files.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.orm import undefer
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.tenant.task_types import get_default_type
from app.db.schema_provisioning import guild_schema_name
from app.db.soft_delete_filter import SOFT_DELETE_MODELS, select_including_deleted
from app.db.tenancy import GUILD_SCOPED_TABLES
from app.models.platform.user import User
from app.core.file_types import FileType
from app.models.tenant.file import File
from app.models.tenant.initiative import Initiative
from app.models.tenant.project import Project
from app.models.tenant.queue import Queue
from app.models.tenant.task import Task
from app.models.tenant.upload import Upload
from app.services.tenant.lifecycle_tree import CASCADE_CHILDREN, CASCADE_PARENTS
from app.services.tenant.soft_delete import (
    restore_entity,
    soft_delete_entity,
)
from app.testing.factories import (
    create_file,
    create_guild,
    create_initiative,
    create_project,
    create_upload,
    create_user,
)


async def _create_task(
    session: AsyncSession, project: Project, *, title: str = "T"
) -> Task:
    """Build a task with a fresh status. The project factory does not seed
    task statuses, so we create one on first use per-project."""
    from sqlmodel import select

    from app.models.tenant.task import TaskPriority, TaskStatus, TaskStatusCategory

    status = (
        await session.exec(
            select(TaskStatus).where(TaskStatus.project_id == project.id).limit(1)
        )
    ).first()
    if status is None:
        status = TaskStatus(
            project_id=project.id,
            name="Todo",
            category=TaskStatusCategory.todo,
            position=0,
            is_default=True,
        )
        session.add(status)
        await session.commit()
        await session.refresh(status)
    task = Task(
        project_id=project.id,
        task_status_id=status.id,
        task_type_id=(await get_default_type(session, project.id)).id,
        title=title,
        priority=TaskPriority.medium,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


# ---------------------------------------------------------------------------
# Cascade stamp / unstamp
# ---------------------------------------------------------------------------


async def test_soft_delete_project_cascades_to_tasks(session: AsyncSession):
    """Soft-deleting a project stamps the same deleted_at on every task,
    so children are hidden behind the parent in default selects."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    initiative = await create_initiative(session, guild, user)
    project = await create_project(session, initiative, user)
    task_a = await _create_task(session, project, title="A")
    task_b = await _create_task(session, project, title="B")

    await soft_delete_entity(
        session, project, deleted_by_user_id=user.id, retention_days=30
    )
    await session.commit()

    refreshed_project = (
        await session.exec(
            select_including_deleted(Project).where(Project.id == project.id)
        )
    ).one()
    refreshed_a = (
        await session.exec(select_including_deleted(Task).where(Task.id == task_a.id))
    ).one()
    refreshed_b = (
        await session.exec(select_including_deleted(Task).where(Task.id == task_b.id))
    ).one()

    assert refreshed_project.deleted_at is not None
    assert refreshed_a.deleted_at == refreshed_project.deleted_at
    assert refreshed_b.deleted_at == refreshed_project.deleted_at
    assert refreshed_a.deleted_by == user.id
    assert refreshed_a.purge_at is not None


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
    """If a task was independently soft-deleted earlier, restoring its
    project must NOT bring that task back — it has its own deleted_at and
    belongs in the trash on its own."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    initiative = await create_initiative(session, guild, user)
    project = await create_project(session, initiative, user)
    independently_trashed = await _create_task(session, project, title="indep")
    cascaded = await _create_task(session, project, title="cascaded")

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
# Restore needs-reassignment
# ---------------------------------------------------------------------------


async def test_restrictive_delete_policy_exists_on_each_soft_delete_table(
    session: AsyncSession,
):
    """Every soft-delete-capable table carries a RESTRICTIVE FOR DELETE policy
    (``soft_delete_admin_purge``) that admits only a routed guild admin
    (``app.guild_admin = 'true'``); a hard delete is a purge. Post-squash
    these tables (and thus their policies) live in the per-guild schemas, not
    ``public``, rendered from the registry when a guild is provisioned. The
    admin fixture can't exercise the policy at runtime, so we inspect
    ``pg_policies`` in a freshly provisioned guild schema."""
    guild = await create_guild(session)
    expected = {
        "projects",
        "tasks",
        "files",
        "comments",
        "initiatives",
        "tags",
        "queues",
        "queue_items",
        "calendars",
        "calendar_events",
    }
    result = await session.exec(
        text(
            "SELECT tablename, policyname, cmd, permissive "
            "FROM pg_policies "
            "WHERE schemaname = :schema "
            "AND policyname = 'soft_delete_admin_purge'"
        ).bindparams(schema=guild_schema_name(guild.id))
    )
    rows = result.all()
    found_tables = {row[0] for row in rows}
    assert expected.issubset(found_tables), f"missing on: {expected - found_tables}"
    for tname, pname, cmd, permissive in rows:
        if tname in expected:
            assert cmd == "DELETE", f"{tname}: {pname} cmd={cmd}"
            assert permissive == "RESTRICTIVE", (
                f"{tname}: {pname} permissive={permissive}"
            )


# ---------------------------------------------------------------------------
# Upload preservation
# ---------------------------------------------------------------------------


async def test_soft_delete_file_preserves_uploads(session: AsyncSession):
    """Soft-deleting a native file leaves its referenced Upload row
    alone so the image still works after a restore."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    initiative = await create_initiative(session, guild, user)

    upload = Upload(
        filename="abc123.png",
        created_by=user.id,
        size_bytes=1234,
    )
    session.add(upload)
    await session.commit()

    doc = File(
        initiative_id=initiative.id,
        name="With image",
        file_type=FileType.lexical,
        content={"text": "uses /uploads/abc123.png"},
        featured_image_url="/uploads/abc123.png",
        created_by=user.id,
    )
    session.add(doc)
    await session.commit()
    await session.refresh(doc)

    await soft_delete_entity(
        session, doc, deleted_by_user_id=user.id, retention_days=30
    )
    await session.commit()

    # Upload row + filename still present after soft-delete.
    from sqlmodel import select

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
        size_bytes=1234,
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
    from app.models.tenant.comment import Comment
    from app.models.platform.guild import CommunityRole
    from app.testing.factories import (
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
    task = await _create_task(session, project, title="Task with comments")

    parent = Comment(
        task_id=task.id,
        created_by=user.id,
        content="Top-level",
    )
    session.add(parent)
    await session.commit()
    await session.refresh(parent)

    reply = Comment(
        task_id=task.id,
        created_by=user.id,
        content="Reply",
        parent_comment_id=parent.id,
    )
    session.add(reply)
    await session.commit()

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
        Upload(filename=name, created_by=user.id, size_bytes=10) for name in names
    )
    newest = await file_versions.add_version(
        session,
        doomed,
        created_by=user.id,
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
    from the repaired content."""
    from sqlmodel import select

    from app.core.relationships import RelationshipType, node_id
    from app.core.search import SearchEntityType
    from app.models.tenant.relationship import EntityRelationship
    from app.services.tenant import content_references
    from app.services.tenant.relationships import Endpoint
    from app.services.tenant.soft_delete import hard_purge_entity
    from app.testing.factories import create_file

    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    initiative = await create_initiative(session, guild, user)
    target = await create_file(session, initiative, user, name="Target")
    linking = await create_file(
        session,
        initiative,
        user,
        name="Linking",
        content=_linking_content(target.id),
        yjs_state=b"stale-collab-state",
    )
    await content_references.sync_for_entity(
        session,
        Endpoint(SearchEntityType.file, linking.id),
        body=linking.content,
        author_id=user.id,
    )
    await session.commit()

    await soft_delete_entity(
        session, target, deleted_by_user_id=user.id, retention_days=30
    )
    await session.commit()

    await hard_purge_entity(session, target)
    await session.commit()

    refreshed = (
        await session.exec(
            select(File)
            .where(File.id == linking.id)
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


async def test_hard_purge_unlinks_references_in_trashed_linking_files(
    session: AsyncSession,
):
    """A linking file sitting in the trash gets its references unlinked too —
    restoring it after the purge must not bring back a dangling link."""
    from app.core.search import SearchEntityType
    from app.services.tenant import content_references
    from app.services.tenant.relationships import Endpoint
    from app.services.tenant.soft_delete import hard_purge_entity
    from app.testing.factories import create_file

    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    initiative = await create_initiative(session, guild, user)
    target = await create_file(session, initiative, user, name="Target")
    linking = await create_file(
        session,
        initiative,
        user,
        name="Trashed Linking",
        content=_linking_content(target.id),
    )
    await content_references.sync_for_entity(
        session,
        Endpoint(SearchEntityType.file, linking.id),
        body=linking.content,
        author_id=user.id,
    )
    await session.commit()

    # Both files go to the trash; only the target is purged.
    await soft_delete_entity(
        session, linking, deleted_by_user_id=user.id, retention_days=30
    )
    await soft_delete_entity(
        session, target, deleted_by_user_id=user.id, retention_days=30
    )
    await session.commit()

    await hard_purge_entity(session, target)
    await session.commit()

    refreshed = (
        await session.exec(
            select_including_deleted(File)
            .where(File.id == linking.id)
            .options(undefer(File.content))
        )
    ).one()
    assert _unlinked(refreshed.content)


# ---------------------------------------------------------------------------
# Restoring a tree that has archived content in it
# ---------------------------------------------------------------------------


async def test_restore_initiative_brings_back_an_archived_queues_items(
    session: AsyncSession,
):
    """A queue item carries no ``archived_at``: inside an archived queue it is
    simply live, because that is the only state it has. Restoring the
    initiative has to put it back in exactly that state."""
    from app.models.tenant.queue import QueueItem
    from app.services.tenant.archive import archive_entity
    from app.testing.factories import create_queue, create_queue_item

    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    initiative = await create_initiative(session, guild, user)
    queue = await create_queue(session, initiative, user)
    item = await create_queue_item(session, queue)
    await archive_entity(session, queue)
    await session.commit()

    await soft_delete_entity(
        session, initiative, deleted_by_user_id=user.id, retention_days=30
    )
    await session.commit()

    await restore_entity(session, initiative)
    await session.commit()

    refreshed = (
        await session.exec(
            select_including_deleted(QueueItem).where(QueueItem.id == item.id)
        )
    ).one()
    assert refreshed.deleted_at is None
    refreshed_queue = (
        await session.exec(select_including_deleted(Queue).where(Queue.id == queue.id))
    ).one()
    assert refreshed_queue.deleted_at is None
    assert refreshed_queue.archived_at is not None


async def test_restore_initiative_brings_back_an_archived_files_comments(
    session: AsyncSession,
):
    """Same rule, one hop further down: archiving a file never touches the
    comments on it, so they come back out of the trash unstamped."""
    from app.models.tenant.comment import Comment
    from app.services.tenant.archive import archive_entity
    from app.testing.factories import create_comment, create_file

    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    initiative = await create_initiative(session, guild, user)
    file = await create_file(session, initiative, user)
    comment = await create_comment(session, user, file=file)
    await archive_entity(session, file)
    await session.commit()

    await soft_delete_entity(
        session, initiative, deleted_by_user_id=user.id, retention_days=30
    )
    await session.commit()

    await restore_entity(session, initiative)
    await session.commit()

    refreshed = (
        await session.exec(
            select_including_deleted(Comment).where(Comment.id == comment.id)
        )
    ).one()
    assert refreshed.deleted_at is None


async def test_soft_delete_project_takes_its_own_thread(session: AsyncSession):
    """A project's conversation is filed under the project, so it goes into the
    bin with it and comes back with it."""
    from app.models.tenant.comment import Comment
    from app.testing.factories import create_comment

    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    initiative = await create_initiative(session, guild, user)
    project = await create_project(session, initiative, user)
    comment = await create_comment(session, user, project=project)
    reply = await create_comment(
        session, user, project=project, parent_comment_id=comment.id
    )

    await soft_delete_entity(
        session, project, deleted_by_user_id=user.id, retention_days=30
    )
    await session.commit()

    async def stamps() -> set:
        rows = await session.exec(
            select_including_deleted(Comment.deleted_at).where(
                Comment.id.in_([comment.id, reply.id])
            )
        )
        return set(rows.all())

    assert await stamps() == {project.deleted_at}

    await restore_entity(session, project)
    await session.commit()

    assert await stamps() == {None}


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
    fk: str,
    user: User,
    built: dict[type, SQLModel],
) -> SQLModel:
    """A row of ``model`` filed under ``parent`` through ``fk``. ``built`` holds
    the rows above ``parent``, by model, for a child that names one of them."""
    from app.core.tools import Tool
    from app.models.tenant._mixins import tool_models
    from app.models.tenant.calendar_event import CalendarEvent
    from app.models.tenant.comment import Comment
    from app.models.tenant.counter import Counter
    from app.models.tenant.collection import Collection
    from app.models.tenant.queue import QueueItem
    from app.models.tenant.wiki import Wiki, WikiPage
    from app.testing.factories import (
        TOOL_FACTORIES,
        create_calendar_event,
        create_comment,
        create_counter,
        create_collection,
        create_queue_item,
        create_task,
        create_wiki_page,
    )

    models = tool_models()
    tool = next((t for t in Tool if models.get(t.plural) is model), None)
    if tool is not None:
        return await TOOL_FACTORIES[tool](session, parent, user)
    if model is Task:
        return await create_task(session, parent)
    if model is QueueItem:
        return await create_queue_item(session, parent)
    if model is Counter:
        return await create_counter(session, parent)
    if model is CalendarEvent:
        if fk != "calendar_id":
            # An occurrence of a series, in the series' calendar.
            on_model, on_fk = _first_way_up(CalendarEvent)
            return await create_calendar_event(
                session,
                built[on_model],
                user,
                **{fk: parent.id, "original_start": parent.start_at},
            )
        return await create_calendar_event(session, parent, user)
    if model is Collection:
        return await create_collection(session, parent, user)
    if model is WikiPage:
        if fk == "wiki_id":
            return await create_wiki_page(session, parent, user)
        return await create_wiki_page(session, built[Wiki], user, **{fk: parent.id})
    if model is Comment:
        if fk != "parent_comment_id":
            return await create_comment(
                session, user, **{fk.removesuffix("_id"): parent}
            )
        # A reply sits on the same thing as the comment it answers.
        on_model, on_fk = _first_way_up(Comment)
        return await create_comment(
            session, user, **{on_fk.removesuffix("_id"): built[on_model], fk: parent.id}
        )
    raise AssertionError(f"this test has no way to file a {model.__name__}")


def _first_way_up(model: type) -> tuple[type, str]:
    return next((p, fk) for p, fk in CASCADE_PARENTS[model] if p is not model)


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
    parent_model, fk = _first_way_up(model)
    parent = built.get(parent_model) or await _build(
        session, parent_model, initiative, user, built
    )
    built[model] = await _file(session, model, parent, fk, user, built)
    return built[model]


def _trash_kind(model: type) -> str:
    from app.api.v1.tenant_endpoints.trash import ENTITY_REGISTRY

    return next(kind for kind, (m, _) in ENTITY_REGISTRY.items() if m is model)


def _trash_edges() -> list:
    return [
        pytest.param(parent, child, fk, id=f"{child.__name__}.{fk}")
        for parent, children in CASCADE_CHILDREN.items()
        for child, fk in children
    ]


def _under_an_initiative() -> list:
    return [
        pytest.param(model, id=model.__name__)
        for model in (Initiative, *CASCADE_PARENTS)
    ]


@pytest.mark.parametrize("archived", [False, True])
@pytest.mark.parametrize(("parent_model", "child_model", "fk"), _trash_edges())
async def test_nothing_comes_back_under_something_still_in_the_trash(
    session: AsyncSession, client, parent_model, child_model, fk, archived
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
    child = await _file(session, child_model, parent, fk, user, built)
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
    tool = ownership_service.tool_for_row(row)
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
