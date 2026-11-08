"""``initiative-wiki`` importer: the wiki row, its pages, the shape they sit
in, and the tags on both.

The tree arrives as slugs. Pages are written into the envelope in the order
the navigation draws them — siblings by position, not a walk down each branch
— so a child can appear before its parent. Every page is therefore created
first and filed second, once the whole slug map exists.

Sharing does not cross, here or in any other envelope: who may read a wiki is
a fact about the community it was written in. The importer owns what it
creates.

A page can name people — who wrote it, and anybody its body mentions — and
other pages, by slug. Those are placed once every page exists: a writer the
people step placed becomes the page's author, a mention of somebody placed
links to them, and a mention of a page links to the page it became.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.search import SearchEntityType
from app.core.tools import Tool, tool_envelope_type
from app.models.platform.user import User
from app.models.tenant.initiative import Initiative, PermissionKey
from app.models.tenant.wiki import Wiki, WikiPage
from app.schemas.tenant.import_envelopes import WikiEnvelope, WikiPageEnvelope
from app.services.import_engine.common import (
    handle_key,
    load_initiative_member_handles,
    parse_datetime,
    unique_name_in_initiative,
)
from app.services.import_engine.contract import EnvelopeImportResult
from app.services.import_engine.context import ImportContext
from app.services.import_engine.importers._base import (
    PropertyRestore,
    TagRestore,
    grant_ownership,
    parse_envelope,
)
from app.services.import_engine.links import links_to_pages, wiki_page_slug_ref
from app.services.import_engine.mentions import MENTION_HANDLE, place_mention_node
from app.services.import_engine.references import note_or_settle
from app.services.import_engine.people import (
    PeopleMap,
    quoted_account,
    user_reference_handles,
)
from app.services.tenant.names import slugify, unique_slug

logger = logging.getLogger(__name__)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.schemas.tenant.backup_export import ManifestPerson


class WikiImporter:
    envelope_type = tool_envelope_type(Tool.wiki)
    permission = PermissionKey.create_wikis

    def validate(self, envelope: dict[str, Any]) -> BaseModel:
        return parse_envelope(WikiEnvelope, envelope)

    def people(self, validated: BaseModel) -> list["ManifestPerson"]:
        """Whoever wrote a page, and whoever a page mentions, most-named
        first — both are placed through the people step's answer."""
        from app.schemas.tenant.backup_export import ManifestPerson

        envelope: WikiEnvelope = validated  # ty: ignore[invalid-assignment] — validate() returned this model
        seen: dict[str, ManifestPerson] = {}
        counts: dict[str, int] = {}
        comments: dict[str, int] = {}
        for page in envelope.pages:
            named = [
                (page.author_handle, page.author_name),
                *((handle, None) for handle in page.mention_handles),
            ]
            for comment in page.comments:
                named.append((comment.author_handle, comment.author_name))
                named.extend((handle, None) for handle in comment.mention_handles)
                if comment.author_handle and comment.author_handle.strip():
                    key = handle_key(comment.author_handle.strip())
                    comments[key] = comments.get(key, 0) + 1
            for handle, name in named:
                handle = (handle or "").strip()
                if not handle:
                    continue
                key = handle_key(handle)
                counts[key] = counts.get(key, 0) + 1
                person = seen.setdefault(
                    key, ManifestPerson(handle=handle, name=name, comment_count=0)
                )
                if person.name is None:
                    person.name = name
        # A text document filed in it mentions people the same way a page
        # does, and a person-valued property anywhere in it names somebody.
        for handle in (
            *(
                handle
                for filed in envelope.files
                if filed.envelope is not None
                for handle in filed.envelope.mention_handles
            ),
            *user_reference_handles(envelope.model_dump(mode="json")),
        ):
            handle = (handle or "").strip()
            if not handle:
                continue
            key = handle_key(handle)
            counts[key] = counts.get(key, 0) + 1
            seen.setdefault(
                key, ManifestPerson(handle=handle, name=None, comment_count=0)
            )
        for key, person in seen.items():
            person.comment_count = comments.get(key, 0)
        return sorted(
            seen.values(),
            key=lambda p: (-counts[handle_key(p.handle)], p.handle.lower()),
        )

    def count(self, validated: BaseModel) -> int:
        envelope: WikiEnvelope = validated  # ty: ignore[invalid-assignment] — validate() returned this model
        # A wiki's size is what is written in it, plus the row naming it. A
        # comment is a row like a page is, and so is a file filed in it.
        return (
            len(envelope.pages)
            + sum(len(page.comments) for page in envelope.pages)
            + len(envelope.files)
            + 1
        )

    def archive_assets(
        self, envelope: dict[str, Any]
    ) -> list[tuple[dict[str, Any], str]]:
        """The uploads filed in an exported wiki, whose bytes its zip carries
        under ``assets/``."""
        filed = envelope.get("files")
        if not isinstance(filed, list):
            return []
        return [
            (entry["upload"], "file")
            for entry in filed
            if isinstance(entry, dict) and isinstance(entry.get("upload"), dict)
        ]

    async def apply(
        self,
        session: AsyncSession,
        *,
        envelope: BaseModel,
        target_initiative: Initiative,
        importer: User,
        context: ImportContext | None = None,
    ) -> EnvelopeImportResult:
        env: WikiEnvelope = envelope  # ty: ignore[invalid-assignment] — validate() returned this model
        warnings: list[str] = []

        # The settings an export carried; absent ones keep the model's defaults.
        settings = env.model_dump(
            include={
                "page_order",
                "contents_depth",
                "show_connections",
                "show_updated_at",
                "reading_width",
                "accent_color",
            },
            exclude_none=True,
        )
        wiki = Wiki(
            name=await unique_name_in_initiative(
                session, Wiki, target_initiative.id, env.name
            ),
            description=env.description,
            initiative_id=target_initiative.id,
            created_by=importer.id,
            **settings,
        )
        session.add(wiki)
        await session.flush()

        await grant_ownership(
            session,
            tool=Tool.wiki,
            entity_id=wiki.id,
            target_initiative=target_initiative,
            importer=importer,
        )

        tags = TagRestore(session)
        await tags.attach(wiki, env.tags)
        props = PropertyRestore(
            session, initiative_id=target_initiative.id, context=context
        )
        await props.attach(wiki, env.properties)

        people = context.people if context is not None else PeopleMap()
        member_handles = (
            await load_initiative_member_handles(
                session, initiative_id=target_initiative.id
            )
            if any(
                p.author_handle or p.mention_handles or p.comments for p in env.pages
            )
            else {}
        )

        # Pass one: every page exists before any page is filed.
        slugs = _assign_slugs(env.pages)
        page_ids: dict[str, int] = {}
        rows: list[WikiPage] = []
        for page_env, slug in zip(env.pages, slugs):
            author = quoted_account(
                page_env.author_handle, people=people, member_handles=member_handles
            )
            row = WikiPage(
                wiki_id=wiki.id,
                title=page_env.title,
                slug=slug,
                position=page_env.position,
                is_draft=page_env.is_draft,
                content=page_env.content or {},
                created_by=author if author is not None else importer.id,
                # When it was written, where the envelope says so. Absent
                # leaves the model's own default — the moment of the import,
                # which is the only time this row can honestly claim.
                **_page_timestamps(page_env),
            )
            session.add(row)
            await session.flush()
            page_ids[slug] = row.id  # ty: ignore[invalid-assignment] — persisted row, id is set
            rows.append(row)
            if context is not None:
                context.links.register(
                    page_env.external_ref, SearchEntityType.wiki_page, row.id
                )
                context.links.register(
                    wiki_page_slug_ref(wiki.id, page_env.slug.strip()),
                    SearchEntityType.wiki_page,
                    row.id,
                )
            await tags.attach(row, page_env.tags)
            await props.attach(row, page_env.properties)

        # Pass two: file each page under its parent, by slug.
        parents, cut_loops, unknown = _parent_slugs(env.pages, slugs)
        for slug, parent_slug in parents.items():
            parent_id = page_ids.get(parent_slug) if parent_slug else None
            if parent_id is not None:
                await session.exec(
                    WikiPage.__table__.update()
                    .where(WikiPage.__table__.c.id == page_ids[slug])
                    .values(parent_page_id=parent_id)
                )
        if cut_loops:
            warnings.append(f"pages_filed_under_themselves:{cut_loops}")
        if unknown:
            warnings.append(f"missing_parent_pages:{unknown}")

        # Pass three: what a page names, now that every page has an id.
        bodies = [
            body
            for page in env.pages
            for body in (page.content, *(c.content for c in page.comments))
        ]
        wanted = {key for body in bodies for key in _jira_keys(body)}
        # An issue that came over in this same import is already known by the
        # ref its task was registered under; anything else is looked up by
        # the key an earlier Jira import recorded.
        jira_tasks: dict[str, int] = {}
        if context is not None:
            for key in wanted:
                endpoint = context.links.lookup(f"jira:{key}")
                if endpoint is not None and endpoint.kind == SearchEntityType.task:
                    jira_tasks[key] = endpoint.id
        jira_tasks.update(await _tasks_by_jira_key(session, wanted - jira_tasks.keys()))
        # A file the pages link to was written earlier in this job, as a
        # file of its own.
        files: dict[str, int] = {}
        if context is not None:
            for ref in {r for body in bodies for r in _marks(body, "importRef")}:
                endpoint = context.links.lookup(ref)
                if endpoint is not None and endpoint.kind == SearchEntityType.file:
                    files[ref] = endpoint.id
        by_original = {page.slug.strip(): slug for page, slug in zip(env.pages, slugs)}
        pages_by_slug = {
            original: page_ids[assigned]
            for original, assigned in by_original.items()
            if assigned in page_ids
        }

        def placed(content: Any, handles: list[str]) -> Any:
            mentioned = {
                handle: account
                for handle in handles
                if (
                    account := quoted_account(
                        handle, people=people, member_handles=member_handles
                    )
                )
                is not None
            }
            return _place_references(
                content,
                page_ids=pages_by_slug,
                mentioned=mentioned,
                jira_tasks=jira_tasks,
                file_ids=files,
            )

        comment_count = 0
        for page_env, row in zip(env.pages, rows):
            linked = placed(row.content, page_env.mention_handles)
            if linked is not None:
                row.content = linked
                session.add(row)
            # An exported page's references wait for the rest of the job: what
            # they name may be in an entry that has not been applied yet.
            row.content = note_or_settle(
                context, SearchEntityType.wiki_page, row.id, row.content
            )
            comment_count += await _write_comments(
                session,
                page_env,
                row,
                place=placed,
                people=people,
                member_handles=member_handles,
                importer=importer,
                context=context,
            )

        if env.home_page and env.home_page in page_ids:
            wiki.home_page_id = page_ids[env.home_page]
            session.add(wiki)
        elif env.home_page:
            warnings.append("missing_home_page:1")
        # A template that did not travel is left unset.
        if env.template_page in pages_by_slug:
            wiki.template_page_id = pages_by_slug[env.template_page]
            session.add(wiki)

        filed, filed_tags = await _place_files(
            session,
            env,
            wiki,
            pages_by_slug,
            target_initiative=target_initiative,
            importer=importer,
            context=context,
            warnings=warnings,
        )

        return EnvelopeImportResult(
            entity_id=wiki.id,
            entity_title=wiki.name,
            created={
                Tool.wiki.plural: 1,
                "pages": len(env.pages),
                "comments": comment_count,
                "tags": tags.created + filed_tags[0],
                Tool.file.plural: filed,
                "properties": props.created,
            },
            matched={"tags": tags.matched + filed_tags[1], "properties": props.matched},
            unmatched_handles=await props.settle(wiki),
            warnings=warnings,
        )


