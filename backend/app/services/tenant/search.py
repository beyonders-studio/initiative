"""Reading the guild search index.

``search_entries`` carries the same ``initiative_member_*`` policies as the
content tables it mirrors, per-resource sharing included: its read policy asks
``resource_access`` of the tool each entry names. So a query here states only
what it is looking for, and the database decides what the reader may see.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace

from sqlalchemy import (
    Select,
    String,
    Text,
    cast,
    false,
    func,
    literal,
    not_,
    select,
    text,
    union,
)
from sqlalchemy.dialects.postgresql import TSQUERY
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from app.core.errors import CodedError
from app.core.messages import PluginMessages
from app.core.plugin_scopes import tool_resource
from app.core.search import SearchEntityType
from app.core.tools import Tool
from app.db.authorization import standing_arg
from app.db.guild_standing import ActorContext, InstallContext
from app.db.plugin_rls import SEARCH_ENTRY_READ_SCOPE
from app.db.query import build_paginated_response
from app.db.schema_provisioning import search_operator_available
from app.db.search_index import MENTION_LEXEME, entity_types
from app.models.platform.user_profile_view import GuildMember
from app.models.tenant.engagement_level import EngagementLevel
from app.models.tenant.initiative import Initiative
from app.models.tenant.search_entry import SearchEntry
from app.schemas.tenant.search import SearchHit, SearchResults, SearchSuggestion
from app.services.tenant.engagement_levels import boosted, level_of


def writable_column(user_id: int | None, *, install: InstallContext | None = None):
    """Whether this request may CHANGE the row, not just see it.

    The same ``resource_access`` call the gate makes, asked at write
    level and selected rather than filtered on. A picker needs it because not
    every link is the anchor's to make: a relation that describes its source is
    the source's to assert, so offering "this blocks that" for a thing somebody
    can only read is offering something the server must refuse.

    An installed plug-in also needs the write scope of the row's kind and of the
    tool governing it, as the tool's own routes ask.

    One more call per row, on rows the gate has already narrowed to a page.
    """
    # Coalesced to false: a row with no sharing gate of its own — the guild's
    # tags — answers NULL, and "it did not say" is not a reason to offer
    # somebody an action. Nothing here asks a tag to be the source of a link
    # anyway; that is what the tag picker is for.
    writable = func.coalesce(
        func.resource_access(
            SearchEntry.dac_tool,
            SearchEntry.dac_id,
            user_id,
            SearchEntry.initiative_id,
            True,
            standing_arg(),
        ),
        False,
    )
    if install is not None:
        writable = (
            writable
            & SearchEntry.entity_type.in_(
                [
                    kind.value
                    for kind, resource in SEARCH_ENTRY_READ_SCOPE.items()
                    if resource.value in install.install_write
                ]
            )
            & SearchEntry.dac_tool.in_(
                [
                    tool.value
                    for tool in Tool
                    if tool_resource(tool).value in install.install_write
                ]
            )
        )
    return writable.label("can_write")


class SearchScopeError(CodedError):
    """An installed plug-in asked for kinds its scopes do not let it read.

    Carries the message code the endpoint answers with.
    """

    status_code = 403


def install_entity_types(
    install: InstallContext, types: Sequence[SearchEntityType] | None
) -> tuple[SearchEntityType, ...]:
    """The kinds an installed plug-in's search reaches: those asked for (the
    default scope when none are) whose read scope it holds, per
    ``SEARCH_ENTRY_READ_SCOPE``. Writing implies reading.

    Raises :class:`SearchScopeError` when that leaves none, so a plug-in asking
    only for kinds it cannot read is told so rather than answered with nothing.
    """
    asked = tuple(types) if types else entity_types(default_scope_only=True)
    readable = tuple(
        kind
        for kind in asked
        if (resource := SEARCH_ENTRY_READ_SCOPE.get(kind)) is not None
        and install.holds(f"{resource.value}:read")
    )
    if not readable:
        raise SearchScopeError(PluginMessages.SCOPE_REQUIRED)
    return readable


def search_match_clause(tsquery: ColumnElement) -> ColumnElement[bool]:
    """The text-match predicate, using whichever operator this install can index.

    ``public.@@@`` where ``app.db.bootstrap`` has installed it,
    the stock ``@@`` otherwise. Both return the same rows; only the first can
    use the index. Going through this one function is what keeps a query from
    quietly picking the other.
    """
    if search_operator_available():
        return SearchEntry.tsv.op("OPERATOR(public.@@@)", is_comparison=True)(tsquery)
    return SearchEntry.tsv.op("@@", is_comparison=True)(tsquery)


#: Widest page a caller may ask for.
MAX_PAGE_SIZE = 100
#: Jump-to results for the palette. Small on purpose: it is a way to reach one
#: thing, not a way to read a result set.
SUGGEST_LIMIT = 10

_HEADLINE_OPTIONS = "MaxFragments=2,MinWords=5,MaxWords=18,StartSel=<,StopSel=>"

#: How many close matches a failed search offers. It is a suggestion, not a
#: result set.
FUZZY_LIMIT = 5
#: How close a word has to be to be worth offering. Measured against the
#: closest RUN of the title rather than the whole of it: a title is a sentence
#: and the query is a word, so comparing them entire scores an exact match at
#: 0.14 and finds nothing. A typo of a real word lands around 0.5.
FUZZY_THRESHOLD = 0.4
#: The close-match read cannot be served from an index — its operator is not
#: leakproof, so under RLS it is a scan — and it only ever runs on a search that
#: already found nothing. Bounded here so a large community gives up rather
#: than making the reader wait for a suggestion.
FUZZY_TIMEOUT_MS = 250


#: A prefix scan widens as the prefix shortens, so the last word earns one only
#: once it is specific enough for that to be worth the reading.
MIN_PREFIX_CHARS = 3

#: What ``websearch_to_tsquery`` reads as syntax rather than as a word.
_WEBSEARCH_OPERATORS = frozenset({"or", "and"})


def _trailing_prefix(query: str) -> tuple[str, str | None]:
    """The query without its last word, and that word to match as a prefix.

    A results page searches as its reader types, so the last word is usually
    half-finished: someone who has got as far as ``thro`` means ``Throne``.
    Only a plain word qualifies — a quoted phrase, an exclusion or an operator
    is what the reader asked for exactly, and is left alone.
    """
    if query.count('"') % 2:
        # Mid-phrase: the quote that would close it has not been typed yet.
        return query, None
    head, _, last = query.rpartition(" ")
    if not last.isalnum() or len(last) < MIN_PREFIX_CHARS:
        return query, None
    if last.lower() in _WEBSEARCH_OPERATORS:
        return query, None
    return head, last


#: A quoted phrase, excluded or not, or anything else up to a space: the
#: terms ``websearch_to_tsquery`` reads.
_TERM = re.compile(r'-?"([^"]*)"|(\S+)')
#: A run of letters and digits, as the ``simple`` parser reads a word.
_WORD = re.compile(r"[^\W_]+")


def _term(word: str) -> str | None:
    """A word as a term that could name somebody: without an exclusion's ``-``
    or a stray quote, and ``None`` for an operator or a word holding no
    letters or digits."""
    term = word.lstrip("-").strip('"')
    if term.lower() in _WEBSEARCH_OPERATORS or not _WORD.search(term):
        return None
    return term


def _typed_terms(query: str) -> list[str]:
    """What was typed, as terms each parsing alone to the subtree it parses to
    within the whole: a quoted phrase with its quotes, and every other word as
    :func:`_term` reads it."""
    terms = []
    for phrase, word in _TERM.findall(query):
        term = f'"{phrase}"' if _WORD.search(phrase) else _term(word)
        if term is not None:
            terms.append(term)
    return terms


def _people_named(term: str) -> ColumnElement:
    """Mentions of every member ``term`` names, as one tsquery, or NULL where it
    names nobody.

    A term names a member when its whole words are words of their name in this
    community or of their handle as it is shown (``jordan#0042``), as the term
    would match those written in text. Whole words, never a prefix: three
    letters typed would otherwise name everyone whose name starts with them.
    The members are the routed community's own, and only those.
    """
    from app.services.platform.users import visible_to_other_people

    handle = func.concat(
        GuildMember.username,
        "#",
        func.lpad(cast(GuildMember.discriminator, String), 4, "0"),
    )
    names = func.concat_ws(" ", GuildMember.display_name, handle)
    # A name holding the term holds each of its words, so testing one as a
    # substring first leaves only those few names to parse.
    word = max(_WORD.findall(term), key=len)
    return cast(
        select(
            func.string_agg(
                func.quote_literal(MENTION_LEXEME + cast(GuildMember.id, String)),
                " | ",
            )
        )
        .where(
            visible_to_other_people(GuildMember.status),
            names.ilike(f"%{word}%"),
            func.to_tsvector("simple", names).op("@@")(
                func.websearch_to_tsquery("simple", term)
            ),
        )
        .scalar_subquery(),
        TSQUERY,
    )


def _with_people(parsed, targets: Iterable[tuple[ColumnElement, str]]):
    """``parsed`` with each target also matching a mention of anybody its term
    names.

    A target is the subtree of ``parsed`` one typed term became, beside that
    term as typed, which is what names a person: a handle such as
    ``brave-otter`` parses to a phrase of its parts, and a word matched as a
    prefix names whoever it names whole. Applied to the parsed query rather
    than to the text, so a phrase, an ``or`` and an exclusion keep what they
    meant: ``-ada`` leaves out a mention of Ada as well as the word.

    A term of more words goes first: rewriting ``ada`` would change the
    ``"ada countess"`` around it, which would then not be found as itself.
    """
    for target, term in sorted(targets, key=lambda t: -len(_WORD.findall(t[1]))):
        mentioned = target.op("||", return_type=TSQUERY)(_people_named(term))
        parsed = func.ts_rewrite(
            parsed, target, func.coalesce(mentioned, target), type_=TSQUERY
        )
    return parsed


def _tsquery(query: str):
    """The parsed query. ``websearch_to_tsquery`` takes what a person types —
    bare words, "quoted phrases", ``or``, ``-excluded`` — and never raises on
    input it cannot make sense of.

    Its one gap is that it matches whole words, which reads as nothing being
    found while a word is still being typed. So a bare last word is matched as a
    prefix and ANDed onto the rest, which keeps every bit of the syntax above
    and answers as the reader types.

    A word naming a member also finds what mentions them (:func:`_with_people`).
    """
    head, prefix = _trailing_prefix(query)
    if prefix is None:
        parsed = func.websearch_to_tsquery("simple", query)
    else:
        # `prefix` is alphanumeric, so it reaches `to_tsquery` as a word and
        # never as syntax.
        parsed = func.to_tsquery("simple", f"{prefix}:*")
        if head.strip():
            parsed = func.websearch_to_tsquery("simple", head).op("&&")(parsed)
    # Each term parsed alone by the function that parsed the whole gives the
    # subtree it became there.
    targets = [
        (func.websearch_to_tsquery("simple", term), term)
        for term in dict.fromkeys(_typed_terms(head))
    ]
    if prefix is not None:
        targets.append((func.to_tsquery("simple", f"{prefix}:*"), prefix))
    return _with_people(parsed, targets)


@dataclass(frozen=True)
class Filters:
    """What a caller narrows to, beyond the words themselves.

    Every field only ever removes rows, so narrowing can never reach content
    the gates would not have allowed.

    ``template`` is three-valued on purpose: unset means both, so a results
    page still finds a template by name; a picker choosing where content goes
    asks for ``False``; a template picker asks for ``True``.
    """

    types: Sequence[SearchEntityType] | None = None
    initiative_id: int | None = None
    #: Archived work is indexed and left out unless it is asked for.
    include_archived: bool = False
    template: bool | None = None
    #: The thing being written in, which a reference may not name — see
    #: :meth:`clause`. A results page has no subject and leaves this unset.
    subject: tuple[SearchEntityType, int] | None = None

    @property
    def entity_types(self) -> tuple[SearchEntityType, ...]:
        """The types to search — the default scope when none were named."""
        return (
            tuple(self.types) if self.types else entity_types(default_scope_only=True)
        )

    def clause(self) -> ColumnElement[bool]:
        """This narrowing as a predicate."""
        clause: ColumnElement[bool] = SearchEntry.entity_type.in_(self.entity_types)
        if self.initiative_id is not None:
            clause = clause & (SearchEntry.initiative_id == self.initiative_id)
        if not self.include_archived:
            clause = clause & SearchEntry.archived.is_(False)
        if self.template is not None:
            clause = clause & SearchEntry.template.is_(self.template)
        if self.subject is not None:
            # A thing does not point at itself: the page a reference would open
            # is the page it was written on. Removed here rather than by the
            # caller so it comes off before ``limit``, and a picker that asks
            # for five rows is offered five.
            subject_type, subject_id = self.subject
            clause = clause & not_(
                (SearchEntry.entity_type == subject_type)
                & (SearchEntry.entity_id == subject_id)
            )
        return clause


def _best_chunk(clause: ColumnElement[bool], parsed) -> Select:
    """One row per entity — the chunk that matched best.

    Long text is split across rows, so a file can match several times. The
    highest-ranked chunk is the one worth showing, and is what supplies the
    snippet — drawn by :func:`search` for the rows on the page alone, since a
    headline re-reads the whole chunk.
    """
    rank = func.ts_rank_cd(SearchEntry.tsv, parsed).label("rank")
    return (
        select(
            SearchEntry.entity_type,
            SearchEntry.entity_id,
            SearchEntry.initiative_id,
            SearchEntry.dac_tool.label("tool"),
            SearchEntry.dac_id.label("tool_id"),
            SearchEntry.title,
            SearchEntry.chunk_ix,
            SearchEntry.updated_at,
            rank,
        )
        .where(clause)
        .distinct(SearchEntry.entity_type, SearchEntry.entity_id)
        .order_by(SearchEntry.entity_type, SearchEntry.entity_id, rank.desc())
        .subquery()
    )


async def _close_titles(
    session: AsyncSession, *, query: str, filters: Filters
) -> list[SearchHit]:
    """Entities whose TITLE is close to what was typed, for when nothing matched.

    This answers the typo — ``comunity`` finding Community — which whole-word
    matching cannot. Titles only, one row per entity, and never blended into a
    search that worked: a reader is shown these as close matches, not told they
    are what was asked for.
    """
    closeness = func.word_similarity(query, SearchEntry.title)
    clause = (
        (closeness >= FUZZY_THRESHOLD) & (SearchEntry.chunk_ix == 0) & filters.clause()
    )

    statement = (
        select(
            SearchEntry.entity_type,
            SearchEntry.entity_id,
            SearchEntry.initiative_id,
            SearchEntry.dac_tool.label("tool"),
            SearchEntry.dac_id.label("tool_id"),
            SearchEntry.title,
        )
        .where(clause)
        .order_by(closeness.desc(), SearchEntry.entity_type, SearchEntry.entity_id)
        .limit(FUZZY_LIMIT)
    )
    try:
        # A savepoint, so giving up leaves the request's transaction usable.
        async with session.begin_nested():
            # ``set_config`` rather than ``SET LOCAL``: the latter takes no
            # bind parameter, so the value would have to be built into the
            # statement. Third argument true makes it transaction-local, which
            # is what ``SET LOCAL`` meant here.
            await session.exec(
                text(
                    "SELECT set_config('statement_timeout', :timeout, true)"
                ).bindparams(timeout=f"{FUZZY_TIMEOUT_MS}ms")
            )
            rows = (await session.exec(statement)).all()
    except SQLAlchemyError:
        # Gave up. The reader gets the empty page they already had.
        return []
    finally:
        # A transaction-local setting outlives the savepoint when it commits,
        # so it is put back rather than left on the rest of the request.
        await session.exec(text("SET LOCAL statement_timeout = DEFAULT"))
    return [SearchHit.model_validate(row, from_attributes=True) for row in rows]


async def search(
    session: AsyncSession,
    *,
    query: str,
    filters: Filters = Filters(),
    page: int = 1,
    page_size: int = 20,
) -> SearchResults:
    """Ranked matches across the guild, newest first among equals. A match's
    rank is lifted by its engagement level (:func:`boosted`).

    ``total`` counts entities, not chunks, and is exact: every gate is a
    predicate in this one statement, so there is nothing to filter afterwards.
    """
    page = max(1, page)
    page_size = max(1, min(page_size, MAX_PAGE_SIZE))
    if not query.strip():
        return SearchResults(**build_paginated_response([], 0, page, page_size))

    # Parsed once, by itself: the people its words name are looked up there,
    # not again by each clause below that matches, ranks or quotes with it.
    parsed = cast(
        literal(await session.scalar(select(cast(_tsquery(query), Text)))), TSQUERY
    )
    chunks = _best_chunk(search_match_clause(parsed) & filters.clause(), parsed)
    total = await session.scalar(select(func.count()).select_from(chunks)) or 0
    # Each match beside its engagement level, read once it has matched.
    best = select(
        chunks, level_of(chunks.c.entity_type, chunks.c.entity_id).label("level")
    ).subquery()

    def ranked(rows) -> tuple:
        # entity_type/entity_id last: rank and timestamp both tie, and an order
        # that is not total lets a row repeat on one page and vanish from the
        # next.
        return (
            boosted(rows.c.rank, rows.c.level).desc(),
            rows.c.updated_at.desc(),
            rows.c.entity_type,
            rows.c.entity_id,
        )

    window = (
        select(best)
        .order_by(*ranked(best))
        .limit(page_size)
        .offset((page - 1) * page_size)
        .subquery()
    )
    # The snippet is drawn from the chunk each row on the page chose, read back
    # by its key, so the bodies of the rows the ranking passed over are never
    # read.
    chunk = aliased(SearchEntry, name="chunk")
    rows = (
        await session.exec(
            select(
                *(column for column in window.c if column.key != "chunk_ix"),
                func.ts_headline("simple", chunk.body, parsed, _HEADLINE_OPTIONS).label(
                    "snippet"
                ),
            )
            .select_from(window)
            .join(
                chunk,
                (chunk.entity_type == window.c.entity_type)
                & (chunk.entity_id == window.c.entity_id)
                & (chunk.chunk_ix == window.c.chunk_ix),
            )
            # Re-stated outside the page: a subquery's ordering is not something
            # the query around it inherits.
            .order_by(*ranked(window))
        )
    ).all()
    if not rows and page == 1:
        # Nothing matched what was typed. Offer what is closest to it rather
        # than an empty page — flagged, so the reader is told which they got.
        close = await _close_titles(session, query=query, filters=filters)
        if close:
            return SearchResults(
                **build_paginated_response(close, len(close), page, page_size),
                fuzzy=True,
            )

    return SearchResults(
        **build_paginated_response(
            [SearchHit.model_validate(r, from_attributes=True) for r in rows],
            total,
            page,
            page_size,
        )
    )


#: The columns a picker row is built from, before it is told where it lives.
def _suggestion_columns(
    user_id: int | None, *, install: InstallContext | None = None
) -> tuple:
    return (
        SearchEntry.entity_type,
        SearchEntry.entity_id,
        SearchEntry.initiative_id,
        SearchEntry.dac_tool.label("tool"),
        SearchEntry.dac_id.label("tool_id"),
        SearchEntry.title,
        writable_column(user_id, install=install),
    )


def _with_context(rows: Select) -> Select:
    """The same rows, each told what it lives in.

    A title on its own identifies nothing: six projects run from one template
    hold six tasks called "Do a thing", and a picker offering all six offers a
    choice nobody can make. So every row carries the name of the thing it is
    addressed inside and the initiative it sits in.

    The container is looked up in the index itself — the row governing a task
    IS its project's row — so nothing here has to learn a second time which
    table holds which parent. It is left-joined, and skipped for a row that
    governs itself: a project does not live in a project.

    Wrapped around a finished, ordered, limited query rather than joined into
    it, because the container is only ever read for the handful of rows
    somebody is shown — probing for it before the LIMIT would pay for every
    candidate the ranking threw away.
    """
    inner = rows.subquery()
    container = aliased(SearchEntry, name="container")
    return (
        select(
            *inner.c,
            container.title.label("tool_title"),
            Initiative.name.label("initiative_name"),
        )
        .select_from(inner)
        .join(
            container,
            (container.entity_type == inner.c.tool)
            & (container.entity_id == inner.c.tool_id)
            & (container.chunk_ix == 0)
            & not_(
                (container.entity_type == inner.c.entity_type)
                & (container.entity_id == inner.c.entity_id)
            ),
            isouter=True,
        )
        .join(Initiative, Initiative.id == inner.c.initiative_id, isouter=True)
    )


async def suggest(
    session: AsyncSession,
    *,
    query: str,
    user_id: int | None,
    filters: Filters = Filters(),
    limit: int = SUGGEST_LIMIT,
    install: InstallContext | None = None,
) -> list[SearchSuggestion]:
    """Titles to jump to. No snippets and no body ranking — this answers "take
    me to the thing I am naming", which is a different question from search.

    An installed plug-in (``install``, with ``user_id`` None) is answered only the
    kinds its scopes let it read (:func:`install_entity_types`), and the
    index's policies hold each entry to what the plug-in could read through the
    tool the entry describes. A member token's sharing is asked for the member
    it acts for, as its policies ask it.
    """
    limit = max(1, min(limit, SUGGEST_LIMIT))
    if install is not None:
        filters = replace(filters, types=install_entity_types(install, filters.types))
        user_id = install.member_user_id
    if not query.strip():
        return []
    parsed = prefix_tsquery(query)
    if parsed is None:
        return []
    # The stored vector carries title AND body, so it narrows through the index
    # but would also offer a row whose title shows nothing of what was typed.
    # Rechecking the title alone keeps the palette's answers legible; it runs on
    # what the index already narrowed to.
    title_match = func.to_tsvector("simple", SearchEntry.title).op(
        "@@", is_comparison=True
    )(parsed)
    clause = search_match_clause(parsed) & title_match & filters.clause()
    rank = func.ts_rank_cd(SearchEntry.tsv, parsed)
    # A plug-in reads no levels, so its answers are ordered by the match alone.
    level = (
        literal(0)
        if install is not None
        else level_of(SearchEntry.entity_type, SearchEntry.entity_id)
    )
    ranked = (
        select(
            *_suggestion_columns(user_id, install=install),
            rank.label("rank"),
            level.label("level"),
            SearchEntry.updated_at,
        )
        .where(clause, SearchEntry.chunk_ix == 0)
        .order_by(
            boosted(rank, level).desc(),
            SearchEntry.updated_at.desc(),
            SearchEntry.entity_type,
            SearchEntry.entity_id,
        )
        .limit(limit)
    )
    described = _with_context(ranked)
    rows = (
        await session.exec(
            # Re-stated outside the wrap: a subquery's ordering is not something
            # the query around it inherits.
            described.order_by(
                boosted(
                    described.selected_columns.rank,
                    described.selected_columns.level,
                ).desc(),
                described.selected_columns.updated_at.desc(),
                described.selected_columns.entity_type,
                described.selected_columns.entity_id,
            )
        )
    ).all()
    return [SearchSuggestion.model_validate(r, from_attributes=True) for r in rows]


async def recent(
    session: AsyncSession,
    *,
    user_id: int,
    filters: Filters = Filters(),
    limit: int = SUGGEST_LIMIT,
) -> list[SearchSuggestion]:
    """The things most recently changed that a picker could offer.

    What a picker shows before anything is typed. :func:`suggest` answers "take
    me to the thing I am naming"; this answers "what might I be naming", which
    is the same question a person is asking when they open a picker and have
    not yet decided.

    Deliberately the same rows, filters and gate as :func:`suggest` — only the
    ordering differs — so a picker cannot offer something its own search would
    refuse to find. What more people engaged with lately comes first, then the
    newest.

    The candidates are the newest rows and the highest levels, each limited:
    the levels are read highest first through their own index, so a picker
    stops at its limit rather than reading a level for every row.
    """
    limit = max(1, min(limit, SUGGEST_LIMIT))
    # One row per thing: the index holds a row per body chunk as well.
    rows_here = select(*_suggestion_columns(user_id), SearchEntry.updated_at).where(
        filters.clause(), SearchEntry.chunk_ix == 0
    )
    order = (
        SearchEntry.updated_at.desc(),
        SearchEntry.entity_type,
        SearchEntry.entity_id,
    )
    newest = rows_here.order_by(*order).limit(limit).subquery()
    engaged = (
        rows_here.join(
            EngagementLevel,
            (EngagementLevel.entity_type == SearchEntry.entity_type)
            & (EngagementLevel.entity_id == SearchEntry.entity_id),
        )
        .order_by(
            EngagementLevel.level.desc(),
            EngagementLevel.entity_type.desc(),
            EngagementLevel.entity_id.desc(),  # type: ignore[attr-defined]
        )
        .limit(limit)
        .subquery()
    )
    candidates = union(select(newest), select(engaged)).subquery()
    level = level_of(candidates.c.entity_type, candidates.c.entity_id)
    chosen = (
        select(candidates, level.label("level"))
        .order_by(
            level.desc(),
            candidates.c.updated_at.desc(),
            candidates.c.entity_type,
            candidates.c.entity_id,
        )
        .limit(limit)
    )
    described = _with_context(chosen)
    rows = (
        await session.exec(
            described.order_by(
                described.selected_columns.level.desc(),
                described.selected_columns.updated_at.desc(),
                described.selected_columns.entity_type,
                described.selected_columns.entity_id,
            )
        )
    ).all()
    return [SearchSuggestion.model_validate(r, from_attributes=True) for r in rows]


def prefix_tsquery(text: str):
    """A query whose last word matches as a prefix, or ``None`` for no terms.

    What a filter box needs: someone typing ``ven`` should see ``vendor``
    before they finish the word. ``websearch_to_tsquery`` matches whole words
    only, which is right for a results page and wrong for type-ahead.

    Tokens are reduced to alphanumerics, so nothing a person types reaches
    ``to_tsquery`` as syntax.
    """
    tokens = _prefix_tokens(text)
    if not tokens:
        return None
    return func.to_tsquery("simple", " & ".join(tokens))


def _prefix_tokens(text: str) -> list[str]:
    """Each word of ``text`` as :func:`prefix_tsquery` matches it: its letters
    and digits, the last one as a prefix."""
    tokens = ["".join(c for c in part if c.isalnum()) for part in text.split()]
    tokens = [t for t in tokens if t]
    return [*tokens[:-1], f"{tokens[-1]}:*"] if tokens else []


def tool_search_clause(
    tool: Tool,
    id_col: ColumnElement[int],
    search: str | None,
    context: ActorContext,
) -> ColumnElement[bool] | None:
    """Narrow a tool's list to rows whose indexed text matches ``search``.

    The same index the search page reads, so a tool's filter box and the search
    page agree about what matches — and it reaches a description, not just a
    name, and what mentions a member the words name. An installed plug-in finds a
    mention by a name only when it may read names (``members:read``). ``None``
    when there is nothing to search for, so a caller appends it conditionally.

    The subquery reads ``search_entries``, which is gated by its own policies;
    the caller's own access clause still applies to the rows it returns.
    """
    if not search or not search.strip():
        return None
    parsed = prefix_tsquery(search)
    if parsed is None:
        # Something was typed, but it holds no word to match — punctuation only.
        # Nothing matches it, which is a truer answer than the unfiltered list
        # a caller would read as "the filter was ignored".
        return false()
    if not isinstance(context, InstallContext) or context.holds("members:read"):
        # The same words, typed: ``brave-otter`` is matched as ``braveotter``
        # but names somebody as itself.
        typed = (part for part in search.split() if any(map(str.isalnum, part)))
        parsed = _with_people(
            parsed,
            (
                (func.to_tsquery("simple", token), term)
                for token, part in zip(_prefix_tokens(search), typed)
                if (term := _term(part)) is not None
            ),
        )
    return id_col.in_(
        select(SearchEntry.entity_id).where(
            SearchEntry.entity_type == tool.value,
            search_match_clause(parsed),
        )
    )
