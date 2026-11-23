"""The search index registry — which tables are searchable, and how.

One declaration per searchable table in :data:`SEARCH_SOURCES`, from which two
things are rendered: the trigger that keeps ``search_entries`` current, and the
default query scope. Adding a searchable table is one entry here.

Nothing declares *which* initiative a row belongs to. That is read from the same
``INITIATIVE_PATHS`` entry that renders the table's RLS policies, so a row cannot
be gated by one initiative and indexed under another — the argument
``event_capture`` already makes for reusing that registry, applied again.

Chunking is a length rule, not a per-table setting: an extractor yields text and
the trigger splits it if it is long. A tag's name is one chunk by the same code
path that gives a long file several.
"""

from __future__ import annotations

import enum
import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from functools import lru_cache, partial
from typing import Any

from sqlalchemy import JSON, DateTime, Enum, MetaData, Table
from sqlmodel import SQLModel

from app.core.file_types import FileType
from app.core.identity_boundary import STORED_MENTION
from app.core.search import SearchEntityType
from app.core.tool_set import BUILTIN_TOOLS, KEPT_TOOL_SETS, ToolRecord, ToolSet
from app.core.tools import Kind, Tool
from app.db.initiative_rls import (
    comment_parents,
    governing_walk,
    initiative_locator,
    paths_for,
)
from app.db.names import object_name

#: How a row reaches the trigger's dynamic lookups: as ``$1`` in an EXECUTE.
ROW = "($1)"

SEARCH_FUNCTION = "public.refresh_search_entry"

#: Target size of one chunk's body text, and the ceiling on chunks per entity.
#: The ceiling is a backstop for a pathological spreadsheet; ordinary content is
#: nowhere near it.
CHUNK_CHARS = 8000
MAX_CHUNKS = 2000

#: How much of a comment stands in for its title.
COMMENT_PREVIEW_CHARS = 140

#: What an entry holds for each person its body mentions: this and their id, as
#: a word of its own. The parser never starts a word with it, so nothing typed
#: is read as one; a search names a person's mentions by rewriting a word that
#: names them (``app.services.tenant.search``).
MENTION_LEXEME = "@"


@dataclass(frozen=True)
class SearchDependency:
    """A column on ANOTHER table that a source's stored gate is derived from.

    Almost every source names its parent in a column of its own, so its own
    trigger fires when that parent changes. A comment does not: it names a task,
    and the tool governing it is the task's PROJECT — so a task moving between
    projects moves the comment without touching the comment's row. Declared here,
    it gets a trigger on the table that moved, rewriting the entries that
    followed it.
    """

    #: The table whose column moves rows between gates.
    table: str
    #: The column on it that does the moving.
    column: str
    #: How the dependent source's rows tie back to it.
    local_column: str
    #: Where the source names what it is on as a pair, the kind that pair
    #: holds for this table's rows.
    local_kind: str | None = None

    def rows_under(self, row: str) -> str:
        """The source rows under the ``$2`` this trigger fired for."""
        return _tied(row, self.local_column, self.local_kind, "= $2")


@dataclass(frozen=True)
class ArchiveParent:
    """Something archivable a row sits under, which takes the row out of the
    working set when it is archived.

    The archive cascade stamps every archivable child, so a row that can carry
    its own ``archived_at`` needs none of these. One that cannot — a comment, a
    wiki page, a counter — reads it off what it sits under, and a trigger on
    that table rewrites its entries when the stamp moves.
    """

    #: The table whose ``archived_at`` counts.
    table: str
    #: The source's column naming it, or naming the step to it.
    column: str
    #: ``(table, column)`` between the two, where the row names the step.
    through: tuple[str, str] | None = None
    #: Where the source names what it is on as a pair, the kind that pair
    #: holds for this parent (or for the step to it); ``column`` is its id.
    kind: str | None = None

    @property
    def label(self) -> str:
        """What its trigger is named by: the column, or ``<kind>_id`` for a
        pair, which is the name a comment's column for the kind had (a tool
        plug-in's ``.`` spelled ``_``)."""
        return self.column if self.kind is None else f"{self.kind.replace('.', '_')}_id"

    def archived(self, row: str) -> str:
        if self.through is None:
            exists = (
                f"EXISTS (SELECT 1 FROM {self.table} a WHERE a.id = {row}.{self.column}"
                " AND a.archived_at IS NOT NULL)"
            )
        else:
            step, fk = self.through
            exists = (
                f"EXISTS (SELECT 1 FROM {step} s JOIN {self.table} a ON a.id = s.{fk}"
                f" WHERE s.id = {row}.{self.column} AND a.archived_at IS NOT NULL)"
            )
        if self.kind is None:
            return exists
        return f"({row}.subject_type = '{self.kind}' AND {exists})"

    def rows_under(self, row: str) -> str:
        """The source rows under the ``$2`` this trigger fired for."""
        if self.through is None:
            return _tied(row, self.column, self.kind, "= $2")
        step, fk = self.through
        return _tied(
            row, self.column, self.kind, f"IN (SELECT id FROM {step} WHERE {fk} = $2)"
        )


def _tied(row: str, column: str, kind: str | None, match: str) -> str:
    """``row.column`` matching, and, for a pair, of ``kind``."""
    tie = f"{row}.{column} {match}"
    return tie if kind is None else f"{row}.subject_type = '{kind}' AND {tie}"


