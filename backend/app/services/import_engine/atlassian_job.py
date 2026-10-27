"""An import from an Atlassian site as a job: starting one, and fetching it.

The job's life is the backup's with one step in front of it::

    queued → fetching → staged → (confirm) → queued → running → done | failed

Everything from ``staged`` on is the backup path, unchanged — the fetch writes
the same zip a backup upload stages, and the worker applies it the same way.
What this module adds is the part before that: the request that names what
to bring over, and the worker's fetch that turns it into a bundle.

A queued Atlassian job with no payload has not been fetched yet; one with a
payload has been, and was confirmed. That is the whole of how the worker tells
the two apart (:func:`awaits_fetch`), and it is why a re-claimed fetch drops
its payload on the way back into the queue. The one exception is an uploaded
Confluence HTML export: its job says so (``confluence_export``) and has no
plan until the fetch converts it rather than calling a site.

**The credential is spent by the fetch.** Everything the apply needs is in the
bundle, so the moment the bundle is staged the token has no further use and is
dropped — the review step can sit for hours without a live secret behind it.
"""

from __future__ import annotations

import asyncio
import logging
import zipfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, AsyncContextManager, Awaitable, Callable
from urllib.parse import urlsplit

from cryptography.fernet import InvalidToken
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import ImportEngineMessages
from app.core.tools import Tool, tool_envelope_type
from app.core.version import get_version
from app.models.platform.user import User, UserStatus
from app.models.tenant.import_job import ImportJob, ImportJobStatus
from app.models.tenant.initiative import Initiative
from app.core.encryption import (
    SALT_IMPORT_CREDENTIAL,
    decrypt_field,
    encrypt_field,
)
from app.schemas.tenant.import_job import (
    AtlassianDroppedItem,
    AtlassianFetchSummary,
    AtlassianPlanProperty,
    BackupImportPlan,
)
from app.services.import_engine import engine as import_engine
from app.services.import_engine import (
    confluence_fetch,
    jira_attachments,
    jira_fetch,
)
from app.services.import_engine.atlassian import AtlassianCredential
from app.services.import_engine.atlassian_bundle import BundleWriter, merge_people
from app.services.import_engine.common import load_guild_member_handles
from app.services.import_engine.contract import ImportEngineError
from app.services.import_engine import limits as import_limits
from app.services.import_engine.zip_bounds import open_zip
from app.services.tenant import attachments as attachments_service

logger = logging.getLogger(__name__)

#: ``import_jobs.source`` for every import read from an Atlassian site.
SOURCE = "atlassian"

#: The provider a credential has to have been stored under to start one.
PROVIDER = "atlassian"

#: The importer whose permission a Jira project needs.
_PROJECT_ENVELOPE = tool_envelope_type(Tool.project)

#: The importer whose permission a Confluence space needs.
_WIKI_ENVELOPE = tool_envelope_type(Tool.wiki)

#: The importer a board's sprints go through, as calendar events.
_CALENDAR_ENVELOPE = tool_envelope_type(Tool.calendar)

#: The importer a page's attached files go through, as uploaded files.
_FILE_ENVELOPE = tool_envelope_type(Tool.file)


#: What an uploaded Confluence HTML export is staged as.
EXPORT_SUFFIX = "confluence-export.zip"


def awaits_fetch(job: ImportJob) -> bool:
    """Whether the worker should read the source for this job rather than
    apply it: a site not yet read, or an export not yet converted."""
    return job.source == SOURCE and (
        not job.payload_ref
        or (bool((job.params or {}).get("confluence_export")) and job.plan is None)
    )


