"""What one import job knows that no single envelope does.

Two facts, and both exist for the same reason: an envelope is written without
knowing where it will land. It names the far end of a link by a string the
source chose, and it names people by the handles they had somewhere else.
Neither can be resolved by the importer reading that envelope — the far end is
usually in another entry, and who somebody is here was answered by a person in
the wizard, not by the file.

So both are held for the length of the job and handed to every importer. An
importer reads what it needs and ignores the rest; most ignore both.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.import_engine.links import LinkCollector
from app.services.import_engine.people import PeopleMap


@dataclass
class ImportContext:
    """The job's shared state, passed to every ``apply``.

    Defaults are the empty versions rather than ``None``, so an importer can
    always ask without checking first: a job with nothing mapped and nothing
    linked behaves exactly as one that was never given either.
    """

    links: LinkCollector = field(default_factory=LinkCollector)
    people: PeopleMap = field(default_factory=PeopleMap)
    #: Property names somebody unticked on the review. Their definitions are
    #: not created, and every value naming one falls away with it — the
    #: review lists the properties an import would add to an initiative
    #: somebody else runs, and this is the answer to that list. A project's
    #: metadata is the project's, made with it, and no name here touches it.
    excluded_properties: frozenset[str] = frozenset()
    #: The site the bundle was read from — an Atlassian site, for a fetch. A
    #: link in a task to a page there becomes a mention of the page, once the
    #: page has been written in the same job.
    source_url: str | None = None
    #: Files to file under a page of a wiki once both exist, as
    #: ``(file ref, wiki ref, page slug)``: the wiki's own importer knows
    #: its pages by slug, and the file is applied before the wiki is.
    placements: list[tuple[str, str, str]] = field(default_factory=list)
    #: Whether what is being imported was exported from this community on this
    #: server. A reference to something the export did not carry still names
    #: the thing it named then, so it keeps pointing at it rather than being
    #: reduced to its title.
    same_community: bool = False


def exported_from_here(
    source_instance_url: Any, source_guild_id: Any, *, guild_id: int | None
) -> bool:
    """Whether an export names this server and this community as where it was
    taken. Both have to match: a community id is only unique on its own
    server, and an export that says nothing about either is from elsewhere."""
    from app.core.config import settings

    if not isinstance(source_guild_id, int) or source_guild_id != guild_id:
        return False
    if not isinstance(source_instance_url, str) or not source_instance_url.strip():
        return False
    return source_instance_url.strip().rstrip("/") == settings.APP_URL.strip().rstrip(
        "/"
    )


def excluded_property_names(raw: Any) -> frozenset[str]:
    """What a confirm recorded as unticked, read back defensively.

    It round-tripped through a request into the job's params, so anything
    that is not a list of non-empty strings is treated as nothing unticked.
    """
    if not isinstance(raw, list):
        return frozenset()
    return frozenset(name for name in raw if isinstance(name, str) and name)
