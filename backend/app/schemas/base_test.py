"""Tests for SanitizedBaseModel."""

from __future__ import annotations

import importlib
import pkgutil
from enum import Enum
from typing import Optional

import pytest
from pydantic import BaseModel, ValidationError

import app.schemas as schemas_pkg
from app.schemas.base import (
    MAX_PLAIN_TEXT_LENGTH,
    MAX_TITLE_LENGTH,
    RESERVED_SIGILS,
    RawTextStr,
    RichTextStr,
    SanitizedBaseModel,
    TitleStr,
    sigil_free_fields,
)


class _Color(str, Enum):
    red = "red"
    blue = "blue"


class _Model(SanitizedBaseModel):
    name: str
    display: Optional[TitleStr] = None
    bio: Optional[str] = None
    rich: RichTextStr = ""
    rich_opt: Optional[RichTextStr] = None
    raw: RawTextStr = ""
    raw_opt: Optional[RawTextStr] = None
    count: int = 0
    enabled: bool = False
    color: _Color = _Color.red


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Markup goes, the text inside it stays.
        ("<script>alert(1)</script>hello", "hello"),
        ("<b>bold</b>", "bold"),
        ("before <img src=x onerror=alert(1)> after", "before  after"),
        # Benign characters survive verbatim rather than being entity-encoded
        # (an encoder here renders "&amp;" literally on screen).
        ("Death House Encounter & Planning", "Death House Encounter & Planning"),
        ('5 < 3 is false; she said "hi"', '5 < 3 is false; she said "hi"'),
        ("plain text without html", "plain text without html"),
        # Entities decode to their characters, still as text.
        ("5 &lt; 3 &amp; 2 &gt; 1", "5 < 3 & 2 > 1"),
    ],
)
def test_plain_text_keeps_the_text_and_drops_the_markup(
    raw: str, expected: str
) -> None:
    assert _Model(name=raw).name == expected


@pytest.mark.parametrize(
    ("raw", "absent"),
    [
        ("before &lt;img src=x onerror=alert(1)&gt; after", ["<img", "onerror"]),
        (
            "&amp;lt;script&amp;gt;alert(1)&amp;lt;/script&amp;gt;",
            ["<script", "alert(1)"],
        ),
        ('<a href="javascript:bad()">link</a>', ["javascript:"]),
    ],
)
def test_encoded_markup_is_not_turned_back_into_markup(
    raw: str, absent: list[str]
) -> None:
    """Decoding happens before stripping, and once — so nothing that arrives
    encoded (or double-encoded) comes back out live."""
    cleaned = _Model(name=raw).name
    for fragment in absent:
        assert fragment not in cleaned


@pytest.mark.parametrize("field", ["rich", "raw", "rich_opt", "raw_opt"])
def test_opted_out_fields_keep_their_markup(field: str) -> None:
    """The opt-out marker is honoured on the field itself and when it is nested
    inside ``Optional[...]``, where field metadata alone does not show it."""
    raw = "<script>alert(1)</script><b>x</b> & < >"
    assert getattr(_Model(name="x", **{field: raw}), field) == raw


def test_enum_field_not_modified() -> None:
    # Enums should never be coerced through nh3.clean.
    m = _Model(name="x", color=_Color.blue)
    assert m.color is _Color.blue

    # Same goes for string-form enum values.
    m2 = _Model(name="x", color="red")
    assert m2.color is _Color.red


def test_non_str_fields_not_modified() -> None:
    m = _Model(name="x", count=42, enabled=True)
    assert m.count == 42
    assert m.enabled is True


def test_optional_str_sanitized_when_present() -> None:
    m = _Model(name="x", bio="<script>x</script>safe")
    assert m.bio == "safe"


def test_optional_str_none_passes_through() -> None:
    m = _Model(name="x", bio=None)
    assert m.bio is None


def test_plain_text_over_max_length_rejected() -> None:
    with pytest.raises(ValidationError):
        _Model(name="x" * (MAX_PLAIN_TEXT_LENGTH + 1))


