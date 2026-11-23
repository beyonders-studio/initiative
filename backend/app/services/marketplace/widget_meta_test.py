"""The widget-meta mirror, and proof it still matches the browser's copy.

Two implementations read the same structure: ``validateWidgetMeta`` in
``frontend/src/lib/widgets/widgetMeta.ts`` reads it out of the sandbox, and
``widget_meta.py`` reads it out of a listing. Neither can call the other, so the
only thing keeping them equal is a test that fails when they stop being.

``TestMirrorsTheFrontend`` is that test: it reads the TypeScript file and pins
every limit against the Python constant. A limit changed on one side, or a new
limit added to the frontend with no counterpart here, fails here — rather than
in production, where the symptom would be a widget the catalog accepted and the
browser then trimmed differently.
"""

from pathlib import Path

import pytest

from app.services.marketplace import widget_meta
from app.services.marketplace.widget_meta import (
    localized_text,
    validate_widget_meta,
)

pytestmark = pytest.mark.always


# backend/app/services/marketplace/<this file> -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[4]
_FRONTEND = _REPO_ROOT / "frontend"

#: The two places the vendored contract lands. The backend validator reads one
#: and the browser's reads the other, and they are written by a single refresh.
_BACKEND_CONTRACT = (
    Path(__file__).resolve().parents[3]
    / "vendor"
    / "plugin-kit"
    / "manifest.contract.json"
)
_FRONTEND_CONTRACT = _FRONTEND / "src" / "contract" / "manifest.contract.json"


class TestTheBrowserTrimsByTheSameNumbers:
    """A widget's meta is validated here over catalog content and in the browser
    over what a module returns. Neither can call the other, so the numbers they
    trim by have to be one set — otherwise a widget is accepted by the catalog
    and then re-trimmed differently on screen.

    They used to be two hand-written sets held together by a test that parsed
    ``META_LIMITS`` out of the TypeScript. Now both sides read the vendored
    contract, so the only thing left to check is that the two copies of it are
    the same file.
    """

    def test_both_copies_are_the_same_contract(self):
        if not _FRONTEND.is_dir():
            pytest.skip("frontend tree not present in this checkout")
        # Present but moved is a real failure: the browser would fall back to
        # nothing, and silently passing is how the two would drift again.
        assert _FRONTEND_CONTRACT.is_file(), (
            f"no vendored contract at {_FRONTEND_CONTRACT}"
        )
        assert _BACKEND_CONTRACT.read_text(encoding="utf-8") == (
            _FRONTEND_CONTRACT.read_text(encoding="utf-8")
        ), "the two vendored copies differ — run backend/scripts/refresh_plugin_kit.py"


class TestLocalizedText:
    @pytest.mark.parametrize(
        ("value", "cap", "expected"),
        [
            ({"en": "Chart"}, 120, {"en": "Chart"}),
            # Meta is presentation: trimmed and truncated rather than refused,
            # which is what the browser does with the same input.
            ({"en": "  Chart  "}, 120, {"en": "Chart"}),
            ({"en": "abcdef"}, 3, {"en": "abc"}),
            # A key that is not a language tag is dropped.
            *(
                ({tag: "Chart", "en": "Chart"}, 120, {"en": "Chart"})
                for tag in ("en_US", "en US", "toolongalanguagetag", "", "en/../..")
            ),
            # A non-string value is dropped rather than coerced.
            ({"en": {"nested": "object"}, "de": "Diagramm"}, 120, {"de": "Diagramm"}),
            ({}, 120, None),
            ({"en": "   "}, 120, None),
            ("Chart", 120, None),
            (["Chart"], 120, None),
            # The scan stops at the locale cap rather than reading everything a
            # module supplies.
            (
                {
                    **{f"l{i:03d}": "x" for i in range(widget_meta.MAX_LOCALES + 5)},
                    "en": "Chart",
                },
                120,
                None,
            ),
        ],
    )
    def test_text_keeps_only_what_is_usable(self, value, cap, expected):
        assert localized_text(value, cap) == expected


class TestValidateWidgetMeta:
    def test_a_widget_without_a_name_has_no_usable_meta(self):
        assert validate_widget_meta({"description": {"en": "no name"}}) is None
        assert validate_widget_meta(None) is None
        assert validate_widget_meta("Chart") is None

    def test_meta_is_rebuilt_from_checked_parts(self):
        meta = validate_widget_meta(
            {
                "name": {"en": "Chart", "de": "Diagramm"},
                "description": {"en": "Draws a series."},
                "options": {
                    "mark": {
                        "label": {"en": "Mark"},
                        "values": {"bar": {"en": "Bar"}, "line": {"en": "Line"}},
                    }
                },
                "render": "function () {}",
                "__proto__": {"en": "nope"},
            }
        )
        assert meta == {
            "name": {"en": "Chart", "de": "Diagramm"},
            "description": {"en": "Draws a series."},
            "options": {
                "mark": {
                    "label": {"en": "Mark"},
                    "values": {"bar": {"en": "Bar"}, "line": {"en": "Line"}},
                }
            },
        }

    def test_an_option_without_a_label_is_dropped(self):
        meta = validate_widget_meta(
            {"name": {"en": "Chart"}, "options": {"mark": {"values": {}}}}
        )
        assert meta == {"name": {"en": "Chart"}}

    def test_option_values_must_be_named(self):
        # A positional list cannot say which value it labels, so it is dropped
        # rather than read by index.
        meta = validate_widget_meta(
            {
                "name": {"en": "Chart"},
                "options": {"mark": {"label": {"en": "Mark"}, "values": ["Bar"]}},
            }
        )
        assert meta is not None
        assert meta["options"] == {"mark": {"label": {"en": "Mark"}}}