def summary_of(report: jira_fetch.FetchReport) -> AtlassianFetchSummary:
    return AtlassianFetchSummary(
        projects=report.projects,
        tasks=report.tasks,
        dropped_nodes=report.dropped_nodes,
        skipped_issues=report.skipped_issues,
        unreadable_projects=list(report.unreadable_projects),
        projects_over_limit=list(report.projects_over_limit),
        links=report.links,
        links_outside_selection=report.links_outside_selection,
        properties=[
            AtlassianPlanProperty(name=name, type=ptype, issue_count=count)
            for name, (ptype, count) in report.properties.items()
        ],
        dropped_fields=list(report.dropped_fields),
        sprints=report.sprints,
        sprint_calendars=report.sprint_calendars,
        sprints_undated=report.sprints_undated,
        sprints_skipped=report.sprints_skipped,
        comments=report.comments,
        comments_restricted=report.comments_restricted,
        images=report.images,
        image_bytes=report.image_bytes,
        images_oversize=report.images_oversize,
        images_unreadable=report.images_unreadable,
        other_attachments=report.other_attachments,
        files=report.files,
        file_bytes=report.file_bytes,
    )


def confluence_summary_of(
    report: confluence_fetch.ConfluenceFetchReport,
) -> AtlassianFetchSummary:
    return AtlassianFetchSummary(
        spaces=report.spaces,
        pages=report.pages,
        page_containers=report.containers,
        dropped_nodes=report.dropped_nodes,
        unreadable_spaces=list(report.unreadable_spaces),
        spaces_over_limit=list(report.spaces_over_limit),
        pages_over_limit=report.pages_over_limit,
        page_attachments=report.attachments,
        page_images=report.images,
        page_files=report.files,
        page_attachment_bytes=report.attachment_bytes,
        page_attachments_skipped=report.attachments_skipped,
        page_files_blocked=report.files_blocked,
        page_comments=report.comments,
        page_comments_resolved=report.comments_resolved,
        labels=report.labels,
        dropped_macros=[
            AtlassianDroppedItem(name=name, count=count)
            for name, count in report.dropped.most_common()
        ],
    )


def _unique(keys: list[str]) -> list[str]:
    """Order kept, repeats dropped: the order is the order they were ticked."""
    return list(dict.fromkeys(key.strip() for key in keys if key.strip()))