async def _place_files(
    session: AsyncSession,
    env: WikiEnvelope,
    wiki: Wiki,
    pages_by_slug: dict[str, int],
    *,
    target_initiative: Initiative,
    importer: User,
    context: ImportContext | None,
    warnings: list[str],
) -> tuple[int, tuple[int, int]]:
    """Create the files the wiki's export carried and file each where it
    sat: under its page, at its place, and joined to the wiki by the edge
    that says it belongs there. Returns how many were filed, and the tags
    (created, matched) those that were filed restored.

    Creating a file takes what creating one anywhere takes, so an
    initiative with files off, or somebody who may not create them there,
    gets the wiki without them and is told so.
    """
    if not env.files:
        return 0, (0, 0)
    from app.core.relationships import RelationshipType
    from app.db.session import routed_guild_id
    from app.services.import_engine import engine as import_engine
    from app.services.import_engine.contract import ImportEngineError
    from app.services.import_engine.importers.file import FileImporter
    from app.services.import_engine.links import IMPORT_PROVENANCE
    from app.services.tenant import relationships as relationships_service
    from app.services.tenant import wikis as wikis_service
    from app.services.tenant.relationships import Endpoint

    files = FileImporter()
    try:
        await import_engine.load_target_initiative(
            session,
            guild_id=routed_guild_id(session),
            initiative_id=target_initiative.id,
            importer=files,
            user=importer,
        )
    except ImportEngineError:
        warnings.append(f"files_left_behind:{len(env.files)}")
        return 0, (0, 0)

    filed = 0
    missing = 0
    tags_created = tags_matched = 0
    for entry in env.files:
        file_id: int | None = None
        # Counted only once the file's savepoint has held.
        entry_tags = (0, 0)
        try:
            async with session.begin_nested():
                if entry.envelope is not None:
                    result = await files.apply(
                        session,
                        envelope=entry.envelope,
                        target_initiative=target_initiative,
                        importer=importer,
                        context=context,
                    )
                    file_id = result.entity_id
                    entry_tags = (
                        result.created.get("tags", 0),
                        result.matched.get("tags", 0),
                    )
                elif entry.upload is not None:
                    file_id, entry_tags = await _upload_file(
                        session,
                        entry.upload,
                        target_initiative=target_initiative,
                        importer=importer,
                        context=context,
                    )
        except Exception:
            logger.exception("wiki import: a filed file failed")
            file_id = None
        if file_id is None:
            missing += 1
            continue
        tags_created += entry_tags[0]
        tags_matched += entry_tags[1]
        if context is not None:
            context.links.register(entry.external_ref, SearchEntityType.file, file_id)
        await relationships_service.create(
            session,
            source=Endpoint(SearchEntityType.file, file_id),
            relationship_type=RelationshipType.part_of,
            target=Endpoint(SearchEntityType.wiki, wiki.id),
            provenance=IMPORT_PROVENANCE,
            created_by=importer.id,
        )
        wikis_service.place_file(
            wiki,
            file_id,
            parent_page_id=pages_by_slug.get(entry.page) if entry.page else None,
            position=entry.position,
        )
        session.add(wiki)
        filed += 1
    if missing:
        warnings.append(f"missing_filed_files:{missing}")
    return filed, (tags_created, tags_matched)


