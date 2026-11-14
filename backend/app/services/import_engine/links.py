"""The deferred pass that turns what an import *said* into edges.

An envelope names the far end of a link by an **external ref** — a string the
source chose (``"jira:ACME-123"``, ``"task:41"``) — and not by an id, because
at the moment the link is read the far end usually does not exist yet. It can
be later in the same envelope, in a different envelope, or created by a
different importer entirely: a task blocked by another task, a sub-task under
its epic, and a task in its sprint are three rows written by two importers,
and only one of those pairs is ever in the same file.

So nothing resolves as it goes. Every importer does two things and knows
nothing about any other: it **registers** what it created under the ref the
envelope gave it, and it **records** the links it read. Once the last entry
has flushed, the job resolves the whole collection at once — every ref that
found both ends becomes an edge, and every ref that did not is counted.

An envelope imported on its own runs the same code: it resolves the links
whose far end it also carried, and counts the rest. There is no second path.

What this is not: a permission decision. Edges are written on the caller's
routed session, so RLS gates every insert exactly as it gates a link made by
hand. A ref that names something the importer cannot reach resolves to
nothing, which is the same answer as a ref that names nothing at all.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.relationships import Provenance, RelationshipType
from app.core.search import SearchEntityType
from app.services.tenant import relationships as relationships_service
from app.services.tenant.relationships import Endpoint

logger = logging.getLogger(__name__)

#: How an imported edge is known. ``manual``, because the source asserted it:
#: a Jira "blocks" link and a sub-task's parent are statements somebody made,
#: not something read out of a sentence (``content``) or offered by a model
#: and accepted (``inferred``). It also means taking one back is remembered.
IMPORT_PROVENANCE = Provenance.manual


@dataclass(frozen=True)
class PendingLink:
    """One edge an envelope asserted, both ends named by ref."""

    source_ref: str
    relationship_type: RelationshipType
    target_ref: str


@dataclass
class LinkResolution:
    """What the pass managed to write.

    ``unresolved`` is the honest half of the report: a link whose far end was
    never imported is not an error — a Jira project links to issues outside
    the selection all the time — but it is something the person who ran the
    import is owed a number for.
    """

    created: int = 0
    unresolved: int = 0
    duplicate: int = 0


@dataclass
class LinkCollector:
    """One job's refs and the links waiting on them.

    Lives for the length of a job and is never persisted: a ref is a name the
    source used, meaningful only while the import that read it is running.
    """

    _refs: dict[str, Endpoint] = field(default_factory=dict)
    _pending: list[PendingLink] = field(default_factory=list)
    #: Tasks and comments whose text links to a page on the source site —
    #: rewritten once every page has been written (:func:`rewrite_page_links`).
    _bodies: list[tuple[SearchEntityType, int]] = field(default_factory=list)
    #: Rows whose body names things by the ref they had where it was exported
    #: — placed once every entry has been written
    #: (:func:`app.services.import_engine.references.resolve_references`).
    _referencing: list[tuple[SearchEntityType, int]] = field(default_factory=list)

    def lookup(self, ref: str) -> Endpoint | None:
        """The row a ref names, if it has been written yet this job."""
        return self._refs.get(ref)

    def note_body(self, kind: SearchEntityType, entity_id: int | None) -> None:
        """Say that this row's text links to a page, so the job comes back
        to it once the pages exist."""
        if entity_id is not None and (kind, entity_id) not in self._bodies:
            self._bodies.append((kind, entity_id))

    def take_bodies(self) -> list[tuple[SearchEntityType, int]]:
        bodies, self._bodies = self._bodies, []
        return bodies

    def note_references(self, kind: SearchEntityType, entity_id: int) -> None:
        """Say that this row's body names things by their exported refs, so
        the job comes back to it once everything it names could exist."""
        if (kind, entity_id) not in self._referencing:
            self._referencing.append((kind, entity_id))

    def take_references(self) -> list[tuple[SearchEntityType, int]]:
        noted, self._referencing = self._referencing, []
        return noted

    def register(
        self, ref: str | None, kind: SearchEntityType, entity_id: int | None
    ) -> None:
        """Say that ``ref`` is now this row.

        A ref the envelope did not give, and a row that somehow has no id, are
        both nothing to record rather than something to fail over — a task
        with no external ref is simply a task nothing can point at.

        A repeated ref keeps the **first** row it named. Two things claiming
        one name is the source's ambiguity, and picking the earlier one at
        least makes the outcome the same on every re-run.
        """
        if not ref or entity_id is None:
            return
        if ref in self._refs:
            logger.info("import link ref claimed twice ref=%s", ref)
            return
        self._refs[ref] = Endpoint(kind=kind, id=entity_id)

    def link(
        self,
        source_ref: str | None,
        relationship_type: RelationshipType,
        target_ref: str | None,
    ) -> None:
        """Record an edge to resolve later. Either end missing means there is
        no edge to make — a link with nothing on one side says nothing."""
        if not source_ref or not target_ref:
            return
        self._pending.append(
            PendingLink(
                source_ref=source_ref,
                relationship_type=relationship_type,
                target_ref=target_ref,
            )
        )

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    async def resolve(
        self, session: AsyncSession, *, created_by: int | None = None
    ) -> LinkResolution:
        """Write every edge whose both ends were imported; count the rest.

        Runs after the last entry has flushed, on the caller's session, and
        leaves the collection empty so a second call is a no-op rather than a
        second set of edges.
        """
        resolution = LinkResolution()
        pending, self._pending = self._pending, []
        for item in pending:
            source = self._refs.get(item.source_ref)
            target = self._refs.get(item.target_ref)
            if source is None or target is None:
                resolution.unresolved += 1
                continue
            if source.node == target.node:
                # A ref pointing at itself — a source that named one thing
                # twice. Nothing to write, and nothing worth failing over.
                resolution.unresolved += 1
                continue
            row = await relationships_service.create(
                session,
                source=source,
                relationship_type=item.relationship_type,
                target=target,
                provenance=IMPORT_PROVENANCE,
                created_by=created_by,
            )
            if row is None:
                resolution.duplicate += 1
            else:
                resolution.created += 1
        return resolution


#: A link to a Confluence page, in either of the forms the product writes:
#: ``/wiki/spaces/KEY/pages/123/Title`` and ``…/viewpage.action?pageId=123``.
_PAGE_URL = re.compile(
    r"/wiki/(?:spaces/[^/?#\s)>]+/pages/|pages/viewpage\.action\?pageId=)(\d+)"
)
#: A markdown link, its URL bare or in angle brackets.
_MARKDOWN_LINK = re.compile(r"\[([^\]\n]*)\]\(<?([^)>\s]+)>?\)")


def wiki_page_slug_ref(wiki_id: int, slug: str) -> str:
    """The name a page of an imported wiki answers to by the slug its
    envelope gave it — kept apart from the slug it was stored under, which can
    differ when two envelope slugs collide."""
    return f"wiki:{wiki_id}:page:{slug}"


def confluence_page_ref(url: str, site_url: str | None) -> str | None:
    """The ref a Confluence page URL names — ``confluence:123`` — when it is a
    page on this site."""
    if not site_url or not url.startswith(site_url.rstrip("/") + "/"):
        return None
    match = _PAGE_URL.search(url)
    return f"confluence:{match.group(1)}" if match else None


def links_to_pages(text: str | None) -> bool:
    """Whether some link in this text could be a Confluence page."""
    return bool(text) and _PAGE_URL.search(text or "") is not None


def rewrite_page_links(
    text: str, resolve: Callable[[str], tuple[int, str] | None]
) -> str:
    """``text`` with each markdown link to a page that came over turned into
    a mention of the wiki page it became. ``resolve`` answers a URL with the
    page's id and title, or ``None`` for a link that stays a link."""

    def replace(match: re.Match[str]) -> str:
        found = resolve(match.group(2))
        if found is None:
            return match.group(0)
        page_id, title = found
        label = (match.group(1) or "").strip()
        # A bare URL for a label says nothing a reader wants; the page's own
        # title does.
        if not label or label.startswith(("http://", "https://")):
            label = title
        label = label.replace("[", "").replace("]", "")
        return f"#wiki_page[{label}]({page_id})"

    return _MARKDOWN_LINK.sub(replace, text)


