"""The security rules: what, seen often enough, opens a security case.

A rule watches audit events — or **signals**, the high-volume rejections that
are counted and never written down — and counts them per key over a fixed
window. When a key's count reaches the rule's threshold within one window, the
deployment opens a security case about it (``app.services.platform
.security_signals``), and keeps adding to that case while the run lasts rather
than opening one per event.

The thresholds are constants, reviewed in code like everything else that
decides what the people running a server are woken for, rather than
settings.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from enum import Enum
from typing import Any

from app.core.audit_events import AuditEventType

#: An audit line, or the stand-in a signal makes (see :func:`signal_envelope`).
Envelope = Mapping[str, Any]


class Signal(str, Enum):
    """A rejection too frequent to write down one line at a time. Counted by
    the rules, and written down only when one of them trips."""

    #: A request refused for failing its cross-site check.
    csrf_rejected = "csrf_rejected"
    #: A request answered 429 for going too fast.
    rate_limited = "rate_limited"
    #: A captcha answer the provider refused.
    captcha_rejected = "captcha_rejected"


class Severity(str, Enum):
    """How urgently a tripped rule wants somebody, as the case records it."""

    high = "high"
    medium = "medium"
    low = "low"
    info = "info"


Watched = AuditEventType | Signal


def signal_envelope(signal: Signal, *, source_ip: str | None) -> dict[str, Any]:
    """What a rule sees of a signal: the shape of an audit line, carrying
    only where it came from."""
    return {
        "event_type": signal.value,
        "event_uuid": None,
        "actor_user_id": None,
        "target_user_id": None,
        "guild_id": None,
        "target": None,
        "detail": {},
        "context": {"source_ip": source_ip} if source_ip else None,
    }


# -- What a rule counts by ------------------------------------------------------


def source_ip(envelope: Envelope) -> str | None:
    context = envelope.get("context") or {}
    return context.get("source_ip")


def subject_user(envelope: Envelope) -> str | None:
    """The account it happened to: the target, else whoever acted."""
    user = envelope.get("target_user_id") or envelope.get("actor_user_id")
    return str(user) if user is not None else None


def actor(envelope: Envelope) -> str | None:
    user = envelope.get("actor_user_id")
    return str(user) if user is not None else None


def target(envelope: Envelope) -> str | None:
    named = envelope.get("target") or {}
    return str(named["id"]) if named.get("id") is not None else None


def actor_in_community(envelope: Envelope) -> str | None:
    """One person breaking glass on one community: the content grant and the
    settings grant it issues together are one occasion."""
    user = envelope.get("actor_user_id")
    if user is None:
        return None
    return f"{user}:{envelope.get('guild_id')}"


def replay_source(envelope: Envelope) -> str | None:
    """Which channel was replayed into, and for which install or key."""
    detail = envelope.get("detail") or {}
    channel = detail.get("channel")
    if channel is None:
        return None
    return f"{channel}:{detail.get('install') or target(envelope) or '-'}"


def promoted_to_operator(envelope: Envelope) -> bool:
    return (envelope.get("detail") or {}).get("to") in {"operator", "owner"}


# -- The rules ------------------------------------------------------------------


@dataclass(frozen=True)
class SecurityRule:
    #: Stable: it is part of every case key and every counted row.
    name: str
    #: What a person reading the case is told it is.
    title: str
    watches: frozenset[Watched]
    #: What one count is of: an address, an account, a key. ``None`` is not
    #: counted.
    key: Callable[[Envelope], str | None]
    #: How many in one window open the case.
    threshold: int
    window: timedelta
    severity: Severity
    #: Narrows ``watches`` past the event's type.
    when: Callable[[Envelope], bool] | None = field(default=None)


_DAY = timedelta(hours=24)

RULES: tuple[SecurityRule, ...] = (
    SecurityRule(
        name="sign_in_spray",
        title="Many failed sign-ins from one address",
        watches=frozenset({AuditEventType.AUTH_SIGN_IN_FAILED}),
        key=source_ip,
        threshold=50,
        window=timedelta(minutes=10),
        severity=Severity.high,
    ),
    SecurityRule(
        name="account_held",
        title="An account's sign-in was locked",
        watches=frozenset({AuditEventType.AUTH_SIGN_IN_LOCKED}),
        key=subject_user,
        threshold=1,
        window=_DAY,
        severity=Severity.medium,
    ),
    SecurityRule(
        name="refresh_reuse",
        title="A spent session token was used again",
        watches=frozenset({AuditEventType.AUTH_REFRESH_REUSE_DETECTED}),
        key=subject_user,
        threshold=1,
        window=_DAY,
        severity=Severity.high,
    ),
    SecurityRule(
        name="second_factor_guessing",
        title="Many wrong second-factor codes for one account",
        watches=frozenset({AuditEventType.AUTH_SECOND_FACTOR_FAILED}),
        key=subject_user,
        threshold=10,
        window=timedelta(hours=1),
        severity=Severity.high,
    ),
    SecurityRule(
        name="break_glass_review",
        title="An operator broke glass on a community",
        watches=frozenset({AuditEventType.ACCESS_GRANT_SELF_ISSUED}),
        key=actor_in_community,
        threshold=1,
        window=_DAY,
        severity=Severity.info,
    ),
    SecurityRule(
        name="privileged_role_granted",
        title="An account was made an operator or owner",
        watches=frozenset({AuditEventType.USER_PLATFORM_ROLE_CHANGED}),
        key=subject_user,
        threshold=1,
        window=_DAY,
        severity=Severity.medium,
        when=promoted_to_operator,
    ),
    SecurityRule(
        name="operator_reset_second_factor",
        title="Staff cleared an account's second factor",
        watches=frozenset({AuditEventType.AUTH_SECOND_FACTOR_RESET}),
        key=subject_user,
        threshold=1,
        window=_DAY,
        severity=Severity.low,
    ),
    SecurityRule(
        name="bulk_user_export",
        title="The user list was exported",
        watches=frozenset({AuditEventType.PLATFORM_USERS_EXPORTED}),
        key=actor,
        threshold=1,
        window=_DAY,
        severity=Severity.low,
    ),
    SecurityRule(
        name="replay",
        title="A one-time token or assertion was presented again",
        watches=frozenset({AuditEventType.SECURITY_REPLAY_REJECTED}),
        key=replay_source,
        threshold=5,
        window=timedelta(minutes=10),
        severity=Severity.high,
    ),
    SecurityRule(
        name="csrf_burst",
        title="Many cross-site request refusals from one address",
        watches=frozenset({Signal.csrf_rejected}),
        key=source_ip,
        threshold=100,
        window=timedelta(minutes=10),
        severity=Severity.medium,
    ),
    SecurityRule(
        name="rate_limit_burst",
        title="One address kept hitting the rate limit",
        watches=frozenset({Signal.rate_limited}),
        key=source_ip,
        threshold=1000,
        window=timedelta(minutes=10),
        severity=Severity.low,
    ),
    SecurityRule(
        name="captcha_burst",
        title="Many refused captchas from one address",
        watches=frozenset({Signal.captcha_rejected}),
        key=source_ip,
        threshold=100,
        window=timedelta(minutes=10),
        severity=Severity.low,
    ),
    SecurityRule(
        name="api_key_scope",
        title="An API key kept reaching past what it may do",
        watches=frozenset({AuditEventType.API_KEY_SCOPE_VIOLATION}),
        key=target,
        threshold=20,
        window=timedelta(hours=1),
        severity=Severity.medium,
    ),
)

#: What each watched thing is counted by, by its string value: the lookup
#: every audit line pays, and most find nothing in.
BY_WATCHED: Mapping[str, tuple[SecurityRule, ...]] = {
    watched.value: tuple(rule for rule in RULES if watched in rule.watches)
    for watched in {w for rule in RULES for w in rule.watches}
}

#: The longest window, past which a counted row is no use to any rule.
LONGEST_WINDOW: timedelta = max(rule.window for rule in RULES)

#: More live keys than this in one rule's buckets and new keys collapse into
#: one, so memory stays bounded under a flood of addresses — and the collapse
#: is itself counted, and trips like any key.
MAX_KEYS_PER_RULE = 10_000

#: The key everything past the cap is counted under.
COLLAPSED_KEY = "*"

BY_NAME: Mapping[str, SecurityRule] = {rule.name: rule for rule in RULES}