async def _upload_file(
    session: AsyncSession,
    upload: Any,
    *,
    target_initiative: Initiative,
    importer: User,
    context: ImportContext | None,
) -> tuple[int | None, tuple[int, int]]:
    """A filed upload, as an uploaded file over the bytes its zip brought, and
    the tags (created, matched) restoring it took. One
    whose file is not stored here — left out of the zip, or refused on the way
    in — or is not a type an uploaded file holds is not created."""
    from app.db.session import routed_guild_id
    from app.core.file_types import type_of_media
    from app.models.tenant.file import File
    from app.models.tenant.upload import Upload
    from app.services.tenant import file_versions

    key = (upload.storage_key or "").strip()
    stored = (
        await session.exec(select(Upload).where(Upload.filename == key))
    ).one_or_none()
    if not key or stored is None:
        return None, (0, 0)
    filename = upload.original_filename or key
    content_type = await file_versions.stored_file_type(
        routed_guild_id(session),
        key,
        filename=filename,
    )
    if content_type is None:
        return None, (0, 0)
    file = File(
        name=upload.name,
        file_type=type_of_media(content_type),
        content={},
        initiative_id=target_initiative.id,
        created_by=importer.id,
    )
    session.add(file)
    await session.flush()
    await grant_ownership(
        session,
        tool=Tool.file,
        entity_id=file.id,
        target_initiative=target_initiative,
        importer=importer,
    )
    await file_versions.add_version(
        session,
        file,
        created_by=importer.id,
        file_url=f"/uploads/{routed_guild_id(session)}/{key}",
        original_filename=filename,
        file_content_type=content_type,
        file_size=stored.size_bytes,
    )
    tags = TagRestore(session)
    await tags.attach(file, upload.tags)
    props = PropertyRestore(
        session, initiative_id=target_initiative.id, context=context
    )
    await props.attach(file, upload.properties)
    await props.settle(file)
    return file.id, (tags.created, tags.matched)


