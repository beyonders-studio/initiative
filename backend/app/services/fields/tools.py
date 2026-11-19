"""The datasets that are a tool, one declaration each.

Where a dataset *is* a tool, almost everything about it is already derivable —
its name is the tool's plural, its sharing is the tool's own, and its fields are
its model's columns. So each of these is a name, a tool, and whatever the table
cannot say for itself.

They live together rather than one module each because there is nothing to say
about any of them individually. A dataset that grows a computed field or a
relation worth explaining earns its own module then, the way tasks have.

A tool plug-in's tool and each of its item tables are datasets too
(:func:`build_installed`), named by their tables as a built-in's are, their
fields their columns: the declared ones and those every tool's rows have.
"""

from __future__ import annotations

from sqlalchemy import Table

from app.core.tool_set import ToolSet
from app.core.tools import Tool
from app.db.plugin_tools import DECLARED
from app.models.tenant.calendar import Calendar
from app.models.tenant.collection import Collection
from app.models.tenant.contact import Contact
from app.models.tenant.dashboard import Dashboard
from app.models.tenant.file import File, FileVersion
from app.models.tenant.post import Post
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


def build_collections() -> Dataset:
    """A collection in Files, read as its reader sees it: one holding a file
    they can open."""
    return Dataset(
        model=Collection,
        tool=Tool.file,
        name_override="collections",
        fields=derive_fields(Collection),
    )


def build_wikis() -> Dataset:
    return Dataset(model=Wiki, tool=Tool.wiki, fields=derive_fields(Wiki))


def build_contacts() -> Dataset:
    return Dataset(model=Contact, tool=Tool.contact, fields=derive_fields(Contact))


def build_wiki_pages() -> Dataset:
    """One page of a wiki. Its own dataset because what somebody asks about a
    wiki — how many pages are still drafts, what has not been touched since
    spring — is a question about the pages, and the wiki is what they are
    grouped by.

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


def build_installed(tools: ToolSet) -> dict[str, Dataset]:
    """The datasets of every tool in ``tools`` an installed tool plug-in
    brings, by table: the tool's own, and each item table's, which reaches
    the table it sits under as a wiki's page reaches its wiki, each tagged as
    its kind is."""
    from app.services.tenant.tags import tag_links

    tagged = {link.table.name: link for link in tag_links(tools).values()}

    def build(table: Table) -> Dataset:
        return Dataset(
            model=table,
            name_override=table.name,
            # A declared person is an id with no key to ``users``: say so.
            fields=derive_fields(
                table,
                references={
                    column.name: "users"
                    for column in table.c
                    if column.info.get("field") == "user_reference"
                },
                tags=tagged.get(table.name),
            ),
            relations=tuple(
                Relation(
                    name=fk.column.table.info[DECLARED]["key"],
                    hops=(
                        Hop(
                            dataset=fk.column.table.name,
                            left=fk.parent.name,
                            right=fk.column.name,
                        ),
                    ),
                )
                for fk in table.foreign_keys
                if DECLARED in fk.column.table.info
            ),
        )

    return {
        table.name: build(table)
        for tool in tools.installed
        for table in (tool.table, *tool.items)
    }
