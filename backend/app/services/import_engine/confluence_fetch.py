"""Reading Confluence spaces into a bundle the ordinary backup importer applies.

The Confluence half of the Atlassian fetch, and the same shape as the Jira
one: the calls and the paging live here, the mapping is pure and lives in
``confluence_mapping``, and the applying is ``backup.apply_backup``. It writes
no content row and opens no routed session — its one artifact is the zip.

Each space becomes one wiki envelope in a manifest naming the one initiative
the person picked, carried as ``target_initiative_id``.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Awaitable, BinaryIO, Callable, Optional
from urllib.parse import quote

from app.core.messages import ImportEngineMessages
from app.services.import_engine import confluence_attachments, confluence_mapping
from app.services.import_engine.atlassian import (
    AtlassianCredential,
    Heartbeat,
    Walk,
    get_file,
    get_json,
    throttled,
)
from app.services.import_engine.contract import ImportEngineError
from app.services.import_engine.jira_attachments import (
    AssetBudget,
    AssetSink,
    StoredImage,
)
from app.services.import_engine import limits as import_limits

logger = logging.getLogger(__name__)

#: Pages per request. The API's own ceiling; each page carries its body, so a
#: request is held in memory whole.
PAGE_LIMIT = 250

#: A hard stop on paging, whatever the site says: ``_links.next`` is the
#: site's to hand back, and a loop that trusts it without a bound is a loop
#: somebody else controls.
MAX_PAGE_REQUESTS = 200

#: How deep a chain of folders is followed before it is treated as the top.
MAX_FOLDER_DEPTH = 20

#: How deep a thread of replies is followed.
MAX_REPLY_DEPTH = 10

#: Account ids per ``users-bulk`` request.
USERS_PER_REQUEST = 100

#: Held back from the envelope's byte bound for the wiki row and the
#: manifest's own framing.
_ENVELOPE_RESERVE_BYTES = 256 * 1024

_ACCOUNT_ID = re.compile(r'ri:account-id="([^"]{1,128})"')


@dataclass
class ConfluenceFetchReport:
    """What the fetch found, for the plan the wizard shows. Counts only."""

    spaces: int = 0
    pages: int = 0
    #: Folders, and pages with children and no words of their own, that were
    #: given a list of what sits beneath them.
    containers: int = 0
    #: What the converter left out, by kind — a macro's name, ``image`` for a
    #: picture that did not come over.
    dropped: Counter[str] = field(default_factory=Counter)
    #: Spaces ticked that the token could not read.
    unreadable_spaces: list[str] = field(default_factory=list)
    #: Spaces the import's size limit cut short or left out, by key.
    spaces_over_limit: list[str] = field(default_factory=list)
    #: Pages left out because the space's wiki would have been too large to
    #: import in one piece, or the import's row budget was spent.
    pages_over_limit: int = 0
    #: Files the pages show or link to, left at the source because
    #: attachments were not asked for.
    attachments: int = 0
    #: Pictures the pages show, coming over as uploads.
    images: int = 0
    #: Files — and pictures no page shows — coming over as files.
    files: int = 0
    #: What both will take up.
    attachment_bytes: int = 0
    #: Too large, past the bundle's budget, a type never brought, or one the
    #: site would not hand over.
    attachments_skipped: int = 0
    #: Files left behind because the initiative cannot take files.
    files_blocked: int = 0
    #: Comments carried onto the pages, footer and inline alike.
    comments: int = 0
    #: Inline comments marked resolved at the source, left behind with their
    #: replies: the discussion they held is over.
    comments_resolved: int = 0
    #: Tags the pages' labels will become.
    labels: int = 0

    @property
    def dropped_nodes(self) -> int:
        return sum(self.dropped.values())


def _next_path(payload: dict) -> Optional[str]:
    """The next page of a v2 listing, as a path on the site.

    The API hands back a path under ``/wiki``; anything that does not look
    like one of its own listings ends the walk rather than being followed.
    """
    links = payload.get("_links")
    link = links.get("next") if isinstance(links, dict) else None
    if not isinstance(link, str) or not link:
        return None
    path = link if link.startswith("/wiki/") else f"/wiki{link}"
    return path if path.startswith("/wiki/api/v2/") else None


async def fetch_space(credential: AtlassianCredential, key: str) -> dict:
    """The space row: its id, name, description and home page."""
    payload = await get_json(
        credential,
        f"/wiki/api/v2/spaces?keys={quote(key, safe='')}&description-format=plain",
    )
    results = payload.get("results") if isinstance(payload, dict) else None
    space = results[0] if isinstance(results, list) and results else None
    if not isinstance(space, dict) or not space.get("id"):
        raise ImportEngineError(ImportEngineMessages.IMPORT_SOURCE_UNREACHABLE)
    return space


async def fetch_pages(
    credential: AtlassianCredential,
    space_id: str,
    *,
    max_pages: int,
    walk: Optional[Walk] = None,
) -> list[dict[str, Any]]:
    """Every current page in the space, with its storage-format body.

    Current only: a draft is somebody's unfinished work, and an archived page
    is one the space itself set aside. ``walk`` hears whether every page was
    read, or the read stopped at ``max_pages`` or the request bound.
    """
    pages: list[dict[str, Any]] = []
    path: Optional[str] = (
        f"/wiki/api/v2/spaces/{quote(space_id, safe='')}/pages"
        f"?body-format=storage&status=current&limit={PAGE_LIMIT}"
    )
    for _ in range(MAX_PAGE_REQUESTS):
        if path is None or len(pages) >= max_pages:
            break
        payload = await get_json(credential, path)
        if not isinstance(payload, dict):
            break
        results = payload.get("results")
        if isinstance(results, list):
            pages.extend(page for page in results if isinstance(page, dict))
        path = _next_path(payload)
    if walk is not None:
        walk.complete = path is None and len(pages) <= max_pages
    return pages[:max_pages]


async def fetch_labels(
    credential: AtlassianCredential, page_id: str
) -> tuple[str, ...]:
    """A page's labels. One that will not answer has none — not worth
    failing the space over. Being throttled is, as everywhere else."""
    try:
        payload = await get_json(
            credential, f"/wiki/api/v2/pages/{page_id}/labels?limit=250"
        )
    except ImportEngineError as exc:
        if exc.code == ImportEngineMessages.IMPORT_SOURCE_RATE_LIMITED:
            raise
        return ()
    return confluence_mapping.page_labels(payload)


async def fetch_folders(
    credential: AtlassianCredential, pages: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """The folders the pages sit in, and the folders those sit in.

    A folder is not a page, so the page listing leaves it out; it is read on
    its own, up the chain, for as far as folders go.
    """
    wanted = {
        str(page.get("parentId"))
        for page in pages
        if page.get("parentType") == "folder" and page.get("parentId")
    }
    folders: dict[str, Any] = {}
    for _ in range(MAX_FOLDER_DEPTH):
        wanted -= folders.keys()
        if not wanted:
            break
        found: set[str] = set()
        for folder_id in sorted(wanted):
            if not folder_id.isdigit():
                continue
            try:
                folder = await get_json(credential, f"/wiki/api/v2/folders/{folder_id}")
            except ImportEngineError as exc:
                if exc.code == ImportEngineMessages.IMPORT_SOURCE_RATE_LIMITED:
                    raise
                continue
            if not isinstance(folder, dict):
                continue
            folders[folder_id] = folder
            if folder.get("parentType") == "folder" and folder.get("parentId"):
                found.add(str(folder["parentId"]))
        wanted = found
    return list(folders.values())


async def fetch_user_names(
    credential: AtlassianCredential, account_ids: set[str]
) -> dict[str, str]:
    """Who each account is, by the name the site shows for them.

    A name, never an address: who that is *here* is the people step's to
    answer. An account the site will not name keeps none, and its mentions
    keep the words they were written with.
    """
    names: dict[str, str] = {}
    ids = sorted(account_ids)
    for start in range(0, len(ids), USERS_PER_REQUEST):
        batch = ids[start : start + USERS_PER_REQUEST]
        try:
            payload = await get_json(
                credential,
                "/wiki/api/v2/users-bulk",
                method="POST",
                json={"accountIds": batch},
            )
        except ImportEngineError as exc:
            if exc.code == ImportEngineMessages.IMPORT_SOURCE_RATE_LIMITED:
                raise
            logger.info("confluence users unreadable code=%s", exc.code)
            continue
        results = payload.get("results") if isinstance(payload, dict) else None
        for user in results if isinstance(results, list) else []:
            if not isinstance(user, dict):
                continue
            account = str(user.get("accountId") or "")
            name = str(user.get("displayName") or user.get("publicName") or "").strip()
            if account and name:
                names[account] = name
    return names


async def fetch_attachments(
    credential: AtlassianCredential, page_id: str
) -> list[confluence_attachments.PageAttachment]:
    """What a page has attached. A page whose list will not answer has
    none — not worth failing the space over. Being throttled is."""
    found: list[confluence_attachments.PageAttachment] = []
    path: Optional[str] = f"/wiki/api/v2/pages/{page_id}/attachments?limit={PAGE_LIMIT}"
    for _ in range(MAX_PAGE_REQUESTS):
        if path is None:
            break
        try:
            payload = await get_json(credential, path)
        except ImportEngineError as exc:
            if exc.code == ImportEngineMessages.IMPORT_SOURCE_RATE_LIMITED:
                raise
            break
        found.extend(confluence_attachments.read_attachments(payload))
        path = _next_path(payload) if isinstance(payload, dict) else None
    return found


async def fetch_page_media(
    credential: AtlassianCredential,
    page_id: str,
    *,
    guild_id: int,
    budget: AssetBudget,
    store: AssetSink,
    report: confluence_attachments.AttachmentReport,
    files_allowed: bool,
    tick: Optional[Heartbeat] = None,
) -> confluence_attachments.PageMedia:
    """A page's attachments, downloaded within what the bundle can hold."""

    async def download(
        attachment: confluence_attachments.PageAttachment,
        max_bytes: int,
        target: BinaryIO,
    ) -> int:
        # The download answers with one hop to Atlassian's media host.
        return await get_file(
            credential,
            f"/wiki/rest/api/content/{page_id}/child/attachment/"
            f"{attachment.id}/download",
            target,
            max_bytes=max_bytes,
            follow_redirect=True,
        )

    return await confluence_attachments.download_page_attachments(
        await fetch_attachments(credential, page_id),
        guild_id=guild_id,
        download=download,
        store=store,
        budget=budget,
        report=report,
        files_allowed=files_allowed,
        tick=tick,
    )


