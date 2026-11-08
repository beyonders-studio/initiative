"""Platform-level capability model.

Authorization for app-wide (platform) operations is expressed in terms of
*capabilities*, not role names. Each :class:`~app.models.user.UserRole` is a
preset that maps to a frozen set of capabilities (see ``ROLE_CAPABILITIES``).
Endpoints and services should check a capability via
:func:`user_has_capability` (or the ``require_capability`` dependency in
``app.api.deps``) so the privilege ladder can change without touching every
call site.

This is deliberately separate from *guild* roles (``CommunityRole``) and
*initiative* roles, which are scoped tenancy concepts. Capabilities here are
about platform-wide privilege.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

from app.models.platform.access_grant import AccessGrantPurpose, AccessLevel
from app.models.platform.user import UserRole, UserStatus

if TYPE_CHECKING:  # pragma: no cover
    from app.models.platform.user import User


class Capability(str, Enum):
    """A discrete platform-level permission.

    Values are stable dotted strings shared with the frontend (exposed on
    ``UserRead.capabilities``); treat them as part of the API contract.
    """

    # Read-only visibility of the platform's user list (served via operator
    # endpoints, gated purely by capability).
    USERS_READ = "users.read"

    # Trust & safety / user lifecycle.
    #: Moderation: renaming an account, clearing its picture and profile
    #: fields, suspending it, and asking for a ``moderate`` grant to read what
    #: the platform holds in a community.
    CONTENT_MODERATE = "content.moderate"
    #: Lift the block on an account that answered the age question as under
    #: age. A mistyped birth year is a support ticket, not a moderation case.
    USERS_AGE_UNBLOCK = "users.age_unblock"
    #: Account recovery: second factor, sessions, password, sign-in lock, API
    #: keys, reactivating and restoring.
    USERS_MANAGE = "users.manage"
    USERS_DELETE = "users.delete"

    # Platform operations.
    #: The operator dashboard's list of every community — its name, members,
    #: storage and status — for the staff who answer questions about them.
    #: Reading only: what an operator sets on a community stays
    #: ``communities.manage``.
    COMMUNITIES_READ = "communities.read"
    COMMUNITIES_MANAGE = "communities.manage"
    #: Suspend a community and lift it, out of deletion included. Never on its
    #: own: the route also asks for a live ``moderate`` grant on that
    #: community, so a moderator acts on one they are looking at.
    COMMUNITIES_SUSPEND = "communities.suspend"
    #: Open the billing service's support console for one community: its plan,
    #: invoices and payments, read under a billing grant that reaches nothing
    #: in the community. The operator console, which changes them, stays
    #: ``communities.manage``.
    BILLING_SUPPORT = "billing.support"

    # Opening the billing service's insights page: account-wide revenue and
    # subscriber figures from the payment processor, and counts that name no
    # community. Its own capability because it reaches no community — it is not
    # a grant, and the visit needs none — so it is decided here rather than by
    # ``communities.manage``, which can be narrowed later without taking it
    # along.
    BILLING_INSIGHTS = "billing.insights"

    # Opening the billing service's contracts console: the enterprise payers
    # invoiced by hand, their terms and invoices, and a dedicated deployment's
    # registration key file. Like insights it reaches no community and needs
    # no grant — a contract is a payer's, and some cover no community here —
    # but unlike insights it writes money records, so it is its own capability
    # rather than riding along with the read-only page.
    BILLING_CONTRACTS = "billing.contracts"

    # Opening the billing service's directory: every account that pays, its
    # communities, what comes next and what reconciliation found. Owners
    # only: it names every paying customer at once, which no operator task
    # needs. Read-only — acting on an account goes through the consoles and
    # their grants.
    BILLING_DIRECTORY = "billing.directory"

    # Opening the billing service's Control: where the deployment's owners
    # define its plans (the catalog, its words in each language, the prices
    # that sell it), and later share them out to communities and answer their
    # requests for more. Owners only: it changes what every community is sold
    # and allowed.
    BILLING_CONTROL = "billing.control"

    # Writing the notices every user of this deployment is shown (see
    # ``app.services.platform.announcements``). Product communication rather
    # than configuration, so it sits a rung below ``config.manage``: an
    # operator running the deployment day to day can say what changed without
    # also holding the keys to OIDC and SMTP.
    ANNOUNCEMENTS_MANAGE = "announcements.manage"
    ROLES_ASSIGN = "roles.assign"

    # The right to self-issue a break-glass PAM grant (operator+owner only). This is
    # NOT a standing all-guild bypass: instead of an ambient all-guild flag,
    # the holder records a scoped, time-bound, audited grant in one step
    # (created + self-approved) to reach one guild's data, then routes through the
    # normal PAM path until it expires. Lower tiers reach a guild via the
    # request→approve flow instead.
    DATA_BYPASS = "data.bypass"

    # Privileged Access Management (time-bound, per-guild grants).
    #: Ask for a grant through request and approval. Which grants is
    #: ``access.request_any``'s: without it, only a ``moderate`` one.
    ACCESS_REQUEST = "access.request"
    #: Ask for any grant: read or read-write content, settings, billing.
    ACCESS_REQUEST_ANY = "access.request_any"
    ACCESS_APPROVE = "access.approve"

    # App-wide configuration (OIDC, SMTP, branding, role labels). owner only.
    CONFIG_MANAGE = "config.manage"

    # Wiring external plug-in services into this deployment: their URL, the shared
    # secret, and the powers the operator confers on them. owner only — this is
    # deployment configuration, the same class ``config.manage`` occupies, kept
    # as its own capability so the plug-in catalog can be delegated separately later.
    PLUGINS_MANAGE = "plugins.manage"


# Capability presets per platform role, least → most privileged. Each higher
# tier is a strict superset of the tier below it, but the model itself does
# not assume that — membership is explicit so the matrix can diverge later.
_MEMBER: frozenset[Capability] = frozenset()

# Moderation and nothing else: finding the account or community to act on,
# acting on it, and asking for the ``moderate`` grant that reading held content
# takes. No other grant — no settings, no billing, no plain read of a community.
_MODERATOR: frozenset[Capability] = _MEMBER | {
    Capability.USERS_READ,
    Capability.COMMUNITIES_READ,
    Capability.CONTENT_MODERATE,
    Capability.COMMUNITIES_SUSPEND,
    Capability.ACCESS_REQUEST,
}

_SUPPORT: frozenset[Capability] = _MODERATOR | {
    Capability.USERS_AGE_UNBLOCK,
    Capability.USERS_MANAGE,
    Capability.ACCESS_REQUEST_ANY,
    Capability.BILLING_SUPPORT,
}

_OPERATOR: frozenset[Capability] = _SUPPORT | {
    Capability.COMMUNITIES_MANAGE,
    Capability.BILLING_INSIGHTS,
    Capability.BILLING_CONTRACTS,
    Capability.ANNOUNCEMENTS_MANAGE,
    Capability.USERS_DELETE,
    Capability.DATA_BYPASS,
    Capability.ROLES_ASSIGN,
    Capability.ACCESS_APPROVE,
}

_OWNER: frozenset[Capability] = (
    _OPERATOR
    | {
        Capability.CONFIG_MANAGE,
        Capability.PLUGINS_MANAGE,
        Capability.BILLING_DIRECTORY,
        Capability.BILLING_CONTROL,
    }
) - {
    # Owners approve access requests; they don't go through the request→approve
    # flow for themselves — they reach a guild via the self-approved break-glass
    # path (``data.bypass`` + ``access.approve``), so ``access.request`` is dropped.
    Capability.ACCESS_REQUEST,
    Capability.ACCESS_REQUEST_ANY,
}


ROLE_CAPABILITIES: dict[UserRole, frozenset[Capability]] = {
    UserRole.member: _MEMBER,
    UserRole.moderator: _MODERATOR,
    UserRole.support: _SUPPORT,
    UserRole.operator: _OPERATOR,
    UserRole.owner: _OWNER,
}


# Per-role maximum access-grant duration in minutes (least privilege). The
# service clamps each to its absolute ceiling; the request and break-glass forms
# read the caller's figure from the server.
ROLE_MAX_GRANT_MINUTES: dict[UserRole, int] = {
    UserRole.moderator: 240,  # 4 hours
    UserRole.support: 480,  # 8 hours
    UserRole.operator: 1440,  # 24 hours
    # Owners/operators reach a guild via the self-approved break-glass path
    # (``data.bypass``) rather than the request→approve flow; their cap applies
    # to that self-issued grant.
    UserRole.owner: 1440,
}


def capabilities_for(role: UserRole) -> frozenset[Capability]:
    """Return the capability set granted by a standing platform role."""
    return ROLE_CAPABILITIES.get(role, _MEMBER)


def roles_with_capability(capability: Capability) -> frozenset[UserRole]:
    """Return every standing role whose preset grants ``capability``.

    Used to translate a capability into a role filter for queries (e.g.
    "how many users can still manage platform config").
    """
    return frozenset(
        role for role, caps in ROLE_CAPABILITIES.items() if capability in caps
    )


def may_hold_grant(role: UserRole | str, purpose: str, level: str) -> bool:
    """Whether someone at ``role`` may hold a grant of ``purpose`` at
    ``level``: when asking for it, when it is approved, and each time it is
    used. A ``moderate`` content grant is for those who moderate. Every other
    grant is for those who may ask for any (``access.request_any``) or break
    glass (``data.bypass``)."""
    held = capabilities_for(UserRole(role))
    if (
        purpose == AccessGrantPurpose.content.value
        and level == AccessLevel.moderate.value
    ):
        return Capability.CONTENT_MODERATE in held
    return bool(held & {Capability.ACCESS_REQUEST_ANY, Capability.DATA_BYPASS})


def standing_capabilities(role: UserRole, status: UserStatus) -> frozenset[Capability]:
    """What a standing role grants an account in ``status``.

    A suspended account holds none: it is in time out, and its rung comes back
    untouched when the suspension lifts.
    """
    if status == UserStatus.suspended:
        return frozenset()
    return capabilities_for(role)


def user_has_capability(user: User, capability: Capability) -> bool:
    """True iff the user's standing platform role grants ``capability``.

    This reflects *standing* privilege only. Time-bound PAM grants (cross-guild
    data access) are resolved separately when the guild session is built.
    """
    return capability in standing_capabilities(user.role, user.status)


# Privilege ladder, least → most, taken from ``UserRole``'s declaration order.
# Assignment is bounded by rank rather than capability-subset: the presets
# aren't strictly nested (owner intentionally drops ``access.request``, which
# the lower tiers carry), so a subset check would wrongly forbid an owner from
# assigning ``operator``. Mirrors the frontend's PLATFORM_ROLE_ORDER.
_ROLE_ORDER: tuple[UserRole, ...] = tuple(UserRole)


def role_rank(role: UserRole) -> int:
    return _ROLE_ORDER.index(role)


def may_act_on(actor: User, target: User) -> bool:
    """Whether staff ``actor`` may act on ``target``'s account: never their
    own, and never one whose rung is above theirs. Every operator route that
    changes an account asks this."""
    return target.id != actor.id and role_rank(target.role) <= role_rank(actor.role)


def can_assign_role(actor: User, target_role: UserRole) -> bool:
    """Whether ``actor`` may assign ``target_role`` to someone.

    Bounded delegation: you can only grant a role at or below your own rung of
    the ladder (an operator can't mint an owner). Requires the actor to hold
    ``ROLES_ASSIGN`` in the first place.
    """
    if not user_has_capability(actor, Capability.ROLES_ASSIGN):
        return False
    return role_rank(target_role) <= role_rank(actor.role)
