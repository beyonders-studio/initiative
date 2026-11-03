"""API payloads for imports beyond the job itself (``DataJobRead``): the
requests that start one, and the plan and report an import job records — never
envelope content (large payloads are staged behind storage and deleted on
terminal states)."""

from typing import Any, Optional

from app.schemas.base import RawTextStr, SanitizedBaseModel
from app.services.import_engine.contract import EnvelopeImportResult


class EnvelopeImportRequest(SanitizedBaseModel):
    """Body of ``POST /imports/envelope``. The envelope is a raw dict —
    its ``type`` field selects the importer, which validates the full shape
    (typing it as a union here would split the OpenAPI schema per type)."""

    initiative_id: int
    envelope: dict[str, Any]


class EnvelopeImportResponse(SanitizedBaseModel):
    """201 body for an inline (small) envelope import."""

    result: EnvelopeImportResult


class ForeignSourceOption(SanitizedBaseModel):
    """One importable thing inside an uploaded export."""

    key: str
    name: str
    task_count: int


class ForeignPreview(SanitizedBaseModel):
    """What an uploaded export holds, read without storing any of it.

    ``picks_one`` tells the wizard what its next step is for: choosing
    between the options, or naming the single project the file describes.
    """

    source: str
    picks_one: bool
    options: list[ForeignSourceOption]


class ForeignImportRequest(SanitizedBaseModel):
    """Body of ``POST /imports/foreign/{source}``.

    ``content`` is the export's own text — a CSV or a JSON document — sent
    back with the choice made about it, so nothing is held server-side
    between the preview and the import.
    """

    initiative_id: int
    selection: str = ""
    #: The file itself, verbatim. Raw rather than plain text: a plain string
    #: field is capped at a few kilobytes and has its markup stripped, and an
    #: export is neither short nor something to rewrite before it is parsed.
    #: Its size is bounded at the transport instead (``body_limit``), and the
    #: parser is what decides whether it reads.
    content: RawTextStr


class EntryResult(SanitizedBaseModel):
    """One manifest entry's apply outcome inside a backup import."""

    path: str
    tool: str
    type: str
    title: str
    status: str  # "created" | "failed" | "skipped"
    error: Optional[str] = None  # short code, never content
    detail: Optional[EnvelopeImportResult] = None


class BackupPlanInitiative(SanitizedBaseModel):
    """One initiative in the pre-flight plan: what would be created."""

    source_id: int
    name: str
    proposed_name: str
    tools: dict[str, str]  # tool -> "included" | "excluded" | "disabled"
    entry_counts: dict[str, int]  # tool -> entries in the zip
    # Set when the bundle files into an initiative that already exists rather
    # than creating one — every foreign-source import. ``proposed_name`` means
    # nothing then; this is where the content goes.
    target_initiative_id: Optional[int] = None


class BackupPlanPerson(SanitizedBaseModel):
    """One name the archive quotes, and our best guess at who that is here.

    ``suggested_user_id`` is filled only by an **exact** handle match against
    the guild's own roster. Anything looser is left empty on purpose: a
    display name that looks similar is how one person's words end up under
    another person's face, and the wizard is asking precisely so that nobody
    has to guess.
    """

    handle: str
    name: Optional[str] = None
    comment_count: int = 0
    suggested_user_id: Optional[int] = None


class AtlassianPlanProperty(SanitizedBaseModel):
    """One property the import would create, for the review step's list."""

    name: str
    type: str
    #: How many imported tasks carry a value for it.
    issue_count: int = 0


class AtlassianDroppedItem(SanitizedBaseModel):
    """One kind of thing a page held that will not come over, and how many."""

    #: A Confluence macro's name (``toc``, ``drawio``), or ``image`` for a
    #: picture that could not be placed.
    name: str
    count: int = 0