@dataclass(frozen=True)
class SearchSource:
    """How one table's rows become search entries."""

    #: Value stored in ``search_entries.entity_type``: the kind of what is
    #: indexed.
    entity_type: str
    #: Column holding the row's display title (weighted 'A'). Also the column
    #: whose change makes the entry stale, even where ``title_sql`` builds the
    #: stored value from it.
    title: str
    #: Builds the title from a row alias, for a source whose title is not a
    #: column as it stands — a comment has no title, so it shows an opening.
    title_sql: Callable[[str], str] | None = None
    #: Columns feeding the body (weighted 'B'). Also the columns whose change
    #: makes the entry stale, so they drive the trigger's WHEN clause.
    body: tuple[str, ...] = ()
    #: Builds the body from a row alias, for a source whose text is not simply
    #: its columns concatenated. Takes precedence over ``body``; the columns are
    #: still declared above so the WHEN clause knows what to watch.
    body_sql: Callable[[str], str] | None = None
    #: The tool whose sharing governs this row, and the column naming the
    #: resource id to test. ``dac_id=None`` means the row's own ``id``.
    #: ``dac_tool=None`` means the row carries no sharing gate (a tag).
    dac_tool: ToolRecord | None = None
    dac_id: str | None = None
    #: Builds ``(tool, id)`` from a row alias, for a source whose governing tool
    #: differs per row. Takes precedence over the pair above.
    dac_sql: Callable[[str], tuple[str, str]] | None = None
    #: Whether this source is searched when the caller names no types. False
    #: puts the source behind an explicit opt-in and out of the default index.
    in_default_scope: bool = True
    #: Columns on other tables that move these rows between gates.
    depends_on: tuple[SearchDependency, ...] = ()
    #: What archiving takes this row with, for a source whose governing tool
    #: is not one fixed column, read once the models are loaded. ``None``
    #: derives it from ``dac_tool``/``dac_id``.
    archive_parents: Callable[[], tuple[ArchiveParent, ...]] | None = None

    @property
    def trigger_name(self) -> str:
        """Stem for this table's triggers; INSERT/DELETE and UPDATE are split
        (a WHEN clause naming OLD is invalid on INSERT). A tool plug-in's kind
        holds a ``.``, which a name spells ``_``."""
        return f"search_{self.entity_type.replace('.', '_')}"

    def trigger(self, suffix: str) -> str:
        """One of this table's triggers, by what it does."""
        return object_name("search", self.trigger_name.removeprefix("search_"), suffix)


def _json_text(row: str, path: str, *, column: str = "content") -> str:
    """Text of every value a jsonpath selects, as one space-joined string.

    ``strict`` so a value reachable by more than one path is taken once —
    the lax form walks into arrays as well as their elements and would store
    the same text twice. ``silent`` so a shape that simply lacks the key
    yields nothing instead of raising.
    """
    return (
        "coalesce((SELECT string_agg(v #>> '{}', ' ') FROM jsonb_path_query("
        f"{row}.{column}, '{path}', '{{}}'::jsonb, true) v), '')"
    )


def _with_words(expr: str) -> str:
    """``expr``, plus the same value split on punctuation.

    A URL or a filename is tokenized as a whole — ``www.figma.com`` and
    ``vendor-contract-2026.pdf`` are each a single lexeme — so the words inside
    them are not findable on their own. Emitting a split copy alongside makes
    both work. Used only for these short, punctuation-dense fields; doing it to
    prose would double what is stored for nothing.
    """
    return f"{expr} || ' ' || regexp_replace({expr}, '[^[:alnum:]]+', ' ', 'g')"


def _post_text(row: str) -> str:
    """A post's searchable text: every word in its Lexical body.

    The same recursive ``text`` path a lexical file uses — a text node, a
    mention, and a smart chip's label all keep their words in a field of that
    name — read from ``body`` rather than ``content``, which is what a post
    calls the column. A post whose body is only a picture indexes on its
    headline alone, which is what there is to index.
    """
    return _json_text(row, "strict $.**.text", column="body")


def _wiki_page_text(row: str) -> str:
    """A wiki page's searchable text: every word in its Lexical body.

    The same recursive ``text`` path a post and a lexical file use. A page
    needs no branch of its own — a page is always prose, where a file's
    ``content`` holds a different shape per type.
    """
    return _json_text(row, "strict $.**.text")


def _current_filename(row: str, versions: str) -> str:
    """The uploaded filename of the version a row shows (its
    ``current_version_id`` in ``versions``), or empty where it shows none."""
    return (
        f"coalesce((SELECT v.original_filename FROM {versions} v"
        f" WHERE v.id = {row}.current_version_id), '')"
    )


def _file_text(row: str) -> str:
    """A file's searchable text, by what kind of file it is.

    ``content`` holds a different shape per type, so there is no single
    expression. ``lexical`` and ``excalidraw`` share one: a Lexical text node
    and an Excalidraw text or label element both keep their text in a field
    named ``text``, and the recursive path reaches nested cases — a mention, a
    reference, an image caption's own editor state.

    An uploaded file contributes nothing here: its bytes live in ``uploads``,
    so its name, description and uploaded filename are all there is to index.
    """
    leaves = _json_text(row, "strict $.**.text")
    cells = (
        "coalesce((SELECT string_agg(v #>> '{}', ' ') FROM ("
        f"SELECT v FROM jsonb_path_query({row}.content, 'strict $.**.cells.*', "
        "'{}'::jsonb, true) v"
        " UNION ALL "
        f"SELECT v FROM jsonb_path_query({row}.content, 'strict $.sheets[*].name', "
        "'{}'::jsonb, true) v) s), '')"
    )
    url = _with_words(f"coalesce({row}.content ->> 'url', '')")
    return (
        f"(CASE {row}.file_type::text"
        f" WHEN '{FileType.lexical.value}' THEN {leaves}"
        f" WHEN '{FileType.excalidraw.value}' THEN {leaves}"
        f" WHEN '{FileType.sheet.value}' THEN {cells}"
        f" WHEN '{FileType.url.value}' THEN {url}"
        " ELSE '' END)"
        " || ' ' || " + _with_words(_current_filename(row, "file_versions"))
    )


def _task_text(row: str) -> str:
    """A task's searchable text: its description, and its checklist lines.

    The lines are content someone wrote on the task, so a phrase typed onto one
    finds the task it belongs to. There is no separate row to find instead.
    """
    lines = (
        "coalesce((SELECT string_agg(entry->>'text', ' ') "
        f"FROM jsonb_array_elements({row}.checklist) AS entry), '')"
    )
    return f"coalesce({row}.description, '') || ' ' || {lines}"


