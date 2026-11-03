"""Revision 0553 gives the overdue digest a row and a schedule of its own:
an "Assigned to you" email or push switched off switches it off too, and it
keeps the email's time, weekly where the email was."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_PATH = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20261028_0553_digests_keep_their_own_time.py"
)


def _separate():
    spec = importlib.util.spec_from_file_location(_PATH.stem, _PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.separate


def test_the_overdue_digest_keeps_what_the_account_had() -> None:
    doc = {
        "categories": {"assignments": {"in_app": False, "email": False}},
        "email": {"cadence": "weekly", "at": "08:00", "weekday": 3},
    }
    assert _separate()(doc) == {
        "categories": {
            "assignments": {"in_app": False, "email": False},
            "overdue": {"email": False},
        },
        "email": {"cadence": "weekly", "at": "08:00", "weekday": 3},
        "digests": {"overdue": {"at": "08:00", "weekday": 3, "cadence": "weekly"}},
    }


def test_an_account_that_chose_nothing_still_has_nothing() -> None:
    assert _separate()({}) == {}
