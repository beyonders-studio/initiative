"""What a person and a community are called at the edge of a request.

Inside, a person is a row id and so is a community. An installed plug-in is never
handed either: it knows each person by a reference minted for its own install,
and its community by one more. A request and a response carry the
two in fields typed :data:`PersonId` and :data:`GuildId`, and those two types
are where the translation happens.

For a person, nothing changes: both are ``int`` on the way in and on the way
out, with ``int``'s JSON schema and a marker naming what the field carries.

For an install, each request passes through three phases, held on an
:class:`InstallBoundary` that the route's scope dependency sets up once the
install's standing is in:

- **input**: the request's own path, query and body are validated. A field of
  either type accepts only a reference, looked up in what the standing
  statement resolved for this request (:attr:`InstallBoundary.named`). A row
  id, or a reference that names nobody in this install's sector, is a 422
  (``PLUGIN_REFERENCE_UNKNOWN``).
- **handler**: the route's own code runs. Both types behave as ``int``, so a
  model built from rows and a payload stored as JSON hold row ids.
- **response**: the route's return value is serialized. A :data:`GuildId`
  becomes the install's community reference when the standing returned one;
  anything else becomes a marker carrying a per-request nonce, and the route
  class (``app.api.actor_route.ActorRoute``) resolves the markers after
  serialization and writes the references in.

A field marked :class:`Mentions` names people inside its value. A mention is
stored by row id alone, whoever writes it, and its name is read wherever it is
shown. For an install it goes through the same phases: a mention it writes
names a reference, which the input phase resolves to the row id, and a mention
in a response carries a marker.

A field marked :data:`UPLOAD_PATH` holds a stored file's path,
``/uploads/{guild_id}/{name}``, which names the community by its row id and is
served to people. A person gets it; in an install's response it is ``""``, and
an outside URL the field holds instead is as it is. Text
marked :class:`Mentions` can show a stored file too, as an image or a link: in
an install's response the address of each one this deployment serves is left
empty (:data:`UPLOAD_PATH_SHAPE`).

The boundary lives in a context variable that ``ActorRoute`` opens per request,
so it never outlives the request that set it.
"""

from __future__ import annotations

import re
import secrets
from collections.abc import Callable, Generator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from typing import Annotated, Any
from urllib.parse import urlsplit

from fastapi import HTTPException, status
from pydantic import (
    GetCoreSchemaHandler,
    GetJsonSchemaHandler,
    PlainSerializer,
    WithJsonSchema,
    WrapValidator,
)
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import PydanticCustomError, core_schema

from app.core.config import settings
from app.core.messages import PluginMessages
from app.models.platform.identity_ref import IdentityEntity

__all__ = [
    "LEXICAL_MENTIONS",
    "MARKDOWN_MENTIONS",
    "STORED_MENTION",
    "UNKNOWN_REFERENCE_ERROR",
    "UPLOAD_PATH",
    "UPLOAD_PATH_SHAPE",
    "BoundaryPhase",
    "GuildId",
    "InstallBoundary",
    "MentionForm",
    "Mentions",
    "PersonId",
    "admit_install",
    "boundary_scope",
    "current_install_boundary",
    "filter_people",
    "names_withheld",
    "responding_to_install",
    "with_mention_markup",
    "without_mention_names",
    "written_mention_refs",
]


class BoundaryPhase(str, Enum):
    """Where an install's request is: see the module docstring."""

    input = "input"
    handler = "handler"
    response = "response"


#: The pydantic error type a reference that names nobody raises under.
UNKNOWN_REFERENCE_ERROR = "plugin_reference_unknown"


def _unknown() -> PydanticCustomError:
    return PydanticCustomError(
        UNKNOWN_REFERENCE_ERROR, PluginMessages.REFERENCE_UNKNOWN
    )


