"""Jira fields → property definitions and values (design §6.5).

Pure, like the rest of the mapping: it takes the site's field catalog and the
issues the fetch read, and returns what the envelope carries. Two rules, in
order.

**Only fields somebody filled in.** A field no fetched issue carries a value
for creates no definition: it would be a column nobody ever used, dumped on an
initiative somebody else runs. The same rule narrows options — a select gets
the values actually seen, not the field's whole allowed set, because adding
one option later is a click and deleting eleven is not.

**Type from the schema.** Jira describes every field with ``schema.type`` (and
``schema.items`` for arrays, ``schema.custom`` for a plugin's own kind), so a
site's own fields arrive through the same table as the built-ins, with no
per-field code. What has no home here — several people in one field, a
service desk's internal records, a type nobody recognises — is dropped and
named, so the plan can say what will not come over.

Some fields are not properties at all, because they have a home already: the
summary is the title, status is the column, labels are tags, the assignee is
the assignee, links and the parent are edges. Those are never considered.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from app.models.tenant.metadata import MetadataType
from app.services.import_engine.adf import adf_to_markdown

#: The property every imported task carries, naming what it was called in Jira.
#: The only home an external id has, and what lets somebody reconcile a re-run
#: by hand.
JIRA_KEY_PROPERTY = "Jira key"

#: A custom date field with this name fills the task's own start date rather
#: than becoming a property: the task already has the column (§6.1).
START_DATE_FIELD_NAME = "start date"

_SECONDS_PER_HOUR = 3600.0


@dataclass(frozen=True)
class FieldSpec:
    """How one Jira field becomes a property."""

    field_id: str
    name: str
    property_type: MetadataType
    #: Jira's value → the envelope's, or ``None`` when there is nothing in it.
    read: Callable[[Any], Any]


@dataclass
class MappedFields:
    """What the fields came to, across every issue of one project."""

    #: The envelope's ``property_definitions``, one per field somebody filled.
    definitions: list[dict[str, Any]] = field(default_factory=list)
    #: Each issue's ``properties``, keyed by issue key.
    values_by_issue: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    #: Each issue's start date, from a "Start date" field, keyed by issue key.
    start_dates: dict[str, str] = field(default_factory=dict)
    #: How many issues filled each definition, by property name — the number
    #: the review step shows beside it.
    issue_counts: dict[str, int] = field(default_factory=dict)
    #: Fields some issue filled that have no home here, by name.
    dropped_fields: list[str] = field(default_factory=list)


# --- reading one value -------------------------------------------------------


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _text(value: Any) -> Optional[str]:
    """A string, or a rich-text field's ADF rendered as markdown."""
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict) and value.get("type") == "doc":
        return adf_to_markdown(value).markdown.strip() or None
    return None


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _hours(value: Any) -> Optional[float]:
    """Jira keeps estimates in seconds; a person reads them in hours."""
    seconds = _number(value)
    if seconds is None:
        return None
    return round(seconds / _SECONDS_PER_HOUR, 2)


def _date(value: Any) -> Optional[str]:
    if not isinstance(value, str) or len(value) < 10:
        return None
    candidate = value[:10]
    try:
        datetime.strptime(candidate, "%Y-%m-%d")
    except ValueError:
        return None
    return candidate


def _datetime(value: Any) -> Optional[str]:
    """Jira's ``2024-03-04T09:30:00.000+0000`` as ISO 8601 in UTC."""
    if not isinstance(value, str) or not value:
        return None
    for pattern in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            parsed = datetime.strptime(value, pattern)
        except ValueError:
            continue
        return parsed.astimezone(timezone.utc).isoformat()
    return None


def _label(value: Any) -> Optional[str]:
    """What an option, a version, a component or a priority is called."""
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        for key in ("value", "name"):
            text = value.get(key)
            if isinstance(text, str) and text.strip():
                return text.strip()
    return None


def _labels(value: Any) -> Optional[list[str]]:
    if not isinstance(value, list):
        return None
    out: list[str] = []
    for item in value:
        text = _label(item)
        if text and text not in out:
            out.append(text)
    return out or None


def _person(value: Any) -> Optional[str]:
    """A display name — never an address, which Jira withholds anyway."""
    if not isinstance(value, dict):
        return None
    name = value.get("displayName")
    return name.strip() if isinstance(name, str) and name.strip() else None


