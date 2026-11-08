"""Base schema with automatic HTML sanitization for str fields."""

from __future__ import annotations

import html
from enum import Enum
from functools import cache
from typing import Annotated, Any, Final, get_args, get_origin, get_type_hints

import nh3
from pydantic import BaseModel, field_validator, model_validator

from app.core.identity_boundary import LEXICAL_MENTIONS, MARKDOWN_MENTIONS

# Hard ceiling on any plain-text field. Generous for names/titles/labels/tokens
# while bounding both the stored size and the entity-decode loop in
# strip_to_plain_text. Fields that legitimately hold large data (base64 images,
# import payloads, AI output) opt out via RawTextStr; rich text via RichTextStr.
MAX_PLAIN_TEXT_LENGTH = 8192


class _SanitizeOptOut:
    """Base for markers that exempt a field from plain-text sanitization."""


class _RichTextMarker(_SanitizeOptOut):
    """Marker: field holds rich text rendered as markup — keep raw input."""


class _RawTextMarker(_SanitizeOptOut):
    """Marker: field holds raw/opaque data validated elsewhere (base64, import
    payloads, tokens) — keep raw input and skip the length cap."""


RichTextStr = Annotated[str, _RichTextMarker()]
"""str that opts out of plain-text sanitization (rich text kept verbatim)."""

RawTextStr = Annotated[str, _RawTextMarker()]
"""str that opts out of sanitization AND the length cap (large/opaque data)."""

MentionStr = Annotated[str, MARKDOWN_MENTIONS]
"""str that may mention people (``@[Name](id)``), translated for an installed
plug-in (``app.core.identity_boundary.Mentions``)."""

RichMentionStr = Annotated[RichTextStr, MARKDOWN_MENTIONS]
"""Rich text that may mention people, translated as :data:`MentionStr` is."""

#: A Lexical editor state: a file's, a post's or a wiki page's body.
LexicalState = Annotated[dict[str, Any], LEXICAL_MENTIONS]


# ``#`` and ``@`` are syntax wherever a name is written or read back. A comment
# body spells a mention ``@[Name](12)`` or ``#task[Title](3)``; a handle renders
# ``foobar#1234``, and a member search splits its term on the ``#`` to read the
# number after it. A name is the thing those forms point AT, so it does not also
# get to contain them.
RESERVED_SIGILS: Final = frozenset("#@")

#: Flat code raised for a name carrying one, mapped in ``errors.json``.
RESERVED_SIGIL_CODE: Final = "RESERVED_SIGIL_IN_NAME"

#: Flat code raised for a null on a field ``reject_null`` names.
NULL_FIELD_CODE: Final = "FIELD_CANNOT_BE_NULL"


# A name or title is a label: it is read in a sidebar, a breadcrumb, a card and
# a notification line, where the room it gets is a line rather than a page. Well
# under MAX_PLAIN_TEXT_LENGTH, which bounds a plain-text field of any kind. A
# field that wants a shorter one says so itself (``max_length=``); this is the
# ceiling for the ones that say nothing.
MAX_TITLE_LENGTH: Final = 255


class _SigilFreeMarker:
    """Marker: field is a name or title, and is held to :data:`RESERVED_SIGILS`
    and :data:`MAX_TITLE_LENGTH`."""


TitleStr = Annotated[str, _SigilFreeMarker()]
"""str for a name/title a person types: sanitized, trimmed, refused when blank,
bounded, and rejected if it holds a reserved sigil. Read schemas deliberately do NOT use it — a row stored
before the rules has to stay readable."""


def _reject_none(value: Any) -> Any:
    if value is None:
        raise ValueError(NULL_FIELD_CODE)
    return value


def reject_null(*fields: str) -> Any:
    """A validator for an update schema's fields where omitted means "keep" and
    null has no meaning: the column it lands in is required. Assign it in the
    class body (``_required = reject_null("name")``)."""
    return field_validator(*fields)(_reject_none)


def strip_to_plain_text(value: str) -> str:
    """Strip all HTML markup from a plain-text field WITHOUT HTML-encoding it.

    ``nh3.clean()`` is an HTML *output encoder*: it turns ``&`` into ``&amp;``,
    ``<`` into ``&lt;`` and so on, producing a string that is safe to drop into
    raw HTML. That is wrong for plain-text fields (names, titles, labels): the
    frontend renders them as React text nodes, which escape for the DOM at
    render time, so a stored ``&amp;`` shows up literally on screen as the four
    characters ``&amp;`` instead of ``&``.

    For these fields we want dangerous markup gone (``<img onerror>``,
    ``<script>``) but the benign characters the user actually typed (``&``,
    ``<``, ``>``, ``"``) preserved verbatim.

    The subtlety: a naive ``html.unescape(nh3.clean(value))`` unescapes *after*
    stripping, so an already-entity-encoded payload (``&lt;img onerror&gt;``)
    sails past ``nh3.clean`` as inert text and is then revived into live markup
    by the unescape. So we fully decode the input *first* — to a fixpoint, so
    markup encoded to any depth (``&amp;lt;…``) is exposed — and only then strip.
    Stripping with an empty allowlist also removes tags nh3's default allowlist
    would keep (e.g. ``<img src="x">``), which is what a plain-text field wants.
    """
    # Decode to a fixpoint before stripping. html.unescape returns a strictly
    # shorter string whenever it changes anything, so this terminates on its own
    # (no arbitrary iteration cap): worst case is one pass per entity.
    decoded = value
    while (once := html.unescape(decoded)) != decoded:
        decoded = once
    # Strip every tag, then undo the encoding nh3 applies to the surviving benign
    # characters. The final unescape is tag-free: ``decoded`` holds no entities,
    # so nh3 only ``&``-encodes lone </>/& that were never part of a tag.
    return html.unescape(nh3.clean(decoded, tags=set(), attributes={}))


