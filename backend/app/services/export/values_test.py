"""How export cells write a plug-in field's value and a moment."""

from datetime import datetime, timezone

from app.services.export.values import moment, plugin_value


def test_a_plug_in_value_is_written_as_the_page_draws_its_kind():
    assert plugin_value({"text": "Ready", "tone": "positive"}, "badge", "en", None) == (
        "Ready"
    )
    assert plugin_value(75, "scale", "en", None) == 75
    assert plugin_value(
        {"url": "https://x.test", "text": "PR"}, "link", "en", None
    ) == ("PR")
    # A value kept beside a state, and a list's elements, zero among them.
    assert plugin_value({"value": 2, "state": {"ci": "ok"}}, "number", "en", None) == 2
    assert plugin_value(
        [{"ref": "a", "value": 0}, {"ref": "b", "value": 5}], "number", "en", None
    ) == ("0, 5")
    # A value of another shape draws nothing, as on the page, rather than
    # failing the export.
    assert plugin_value("pending", "number", "en", None) is None
    assert plugin_value({"value": "x"}, "scale", "en", None) is None
    assert plugin_value({"url": "javascript:x"}, "link", "en", None) is None
    # An unset checkbox is no value, not "No".
    assert plugin_value(None, "checkbox", "en", None) is None
    assert plugin_value(False, "checkbox", "en", None) == "No"


def test_a_moment_keeps_its_time_in_the_readers_zone():
    noon = datetime(2026, 10, 20, 19, 30, tzinfo=timezone.utc)
    assert moment(noon, "America/Los_Angeles") == "2026-10-20 12:30 PDT"
    assert moment("2026-10-20T19:30:00+00:00", None) == "2026-10-20 19:30 UTC"
