"""The security rules, as declared: what they watch exists, their numbers are
sane, and nothing high-volume is counted without a key."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.audit_events import AuditEventType
from app.core.security_rules import (
    BY_NAME,
    BY_WATCHED,
    RULES,
    SecurityRule,
    Signal,
    signal_envelope,
)

pytestmark = pytest.mark.always


def test_names_are_unique_and_fit_the_column():
    assert len(BY_NAME) == len(RULES)
    assert all(0 < len(rule.name) <= 64 for rule in RULES)


@pytest.mark.parametrize("rule", RULES, ids=lambda rule: rule.name)
def test_every_rule_is_well_formed(rule: SecurityRule):
    assert rule.watches, "a rule watches something"
    for watched in rule.watches:
        assert isinstance(watched, (AuditEventType, Signal))
    assert rule.threshold >= 1
    assert rule.window > timedelta(0)
    # Windows are fixed and aligned to the epoch, so they divide a day.
    assert timedelta(days=1).total_seconds() % rule.window.total_seconds() == 0
    assert rule.title.strip()


def test_every_signal_is_watched():
    """A signal nothing counts would be a rejection still nobody sees."""
    watched = {w for rule in RULES for w in rule.watches}
    assert set(Signal) <= watched


@pytest.mark.parametrize("signal", list(Signal))
def test_a_signal_is_keyed_by_where_it_came_from(signal: Signal):
    """A high-volume event counted without a key would be one bucket for
    everybody: one noisy address would trip it for all of them."""
    envelope = signal_envelope(signal, source_ip="203.0.113.7")
    for rule in BY_WATCHED[signal.value]:
        assert rule.key(envelope) == "203.0.113.7"
        assert rule.key(signal_envelope(signal, source_ip=None)) is None


def test_the_lookup_covers_exactly_what_is_watched():
    watched = {w.value for rule in RULES for w in rule.watches}
    assert set(BY_WATCHED) == watched


def test_only_a_promotion_to_operator_trips_the_role_rule():
    rule = BY_NAME["privileged_role_granted"]
    assert rule.when is not None
    assert rule.when({"detail": {"from": "member", "to": "owner"}})
    assert rule.when({"detail": {"from": "member", "to": "operator"}})
    assert not rule.when({"detail": {"from": "member", "to": "moderator"}})