@dataclass
class InstallBoundary:
    """One installed plug-in's request, as the identity types see it.

    Built by the scope dependency from the install's completed standing:
    ``guild_id`` and ``install_id`` are the routed community and install,
    ``guild_ref`` what the install calls that community, and ``named`` the
    references the request named that resolve in the install's sector, and
    ``members`` the people among them who are members of the community.
    ``reads_names`` is whether the install holds ``members:read``, which is
    what lets it read people's names. ``session`` is the request's routed
    session, on which the route class resolves what the response names.
    """

    guild_id: int
    install_id: int
    guild_ref: str | None
    named: Mapping[str, tuple[IdentityEntity, int]]
    members: frozenset[int] = frozenset()
    reads_names: bool = False
    session: Any = None
    phase: BoundaryPhase = BoundaryPhase.input
    #: Marks a value the response names. Random per request, so nothing a
    #: route returns can be read as one.
    nonce: str = field(default_factory=lambda: secrets.token_hex(16))
    #: What the response named, as ``(entity, row id)``.
    wanted: set[tuple[IdentityEntity, int]] = field(default_factory=set)

    def resolve(self, value: Any, entity: IdentityEntity) -> int:
        """The row id a reference in the request names, or a 422.

        A reference is a string; a row id is not accepted from an install. A
        community reference must name the routed community.
        """
        if not isinstance(value, str):
            raise _unknown()
        found = self.named.get(value)
        if found is None or found[0] is not entity:
            raise _unknown()
        entity_id = found[1]
        if entity is IdentityEntity.guild and entity_id != self.guild_id:
            raise _unknown()
        return entity_id

    def mentioned(self, value: Any) -> int:
        """The member a mention in the request names, or a 422."""
        user_id = self.resolve(value, IdentityEntity.user)
        if user_id not in self.members:
            raise _unknown()
        return user_id

    def mark(self, entity: IdentityEntity, entity_id: int) -> str:
        """The marker a response carries for ``entity_id`` until the route
        class writes its reference in."""
        if entity is IdentityEntity.guild and entity_id != self.guild_id:
            # A response to an install names its own community and no other.
            raise ValueError("a response to an install names only its community")
        self.wanted.add((entity, entity_id))
        return f"{self.nonce}:{entity.code}:{entity_id}"


class _Slot:
    """The request's place for a boundary. Opened by the route class; filled
    by the scope dependency when the request is an install's."""

    __slots__ = ("boundary",)

    def __init__(self) -> None:
        self.boundary: InstallBoundary | None = None


_SLOT: ContextVar[_Slot | None] = ContextVar("identity_boundary", default=None)


@contextmanager
def boundary_scope() -> Generator[_Slot]:
    """Open a request's slot for the rest of the request, and close it after."""
    slot = _Slot()
    token = _SLOT.set(slot)
    try:
        yield slot
    finally:
        _SLOT.reset(token)


def admit_install(boundary: InstallBoundary) -> None:
    """Record ``boundary`` as the request's. Refuses outside an open slot: a
    route that admits an installed plug-in is served by ``ActorRoute``."""
    slot = _SLOT.get()
    if slot is None:
        raise RuntimeError(
            "an installed plug-in's request is served by ActorRoute; this route's "
            "router does not use it"
        )
    slot.boundary = boundary


def current_install_boundary() -> InstallBoundary | None:
    """The install boundary of the request in progress, or ``None``."""
    slot = _SLOT.get()
    return None if slot is None else slot.boundary


def filter_people(value: Any) -> Any:
    """The row ids a list filter names, for an installed plug-in, which names
    each person by a reference: one, or a list of them. A 422
    (``PLUGIN_REFERENCE_UNKNOWN``) for one that names nobody in its sector, as
    a :data:`PersonId` field answers."""
    boundary = current_install_boundary()
    try:
        if boundary is None:
            raise _unknown()
        if isinstance(value, list):
            return [boundary.resolve(item, IdentityEntity.user) for item in value]
        return boundary.resolve(value, IdentityEntity.user)
    except PydanticCustomError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=PluginMessages.REFERENCE_UNKNOWN,
        ) from None


def _boundary_in(phase: BoundaryPhase) -> InstallBoundary | None:
    boundary = current_install_boundary()
    if boundary is None or boundary.phase is not phase:
        return None
    return boundary


def responding_to_install() -> bool:
    """Whether a value being serialized now goes out in an installed plug-in's
    response. For a field whose value names a person some other way than by
    a :data:`PersonId` field, and is left out for an install."""
    return _boundary_in(BoundaryPhase.response) is not None


def names_withheld() -> bool:
    """Whether a value being serialized now goes out to an installed plug-in that
    does not hold ``members:read``, which knows people only by its references."""
    boundary = _boundary_in(BoundaryPhase.response)
    return boundary is not None and not boundary.reads_names


# --- The two types --------------------------------------------------------------


def _validator(entity: IdentityEntity):
    def validate(value: Any, handler: core_schema.ValidatorFunctionWrapHandler) -> int:
        boundary = _boundary_in(BoundaryPhase.input)
        if boundary is None:
            return handler(value)
        return boundary.resolve(value, entity)

    return validate


def _serializer(entity: IdentityEntity):
    def serialize(value: int) -> int | str:
        boundary = _boundary_in(BoundaryPhase.response)
        if boundary is None:
            return value
        if (
            entity is IdentityEntity.guild
            and boundary.guild_ref is not None
            and value == boundary.guild_id
        ):
            return boundary.guild_ref
        return boundary.mark(entity, value)

    return serialize


