"""A Confluence space → a wiki envelope (design §6.2).

Pure: it takes what the fetch read — the space, its pages and folders, their
labels, and who the accounts they name are — and returns the envelope the
ordinary wiki importer applies. No call to the site is made here, so every
rule can be tested against plain data.

The tree survives. A page keeps its parent, by slug, and its place among its
siblings. A Confluence folder has a title and children but no body, so it
becomes a page whose body lists them; a page with children and nothing of its
own to say gets the same list, rather than arriving blank.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

from app.services.import_engine.confluence_attachments import (
    PageFile,
    PageMedia,
    file_ref,
)
from app.services.import_engine.confluence_storage import (
    PageTarget,
    storage_to_lexical,
)
from app.services.import_engine.jira_attachments import StoredImage
from app.services.tenant.names import slugify, unique_slug

#: A title the wiki cannot hold is cut to what it can.
MAX_TITLE_LENGTH = 255


@dataclass(frozen=True)
class SourcePage:
    """One page or folder as the fetch read it, in the shape mapping needs."""

    id: str
    title: str
    parent_id: str | None
    position: int | None
    #: The storage-format body. ``None`` for a folder, which has none.
    body: str | None
    author_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    labels: tuple[str, ...] = ()

    @property
    def is_folder(self) -> bool:
        return self.body is None


@dataclass(frozen=True)
class SourceComment:
    """One comment on a page as the fetch read it."""

    id: str
    #: The storage-format body.
    body: str
    parent_id: str | None = None
    author_id: str | None = None
    created_at: str | None = None
    #: The words an inline comment was anchored to, quoted above it — the
    #: wiki's comments sit under the page rather than beside a sentence.
    selection: str | None = None
    #: An inline comment somebody marked resolved: the discussion is over.
    resolved: bool = False


@dataclass
class MappedSpace:
    """One space as a wiki envelope, and what converting it cost."""

    envelope: dict[str, Any]
    pages: int = 0
    #: Folders and empty parents given a list of their children for a body.
    containers: int = 0
    #: What the converter left out, by kind, summed over every page.
    dropped: Counter[str] = field(default_factory=Counter)
    #: Pages that would have taken the envelope past what one may hold.
    over_limit: int = 0
    #: Everybody the pages name — authors and mentions — with how often.
    people: Counter[str] = field(default_factory=Counter)
    #: Attachment filenames the pages show or link to, by page id.
    attachments: dict[str, list[str]] = field(default_factory=dict)
    #: The pictures the kept pages show, to travel as uploads.
    uploads: list[StoredImage] = field(default_factory=list)
    #: Everything else the kept pages had attached, to become uploaded files
    #: filed under the page each came from.
    files: list[PageFile] = field(default_factory=list)
    #: Pictures a page never shows, left behind because the initiative
    #: cannot take files.
    files_blocked: int = 0
    #: Comments carried onto the kept pages.
    comments: int = 0


def read_page(raw: Any, labels: tuple[str, ...] = ()) -> SourcePage | None:
    """A v2 page object as a :class:`SourcePage`, or ``None`` if it is not
    one — the site's data is somebody else's, and a malformed row is skipped
    rather than trusted."""
    if not isinstance(raw, dict):
        return None
    page_id = str(raw.get("id") or "").strip()
    title = str(raw.get("title") or "").strip()
    if not page_id.isdigit() or not title:
        return None
    body = raw.get("body")
    storage = body.get("storage") if isinstance(body, dict) else None
    value = storage.get("value") if isinstance(storage, dict) else None
    version = raw.get("version")
    return SourcePage(
        id=page_id,
        title=title[:MAX_TITLE_LENGTH],
        parent_id=_id(raw.get("parentId")),
        position=_position(raw.get("position")),
        body=value if isinstance(value, str) else "",
        author_id=_text(raw.get("authorId")),
        created_at=_text(raw.get("createdAt")),
        updated_at=_text(version.get("createdAt"))
        if isinstance(version, dict)
        else None,
        labels=labels,
    )


def read_folder(raw: Any) -> SourcePage | None:
    """A v2 folder object as a body-less :class:`SourcePage`."""
    if not isinstance(raw, dict):
        return None
    folder_id = str(raw.get("id") or "").strip()
    title = str(raw.get("title") or "").strip()
    if not folder_id.isdigit() or not title:
        return None
    return SourcePage(
        id=folder_id,
        title=title[:MAX_TITLE_LENGTH],
        parent_id=_id(raw.get("parentId")),
        position=_position(raw.get("position")),
        body=None,
        author_id=_text(raw.get("authorId")),
        created_at=_text(raw.get("createdAt")),
    )


def read_comment(raw: Any, *, parent_id: str | None = None) -> SourceComment | None:
    """A v2 footer or inline comment as a :class:`SourceComment`, or ``None``
    for one that is malformed or has nothing in it."""
    if not isinstance(raw, dict):
        return None
    comment_id = _id(raw.get("id"))
    body = raw.get("body")
    storage = body.get("storage") if isinstance(body, dict) else None
    value = storage.get("value") if isinstance(storage, dict) else None
    if comment_id is None or not isinstance(value, str) or not value.strip():
        return None
    version = raw.get("version") if isinstance(raw.get("version"), dict) else {}
    properties = (
        raw.get("properties") if isinstance(raw.get("properties"), dict) else {}
    )
    selection = _text(properties.get("inlineOriginalSelection"))
    return SourceComment(
        id=comment_id,
        body=value,
        parent_id=parent_id or _id(raw.get("parentCommentId")),
        author_id=_text(version.get("authorId")),
        created_at=_text(version.get("createdAt")),
        selection=selection[:1000] if selection else None,
        resolved=str(raw.get("resolutionStatus") or "").lower() == "resolved",
    )


def comment_ref(comment_id: str) -> str:
    return f"confluence-comment:{comment_id}"


def page_labels(payload: Any) -> tuple[str, ...]:
    """The label names a ``/pages/{id}/labels`` answer lists."""
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        return ()
    names = []
    for label in results:
        name = str(label.get("name") or "").strip() if isinstance(label, dict) else ""
        if name and name not in names:
            names.append(name)
    return tuple(names)


def page_ref(page_id: str) -> str:
    """The name a page answers to in the job's links: ``confluence:123``."""
    return f"confluence:{page_id}"