def _cascade(value: Any) -> Optional[str]:
    """A cascading select, ``Parent → Child``."""
    parent = _label(value)
    if parent is None:
        return None
    child = _label(value.get("child")) if isinstance(value, dict) else None
    return f"{parent} → {child}" if child else parent


# --- which fields become what --------------------------------------------------


#: The built-in fields with a property home, by field id, with the name §6.1
#: gives each. The rest of Jira's system fields either have a home already
#: (title, status, type, tags, assignee, dates, links) or none worth a column.
_SYSTEM_FIELDS: dict[str, tuple[str, MetadataType, Callable[[Any], Any]]] = {
    "priority": ("Priority", MetadataType.select, _label),
    "resolution": ("Resolution", MetadataType.select, _label),
    "resolutiondate": ("Resolved", MetadataType.datetime, _datetime),
    "reporter": ("Reporter", MetadataType.user_reference, _person),
    "components": ("Components", MetadataType.multi_select, _labels),
    "fixVersions": ("Fix versions", MetadataType.multi_select, _labels),
    "versions": ("Affects versions", MetadataType.multi_select, _labels),
    "environment": ("Environment", MetadataType.text, _text),
    "security": ("Security level", MetadataType.select, _label),
    "timeoriginalestimate": (
        "Original estimate (hours)",
        MetadataType.number,
        _hours,
    ),
    "timespent": ("Time spent (hours)", MetadataType.number, _hours),
    "timeestimate": ("Remaining estimate (hours)", MetadataType.number, _hours),
}

#: Custom fields that are not properties, by ``schema.custom``: each is either
#: somebody else's job (Sprint is the sprints item; the parent link replaces
#: the Epic fields) or Jira's bookkeeping (Rank is the order the tasks already
#: carry).
_HANDLED_ELSEWHERE = frozenset(
    {
        "com.pyxis.greenhopper.jira:gh-lexo-rank",
        "com.pyxis.greenhopper.jira:gh-sprint",
        "com.pyxis.greenhopper.jira:gh-epic-link",
        "com.pyxis.greenhopper.jira:gh-epic-label",
        "com.pyxis.greenhopper.jira:gh-epic-status",
        "com.pyxis.greenhopper.jira:gh-epic-color",
        "com.atlassian.jira.plugins.jira-development-integration-plugin:devsummarycf",
    }
)

_URL_CUSTOM = "com.atlassian.jira.plugin.system.customfieldtypes:url"


def _custom_spec(entry: dict) -> tuple[Optional[MetadataType], Callable[[Any], Any]]:
    """The property type and reader for a custom field, from its schema.

    ``(None, …)`` means the field has no home here and is dropped.
    """
    schema = entry.get("schema") if isinstance(entry.get("schema"), dict) else {}
    kind = schema.get("type")
    items = schema.get("items")
    custom = str(schema.get("custom") or "")

    if custom.startswith("com.atlassian.servicedesk"):
        return None, _text
    if kind == "string":
        if custom == _URL_CUSTOM:
            return MetadataType.url, _text
        return MetadataType.text, _text
    if kind == "number":
        return MetadataType.number, _number
    if kind == "date":
        return MetadataType.date, _date
    if kind == "datetime":
        return MetadataType.datetime, _datetime
    if kind in ("option", "priority", "resolution", "issuetype", "securitylevel"):
        return MetadataType.select, _label
    if kind in ("version", "component"):
        return MetadataType.select, _label
    if kind == "option-with-child":
        return MetadataType.text, _cascade
    if kind == "user":
        return MetadataType.user_reference, _person
    if kind == "array" and items in ("option", "string", "version", "component"):
        return MetadataType.multi_select, _labels
    return None, _text


def _unique(name: str, taken: set[str]) -> str:
    """A name no other definition in this envelope has, case-insensitively."""
    candidate = name
    n = 2
    while candidate.lower() in taken:
        candidate = f"{name} ({n})"
        n += 1
    taken.add(candidate.lower())
    return candidate


def _value_entry(spec: FieldSpec, value: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "property_name": spec.name,
        "property_type": spec.property_type.value,
    }
    if spec.property_type == MetadataType.number:
        entry["value_number"] = value
    elif spec.property_type == MetadataType.multi_select:
        entry["value_json"] = value
    elif spec.property_type == MetadataType.user_reference:
        entry["value_handle"] = value
    else:
        entry["value_text"] = value
    return entry