async def resolve_page_links(
    session: AsyncSession, collector: LinkCollector, *, site_url: str | None
) -> int:
    """Rewrite the page links in every task and comment the job noted, now
    that the pages exist. Returns how many links became mentions.

    Runs on the caller's routed session after the last entry has flushed,
    like :meth:`LinkCollector.resolve`: a row the importer cannot read or
    write is not rewritten, which is the same as a page that never came.
    """
    from app.models.tenant.comment import Comment
    from app.models.tenant.task import Task
    from app.models.tenant.wiki import WikiPage

    bodies = collector.take_bodies()
    if not bodies or not site_url:
        return 0
    titles: dict[int, str] = {}

    def page_for(url: str) -> tuple[int, str] | None:
        ref = confluence_page_ref(url, site_url)
        endpoint = collector.lookup(ref) if ref else None
        if endpoint is None or endpoint.kind != SearchEntityType.wiki_page:
            return None
        return endpoint.id, titles.get(endpoint.id, "")

    page_ids = [
        endpoint.id
        for endpoint in collector._refs.values()
        if endpoint.kind == SearchEntityType.wiki_page
    ]
    if page_ids:
        from sqlmodel import select

        rows = await session.exec(
            select(WikiPage.id, WikiPage.title).where(WikiPage.id.in_(page_ids))
        )
        titles = {page_id: title for page_id, title in rows.all() if page_id}

    rewritten = 0
    for kind, entity_id in bodies:
        model = Task if kind == SearchEntityType.task else Comment
        row = await session.get(model, entity_id)
        if row is None:
            continue
        column = "description" if model is Task else "content"
        before = getattr(row, column) or ""
        after = rewrite_page_links(before, page_for)
        if after != before:
            rewritten += before.count("](") - after.count("](")
            setattr(row, column, after)
            session.add(row)
    await session.flush()
    return rewritten