def test_plain_text_at_max_length_allowed() -> None:
    m = _Model(name="x" * MAX_PLAIN_TEXT_LENGTH)
    assert len(m.name) == MAX_PLAIN_TEXT_LENGTH


def test_raw_text_field_exempt_from_length_cap() -> None:
    big = "A" * (MAX_PLAIN_TEXT_LENGTH + 5000)
    m = _Model(name="ok", raw=big)
    assert m.raw == big


@pytest.mark.parametrize("sigil", sorted(RESERVED_SIGILS))
def test_title_str_rejects_reserved_sigil(sigil: str) -> None:
    with pytest.raises(ValidationError) as exc:
        _Model(name="x", display=f"team {sigil}alpha")
    assert "RESERVED_SIGIL_IN_NAME" in str(exc.value)


def test_title_str_rejects_sigil_revealed_by_stripping() -> None:
    """The check runs on the stripped value, not the raw one."""
    with pytest.raises(ValidationError):
        _Model(name="x", display="a<b>&#35;</b>b")


def test_title_str_allows_ordinary_punctuation() -> None:
    m = _Model(name="x", display="Q3 Report (final) & notes — v2")
    assert m.display == "Q3 Report (final) & notes — v2"


def test_title_str_is_trimmed() -> None:
    assert _Model(name="  x  ", display="  Q3 Report  ").display == "Q3 Report"
    assert _Model(name="  x  ").name == "  x  "
    # Nothing left once trimmed is no title at all.
    with pytest.raises(ValidationError):
        _Model(name="x", display="   ")


def test_title_str_none_passes_through() -> None:
    assert _Model(name="x", display=None).display is None


def test_title_str_stops_at_the_bound() -> None:
    at = "a" * MAX_TITLE_LENGTH
    assert _Model(name="x", display=at).display == at
    with pytest.raises(ValidationError):
        _Model(name="x", display=at + "a")


def test_plain_str_field_is_not_held_to_the_title_bound() -> None:
    """A title is a label; a plain str field is bounded by the plain-text cap."""
    long = "a" * (MAX_TITLE_LENGTH + 1)
    assert _Model(name=long).name == long


def test_plain_str_field_still_accepts_sigils() -> None:
    """Only TitleStr fields are held to the rule."""
    assert _Model(name="Fix #12 for @alice").name == "Fix #12 for @alice"


def test_sigil_free_fields_sees_through_optional() -> None:
    assert sigil_free_fields(_Model) == frozenset({"display"})


def test_every_schema_extends_sanitized_base() -> None:
    """Lint: every Pydantic class in app.schemas must extend SanitizedBaseModel.

    Catches the case where a new schema is added that inherits directly from
    pydantic.BaseModel, silently bypassing HTML sanitization on its str fields.
    """
    offenders: list[str] = []
    for module_info in pkgutil.iter_modules(schemas_pkg.__path__):
        if module_info.name.endswith("_test"):
            continue
        module = importlib.import_module(f"app.schemas.{module_info.name}")
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if not isinstance(attr, type):
                continue
            if attr is BaseModel or attr is SanitizedBaseModel:
                continue
            if not issubclass(attr, BaseModel):
                continue
            # Skip classes re-exported from elsewhere.
            if not attr.__module__.startswith("app.schemas"):
                continue
            if not issubclass(attr, SanitizedBaseModel):
                offenders.append(f"{attr.__module__}.{attr.__name__}")
    assert not offenders, (
        "These Pydantic classes in app.schemas do not extend SanitizedBaseModel:\n"
        + "\n".join(f"  - {o}" for o in offenders)
        + "\n\nInherit from SanitizedBaseModel (app.schemas.base) instead of"
        " BaseModel so str fields are HTML-sanitized by default."
    )


# Name-shaped fields on a request body. A schema either holds these to
# RESERVED_SIGILS via TitleStr or is listed in _SIGIL_EXEMPT below, so a new
# tool's Create schema cannot quietly join the searched surface without a
# decision being recorded here.
_NAME_FIELDS = frozenset({"name", "title", "label"})