#: What a cut preview can end inside: a mention or reference, a markdown
#: picture or link, or a stored file's address.
_UNFINISHED_TAIL = r"(?:(?:[@!]|#\w+)?\[[^\]\n]*(?:\](?:\([^)\n]*)?)?|\S*/uploads/\S*)$"


def _comment_preview(row: str) -> str:
    """The opening of a comment, as the line a result is shown by.

    A comment has no title. Storing the whole of one would put an essay where a
    name goes; the full text is still indexed as the body, so what matched is
    findable either way. A mention, reference, picture or link, or a stored
    file's address, that the cut goes through is left out whole.
    """
    content = f"{row}.content"
    return (
        f"CASE WHEN length({content}) > {COMMENT_PREVIEW_CHARS} THEN"
        f" regexp_replace(left({content}, {COMMENT_PREVIEW_CHARS}), '{_UNFINISHED_TAIL}', '')"
        f" ELSE {content} END"
    )


def _comment_archive_parents(tools: ToolSet) -> tuple[ArchiveParent, ...]:
    """What archiving takes a comment with: the thing it is on, or, where that
    cannot be archived itself, the tool it is part of (a wiki page's wiki)."""
    parents: list[ArchiveParent] = []
    tables = tools.tables
    for kind, parent in comment_parents(tools).items():
        if "archived_at" in tables[parent.table].columns:
            parents.append(ArchiveParent(parent.table, "subject_id", kind=kind))
        elif parent.tool_fk is not None and parent.governed_by is not None:
            parents.append(
                ArchiveParent(
                    parent.governed_by.table.name,
                    "subject_id",
                    through=(parent.table, parent.tool_fk),
                    kind=kind,
                )
            )
    return tuple(parents)


def _comment_dac(row: str, tools: ToolSet) -> tuple[str, str]:
    """Which tool's sharing governs a comment, and which of its entities.

    A comment is said on one subject, and the subjects are declared once for
    the RLS policies — so the legs are derived from that same list rather than
    restated here. A subject that is not itself a tool row names the tool it is
    shared as part of: a task by its project, a wiki page by its wiki.
    """
    governing: list[str] = []
    ids: list[str] = []
    for kind, parent in comment_parents(tools).items():
        if parent.governed_by is None:
            # No sharing to stamp: the entry is reached as the comment is.
            continue
        if parent.tool_fk is not None:
            ident = (
                f"(SELECT {parent.tool_fk} FROM {parent.table} "
                f"WHERE id = {row}.subject_id)"
            )
        elif parent.table == parent.governed_by.table.name:
            ident = f"{row}.subject_id"
        else:
            # Under its tool by more than one hop: the tool is the outermost
            # row its walk reaches.
            ident = (
                f"(SELECT {parent.chain[-1][1]} FROM {parent.frm} "
                f"WHERE {parent.tie} = {row}.subject_id)"
            )
        governing.append(f"WHEN '{kind}' THEN '{parent.governed_by.kind}'")
        ids.append(f"WHEN '{kind}' THEN {ident}")
    return (
        f"(CASE {row}.subject_type {' '.join(governing)} END)",
        f"(CASE {row}.subject_type {' '.join(ids)} END)",
    )


def _title_expr(source: SearchSource, row: str = ROW) -> str:
    """Row expression yielding a source's stored title."""
    if source.title_sql is not None:
        return source.title_sql(row)
    return f"{row}.{source.title}"


#: Columns that say a row is not part of the working set. Having the column IS
#: the declaration — a source states nothing, the same way ``deleted_at`` is read
#: off the table rather than declared.
FLAG_COLUMNS: dict[str, str] = {"archived": "archived_at", "template": "is_template"}


def _flag_expr(table: Table, flag: str, row: str) -> str | None:
    """Row expression for one flag, or ``None`` where the table cannot carry it.

    A flag is a boolean either way, but the column behind it need not be: a
    lifecycle column answers "when", and "whether" is that column being set. The
    shape comes off the column's own type rather than a second declaration
    saying how to read it.
    """
    column = FLAG_COLUMNS[flag]
    columns = table.columns
    if column not in columns:
        return None
    if isinstance(columns[column].type, DateTime):
        return f"{row}.{column} IS NOT NULL"
    return f"{row}.{column}"


def archive_parents(
    table: Table, source: SearchSource, tables: Mapping[str, Table]
) -> tuple[ArchiveParent, ...]:
    """What archiving takes a row of ``source`` with. A row that carries its
    own ``archived_at`` is stamped by the cascade and needs none; any other
    sits under its governing tool."""
    if source.archive_parents is not None:
        return source.archive_parents()
    if "archived_at" in table.columns or not (source.dac_tool and source.dac_id):
        return ()
    tool = source.dac_tool.table.name
    if "archived_at" not in tables[tool].columns:
        return ()
    return (ArchiveParent(tool, source.dac_id),)


def _archived_expr(
    table: Table, source: SearchSource, row: str, tables: Mapping[str, Table]
) -> str | None:
    """Whether a row is archived: stamped itself, or under something that is."""
    legs = [_flag_expr(table, "archived", row)]
    legs += [parent.archived(row) for parent in archive_parents(table, source, tables)]
    present = [leg for leg in legs if leg]
    return f"({' OR '.join(present)})" if present else None


def _written(table: Table, source: SearchSource) -> tuple[str, ...]:
    """The body columns somebody writes in: all of them, less a column that only
    names a kind (an enum, in the database or on the model) or another row (a
    foreign key)."""
    from app.db.base import MODELS_BY_TABLE

    columns = table.columns
    model = MODELS_BY_TABLE.get(table.name)
    fields = model.model_fields if model is not None else {}

    def names_a_kind(column: str) -> bool:
        annotation = fields[column].annotation if column in fields else None
        return isinstance(columns[column].type, Enum) or (
            isinstance(annotation, type) and issubclass(annotation, enum.Enum)
        )

    return tuple(
        c for c in source.body if not names_a_kind(c) and not columns[c].foreign_keys
    )


