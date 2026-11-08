"""Mixins shared by guild-schema (tenant) tables only.

This module lives under ``app/models/tenant/`` on purpose: every mixin here is
part of the per-guild **content** lifecycle and is mixed into ``table=True``
models that live in a ``guild_<id>`` schema. **Platform/public tables never use
these** — trash/restore/purge is a guild-content concern, so there is no
table-less "shared by both" bucket at the models root. ``layout_test.py`` fails
CI if a ``SoftDeleteMixin`` subclass ever lands outside ``app/models/tenant/``.
"""

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, ClassVar

from sqlalchemy import (
    ARRAY,
    DateTime,
    Integer,
    String,
    func,
    literal_column,
    select,
)
from sqlalchemy.orm import column_property
from sqlmodel import Field, SQLModel

from app.db import gucs

if TYPE_CHECKING:  # pragma: no cover
    from app.core.tools import Tool


class ActorKind(StrEnum):
    """Who did something to a row: what its ``created_by`` (made it) or
    ``deleted_by`` (put it in the trash) names."""

    #: A person; the column is their user id.
    member = "member"
    #: An installed plug-in acting as its community; the column is the install
    #: (``guild_plugins.id``).
    plugin = "plugin"
    #: Initiative itself; the column is NULL.
    system = "system"


class SoftDeleteMixin(SQLModel):
    """Mixin that adds the trash-can lifecycle columns to a guild-scoped model.

    `_display_field` names the column that labels a row wherever the app shows
    a bare list of mixed entity types (the recents tab bar, the trash can).
    It defaults to `name`; only models that call it something else override it.

    ``deleted_by`` names who binned the row, with ``deleted_by_kind`` saying
    what it names, as ``created_by`` does (:class:`ActorKind`): a member, a
    plug-in or Initiative, stamped by the database as the row goes to the
    trash and cleared as it comes back (``public.fn_stamp_deleted_by``). It is
    the one person-naming column here that declares no ``foreign_key`` at all
    — see the note on it below.
    """

    deleted_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),
        nullable=True,
    )
    # NOTE: no ``foreign_key=`` here, deliberately. SQLAlchemy would then see
    # two references from this table to users (``created_by`` + this one) and
    # fail to auto-determine join conditions on relationships that join to
    # users. Audit lookups go through the trash service, never through an ORM
    # relationship, so SQLAlchemy doesn't need the metadata.
    deleted_by: int | None = Field(default=None, nullable=True)
    deleted_by_kind: ActorKind | None = Field(
        default=None, sa_type=String(length=16), nullable=True
    )
    purge_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),
        nullable=True,
    )

    _display_field: ClassVar[str] = "name"

    @classmethod
    def display_field(cls) -> str:
        return cls._display_field


class ArchiveMixin(SQLModel):
    """Mixin that adds the archive lifecycle column to a guild-scoped model.

    Archiving says *this is finished*; the trash says *this is going away*. They
    are different states with the same shape, so they carry the same shape of
    column: one nullable timestamp, null while live, stamped when it happens.
    ``archived_at`` reads beside ``deleted_at`` and answers "when?" as well as
    "whether?", which a boolean never could.

    Anything an initiative offers can be finished with, so every tool carries
    it, and so do the two things that are not tools but are still worked
    through and put away: a task and an initiative itself.

    Archived content is read-only, down through everything inside it — the rule
    is ``app.db.frozen``, which reads this column and ``deleted_at`` together
    and derives the archivable tables from this mixin.
    """

    archived_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),
        nullable=True,
    )


class HoldMixin(SQLModel):
    """Mixin that adds the hold columns to a guild-scoped model.

    A hold keeps content where it is for the platform: while ``held_at`` is
    set, the row reads as absent to everyone in the community, community
    admins included, and nobody in the community can change or delete it.
    ``hold_id`` names the ``content_holds`` row that placed it. Only the
    platform releases it (``app.services.platform.holds``).

    Everything a person can report carries it — every searchable kind and
    the uploads such content shows — so ``HOLDABLE_TABLES``
    (``app.db.holds``), its row policy and its guard are derived from this
    mixin, and a new kind is holdable the day it declares it.
    """

    held_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),
        nullable=True,
    )
    hold_id: int | None = Field(default=None, nullable=True)