#: The schema each type publishes, in both modes: an integer, which is what a
#: person sends and receives, marked with what it names so the plug-in API's
#: document (``app.api.plugin_openapi``) can publish it as an install's reference.
_PERSON_SCHEMA = WithJsonSchema({"type": "integer", "x-identity": "person"})
_GUILD_SCHEMA = WithJsonSchema({"type": "integer", "x-identity": "community"})

#: A person's id in a request or response schema. ``int`` for a person; the
#: install's reference for an installed plug-in.
PersonId = Annotated[
    int,
    WrapValidator(_validator(IdentityEntity.user)),
    PlainSerializer(_serializer(IdentityEntity.user), return_type=Any),
    _PERSON_SCHEMA,
]

#: A community's id in a request or response schema. ``int`` for a person; the
#: install's community reference for an installed plug-in.
GuildId = Annotated[
    int,
    WrapValidator(_validator(IdentityEntity.guild)),
    PlainSerializer(_serializer(IdentityEntity.guild), return_type=Any),
    _GUILD_SCHEMA,
]


# --- Mentions -------------------------------------------------------------------


class MentionForm(str, Enum):
    """How a field's value mentions a person."""

    #: ``@[](42)`` inside text: the person's row id. A mention written before
    #: names were left out carries one, ``@[Ada](42)``, and one of somebody
    #: with no account here has only a name, ``@[Ada]()``.
    markdown = "markdown"
    #: A node inside a Lexical editor state carrying ``mentionUserId``, with
    #: ``mentionName`` and ``text`` empty, and both set where it has no id.
    lexical = "lexical"


#: A stored markdown mention: its name and the row id. Postgres reads it alike.
STORED_MENTION = re.compile(r"@\[([^\]]*)\]\((\d+)\)")
#: A markdown mention an install writes: whatever it names, which must be a
#: reference.
_WRITTEN_MENTION = re.compile(r"@\[[^\]]*\]\(([A-Za-z0-9_-]+)\)")

_MENTION_ID = "mentionUserId"
#: What a node with an id holds in place of a name.
_NAMELESS = {"mentionName": "", "text": ""}


def written_mention_refs(text: str) -> list[str]:
    """What the markdown mentions in ``text`` name, for the standing statement
    to resolve."""
    return _WRITTEN_MENTION.findall(text)


def _rewrite_nodes(
    value: Any,
    rewrite: Callable[[dict[str, Any]], Any],
    text: Callable[[str], str] | None = None,
) -> Any:
    """``value`` copied, with every node that names a person in
    ``mentionUserId`` passed through ``rewrite``, and every string through
    ``text`` when one is given."""
    if isinstance(value, list):
        return [_rewrite_nodes(item, rewrite, text) for item in value]
    if isinstance(value, str) and text is not None:
        return text(value)
    if not isinstance(value, dict):
        return value
    walked = {key: _rewrite_nodes(child, rewrite, text) for key, child in value.items()}
    return walked if walked.get(_MENTION_ID) is None else rewrite(walked)


def without_mention_names(value: Any, form: MentionForm) -> Any:
    """``value`` with every mention of somebody by id carrying no name.

    How a mention is stored, whoever wrote it: the name is read where it is
    shown, so it is the one somebody goes by now and nothing holds it once they
    are gone. A mention with no id keeps the name it was written with, which is
    all it has.
    """
    if form is MentionForm.lexical:
        return _rewrite_nodes(value, lambda node: node | _NAMELESS)
    if not isinstance(value, str):
        return value
    return STORED_MENTION.sub(lambda match: f"@[]({match.group(2)})", value)


def with_mention_markup(value: Any) -> Any:
    """An editor state whose mentions by id read as their markdown, ``@[](42)``,
    in ``text``: for plain text made from it, which a client reads the mentions
    back out of and names as it names any other."""
    return _rewrite_nodes(
        value, lambda node: node | {"text": f"@[]({node[_MENTION_ID]})"}
    )


def _markdown_in(value: Any, boundary: InstallBoundary) -> Any:
    if not isinstance(value, str):
        return value
    return _WRITTEN_MENTION.sub(
        lambda match: f"@[]({boundary.mentioned(match.group(1))})", value
    )


def _markdown_out(value: Any, boundary: InstallBoundary) -> Any:
    if not isinstance(value, str):
        return value
    return _without_paths(
        STORED_MENTION.sub(
            lambda match: (
                f"@[]({boundary.mark(IdentityEntity.user, int(match.group(2)))})"
            ),
            value,
        )
    )


def _lexical_in(value: Any, boundary: InstallBoundary) -> Any:
    return _rewrite_nodes(
        value,
        lambda node: node | {_MENTION_ID: boundary.mentioned(node[_MENTION_ID])},
    )