async def _write_comments(
    session: AsyncSession,
    page_env: WikiPageEnvelope,
    row: WikiPage,
    *,
    place: Any,
    people: PeopleMap,
    member_handles: dict[str, int],
    importer: User,
    context: ImportContext | None,
) -> int:
    """Write what was said on one page, as its comment thread.

    Each body's references are placed the way the page's own are, and then
    written as comment text. A comment belongs to the account the people step
    placed its author on; anybody else's is written by the importer with the
    source's name beside it, never under somebody else's face. A reply whose
    parent did not come stands on its own.
    """
    from datetime import timezone

    from app.models.tenant.comment import Comment
    from app.services.import_engine.comment_markdown import comment_markdown

    written: dict[str, int] = {}
    count = 0
    for comment_env in page_env.comments:
        content = comment_env.content
        body = comment_markdown(place(content, comment_env.mention_handles) or content)
        if not body:
            continue
        author = quoted_account(
            comment_env.author_handle, people=people, member_handles=member_handles
        )
        source_name = (
            comment_env.author_name or comment_env.author_handle or ""
        ).strip()
        created = parse_datetime(comment_env.created_at)
        comment = Comment(
            wiki_page_id=row.id,
            content=body,
            created_by=author if author is not None else importer.id,
            imported_author_name=None
            if author is not None
            else (source_name[:200] or None),
            parent_comment_id=written.get(comment_env.reply_to_ref or ""),
            created_at=created or datetime.now(timezone.utc),
        )
        session.add(comment)
        if context is not None and links_to_pages(body):
            # A link to a page in another space of this job is joined once
            # every wiki is in.
            await session.flush()
            context.links.note_body(SearchEntityType.comment, comment.id)
        if comment_env.external_ref:
            await session.flush()
            written[comment_env.external_ref] = comment.id  # ty: ignore[invalid-assignment] — persisted row, id is set
        count += 1
    return count