class CreatedByMixin(SQLModel):
    """Who made a guild-schema row: ``created_by`` and ``created_by_kind``.

    The kind says what ``created_by`` names (:class:`ActorKind`): a member's
    user id, a plug-in's install id, or NULL for Initiative. CHECKs hold the
    pair together. Anything that compares ``created_by`` to a user checks the
    kind as well.

    The database fills both (``public.fn_set_created_by``, a BEFORE INSERT
    trigger per table) from the request: its user, else its plug-in, else
    Initiative. A write on someone else's behalf names both columns; one that
    names only ``created_by`` is refused. A freshly flushed object holds
    ``None`` until refreshed.

    Authorship is historical and never transfers; ownership lives in
    ``resource_grants``. ``created_by`` is a weak reference: it outlives the
    account or install it names. The ``users.id`` foreign key is metadata only,
    which gives its filter a member picker (``app.services.fields.derive``).
    There is no ``updated_by``; ``event_outbox`` records who changed what.
    """

    created_by: int | None = Field(default=None, foreign_key="users.id", nullable=True)
    #: What ``created_by`` names. NULL on an object until the insert trigger has
    #: stamped it and the object is refreshed.
    created_by_kind: ActorKind | None = Field(
        default=None, sa_type=String(length=16), nullable=False
    )


class ListingProvenanceMixin(SQLModel):
    """Mixin that records which marketplace listing a tool item came from.

    Installing a listing is importing a copy of it, and the copy keeps two
    facts about where it came from: the listing's ``uid`` and the version it
    was taken at. Both are NULL on anything made here, which is almost
    everything. There is no link back and no update stream — the copy belongs
    to whoever installed it — so these are a record, not a reference, and no
    foreign key reaches the catalog.

    Every tool has a marketplace, so every tool carries the pair.
    ``tools_test.py`` fails CI if a ``Tool`` member's model lacks it. Declared
    without ``sa_column`` so each table builds its own Column.
    """

    listing_uid: str | None = Field(default=None, sa_type=String(14), nullable=True)
    listing_version: str | None = Field(default=None, sa_type=String(32), nullable=True)


class CommentsToggleMixin(SQLModel):
    """Mixin that adds the per-entity comment switch to a tool's content table.

    Every tool is commentable, so every tool can turn its thread off:
    ``comments_enabled`` is the one column behind that, carrying the same name
    and the same default (on) on every tool. ``tools_test.py`` fails CI if a
    ``Tool`` member's model or read schema lacks it.

    Stated positively — a switch labelled "Comments" is on when comments
    happen, so nobody has to answer yes to mean no.

    The switch belongs to the tool entity, not to its children: a project with
    comments off still has task threads, because a task is its own flow rather
    than a tool surface.

    Declared without ``sa_column`` so each table builds its own Column — one
    Column instance cannot be shared across mapped tables.
    """

    comments_enabled: bool = Field(
        default=True,
        nullable=False,
        sa_column_kwargs={"server_default": "true"},
    )


class CommentLockMixin(SQLModel):
    """Mixin that lets a moderator close a thread to new comments.

    On everything a thread hangs off — every tool, and the content-level
    extras with threads of their own. While ``comments_locked_at`` is set the
    thread still reads, nobody adds to it or edits what is in it, and only
    the community's moderators lift the lock: it is not the owner's comment switch
    (``CommentsToggleMixin``), which hides the thread altogether and is
    theirs to flip.
    """

    comments_locked_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),
        nullable=True,
    )


def _mapped_subclasses[M: SQLModel](base: type[M]) -> dict[str, type[M]]:
    """Every mapped table model under ``base``, however indirectly, by table."""
    found: dict[str, type[M]] = {}
    stack = list(base.__subclasses__())
    while stack:
        cls = stack.pop()
        stack.extend(cls.__subclasses__())
        table = getattr(cls, "__tablename__", None)
        if table and getattr(cls, "__table__", None) is not None:
            found[str(table)] = cls
    return found