def page_url(site_url: str, space_key: str, title: str) -> str:
    """Where a page lives at the source, by its space and title — for a link
    to a page the import did not bring."""
    return (
        f"{site_url.rstrip('/')}/wiki/display/{quote(space_key, safe='')}/"
        f"{quote(title.replace(' ', '+'), safe='+')}"
    )


def build_wiki_envelope(
    *,
    space: dict[str, Any],
    pages: list[SourcePage],
    users: dict[str, str],
    site_url: str,
    app_version: str,
    max_bytes: int | None = None,
    media: dict[str, PageMedia] | None = None,
    files_allowed: bool = True,
    comments: dict[str, list[SourceComment]] | None = None,
) -> MappedSpace:
    """The space's pages as one wiki envelope.

    ``users`` names the account ids the pages carry — authors, and anybody a
    body mentions. ``max_bytes`` bounds the envelope: pages that would take
    it past are left out and counted, whole, rather than truncated.

    ``media`` is what each page's attachments became, by page id. A picture
    the page shows renders from its upload; a link to a file becomes a
    mention of the file it will be. ``files_allowed`` false is an initiative
    that cannot take one, and only the shown pictures come.

    ``comments`` is what was said on each page, by page id; each is converted
    the way a page body is and carried on its page, a thread in reading order.
    """
    space_key = str(space.get("key") or "").strip()
    by_id = {page.id: page for page in pages}
    children: dict[str | None, list[SourcePage]] = {}
    for page in pages:
        parent = page.parent_id if page.parent_id in by_id else None
        children.setdefault(parent, []).append(page)
    for siblings in children.values():
        siblings.sort(key=lambda p: (p.position is None, p.position or 0, p.title))

    # The navigation order: each page, then what sits under it.
    ordered: list[SourcePage] = []
    seen: set[str] = set()

    def walk(parent: str | None) -> None:
        for page in children.get(parent, []):
            if page.id in seen:
                continue
            seen.add(page.id)
            ordered.append(page)
            walk(page.id)

    walk(None)
    # A loop in the tree reaches no root. Its pages still come over, from the
    # top; the importer cuts the loop when it files them.
    for page in pages:
        if page.id not in seen:
            seen.add(page.id)
            ordered.append(page)
            walk(page.id)

    slugs: dict[str, str] = {}
    taken: set[str] = set()
    for page in ordered:
        slugs[page.id] = unique_slug(slugify(page.title, fallback="page"), taken)
        taken.add(slugs[page.id])
    slug_by_title = {page.title.casefold(): slugs[page.id] for page in ordered}

    def resolve_page(title: str, key: str | None) -> PageTarget | None:
        if key and key != space_key:
            return PageTarget(url=page_url(site_url, key, title))
        slug = slug_by_title.get(title.strip().casefold())
        if slug is not None:
            return PageTarget(slug=slug)
        return PageTarget(url=page_url(site_url, space_key, title))

    mapped = MappedSpace(envelope={})
    envelope_pages: list[dict[str, Any]] = []
    budget = max_bytes
    positions: Counter[str | None] = Counter()
    for page in ordered:
        parent = page.parent_id if page.parent_id in by_id else None
        position = positions[parent]
        positions[parent] += 1
        mentions: list[str] = []
        shown: list[str] = []
        files = (media or {}).get(page.id) or PageMedia()
        if page.is_folder:
            content = None
        else:
            kids = children.get(page.id, [])
            result = storage_to_lexical(
                page.body,
                page=resolve_page,
                user=lambda account: users.get(account),
                image=files.images.get,
                # A link to a picture goes to the picture.
                attachment=files.images.get,
                file=lambda name, files=files: (
                    file_ref(files.files[name]) if name in files.files else None
                ),
                site_url=site_url,
                # Confluence's "children" macro draws the pages beneath this
                # one; so does this list.
                children=(
                    (lambda kids=kids: _child_list(kids, slugs)["root"]["children"][0])
                    if kids
                    else None
                ),
            )
            mapped.dropped.update(result.dropped)
            mentions = result.mentions
            shown = result.shown
            if result.attachments:
                mapped.attachments[page.id] = result.attachments
            content = None if _is_blank(result.content) else result.content
        if content is None:
            kids = children.get(page.id, [])
            content = _child_list(kids, slugs) if kids else _empty()
            if kids:
                mapped.containers += 1

        page_comments = [
            _comment_entry(
                comment,
                page=resolve_page,
                users=users,
                site_url=site_url,
                files=files,
                dropped=mapped.dropped,
            )
            for comment in _thread_order((comments or {}).get(page.id, []))
        ]
        entry: dict[str, Any] = {
            "title": page.title,
            "slug": slugs[page.id],
            "parent": slugs.get(parent) if parent else None,
            "position": position,
            "content": content,
            "tags": list(page.labels),
            "mention_handles": mentions,
            "external_ref": page_ref(page.id),
            "comments": page_comments,
        }
        author = users.get(page.author_id or "")
        if author:
            entry["author_handle"] = author
            entry["author_name"] = author
        if page.created_at:
            entry["created_at"] = page.created_at
        if page.updated_at or page.created_at:
            entry["updated_at"] = page.updated_at or page.created_at

        if budget is not None:
            size = len(json.dumps(entry))
            if size > budget:
                mapped.over_limit += 1
                continue
            budget -= size
        envelope_pages.append(entry)
        mapped.pages += 1
        mapped.uploads.extend(files.uploads(shown))
        if files_allowed:
            mapped.files.extend(
                PageFile(stored, slugs[page.id]) for stored in files.as_files(shown)
            )
        else:
            mapped.files_blocked += len(files.stored_images) - len(files.uploads(shown))
        for name in {name for name in (author, *mentions) if name}:
            mapped.people[name] += 1
        mapped.comments += len(page_comments)
        for comment in page_comments:
            for name in {
                name
                for name in (comment.get("author_handle"), *comment["mention_handles"])
                if name
            }:
                mapped.people[name] += 1

    home = _id(space.get("homepageId"))
    kept = {entry["slug"] for entry in envelope_pages}
    home_slug = slugs.get(home) if home else None
    mapped.envelope = {
        "type": "initiative-wiki",
        "schema_version": 1,
        "app_version": app_version,
        "name": str(space.get("name") or space_key or "Confluence").strip()[
            :MAX_TITLE_LENGTH
        ],
        "description": _description(space),
        "home_page": home_slug if home_slug in kept else None,
        "tags": [],
        "pages": envelope_pages,
    }
    return mapped


