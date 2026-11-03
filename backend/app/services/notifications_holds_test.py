"""Holds: pause, quiet hours, and being at the keyboard already.

Three sources, one idea. A hold names the moment it lifts; email defers to the
latest lift and push refuses while any is in force, and the bell collects
throughout. What arrives when a hold ends is the content itself, by email, out
of the outbox — the push that goes with it is only a count.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.notification_categories import Channel, NotificationCategory
from app.models.platform.notice_outbox import NoticeOutboxItem
from app.models.platform.notification import NotificationType
from app.services.notifications import _run_hold_summary_pass
from app.services.platform import notification_prefs, user_notifications
from app.services.platform.notification_prefs import HoldKind
from app.testing import (
    create_guild,
    create_user,
    push_switched_on,
    set_notification_prefs,
)
from app.testing.sockets import settle
from app.services.platform import rules

NIGHT = {"quiet_hours": {"start": "22:00", "end": "07:00"}}
MENTION = NotificationType.mention
MENTIONS = NotificationCategory.mentions


def _at(hour: int, day: int = 9) -> datetime:
    return datetime(2026, 9, day, hour, 0, tzinfo=timezone.utc)


#: Well before any moment these tests call "now", so the pause this builds is
#: one that is already running. A pause booked for later is written out in
#: full, because when it starts is the point of those.
_LONG_AGO = datetime(2026, 9, 1, tzinfo=timezone.utc)


def _paused_until(moment: datetime, *, since: datetime | None = None) -> dict:
    return {
        "pause": {
            "since": (since or _LONG_AGO).isoformat(),
            "until": moment.isoformat(),
        }
    }


# --- what is holding, and when it lifts --------------------------------------


def test_nothing_holds_by_default():
    assert notification_prefs.holds_in_force({}, tz_name="UTC", now=_at(12)) == []


def test_a_running_pause_holds_until_its_end():
    prefs = _paused_until(_at(9, day=20))
    holds = notification_prefs.holds_in_force(prefs, tz_name="UTC", now=_at(12))
    assert [hold.kind for hold in holds] == [HoldKind.pause]
    assert holds[0].lifts_at == _at(9, day=20)


def test_a_lapsed_pause_holds_nothing():
    prefs = _paused_until(_at(9, day=8))
    assert notification_prefs.holds_in_force(prefs, tz_name="UTC", now=_at(12)) == []


def test_a_pause_booked_for_next_week_holds_nothing_yet():
    """Booking a holiday is not the same as being on it."""
    prefs = {
        "pause": {
            "since": _at(9, day=25).isoformat(),
            "until": _at(9, day=30).isoformat(),
        }
    }
    assert notification_prefs.holds_in_force(prefs, tz_name="UTC", now=_at(12)) == []
    assert notification_prefs.reachable(
        prefs,
        category=MENTIONS,
        channel=Channel.push,
        tz_name="UTC",
        now=_at(12),
    )


def test_a_pause_booked_for_next_week_holds_once_it_starts():
    prefs = {
        "pause": {
            "since": _at(9, day=25).isoformat(),
            "until": _at(9, day=30).isoformat(),
        }
    }
    holds = notification_prefs.holds_in_force(prefs, tz_name="UTC", now=_at(12, day=26))
    assert [hold.kind for hold in holds] == [HoldKind.pause]
    assert holds[0].lifts_at == _at(9, day=30)


def test_mail_timed_to_land_inside_a_booked_pause_waits_for_the_end():
    """The hold is not in force when the message is written, so nothing above
    catches it — but arriving in the middle of somebody's holiday is exactly
    what booking one is meant to prevent."""
    prefs = {
        "email": {"cadence": "daily", "at": "08:00"},
        "pause": {
            "since": _at(0, day=20).isoformat(),
            "until": _at(9, day=30).isoformat(),
        },
    }
    due = notification_prefs.email_due_at(
        prefs,
        category=NotificationCategory.subscriptions,
        tz_name="UTC",
        now=_at(12, day=19),
    )
    assert due == _at(9, day=30)


def test_mail_due_before_a_booked_pause_still_goes():
    prefs = {
        "pause": {
            "since": _at(0, day=25).isoformat(),
            "until": _at(9, day=30).isoformat(),
        }
    }
    now = _at(12)
    assert (
        notification_prefs.email_due_at(
            prefs, category=MENTIONS, tz_name="UTC", now=now
        )
        == now
    )


def test_a_window_closing_before_a_booked_pause_starts_is_still_reported():
    """A pause suppresses the nightly summary only while it is actually on."""
    prefs = {
        **NIGHT,
        "pause": {
            "since": _at(0, day=25).isoformat(),
            "until": _at(9, day=30).isoformat(),
        },
    }
    lift = notification_prefs.last_lift(prefs, tz_name="UTC", now=_at(8))
    assert lift is not None
    assert lift.kind is HoldKind.quiet_hours


def test_the_nightly_window_holds_until_it_closes():
    holds = notification_prefs.holds_in_force(NIGHT, tz_name="UTC", now=_at(23))
    assert [hold.kind for hold in holds] == [HoldKind.quiet_hours]
    assert holds[0].lifts_at == _at(7, day=10)


def test_being_at_the_keyboard_holds_for_the_idle_window():
    seen = _at(12) - timedelta(minutes=3)
    holds = notification_prefs.holds_in_force(
        {}, tz_name="UTC", last_active_at=seen, now=_at(12)
    )
    assert [hold.kind for hold in holds] == [HoldKind.present]
    assert holds[0].lifts_at == seen + notification_prefs.PRESENT_WITHIN


def test_having_been_away_a_while_holds_nothing():
    assert (
        notification_prefs.holds_in_force(
            {}, tz_name="UTC", last_active_at=_at(10), now=_at(12)
        )
        == []
    )


def test_never_seen_reads_as_away():
    """Not knowing where somebody is delivers rather than holds."""
    assert (
        notification_prefs.holds_in_force(
            {}, tz_name="UTC", last_active_at=None, now=_at(12)
        )
        == []
    )


def test_the_presence_hold_can_be_switched_off():
    prefs = {"away": {"respect": False}}
    assert (
        notification_prefs.holds_in_force(
            prefs,
            tz_name="UTC",
            last_active_at=_at(12) - timedelta(minutes=1),
            now=_at(12),
        )
        == []
    )


def test_a_stamp_from_the_future_holds_for_the_ordinary_window():
    """Two clocks disagreeing must not hold somebody's mail indefinitely."""
    holds = notification_prefs.holds_in_force(
        {}, tz_name="UTC", last_active_at=_at(18), now=_at(12)
    )
    assert holds[0].lifts_at == _at(12) + notification_prefs.PRESENT_WITHIN


