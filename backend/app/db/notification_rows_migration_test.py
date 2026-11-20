"""Revision 0522 carries each account's settings onto the nine rows: where
several rows became one, one of them decides; the rest go; a community's
level becomes its mute or its rows, and it keeps only rows off on every
channel."""

from __future__ import annotations

from app.testing.later_revisions import load_revision


def test_one_row_decides_and_the_rest_go() -> None:
    regroup = load_revision("20261018_0522_notification_rows_by_relationship").regroup
    assert regroup(
        {
            "categories": {
                "comments": {"email": False},
                "reactions": {"push": False},
                "replies": {"email": False},
                "posts": {"push": False},
                "account": {"email": False},
            },
            "email": {"cadence": "daily"},
        }
    ) == {
        "categories": {
            "account": {"email": False},
            "subscriptions": {"email": False},
            "news": {"push": False},
        },
        "email": {"cadence": "daily"},
    }


def test_a_communitys_level_becomes_its_mute_or_its_rows() -> None:
    off = {channel: False for channel in ("in_app", "email", "push", "desktop")}
    assert load_revision("20261018_0522_notification_rows_by_relationship").regroup(
        {
            "guilds": {
                "1": {"level": "nothing"},
                "2": {"level": "personal"},
                "3": {
                    "level": "everything",
                    "categories": {
                        "mentions": {"push": False},
                        "comments": off,
                        "approvals": {"email": False},
                    },
                },
                "4": {"level": "everything"},
            }
        }
    ) == {
        "guilds": {
            "1": {"muted": True},
            "2": {"categories": {"subscriptions": off, "news": off}},
            "3": {"categories": {"subscriptions": off}},
        }
    }