def _mentions_expr(table: Table, source: SearchSource, row: str = ROW) -> str:
    """Row expression yielding the people a source's body mentions, as words.

    A markdown mention in any written column, and in an editor state a mention
    node's ``mentionUserId`` as well. Empty where the source writes nothing.
    """
    columns = table.columns
    markdown = STORED_MENTION.pattern
    found: list[str] = []
    for column in _written(table, source):
        value = f"{row}.{column}"
        if isinstance(columns[column].type, JSON):
            found.append(
                "SELECT v #>> '{}' FROM jsonb_path_query("
                f"{value}, 'strict $.**.mentionUserId ? (@.type() == \"number\")',"
                " '{}'::jsonb, true) v"
            )
            value = f"{value}::text"
        found.append(f"SELECT m[2] FROM regexp_matches({value}, '{markdown}', 'g') m")
    if not found:
        return ""
    return (
        f"ARRAY(SELECT DISTINCT '{MENTION_LEXEME}' || id"
        f" FROM ({' UNION ALL '.join(found)}) AS mentioned(id))"
    )


def _body_expr(source: SearchSource, row: str = ROW) -> str:
    """Row expression yielding a source's body text."""
    if source.body_sql is not None:
        return source.body_sql(row)
    if not source.body:
        return ""
    parts = [f"coalesce({row}.{c}, '')" for c in source.body]
    return " || ' ' || ".join(parts) if len(parts) > 1 else parts[0]


def _text(table: Table) -> tuple[str, ...]:
    """What a row says beyond its name: a model's ``description``, or the
    columns a tool plug-in declared as text."""
    return tuple(
        c.name
        for c in table.columns
        if c.info.get("field", "text" if c.name == "description" else None) == "text"
    )


def _two_hop_dac(
    row: str, kind: str, hops: tuple[tuple[str, str], ...]
) -> tuple[str, str]:
    """The sharing gate of an item two hops under its tool: the tool's kind,
    and the id its middle row names."""
    (fk, mid), (mid_fk, _) = hops
    return f"'{kind}'::text", f"(SELECT {mid_fk} FROM {mid} WHERE id = {row}.{fk})"


def _kind_source(kind: Kind, tools: ToolSet) -> SearchSource:
    """A kind inside a tool, by its name and its text, gated by the sharing of
    the tool it lives in, which its path walks to. A kind in no one instance
    of its tool (a collection) stamps no sharing: its entry is reached as the
    row itself is (``initiative_rls.named_tool_path``)."""
    table = tools.tables[kind.table]
    if kind.standalone:
        return SearchSource(kind.value, title="name", body=_text(table))
    walk = governing_walk(kind.table, paths_for(tools))
    assert walk is not None, kind.table
    tool, hops = walk
    # The key to its parent moves it, and under two hops so does the middle
    # row's key to the tool.
    gate: dict[str, Any] = {"dac_id": hops[0][0]}
    if len(hops) == 2:
        (fk, mid), (mid_fk, _) = hops
        gate["dac_sql"] = partial(_two_hop_dac, kind=tool.kind, hops=hops)
        gate["depends_on"] = (SearchDependency(mid, mid_fk, fk),)
    return SearchSource(
        kind.value, title="name", body=_text(table), dac_tool=tool, **gate
    )


#: Where a tool's or a kind's text is not its name and its text
#: (:func:`_text`). A kind absent from here is not an omission — it takes that
#: shape.
TEXT_OVERRIDES: dict[str, dict[str, object]] = {
    Tool.file.value: {
        "body": ("content", "file_type", "current_version_id"),
        "body_sql": _file_text,
    },
    # A post's text is what it says, not a summary of it: the headline is the
    # title and the Lexical body is the body. There is no `description`.
    Tool.post.value: {"body": ("body",), "body_sql": _post_text},
    # A contact is found by its name. How to reach one is not text somebody
    # writes in, which is what a body is (``written_columns``).
    Tool.contact.value: {"body": ()},
    "task": {
        "title": "title",
        "body": ("description", "checklist"),
        "body_sql": _task_text,
    },
    "calendar_event": {"title": "title", "body": ("description", "location")},
    # A page is found by its title and by what is written on it. Its body is a
    # Lexical state, the same shape a lexical file's is, so it is read by the
    # same extractor rather than a second one.
    "wiki_page": {"title": "title", "body": ("content",), "body_sql": _wiki_page_text},
}


@lru_cache(KEPT_TOOL_SETS)
def search_sources(tools: ToolSet) -> dict[str, SearchSource]:
    """table -> how its rows are indexed, in a community with ``tools``: every
    tool's own table and every kind inside one, derived; the guild's tags; and
    the comments on any of them."""
    derived = [
        *(
            (
                t.table.name,
                SearchSource(t.kind, title="name", body=_text(t.table), dac_tool=t),
            )
            for t in tools
        ),
        *((kind.table, _kind_source(kind, tools)) for kind in tools.child_kinds),
    ]
    return {
        **{
            table: replace(source, **TEXT_OVERRIDES.get(source.entity_type, {}))
            for table, source in derived
        },
        # Guild-level vocabulary, in no tool: no initiative, no sharing gate.
        # Reaching the query at all means being in the guild, which is the
        # whole gate for a tag.
        "tags": SearchSource(SearchEntityType.tag.value, title="name"),
        # What people said on the content above. Out of the default scope: it
        # is the highest-volume table in a busy guild, and a caller that wants
        # it says so — which is what the results page's own tab does.
        "comments": SearchSource(
            SearchEntityType.comment.value,
            title="content",
            title_sql=_comment_preview,
            body=("content",),
            dac_sql=partial(_comment_dac, tools=tools),
            in_default_scope=False,
            # A comment on a task is governed by the task's project, and a task
            # can move between projects. Nothing about the comment changes when
            # it does, so the entry is rewritten from the table that moved.
            # Every other parent names its own initiative and cannot move
            # between them.
            depends_on=(
                SearchDependency(
                    "tasks", "project_id", "subject_id", local_kind="task"
                ),
            ),
            archive_parents=partial(_comment_archive_parents, tools),
        ),
    }


