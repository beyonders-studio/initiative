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
from app.core.login_methods import (
    DEFAULT_LOGIN_METHODS,
    LoginMethod,
    SecondFactorRequirement,
)
from app.models.platform.user_dm_settings import DmPolicy
from app.schemas.ai_settings import AIConfigMode


class Slot(str, Enum):
    """Where a rule row keeps its value. A row sets exactly one."""

    #: An on/off answer.
    enabled = "enabled"
    #: A figure: hours, minutes, days.
    amount = "amount"
    #: One of a fixed set of values, the set ``rule_choices`` holds.
    choice = "choice"
    #: Sign-in methods: the deployment's, the ways in it permits; a
    #: community's, a sign-in requirement, the methods it asks for and beside
    #: them the provider it names, if any.
    methods = "methods"


@dataclass(frozen=True)
class SignInRequirement:
    """A community's sign-in requirement: ``open``, or ``required`` naming a
    provider its members arrive through, methods they must use, or both."""

    policy: str = "open"
    provider_id: int | None = None
    methods: frozenset[LoginMethod] = frozenset()


@dataclass(frozen=True)
class StoredRule:
    key: str
    slot: Slot
    #: What the rule says while no row does. A community's is also its loosest
    #: value: every community rule starts out asking nothing.
    default: bool | int | Enum | frozenset[LoginMethod] | SignInRequirement | None
    #: The option a community must hold for its value to apply, and to tighten
    #: it. Withdrawing the option stops the rule and leaves its row, so it
    #: applies again when the option comes back.
    entitlement: CommunityAuthOption | None = None


def choices(rule: StoredRule) -> tuple[str, ...]:
    """The values a ``choice`` rule may take: its default's enum."""
    assert isinstance(rule.default, Enum)
    return tuple(member.value for member in type(rule.default))


def _catalog(*rules: StoredRule) -> dict[str, StoredRule]:
    return {rule.key: rule for rule in rules}


_ON = Slot.enabled
_RESTRICTIONS = CommunityAuthOption.restrictions

#: The retention window a deployment gets until it says otherwise, in days.
#:
#: The figure is the deployment's, not a community's: one answer for everybody
#: on the server, set by whoever runs it. A community cannot shorten or extend
#: its own, which is what makes the window mean something to the person
#: deleting theirs.
DEFAULT_GUILD_RETENTION_DAYS = 90

#: The window a deployment gets for a deleted **account**, in days.
#:
#: Shorter than the community one by default: a community's window protects a
#: body of work that several people made, an account's protects one person
#: from a decision they made in a moment, and thirty days is what somebody
#: takes to change their mind.
#:
#: It is a separate figure from the community's rather than one setting for
#: both, because they answer to different things — what a deployment owes the
#: people in it, and what it owes the person leaving.
DEFAULT_ACCOUNT_RETENTION_DAYS = 30

#: How long a community sits on hold before it is deleted, in days.
#:
#: Deleted, not destroyed: once this runs out the community moves to
#: ``deleted`` and the retention window above starts, so an operator can still
#: put it back. The figure is the deployment's, like the retention window.
DEFAULT_HOLD_DELETION_DAYS = 30

#: The shortest window a deployment may set, for either. A day, because a
#: window measured in hours is not one somebody notices their mistake inside
#: of.
MIN_GUILD_RETENTION_DAYS = 1

#: The longest. Past this, the answer being asked for is "never", which is what
#: switching the window off says.
MAX_GUILD_RETENTION_DAYS = 3650