def archive_models() -> list[type[ArchiveMixin]]:
    """Every mapped model carrying :class:`ArchiveMixin`, by table name.

    The single source for "which tables can be archived" — the freeze reads it
    rather than keeping a list of its own, so a tool that becomes archivable is
    archivable everywhere the moment it declares the mixin.
    """
    found = _mapped_subclasses(ArchiveMixin)
    return [found[name] for name in sorted(found)]


def soft_delete_models() -> list[type[SoftDeleteMixin]]:
    """Every mapped model carrying :class:`SoftDeleteMixin`, by table name.

    The single source for "which tables have a trash can" — the active-row
    filter, the trash routes and the purge read it, so a model is trashable
    everywhere the moment it declares the mixin.
    """
    found = _mapped_subclasses(SoftDeleteMixin)
    return [found[name] for name in sorted(found)]


def hold_models() -> list[type[HoldMixin]]:
    """Every mapped model carrying :class:`HoldMixin`, by table name. The
    single source for which tables can be held."""
    found = _mapped_subclasses(HoldMixin)
    return [found[name] for name in sorted(found)]


def created_by_models() -> list[type[CreatedByMixin]]:
    """Every mapped model carrying :class:`CreatedByMixin`, by table name.

    The single source for "which tables record an author" — the completeness
    test reads it, so a new table joins the moment it declares the mixin.
    """
    found = _mapped_subclasses(CreatedByMixin)
    return [found[name] for name in sorted(found)]


def tool_models() -> dict[str, type[SQLModel]]:
    """Each tool's own content model, keyed by table name.

    A tool's table is its plural — that rule is :class:`~app.core.tools.Tool`'s,
    not this module's — so the registries that map a tool to its model read this
    instead of restating the pairing. A tool added to the enum is picked up the
    moment its model exists, which is what keeps those registries from being a
    place a new tool can be forgotten.
    """
    return _mapped_subclasses(SoftDeleteMixin)


def attach_actions(model: type[SQLModel], tool: "Tool") -> None:
    """Map ``actions`` on a shareable model: what the request may do to the
    row beyond reading it, answered by the schema's own ``resource_actions`` in
    the same SELECT as the row — the function whose answers the routes refuse
    by and the row's ``can`` reports.

    Deferred, so a load that only needs the row pays nothing; a loader that
    goes on to decide or serialize asks for it with ``undefer``. Read through
    :func:`app.services.permissions.actions_of`.
    """
    model.__mapper__.add_property(  # type: ignore[attr-defined]
        "actions",
        column_property(
            func.resource_actions(
                tool.value,
                model.id,  # type: ignore[attr-defined]
                _reader(),
                model.initiative_id,  # type: ignore[attr-defined]
                model.archived_at,  # type: ignore[attr-defined]
                model.deleted_at,  # type: ignore[attr-defined]
                _standing(),
                type_=ARRAY(String),
            ),
            deferred=True,
        ),
    )


def attach_initiative_actions(model: type[SQLModel]) -> None:
    """Map ``actions`` on the initiative: what the request may do in it,
    answered by the schema's ``initiative_actions`` in the same SELECT as the
    row. Deferred like a tool's; the loaders that serialize an initiative ask
    for it with ``undefer``."""
    model.__mapper__.add_property(  # type: ignore[attr-defined]
        "actions",
        column_property(
            func.initiative_actions(
                model.id,  # type: ignore[attr-defined]
                _reader(),
                _standing(),
                type_=ARRAY(String),
            ),
            deferred=True,
        ),
    )


def _reader() -> Any:
    """The request's user, as the policies read it."""
    return literal_column(gucs.USER_ID.sql, Integer)


def _standing() -> Any:
    """This statement's standing, as ``app.db.authorization.standing_arg``
    spells it; this module sits below that one, so the sub-select is written
    here."""
    return select(func.current_standing()).scalar_subquery()