#: :func:`search_sources` of the built-in tools.
SEARCH_SOURCES: dict[str, SearchSource] = search_sources(BUILTIN_TOOLS)


def written_columns() -> dict[type[SQLModel], tuple[str, ...]]:
    """Every column somebody writes in, by model: the body of every source
    above, less a column that only names a kind (an enum). Whatever can be
    searched for is written somewhere, and this is where."""
    from app.db.base import MODELS_BY_TABLE

    written = {
        MODELS_BY_TABLE[table]: _written(SQLModel.metadata.tables[table], source)
        for table, source in SEARCH_SOURCES.items()
    }
    return {model: columns for model, columns in written.items() if columns}


#: Tables that are deliberately NOT searchable, and why. Every guild content
#: table is in exactly one of this or SEARCH_SOURCES; ``search_index_test``
#: fails until a new one is placed, so a table ships searchable by default or
#: says why not.
NOT_SEARCHABLE: dict[str, str] = {
    "search_entries": "the index itself",
    "uploads": "stored files, found through the content that shows them",
    "event_outbox": "change log, not content",
    "plugin_event_outbox": "plug-in events awaiting delivery, not content",
    "resource_grants": "sharing rows carry no text",
    "metadata_definitions": "field config, reached from the tool it configures",
    "webhook_subscriptions": "integration config",
    "intake_bindings": "routing config, reached from the settings page",
    "guest_invite_grants": "an invite's terms, reached from the invite",
    "share_requests": "who asked for what, read where it is answered",
    "moderation_reports": "moderation work, reached from its own surface",
    "moderation_report_reporters": "who reported a thing; never a search result",
    "moderation_actions": "the moderation log, reached from its own surface",
    "intake_cases": "the key -> task map; the task it names is what is indexed",
    "idea_votes": "who voted for an idea; never a search result",
    "evidence": "files attached to a report or a case, opened only through it",
    "personal_items": "one member's own opens, bookmarks and subscriptions",
    "engagement_levels": "how widely an item was engaged with, not content",
    "tool_layouts": "how a tool is laid out, reached from the tool",
    "task_statuses": "column names, reached from the project",
    "task_types": "type names, reached from the project",
    "file_versions": "history of a file already indexed",
    "collection_files": "which files a collection holds; each file is indexed",
    "post_polls": "the question a notice asks, reached from the notice",
    "post_poll_options": "a poll's choices, reached from the notice",
    "calendar_event_answers": "one invitee's answer, reached from the event",
    "initiatives": "structural; discovery is the join surface, not search",
    "event_reminder_dispatches": "scheduler bookkeeping",
    "batched_notices": "scheduler bookkeeping",
    "timer_marks": "scheduler bookkeeping",
    "subscription_progress": "notification bookkeeping",
    "reactions": "a gesture with no text of its own",
    "relationships": "an edge between two things, each indexed on its own",
}


#: A junction row is not a search result: it has no id to address and no text of
#: its own. Their composite primary key says so, which is the same derivation
#: ``event_capture`` uses to report them against their parent — so they are
#: excluded by construction rather than by a list that would need maintaining.
def addressable_tables(metadata: MetaData) -> set[str]:
    """Guild content tables a search hit could name — those with an ``id``."""
    return {
        name
        for name, table in metadata.tables.items()
        if [c.name for c in table.primary_key.columns] == ["id"]
    }


def entity_types(
    tools: ToolSet = BUILTIN_TOOLS, *, default_scope_only: bool = False
) -> tuple[str, ...]:
    """The entity types indexed in a community with ``tools``, sorted. The
    default-scope subset is what a query naming no types searches."""
    return tuple(
        sorted(
            s.entity_type
            for s in search_sources(tools).values()
            if s.in_default_scope or not default_scope_only
        )
    )


def _quoted(expr: str) -> str:
    """A SQL expression as a trigger-argument string literal."""
    return "'" + expr.replace("'", "''") + "'"


def _when_clause(table: Table, source: SearchSource) -> str:
    """Columns whose change makes a row's index entry stale.

    The trigger does not fire unless one of these actually changed, so the
    status moves, assignee changes and reordering that dominate writes to
    ``tasks`` cost nothing at all.
    """
    watched = [source.title, *source.body]
    if source.dac_id:
        watched.append(source.dac_id)
    watched.extend(FLAG_COLUMNS.values())
    # The two columns that decide whether a row is indexed at all. Watching
    # ``published_at`` is what makes the publication worker's stamp index the
    # notice: no trigger fires on the passage of time, but the write that
    # records the publication is a write like any other.
    watched.extend(("deleted_at", "published_at", "held_at", "removed_at"))
    present = [c for c in dict.fromkeys(watched) if c in table.columns]
    return " OR ".join(f"OLD.{c} IS DISTINCT FROM NEW.{c}" for c in present)


WRITE_FUNCTION = "public.search_entry_write"

