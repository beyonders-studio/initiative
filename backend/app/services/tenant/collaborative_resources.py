"""What can be edited by several people at once, and how each one is reached.

A collaboration room is a Yjs document plus the row it is a body of. Which row
that is differs — a file's body is its own, a wiki page's body is the
page's while the *sharing* belongs to the wiki it sits in — and that difference
is the whole of what varies between them.

So it is declared once here, per kind, and the room, the socket and the
persistence sweep all read it rather than each knowing about files:

``entity_type``
    The room's ``resource_type`` in the stream register, and the reference kind
    the body's ``[[ ]]`` links are recorded against. One value, because they
    are the same fact.
``tool``
    Whose sharing decides who may open the socket.
``model`` / ``content_column``
    Where the JSON body lives. The Yjs columns are spelled the same on every
    collaborative table, so they are not restated.
``body_kind``
    Which editor a row's body is for, as a SQL expression: a file's type,
    or ``lexical`` for a page, which is always prose. The server makes the
    body's Yjs state and renders its content with that editor's mapping
    (:mod:`app.services.tenant.body_states`).
``load``
    Fetches the body row and the row whose grants govern it, with everything
    the DAC engine reads eager-loaded. Returns ``None`` when either is missing
    or belongs to another guild — which the socket treats as "not found",
    exactly as the REST path does.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from sqlalchemy import literal
from sqlalchemy.orm import selectinload, undefer
from sqlmodel import select

from app.core.file_types import FileType
from app.core.search import SearchEntityType
from app.core.tools import Tool, plural_of

#: Both columns are spelled the same on every collaborative table, so a new one
#: declares neither.
YJS_STATE_COLUMN = "yjs_state"
YJS_UPDATED_COLUMN = "yjs_updated_at"


@dataclass(frozen=True)
class Collaborating:
    """One resolved resource: the row holding the body, and the row that says
    who may read or write it. They are the same row for a file."""

    body: Any
    governing: Any
    initiative_id: Optional[int]


@dataclass(frozen=True)
class CollaborativeResource:
    entity_type: SearchEntityType
    tool: Tool
    model: type
    content_column: str
    load: Callable[..., Awaitable[Optional[Collaborating]]]
    body_kind: Callable[[], Any]
    #: A path parameter that differs from ``<kind>_id``.
    id_param: Optional[str] = None

    @property
    def resource_type(self) -> str:
        """The room key's middle term, and the stream register's."""
        return self.entity_type.value

    @property
    def route_segment(self) -> str:
        """The kebab plural its routes are served under (``wiki-pages``)."""
        return plural_of(self.resource_type).replace("_", "-")

    @property
    def path_param(self) -> str:
        """The path parameter a body is addressed by."""
        return self.id_param or f"{self.resource_type}_id"


async def _load_file(
    session: Any, resource_id: int, guild_id: int
) -> Optional[Collaborating]:
    from app.models.tenant.file import File

    statement = (
        select(File)
        .where(File.id == resource_id)
        .options(
            selectinload(File.initiative),
            undefer(File.actions),
            selectinload(File.grants),
        )
    )
    file = (await session.exec(statement)).one_or_none()
    if file is None:
        return None
    return Collaborating(body=file, governing=file, initiative_id=file.initiative_id)


async def _load_wiki_page(
    session: Any, resource_id: int, guild_id: int
) -> Optional[Collaborating]:
    """A page's body is its own; who may read or write it is the wiki's.

    That is the same rule the REST path applies — a page is the wiki's content
    — so the socket asks the same question of the same row.
    """
    from app.models.tenant.wiki import Wiki, WikiPage

    page = (
        await session.exec(select(WikiPage).where(WikiPage.id == resource_id))
    ).one_or_none()
    if page is None:
        return None

    statement = (
        select(Wiki)
        .where(Wiki.id == page.wiki_id)
        .options(
            selectinload(Wiki.initiative),
            undefer(Wiki.actions),
            selectinload(Wiki.grants),
        )
    )
    wiki = (await session.exec(statement)).one_or_none()
    if wiki is None:
        return None
    return Collaborating(body=page, governing=wiki, initiative_id=wiki.initiative_id)


COLLABORATIVE_RESOURCES: dict[str, CollaborativeResource] = {}


def _register(resource: CollaborativeResource) -> CollaborativeResource:
    COLLABORATIVE_RESOURCES[resource.resource_type] = resource
    return resource


def _file_resource() -> CollaborativeResource:
    from app.models.tenant.file import File

    return CollaborativeResource(
        entity_type=SearchEntityType.file,
        tool=Tool.file,
        model=File,
        content_column="content",
        load=_load_file,
        body_kind=lambda: File.file_type,
    )


def _wiki_page_resource() -> CollaborativeResource:
    from app.models.tenant.wiki import WikiPage

    return CollaborativeResource(
        entity_type=SearchEntityType.wiki_page,
        tool=Tool.wiki,
        model=WikiPage,
        content_column="content",
        load=_load_wiki_page,
        body_kind=lambda: literal(FileType.lexical.value),
        # Every wiki page route names its row ``page_id``.
        id_param="page_id",
    )


def resource_for(resource_type: str) -> CollaborativeResource:
    """The declaration for one kind. Raises for a kind nothing registered,
    which is a wiring mistake rather than a request error."""
    if not COLLABORATIVE_RESOURCES:
        _register(_file_resource())
        _register(_wiki_page_resource())
    return COLLABORATIVE_RESOURCES[resource_type]


def registered_types() -> tuple[str, ...]:
    """Every collaborative kind: what the routes are mounted for, and what the
    tests walk."""
    resource_for(SearchEntityType.file.value)
    return tuple(sorted(COLLABORATIVE_RESOURCES))