def _lexical_out(value: Any, boundary: InstallBoundary) -> Any:
    def marked(node: dict[str, Any]) -> dict[str, Any]:
        user_id = node[_MENTION_ID]
        if not isinstance(user_id, int) or isinstance(user_id, bool):
            return node
        return node | {_MENTION_ID: boundary.mark(IdentityEntity.user, user_id)}

    return _rewrite_nodes(value, marked, _without_paths)


_TRANSLATIONS = {
    MentionForm.markdown: (_markdown_in, _markdown_out),
    MentionForm.lexical: (_lexical_in, _lexical_out),
}


@dataclass(frozen=True)
class Mentions:
    """Marks a field whose value may mention people, in ``form``.

    A mention in the request is stored by row id with no name
    (:func:`without_mention_names`). For an install it names a reference, and
    a mention in the response names the install's reference; a stored file the
    value shows comes without its path. The field's schema carries
    ``x-mentions``, which the plug-in API's document describes.
    """

    form: MentionForm

    def __get_pydantic_core_schema__(
        self, source: Any, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        schema = core_schema.no_info_wrap_validator_function(
            self._validate, handler(source)
        )
        schema["serialization"] = core_schema.wrap_serializer_function_ser_schema(
            self._serialize
        )
        return schema

    def __get_pydantic_json_schema__(
        self, schema: core_schema.CoreSchema, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        json_schema = handler(schema)
        json_schema["x-mentions"] = self.form.value
        return json_schema

    def _validate(
        self, value: Any, handler: core_schema.ValidatorFunctionWrapHandler
    ) -> Any:
        boundary = _boundary_in(BoundaryPhase.input)
        if boundary is not None:
            value = _TRANSLATIONS[self.form][0](value, boundary)
        return handler(without_mention_names(value, self.form))

    def _serialize(
        self, value: Any, handler: core_schema.SerializerFunctionWrapHandler
    ) -> Any:
        boundary = _boundary_in(BoundaryPhase.response)
        if boundary is not None:
            value = _TRANSLATIONS[self.form][1](value, boundary)
        return handler(value)


#: The marks a field type carries: markdown text, and a Lexical editor state.
MARKDOWN_MENTIONS = Mentions(MentionForm.markdown)
LEXICAL_MENTIONS = Mentions(MentionForm.lexical)


# --- Stored files ---------------------------------------------------------------


#: A stored file's path, ``/uploads/{guild_id}/{name}``, as a pattern.
UPLOAD_PATH_SHAPE = r"/uploads/\d+/[\w.-]+"

#: Characters an address goes on with: a path after one is part of it.
_ADDRESS_CHARS = r"\w.~%+@:/?#=&-"


@lru_cache(maxsize=4)
def _stored_file_address(app_url: str) -> re.Pattern[str]:
    """A stored file's address in text: its path on its own, or behind this
    deployment's origin (``app_url``, with its path when it has one), with any
    query and fragment, up to a space, a bracket or the end of the text."""
    own = urlsplit(app_url.strip())
    origin = rf"(?<![{_ADDRESS_CHARS}])"
    if own.netloc:
        prefix = re.escape(own.path.rstrip("/"))
        origin = rf"(?:https?://(?i:{re.escape(own.netloc)})(?:{prefix})?|{origin})"
    return re.compile(rf"{origin}{UPLOAD_PATH_SHAPE}(?:[?#][^\s()<>]*)?")


def _without_paths(text: str) -> str:
    """``text`` with each stored file's address emptied: ``![alt]()``,
    ``[name]()``, a node's ``"src": ""``. An address on another site stays."""
    return _stored_file_address(settings.APP_URL).sub("", text)


@dataclass(frozen=True)
class UploadPath:
    """Marks a field holding a stored file's path, or an outside URL.

    For a person the value passes through as it is. In an install's response a
    stored file's path, the whole value, is ``""``; an outside URL is as it is,
    and ``None`` stays ``None``. The field's schema carries ``x-upload``, which
    the plug-in API's document describes.
    """

    def __get_pydantic_core_schema__(
        self, source: Any, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        schema = handler(source).copy()
        schema["serialization"] = core_schema.wrap_serializer_function_ser_schema(
            self._serialize
        )
        return schema

    def __get_pydantic_json_schema__(
        self, schema: core_schema.CoreSchema, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        json_schema = handler(schema)
        json_schema["x-upload"] = True
        return json_schema

    def _serialize(
        self, value: Any, handler: core_schema.SerializerFunctionWrapHandler
    ) -> Any:
        if (
            isinstance(value, str)
            and responding_to_install()
            and _stored_file_address(settings.APP_URL).fullmatch(value)
        ):
            value = ""
        return handler(value)


#: The mark on a field holding a file's path: ``Annotated[str, UPLOAD_PATH]``,
#: or ``Annotated[Optional[str], UPLOAD_PATH]``.
UPLOAD_PATH = UploadPath()
