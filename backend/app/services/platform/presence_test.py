"""The roll that decides how a person appears.

Three facts meet here — which sockets are open, what the account picked, and
when anyone last touched it — and these pin the rule that combines them,
because every surface that draws a dot asks this one object rather than
applying the rule for itself.
"""

import pytest

from app.models.platform.user import Presence
from app.services.platform import presence as presence_module
from app.services.platform.presence import (
    IDLE_AFTER_SECONDS,
    OnlineRoll,
    monotonic,
)


@pytest.fixture
def a_while_later(monkeypatch):
    """Move the clock the roll reads, without moving anyone's real one."""

    def go(seconds: float) -> None:
        base = presence_module.monotonic()
        monkeypatch.setattr(
            presence_module, "monotonic", lambda: base + seconds, raising=True
        )

    return go


def test_nobody_is_online_until_something_is_open() -> None:
    roll = OnlineRoll()

    assert roll.presence_of(7) is Presence.offline


def test_an_open_tab_shows_what_it_brought() -> None:
    roll = OnlineRoll()
    roll.arrived(7, Presence.busy)

    assert roll.presence_of(7) is Presence.busy


def test_appearing_offline_holds_with_a_tab_open() -> None:
    roll = OnlineRoll()
    roll.arrived(7, Presence.offline)

    assert roll.presence_of(7) is Presence.offline


def test_a_connect_that_started_first_cannot_undo_a_later_choice() -> None:
    """A socket reads the column somewhere on its way in and can arrive after a
    change that was made while it was still on its way."""
    roll = OnlineRoll()
    roll.arrived(7, Presence.online)
    read_at = monotonic()  # the connecting socket reads the row here

    roll.chose(7, Presence.offline)  # ...and a write lands before it registers
    roll.arrived(7, Presence.online, known_at=read_at)

    assert roll.presence_of(7) is Presence.offline


def test_a_choice_made_with_nothing_open_survives_the_connect_it_raced() -> None:
    """The same race, with the write landing while the first tab is still
    opening — so there is no socket for the write to find."""
    roll = OnlineRoll()
    read_at = monotonic()

    roll.chose(7, Presence.offline)
    roll.arrived(7, Presence.online, known_at=read_at)

    assert roll.presence_of(7) is Presence.offline


def test_a_socket_that_read_after_the_change_carries_it() -> None:
    """The rule is which value is later, not which caller is a socket."""
    roll = OnlineRoll()
    roll.chose(7, Presence.offline)

    roll.arrived(7, Presence.busy, known_at=monotonic())

    assert roll.presence_of(7) is Presence.busy


def test_closing_the_last_tab_puts_someone_offline() -> None:
    """Whatever they picked, nothing open is nothing to show."""
    roll = OnlineRoll()
    roll.arrived(7, Presence.busy)
    roll.arrived(7, Presence.busy)

    roll.left(7)
    assert roll.presence_of(7) is Presence.busy  # a second tab is still open

    roll.left(7)
    assert roll.presence_of(7) is Presence.offline


def test_a_change_is_followed_while_connected() -> None:
    roll = OnlineRoll()
    roll.arrived(7)

    roll.chose(7, Presence.busy)
    assert roll.presence_of(7) is Presence.busy


def test_a_change_by_someone_with_nothing_open_shows_nothing() -> None:
    """Recorded, so a connect in flight cannot undo it — but nothing open is
    still nothing to show."""
    roll = OnlineRoll()

    roll.chose(7, Presence.busy)

    assert roll.presence_of(7) is Presence.offline
    roll.arrived(7, Presence.busy)
    assert roll.presence_of(7) is Presence.busy


def test_the_socket_that_read_most_recently_wins() -> None:
    roll = OnlineRoll()
    roll.arrived(7, Presence.online)
    roll.arrived(7, Presence.busy)

    assert roll.presence_of(7) is Presence.busy


def test_an_open_tab_goes_idle_when_nobody_touches_it(a_while_later) -> None:
    """Nobody says they are away from their keyboard; the quiet says it."""
    roll = OnlineRoll()
    roll.arrived(7)

    a_while_later(IDLE_AFTER_SECONDS + 1)

    assert roll.presence_of(7) is Presence.idle


def test_a_sign_of_them_brings_them_back(a_while_later) -> None:
    roll = OnlineRoll()
    roll.arrived(7)
    a_while_later(IDLE_AFTER_SECONDS + 1)
    assert roll.presence_of(7) is Presence.idle

    roll.active(7)

    assert roll.presence_of(7) is Presence.online


def test_one_tab_being_used_keeps_the_person_here(a_while_later) -> None:
    """A person reading in one window is at their keyboard whatever the other
    windows are doing."""
    roll = OnlineRoll()
    roll.arrived(7)
    roll.arrived(7)
    a_while_later(IDLE_AFTER_SECONDS + 1)

    roll.active(7)

    assert roll.presence_of(7) is Presence.online


@pytest.mark.parametrize("chosen", [Presence.idle, Presence.busy, Presence.offline])
def test_a_guess_never_talks_over_what_someone_said(
    a_while_later, chosen: Presence
) -> None:
    """Everything but ``online`` is a statement, and going quiet is not an
    argument against one."""
    roll = OnlineRoll()
    roll.arrived(7, chosen)

    a_while_later(IDLE_AFTER_SECONDS + 1)

    assert roll.presence_of(7) is chosen


def test_picking_idle_holds_while_someone_is_typing() -> None:
    """Picked and inferred are the same state: someone who would rather look
    idle looks idle, whatever their keyboard says."""
    roll = OnlineRoll()
    roll.arrived(7, Presence.idle)

    roll.active(7)

    assert roll.presence_of(7) is Presence.idle


def test_a_sign_of_someone_with_nothing_open_is_ignored() -> None:
    roll = OnlineRoll()

    roll.active(7)

    assert roll.presence_of(7) is Presence.offline


def test_reconnecting_starts_the_clock_again(a_while_later) -> None:
    """Opening a tab is somebody doing something."""
    roll = OnlineRoll()
    roll.arrived(7)
    a_while_later(IDLE_AFTER_SECONDS + 1)
    roll.left(7)

    roll.arrived(7)

    assert roll.presence_of(7) is Presence.online