async def _listing(credential: AtlassianCredential, path: str) -> list[dict[str, Any]]:
    """Every row of a v2 listing, bounded like the page walk is."""
    rows: list[dict[str, Any]] = []
    next_path: Optional[str] = path
    for _ in range(MAX_PAGE_REQUESTS):
        if next_path is None:
            break
        payload = await get_json(credential, next_path)
        if not isinstance(payload, dict):
            break
        results = payload.get("results")
        if isinstance(results, list):
            rows.extend(row for row in results if isinstance(row, dict))
        next_path = _next_path(payload)
    return rows


async def fetch_comments(
    credential: AtlassianCredential,
    page_id: str,
    report: Optional[ConfluenceFetchReport] = None,
) -> list[confluence_mapping.SourceComment]:
    """What was said on a page: its footer comments and its inline ones, with
    every reply. An inline comment marked resolved is left behind, replies
    and all, and counted. A thread that will not answer is left out rather
    than failing the space. Being throttled is not."""
    found: list[confluence_mapping.SourceComment] = []
    for kind in ("footer-comments", "inline-comments"):

        async def walk(path: str, parent: Optional[str], depth: int) -> None:
            try:
                rows = await _listing(credential, path)
            except ImportEngineError as exc:
                if exc.code == ImportEngineMessages.IMPORT_SOURCE_RATE_LIMITED:
                    raise
                return
            for raw in rows:
                comment = confluence_mapping.read_comment(raw, parent_id=parent)
                if comment is None:
                    continue
                if comment.resolved and parent is None:
                    if report is not None:
                        report.comments_resolved += 1
                    continue
                found.append(comment)
                if depth < MAX_REPLY_DEPTH:
                    await walk(
                        f"/wiki/api/v2/{kind}/{comment.id}/children"
                        f"?body-format=storage&limit={PAGE_LIMIT}",
                        comment.id,
                        depth + 1,
                    )

        await walk(
            f"/wiki/api/v2/pages/{page_id}/{kind}?body-format=storage&limit={PAGE_LIMIT}",
            None,
            0,
        )
    return found