async def start_import(
    session: AsyncSession,
    *,
    user: User,
    guild_id: int,
    credential: AtlassianCredential,
    initiative_id: int,
    project_keys: list[str],
    space_keys: list[str],
    include_comments: bool = True,
    include_attachments: bool = True,
) -> ImportJob:
    """Queue a job that reads these Jira projects and Confluence spaces into
    ``initiative_id`` — projects as projects, each space as a wiki.

    One job for both products, so a link between an issue and a page read in
    the same fetch has both of its ends in the same apply to be joined.

    The token the connect step proved comes back with this request and is
    stored on the job, encrypted, for the worker that reads the site minutes
    later. It is cleared the moment the job reaches a terminal state.

    Everything that can be refused now is refused now, so a person finds out
    in the wizard rather than from a failed job minutes later: nothing
    ticked, an initiative they cannot create projects — or wikis — in. The
    worker asks the second of those again before it reads anything, and the
    apply asks it a third time: authorization is a property of the moment.
    """
    projects = _unique(project_keys)
    spaces = _unique(space_keys)
    if not projects and not spaces:
        raise ImportEngineError(ImportEngineMessages.IMPORT_SOURCE_NOTHING_SELECTED)

    initiative = None
    for chosen, envelope_type in (
        (projects, _PROJECT_ENVELOPE),
        (spaces, _WIKI_ENVELOPE),
    ):
        if chosen:
            initiative = await import_engine.load_target_initiative(
                session,
                guild_id=guild_id,
                initiative_id=initiative_id,
                importer=import_engine.get_importer(envelope_type),
                user=user,
            )
    assert initiative is not None
    await import_engine.count_active_jobs_locked(session, user=user)

    job = ImportJob(
        created_by=user.id,
        source=SOURCE,
        params={
            "initiative_id": initiative.id,
            # Which site and as whom, so the wizard and the Data tab can say
            # where this came from. The person typed both; neither is secret.
            "site_url": credential.site_url,
            "principal": credential.email,
            "jira_projects": projects,
            "confluence_spaces": spaces,
            "include_comments": include_comments,
            "include_attachments": include_attachments,
        },
        secret_encrypted=encrypt_field(credential.api_token, SALT_IMPORT_CREDENTIAL),
        status=ImportJobStatus.queued,
        expires_at=datetime.now(timezone.utc)
        + timedelta(hours=import_limits.IMPORT_STAGED_TTL_HOURS),
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def export_initiative(
    session: AsyncSession, *, user: User, guild_id: int, initiative_id: int
) -> Initiative:
    """The initiative an export is read into, refused unless ``user`` may make
    a wiki there."""
    return await import_engine.load_target_initiative(
        session,
        guild_id=guild_id,
        initiative_id=initiative_id,
        importer=import_engine.get_importer(_WIKI_ENVELOPE),
        user=user,
    )


async def start_export(
    session: AsyncSession,
    *,
    user: User,
    guild_id: int,
    initiative_id: int,
    payload: bytes | Path,
    include_attachments: bool = True,
    payload_ref: str | None = None,
) -> ImportJob:
    """Queue a job that reads a Confluence space's HTML export into
    ``initiative_id`` as a wiki.

    The zip is checked for being one — a zip, within the bounds a restore
    accepts, with pages in it — and staged for the worker, which converts it
    the way it reads a site; everything after that is the same review.
    ``payload`` is the zip itself or the file holding it; ``payload_ref``,
    where it is already in the community's storage (a resumable upload).
    """
    await asyncio.to_thread(_check_export, payload)

    initiative = await export_initiative(
        session, user=user, guild_id=guild_id, initiative_id=initiative_id
    )
    await import_engine.count_active_jobs_locked(session, user=user)
    if payload_ref is None:
        stage = (
            import_engine.stage_payload_file
            if isinstance(payload, Path)
            else import_engine.stage_payload
        )
        payload_ref = await asyncio.to_thread(
            stage, guild_id, payload, suffix=EXPORT_SUFFIX
        )
    job = ImportJob(
        created_by=user.id,
        source=SOURCE,
        params={
            "initiative_id": initiative.id,
            "confluence_export": True,
            "include_attachments": include_attachments,
        },
        payload_ref=payload_ref,
        status=ImportJobStatus.queued,
        expires_at=datetime.now(timezone.utc)
        + timedelta(hours=import_limits.IMPORT_STAGED_TTL_HOURS),
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


def _check_export(payload: bytes | Path) -> None:
    """Refuse a payload that is not a zip within the upload bounds, or holds
    no page. Blocking; run it in a thread."""
    with open_zip(payload) as archive:
        if not any(
            info.filename.endswith(".html") and not info.filename.endswith("index.html")
            for info in archive.infolist()
        ):
            raise ImportEngineError(ImportEngineMessages.IMPORT_ZIP_INVALID)


async def _fetch_export(
    job: ImportJob,
    *,
    guild_id: int,
    open_user_session: Callable[[], AsyncContextManager[AsyncSession]],
    progress: Callable[[AtlassianFetchSummary], Awaitable[None]] | None,
) -> StagedFetch:
    """Convert an uploaded HTML export into the bundle a site fetch writes."""
    raw_ref = job.payload_ref
    if not raw_ref:
        raise ImportEngineError(ImportEngineMessages.IMPORT_INVALID_PARAMS)
    async with import_engine.open_payload(guild_id, raw_ref) as upload:
        try:
            archive = (
                await asyncio.to_thread(open_zip, upload)
                if upload is not None
                else None
            )
        finally:
            # The upload is read once. A conversion interrupted after this
            # starts over from nothing, and says so, rather than finding half
            # of one. The open archive keeps reading the file it opened.
            await asyncio.to_thread(import_engine.delete_payload, guild_id, raw_ref)
            job.payload_ref = None
        if archive is None:
            raise ImportEngineError(ImportEngineMessages.IMPORT_INVALID_PARAMS)
        with archive:
            return await _convert_export(
                job,
                archive,
                guild_id=guild_id,
                open_user_session=open_user_session,
                progress=progress,
            )


async def _convert_export(
    job: ImportJob,
    archive: zipfile.ZipFile,
    *,
    guild_id: int,
    open_user_session: Callable[[], AsyncContextManager[AsyncSession]],
    progress: Callable[[AtlassianFetchSummary], Awaitable[None]] | None,
) -> StagedFetch:
    from app.api.deps import establish_guild_access
    from app.services.import_engine import confluence_export
    from app.services.platform import accounts as accounts_service

    params = job.params or {}
    user = await accounts_service.load_one(job.created_by)
    if user is None or user.status != UserStatus.active:
        raise ImportEngineError(ImportEngineMessages.IMPORT_CREATOR_INACTIVE)

    include_attachments = params.get("include_attachments") is not False
    async with open_user_session() as user_session:
        context = await establish_guild_access(
            user_session, user, guild_id, on_behalf=True
        )
        if context.content_read_only or context.is_pam or context.grant is not None:
            raise ImportEngineError(ImportEngineMessages.IMPORT_WRITE_REQUIRED)
        initiative = await import_engine.load_target_initiative(
            user_session,
            guild_id=guild_id,
            initiative_id=params.get("initiative_id"),
            importer=import_engine.get_importer(_WIKI_ENVELOPE),
            user=user,
        )
        files_allowed = True
        if include_attachments:
            try:
                await import_engine.load_target_initiative(
                    user_session,
                    guild_id=guild_id,
                    initiative_id=initiative.id,
                    importer=import_engine.get_importer(_FILE_ENVELOPE),
                    user=user,
                )
            except ImportEngineError:
                files_allowed = False
        roster = await load_guild_member_handles(user_session, guild_id=guild_id)
        # Attachments past the community's storage quota could never be
        # restored, so they are not downloaded either.
        storage_left = (
            await attachments_service.storage_left(guild_id)
            if include_attachments
            else None
        )

    with BundleWriter() as writer:
        fetched, site_url = await confluence_export.export_to_fetched(
            archive,
            guild_id=guild_id,
            app_version=get_version(),
            asset_budget=jira_attachments.bundle_budget(storage_left)
            if include_attachments
            else None,
            store=writer.put_asset,
            files_allowed=files_allowed,
        )
        summary = combined_summary(None, fetched.report)
        if progress is not None:
            await progress(summary)

        path = await asyncio.to_thread(
            writer.finish,
            images=fetched.images,
            wikis=fetched.envelopes,
            wiki_files=fetched.files,
            people=merge_people([], fetched.people),
            guild_id=guild_id,
            guild_name="Confluence export",
            target_initiative_id=initiative.id,
            app_version=get_version(),
            site_url=site_url,
        )
        return await _stage(path, guild_id=guild_id, roster=roster, summary=summary)


def combined_summary(
    jira: jira_fetch.FetchReport | None,
    confluence: confluence_fetch.ConfluenceFetchReport | None,
    *,
    cross_links: int = 0,
) -> AtlassianFetchSummary:
    """One summary for the review, whichever products were read."""
    summary = summary_of(jira) if jira is not None else AtlassianFetchSummary()
    if confluence is not None:
        pages = confluence_summary_of(confluence)
        for name in (
            "spaces",
            "pages",
            "page_containers",
            "unreadable_spaces",
            "spaces_over_limit",
            "pages_over_limit",
            "page_attachments",
            "page_images",
            "page_files",
            "page_attachment_bytes",
            "page_attachments_skipped",
            "page_files_blocked",
            "page_comments",
            "page_comments_resolved",
            "labels",
            "dropped_macros",
        ):
            setattr(summary, name, getattr(pages, name))
        summary.dropped_nodes += pages.dropped_nodes
    summary.cross_links = cross_links
    return summary


def count_cross_links(
    projects: list[tuple[str, dict[str, Any]]],
    wikis: list[tuple[str, dict[str, Any]]],
    *,
    site_url: str,
) -> int:
    """How many links between an issue and a page the apply will join: a
    page naming an issue that came over, and an issue naming a page that
    did."""
    from app.services.import_engine.importers.wiki import _jira_keys
    from app.services.import_engine.links import (
        _MARKDOWN_LINK,
        confluence_page_ref,
    )

    issues = {
        str(task.get("external_ref") or "").removeprefix("jira:")
        for _key, envelope in projects
        for task in envelope["tasks"]
    }
    pages = {
        page.get("external_ref")
        for _key, envelope in wikis
        for page in envelope["pages"]
    }
    count = sum(
        1
        for _key, envelope in wikis
        for page in envelope["pages"]
        for key in _jira_keys(page.get("content"))
        if key in issues
    )
    for _key, envelope in projects:
        for task in envelope["tasks"]:
            count += sum(
                1 for link in task["links"] if link["target_external_ref"] in pages
            )
            texts = [task.get("description") or ""] + [
                comment.get("body") or "" for comment in task.get("comments") or []
            ]
            count += sum(
                1
                for text in texts
                for match in _MARKDOWN_LINK.finditer(text)
                if confluence_page_ref(match.group(2), site_url) in pages
            )
    return count


@dataclass(frozen=True)
class StagedFetch:
    """A finished fetch: where the bundle is, and the plan to review it by."""

    payload_ref: str
    plan: dict[str, Any]


class FetchCancelled(Exception):
    """The job stopped being a fetch while the fetch was running."""


async def fetch(
    job: ImportJob,
    *,
    guild_id: int,
    open_user_session: Callable[[], AsyncContextManager[AsyncSession]],
    progress: Callable[[AtlassianFetchSummary], Awaitable[None]] | None = None,
) -> StagedFetch:
    """:func:`_read`, within :data:`~limits.IMPORT_FETCH_DEADLINE_SECONDS`.

    A fetch still going when the time runs out fails with
    ``IMPORT_SOURCE_TOO_SLOW``, and nothing it read so far is kept.
    """
    try:
        async with asyncio.timeout(import_limits.IMPORT_FETCH_DEADLINE_SECONDS):
            return await _read(
                job,
                guild_id=guild_id,
                open_user_session=open_user_session,
                progress=progress,
            )
    except TimeoutError:
        raise ImportEngineError(ImportEngineMessages.IMPORT_SOURCE_TOO_SLOW) from None


async def _read(
    job: ImportJob,
    *,
    guild_id: int,
    open_user_session: Callable[[], AsyncContextManager[AsyncSession]],
    progress: Callable[[AtlassianFetchSummary], Awaitable[None]] | None = None,
) -> StagedFetch:
    """Read the job's projects or spaces from the site and stage the bundle.

    Raises an :class:`ImportEngineError` for anything the person has to act
    on, and lets ``progress`` raise :class:`FetchCancelled` to stop early.
    Nothing is written to any content table: the one artifact is the zip, and
    it is staged only after the whole read succeeded, so a failure leaves
    nothing behind to clean up.
    """
    from app.api.deps import establish_guild_access
    from app.services.platform import accounts as accounts_service

    params = job.params or {}
    if params.get("confluence_export"):
        return await _fetch_export(
            job,
            guild_id=guild_id,
            open_user_session=open_user_session,
            progress=progress,
        )
    # A job started before the option existed brought attachments across.
    include_attachments = params.get("include_attachments") is not False
    raw_projects = params.get("jira_projects", [])
    raw_spaces = params.get("confluence_spaces", [])
    site_url = params.get("site_url")
    principal = params.get("principal")
    if (
        not isinstance(raw_projects, list)
        or not isinstance(raw_spaces, list)
        or not isinstance(site_url, str)
        or not isinstance(principal, str)
        or not job.secret_encrypted
    ):
        raise ImportEngineError(ImportEngineMessages.IMPORT_INVALID_PARAMS)
    projects = [key for key in raw_projects if isinstance(key, str) and key]
    spaces = [key for key in raw_spaces if isinstance(key, str) and key]
    if not projects and not spaces:
        raise ImportEngineError(ImportEngineMessages.IMPORT_INVALID_PARAMS)

    user = await accounts_service.load_one(job.created_by)
    if user is None or user.status != UserStatus.active:
        raise ImportEngineError(ImportEngineMessages.IMPORT_CREATOR_INACTIVE)

    try:
        api_token = decrypt_field(job.secret_encrypted, SALT_IMPORT_CREDENTIAL)
    except InvalidToken as exc:
        raise ImportEngineError(
            ImportEngineMessages.IMPORT_CREDENTIAL_UNAVAILABLE
        ) from exc

    # Before a single call to the site: is the person still somebody who may
    # put projects in that initiative? The session is closed again before
    # the read, which can take far longer than a routed session may live.
    async with open_user_session() as user_session:
        context = await establish_guild_access(
            user_session, user, guild_id, on_behalf=True
        )
        if context.content_read_only or context.is_pam or context.grant is not None:
            raise ImportEngineError(ImportEngineMessages.IMPORT_WRITE_REQUIRED)
        target_initiative_id = 0
        for chosen, envelope_type in (
            (projects, _PROJECT_ENVELOPE),
            (spaces, _WIKI_ENVELOPE),
        ):
            if chosen:
                initiative = await import_engine.load_target_initiative(
                    user_session,
                    guild_id=guild_id,
                    initiative_id=params.get("initiative_id"),
                    importer=import_engine.get_importer(envelope_type),
                    user=user,
                )
                target_initiative_id = initiative.id
        # Sprints land as calendar events, so they need somewhere to land.
        # Asked now, with the same gate the apply will use, so the plan can
        # say sprints are being left behind rather than the apply refusing
        # the whole bundle over a tool the projects never needed.
        sprints_blocked_by: str | None = None
        if projects:
            try:
                await import_engine.load_target_initiative(
                    user_session,
                    guild_id=guild_id,
                    initiative_id=target_initiative_id,
                    importer=import_engine.get_importer(_CALENDAR_ENVELOPE),
                    user=user,
                )
            except ImportEngineError as exc:
                sprints_blocked_by = exc.code
        # Attachments become files — a page's and an issue's — which
        # the apply refuses the whole bundle over if the initiative cannot
        # take them. Asked now, so only the pictures come instead.
        files_allowed = True
        if include_attachments:
            try:
                await import_engine.load_target_initiative(
                    user_session,
                    guild_id=guild_id,
                    initiative_id=target_initiative_id,
                    importer=import_engine.get_importer(_FILE_ENVELOPE),
                    user=user,
                )
            except ImportEngineError:
                files_allowed = False
        # The community's roster, so the plan can suggest who each person the
        # site names is — read now, as the person, like a backup upload does.
        roster = await load_guild_member_handles(user_session, guild_id=guild_id)
        # Attachments past the community's storage quota could never be
        # restored, so they are not downloaded either.
        storage_left = (
            await attachments_service.storage_left(guild_id)
            if include_attachments
            else None
        )

    credential = AtlassianCredential(
        site_url=site_url, email=principal, api_token=api_token
    )
    # The bundle's "source guild" is where it came from, which is the site.
    source_name = urlsplit(site_url).hostname or site_url
    jira: jira_fetch.JiraFetched | None = None
    pages: confluence_fetch.ConfluenceFetched | None = None
    jira_report: jira_fetch.FetchReport | None = None

    async def report_issues(report: jira_fetch.FetchReport) -> None:
        if progress is not None:
            await progress(combined_summary(report, None))

    async def report_spaces(report: confluence_fetch.ConfluenceFetchReport) -> None:
        if progress is not None:
            await progress(combined_summary(jira_report, report))

    # One bundle, so one budget for everything attached, issues and pages.
    asset_budget = (
        jira_attachments.bundle_budget(storage_left) if include_attachments else None
    )
    with BundleWriter() as writer:
        if projects:
            try:
                jira = await jira_fetch.fetch_projects(
                    credential,
                    project_keys=projects,
                    guild_id=guild_id,
                    app_version=get_version(),
                    progress=report_issues,
                    sprints_blocked_by=sprints_blocked_by,
                    # A job started before the option existed brought
                    # comments across.
                    include_comments=params.get("include_comments") is not False,
                    include_attachments=include_attachments,
                    asset_budget=asset_budget,
                    store=writer.put_asset,
                    files_allowed=files_allowed,
                    # An issue's "Confluence pages" are worth asking for only
                    # when the pages are coming too.
                    link_pages=bool(spaces),
                )
                jira_report = jira.report
            except ImportEngineError as exc:
                # Nothing readable on the Jira side is the whole import's
                # failure only when there is no other side to bring.
                if (
                    exc.code != ImportEngineMessages.IMPORT_SOURCE_UNREACHABLE
                    or not spaces
                ):
                    raise
                jira_report = jira_fetch.FetchReport(unreadable_projects=list(projects))
        if spaces:
            try:
                pages = await confluence_fetch.fetch_spaces(
                    credential,
                    space_keys=spaces,
                    app_version=get_version(),
                    progress=report_spaces,
                    # What the issues left of the import's row budget.
                    max_rows=import_limits.IMPORT_FETCH_MAX_ROWS
                    - (jira.rows_used if jira else 0),
                    guild_id=guild_id,
                    asset_budget=asset_budget,
                    store=writer.put_asset,
                    files_allowed=files_allowed,
                    include_comments=params.get("include_comments") is not False,
                )
            except ImportEngineError as exc:
                if (
                    exc.code != ImportEngineMessages.IMPORT_SOURCE_UNREACHABLE
                    or jira is None
                ):
                    raise
        space_report = (
            pages.report
            if pages is not None
            else confluence_fetch.ConfluenceFetchReport(unreadable_spaces=list(spaces))
            if spaces
            else None
        )

        project_envelopes = jira.envelopes if jira else []
        wiki_envelopes = pages.envelopes if pages else []
        path = await asyncio.to_thread(
            writer.finish,
            projects=project_envelopes,
            calendars=jira.calendars if jira else [],
            images=[*(jira.images if jira else []), *(pages.images if pages else [])],
            wikis=wiki_envelopes,
            wiki_files=pages.files if pages else {},
            task_files=jira.files if jira else [],
            people=merge_people(
                jira.people if jira else [], pages.people if pages else Counter()
            ),
            guild_id=guild_id,
            guild_name=source_name,
            target_initiative_id=target_initiative_id,
            app_version=get_version(),
            site_url=site_url,
        )
        cross_links = await asyncio.to_thread(
            count_cross_links, project_envelopes, wiki_envelopes, site_url=site_url
        )
        summary = combined_summary(jira_report, space_report, cross_links=cross_links)
        return await _stage(path, guild_id=guild_id, roster=roster, summary=summary)


async def _stage(
    path: Path,
    *,
    guild_id: int,
    roster: dict[str, int],
    summary: AtlassianFetchSummary,
) -> StagedFetch:
    """Plan a finished bundle and put it where the apply will find it."""
    from app.services.import_engine import backup as backup_service

    plan: BackupImportPlan = await asyncio.to_thread(
        backup_service.plan_backup,
        path,
        existing_initiative_names=set(),
        member_ids_by_handle=roster,
        fetched=True,
    )
    plan.atlassian = summary
    payload_ref = await asyncio.to_thread(
        import_engine.stage_payload_file, guild_id, path, suffix="zip"
    )
    return StagedFetch(payload_ref=payload_ref, plan=plan.model_dump(mode="json"))
