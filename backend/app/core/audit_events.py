"""The catalogue of things Initiative writes down.

One enum drives every surface — the table, the ingestible line, the board, the
filters — so adding a newly-audited action is an enum member, which carries its
own category, tier and write flag, and one ``record()`` call at the site. There
is no second list to keep in step.

There are two tiers. Tier 1 is the privileged
-access family, which is meant for immutable storage as well; Tier 2 is
everything else Initiative owns. Nothing here ships anywhere yet — the tier is
recorded now so the shipper does not have to reclassify history later.

Initiative records only actions whose authority it enforces itself. Infra
access, the identity provider's own sign-ins and billing all emit their own
streams; the envelope carries the fields that stitch them together downstream.
"""

from __future__ import annotations

from enum import Enum


class AuditCategory(str, Enum):
    """Which family an event belongs to. The board groups by this."""

    MODERATION = "moderation"
    AUTHENTICATION = "authentication"
    #: Who may reach what: memberships, roles, shares, plug-in consents, and
    #: privileged access into a community from outside it.
    AUTHORIZATION = "authorization"
    #: The platform itself: who holds which rung of its ladder. Operator
    #: work, which is a different job from moderating an account.
    PLATFORM = "platform"
    #: Settings, at either level: how sign-in, email, storage, AI and plug-ins
    #: are wired.
    CONFIGURATION = "configuration"
    #: Accounts and communities arriving and leaving, and data moved in
    #: bulk — exported, or destroyed.
    LIFECYCLE = "lifecycle"


