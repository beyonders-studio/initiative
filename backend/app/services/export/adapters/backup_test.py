"""Unit tests for the aggregate export's selector validation and sections."""

from typing import Any

import pytest

from app.core.messages import ExportMessages
from app.services.export.adapters.backup import _SECTIONS, _validate_params
from app.services.export.engine import ExportError


def _report(formats: dict[str, Any]) -> dict[str, Any]:
    return {"mode": "report", "formats": formats}


@pytest.mark.parametrize(
    "formats",
    [
        {"project": "pdf"},
        {"queue": "md", "counter_group": "xlsx"},
        {"calendar": "json"},
        {"file": {"native": "docx", "spreadsheet": "csv"}},
    ],
)
def test_report_formats_a_section_offers_are_accepted(formats):
    _validate_params(_report(formats), scope_kind="initiative")


@pytest.mark.parametrize(
    "formats",
    [
        # The envelope is what a report falls back to, not a choice for these.
        {"project": "json"},
        {"dashboard": "json"},
        # Tools with no report shape are left out of reports entirely.
        {"post": "json"},
        {"wiki": "pdf"},
        {"catalog": "json"},
        # A file's choices are per type, and only for the two with any.
        {"file": "pdf"},
        {"file": {"whiteboard": "json"}},
        {"file": {"smart_link": "md"}},
        {"file": {"native": "csv"}},
        {"not_a_tool": "pdf"},
        # A format that is not a string is refused rather than looked up.
        {"queue": {"md": True}},
    ],
)
def test_report_formats_a_section_does_not_offer_are_refused(formats):
    with pytest.raises(ExportError) as exc:
        _validate_params(_report(formats), scope_kind="initiative")
    assert exc.value.code == ExportMessages.EXPORT_INVALID_FORMAT


def test_report_formats_are_formats_the_tools_adapter_renders():
    for section in _SECTIONS:
        offered = set(section.report_formats).union(
            *section.type_report_formats.values()
        )
        assert offered <= set(section.adapter.formats), section.key