# --- what each channel does about them ---------------------------------------


@pytest.mark.parametrize(
    "prefs,extra",
    [
        (_paused_until(_at(9, day=20)), {}),
        (NIGHT, {}),
        ({}, {"last_active_at": _at(12) - timedelta(minutes=1)}),
    ],
    ids=["pause", "quiet-hours", "already-here"],
)
def test_push_is_refused_while_anything_holds(prefs, extra):
    assert not notification_prefs.reachable(
        prefs,
        category=MENTIONS,
        channel=Channel.push,
        tz_name="UTC",
        now=_at(23) if prefs is NIGHT else _at(12),
        **extra,
    )


@pytest.mark.parametrize(
    "prefs,extra,held",
    [
        (_paused_until(_at(9, day=20)), {}, True),
        (NIGHT, {}, True),
        ({}, {"last_active_at": _at(12) - timedelta(minutes=1)}, False),
    ],
    ids=["pause", "quiet-hours", "already-here"],
)
def test_the_desktop_keeps_every_hold_but_presence(prefs, extra, held):
    """The desktop app checks its own window instead: activity a minute ago
    says nothing about whether it is in front now."""
    reachable = notification_prefs.reachable(
        prefs,
        category=MENTIONS,
        channel=Channel.desktop,
        tz_name="UTC",
        now=_at(23) if prefs is NIGHT else _at(12),
        **extra,
    )
    assert reachable is not held


