"""Which plug-in API contract this build serves, and which plug-ins run on it."""

from __future__ import annotations

import pytest

from app.services.marketplace.plugin_api import (
    PLUGIN_API_VERSION,
    check_min_plugin_api,
    serves_plugin_api,
)


@pytest.mark.parametrize(
    ("needed", "served", "runs"),
    [
        (None, "4.1.1", True),
        ("", "4.1.1", True),
        ("4.1", "4.1.1", True),
        ("4.0", "4.1.1", True),
        ("4.1", "4.1.0", True),
        ("4.2", "4.1.1", False),
        ("3.9", "4.1.1", False),
        ("5.0", "4.1.1", False),
        ("4.10", "4.9.0", False),
        ("4.9", "4.10.0", True),
        ("4.2", "4.2.0-rc.1", True),
    ],
)
def test_a_server_runs_a_plugin_of_its_major_at_or_below_its_minor(
    needed, served, runs
):
    assert serves_plugin_api(needed, served) is runs


def test_the_server_answers_for_its_own_contract_by_default():
    major, minor, *_ = PLUGIN_API_VERSION.split(".")
    assert serves_plugin_api(f"{major}.{minor}") is True
    assert serves_plugin_api(f"{major}.{int(minor) + 1}") is False
    assert serves_plugin_api(f"{int(major) + 1}.0") is False


@pytest.mark.parametrize("value", ["4", "4.1.0", "v4.1", "4.x", " 4.1", "4.1\n", 4.1])
def test_a_floor_that_is_not_major_minor_is_refused(value):
    with pytest.raises(ValueError, match="MAJOR.MINOR"):
        check_min_plugin_api(value)
    assert serves_plugin_api(value) is False