def _thread_order(comments: list[SourceComment]) -> list[SourceComment]:
    """Each comment followed by its replies, oldest first at every level, so
    a reply is written after what it answers. A reply to something that did
    not come stands at the top of the thread."""
    known = {comment.id for comment in comments}
    replies: dict[str | None, list[SourceComment]] = {}
    for comment in comments:
        parent = comment.parent_id if comment.parent_id in known else None
        replies.setdefault(parent, []).append(comment)
    for group in replies.values():
        group.sort(key=lambda c: (c.created_at or "", int(c.id)))

    ordered: list[SourceComment] = []
    seen: set[str] = set()

    def walk(parent: str | None) -> None:
        for comment in replies.get(parent, []):
            if comment.id in seen:
                continue
            seen.add(comment.id)
            ordered.append(comment)
            walk(comment.id)

    walk(None)
    return ordered


def _comment_entry(
    comment: SourceComment,
    *,
    page: Any,
    users: dict[str, str],
    site_url: str,
    files: PageMedia,
    dropped: Counter[str],
) -> dict[str, Any]:
    """One comment as its envelope entry: the body converted like a page's,
    an inline comment's anchor quoted above it."""
    result = storage_to_lexical(
        comment.body,
        page=page,
        user=lambda account: users.get(account),
        image=files.images.get,
        attachment=files.images.get,
        file=lambda name: file_ref(files.files[name]) if name in files.files else None,
        site_url=site_url,
    )
    dropped.update(result.dropped)
    content = result.content
    if comment.selection:
        quote = {
            "type": "quote",
            "version": 1,
            "direction": "ltr",
            "format": "",
            "indent": 0,
            "children": [
                {
                    "type": "text",
                    "version": 1,
                    "text": comment.selection,
                    "format": 0,
                    "detail": 0,
                    "mode": "normal",
                    "style": "",
                }
            ],
        }
        root = content["root"]
        content = {**content, "root": {**root, "children": [quote, *root["children"]]}}
    entry: dict[str, Any] = {
        "content": content,
        "external_ref": comment_ref(comment.id),
        "reply_to_ref": comment_ref(comment.parent_id) if comment.parent_id else None,
        "mention_handles": result.mentions,
    }
    author = users.get(comment.author_id or "")
    if author:
        entry["author_handle"] = author
        entry["author_name"] = author
    if comment.created_at:
        entry["created_at"] = comment.created_at
    return entry