class FieldMapper:
    """:func:`map_fields` a page of issues at a time.

    Each page's values are read as it arrives, so the issues themselves can
    go once they are mapped. Which fields become definitions — only those
    somebody filled, with the options somebody used — is known only after
    the last page, which is what :meth:`finish` decides.
    """

    def __init__(self, catalog: Any) -> None:
        entries = (
            [e for e in catalog if isinstance(e, dict)]
            if isinstance(catalog, list)
            else []
        )
        taken: set[str] = {JIRA_KEY_PROPERTY.lower()}
        self._specs: list[FieldSpec] = []
        self._no_home: dict[str, str] = {}
        self._start_date_id: Optional[str] = None

        for field_id, (name, ptype, reader) in _SYSTEM_FIELDS.items():
            self._specs.append(FieldSpec(field_id, _unique(name, taken), ptype, reader))

        for entry in entries:
            field_id = str(entry.get("id") or "")
            name = str(entry.get("name") or "").strip()
            if not field_id or not name or not entry.get("custom"):
                continue
            schema = (
                entry.get("schema") if isinstance(entry.get("schema"), dict) else {}
            )
            if str(schema.get("custom") or "") in _HANDLED_ELSEWHERE:
                continue
            ptype, reader = _custom_spec(entry)
            if ptype is MetadataType.date and name.lower() == START_DATE_FIELD_NAME:
                self._start_date_id = field_id
                continue
            if ptype is None:
                self._no_home[field_id] = name
                continue
            self._specs.append(FieldSpec(field_id, _unique(name, taken), ptype, reader))

        self._result = MappedFields()
        self._options: dict[str, list[str]] = {}
        self._dropped: dict[str, str] = {}

    def add(self, issues: list[Any]) -> None:
        """Read what these issues filled in."""
        result = self._result
        options = self._options
        for issue in issues:
            if not isinstance(issue, dict) or not isinstance(issue.get("fields"), dict):
                continue
            key = str(issue.get("key") or "").strip()
            if not key:
                continue
            fields = issue["fields"]
            values = [
                {
                    "property_name": JIRA_KEY_PROPERTY,
                    "property_type": MetadataType.text.value,
                    "value_text": key,
                }
            ]
            result.issue_counts[JIRA_KEY_PROPERTY] = (
                result.issue_counts.get(JIRA_KEY_PROPERTY, 0) + 1
            )
            for spec in self._specs:
                value = spec.read(fields.get(spec.field_id))
                if _is_empty(value):
                    continue
                values.append(_value_entry(spec, value))
                result.issue_counts[spec.name] = (
                    result.issue_counts.get(spec.name, 0) + 1
                )
                if spec.property_type == MetadataType.select:
                    seen = options.setdefault(spec.name, [])
                    if value not in seen:
                        seen.append(value)
                elif spec.property_type == MetadataType.multi_select:
                    seen = options.setdefault(spec.name, [])
                    for item in value:
                        if item not in seen:
                            seen.append(item)
            if self._start_date_id is not None:
                start = _date(fields.get(self._start_date_id))
                if start:
                    result.start_dates[key] = start
            for field_id, name in self._no_home.items():
                if not _is_empty(fields.get(field_id)):
                    self._dropped[field_id] = name
            result.values_by_issue[key] = values

    def finish(self) -> MappedFields:
        """The definitions for what somebody filled, and every value read."""
        result = self._result
        # Definitions only for what somebody filled, in the order specs were
        # declared: the built-ins first, then the site's own in catalog order.
        filled = [spec for spec in self._specs if spec.name in result.issue_counts]
        if result.values_by_issue:
            result.definitions.append(
                {
                    "name": JIRA_KEY_PROPERTY,
                    "type": MetadataType.text.value,
                    "position": 0,
                }
            )
        for spec in filled:
            definition: dict[str, Any] = {
                "name": spec.name,
                "type": spec.property_type.value,
                "position": len(result.definitions),
            }
            if spec.name in self._options:
                definition["options"] = [
                    {"value": option, "label": option}
                    for option in self._options[spec.name]
                ]
            result.definitions.append(definition)
        result.dropped_fields = sorted(self._dropped.values(), key=str.lower)
        return result


def map_fields(catalog: Any, issues: list[Any]) -> MappedFields:
    """Turn what the issues filled in into definitions and values.

    ``catalog`` is ``GET /rest/api/3/field``. Without it the built-in fields
    still map — their ids are Jira's own — and a site's custom fields cannot
    be typed, so they are left out rather than guessed at.
    """
    mapper = FieldMapper(catalog)
    mapper.add(issues)
    return mapper.finish()