@pytest.mark.parametrize(
    "prefs,extra",
    [
        (_paused_until(_at(9, day=20)), {}),
        (NIGHT, {}),
        ({}, {"last_active_at": _at(12) - timedelta(minutes=1)}),
    ],
    ids=["pause", "quiet-hours", "already-here"],
)
def test_the_bell_collects_through_every_hold(prefs, extra):
    assert notification_prefs.reachable(
        prefs,
        category=MENTIONS,
        channel=Channel.in_app,
        tz_name="UTC",
        now=_at(23) if prefs is NIGHT else _at(12),
        **extra,
    )


def test_email_is_deferred_to_the_latest_lift_not_refused():
    """Two holds at once compose: the later one decides."""
    prefs = {**NIGHT, **_paused_until(_at(9, day=20))}
    due = notification_prefs.email_due_at(
        prefs, category=MENTIONS, tz_name="UTC", now=_at(23)
    )
    assert due == _at(9, day=20)


def test_the_presence_hold_is_never_renewed():
    """Computed once, at ten minutes — not deferred again for as long as
    somebody keeps working, which would be an off switch by another name."""
    seen = _at(12) - timedelta(minutes=1)
    due = notification_prefs.email_due_at(
        {}, category=MENTIONS, tz_name="UTC", last_active_at=seen, now=_at(12)
    )
    assert due - _at(12) <= notification_prefs.PRESENT_WITHIN


def test_a_pause_holds_even_a_direct_mention():
    """Standing down means standing down. A hold you have to keep checking is
    not one."""
    prefs = _paused_until(_at(9, day=20))
    due = notification_prefs.email_due_at(
        prefs, category=MENTIONS, tz_name="UTC", now=_at(12)
    )
    assert due == _at(9, day=20)
    assert not notification_prefs.reachable(
        prefs,
        category=MENTIONS,
        channel=Channel.push,
        tz_name="UTC",
        now=_at(12),
    )


# --- which hold lifted -------------------------------------------------------


def test_a_window_still_running_has_nothing_to_summarise():
    assert notification_prefs.last_lift(NIGHT, tz_name="UTC", now=_at(23)) is None


def test_the_window_that_just_closed_is_found():
    lift = notification_prefs.last_lift(NIGHT, tz_name="UTC", now=_at(8))
    assert lift is not None
    assert lift.kind is HoldKind.quiet_hours
    assert lift.closed == _at(7)
    # Overnight: it opened the evening before.
    assert lift.opened == _at(22, day=8)


def test_a_long_past_window_is_not_summarised():
    """A "while you were away" about the night before last is noise."""
    assert notification_prefs.last_lift(NIGHT, tz_name="UTC", now=_at(20)) is None


def test_a_pause_reports_the_whole_stretch_it_covered():
    since = _at(9, day=1)
    lift = notification_prefs.last_lift(
        _paused_until(_at(7), since=since), tz_name="UTC", now=_at(8)
    )
    assert lift is not None
    assert lift.kind is HoldKind.pause
    assert (lift.opened, lift.closed) == (since, _at(7))


def test_a_window_closing_inside_a_pause_is_not_reported_on_its_own():
    """The pause is the outer hold and will report the whole stretch."""
    prefs = {**NIGHT, **_paused_until(_at(9, day=20))}
    assert notification_prefs.last_lift(prefs, tz_name="UTC", now=_at(8)) is None


# --- what arrives when one lifts ---------------------------------------------


async def _summaries(session: AsyncSession) -> list[NoticeOutboxItem]:
    """The summaries handed to the notice worker to push."""
    return list(
        (
            await session.exec(
                select(NoticeOutboxItem).where(NoticeOutboxItem.kind == "push")
            )
        ).all()
    )