def _text_node(text: str) -> dict[str, Any]:
    return {
        "type": "text",
        "version": 1,
        "text": text,
        "format": 0,
        "style": "",
        "mode": "normal",
        "detail": 0,
    }


def _marks(content: Any, name: str) -> set[str]:
    """Every value of one import placeholder a page's content carries."""
    found: set[str] = set()

    def walk(node: Any) -> None:
        if not isinstance(node, dict):
            return
        value = node.get(name)
        if isinstance(value, str) and value:
            found.add(value)
        for child in node.get("children") or []:
            walk(child)

    walk(content.get("root") if isinstance(content, dict) else None)
    return found


def _jira_keys(content: Any) -> set[str]:
    """The Jira issue keys a page's content waits to have placed."""
    return _marks(content, "importJiraKey")


async def _tasks_by_jira_key(session: AsyncSession, keys: set[str]) -> dict[str, int]:
    """Which task each Jira issue became, found by the key the Jira import
    records on every task it writes.

    Anywhere in the community this person can read — a Confluence space and
    the Jira project its pages talk about are often filed in different
    initiatives. An issue imported twice points at the newer copy. An issue
    whose key property was left out at import, or that never came over, is
    not found, and the page keeps its link to Jira.
    """
    if not keys:
        return {}
    from sqlalchemy import or_

    from app.models.tenant.metadata import MetadataDefinition, MetadataValue
    from app.models.tenant.task import Task
    from app.services.import_engine.jira_fields import JIRA_KEY_PROPERTY

    rows = (
        await session.exec(
            select(MetadataValue.value_text, Task.id)
            .join(
                MetadataDefinition,
                MetadataDefinition.id == MetadataValue.property_id,
            )
            .join(
                Task,
                (MetadataValue.entity_type == "task")
                & (Task.id == MetadataValue.entity_id),
            )
            .where(
                # The name the import gave it, or the one it was renamed to
                # when that name was already taken by a different kind.
                or_(
                    MetadataDefinition.name == JIRA_KEY_PROPERTY,
                    MetadataDefinition.name.like(f"{JIRA_KEY_PROPERTY} (%"),
                ),
                MetadataValue.value_text.in_(sorted(keys)),
                Task.deleted_at.is_(None),
            )
            .order_by(Task.id)
        )
    ).all()
    found: dict[str, int] = {}
    for key, task_id in rows:
        if key is not None and task_id is not None:
            found[key] = task_id
    return found


