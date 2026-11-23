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


def lost_reply(envelope: Envelope) -> bool:
    """A renewed token presented again by the device that renewed it, the
    session it was renewed into never used: the renewal's answer never reached
    the device (``app.services.auth.sessions.Replay``)."""
    return (envelope.get("detail") or {}).get("lost_reply") is True


def not_a_lost_reply(envelope: Envelope) -> bool:
    return not lost_reply(envelope)


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
    #: What it usually means and what to check: the case opens with it.
    guidance: str
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
        guidance=(
            "Fifty failed sign-ins in ten minutes from one address. Usually someone trying "
            "passwords against many accounts; an office or school behind one address can "
            "trip it too. Check whether the failures name many accounts or a few, and "
            "whether a sign-in from the address then succeeded."
        ),
    ),
    SecurityRule(
        name="account_held",
        title="An account's sign-in was locked",
        watches=frozenset({AuditEventType.AUTH_SIGN_IN_LOCKED}),
        key=subject_user,
        threshold=1,
        window=_DAY,
        severity=Severity.medium,
        guidance=(
            "Wrong passwords locked this account's sign-in for a while. Usually the person "
            "forgot theirs. If they say they did not try, someone else did: suggest a new "
            "password and a second factor."
        ),
    ),
    SecurityRule(
        name="refresh_reuse",
        title="A spent session token was used again",
        watches=frozenset({AuditEventType.AUTH_REFRESH_REUSE_DETECTED}),
        key=subject_user,
        threshold=1,
        window=_DAY,
        severity=Severity.high,
        guidance=(
            "A sign-in token that had already been renewed was presented again, and not the "
            "way a device that missed its own renewal does it: from another device or "
            "address, or after the session it was renewed into had been used. Every session "
            "on that sign-in is now ended. Ask the person whether they recognise the "
            "devices on their account, and suggest a new password."
        ),
        when=not_a_lost_reply,
    ),
    SecurityRule(
        name="refresh_resent",
        title="A device sent a sign-in token it had already renewed",
        watches=frozenset({AuditEventType.AUTH_REFRESH_REUSE_DETECTED}),
        key=subject_user,
        threshold=1,
        window=_DAY,
        severity=Severity.low,
        guidance=(
            "A device presented a sign-in token it had already renewed, from the same app or "
            "browser, and the session it was renewed into was never used: the renewal's "
            "answer never reached the device, usually because it slept or the app closed "
            "as the answer came back. That sign-in was ended and the person signs in again. "
            "Nothing to do unless it keeps happening to the same person."
        ),
        when=lost_reply,
    ),
    SecurityRule(
        name="second_factor_guessing",
        title="Many wrong second-factor codes for one account",
        watches=frozenset({AuditEventType.AUTH_SECOND_FACTOR_FAILED}),
        key=subject_user,
        threshold=10,
        window=timedelta(hours=1),
        severity=Severity.high,
        guidance=(
            "Ten wrong second-factor codes for one account in an hour, each after a correct "
            "password. Whoever is trying knows the password: ask the person to change it."
        ),
    ),
    SecurityRule(
        name="break_glass_review",
        title="An operator broke glass on a community",
        watches=frozenset({AuditEventType.ACCESS_GRANT_SELF_ISSUED}),
        key=actor_in_community,
        threshold=1,
        window=_DAY,
        severity=Severity.info,
        guidance=(
            "An operator gave themselves access to a community. Check that there was a "
            "reason (a ticket or a request) and that the access has ended."
        ),
    ),
    SecurityRule(
        name="privileged_role_granted",
        title="An account was made an operator or owner",
        watches=frozenset({AuditEventType.USER_PLATFORM_ROLE_CHANGED}),
        key=subject_user,
        threshold=1,
        window=_DAY,
        severity=Severity.medium,
        guidance=(
            "An account was made an operator or owner. Check that whoever changed it meant "
            "to, and that the account's holder expected it."
        ),
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
        guidance=(
            "Staff removed an account's second factor, usually at the person's request "
            "after losing a device. Check that the request came from them."
        ),
    ),
    SecurityRule(
        name="bulk_user_export",
        title="The user list was exported",
        watches=frozenset({AuditEventType.PLATFORM_USERS_EXPORTED}),
        key=actor,
        threshold=1,
        window=_DAY,
        severity=Severity.low,
        guidance=("Someone exported the list of accounts. Check that it was expected."),
    ),
    SecurityRule(
        name="replay",
        title="A one-time token or assertion was presented again",
        watches=frozenset({AuditEventType.SECURITY_REPLAY_REJECTED}),
        key=replay_source,
        threshold=5,
        window=timedelta(minutes=10),
        severity=Severity.high,
        guidance=(
            "A one-time token or answer (a link, a webhook, a sign-in response) was "
            "presented again five times in ten minutes from one source. A client retrying "
            "what it should not is the usual cause; check what the source is."
        ),
    ),
    SecurityRule(
        name="csrf_burst",
        title="Many cross-site request refusals from one address",
        watches=frozenset({Signal.csrf_rejected}),
        key=source_ip,
        threshold=100,
        window=timedelta(minutes=10),
        severity=Severity.medium,
        guidance=(
            "A hundred requests from one address were refused in ten minutes for coming "
            "from another site. Usually an embed or a proxy set up wrong; check the address "
            "and the pages the requests came from."
        ),
    ),
    SecurityRule(
        name="rate_limit_burst",
        title="One address kept hitting the rate limit",
        watches=frozenset({Signal.rate_limited}),
        key=source_ip,
        threshold=1000,
        window=timedelta(minutes=10),
        severity=Severity.low,
        guidance=(
            "One address hit the rate limit a thousand times in ten minutes. Usually a "
            "script or a stuck client; check the address, and block it at the edge if it "
            "carries on."
        ),
    ),
    SecurityRule(
        name="captcha_burst",
        title="Many refused captchas from one address",
        watches=frozenset({Signal.captcha_rejected}),
        key=source_ip,
        threshold=100,
        window=timedelta(minutes=10),
        severity=Severity.low,
        guidance=(
            "A hundred captcha answers from one address were refused in ten minutes, which "
            "is what automated sign-ups look like. Check the accounts created from the "
            "address."
        ),
    ),
    SecurityRule(
        name="api_key_scope",
        title="An API key kept reaching past what it may do",
        watches=frozenset({AuditEventType.API_KEY_SCOPE_VIOLATION}),
        key=target,
        threshold=20,
        window=timedelta(hours=1),
        severity=Severity.medium,
        guidance=(
            "An API key asked twenty times in an hour for things outside its scopes. "
            "Usually an integration given too narrow a key; check with its owner."
        ),
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