class AuditEventType(str, Enum):
    """A recorded action. Values are stable strings — treat them as a contract
    with whatever reads the log.

    A member is declared as ``value, category[, tier[, is_write]]``; most are
    tier 2 writes and give only the first two.
    """

    _value_: str
    category: AuditCategory
    #: 1 for the privileged-access family (destined for immutable storage),
    #: 2 for everything else. Denormalized onto the row so a shipper can
    #: select by it without reading this registry.
    tier: int
    #: Whether the action changed something. Reads are recorded too (a PAM
    #: grantee's are the point of the log), so this is not implied by presence.
    is_write: bool

    def __new__(
        cls,
        value: str,
        category: AuditCategory,
        tier: int = 2,
        is_write: bool = True,
    ) -> AuditEventType:
        member = str.__new__(cls, value)
        member._value_ = value
        member.category = category
        member.tier = tier
        member.is_write = is_write
        return member

    # Trust & safety: what a moderator does to an account, none of which needs
    # a PAM grant because none of it reaches a guild's content.
    USER_AVATAR_REMOVED = "user.avatar_removed", AuditCategory.MODERATION
    USER_USERNAME_CHANGED = "user.username_changed", AuditCategory.MODERATION
    USER_SUSPENDED = "user.suspended", AuditCategory.MODERATION
    USER_UNSUSPENDED = "user.unsuspended", AuditCategory.MODERATION
    USER_AGE_BLOCK_CLEARED = "user.age_block_cleared", AuditCategory.MODERATION
    #: Staff ended every session an account had, everywhere.
    USER_SESSIONS_REVOKED = "user.sessions_revoked", AuditCategory.MODERATION, 1
    #: Staff cleared part of how an account appears to others: its names in
    #: communities, its custom status or its decorations.
    USER_PROFILE_FIELD_CLEARED = (
        "user.profile_field_cleared",
        AuditCategory.MODERATION,
        1,
    )
    #: A file somebody attached to a ticket or a report was opened: by the
    #: people working it, or by whoever attached it. Who looked at evidence,
    #: and when, is a record kept as long as the privileged-access family's.
    EVIDENCE_ACCESSED = (
        "evidence.accessed",
        AuditCategory.MODERATION,
        1,
        False,
    )
    USER_SIGN_IN_LOCK_LIFTED = "user.sign_in_lock_lifted", AuditCategory.MODERATION
    #: Content was held for the platform, and a hold was released: what was
    #: kept from the community, by whom, and how it ended.
    HOLD_PLACED = "hold.placed", AuditCategory.MODERATION, 1
    HOLD_RELEASED = "hold.released", AuditCategory.MODERATION, 1
    #: A community's moderators acted, one line per row of its moderation log:
    #: what was done, to what, on whose report or hold, and under which grant.
    #: Never the words a removal took down; the log row keeps those, sealed.
    MODERATION_CONTENT_REMOVED = (
        "moderation.content_removed",
        AuditCategory.MODERATION,
        1,
    )
    MODERATION_CONTENT_RESTORED = (
        "moderation.content_restored",
        AuditCategory.MODERATION,
        1,
    )
    MODERATION_COMMENTS_LOCKED = (
        "moderation.comments_locked",
        AuditCategory.MODERATION,
        1,
    )
    MODERATION_COMMENTS_UNLOCKED = (
        "moderation.comments_unlocked",
        AuditCategory.MODERATION,
        1,
    )
    MODERATION_REACTIONS_CLEARED = (
        "moderation.reactions_cleared",
        AuditCategory.MODERATION,
        1,
    )
    MODERATION_MEMBER_WARNED = (
        "moderation.member_warned",
        AuditCategory.MODERATION,
        1,
    )
    #: A community report was closed, with its outcome and the log row an
    #: outcome that acts wrote.
    MODERATION_REPORT_SETTLED = (
        "moderation.report_settled",
        AuditCategory.MODERATION,
        1,
    )
    #: Somebody filed a ticket with whoever runs the server: which stream, and
    #: what about. Never what it said.
    TICKET_FILED = "ticket.filed", AuditCategory.MODERATION, 1
    #: Whoever filed a case answered on it.
    TICKET_REPLIED = "ticket.replied", AuditCategory.MODERATION

    # The platform ladder. Granting a rung is an operator's job (``roles.assign``),
    # not a moderator's, so it is recorded apart from the account actions above:
    # the account it happened to, and the two roles it moved between.
    USER_PLATFORM_ROLE_CHANGED = "user.platform_role_changed", AuditCategory.PLATFORM

    # Authentication: who got in, who did not, and what changed about the
    # credentials. Every failed attempt is recorded, whether or not it
    # resolved to an account; one that did not carries no target and no
    # submitted address, so nothing unowned reaches the log. See T123.
    # A sign-in opens a session, so it is a write; a refused one changed
    # nothing and is not.
    AUTH_SIGNED_IN = "auth.signed_in", AuditCategory.AUTHENTICATION
    AUTH_SIGN_IN_FAILED = "auth.sign_in_failed", AuditCategory.AUTHENTICATION, 2, False
    AUTH_SIGNED_OUT = "auth.signed_out", AuditCategory.AUTHENTICATION
    #: The account ended a session other than the one it was asking from —
    #: a row in its own "where you're signed in" list, or all of them at
    #: once. Apart from a sign-out because the session that ends is not the
    #: session that asked, which is the whole point of recording it.
    AUTH_SESSION_REVOKED = "auth.session_revoked", AuditCategory.AUTHENTICATION
    AUTH_PASSWORD_CHANGED = "auth.password_changed", AuditCategory.AUTHENTICATION
    #: The account gave its password up and signs in by another way from
    #: now on. Recorded apart from a change, because what the account holds
    #: is different afterwards rather than merely different in value.
    AUTH_PASSWORD_REMOVED = "auth.password_removed", AuditCategory.AUTHENTICATION
    AUTH_IDENTITY_LINKED = "auth.identity_linked", AuditCategory.AUTHENTICATION
    #: An address was proved for the first time, and the credentials the
    #: account held while it was unproven were retired with it.
    AUTH_CREDENTIALS_RETIRED = "auth.credentials_retired", AuditCategory.AUTHENTICATION
    AUTH_REFRESH_REUSE_DETECTED = (
        "auth.refresh_reuse_detected",
        AuditCategory.AUTHENTICATION,
    )
    #: The account's own second factor. ``failed`` is a refused code against a
    #: standing challenge, so it is the shape a run of guesses makes; like a
    #: refused sign-in, it changed nothing.
    AUTH_SECOND_FACTOR_ENROLLED = (
        "auth.second_factor_enrolled",
        AuditCategory.AUTHENTICATION,
    )
    AUTH_SECOND_FACTOR_DISABLED = (
        "auth.second_factor_disabled",
        AuditCategory.AUTHENTICATION,
    )
    AUTH_SECOND_FACTOR_FAILED = (
        "auth.second_factor_failed",
        AuditCategory.AUTHENTICATION,
        2,
        False,
    )
    #: Wrong answers adding up: the account's password and codes are refused
    #: for a while, longer for each lock within a day.
    AUTH_SIGN_IN_LOCKED = "auth.sign_in_locked", AuditCategory.AUTHENTICATION
    #: Cleared by somebody else — a support path, so actor and target differ.
    AUTH_SECOND_FACTOR_RESET = "auth.second_factor_reset", AuditCategory.AUTHENTICATION
    AUTH_RECOVERY_CODE_USED = "auth.recovery_code_used", AuditCategory.AUTHENTICATION
    AUTH_RECOVERY_CODES_ISSUED = (
        "auth.recovery_codes_issued",
        AuditCategory.AUTHENTICATION,
    )
    #: A WebAuthn credential joined or left the account. The row carries the
    #: passkey's id and what the ceremony reported about it, never the
    #: credential id and never any key material.
    AUTH_PASSKEY_REGISTERED = "auth.passkey_registered", AuditCategory.AUTHENTICATION
    AUTH_PASSKEY_REMOVED = "auth.passkey_removed", AuditCategory.AUTHENTICATION
    #: A change to how the account is signed into was held, and later
    #: cancelled or applied. The row carries the hold's id and kind.
    AUTH_CHANGE_HELD = "auth.change_held", AuditCategory.AUTHENTICATION
    AUTH_HELD_CHANGE_CANCELLED = (
        "auth.held_change_cancelled",
        AuditCategory.AUTHENTICATION,
    )
    AUTH_HELD_CHANGE_APPLIED = "auth.held_change_applied", AuditCategory.AUTHENTICATION
    #: Who holds a guild's sign-in configuration changed. The seat is passed
    #: on by whoever holds it — by membership, or through a superadmin
    #: settings grant — from the guild's own role route.
    GUILD_SUPERADMIN_CHANGED = "guild.superadmin_changed", AuditCategory.AUTHENTICATION
    #: A privileged-access grant was asked for, decided, or self-issued. The
    #: ``access_grants`` row is the record of what was granted; these say when
    #: each step happened and carry the purpose and the rung with them, so
    #: "who held this community's settings, at what level, and on whose
    #: authority" is answerable from the log by itself.
    ACCESS_GRANT_REQUESTED = "access_grant.requested", AuditCategory.AUTHORIZATION, 1
    ACCESS_GRANT_DECIDED = "access_grant.decided", AuditCategory.AUTHORIZATION, 1
    ACCESS_GRANT_SELF_ISSUED = (
        "access_grant.self_issued",
        AuditCategory.AUTHORIZATION,
        1,
    )
    #: A grant named the operations case it serves, so the case the access
    #: was for is answerable from the log as well as from the grant.
    ACCESS_GRANT_CASE_LINKED = (
        "access_grant.case_linked",
        AuditCategory.AUTHORIZATION,
        1,
    )
    #: One request served through a grant rather than through membership —
    #: every one of them, read or write. The grant says what somebody was let
    #: into; this says what they then did with it, which is the difference
    #: between "an operator held this community for an hour" and "an operator
    #: opened four hundred files". It records the reach, so it is not a
    #: write itself: a request that changed something records that separately,
    #: under the event for what it changed.
    PAM_REQUEST = "pam.request", AuditCategory.AUTHORIZATION, 1, False
    #: Somebody serving a grant changed a file's or a wiki page's body,
    #: which happens over a live editing socket rather than through a request.
    #: One line the first time they do it in a session: that they edited it is
    #: the fact worth having, and a line per keystroke would bury it.
    PAM_CONTENT_EDITED = "pam.content_edited", AuditCategory.AUTHORIZATION, 1
    #: Which ways in the deployment permits changed. Carries the count of
    #: accounts an operator acknowledged stranding, where they did.
    PLATFORM_LOGIN_METHODS_CHANGED = (
        "platform.login_methods_changed",
        AuditCategory.AUTHENTICATION,
    )
    #: Who the deployment asks to hold a second factor changed.
    PLATFORM_SECOND_FACTOR_REQUIREMENT_CHANGED = (
        "platform.second_factor_requirement_changed",
        AuditCategory.AUTHENTICATION,
    )

    # Who may reach what. A membership is the first gate into a community's
    # content and an initiative's the second; a share is the last. Each row
    # names the account it happened to, so "everything ever granted to this
    # person" is one query on ``target_user_id``.
    GUILD_MEMBER_ADDED = "guild.member_added", AuditCategory.AUTHORIZATION
    GUILD_MEMBER_REMOVED = "guild.member_removed", AuditCategory.AUTHORIZATION
    #: Between member and admin. A change to or from the seat that holds a
    #: community's sign-in is ``GUILD_SUPERADMIN_CHANGED`` instead.
    GUILD_MEMBER_ROLE_CHANGED = "guild.member_role_changed", AuditCategory.AUTHORIZATION
    #: A custom role made, changed or deleted: what it holds and on which
    #: rung. ``detail.action`` says which.
    GUILD_CUSTOM_ROLE_CHANGED = "guild.custom_role_changed", AuditCategory.AUTHORIZATION
    #: A custom role given to a member, or taken off.
    GUILD_CUSTOM_ROLE_ASSIGNED = (
        "guild.custom_role_assigned",
        AuditCategory.AUTHORIZATION,
    )
    #: The seat turning one member's personal API keys off or on for the
    #: community.
    GUILD_MEMBER_API_ACCESS_CHANGED = (
        "guild.member_api_access_changed",
        AuditCategory.AUTHORIZATION,
    )
    #: An invite is a standing offer of membership; issuing or withdrawing
    #: one is recorded, and redeeming one is a ``GUILD_MEMBER_ADDED``.
    GUILD_INVITE_CREATED = "guild.invite_created", AuditCategory.AUTHORIZATION
    GUILD_INVITE_REVOKED = "guild.invite_revoked", AuditCategory.AUTHORIZATION
    #: A guest's end moved. Becoming a guest is a ``GUILD_MEMBER_ADDED`` with
    #: ``guest_until`` in its detail, and leaving one a ``GUILD_MEMBER_REMOVED``.
    GUILD_GUEST_EXTENDED = "guild.guest_extended", AuditCategory.AUTHORIZATION
    #: A guest made a member: their time no longer ends, and they take a seat.
    GUILD_GUEST_MADE_MEMBER = "guild.guest_made_member", AuditCategory.AUTHORIZATION
    INITIATIVE_MEMBER_ADDED = "initiative.member_added", AuditCategory.AUTHORIZATION
    INITIATIVE_MEMBER_REMOVED = "initiative.member_removed", AuditCategory.AUTHORIZATION
    INITIATIVE_MEMBER_ROLE_CHANGED = (
        "initiative.member_role_changed",
        AuditCategory.AUTHORIZATION,
    )
    #: The roles themselves: a role is a bundle of permissions, so changing
    #: one changes what every holder may do.
    INITIATIVE_ROLE_CREATED = "initiative.role_created", AuditCategory.AUTHORIZATION
    INITIATIVE_ROLE_UPDATED = "initiative.role_updated", AuditCategory.AUTHORIZATION
    INITIATIVE_ROLE_DELETED = "initiative.role_deleted", AuditCategory.AUTHORIZATION
    #: One grantee's level on one resource moved: granted, raised, lowered
    #: or withdrawn. A share rebuilt from a list is one of these per grantee
    #: whose level actually changed.
    SHARING_GRANT_CHANGED = "sharing.grant_changed", AuditCategory.AUTHORIZATION
    #: Everything one account owned in a community now belongs to another,
    #: or to nobody. One record per transfer, with counts by tool.
    CONTENT_OWNERSHIP_TRANSFERRED = (
        "content.ownership_transferred",
        AuditCategory.AUTHORIZATION,
    )
    #: A member allowed an installed plug-in's request to act as them, or took
    #: that back (or the community's seat ended it for them).
    PLUGIN_CONSENT_GRANTED = "plugin_consent.granted", AuditCategory.AUTHORIZATION
    PLUGIN_CONSENT_REVOKED = "plugin_consent.revoked", AuditCategory.AUTHORIZATION
    #: One installed plug-in called another through Initiative: which plug-in called,
    #: which it called, the endpoint, whose behalf it was on, and how it ended.
    #: It records the reach, as ``pam.request`` does; what the plug-in called then
    #: changed is its own.
    PLUGIN_HUB_CALL = "plugin_hub.call", AuditCategory.AUTHORIZATION, 2, False
    #: A member ran one of an installed plug-in's actions on an item: which
    #: install, which action, the item, and how it ended. Like a hub call it
    #: records the reach; what the plug-in then changed is its own.
    PLUGIN_ACTION = "plugin.action", AuditCategory.AUTHORIZATION, 2, False

    # Configuration. The record says which fields moved; a value is copied in
    # only where its type rules out a secret (see ``audit.changed_fields``).
    #: The deployment's own settings row: interface, community, email,
    #: storage, session lifetime, AI mode. ``detail.area`` says which.
    PLATFORM_SETTINGS_CHANGED = "platform.settings_changed", AuditCategory.CONFIGURATION
    AUTH_PROVIDER_CREATED = "auth_provider.created", AuditCategory.CONFIGURATION
    AUTH_PROVIDER_UPDATED = "auth_provider.updated", AuditCategory.CONFIGURATION
    AUTH_PROVIDER_DELETED = "auth_provider.deleted", AuditCategory.CONFIGURATION
    #: The answer a provider gives every community that has not given its
    #: own.
    AUTH_PROVIDER_DEFAULT_SET = "auth_provider.default_set", AuditCategory.CONFIGURATION
    AUTH_PROVIDER_DEFAULT_CLEARED = (
        "auth_provider.default_cleared",
        AuditCategory.CONFIGURATION,
    )
    #: A claim rule places arriving accounts; written by the community's
    #: superadmin for that community.
    CLAIM_RULE_CREATED = "claim_rule.created", AuditCategory.CONFIGURATION
    CLAIM_RULE_UPDATED = "claim_rule.updated", AuditCategory.CONFIGURATION
    CLAIM_RULE_DELETED = "claim_rule.deleted", AuditCategory.CONFIGURATION
    PROVIDER_PLACEMENT_EVERYWHERE_CHANGED = (
        "platform.provider_placement_everywhere_changed",
        AuditCategory.CONFIGURATION,
    )
    GUILD_PROVIDER_CONNECTED = "guild.provider_connected", AuditCategory.CONFIGURATION
    GUILD_PROVIDER_CONNECTION_UPDATED = (
        "guild.provider_connection_updated",
        AuditCategory.CONFIGURATION,
    )
    GUILD_PROVIDER_DISCONNECTED = (
        "guild.provider_disconnected",
        AuditCategory.CONFIGURATION,
    )
    #: What a community requires of a sign-in before it counts.
    GUILD_AUTH_POLICY_CHANGED = "guild.auth_policy_changed", AuditCategory.CONFIGURATION
    #: A community's other settings — its own (API keys, session limit,
    #: retention, profile) and the operator's for it (caps, options).
    GUILD_SETTINGS_CHANGED = "guild.settings_changed", AuditCategory.CONFIGURATION
    AI_CONNECTION_CREATED = "ai_connection.created", AuditCategory.CONFIGURATION
    AI_CONNECTION_UPDATED = "ai_connection.updated", AuditCategory.CONFIGURATION
    AI_CONNECTION_DELETED = "ai_connection.deleted", AuditCategory.CONFIGURATION
    #: The seat took back the key a member gave one of the community's AI
    #: connections.
    PLUGIN_SERVICE_CREATED = "plugin_service.created", AuditCategory.CONFIGURATION
    PLUGIN_SERVICE_UPDATED = "plugin_service.updated", AuditCategory.CONFIGURATION
    PLUGIN_SERVICE_DELETED = "plugin_service.deleted", AuditCategory.CONFIGURATION
    PLUGIN_PUBLISHER_CREATED = "plugin_publisher.created", AuditCategory.CONFIGURATION
    PLUGIN_PUBLISHER_UPDATED = "plugin_publisher.updated", AuditCategory.CONFIGURATION
    #: An operator re-read the catalogue sources; carries what was published
    #: and withdrawn.
    MARKETPLACE_CATALOG_REFRESHED = (
        "marketplace.catalog_refreshed",
        AuditCategory.CONFIGURATION,
    )
    #: A member shared an item from a community to this deployment's
    #: marketplace; carries the listing, its version, and whether it waits for
    #: review.
    MARKETPLACE_LISTING_SHARED = (
        "marketplace.listing_shared",
        AuditCategory.CONFIGURATION,
    )
    #: The owner approved or refused a shared version.
    MARKETPLACE_LISTING_REVIEWED = (
        "marketplace.listing_reviewed",
        AuditCategory.CONFIGURATION,
    )
    #: The owner uploaded a listing file.
    MARKETPLACE_LISTING_UPLOADED = (
        "marketplace.listing_uploaded",
        AuditCategory.CONFIGURATION,
    )
    #: A member took down a listing they shared.
    MARKETPLACE_LISTING_WITHDRAWN = (
        "marketplace.listing_withdrawn",
        AuditCategory.CONFIGURATION,
    )
    #: An installed plug-in's own settings or configuration.
    PLUGIN_UPDATED = "plugin.updated", AuditCategory.CONFIGURATION

    # Lifecycle: accounts and communities coming and going, and the bulk
    # movements of data — out of the deployment, or gone for good.
    USER_CREATED = "user.created", AuditCategory.LIFECYCLE
    USER_DEACTIVATED = "user.deactivated", AuditCategory.LIFECYCLE
    USER_REACTIVATED = "user.reactivated", AuditCategory.LIFECYCLE
    #: Personal details removed, contributions kept under a placeholder.
    USER_ANONYMIZED = "user.anonymized", AuditCategory.LIFECYCLE
    #: The account and everything it left, removed outright.
    USER_DELETED = "user.deleted", AuditCategory.LIFECYCLE
    #: The holder asked for the account to go. It is kept for the deployment's
    #: window, and erased at the end of it unless somebody comes back.
    USER_DELETION_SCHEDULED = "user.deletion_scheduled", AuditCategory.LIFECYCLE
    #: Called off inside the window — by the holder signing in, or by an
    #: operator restoring it.
    USER_DELETION_CANCELLED = "user.deletion_cancelled", AuditCategory.LIFECYCLE
    GUILD_CREATED = "guild.created", AuditCategory.LIFECYCLE
    #: Deleted and kept: the community stops existing for everyone in it, and
    #: is retained for the restore window before the purge below destroys it.
    GUILD_DELETED = "guild.deleted", AuditCategory.LIFECYCLE
    #: Brought back inside the window by a platform operator, who named the
    #: status it returns at and, where the roster was emptied, who runs it.
    GUILD_RESTORED = "guild.restored", AuditCategory.LIFECYCLE
    #: The retention window ran out. What the deletion kept is now gone: the
    #: shared rows, the guild's schema, and its stored blobs.
    GUILD_PURGED = "guild.purged", AuditCategory.LIFECYCLE
    GUILD_STATUS_CHANGED = "guild.status_changed", AuditCategory.LIFECYCLE
    # Data leaving: nothing here changed, which is what is worth knowing.
    #: A whole community handed over as a bundle.
    GUILD_EXPORTED = "guild.exported", AuditCategory.LIFECYCLE, 2, False
    #: A community's roster, as a spreadsheet.
    GUILD_MEMBERS_EXPORTED = "guild.members_exported", AuditCategory.LIFECYCLE, 2, False
    #: Every account on the deployment, as a spreadsheet.
    PLATFORM_USERS_EXPORTED = (
        "platform.users_exported",
        AuditCategory.LIFECYCLE,
        2,
        False,
    )
    INITIATIVE_EXPORTED = "initiative.exported", AuditCategory.LIFECYCLE, 2, False
    INITIATIVE_DELETED = "initiative.deleted", AuditCategory.LIFECYCLE
    #: Rows gone past recovery: one item purged from the trash by an admin,
    #: or a community's sweep, which carries counts and no actor.
    TRASH_PURGED = "trash.purged", AuditCategory.LIFECYCLE
    #: A personal API key is a credential, so it sits with the rest of them
    #: under authentication.
    API_KEY_CREATED = "api_key.created", AuditCategory.AUTHENTICATION
    API_KEY_DELETED = "api_key.deleted", AuditCategory.AUTHENTICATION
    #: Switched off by staff rather than deleted by its holder, who still sees it.
    API_KEY_REVOKED = "api_key.revoked", AuditCategory.AUTHENTICATION
    #: A key reached past what it was made for: a read-only key writing, or a
    #: key named for one thing reaching another. Refused, so nothing changed.
    API_KEY_SCOPE_VIOLATION = (
        "api_key.scope_violation",
        AuditCategory.AUTHENTICATION,
        2,
        False,
    )
    #: A one-time token, assertion or nonce was presented again and refused.
    #: ``detail.channel`` says which.
    SECURITY_REPLAY_REJECTED = (
        "security.replay_rejected",
        AuditCategory.AUTHENTICATION,
        1,
        False,
    )
    #: A security rule saw enough of something within its window to open a
    #: case (``app.core.security_rules``): one line per key and window, however
    #: many events it took.
    SECURITY_THRESHOLD_CROSSED = (
        "security.threshold_crossed",
        AuditCategory.PLATFORM,
        1,
        False,
    )
    #: Everything encrypted under the deployment's secret key was sealed again
    #: under a new one.
    PLATFORM_SECRET_KEY_ROTATED = (
        "platform.secret_key_rotated",
        AuditCategory.CONFIGURATION,
        1,
    )
    PLUGIN_INSTALLED = "plugin.installed", AuditCategory.LIFECYCLE
    PLUGIN_UNINSTALLED = "plugin.uninstalled", AuditCategory.LIFECYCLE
    #: A plug-in never answered the community's request to erase its data;
    #: its references were dropped anyway. Carries the plug-in and the tries.
    PLUGIN_ERASE_ABANDONED = "plugin.erase_abandoned", AuditCategory.LIFECYCLE
    WEBHOOK_CREATED = "webhook.created", AuditCategory.LIFECYCLE
    WEBHOOK_UPDATED = "webhook.updated", AuditCategory.LIFECYCLE
    WEBHOOK_DELETED = "webhook.deleted", AuditCategory.LIFECYCLE
    #: Content left the deployment for an AI provider. Recorded before the
    #: request goes out, since the disclosure does not wait on the reply.
    AI_REQUEST_SENT = "ai.request_sent", AuditCategory.LIFECYCLE, 2, False


#: The envelope's shape version. Downstream contracts against it; bump only on
#: a breaking change.
SCHEMA_VERSION = 1

#: The line names the service it came from. Billing and auto emit streams of
#: the same shape about the same communities, so a reader filtering on a
#: community sees all three, and this is what tells them apart.
SERVICE = "initiative"