def _place_references(
    content: Any,
    *,
    page_ids: dict[str, int],
    mentioned: dict[str, int],
    jira_tasks: dict[str, int] | None = None,
    file_ids: dict[str, int] | None = None,
) -> dict[str, Any] | None:
    """``content`` with its import references resolved, or ``None`` if it
    had none.

    A wiki-page mention carrying an ``importSlug`` points at the page that
    slug became; one whose page did not arrive is its text again. A person's
    mention with no account yet gets the one the people step placed its
    handle (``mentionHandle``, from an export) or its name (from Confluence)
    on, and stays a name otherwise.

    A Jira issue the page names by ``importJiraKey`` points at the task that
    issue became, when it came over: the macro's mention and its live status
    chip take the task's id, and a link to the issue becomes a mention of the
    task. When it did not, the mention is a link back to Jira again, the chip
    is left out, and a link stays the link it was.

    A file mention carrying an ``importRef`` points at the file that
    file became in this job, and is the file's name again if it did not.
    """
    if not isinstance(content, dict):
        return None
    tasks = jira_tasks or {}
    files = file_ids or {}
    changed = False

    def walk(node: Any) -> Any:
        nonlocal changed
        if not isinstance(node, dict):
            return node
        node_type = node.get("type")
        if node_type == "entity-mention" and "importSlug" in node:
            changed = True
            slug = node.get("importSlug")
            target = page_ids.get(slug) if isinstance(slug, str) else None
            text = str(node.get("text") or "")
            if target is None:
                return _text_node(text)
            placed = {k: v for k, v in node.items() if k != "importSlug"}
            placed["entityId"] = target
            return placed
        if node_type == "entity-mention" and "importRef" in node:
            changed = True
            ref = node.get("importRef")
            file_id = files.get(ref) if isinstance(ref, str) else None
            if file_id is None:
                return _text_node(str(node.get("text") or ""))
            placed = {k: v for k, v in node.items() if k != "importRef"}
            placed["entityId"] = file_id
            return placed
        jira_key = node.get("importJiraKey")
        if isinstance(jira_key, str):
            changed = True
            task_id = tasks.get(jira_key)
            bare = {
                k: v for k, v in node.items() if k not in ("importJiraKey", "importUrl")
            }
            if node_type == "entity-mention":
                if task_id is not None:
                    return {**bare, "entityId": task_id}
                url = node.get("importUrl")
                text = str(node.get("text") or jira_key)
                if not isinstance(url, str) or not url:
                    return _text_node(text)
                return {
                    "type": "link",
                    "version": 1,
                    "direction": "ltr",
                    "format": "",
                    "indent": 0,
                    "url": url,
                    "rel": "noopener noreferrer",
                    "target": "_blank",
                    "title": None,
                    "children": [_text_node(text)],
                }
            if node_type == "smart-chip":
                return {**bare, "entityId": task_id} if task_id is not None else None
            if node_type == "link" and task_id is not None:
                words = "".join(
                    str(child.get("text") or "")
                    for child in node.get("children") or []
                    if isinstance(child, dict)
                )
                return {
                    "type": "entity-mention",
                    "version": 1,
                    "entityType": "task",
                    "entityId": task_id,
                    "text": words or jira_key,
                }
            node = bare
        if node_type == "mention" and isinstance(node.get(MENTION_HANDLE), str):
            # An exported page names its person by handle rather than by the
            # account it had where it was written.
            changed = True
            return place_mention_node(node, mentioned.get(node[MENTION_HANDLE]))
        if (
            node_type == "mention"
            and node.get("mentionUserId") is None
            and node.get("mentionName") in mentioned
        ):
            changed = True
            return place_mention_node(node, mentioned[node["mentionName"]])
        children = node.get("children")
        if isinstance(children, list):
            walked = [walk(child) for child in children]
            return {
                **node,
                "children": [child for child in walked if child is not None],
            }
        return node

    placed = walk(content.get("root"))
    if not changed:
        return None
    return {**content, "root": placed}