#: Each retention window's figure, by the rule that says whether the window
#: runs at all. Off is "never": nothing is removed on that timer, and the
#: figure is kept for when it is switched back on.
RETENTION_WINDOWS: dict[str, str] = {
    "deleted_account_retention_days": "erase_deleted_accounts",
    "deleted_community_retention_days": "destroy_deleted_communities",
    "on_hold_community_deletion_days": "delete_held_communities",
}

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
    # Which ways in the deployment permits. At least one, and one of them a
    # way to begin a session. A fresh deployment's first value is the
    # environment's (``AUTH_LOGIN_METHODS``), seeded once at its first boot.
    StoredRule("login_methods", Slot.methods, frozenset(DEFAULT_LOGIN_METHODS)),
    # Who the deployment asks to hold a second factor.
    StoredRule(
        "second_factor_requirement", Slot.choice, SecondFactorRequirement.nobody
    ),
    # The direct-message policy a newly created account starts on. Read once,
    # when the account is made; changing it moves no existing account.
    StoredRule("default_dm_policy", Slot.choice, DmPolicy.private),
    # Who owns AI configuration: the operator for every community, each
    # community for itself, or nobody.
    StoredRule("ai_config_mode", Slot.choice, AIConfigMode.disabled),
    # Whether an arriving visitor is asked what this deployment may keep in
    # their browser. Most deployments are a group's own server, reached by
    # people who were sent a link; an owner running a public front door turns
    # it on.
    StoredRule("cookie_consent_enabled", _ON, False),
    # Whether the deployment runs a community directory: the browsable list of
    # communities that opted in, and the invite-free join that goes with it.
    StoredRule("community_directory_enabled", _ON, False),
    # Whether the deployment checks age. Off is its owner asserting that every
    # account here belongs to an adult.
    StoredRule("community_age_gate_enabled", _ON, True),
    # Whether communities may have guests: outside people in for a set time,
    # who take no seat. Off, no guest membership admits anybody.
    StoredRule("guests_enabled", _ON, False),
    # The longest a guest membership may run, in days. A community's own
    # longest sits under it.
    StoredRule("max_guest_days", Slot.amount, 90),
    # Whether the platform's sign-in placement rules apply to every community
    # they name, rather than only to those that accepted them on their
    # connection.
    StoredRule("provider_placement_everywhere", _ON, False),
    # Whether the deployment offers direct messages at all. Off keeps every
    # channel and policy, so switching it back on restores them.
    StoredRule("direct_messages_enabled", _ON, True),
    # Whether a member's share to the marketplace goes on the shelf without
    # the owner's review.
    StoredRule("marketplace_members_publish_directly", _ON, False),
    # Whether the deployment follows the marketplace registry. Off stops the
    # background refresh; what already arrived stays.
    StoredRule("marketplace_registry_enabled", _ON, True),
    # How long a deleted account is kept before it is erased, and whether it
    # is erased on a timer at all.
    StoredRule("erase_deleted_accounts", _ON, True),
    StoredRule(
        "deleted_account_retention_days", Slot.amount, DEFAULT_ACCOUNT_RETENTION_DAYS
    ),
    # How long a deleted community is kept before it is destroyed. Off is the
    # answer for a deployment that has undertaken to keep what its members put
    # in it.
    StoredRule("destroy_deleted_communities", _ON, True),
    StoredRule(
        "deleted_community_retention_days", Slot.amount, DEFAULT_GUILD_RETENTION_DAYS
    ),
    # How long a community stays on hold before it is deleted, counted from
    # its hold.
    StoredRule("delete_held_communities", _ON, True),
    StoredRule(
        "on_hold_community_deletion_days", Slot.amount, DEFAULT_HOLD_DELETION_DAYS
    ),
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
    # Whether a member's personal API keys reach the community. The seat sets
    # it member by member.
    StoredRule("api_keys", _ON, True, _RESTRICTIONS),
    # What reaching the community asks of its members, and of its guests.
    # Tightening one needs ``providers``. The provider or single sign-on it
    # names applies whatever the community holds, and the second factor it
    # asks for only while it holds ``providers``: the gate asks that part by
    # part, so these carry no option of their own.
    StoredRule("auth_policy", Slot.methods, SignInRequirement()),
    StoredRule("guest_auth_policy", Slot.methods, SignInRequirement()),
)