#: Splits one entity's text into chunks and replaces its rows. Shared by the
#: refresh trigger and the reindex sweep so both produce identical entries.
WRITE_FUNCTION_SQL = f"""
CREATE OR REPLACE FUNCTION {WRITE_FUNCTION}(
    p_schema      text,
    p_entity_type text,
    p_entity_id   integer,
    p_initiative  integer,
    p_dac_tool    text,
    p_dac_id      integer,
    p_title       text,
    p_body        text,
    p_archived    boolean,
    p_template    boolean,
    p_mentions    text[]
) RETURNS void
    LANGUAGE plpgsql AS $write$
DECLARE
    v_title text := coalesce(p_title, '');
    v_body  text := coalesce(p_body, '');
    -- Every chunk carries them: a mention says who the whole entity is about,
    -- so "Ada budget" finds a long file whose mention and words sit apart.
    v_people tsvector := coalesce((
        SELECT string_agg(quote_literal(l) || ':1B', ' ')
          FROM unnest(p_mentions) l
    )::tsvector, '');
    v_chunk text;
    v_ix    smallint := 0;
    v_pos   integer := 1;
    v_len   integer;
    v_cut   integer;
    v_space integer;
    c_chunk constant integer := {CHUNK_CHARS};
    c_max   constant integer := {MAX_CHUNKS};
BEGIN
    EXECUTE format(
        'DELETE FROM %I.search_entries WHERE entity_type = $1 AND entity_id = $2',
        p_schema
    ) USING p_entity_type, p_entity_id;

    v_len := length(v_body);

    -- One row per chunk, and always at least one so a titled entity with no
    -- body is still findable. Short text takes this loop exactly once.
    LOOP
        IF v_pos > v_len THEN
            v_chunk := '';
            v_cut := 0;
        ELSE
            v_cut := least(c_chunk, v_len - v_pos + 1);
            v_chunk := substr(v_body, v_pos, v_cut);
            -- Prefer a whitespace boundary when more text follows, so a chunk
            -- does not end mid-word.
            IF v_pos + v_cut - 1 < v_len THEN
                v_space := strpos(reverse(v_chunk), ' ');
                IF v_space > 0 AND (length(v_chunk) - v_space) > c_chunk / 2 THEN
                    v_cut := length(v_chunk) - v_space;
                    v_chunk := substr(v_chunk, 1, v_cut);
                    v_cut := v_cut + 1;
                END IF;
            END IF;
        END IF;

        EXECUTE format(
            'INSERT INTO %I.search_entries ('
            '  entity_type, entity_id, chunk_ix, initiative_id,'
            '  dac_tool, dac_id, title, body, archived, template, updated_at, tsv'
            ') VALUES ($1, $2, $3, $4, nullif($5, ''''), $6, $7, nullif($8, ''''),'
            '  coalesce($9, false), coalesce($10, false), now(),'
            '  setweight(to_tsvector(''simple'', $7), ''A'') ||'
            '  setweight(to_tsvector(''simple'', $8), ''B'') || $11)',
            p_schema
        ) USING p_entity_type, p_entity_id, v_ix, p_initiative,
                p_dac_tool, p_dac_id, v_title, v_chunk,
                p_archived, p_template, v_people;

        v_ix := v_ix + 1;
        v_pos := v_pos + v_cut;
        EXIT WHEN v_pos > v_len OR v_ix >= c_max;
    END LOOP;
END
$write$;
"""


SEARCH_FUNCTION_SQL = f"""
CREATE OR REPLACE FUNCTION {SEARCH_FUNCTION}() RETURNS trigger
    LANGUAGE plpgsql AS $search$
DECLARE
    v_row        record;
    v_entity     integer;
    v_initiative integer;
    v_dac_id     integer;
    v_title      text;
    v_body       text;
    v_dac_tool   text;
    v_archived   boolean := false;
    v_template   boolean := false;
    v_mentions   text[];
BEGIN
    IF TG_OP = 'DELETE' THEN
        v_row := OLD;
    ELSE
        v_row := NEW;
    END IF;

    EXECUTE 'SELECT ' || TG_ARGV[2] INTO v_entity USING v_row;
    IF v_entity IS NULL THEN
        RETURN NULL;
    END IF;

    -- A delete, or a soft delete, leaves the entity with no rows: trash is
    -- browsed through the trash surface, not found by searching. So does a row
    -- that has not been published yet — a scheduled notice is a draft, and a
    -- draft is not something the people it will go to can find. Nor is
    -- content the platform holds (app.db.holds): it reads as absent. Nor is
    -- a comment that is a tombstone: it has no words left to find.
    IF TG_OP = 'DELETE'
       OR (to_jsonb(v_row) ? 'deleted_at'
           AND to_jsonb(v_row) ->> 'deleted_at' IS NOT NULL)
       OR (to_jsonb(v_row) ? 'held_at'
           AND to_jsonb(v_row) ->> 'held_at' IS NOT NULL)
       OR (to_jsonb(v_row) ? 'removed_at'
           AND to_jsonb(v_row) ->> 'removed_at' IS NOT NULL)
       OR (to_jsonb(v_row) ? 'published_at'
           AND to_jsonb(v_row) ->> 'published_at' IS NULL) THEN
        EXECUTE format(
            'DELETE FROM %I.search_entries WHERE entity_type = $1 AND entity_id = $2',
            TG_TABLE_SCHEMA
        ) USING TG_ARGV[1], v_entity;
        RETURN NULL;
    END IF;

    EXECUTE 'SELECT ' || TG_ARGV[0] INTO v_initiative USING v_row;
    EXECUTE 'SELECT ' || TG_ARGV[3] INTO v_title USING v_row;
    IF TG_ARGV[4] <> '' THEN
        EXECUTE 'SELECT ' || TG_ARGV[4] INTO v_body USING v_row;
    END IF;
    IF TG_ARGV[5] <> '' THEN
        EXECUTE 'SELECT ' || TG_ARGV[5] INTO v_dac_tool USING v_row;
        EXECUTE 'SELECT ' || TG_ARGV[6] INTO v_dac_id USING v_row;
    END IF;
    IF TG_ARGV[7] <> '' THEN
        EXECUTE 'SELECT ' || TG_ARGV[7] INTO v_archived USING v_row;
    END IF;
    IF TG_ARGV[8] <> '' THEN
        EXECUTE 'SELECT ' || TG_ARGV[8] INTO v_template USING v_row;
    END IF;
    IF TG_ARGV[9] <> '' THEN
        EXECUTE 'SELECT ' || TG_ARGV[9] INTO v_mentions USING v_row;
    END IF;

    PERFORM {WRITE_FUNCTION}(
        TG_TABLE_SCHEMA, TG_ARGV[1], v_entity, v_initiative,
        v_dac_tool, v_dac_id, v_title, v_body,
        v_archived, v_template, v_mentions
    );
    RETURN NULL;
END
$search$;
"""


def _dac_exprs(source: SearchSource) -> tuple[str, str]:
    """The ``(tool, id)`` expressions naming a row's sharing gate, or empty
    strings where the source has none."""
    if source.dac_sql is not None:
        return source.dac_sql(ROW)
    if source.dac_tool is None:
        return "", ""
    dac_id = f"{ROW}.{source.dac_id}" if source.dac_id else f"{ROW}.id"
    return f"'{source.dac_tool.kind}'::text", dac_id