def _page_timestamps(page_env: WikiPageEnvelope) -> dict[str, datetime]:
    """The page's own times, where the envelope carried them.

    Returned as kwargs so an absent or unparseable stamp falls through to the
    model default rather than overwriting it — a restore that could not read a
    date is not a restore that should claim the page has none.
    """
    stamps: dict[str, datetime] = {}
    for field_name, raw in (
        ("created_at", page_env.created_at),
        ("updated_at", page_env.updated_at),
    ):
        parsed = parse_datetime(raw)
        if parsed is not None:
            stamps[field_name] = parsed
    return stamps


def _assign_slugs(pages: list[WikiPageEnvelope]) -> list[str]:
    """A slug per page, unique within this wiki and in envelope order.

    A page's slug is its address, and the table holds one address per wiki.
    An envelope from a real export already satisfies that; a hand-made one
    may not, so a repeat is suffixed rather than allowed to fail the import.
    """
    assigned: dict[str, None] = {}
    for page in pages:
        base = page.slug.strip() or slugify(page.title, fallback="page")
        assigned[unique_slug(base, assigned)] = None
    return list(assigned)


def _parent_slugs(
    pages: list[WikiPageEnvelope], slugs: list[str]
) -> tuple[dict[str, str | None], int, int]:
    """Each page's parent slug, with anything that would not be a tree cut
    loose: a page filed under itself, a loop of pages filed under each other,
    and a parent no page in the envelope answers to. Each becomes a top-level
    page and is counted, because half a wiki filed correctly is worth more
    than a failed restore.
    """
    # The envelope names parents by their ORIGINAL slug; map those onto the
    # slugs actually assigned, which differ only where one was suffixed.
    renamed = {
        page.slug.strip(): slug for page, slug in zip(pages, slugs) if page.slug.strip()
    }
    parents: dict[str, str | None] = {}
    unknown = 0
    for page, slug in zip(pages, slugs):
        wanted = (page.parent or "").strip()
        if not wanted:
            parents[slug] = None
            continue
        resolved = renamed.get(wanted)
        if resolved is None or resolved == slug:
            parents[slug] = None
            unknown += 1
            continue
        parents[slug] = resolved

    cut_loops = 0
    for slug in list(parents):
        seen = {slug}
        walker = parents[slug]
        while walker is not None:
            if walker in seen:
                parents[slug] = None
                cut_loops += 1
                break
            seen.add(walker)
            walker = parents.get(walker)
    return parents, cut_loops, unknown