def _summary_alerts(socket) -> list[dict]:
    return [
        frame
        for frame in socket.sent
        if (frame.get("resource"), frame.get("action")) == ("alert", "summary")
    ]


async def test_the_summary_counts_what_happened_and_goes_once(
    session: AsyncSession, account_socket
):
    user = await create_user(session, email="hold-summary@example.com", timezone="UTC")
    guild = await create_guild(session, creator=user)
    await set_notification_prefs(session, user, dict(NIGHT))
    desktop = account_socket(user.id)

    for _ in range(2):
        notification = await user_notifications.create_notification(
            session,
            user_id=user.id,
            notification_type=MENTION,
            data={"community_id": guild.id},
        )
        assert notification is not None
        notification.created_at = _at(23, day=8)
    await session.commit()

    with push_switched_on():
        await _run_hold_summary_pass(session, now=_at(8))
        [summary] = await _summaries(session)
        assert "2" in (summary.push_body or "")

        # The same window is not summarised twice.
        await _run_hold_summary_pass(session, now=_at(9))
        assert len(await _summaries(session)) == 1
    await settle()
    assert len(_summary_alerts(desktop)) == 1


async def test_the_desktop_hears_the_summary_with_mobile_off(
    session: AsyncSession, account_socket
):
    user = await create_user(session, timezone="UTC")
    guild = await create_guild(session, creator=user)
    await set_notification_prefs(
        session, user, {**NIGHT, "categories": {"mentions": {"push": False}}}
    )
    notification = await user_notifications.create_notification(
        session,
        user_id=user.id,
        notification_type=MENTION,
        data={"community_id": guild.id},
    )
    assert notification is not None
    notification.created_at = _at(23, day=8)
    await session.commit()
    desktop = account_socket(user.id)

    with push_switched_on():
        await _run_hold_summary_pass(session, now=_at(8))
    await settle()

    assert await _summaries(session) == []
    assert len(_summary_alerts(desktop)) == 1


async def test_a_community_with_push_off_is_left_out_of_the_summary(
    session: AsyncSession, account_socket
):
    user = await create_user(session, timezone="UTC")
    guild = await create_guild(session, creator=user)
    await rules.put(session, "allow_push_notifications", False, guild_id=guild.id)
    await set_notification_prefs(session, user, dict(NIGHT))
    notification = await user_notifications.create_notification(
        session,
        user_id=user.id,
        notification_type=MENTION,
        data={"community_id": guild.id},
    )
    assert notification is not None
    notification.created_at = _at(23, day=8)
    await session.commit()
    desktop = account_socket(user.id)

    with push_switched_on():
        await _run_hold_summary_pass(session, now=_at(8))
    await settle()

    assert await _summaries(session) == []
    assert _summary_alerts(desktop) == []


async def test_a_quiet_night_is_not_reported(session: AsyncSession):
    user = await create_user(session, email="hold-quiet@example.com", timezone="UTC")
    await create_guild(session, creator=user)
    await set_notification_prefs(session, user, dict(NIGHT))

    with push_switched_on():
        await _run_hold_summary_pass(session, now=_at(8))
    assert await _summaries(session) == []


async def test_a_lifted_pause_is_cleared_from_the_document(session: AsyncSession):
    """So the settings page stops showing a stand-down that has ended, and the
    document stays sparse."""
    user = await create_user(session, email="hold-pause@example.com", timezone="UTC")
    guild = await create_guild(session, creator=user)
    await set_notification_prefs(session, user, _paused_until(_at(7)))

    notification = await user_notifications.create_notification(
        session,
        user_id=user.id,
        notification_type=MENTION,
        data={"community_id": guild.id},
    )
    assert notification is not None
    notification.created_at = _at(12, day=8)
    await session.commit()

    with push_switched_on():
        await _run_hold_summary_pass(session, now=_at(8))
    assert len(await _summaries(session)) == 1

    doc = await notification_prefs.load_prefs(session, user.id)
    assert "pause" not in doc