def _child_list(kids: list[SourcePage], slugs: dict[str, str]) -> dict[str, Any]:
    """A body that is a list of links to the pages beneath."""
    items = [
        {
            "type": "listitem",
            "version": 1,
            "direction": "ltr",
            "format": "",
            "indent": 0,
            "value": index,
            "children": [
                {
                    "type": "entity-mention",
                    "version": 1,
                    "entityType": "wiki_page",
                    "entityId": 0,
                    "text": kid.title,
                    "importSlug": slugs[kid.id],
                }
            ],
        }
        for index, kid in enumerate(kids, start=1)
        if kid.id in slugs
    ]
    return {
        "root": {
            "type": "root",
            "version": 1,
            "direction": "ltr",
            "format": "",
            "indent": 0,
            "children": [
                {
                    "type": "list",
                    "version": 1,
                    "direction": "ltr",
                    "format": "",
                    "indent": 0,
                    "listType": "bullet",
                    "start": 1,
                    "tag": "ul",
                    "children": items,
                }
            ],
        }
    }


def _empty() -> dict[str, Any]:
    return storage_to_lexical("").content


def _is_blank(content: dict[str, Any]) -> bool:
    children = content.get("root", {}).get("children") or []
    return all(
        child.get("type") == "paragraph" and not child.get("children")
        for child in children
    )


def _description(space: dict[str, Any]) -> str | None:
    description = space.get("description")
    plain = description.get("plain") if isinstance(description, dict) else None
    value = plain.get("value") if isinstance(plain, dict) else None
    text = str(value or "").strip()
    return text or None


def _id(value: Any) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    text = str(value).strip()
    return text if text.isdigit() else None


def _position(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def _text(value: Any) -> str | None:
    text = str(value).strip() if isinstance(value, str) else ""
    return text or None