def _account_ids(
    pages: list[confluence_mapping.SourcePage],
    comments: Optional[dict[str, list[confluence_mapping.SourceComment]]] = None,
) -> set[str]:
    ids = {page.author_id for page in pages if page.author_id}
    for page in pages:
        if page.body:
            ids.update(_ACCOUNT_ID.findall(page.body))
    for thread in (comments or {}).values():
        for comment in thread:
            if comment.author_id:
                ids.add(comment.author_id)
            ids.update(_ACCOUNT_ID.findall(comment.body))
    return ids


@dataclass
class ConfluenceFetched:
    """Everything a Confluence fetch read, ready to be written into a bundle."""

    envelopes: list[tuple[str, dict[str, Any]]]
    people: Counter[str]
    report: ConfluenceFetchReport
    #: The pictures the pages show, restored as uploads.
    images: list[StoredImage] = field(default_factory=list)
    #: Each space's uploaded files, by space key.
    files: dict[str, list[confluence_attachments.PageFile]] = field(
        default_factory=dict
    )


async def fetch_spaces(
    credential: AtlassianCredential,
    *,
    space_keys: list[str],
    app_version: str,
    progress: Optional[Callable[[ConfluenceFetchReport], Awaitable[None]]] = None,
    max_rows: Optional[int] = None,
    guild_id: Optional[int] = None,
    asset_budget: Optional[AssetBudget] = None,
    store: Optional[AssetSink] = None,
    files_allowed: bool = True,
    include_comments: bool = False,
) -> ConfluenceFetched:
    """Read the chosen spaces and return what was read plus what it found.

    A space the token cannot read is counted, not fatal; every one unreadable
    fails the fetch, because then the selection is what is wrong. ``progress``
    hears the running report after each space, and raising from it stops the
    walk there — how a cancelled job ends.

    ``asset_budget`` is what the bundle can still hold for attachments —
    shared with the issues, when both are read — and without one none are
    fetched. ``files_allowed`` false is an initiative that cannot take uploaded files: only the pictures the pages show come. ``include_comments``
    brings what was said on each page, each comment a row of the import's
    budget like a page is.
    """
    if not space_keys:
        raise ImportEngineError(ImportEngineMessages.IMPORT_SOURCE_NOTHING_SELECTED)
    if asset_budget is not None and store is None:
        raise ValueError("attachments need somewhere to be stored")

    gathered = Gathered()
    report = gathered.report

    async def beat() -> None:
        if progress is not None:
            await progress(report)

    tick = throttled(beat)
    remaining = import_limits.IMPORT_FETCH_MAX_ROWS if max_rows is None else max_rows
    downloads = gathered.downloads
    max_bytes = max(
        0, import_limits.IMPORT_FETCH_MAX_SPACE_BYTES - _ENVELOPE_RESERVE_BYTES
    )

    for position, key in enumerate(space_keys):
        if remaining <= 1:
            # The budget is spent: this space and every one after it are left
            # out, and the plan says which.
            logger.info("confluence fetch row budget spent, stopping at space=%s", key)
            report.spaces_over_limit.extend(space_keys[position:])
            break
        walk = Walk()
        try:
            space = await fetch_space(credential, key)
            raw_pages = await fetch_pages(
                credential, str(space["id"]), max_pages=remaining - 1, walk=walk
            )
            pages: list[confluence_mapping.SourcePage] = []
            for raw in raw_pages:
                page_id = str(raw.get("id") or "")
                page = confluence_mapping.read_page(
                    raw,
                    await fetch_labels(credential, page_id)
                    if page_id.isdigit()
                    else (),
                )
                if page is not None:
                    pages.append(page)
                await tick()
            for raw in await fetch_folders(credential, raw_pages):
                folder = confluence_mapping.read_folder(raw)
                if folder is not None:
                    pages.append(folder)
            comments: dict[str, list[confluence_mapping.SourceComment]] = {}
            if include_comments:
                room = remaining - 1 - len(pages)
                for page in pages:
                    if page.is_folder or room <= 0:
                        continue
                    thread = (await fetch_comments(credential, page.id, report))[:room]
                    if thread:
                        comments[page.id] = thread
                        room -= len(thread)
                    await tick()
            users = await fetch_user_names(credential, _account_ids(pages, comments))
            media: dict[str, confluence_attachments.PageMedia] = {}
            if asset_budget is not None and store is not None and guild_id is not None:
                for page in pages:
                    if not page.is_folder:
                        media[page.id] = await fetch_page_media(
                            credential,
                            page.id,
                            guild_id=guild_id,
                            budget=asset_budget,
                            store=store,
                            report=downloads,
                            files_allowed=files_allowed,
                            tick=tick,
                        )
                        await tick()
        except ImportEngineError as exc:
            if exc.code == ImportEngineMessages.IMPORT_SOURCE_RATE_LIMITED:
                raise
            logger.info("confluence space unreadable key=%s code=%s", key, exc.code)
            report.unreadable_spaces.append(key)
        else:
            mapped = await asyncio.to_thread(
                confluence_mapping.build_wiki_envelope,
                space=space,
                pages=pages,
                users=users,
                site_url=credential.site_url,
                app_version=app_version,
                max_bytes=max_bytes,
                media=media,
                files_allowed=files_allowed,
                comments=comments,
            )
            gathered.add(key, mapped, counted_references=asset_budget is None)
            if not walk.complete:
                report.spaces_over_limit.append(key)
            remaining -= mapped.pages + mapped.comments + 1
        gathered.settle()
        if progress is not None:
            await progress(report)

    if not gathered.envelopes:
        raise ImportEngineError(ImportEngineMessages.IMPORT_SOURCE_UNREACHABLE)

    return gathered.fetched()