#: Request-body fields deliberately outside the rule, and why.
_SIGIL_EXEMPT: frozenset[str] = frozenset(
    {
        # A file's name starts life as a filename, and a filename may
        # legitimately carry either character.
        "app.schemas.tenant.file.FileCreate.name",
        "app.schemas.tenant.file.FileUpdate.name",
        # Any tool's copy: held in ``tool_copy.duplicate`` to the rule its
        # tool's own name follows, since a file's may carry either.
        "app.schemas.tenant.tool.ToolDuplicateRequest.name",
        # Configuration labels: named by whoever administers the thing, and not
        # written into the search index.
        "app.schemas.ai_settings.AIConnectionCreate.label",
        "app.schemas.ai_settings.AIConnectionUpdate.label",
        "app.schemas.platform.api_key.ApiKeyCreateRequest.name",
        "app.schemas.tenant.guild_plugin.CommunityPluginInstall.name",
        "app.schemas.tenant.guild_plugin.CommunityPluginUpdate.name",
        "app.schemas.tenant.initiative.InitiativeRoleCreate.name",
        "app.schemas.tenant.property.PropertyDefinitionCreate.name",
        "app.schemas.tenant.property.PropertyDefinitionUpdate.name",
        "app.schemas.tenant.property.PropertyDefinitionPromote.name",
        "app.schemas.tenant.task_status.TaskStatusCreate.name",
        "app.schemas.tenant.task_status.TaskStatusUpdate.name",
        "app.schemas.tenant.task_type.TaskTypeCreate.name",
        "app.schemas.tenant.task_type.TaskTypeUpdate.name",
        # An announcement's title is prose an operator writes about the product
        # — never a mention target and never indexed — and a notice about
        # mentions or about issue #123 wants to say so in its title.
        "app.schemas.platform.announcement.AnnouncementWrite.title",
        "app.schemas.platform.announcement.AnnouncementUpdate.title",
    }
)


def _request_body_models() -> set[type[BaseModel]]:
    """Every schema reachable from a route's request body, nested ones included."""
    from fastapi.routing import APIRoute

    from app.main import app as fastapi_app

    found: set[type[BaseModel]] = set()

    def walk(annotation: object) -> None:
        # An optional body (``Model | None``) and a nested field are both
        # unions; follow their arguments as well as the annotation itself.
        for model in (annotation, *getattr(annotation, "__args__", ())):
            if not (isinstance(model, type) and issubclass(model, BaseModel)):
                continue
            if model in found or not model.__module__.startswith("app.schemas"):
                continue
            found.add(model)
            for info in model.model_fields.values():
                walk(info.annotation)

    for route in fastapi_app.routes:
        if isinstance(route, APIRoute) and route.body_field is not None:
            walk(route.body_field.field_info.annotation)
    return found


def test_request_body_names_are_sigil_free() -> None:
    """Lint: a name/title/label on a request body carries TitleStr or is exempt.

    The rule travels with the schema rather than with each endpoint, so this
    reads the route table back and asks every body shape what it enforces.
    """
    offenders: list[str] = []
    for model in _request_body_models():
        enforced = sigil_free_fields(model)
        for field_name in model.model_fields:
            if field_name not in _NAME_FIELDS or field_name in enforced:
                continue
            path = f"{model.__module__}.{model.__name__}.{field_name}"
            if path not in _SIGIL_EXEMPT:
                offenders.append(path)
    assert not offenders, (
        "These request-body name fields are neither TitleStr nor exempt:\n"
        + "\n".join(f"  - {o}" for o in sorted(offenders))
        + "\n\nType the field `TitleStr` (app.schemas.base) so it rejects"
        " RESERVED_SIGILS, or add it to _SIGIL_EXEMPT with the reason."
    )


def test_sigil_exempt_entries_all_exist() -> None:
    """The exemption list decays into fiction if an entry outlives its field."""
    live = {
        f"{model.__module__}.{model.__name__}.{field}"
        for model in _request_body_models()
        for field in model.model_fields
        if field in _NAME_FIELDS
    }
    assert not (_SIGIL_EXEMPT - live), (
        "_SIGIL_EXEMPT names fields that no longer reach a request body:\n"
        + "\n".join(f"  - {o}" for o in sorted(_SIGIL_EXEMPT - live))
    )