def _annotation_has_marker(annotation: Any, marker: type) -> bool:
    """True if ``marker`` appears anywhere in the annotation, including nested
    inside ``Optional[...]`` / ``Union[...]``."""
    if get_origin(annotation) is Annotated:
        args = get_args(annotation)
        if any(isinstance(m, marker) for m in args[1:]):
            return True
        return _annotation_has_marker(args[0], marker)
    if get_origin(annotation) is not None:
        return any(_annotation_has_marker(a, marker) for a in get_args(annotation))
    return False


@cache
def _fields_marked(cls: type, marker: type) -> frozenset[str]:
    """Field names carrying ``marker``, resolved once per model.

    ``field_info.metadata`` only carries *top-level* Annotated metadata, so a
    marker nested in ``Optional[...]`` is invisible there — we walk the resolved
    annotations instead. Falls back to the top-level metadata if the annotations
    can't be introspected (e.g. an unresolved forward ref)."""
    try:
        hints = get_type_hints(cls, include_extras=True)
    except Exception:
        return frozenset(
            name
            for name, fi in cls.model_fields.items()
            if any(isinstance(m, marker) for m in fi.metadata)
        )
    return frozenset(
        name
        for name in cls.model_fields
        if name in hints and _annotation_has_marker(hints[name], marker)
    )


def _opt_out_fields(cls: type) -> frozenset[str]:
    """Field names exempt from sanitization (RichTextStr/RawTextStr)."""
    return _fields_marked(cls, _SanitizeOptOut)


def sigil_free_fields(cls: type) -> frozenset[str]:
    """Field names declared :data:`TitleStr`. Public so the drift test can ask a
    schema what it holds to the rule rather than keeping a second list."""
    return _fields_marked(cls, _SigilFreeMarker)


def _is_enum_type(annotation: Any) -> bool:
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return True
    # Handle Optional[SomeEnum], Union[SomeEnum, None], etc.
    args = getattr(annotation, "__args__", None)
    if args:
        return any(isinstance(a, type) and issubclass(a, Enum) for a in args)
    return False


class SanitizedBaseModel(BaseModel):
    """BaseModel that strips HTML markup from every str field by default.

    Plain-text fields have all tags removed without HTML-encoding the surviving
    characters, so ``Foo & Bar`` stays ``Foo & Bar`` (not ``Foo &amp; Bar``)
    while ``<img onerror>``/``<script>`` payloads are stripped — see
    :func:`strip_to_plain_text` — and are rejected past
    :data:`MAX_PLAIN_TEXT_LENGTH` characters. Fields typed :data:`RichTextStr`
    (rich text) or :data:`RawTextStr` (large or opaque data) opt out of both,
    even when wrapped in ``Optional[...]``. Enum-typed fields are skipped.

    Fields typed :data:`TitleStr` are additionally trimmed, refused when blank,
    bounded at
    :data:`MAX_TITLE_LENGTH` and reject :data:`RESERVED_SIGILS`.
    """

    @model_validator(mode="before")
    @classmethod
    def _sanitize_strings(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        exempt = _opt_out_fields(cls)
        sigil_free = sigil_free_fields(cls)
        for field_name, field_info in cls.model_fields.items():
            if field_name in exempt:
                continue
            if _is_enum_type(field_info.annotation):
                continue
            value = data.get(field_name)
            if isinstance(value, str):
                if len(value) > MAX_PLAIN_TEXT_LENGTH:
                    raise ValueError(
                        f"{field_name} exceeds the maximum length of "
                        f"{MAX_PLAIN_TEXT_LENGTH} characters"
                    )
                cleaned = strip_to_plain_text(value)
                # Both checked on the stripped value, which is what gets stored.
                if field_name in sigil_free:
                    cleaned = cleaned.strip()
                    if not cleaned:
                        raise ValueError(f"{field_name} cannot be blank")
                    if len(cleaned) > MAX_TITLE_LENGTH:
                        raise ValueError(
                            f"{field_name} exceeds the maximum length of "
                            f"{MAX_TITLE_LENGTH} characters"
                        )
                    if RESERVED_SIGILS.intersection(cleaned):
                        raise ValueError(RESERVED_SIGIL_CODE)
                data[field_name] = cleaned
        return data
