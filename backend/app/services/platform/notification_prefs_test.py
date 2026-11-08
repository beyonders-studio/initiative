"""Resolution order, each community's mute and rows, and the quiet-hours
window."""

from datetime import UTC, datetime

from app.core.notification_categories import Channel, NotificationCategory
from app.services.platform.notification_prefs import (
    in_quiet_hours,
    is_muted,
    quiet_hours,
    row_is_off,
    wants,
)


def test_empty_prefs_take_every_default():
    for channel in Channel:
        assert wants({}, category=NotificationCategory.mentions, channel=channel)
        assert wants(None, category=NotificationCategory.mentions, channel=channel)


def test_account_override_beats_the_default():
    prefs = {"categories": {"subscriptions": {"in_app": False}}}
    assert not wants(
        prefs,
        category=NotificationCategory.subscriptions,
        channel=Channel.in_app,
    )
    # Only the channel named moves.
    assert wants(
        prefs, category=NotificationCategory.subscriptions, channel=Channel.email
    )
    # And only the category named — the split from mentions is the whole point.
    assert wants(prefs, category=NotificationCategory.mentions, channel=Channel.in_app)


def test_a_row_off_in_one_community_is_off_there_alone():
    prefs = {
        "guilds": {
            "7": {
                "categories": {
                    "subscriptions": {channel.value: False for channel in Channel}
                }
            }
        }
    }
    assert row_is_off(prefs, 7, NotificationCategory.subscriptions)
    assert not row_is_off(prefs, 8, NotificationCategory.subscriptions)
    assert not row_is_off(prefs, 7, NotificationCategory.mentions)
    for channel in Channel:
        assert not wants(
            prefs,
            category=NotificationCategory.subscriptions,
            channel=channel,
            guild_id=7,
        )
        # A different community keeps the account's settings.
        assert wants(
            prefs,
            category=NotificationCategory.subscriptions,
            channel=channel,
            guild_id=8,
        )


def test_the_bell_is_gateable():
    """The whole reason in_app exists as a channel."""
    prefs = {"categories": {"subscriptions": {"in_app": False}}}
    assert not wants(
        prefs,
        category=NotificationCategory.subscriptions,
        channel=Channel.in_app,
    )


def test_a_muted_community_says_nothing_including_a_mention():
    prefs = {"guilds": {"7": {"muted": True}}}
    assert is_muted(prefs, 7)
    assert not is_muted(prefs, 8)
    assert not is_muted({}, None)
    for category in (
        NotificationCategory.mentions,
        NotificationCategory.assignments,
        NotificationCategory.subscriptions,
        NotificationCategory.news,
    ):
        for channel in Channel:
            assert not wants(
                prefs,
                category=category,
                channel=channel,
                guild_id=7,
            )


def test_a_mute_cannot_reach_a_notification_that_has_no_community():
    """An account notice arrives however the communities are set."""
    prefs = {"guilds": {"7": {"muted": True}}}
    assert wants(
        prefs,
        category=NotificationCategory.account,
        channel=Channel.in_app,
        guild_id=7,
    )
    assert wants(
        prefs,
        category=NotificationCategory.direct_messages,
        channel=Channel.in_app,
        guild_id=None,
    )


def test_a_category_with_nothing_to_switch_is_not_a_preference():
    """Cases reach whoever works them: no setting, and no mute, turns them
    down."""
    prefs = {
        "categories": {"cases": {channel.value: False for channel in Channel}},
        "guilds": {"7": {"muted": True}},
    }
    for channel in Channel:
        assert wants(
            prefs, category=NotificationCategory.cases, channel=channel, guild_id=7
        )


def test_non_mutable_channels_ignore_overrides():
    prefs = {"categories": {"account": {"in_app": False}}}
    assert wants(
        prefs,
        category=NotificationCategory.account,
        channel=Channel.in_app,
    )
    # The reachable channels are still the account's own choice.
    assert not wants(
        {"categories": {"account": {"email": False}}},
        category=NotificationCategory.account,
        channel=Channel.email,
    )


def test_quiet_hours_needs_both_ends_and_a_real_span():
    assert quiet_hours({}) is None
    assert quiet_hours({"quiet_hours": {"start": "22:00"}}) is None
    assert quiet_hours({"quiet_hours": {"start": "22:00", "end": "22:00"}}) is None
    assert quiet_hours({"quiet_hours": {"start": "boom", "end": "07:00"}}) is None
    assert quiet_hours({"quiet_hours": {"start": "22:00", "end": "07:00"}}) is not None


def _at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, 9, hour, minute, tzinfo=UTC)


def test_quiet_hours_wraps_overnight():
    prefs = {"quiet_hours": {"start": "22:00", "end": "07:00"}}
    assert in_quiet_hours(prefs, tz_name="UTC", now=_at(23))
    assert in_quiet_hours(prefs, tz_name="UTC", now=_at(3))
    assert in_quiet_hours(prefs, tz_name="UTC", now=_at(22))
    assert not in_quiet_hours(prefs, tz_name="UTC", now=_at(7))
    assert not in_quiet_hours(prefs, tz_name="UTC", now=_at(12))


def test_quiet_hours_within_one_day():
    prefs = {"quiet_hours": {"start": "09:00", "end": "17:00"}}
    assert in_quiet_hours(prefs, tz_name="UTC", now=_at(12))
    assert not in_quiet_hours(prefs, tz_name="UTC", now=_at(20))


def test_quiet_hours_is_read_in_the_accounts_timezone():
    prefs = {"quiet_hours": {"start": "22:00", "end": "07:00"}}
    # 23:00 UTC is 19:00 in New York — inside the window in UTC, well outside
    # it there.
    assert in_quiet_hours(prefs, tz_name="UTC", now=_at(23))
    assert not in_quiet_hours(prefs, tz_name="America/New_York", now=_at(23))


def test_unknown_timezone_falls_back_rather_than_raising():
    prefs = {"quiet_hours": {"start": "22:00", "end": "07:00"}}
    assert in_quiet_hours(prefs, tz_name="Mars/Olympus", now=_at(23))
