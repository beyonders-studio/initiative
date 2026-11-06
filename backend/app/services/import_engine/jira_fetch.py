"""Reading a Jira project into a bundle the ordinary backup importer applies.

This is the orchestration half of the Jira fetch: the calls, the paging, and
the zip. The mapping it feeds is pure and lives in ``jira_mapping``; the
applying is ``backup.apply_backup``, which has existed since long before any
of this and knows nothing about Jira.

**It writes no content row.** The whole fetch produces exactly one artifact —
a zip in guild storage — and touches no table a person could see. That is what
makes it the one phase a crashed job can simply start over: there is nothing
half-applied to duplicate, only a partial payload to throw away (see the
worker's re-claim rule for ``fetching``).

**It never opens a routed session either.** Nothing here needs one: the
credential is read on the system engine and the bundle goes to storage under
an engine-internal key. The routed, RLS-enforced session appears in the apply
phase, unchanged, where rows are actually written.

The bundle is deliberately backup-shaped rather than a format of its own. A
Jira project becomes a manifest naming one initiative — the one the person
picked, carried as ``target_initiative_id`` so the applier files into it
rather than creating something — and one project envelope per project. Every
gate, every count and every report that a restore already has therefore
applies to an import from Jira without being written twice.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, BinaryIO, Callable, Optional

from app.core.messages import ImportEngineMessages
from app.services.import_engine import jira_attachments, jira_mapping, jira_sprints
from app.services.import_engine.atlassian import (
    AtlassianCredential,
    Heartbeat,
    Walk,
    get_file,
    get_json,
    throttled,
)
from app.services.import_engine.contract import ImportEngineError
from app.services.import_engine import limits as import_limits

logger = logging.getLogger(__name__)

#: Issues per search page. Jira allows far more, but a page is held in memory
#: whole and every issue carries its description, so this trades a few more
#: round trips for a bounded footprint.
ISSUE_PAGE_SIZE = 100

#: A hard stop on paging, whatever the site says. ``nextPageToken`` is the
#: site's to hand back, and a loop that trusts it without a bound is a loop
#: somebody else controls.
MAX_ISSUE_PAGES = 500

#: The fields the fetch asks for: every one a person can see on an issue.
#: Narrower than ``*all`` (no internal bookkeeping), but it has to be all the
#: navigable ones — which of a site's own fields anybody filled in is only
#: known by reading them, and that is the rule a property is created by
#: (§6.5).
ISSUE_FIELDS = ("*navigable",)

#: Asked for beside those when comments are wanted. The search returns the
#: first page of each issue's comments with its ``total``, so only an issue
#: with more than that costs a call of its own.
COMMENT_FIELD = "comment"

#: Asked for beside those when images are wanted: each issue's attachments,
#: with the size and type the download is decided by.
ATTACHMENT_FIELD = "attachment"

#: Comments per page when an issue's have to be read on their own.
COMMENT_PAGE_SIZE = 100

#: A hard stop on one issue's comment pages, for the same reason the issue
#: walk has one: the site decides how many pages there are.
MAX_COMMENT_PAGES = 50


@dataclass
class FetchReport:
    """What the fetch found, for the plan the wizard shows.

    Counts only — never a title, never a body. A job row records what
    happened, and a foreign server's content is not something to park in one.
    """

    projects: int = 0
    tasks: int = 0
    #: ADF nodes the walker could not render, summed over every description.
    #: The honest half of the degradation contract: it says what will be lost
    #: before anybody commits to the import.
    dropped_nodes: int = 0
    #: Issues the search returned that were not usable as tasks.
    skipped_issues: int = 0
    #: Projects asked for that the token could not read. Named so the plan can
    #: say which, rather than quietly importing fewer than were ticked.
    unreadable_projects: list[str] = field(default_factory=list)
    #: Projects the import's size limit cut short or left out, by key.
    projects_over_limit: list[str] = field(default_factory=list)
    #: Links and parents whose both ends were fetched — the edges the apply
    #: will draw.
    links: int = 0
    #: Links and parents whose other end is outside what was fetched: another
    #: project, an issue a narrowing left out, one the token cannot see. Said
    #: before anybody commits, because those connections will not come over.
    links_outside_selection: int = 0
    #: Every property the bundle declares, by name: its type, and how many
    #: tasks carry a value. The review step lists these for somebody to
    #: untick what they do not want (§5.4).
    properties: dict[str, tuple[str, int]] = field(default_factory=dict)
    #: Fields some issue filled that have no home here, by name.
    dropped_fields: list[str] = field(default_factory=list)
    #: Distinct sprints the fetched issues were in.
    sprints: int = 0
    #: Calendars they will land on — one per board.
    sprint_calendars: int = 0
    #: Sprints planned but never started: no dates, so no event.
    sprints_undated: int = 0
    #: Images that will come over as uploads, and their bytes.
    images: int = 0
    image_bytes: int = 0
    #: Images over the per-image cap or past the bundle's budget.
    images_oversize: int = 0
    #: Images the site would not hand over.
    images_unreadable: int = 0
    #: Files that are not images, each coming over as a file attached to
    #: its task, and their bytes.
    files: int = 0
    file_bytes: int = 0
    #: Files that are not images, left behind: attachments were not asked
    #: for, the initiative cannot take files, or the type is never brought.
    other_attachments: int = 0
    #: Comments that will come over.
    comments: int = 0
    #: Comments visible only to a role or group at the source, left behind
    #: rather than shown to the whole initiative.
    comments_restricted: int = 0
    #: Why sprints will not come over at all, as a code — the target
    #: initiative has no calendars, or the importer cannot create one there.
    #: ``None`` when they will.
    sprints_skipped: Optional[str] = None


async def fetch_issue_type_statuses(
    credential: AtlassianCredential, project_key: str
) -> list[Any]:
    """Every status this project's issue types can be in.

    Reported per issue type, so the same status arrives under Story and under
    Bug; the mapping takes the union.
    """
    payload = await get_json(credential, f"/rest/api/3/project/{project_key}/statuses")
    return payload if isinstance(payload, list) else []


async def fetch_board_column_order(
    credential: AtlassianCredential, project_key: str
) -> Optional[list[str]]:
    """The board's columns as status ids, or ``None`` when there is no board.

    A project can have none, and a board this token cannot read is the same
    thing as far as the import is concerned: the workflow order stands
    instead. Neither is worth failing a fetch over, so both come back
    ``None`` rather than raising.

    Being throttled is the exception. That is about the site, not the board,
    and quietly importing without the column order would hide it — so it is
    raised like everywhere else.
    """
    try:
        boards = await get_json(
            credential,
            f"/rest/agile/1.0/board?projectKeyOrId={project_key}&maxResults=1",
        )
    except ImportEngineError as exc:
        if exc.code == ImportEngineMessages.IMPORT_SOURCE_RATE_LIMITED:
            raise
        return None
    values = boards.get("values") if isinstance(boards, dict) else None
    if not isinstance(values, list) or not values:
        return None
    board = values[0]
    board_id = board.get("id") if isinstance(board, dict) else None
    if board_id is None:
        return None
    try:
        configuration = await get_json(
            credential, f"/rest/agile/1.0/board/{board_id}/configuration"
        )
    except ImportEngineError as exc:
        if exc.code == ImportEngineMessages.IMPORT_SOURCE_RATE_LIMITED:
            raise
        return None
    return jira_mapping.board_column_statuses(configuration)


async def iter_issue_pages(
    credential: AtlassianCredential,
    project_key: str,
    *,
    jql_extra: str | None = None,
    max_issues: int,
    include_comments: bool = False,
    include_attachments: bool = False,
    walk: Optional[Walk] = None,
) -> AsyncIterator[list[Any]]:
    """Every issue in the project, in Rank order, a page at a time.

    Rank order is what the team dragged them into, and it is the only ordering
    worth carrying — so it is asked for explicitly rather than left to
    whatever the index returns.

    ``jql_extra`` is the wizard's optional narrowing (a date range, an issue
    type), appended to the project clause rather than replacing it: the
    selection is the project, and a narrowing that could widen it would not be
    one.

    Paging stops at ``max_issues`` or :data:`MAX_ISSUE_PAGES`, whichever comes
    first. The cap is the caller's row budget; the page bound is the loop
    refusing to be driven forever by somebody else's cursor.
    """
    clause = f'project = "{project_key}"'
    if jql_extra and jql_extra.strip():
        clause = f"{clause} AND ({jql_extra.strip()})"
    jql = f"{clause} ORDER BY Rank ASC"

    seen = 0
    token: str | None = None
    for _ in range(MAX_ISSUE_PAGES):
        body: dict[str, Any] = {
            "jql": jql,
            "maxResults": min(ISSUE_PAGE_SIZE, max_issues - seen),
            "fields": [
                *ISSUE_FIELDS,
                *([COMMENT_FIELD] if include_comments else []),
                *([ATTACHMENT_FIELD] if include_attachments else []),
            ],
        }
        if token:
            body["nextPageToken"] = token
        payload = await get_json(
            credential, "/rest/api/3/search/jql", method="POST", json=body
        )
        if not isinstance(payload, dict):
            break
        page = payload.get("issues")
        cut = False
        if isinstance(page, list) and page:
            kept = page[: max_issues - seen]
            cut = len(kept) < len(page)
            seen += len(kept)
            yield kept
        # The cursor is the site's to hand back, so it is checked rather
        # than trusted: anything that is not a non-empty string ends the walk.
        cursor = payload.get("nextPageToken")
        if not isinstance(cursor, str) or not cursor:
            if walk is not None:
                walk.complete = not cut
            break
        if seen >= max_issues:
            break
        token = cursor


async def fetch_field_catalog(credential: AtlassianCredential) -> list[Any]:
    """Every field the site defines, with the schema that says its type.

    Read once per fetch, since it is the site's and not a project's. A site
    that will not answer is not worth failing the import over: the built-in
    fields still map by their own ids, and only the site's own fields go
    without a type — so they are left out rather than guessed at. Being
    throttled is the exception, as everywhere else.
    """
    try:
        payload = await get_json(credential, "/rest/api/3/field")
    except ImportEngineError as exc:
        if exc.code == ImportEngineMessages.IMPORT_SOURCE_RATE_LIMITED:
            raise
        logger.info("jira field catalog unreadable code=%s", exc.code)
        return []
    return payload if isinstance(payload, list) else []


async def complete_comments(credential: AtlassianCredential, issue: Any) -> None:
    """Fill in the rest of an issue's comments when the search held back some.

    The search carries each issue's first page with a ``total``; an issue
    with more is read on its own, oldest first, and the comment field is
    replaced with the whole list. One that will not answer keeps the page it
    had — a partial thread beats failing the project over it.
    """
    fields = issue.get("fields") if isinstance(issue, dict) else None
    field = fields.get(COMMENT_FIELD) if isinstance(fields, dict) else None
    if not isinstance(field, dict):
        return
    have = field.get("comments")
    total = field.get("total")
    if not isinstance(have, list) or not isinstance(total, int) or total <= len(have):
        return
    key = str(issue.get("key") or "").strip()
    if not key:
        return
    comments: list[Any] = []
    for page in range(MAX_COMMENT_PAGES):
        try:
            payload = await get_json(
                credential,
                f"/rest/api/3/issue/{key}/comment"
                f"?startAt={page * COMMENT_PAGE_SIZE}"
                f"&maxResults={COMMENT_PAGE_SIZE}&orderBy=created",
            )
        except ImportEngineError as exc:
            if exc.code == ImportEngineMessages.IMPORT_SOURCE_RATE_LIMITED:
                raise
            logger.info("jira comments unreadable key=%s code=%s", key, exc.code)
            return
        batch = payload.get("comments") if isinstance(payload, dict) else None
        if not isinstance(batch, list) or not batch:
            break
        comments.extend(batch)
        if len(comments) >= total:
            break
    if comments:
        field["comments"] = comments


@dataclass
class FetchedProject:
    """One project read from the site, and what the bundle-wide passes need
    from it once every project is in."""

    mapped: jira_mapping.MappedProject
    #: Issues the search returned, usable or not — what the row budget spent.
    issues_used: int
    #: ``(link id, far key)`` pairs, counted once all projects are read.
    link_ends: list[tuple[str, str]]
    #: Each issue's sprints, by issue key.
    sprints: dict[str, list[jira_sprints.Sprint]]
    #: Comments visible only to a role or group, left behind.
    restricted_comments: int
    #: The images downloaded for this project's issues.
    images: jira_attachments.ImageReport
    #: Whether every issue the project has was read, rather than the walk
    #: stopping at the row budget or the page bound.
    complete: bool = True


async def fetch_project_envelope(
    credential: AtlassianCredential,
    project: dict,
    *,
    app_version: str,
    jql_extra: str | None = None,
    max_issues: int,
    field_catalog: Any = None,
    include_comments: bool = False,
    image_budget: Optional[jira_attachments.AssetBudget] = None,
    store: Optional[jira_attachments.AssetSink] = None,
    guild_id: Optional[int] = None,
    files_allowed: bool = False,
    tick: Optional[Heartbeat] = None,
) -> FetchedProject:
    """One Jira project as an envelope, how many issues it cost, and what its
    issues are linked to.

    The issue count is returned separately from the mapping's own counts so
    the caller can spend a shared row budget across several projects rather
    than letting the first one take all of it — what it spent is how many
    issues came back, including the ones that turned out to be unusable.

    The link ends are ``(link id, far key)`` pairs. They come back raw
    because whether a far end was fetched is only known once every project
    has been read — a link between two ticked projects is not outside the
    selection.
    """
    key = str(project.get("key") or "").strip()
    statuses = await fetch_issue_type_statuses(credential, key)
    column_ids = await fetch_board_column_order(credential, key)

    column_names: Optional[list[str]] = None
    if column_ids:
        names_by_id = {
            str(status.get("id")): str(status.get("name") or "")
            for entry in statuses
            if isinstance(entry, dict)
            for status in entry.get("statuses") or []
            if isinstance(status, dict) and status.get("id") is not None
        }
        column_names = [
            names_by_id[status_id]
            for status_id in column_ids
            if status_id in names_by_id
        ]

    mapper = jira_mapping.ProjectMapper(
        project=project,
        issue_type_statuses=statuses,
        board_column_order=column_names,
        app_version=app_version,
        site_url=credential.site_url,
        field_catalog=field_catalog,
        include_comments=include_comments,
        guild_id=guild_id,
    )
    download: Optional[jira_attachments.Downloader] = None
    if image_budget is not None and guild_id is not None:
        if store is None:
            raise ValueError("attachments need somewhere to be stored")

        async def fetch_attachment(
            attachment_id: str, max_bytes: int, target: BinaryIO
        ) -> int:
            # redirect=false: the content itself, not a hop to a media host
            # this client would refuse to follow.
            return await get_file(
                credential,
                f"/rest/api/3/attachment/content/{attachment_id}?redirect=false",
                target,
                max_bytes=max_bytes,
            )

        download = fetch_attachment

    # Which sprints each issue was in, keyed by issue key. Built into events
    # only once every project is read: one sprint can hold issues from several.
    sprint_fields = jira_sprints.sprint_field_ids(field_catalog)
    images = jira_attachments.ImageReport()
    link_ends: list[tuple[str, str]] = []
    sprints: dict[str, list[jira_sprints.Sprint]] = {}
    restricted = 0
    issues_used = 0

    # A page at a time: each is completed, its files downloaded and its
    # issues mapped before the next is asked for, so the site's JSON for the
    # whole project is never held at once.
    walk = Walk()
    async for page in iter_issue_pages(
        credential,
        key,
        jql_extra=jql_extra,
        max_issues=max_issues,
        include_comments=include_comments,
        include_attachments=image_budget is not None,
        walk=walk,
    ):
        issues_used += len(page)
        if include_comments:
            for issue in page:
                await complete_comments(credential, issue)
                if tick is not None:
                    await tick()

        page_images = jira_attachments.ImageReport()
        if download is not None and image_budget is not None and store is not None:
            page_images = await jira_attachments.download_images(
                page,
                download=download,
                store=store,
                budget_bytes=image_budget.bytes_left,
                max_files=image_budget.files_left,
                files_allowed=files_allowed,
                tick=tick,
            )
            image_budget.bytes_left -= page_images.image_bytes + page_images.file_bytes
            image_budget.files_left -= page_images.images + page_images.files
            images.absorb(page_images)

        await asyncio.to_thread(
            mapper.add,
            page,
            images_by_issue=page_images.by_issue,
            files_by_issue=page_images.files_by_issue,
        )
        link_ends.extend(
            end for issue in page for end in jira_mapping.link_far_ends(issue)
        )
        for issue in page:
            if not isinstance(issue, dict):
                continue
            found = jira_sprints.issue_sprints(issue, sprint_fields)
            if found:
                sprints[str(issue.get("key") or "")] = found
            if include_comments:
                restricted += jira_mapping.restricted_comment_count(issue.get("fields"))
        if tick is not None:
            await tick()

    mapped = await asyncio.to_thread(mapper.finish)
    return FetchedProject(
        mapped=mapped,
        issues_used=issues_used,
        link_ends=link_ends,
        sprints=sprints,
        restricted_comments=restricted,
        images=images,
        complete=walk.complete,
    )


def _people(envelopes: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    """Everyone the bundle names, for the wizard's people step.

    Assignees, whoever a person field names — a Reporter, a site's own user
    fields — comment authors, and everybody a description or a comment
    @-mentions, since all of them are placed through the step's answer.
    Counted per appearance so the step can say how much hangs on getting one
    row right, and ordered most-named first.
    """
    from app.services.import_engine.people import user_reference_handles

    counts: dict[str, int] = {}
    comments: dict[str, int] = {}
    for _key, envelope in envelopes:
        for task in envelope.get("tasks") or []:
            named = [
                *(task.get("assignee_handles") or []),
                *user_reference_handles(task.get("properties") or []),
                *(task.get("mention_handles") or []),
                *(
                    handle
                    for comment in task.get("comments") or []
                    for handle in comment.get("mention_handles") or []
                ),
            ]
            for handle in named:
                name = str(handle).strip()
                if name:
                    counts[name] = counts.get(name, 0) + 1
            for comment in task.get("comments") or []:
                name = str(comment.get("author_handle") or "").strip()
                if name:
                    counts[name] = counts.get(name, 0) + 1
                    comments[name] = comments.get(name, 0) + 1
    return [
        {"handle": name, "name": name, "comment_count": comments.get(name, 0)}
        for name, _count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


def _count_links(
    report: FetchReport,
    envelopes: list[tuple[str, dict[str, Any]]],
    link_ends: list[tuple[str, str]],
) -> None:
    """Split the links into those that will be drawn and those that cannot.

    A link is counted once however many of its issues reported it (both sides
    of a Jira link do), and it is drawn only if its far end is among the tasks
    this bundle carries — in any of the projects ticked, not only its own.
    """
    fetched = {
        task["external_ref"].removeprefix("jira:")
        for _key, envelope in envelopes
        for task in envelope["tasks"]
        if task.get("external_ref")
    }
    far_by_link: dict[str, set[str]] = {}
    for link_id, far_key in link_ends:
        far_by_link.setdefault(link_id, set()).add(far_key)
    for far_keys in far_by_link.values():
        if far_keys <= fetched:
            report.links += 1
        else:
            report.links_outside_selection += 1


@dataclass
class JiraFetched:
    """Everything a Jira fetch read, ready to be written into a bundle."""

    envelopes: list[tuple[str, dict[str, Any]]]
    calendars: list[dict[str, Any]]
    images: list[jira_attachments.StoredImage]
    people: list[dict[str, Any]]
    report: FetchReport
    #: Rows the apply will spend on this: tasks, comments, projects and
    #: sprint calendars — what a fetch after this one has left to use.
    rows_used: int
    #: Attached files that are not pictures, each a file of its own.
    files: list[jira_attachments.StoredImage] = field(default_factory=list)


async def fetch_projects(
    credential: AtlassianCredential,
    *,
    project_keys: list[str],
    guild_id: int,
    app_version: str,
    jql_extra: str | None = None,
    progress: Optional[Callable[[FetchReport], Awaitable[None]]] = None,
    sprints_blocked_by: str | None = None,
    include_comments: bool = True,
    include_attachments: bool = True,
    link_pages: bool = False,
    asset_budget: Optional[jira_attachments.AssetBudget] = None,
    store: Optional[jira_attachments.AssetSink] = None,
    files_allowed: bool = False,
) -> JiraFetched:
    """Read the chosen projects and return what was read plus what it found.

    ``progress`` hears the running report after every project, read or not.
    It is how the job row shows the fetch moving, and how a cancelled job
    stops one: the callback raising ends the walk at the next project rather
    than after the last.

    A project the token cannot read is **counted, not fatal**: somebody who
    ticked four projects and can reach three should get the three and be told
    about the fourth, rather than a failed job and no explanation. Every
    project unreadable is a different matter — that is the selection being
    wrong, and it fails.

    ``sprints_blocked_by`` is the code for why sprints cannot land in the
    target initiative — its calendars are off, or the importer may not create
    one there. They are still counted, so the plan can say how many are being
    left behind, and no task is linked to a sprint that will not exist.
    """
    if not project_keys:
        raise ImportEngineError(ImportEngineMessages.IMPORT_SOURCE_NOTHING_SELECTED)

    report = FetchReport()

    async def beat() -> None:
        if progress is not None:
            await progress(report)

    tick = throttled(beat)
    link_ends: list[tuple[str, str]] = []
    remaining = import_limits.IMPORT_FETCH_MAX_ROWS
    envelopes: list[tuple[str, dict[str, Any]]] = []
    field_catalog = await fetch_field_catalog(credential)
    dropped_fields: set[str] = set()
    all_sprints: dict[int, jira_sprints.Sprint] = {}
    all_images: list[jira_attachments.StoredImage] = []
    all_files: list[jira_attachments.StoredImage] = []
    image_budget = (
        (asset_budget or jira_attachments.bundle_budget())
        if include_attachments
        else None
    )
    sprint_membership: dict[str, list[int]] = {}

    for position, key in enumerate(project_keys):
        if remaining <= 0:
            # The budget is spent: this project and every one after it are
            # left out, and the plan says which.
            logger.info("jira fetch row budget spent, stopping at project=%s", key)
            report.projects_over_limit.extend(project_keys[position:])
            break
        try:
            project = await get_json(credential, f"/rest/api/3/project/{key}")
            if not isinstance(project, dict):
                raise ImportEngineError(ImportEngineMessages.IMPORT_SOURCE_UNREACHABLE)
            fetched = await fetch_project_envelope(
                credential,
                project,
                app_version=app_version,
                jql_extra=jql_extra,
                max_issues=remaining,
                field_catalog=field_catalog,
                include_comments=include_comments,
                image_budget=image_budget,
                store=store,
                guild_id=guild_id,
                files_allowed=files_allowed,
                tick=tick,
            )
            mapped = fetched.mapped
        except ImportEngineError as exc:
            if exc.code == ImportEngineMessages.IMPORT_SOURCE_RATE_LIMITED:
                # Being throttled is about the site, not this project, and the
                # next one would be throttled too.
                raise
            logger.info("jira project unreadable key=%s code=%s", key, exc.code)
            report.unreadable_projects.append(key)
        else:
            envelopes.append((key, mapped.envelope))
            if not fetched.complete:
                report.projects_over_limit.append(key)
            link_ends.extend(fetched.link_ends)
            images = fetched.images
            report.images += images.images
            report.image_bytes += images.image_bytes
            report.images_oversize += images.oversize
            report.images_unreadable += images.unreadable
            report.other_attachments += images.other_files
            report.files += images.files
            report.file_bytes += images.file_bytes
            for stored in images.by_issue.values():
                all_images.extend(stored)
            for stored in images.files_by_issue.values():
                all_files.extend(stored)
            for issue_key, found in fetched.sprints.items():
                for sprint in found:
                    all_sprints.setdefault(sprint.id, sprint)
                sprint_membership[issue_key] = [sprint.id for sprint in found]
            report.sprints = len(all_sprints)
            report.projects += 1
            report.tasks += len(mapped.envelope["tasks"])
            report.dropped_nodes += mapped.dropped_nodes
            report.skipped_issues += mapped.skipped_rows
            # Summed across projects: the same field on two boards is one
            # property in the initiative they land in.
            for name, (ptype, count) in mapped.properties.items():
                _type, total = report.properties.get(name, (ptype, 0))
                report.properties[name] = (ptype, total + count)
            dropped_fields.update(mapped.dropped_fields)
            report.dropped_fields = sorted(dropped_fields, key=str.lower)
            # A comment is a row like a task is, so it spends the same budget:
            # ten tasks carrying four thousand comments is a large import.
            project_comments = sum(
                len(task["comments"]) for task in mapped.envelope["tasks"]
            )
            report.comments += project_comments
            report.comments_restricted += fetched.restricted_comments
            # An uploaded file is a row too.
            remaining -= fetched.issues_used + project_comments + images.files
        if progress is not None:
            await progress(report)

    if not envelopes:
        raise ImportEngineError(ImportEngineMessages.IMPORT_SOURCE_UNREACHABLE)

    _count_links(report, envelopes, link_ends)
    calendars: list[dict[str, Any]] = []
    if all_sprints and sprints_blocked_by is not None:
        report.sprints_skipped = sprints_blocked_by
    elif all_sprints:
        board_names = await fetch_board_names(
            credential,
            {s.board_id for s in all_sprints.values() if s.board_id is not None},
        )
        calendars, placed = jira_sprints.build_sprint_calendars(
            all_sprints, board_names
        )
        report.sprint_calendars = len(calendars)
        report.sprints_undated = len(all_sprints) - len(placed)
        _link_tasks_to_sprints(envelopes, sprint_membership, placed)

    if link_pages:
        await _link_tasks_to_pages(credential, envelopes)

    return JiraFetched(
        envelopes=envelopes,
        calendars=calendars,
        images=all_images,
        files=all_files,
        people=_people(envelopes),
        report=report,
        rows_used=import_limits.IMPORT_FETCH_MAX_ROWS - remaining + len(calendars),
    )


async def _link_tasks_to_pages(
    credential: AtlassianCredential, envelopes: list[tuple[str, dict[str, Any]]]
) -> None:
    """Relate each task to the Confluence pages its issue lists — the
    "Confluence pages" an issue shows, which Jira keeps as remote links.

    A page that comes over in the same import becomes the far end of a
    ``related_to`` edge; one that does not is counted as outside the
    selection, like any other link. An issue whose links will not answer
    keeps none — not worth failing the import over; being throttled is.
    """
    from app.core.relationships import RelationshipType
    from app.services.import_engine.links import confluence_page_ref

    for _key, envelope in envelopes:
        for task in envelope["tasks"]:
            issue_key = str(task.get("external_ref") or "").removeprefix("jira:")
            if not issue_key:
                continue
            try:
                payload = await get_json(
                    credential, f"/rest/api/3/issue/{issue_key}/remotelink"
                )
            except ImportEngineError as exc:
                if exc.code == ImportEngineMessages.IMPORT_SOURCE_RATE_LIMITED:
                    raise
                continue
            seen: set[str] = set()
            for link in payload if isinstance(payload, list) else []:
                target = link.get("object") if isinstance(link, dict) else None
                url = target.get("url") if isinstance(target, dict) else None
                ref = (
                    confluence_page_ref(url, credential.site_url)
                    if isinstance(url, str)
                    else None
                )
                if ref and ref not in seen:
                    seen.add(ref)
                    task["links"].append(
                        {
                            "type": RelationshipType.related_to.value,
                            "target_external_ref": ref,
                        }
                    )


async def fetch_board_names(
    credential: AtlassianCredential, board_ids: set[int]
) -> dict[int, str]:
    """What each board is called, for the calendar its sprints land on.

    A board the token cannot read keeps no name, and its calendar gets the
    fallback one: not worth failing an import over. Being throttled is.
    """
    names: dict[int, str] = {}
    for board_id in sorted(board_ids):
        try:
            board = await get_json(credential, f"/rest/agile/1.0/board/{board_id}")
        except ImportEngineError as exc:
            if exc.code == ImportEngineMessages.IMPORT_SOURCE_RATE_LIMITED:
                raise
            continue
        name = board.get("name") if isinstance(board, dict) else None
        if isinstance(name, str) and name.strip():
            names[board_id] = name.strip()
    return names


def _link_tasks_to_sprints(
    envelopes: list[tuple[str, dict[str, Any]]],
    membership: dict[str, list[int]],
    placed: set[int],
) -> None:
    """Relate each task to the sprints it was in — only the ones that became
    events, so no link points at a sprint that will not exist."""
    for _key, envelope in envelopes:
        for task in envelope["tasks"]:
            issue_key = str(task.get("external_ref") or "").removeprefix("jira:")
            for sprint_id in membership.get(issue_key, []):
                if sprint_id in placed:
                    task["links"].append(
                        {
                            "type": "related_to",
                            "target_external_ref": jira_sprints.sprint_ref(sprint_id),
                        }
                    )