class Gathered:
    """What mapping each space produced, and the running report — kept the
    same way whether the spaces were read from a site or from an export."""

    def __init__(self) -> None:
        self.report = ConfluenceFetchReport()
        self.downloads = confluence_attachments.AttachmentReport()
        self.envelopes: list[tuple[str, dict[str, Any]]] = []
        self.people: Counter[str] = Counter()
        self.images: list[StoredImage] = []
        self.files: dict[str, list[confluence_attachments.PageFile]] = {}
        self._labels: set[str] = set()
        self._unshown_blocked = 0

    def add(
        self,
        key: str,
        mapped: confluence_mapping.MappedSpace,
        *,
        counted_references: bool,
    ) -> None:
        """Take one mapped space. ``counted_references`` counts the files its
        pages name as left behind, for a read that brought no attachments."""
        report = self.report
        self.envelopes.append((key, mapped.envelope))
        self.images.extend(mapped.uploads)
        if mapped.files:
            self.files[key] = mapped.files
        self.people.update(mapped.people)
        report.spaces += 1
        report.pages += mapped.pages
        report.containers += mapped.containers
        report.dropped.update(mapped.dropped)
        report.pages_over_limit += mapped.over_limit
        if counted_references:
            report.attachments += sum(len(a) for a in mapped.attachments.values())
        report.images += len(mapped.uploads)
        report.files += len(mapped.files)
        report.attachment_bytes += sum(
            blob.size_bytes
            for blob in (*mapped.uploads, *(f.stored for f in mapped.files))
        )
        self._unshown_blocked += mapped.files_blocked
        for entry in mapped.envelope["pages"]:
            self._labels.update(tag.casefold() for tag in entry["tags"])
        report.labels = len(self._labels)
        report.comments += mapped.comments

    def settle(self) -> None:
        """Bring the download counts into the report."""
        downloads = self.downloads
        self.report.attachments_skipped = (
            downloads.oversize + downloads.unreadable + downloads.refused
        )
        self.report.files_blocked = downloads.blocked + self._unshown_blocked

    def fetched(self) -> ConfluenceFetched:
        return ConfluenceFetched(
            envelopes=self.envelopes,
            people=self.people,
            report=self.report,
            images=self.images,
            files=self.files,
        )