DEPENDENT_FUNCTION = "public.refresh_search_dependents"

#: Rewrites the entries of rows that moved because a column on ANOTHER table
#: changed. The statement is rendered per dependency and passed whole, so a row
#: rewritten here goes through the same expressions as one rewritten by its own
#: trigger or by the sweep.
DEPENDENT_FUNCTION_SQL = f"""
CREATE OR REPLACE FUNCTION {DEPENDENT_FUNCTION}() RETURNS trigger
    LANGUAGE plpgsql AS $dep$
BEGIN
    EXECUTE TG_ARGV[0] USING TG_TABLE_SCHEMA, NEW.id;
    RETURN NULL;
END
$dep$;
"""


def _live_clause(table: Table, row: str) -> str:
    """Restricts to rows that have an entry at all.

    Trash is browsed through the trash surface, not found by searching; a row
    whose publication has not happened yet is a draft, which the people it is
    destined for must not be able to find; held content reads as absent; and a
    tombstone has no words left to find. Each mirrors the same test in the
    trigger function, so the sweep and the triggers index the same set.
    """
    columns = table.columns
    parts = []
    if "deleted_at" in columns:
        parts.append(f" AND {row}.deleted_at IS NULL")
    if "published_at" in columns:
        parts.append(f" AND {row}.published_at IS NOT NULL")
    if "held_at" in columns:
        parts.append(f" AND {row}.held_at IS NULL")
    if "removed_at" in columns:
        parts.append(f" AND {row}.removed_at IS NULL")
    return "".join(parts)


def _write_call(
    tools: ToolSet, name: str, source: SearchSource, row: str, schema: str
) -> str:
    """The ``search_entry_write`` call for one row of a source, as SQL.

    The sweep and the dependency triggers both go through this, so a row
    rewritten by either is written identically.
    """
    table = tools.tables[name]
    dac_tool_expr, dac_id_expr = _dac_exprs(source)
    dac_tool = dac_tool_expr.replace(ROW, row) if dac_tool_expr else "NULL::text"
    dac_id = (
        f"({dac_id_expr.replace(ROW, row)})::integer"
        if dac_id_expr
        else "NULL::integer"
    )
    body = _body_expr(source, row) or "''"
    archived = _archived_expr(table, source, row, tools.tables) or "false"
    template = _flag_expr(table, "template", row) or "false"
    mentions = _mentions_expr(table, source, row) or "NULL::text[]"
    return (
        f"{WRITE_FUNCTION}({schema}, '{source.entity_type}', {row}.id,"
        f" ({initiative_locator(name, paths_for(tools))(row)})::integer,"
        f" {dac_tool}, {dac_id}, {_title_expr(source, row)}, {body},"
        f" {archived}, {template}, {mentions})"
    )


def _rewrite_trigger(
    tools: ToolSet,
    trigger: str,
    name: str,
    source: SearchSource,
    on: str,
    column: str,
    rows: str,
) -> str:
    """DDL for a trigger on ``on`` that rewrites the entries of the ``name``
    rows ``rows`` selects whenever ``column`` changes there.

    ``$1`` is the guild schema and ``$2`` the id of the row that changed. The
    dependent table is named unqualified, as every other rendered expression is:
    the trigger runs with its own schema first on the search path.
    """
    row = "t"
    statement = (
        f"SELECT {_write_call(tools, name, source, row, '$1')}"
        f" FROM {name} {row}"
        f" WHERE {rows.format(row=row)}{_live_clause(tools.tables[name], row)}"
    )
    return "\n".join(
        [
            f"DROP TRIGGER IF EXISTS {trigger} ON {on};",
            f"CREATE TRIGGER {trigger}",
            f"  AFTER UPDATE ON {on}",
            f"  FOR EACH ROW WHEN (OLD.{column} IS DISTINCT FROM NEW.{column})",
            f"  EXECUTE FUNCTION {DEPENDENT_FUNCTION}({_quoted(statement)});",
        ]
    )


def _dependency_block(
    tools: ToolSet, name: str, source: SearchSource, dependency: SearchDependency
) -> str:
    """The trigger that rewrites entries when a row moves under them."""
    return _rewrite_trigger(
        tools,
        source.trigger(f"from_{dependency.table}"),
        name,
        source,
        dependency.table,
        dependency.column,
        dependency.rows_under("{row}"),
    )


def _archive_block(
    tools: ToolSet, name: str, source: SearchSource, parent: ArchiveParent
) -> str:
    """The trigger that rewrites entries when what they sit under is archived
    or brought back."""
    return _rewrite_trigger(
        tools,
        source.trigger(f"archived_by_{parent.label}"),
        name,
        source,
        parent.table,
        "archived_at",
        parent.rows_under("{row}"),
    )


def _call_args(tools: ToolSet, name: str, source: SearchSource) -> list[str]:
    """The ten trigger arguments, shared by both triggers on a table.

    An argument is the empty string where the source has nothing to say — no
    body, no sharing gate, no flag column, nobody it could mention — and the
    function skips it.
    """
    table = tools.tables[name]
    locator = initiative_locator(name, paths_for(tools))
    dac_tool, dac_id = _dac_exprs(source)
    return [
        f"    {_quoted(locator(ROW))},",
        f"    '{source.entity_type}',",
        f"    {_quoted(f'{ROW}.id')},",
        f"    {_quoted(_title_expr(source))},",
        f"    {_quoted(_body_expr(source))},",
        f"    {_quoted(dac_tool)},",
        f"    {_quoted(dac_id)},",
        f"    {_quoted(_archived_expr(table, source, ROW, tools.tables) or '')},",
        f"    {_quoted(_flag_expr(table, 'template', ROW) or '')},",
        f"    {_quoted(_mentions_expr(table, source))}",
    ]


