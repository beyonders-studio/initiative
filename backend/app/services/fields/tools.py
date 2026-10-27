"""The datasets that are a tool, one declaration each.

Where a dataset *is* a tool, almost everything about it is already derivable —
its name is the tool's plural, its sharing is the tool's own, and its fields are
its model's columns. So each of these is a name, a tool, and whatever the table
cannot say for itself.

They live together rather than one module each because there is nothing to say
about any of them individually. A dataset that grows a computed field or a
relation worth explaining earns its own module then, the way tasks have.
"""

from __future__ import annotations

from app.core.tools import Tool
from app.models.tenant.calendar import Calendar
from app.models.tenant.counter import Counter, CounterGroup
from app.models.tenant.dashboard import Dashboard
from app.models.tenant.file import File, FileVersion
from app.models.tenant.library import Library, LibraryItem, LibraryItemVersion
from app.models.tenant.post import Post
from app.models.tenant.queue import Queue, QueueItem
from app.models.tenant.wiki import Wiki, WikiPage
from app.services.fields.derive import derive_fields
from app.services.fields.spec import Dataset, Hop, Relation

#: A file's body is the file. It is a structured blob rather than a
#: value, so there is nothing a comparison would mean against it — the
#: derivation drops it, and this says why.
_FILE_INTERNAL = frozenset({"content"})


def build_files() -> Dataset:
    return Dataset(
        model=File,
        tool=Tool.file,
        fields=derive_fields(File, internal=_FILE_INTERNAL),
        relations=(
            Relation(
                name="current_version",
                hops=(
                    Hop(
                        dataset="file_versions",
                        left="current_version_id",
                        right="id",
                    ),
                ),
            ),
        ),
    )


def build_file_versions() -> Dataset:
    """One uploaded version of an uploaded file: its type, size and name. A
    file reaches the one it shows as ``current_version``."""
    return Dataset(
        model=FileVersion,
        tool=Tool.file,
        name_override="file_versions",
        fields=derive_fields(FileVersion),
    )


def build_queues() -> Dataset:
    return Dataset(model=Queue, tool=Tool.queue, fields=derive_fields(Queue))


def build_queue_items() -> Dataset:
    """One item in a queue. Its own dataset because the question worth asking
    is about the items, and the queue is what they are grouped by."""
    return Dataset(
        model=QueueItem,
        tool=Tool.queue,
        name_override="queue_items",
        fields=derive_fields(QueueItem),
        relations=(
            Relation(
                name="queue",
                hops=(Hop(dataset="queues", left="queue_id", right="id"),),
            ),
        ),
    )


def build_counter_groups() -> Dataset:
    return Dataset(
        model=CounterGroup,
        tool=Tool.counter_group,
        fields=derive_fields(CounterGroup),
    )


def build_counters() -> Dataset:
    """One counter in a group. Its own dataset for the reason queue items
    have one: what one counter reads is a question about the counters, and the
    group is what they are grouped by."""
    return Dataset(
        model=Counter,
        tool=Tool.counter_group,
        name_override="counters",
        fields=derive_fields(Counter),
        relations=(
            Relation(
                name="counter_group",
                hops=(
                    Hop(dataset="counter_groups", left="counter_group_id", right="id"),
                ),
            ),
        ),
    )


def build_calendars() -> Dataset:
    return Dataset(model=Calendar, tool=Tool.calendar, fields=derive_fields(Calendar))


def build_dashboards() -> Dataset:
    #: What a dashboard is made of is a definition, and a definition is not a
    #: value to compare against.
    return Dataset(
        model=Dashboard,
        tool=Tool.dashboard,
        fields=derive_fields(Dashboard, internal=frozenset({"definition", "config"})),
    )


def build_posts() -> Dataset:
    return Dataset(
        model=Post,
        tool=Tool.post,
        fields=derive_fields(Post, internal=frozenset({"body"})),
    )


def build_libraries() -> Dataset:
    return Dataset(model=Library, tool=Tool.library, fields=derive_fields(Library))


def build_wikis() -> Dataset:
    return Dataset(model=Wiki, tool=Tool.wiki, fields=derive_fields(Wiki))


def build_wiki_pages() -> Dataset:
    """One page of a wiki. Its own dataset for the reason queue items and
    library pictures have one: what somebody asks about a wiki — how many
    pages are still drafts, what has not been touched since spring — is a
    question about the pages, and the wiki is what they are grouped by.

    A page's body and the Yjs state beside it are dropped: one is a structured
    blob and the other is a room's working copy of it, and neither is a value a
    comparison would mean anything against. So are the headings read out of the
    body, which are a shape rather than a value.
    """
    return Dataset(
        model=WikiPage,
        tool=Tool.wiki,
        name_override="wiki_pages",
        fields=derive_fields(
            WikiPage, internal=frozenset({"content", "yjs_state", "yjs_updated_at"})
        ),
        relations=(
            Relation(
                name="wiki",
                hops=(Hop(dataset="wikis", left="wiki_id", right="id"),),
            ),
        ),
    )


def build_library_items() -> Dataset:
    """One picture in a library. Its own dataset for the reason queue items
    have one: the question worth asking — how many arrived this month, which
    are still untitled — is about the pictures, and the library is what they
    are grouped by."""
    return Dataset(
        model=LibraryItem,
        tool=Tool.library,
        name_override="library_items",
        fields=derive_fields(LibraryItem),
        relations=(
            Relation(
                name="library",
                hops=(Hop(dataset="libraries", left="library_id", right="id"),),
            ),
            Relation(
                name="current_version",
                hops=(
                    Hop(
                        dataset="library_item_versions",
                        left="current_version_id",
                        right="id",
                    ),
                ),
            ),
        ),
    )


def build_library_item_versions() -> Dataset:
    """One uploaded rendition of a picture: its type, size and dimensions. A
    picture reaches the one it shows as ``current_version``."""
    return Dataset(
        model=LibraryItemVersion,
        tool=Tool.library,
        name_override="library_item_versions",
        fields=derive_fields(LibraryItemVersion),
    )
