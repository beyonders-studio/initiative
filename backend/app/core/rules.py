"""The rules the deployment and its communities store as rows.

A rule says what is asked or allowed of people: whether a notification may
reach a phone, how long a session may last, whether reaching a community asks
for a second factor. Each layer keeps its own in a table of its own —
``platform_rules`` for the deployment, ``community_rules`` for a community —
one row per rule that says something, holding its value in the one slot its
kind uses. No row is the rule's default, so a deployment or community that
never touched a rule holds nothing for it.

This module is the catalog of those rules: which exist at each layer, the slot
each keeps its value in, its default, and the operator option a community must
hold for its value to apply. ``app.services.platform.rules`` reads and writes
the rows; ``app.services.platform.auth_posture`` is the one write path, with
the checks each rule runs.

Adding a rule is an entry here, the hooks it needs in ``auth_posture``, and
the code that enforces it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.core.guild_auth_options import CommunityAuthOption


class Slot(str, Enum):
    """Where a rule row keeps its value. A row sets exactly one."""

    #: An on/off answer.
    enabled = "enabled"
    #: A figure: hours, minutes, days.
    amount = "amount"


@dataclass(frozen=True)
class StoredRule:
    key: str
    slot: Slot
    #: What the rule says while no row does. Also its loosest value: every rule
    #: here starts out asking nothing.
    default: bool | int | None
    #: The option a community must hold for its value to apply, and to tighten
    #: it. Withdrawing the option stops the rule and leaves its row, so it
    #: applies again when the option comes back.
    entitlement: CommunityAuthOption | None = None


def _catalog(*rules: StoredRule) -> dict[str, StoredRule]:
    return {rule.key: rule for rule in rules}


_ON = Slot.enabled
_RESTRICTIONS = CommunityAuthOption.restrictions

#: The deployment's rules.
PLATFORM_RULES: dict[str, StoredRule] = _catalog(
    # The absolute session limit, in hours. ``AUTH_REFRESH_TTL_DAYS`` is the
    # separate question of how long a session may be left alone.
    StoredRule("session_max_hours", Slot.amount, None),
    # The longest a session may be left alone, in minutes, narrowing
    # ``AUTH_REFRESH_TTL_DAYS``.
    StoredRule("session_idle_minutes", Slot.amount, None),
    # Whether a notification may reach a phone at all.
    StoredRule("push_notifications_enabled", _ON, True),
    # Whether a notification may reach a mailbox. Sign-in codes and notices an
    # account gets about itself are not notifications and always go.
    StoredRule("email_notifications_enabled", _ON, True),
    # Whether a notification that leaves the app says only what kind of thing
    # happened.
    StoredRule("redact_notification_content", _ON, False),
    # Whether search may order content by how many members engaged with it.
    StoredRule("engagement_ranking_enabled", _ON, True),
)

#: A community's rules. Each is set by its seat and applies while the community
#: holds the option it needs.
COMMUNITY_RULES: dict[str, StoredRule] = _catalog(
    # Members sign in again every ``COMPLIANCE_SESSION_HOURS``.
    StoredRule("enforce_compliance_session", _ON, False, _RESTRICTIONS),
    # Reaching the community asks for a second factor.
    StoredRule("require_second_factor", _ON, False, _RESTRICTIONS),
    # The community's half of the three notification answers; the stricter of
    # its answer and the deployment's applies.
    StoredRule("allow_push_notifications", _ON, True, _RESTRICTIONS),
    StoredRule("allow_email_notifications", _ON, True, _RESTRICTIONS),
    StoredRule("redact_notification_content", _ON, False, _RESTRICTIONS),
    # Its half of engagement ranking; off wins.
    StoredRule("allow_engagement_ranking", _ON, True, _RESTRICTIONS),
    # Whether AI features may send its content to a provider at all.
    StoredRule("allow_ai", _ON, True, _RESTRICTIONS),
    # The longest a guest may stay, in days, under the deployment's ceiling.
    StoredRule("guest_max_days", Slot.amount, None, _RESTRICTIONS),
)