def _trigger_block(tools: ToolSet, name: str, source: SearchSource) -> str:
    """DDL installing the two refresh triggers on one source table.

    Split by operation because the UPDATE one carries a ``WHEN`` clause naming
    ``OLD``, which is invalid on INSERT. That clause is the point: an update
    touching none of the indexed columns never enters the function.
    """
    args = _call_args(tools, name, source)
    ins, upd = source.trigger("ins"), source.trigger("upd")
    lines = [
        f"DROP TRIGGER IF EXISTS {source.trigger_name} ON {name};",
        f"DROP TRIGGER IF EXISTS {ins} ON {name};",
        f"CREATE TRIGGER {ins}",
        f"  AFTER INSERT OR DELETE ON {name}",
        f"  FOR EACH ROW EXECUTE FUNCTION {SEARCH_FUNCTION}(",
        *args,
        "  );",
        "",
        f"DROP TRIGGER IF EXISTS {upd} ON {name};",
        f"CREATE TRIGGER {upd}",
        f"  AFTER UPDATE ON {name}",
        f"  FOR EACH ROW WHEN ({_when_clause(tools.tables[name], source)})",
        f"  EXECUTE FUNCTION {SEARCH_FUNCTION}(",
        *args,
        "  );",
    ]
    return "\n".join(lines)


_HEADER = """\
-- ============================================================================
-- SEARCH INDEX — GENERATED, DO NOT EDIT BY HAND
-- RENDERED AT RUNTIME from app/db/search_index.py.
--
-- One trigger per searchable content table, all calling
-- public.refresh_search_entry(). Per-table knowledge is passed as trigger
-- arguments derived from SEARCH_SOURCES (title, body, sharing) and
-- INITIATIVE_PATHS (which initiative a row belongs to), so a new searchable
-- table is indexed without a second declaration.
-- ============================================================================"""


SEARCH_INDEX = "ix_search_entries_tsv"


def _index_block(opclass: str | None) -> str:
    """DDL asserting the index is built on ``opclass``, rebuilding only if not.

    Rendered here rather than left to the reflected structure DDL, which emits
    ``CREATE INDEX IF NOT EXISTS`` and so would keep whichever index a schema
    already has. Because the rendered text names the operator class, installing
    or removing it changes the provisioning stamp, and the next boot re-asserts
    the index for every guild.
    """
    marker = opclass.split(".")[-1] if opclass else ""
    using = f"gin (tsv {opclass})" if opclass else "gin (tsv)"
    # With a class: rebuild unless already on it. Without: rebuild if it is on
    # one, so removing the objects leaves a usable index behind.
    condition = (
        f"current_def IS NULL OR position('{marker}' in current_def) = 0"
        if marker
        else "current_def IS NULL OR position('_search_ops' in current_def) > 0"
    )
    return (
        "DO $$\n"
        "DECLARE current_def text;\n"
        "BEGIN\n"
        "    SELECT indexdef INTO current_def FROM pg_indexes\n"
        f"     WHERE schemaname = current_schema() AND indexname = '{SEARCH_INDEX}';\n"
        f"    IF {condition} THEN\n"
        f"        EXECUTE 'DROP INDEX IF EXISTS {SEARCH_INDEX}';\n"
        f"        EXECUTE 'CREATE INDEX {SEARCH_INDEX} ON search_entries "
        f"USING {using}';\n"
        "    END IF;\n"
        "END\n"
        "$$;"
    )


def render_guild_search_ddl(opclass: str | None, tools: ToolSet) -> str:
    """Per-table trigger DDL plus the index, applied inside each guild schema.

    ``opclass`` is the operator class the index is built on, or ``None`` for the
    stock one.
    """
    sources = sorted(search_sources(tools).items())
    blocks = [_trigger_block(tools, name, source) for name, source in sources]
    blocks.extend(
        _dependency_block(tools, name, source, dependency)
        for name, source in sources
        for dependency in source.depends_on
    )
    blocks.extend(
        _archive_block(tools, name, source, parent)
        for name, source in sources
        for parent in archive_parents(tools.tables[name], source, tools.tables)
    )
    blocks.append(_index_block(opclass))
    return _HEADER + "\n\n" + "\n\n".join(blocks) + "\n"


def search_generation(tools: ToolSet = BUILTIN_TOOLS) -> str:
    """Digest of WHAT a community with ``tools`` indexes and HOW, for deciding
    when to reindex it.

    Covers the per-source declarations and the chunking rules, so adding a
    source or changing an extraction re-sweeps, and a community's tool
    plug-ins' sources move its own generation alone. Deliberately excludes the
    index definition: swapping the operator class rebuilds the index, which
    does not change a single stored row.
    """
    digest = hashlib.sha256()
    for name, source in sorted(search_sources(tools).items()):
        digest.update(_trigger_block(tools, name, source).encode())
    digest.update(WRITE_FUNCTION_SQL.encode())
    return f"search:{digest.hexdigest()[:16]}"


def _reindex_statement(tools: ToolSet, name: str, source: SearchSource) -> str:
    """One batch of a source table's rows, re-written through the same function
    the trigger uses.

    ``:schema`` names the guild schema, ``:cursor`` is the last id of the
    previous batch and ``:batch`` its size — so a large table is walked in
    bounded transactions rather than one.
    """
    row = "t"
    return (
        f"SELECT {row}.id AS id,"
        f" {_write_call(tools, name, source, row, ':schema')}"
        f" FROM {name} {row}"
        f" WHERE {row}.id > :cursor{_live_clause(tools.tables[name], row)}"
        f" ORDER BY {row}.id LIMIT :batch"
        # Locks each row for the duration of the write, so the values written
        # are the row's current ones: a concurrent write to the same row
        # finishes first and this sees its result, rather than replacing it
        # with what the batch read a moment earlier.
        " FOR UPDATE"
    )


def reindex_plan(tools: ToolSet = BUILTIN_TOOLS) -> list[tuple[str, str]]:
    """``(entity_type, statement)`` for every source indexed in a community
    with ``tools``, in a stable order."""
    return [
        (source.entity_type, _reindex_statement(tools, name, source))
        for name, source in sorted(search_sources(tools).items())
    ]