class AtlassianFetchSummary(SanitizedBaseModel):
    """What reading an Atlassian site found, for the review step.

    Counts only, never a title or a body. Written while the fetch runs, so the
    wizard can show it climbing, and final once the job is staged.
    """

    projects: int = 0
    tasks: int = 0
    #: Rich-text nodes the converter could not carry, summed over every body.
    #: Said before anybody commits, rather than discovered afterwards.
    dropped_nodes: int = 0
    #: Issues the site returned that were not usable as tasks.
    skipped_issues: int = 0
    #: Project keys that were ticked and could not be read with this token.
    unreadable_projects: list[str] = []
    #: Project keys the import's size limit cut short or left out.
    projects_over_limit: list[str] = []
    #: Issue links and parents that will become connections between tasks.
    links: int = 0
    #: Those whose other end was not brought over, so will not.
    links_outside_selection: int = 0
    #: Every property the import would create — only fields some issue
    #: filled in (§6.5) — with how many tasks carry each.
    properties: list[AtlassianPlanProperty] = []
    #: Fields something filled that have no home here, so will not come over.
    dropped_fields: list[str] = []
    #: Sprints the issues were in, and the calendars — one per board — they
    #: land on as events.
    sprints: int = 0
    sprint_calendars: int = 0
    #: Sprints planned but never started: no dates, so no event.
    sprints_undated: int = 0
    #: Why no sprint will come over, as an error code, when none will — the
    #: target initiative's calendars are off, or the importer cannot create
    #: one there.
    sprints_skipped: Optional[str] = None
    #: Comments that will come over, and those visible only to a role or
    #: group at the source, left behind rather than shown to everybody.
    comments: int = 0
    comments_restricted: int = 0
    #: Images coming over as uploads, and the storage they will use — what a
    #: community with a quota wants to know before it confirms.
    images: int = 0
    image_bytes: int = 0
    #: Images over the per-image cap or past the bundle's budget, and those
    #: the site would not hand over.
    images_oversize: int = 0
    images_unreadable: int = 0
    #: Attached files that are not images, each coming over as a file
    #: attached to its task, and the storage they will use.
    files: int = 0
    file_bytes: int = 0
    #: Attached files that are not images, left behind: attachments were
    #: switched off, or the initiative has files switched off.
    other_attachments: int = 0
    #: Confluence: spaces read, and the pages they became.
    spaces: int = 0
    pages: int = 0
    #: Folders, and pages with children and nothing of their own, given a
    #: list of the pages beneath them for a body.
    page_containers: int = 0
    #: Space keys that were ticked and could not be read with this token.
    unreadable_spaces: list[str] = []
    #: Space keys the import's size limit cut short or left out.
    spaces_over_limit: list[str] = []
    #: Pages left out because the wiki would have been too large to import
    #: in one piece.
    pages_over_limit: int = 0
    #: Files the pages show or link to, left at the source because
    #: attachments were not asked for.
    page_attachments: int = 0
    #: Pictures the pages show, coming over as uploads, and files — with any
    #: picture no page shows — coming over as files filed in the wiki.
    page_images: int = 0
    page_files: int = 0
    #: The storage both will use.
    page_attachment_bytes: int = 0
    #: Attachments too large, past the import's budget, of a type never
    #: brought, or that the site would not hand over.
    page_attachments_skipped: int = 0
    #: Files left behind because the initiative cannot take files.
    page_files_blocked: int = 0
    #: Comments on the pages — footer and inline — that will come over.
    page_comments: int = 0
    #: Inline comments marked resolved at the source, left behind.
    page_comments_resolved: int = 0
    #: Tags the pages' labels will become.
    labels: int = 0
    #: What the pages held that will not come over, by kind, most first.
    dropped_macros: list[AtlassianDroppedItem] = []
    #: Links between an issue and a page that were both read — the page's
    #: Jira macros and issue links, and an issue's links to pages — which the
    #: import joins up.
    cross_links: int = 0


class BackupImportPlan(SanitizedBaseModel):
    """The confirm-screen summary, persisted to ``data_jobs.plan`` —
    counts and names only, never envelope content."""

    source_community_name: str = ""
    app_version: str = ""
    exported_at: Optional[str] = None
    schema_version: int = 0
    initiatives: list[BackupPlanInitiative] = []
    asset_count: int = 0
    asset_bytes: int = 0
    skipped: list[dict[str, Any]] = []
    unknown_types: list[str] = []
    # Everyone the archive quotes, most-quoted first — the rows the wizard's
    # people step asks about. Empty for a backup taken before people were
    # inventoried, and for one that quotes nobody.
    people: list[BackupPlanPerson] = []
    # Only on a bundle this server fetched from an Atlassian site.
    atlassian: Optional[AtlassianFetchSummary] = None


class EnvelopeImportPlan(SanitizedBaseModel):
    """The confirm-screen summary for a lone envelope, persisted to
    ``data_jobs.plan``.

    Only people. A backup's plan has initiatives to name and tools to narrow;
    one envelope is one thing going into one initiative the caller already
    picked, so the only question left is who the handles in it are — and it
    is only written when at least one of them has no obvious answer.
    """

    #: Everybody the envelope quotes, most-quoted first. The only thing in
    #: here: the browser already parsed the file it is about, so a title in
    #: the plan would be a second, guessable copy of something the step
    #: already has.
    people: list[BackupPlanPerson] = []


class BackupImportResult(SanitizedBaseModel):
    """Terminal report for a backup import, persisted to
    ``data_jobs.result``."""

    initiatives: list[dict[str, Any]] = []  # {source_id, initiative_id, name}
    per_tool: dict[str, dict[str, int]] = {}  # tool -> {created, failed, skipped}
    entries: list[EntryResult] = []
    assets_restored: int = 0
    assets_deduped: int = 0
    asset_bytes: int = 0
    # Edges the deferred pass wrote, and the ones whose far end was never
    # imported — a link out of the selection is ordinary, and counted rather
    # than treated as a failure.
    links_created: int = 0
    links_unresolved: int = 0
    unmatched_handles: list[str] = []
    warnings: list[str] = []
