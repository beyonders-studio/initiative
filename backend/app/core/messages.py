"""Centralized error message constants for API responses.

These constants are used as HTTPException detail strings. The frontend
maps these codes to localized user-facing messages via errors.json.
"""

from app.core.tools import Tool


class CommonMessages:
    """Codes that belong to no one tool."""

    #: A time zone that is not one, wherever a request names a zone.
    UNKNOWN_TIMEZONE = "UNKNOWN_TIMEZONE"

    #: Somebody named on the content (an assignee, an attendee, a person
    #: property, a queue item's person) cannot open what it sits in.
    PERSON_CANNOT_READ = "PERSON_CANNOT_READ"

    #: The write reached content that is archived or in the trash, or something
    #: under it. One code for both, because the answer is the same either way:
    #: bring it back first. See ``app.db.frozen``.
    CONTENT_IS_FROZEN = "CONTENT_IS_FROZEN"

    #: The write was fine for the thing itself, but what it sits inside is
    #: archived or in the trash — so it cannot come out on its own, and the
    #: answer names the container rather than the row.
    PARENT_IS_FROZEN = "PARENT_IS_FROZEN"

    #: The request body is larger than its route takes. Answered by the
    #: transport (``app.core.body_limit``) before any handler runs.
    REQUEST_TOO_LARGE = "REQUEST_TOO_LARGE"


class AuthMessages:
    #: A sign-in rule nothing the deployment permits could answer.
    AUTH_RULE_NOT_OFFERED = "AUTH_RULE_NOT_OFFERED"
    #: A sign-in rule its writer does not answer yet; the unmet header names
    #: which part.
    AUTH_RULE_SELF_UNSATISFIED = "AUTH_RULE_SELF_UNSATISFIED"
    EMAIL_ALREADY_REGISTERED = "EMAIL_ALREADY_REGISTERED"
    REGISTRATION_REQUIRES_INVITE = "REGISTRATION_REQUIRES_INVITE"
    UNABLE_TO_CREATE_USER = "UNABLE_TO_CREATE_USER"
    REGISTRATION_INVITE_OR_COMMUNITY = "REGISTRATION_INVITE_OR_COMMUNITY"
    INCORRECT_CREDENTIALS = "INCORRECT_CREDENTIALS"
    #: Too many wrong passwords or codes lately: password and code sign-in are
    #: turned off for now. Passkeys are unaffected.
    SIGN_IN_LOCKED = "SIGN_IN_LOCKED"
    REQUEST_ORIGIN_NOT_RECOGNIZED = "REQUEST_ORIGIN_NOT_RECOGNIZED"
    INACTIVE_USER = "INACTIVE_USER"
    ACCOUNT_SUSPENDED = "ACCOUNT_SUSPENDED"
    CANNOT_REACTIVATE_ANONYMIZED = "CANNOT_REACTIVATE_ANONYMIZED"
    EMAIL_NOT_VERIFIED = "EMAIL_NOT_VERIFIED"
    #: The session named is not one this account holds.
    SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
    NOT_AUTHENTICATED = "NOT_AUTHENTICATED"
    #: The action hands out authority, so it is taken while signed in rather
    #: than through a standing credential (an API key, a plug-in acting on
    #: someone's behalf).
    SESSION_REQUIRED = "SESSION_REQUIRED"
    #: The account holds no password to re-check, and the session is not fresh
    #: enough to stand in for one.
    RECENT_PROOF_REQUIRED = "RECENT_PROOF_REQUIRED"
    #: The password was right and the account holds a second factor, so the
    #: sign-in is not finished. Answered with the challenge to present it
    #: against.
    TOTP_REQUIRED = "TOTP_REQUIRED"
    #: The code did not match. The challenge is still standing, so the client
    #: asks again.
    TOTP_INVALID = "TOTP_INVALID"
    #: The challenge is not standing: never issued, already spent, expired, or
    #: out of attempts. One code for all four, so the client learns only that
    #: it has to begin again — the same shape as the refresh rejection above.
    TOTP_CHALLENGE_INVALID = "TOTP_CHALLENGE_INVALID"
    #: The handle and code presented together are not a waiting sign-in.
    EMAIL_OTP_INVALID = "EMAIL_OTP_INVALID"
    #: A code was asked for while the deployment cannot send mail.
    EMAIL_OTP_CANNOT_SEND = "EMAIL_OTP_CANNOT_SEND"
    #: An address has been sent as many letters as it may be in this window.
    RATE_LIMITED = "RATE_LIMITED"
    #: A code confirming the session was asked for, and the account has proved
    #: no address to send it to.
    EMAIL_OTP_NO_PROVED_ADDRESS = "EMAIL_OTP_NO_PROVED_ADDRESS"
    #: Enrolling over a factor the account has already proved.
    TOTP_ALREADY_ENROLLED = "TOTP_ALREADY_ENROLLED"
    #: The deployment does not offer the authenticator app.
    TOTP_NOT_PERMITTED = "TOTP_NOT_PERMITTED"
    #: Confirming, disabling or re-issuing codes for a factor that is not there.
    TOTP_NOT_ENROLLED = "TOTP_NOT_ENROLLED"
    #: The recovery code did not match an unused one.
    RECOVERY_CODE_INVALID = "RECOVERY_CODE_INVALID"
    #: The account already holds as many passkeys as one may.
    PASSKEY_LIMIT_REACHED = "PASSKEY_LIMIT_REACHED"
    #: The registration ceremony did not verify, or its challenge is not
    #: standing: never issued, spent, expired, or out of attempts. One code for
    #: all of those.
    PASSKEY_REGISTRATION_INVALID = "PASSKEY_REGISTRATION_INVALID"
    #: No passkey by that id on this account.
    PASSKEY_NOT_FOUND = "PASSKEY_NOT_FOUND"
    #: Passkeys need a named host and https; this deployment's address has
    #: neither.
    PASSKEY_SITE_UNSUPPORTED = "PASSKEY_SITE_UNSUPPORTED"
    #: The assertion did not verify, named a credential nobody registered, or
    #: its challenge is not standing. One code for all of those.
    PASSKEY_SIGN_IN_INVALID = "PASSKEY_SIGN_IN_INVALID"
    #: The password is the account's only way to start a session, so it stays.
    PASSWORD_IS_LAST_METHOD = "PASSWORD_IS_LAST_METHOD"
    #: The passkey is the account's only way to start a session, so it stays.
    PASSKEY_IS_LAST_METHOD = "PASSKEY_IS_LAST_METHOD"
    #: Removing a password from an account that holds none.
    PASSWORD_NOT_HELD = "PASSWORD_NOT_HELD"
    COULD_NOT_VALIDATE_CREDENTIALS = "COULD_NOT_VALIDATE_CREDENTIALS"
    INVALID_TOKEN_PAYLOAD = "INVALID_TOKEN_PAYLOAD"
    USER_NOT_FOUND = "USER_NOT_FOUND"
    INSUFFICIENT_PRIVILEGES = "INSUFFICIENT_PRIVILEGES"
    INVALID_TOKEN = "INVALID_TOKEN"
    # Generic refresh rejection: unknown / expired / reused all map here so the
    # client learns only "re-authenticate", never that a replay was detected.
    INVALID_REFRESH_TOKEN = "INVALID_REFRESH_TOKEN"
    INVALID_OR_EXPIRED_TOKEN = "INVALID_OR_EXPIRED_TOKEN"
    ACCOUNT_CHANGE_MOVED_ON = "ACCOUNT_CHANGE_MOVED_ON"
    #: Another change to the account is waiting to apply.
    ACCOUNT_CHANGE_PENDING = "ACCOUNT_CHANGE_PENDING"
    #: The waiting change was cancelled, applied, or never this account's.
    HELD_CHANGE_NOT_FOUND = "HELD_CHANGE_NOT_FOUND"
    #: Making a waiting change now needs a session proved with a passkey.
    HELD_CHANGE_NEEDS_PASSKEY = "HELD_CHANGE_NEEDS_PASSKEY"
    SMTP_NOT_CONFIGURED = "SMTP_NOT_CONFIGURED"
    CAPTCHA_REQUIRED = "CAPTCHA_REQUIRED"
    #: The session store could not be written, so no session was opened.
    #: A sign-in is the session; there is no lesser credential to hand back.
    SESSION_STORE_UNAVAILABLE = "SESSION_STORE_UNAVAILABLE"
    CAPTCHA_INVALID = "CAPTCHA_INVALID"


class ImageMessages:
    # An uploaded picture that does not meet its ``ImageSpec``. Each names the
    # rule it broke, so the page can say what to do about it rather than
    # "that didn't work".
    IMAGE_EMPTY = "IMAGE_EMPTY"
    IMAGE_TOO_LARGE = "IMAGE_TOO_LARGE"
    IMAGE_INVALID = "IMAGE_INVALID"
    IMAGE_WRONG_SIZE = "IMAGE_WRONG_SIZE"
    IMAGE_WRONG_RATIO = "IMAGE_WRONG_RATIO"


class GuildMessages:
    # The frontend error map still carries NO_GUILD_MEMBERSHIP for servers
    # that predate path-based guild resolution; the backend itself only
    # raises COMMUNITY_ACCESS_DENIED.
    COMMUNITY_ACCESS_DENIED = "COMMUNITY_ACCESS_DENIED"
    COMMUNITY_AUTH_STEP_UP_REQUIRED = "COMMUNITY_AUTH_STEP_UP_REQUIRED"
    #: The community asks that the session carried the account's second
    #: factor, and this one did not. Answered apart from the provider step-up
    #: because what satisfies it is a code rather than a sign-in page.
    COMMUNITY_AUTH_FACTOR_REQUIRED = "COMMUNITY_AUTH_FACTOR_REQUIRED"
    #: The community asks that the session was opened, or stepped up, with a
    #: passkey, and this one was not.
    COMMUNITY_AUTH_PASSKEY_REQUIRED = "COMMUNITY_AUTH_PASSKEY_REQUIRED"
    #: The deployment asks this account for a second factor and it holds none.
    #: Kept beside the two above because one dialog answers all three, and the
    #: client tells them apart by the code alone.
    PLATFORM_AUTH_FACTOR_REQUIRED = "PLATFORM_AUTH_FACTOR_REQUIRED"
    COMMUNITY_AUTH_NOT_ENABLED = "COMMUNITY_AUTH_NOT_ENABLED"
    #: The community declines personal API keys. Raised both when one is being
    #: minted into the guild and when a request carrying one addresses it, so
    #: the answer reads the same wherever it is met.
    COMMUNITY_API_KEYS_REFUSED = "COMMUNITY_API_KEYS_REFUSED"
    COMMUNITY_AUTH_POLICY_INVALID_PROVIDER = "COMMUNITY_AUTH_POLICY_INVALID_PROVIDER"
    COMMUNITY_PERMISSION_REQUIRED = "COMMUNITY_PERMISSION_REQUIRED"
    COMMUNITY_ADMIN_REQUIRED = "COMMUNITY_ADMIN_REQUIRED"
    #: The guild's sign-in configuration asks for the seat above admin.
    COMMUNITY_SUPERADMIN_REQUIRED = "COMMUNITY_SUPERADMIN_REQUIRED"
    #: Help requests were switched on with no support stream bound to
    #: receive them.
    SUPPORT_INTAKE_NOT_CONFIGURED = "SUPPORT_INTAKE_NOT_CONFIGURED"
    COMMUNITY_CREATION_DISABLED = "COMMUNITY_CREATION_DISABLED"
    FREE_COMMUNITY_ALREADY_HELD = "FREE_COMMUNITY_ALREADY_HELD"
    COMMUNITY_CREATION_LIMIT_REACHED = "COMMUNITY_CREATION_LIMIT_REACHED"
    #: A demo visitor's account holds its copy and creates no community.
    COMMUNITY_CREATION_DEMO_ACCOUNT = "COMMUNITY_CREATION_DEMO_ACCOUNT"
    # Naming another user as a new guild's admin is platform-staff only.
    COMMUNITY_OWNER_REQUIRES_CAPABILITY = "COMMUNITY_OWNER_REQUIRES_CAPABILITY"
    # ...and that user has to exist already; we never create one.
    COMMUNITY_OWNER_NOT_FOUND = "COMMUNITY_OWNER_NOT_FOUND"
    COMMUNITY_NOT_FOUND = "COMMUNITY_NOT_FOUND"
    COMMUNITY_MEMBERSHIP_CREATE_FAILED = "COMMUNITY_MEMBERSHIP_CREATE_FAILED"
    COMMUNITY_PROVISION_FAILED = "COMMUNITY_PROVISION_FAILED"
    #: Restore was asked for a guild that has not been deleted.
    COMMUNITY_NOT_DELETED = "COMMUNITY_NOT_DELETED"
    #: A guild cannot be restored *to* deleted.
    COMMUNITY_RESTORE_STATUS_INVALID = "COMMUNITY_RESTORE_STATUS_INVALID"
    #: The guild's roster no longer holds the seat that configures it, so the
    #: restore has to name the account that will.
    COMMUNITY_RESTORE_SEAT_REQUIRED = "COMMUNITY_RESTORE_SEAT_REQUIRED"
    #: ``deleted`` is reached by deleting a guild and left by restoring it,
    #: never by setting the status control to it.
    COMMUNITY_STATUS_NOT_SETTABLE = "COMMUNITY_STATUS_NOT_SETTABLE"
    #: The deployment's billing service sets this community's caps and
    #: entitlements; they are changed there.
    COMMUNITY_PLAN_SET_BY_BILLING = "COMMUNITY_PLAN_SET_BY_BILLING"
    #: Where billing sets plans, the operator moves a community into and out
    #: of a suspension and no other way.
    COMMUNITY_STATUS_SET_BY_BILLING = "COMMUNITY_STATUS_SET_BY_BILLING"
    #: Where billing sets plans, a deleted community is restored at the status
    #: billing last set or suspended.
    COMMUNITY_RESTORE_STATUS_SET_BY_BILLING = "COMMUNITY_RESTORE_STATUS_SET_BY_BILLING"
    COMMUNITY_MEMBERSHIP_MISSING = "COMMUNITY_MEMBERSHIP_MISSING"
    COMMUNITY_USER_LIMIT_REACHED = "COMMUNITY_USER_LIMIT_REACHED"
    # Asked to join a guild that is not listed in the community directory (or
    # is no longer active). Reported as a 404 — an unlisted guild has published
    # nothing, its existence at a given id included.
    COMMUNITY_NOT_A_COMMUNITY = "COMMUNITY_NOT_A_COMMUNITY"
    # The three things a guild must be before it can be listed: on at least one
    # shelf, declared free of adult content, and able to admit anyone at all.
    COMMUNITY_COMMUNITY_REQUIRES_CATEGORY = "COMMUNITY_COMMUNITY_REQUIRES_CATEGORY"
    COMMUNITY_COMMUNITY_CONTENT_NOT_DECLARED = (
        "COMMUNITY_COMMUNITY_CONTENT_NOT_DECLARED"
    )
    COMMUNITY_COMMUNITY_ADULT_CONTENT = "COMMUNITY_COMMUNITY_ADULT_CONTENT"
    COMMUNITY_COMMUNITY_REQUIRES_CAPACITY = "COMMUNITY_COMMUNITY_REQUIRES_CAPACITY"
    # A guild on its way onto the shelf that holds somebody who has answered
    # the age question as under the minimum. Only ever raised on the way in:
    # an already-listed guild is not re-checked, so an unrelated edit never
    # fails over who its members are.
    COMMUNITY_COMMUNITY_UNDER_AGE_MEMBERS = "COMMUNITY_COMMUNITY_UNDER_AGE_MEMBERS"
    # The deployment runs no community directory: an owner has not switched it
    # on. Distinct from the four rules above, which are about one guild — this
    # one says the surface does not exist here at all.
    COMMUNITY_DIRECTORY_DISABLED = "COMMUNITY_DIRECTORY_DISABLED"
    # The caller has not answered the age question, and the guild they asked to
    # join is listed in the directory. The deployment's own switch decides
    # whether this is ever raised at all.
    AGE_CONFIRMATION_REQUIRED = "COMMUNITY_AGE_CONFIRMATION_REQUIRED"
    # The caller answered the age question as under the minimum. Separate from
    # the one above because there is nothing to click: the answer stands, and
    # the reply has to say so rather than ask again.
    AGE_BELOW_MINIMUM = "COMMUNITY_AGE_BELOW_MINIMUM"
    IMAGE_NOT_FOUND = "IMAGE_NOT_FOUND"
    BANNER_COLOR_INVALID = "BANNER_COLOR_INVALID"
    # Banner text is black or white; nothing between the two is offered.
    BANNER_TEXT_COLOR_INVALID = "BANNER_TEXT_COLOR_INVALID"
    # Banner artwork is not part of what this guild has; the colour is.
    BANNER_IMAGE_NOT_ENTITLED = "BANNER_IMAGE_NOT_ENTITLED"
    CANNOT_CHANGE_OWN_ROLE = "CANNOT_CHANGE_OWN_ROLE"
    # 'support' is synthesized for PAM grantees only; it is never a stored
    # guild-membership role, so it cannot be assigned via the role endpoints.
    COMMUNITY_ROLE_NOT_ASSIGNABLE = "COMMUNITY_ROLE_NOT_ASSIGNABLE"
    USER_NOT_FOUND_IN_COMMUNITY = "USER_NOT_FOUND_IN_COMMUNITY"
    #: The guild requires a sign-in, and this is the last member who can
    #: change or lift that requirement.
    CANNOT_VACATE_LAST_SUPERADMIN = "CANNOT_VACATE_LAST_SUPERADMIN"
    NOT_COMMUNITY_MEMBER = "NOT_COMMUNITY_MEMBER"
    INVITE_NOT_FOUND = "INVITE_NOT_FOUND"
    INVITE_EXPIRED_OR_USED = "INVITE_EXPIRED_OR_USED"
    INVITE_EMAIL_MISMATCH = "INVITE_EMAIL_MISMATCH"
    #: The account holds a time-limited access grant to this community.
    INVITE_DURING_ACCESS_GRANT = "INVITE_DURING_ACCESS_GRANT"
    INVITE_INVALID = "INVITE_INVALID"
    INVITE_EXPIRED = "INVITE_EXPIRED"
    INVITE_USED = "INVITE_USED"
    INVALID_PASSWORD = "COMMUNITY_INVALID_PASSWORD"
    CONFIRMATION_MISMATCH = "COMMUNITY_CONFIRMATION_MISMATCH"


class InitiativeMessages:
    NOT_FOUND = "INITIATIVE_NOT_FOUND"
    MANAGER_REQUIRED = "INITIATIVE_MANAGER_REQUIRED"
    NAME_EXISTS = "INITIATIVE_NAME_EXISTS"
    NOT_A_MEMBER = "INITIATIVE_NOT_A_MEMBER"
    ROLE_NOT_FOUND = "INITIATIVE_ROLE_NOT_FOUND"
    ROLE_NAME_EXISTS = "INITIATIVE_ROLE_NAME_EXISTS"
    CANNOT_MODIFY_BUILTIN_PERMISSIONS = "INITIATIVE_CANNOT_MODIFY_BUILTIN_PERMISSIONS"
    CANNOT_CHANGE_BUILTIN_MANAGER = "INITIATIVE_CANNOT_CHANGE_BUILTIN_MANAGER"
    MUST_HAVE_MANAGER = "INITIATIVE_MUST_HAVE_MANAGER"
    MEMBER_ROLE_NOT_FOUND = "INITIATIVE_MEMBER_ROLE_NOT_FOUND"
    MEMBER_NOT_FOUND = "INITIATIVE_MEMBER_NOT_FOUND"
    MUST_HAVE_PM = "INITIATIVE_MUST_HAVE_PM"
    CANNOT_DELETE_BUILTIN = "INITIATIVE_CANNOT_DELETE_BUILTIN"
    ROLE_HAS_MEMBERS = "INITIATIVE_ROLE_HAS_MEMBERS"
    # A guild admin already has full access to every initiative; they may only
    # hold the manager role (for manager-style features), never a standard
    # member or custom role.
    GUILD_ADMIN_ROLE_RESTRICTED = "INITIATIVE_COMMUNITY_ADMIN_ROLE_RESTRICTED"
    # A role carrying "Full access" (override_share_restrictions) — the
    # built-in moderator — is a guild admin's to assign.
    OVERRIDE_REQUIRES_GUILD_ADMIN = "INITIATIVE_OVERRIDE_REQUIRES_COMMUNITY_ADMIN"
    # Asked to self-join an initiative whose join policy is not 'open'. Reported
    # for 'private' and 'request' alike, so the answer says only "not by this
    # route" — a request-policy initiative is discoverable through the directory.
    NOT_JOINABLE = "INITIATIVE_NOT_JOINABLE"
    # Auto-join enrols new guild members automatically, so it is only coherent on
    # an initiative they could also have found and joined themselves ('open').
    AUTO_JOIN_REQUIRES_OPEN = "INITIATIVE_AUTO_JOIN_REQUIRES_OPEN"
    # Auto-join shapes onboarding for the whole guild, so only a guild admin sets
    # it — unlike join_policy, which any initiative manager may change.
    AUTO_JOIN_ADMIN_ONLY = "INITIATIVE_AUTO_JOIN_ADMIN_ONLY"
    # A PAM grant confers content read/write for a window; a membership row
    # would outlast it, so joining is for real guild members.
    GRANT_CANNOT_MANAGE_MEMBERS = "INITIATIVE_GRANT_CANNOT_MANAGE_MEMBERS"
    # Asked to knock on an initiative whose join policy is not 'request'.
    # Reported for 'private' and 'open' alike, so — like NOT_JOINABLE — the
    # answer says only "not by this route".
    NOT_REQUESTABLE = "INITIATIVE_NOT_REQUESTABLE"
    # Nothing to ask for: the caller already holds a membership row here.
    ALREADY_A_MEMBER = "INITIATIVE_ALREADY_A_MEMBER"
    # A guild admin reaches every initiative in their guild by standing, and may
    # only ever hold a manager role in one — so there is nothing for them to
    # request, and no request that could be approved into a permitted row.
    GUILD_ADMIN_NEED_NOT_REQUEST = "INITIATIVE_COMMUNITY_ADMIN_NEED_NOT_REQUEST"
    # One live request per user per initiative (uq_initiative_join_requests_pending).
    JOIN_REQUEST_ALREADY_PENDING = "INITIATIVE_JOIN_REQUEST_ALREADY_PENDING"
    JOIN_REQUEST_NOT_FOUND = "INITIATIVE_JOIN_REQUEST_NOT_FOUND"
    # Approve/deny act on a pending row only; a resolved one is history.
    JOIN_REQUEST_ALREADY_RESOLVED = "INITIATIVE_JOIN_REQUEST_ALREADY_RESOLVED"
    # The initiative keeps its content in: nothing in it is exported on its own
    # or copied to another initiative.
    CONTENT_KEPT_IN = "INITIATIVE_CONTENT_KEPT_IN"


class ToolViewMessages:
    # The tool takes no views, or the target names an instance where the tool
    # has one page per initiative (or the other way round).
    TARGET_INVALID = "TOOL_VIEWS_TARGET_INVALID"
    # A layout or an item kind this tool does not draw.
    LAYOUT_NOT_ALLOWED = "TOOL_VIEWS_LAYOUT_NOT_ALLOWED"
    # A set holds exactly one default view.
    ONE_DEFAULT = "TOOL_VIEWS_ONE_DEFAULT"
    # More views than a target may have.
    LIMIT_REACHED = "TOOL_VIEWS_LIMIT_REACHED"
    DUPLICATE_SLUG = "TOOL_VIEWS_DUPLICATE_SLUG"
    DUPLICATE_ITEM_LAYOUT = "TOOL_VIEWS_DUPLICATE_ITEM_LAYOUT"
    # A view or item layout over its node, depth or size limit.
    TOO_LARGE = "TOOL_VIEWS_TOO_LARGE"
    # More of one plug-in's parts on an item than it may place there.
    TOO_MANY_PLUGIN_PARTS = "TOOL_VIEWS_TOO_MANY_PLUGIN_PARTS"


class ProjectMessages:
    INVALID_TEMPLATE = "PROJECT_INVALID_TEMPLATE"
    INITIATIVE_REQUIRED = "PROJECT_INITIATIVE_REQUIRED"
    # Configuring the project itself (pinning, default view, its views) — a
    # project manager, the project owner, or a guild admin.
    CONFIGURE_REQUIRED = "PROJECT_CONFIGURE_REQUIRED"


class TaskMessages:
    NOT_FOUND = "TASK_NOT_FOUND"
    #: The task was not opened by an intake stream.
    NOT_A_CASE = "TASK_NOT_A_CASE"
    MISSING_AFTER_CREATE = "TASK_MISSING_AFTER_CREATE"
    MISSING_AFTER_UPDATE = "TASK_MISSING_AFTER_UPDATE"
    MISSING_AFTER_MOVE = "TASK_MISSING_AFTER_MOVE"
    ALREADY_IN_PROJECT = "TASK_ALREADY_IN_PROJECT"
    CANNOT_MOVE_TO_TEMPLATE = "TASK_CANNOT_MOVE_TO_TEMPLATE"
    PROJECT_MISMATCH = "TASK_PROJECT_MISMATCH"
    STATUS_NOT_FOUND = "TASK_STATUS_NOT_FOUND_FOR_PROJECT"
    INVALID_ASSIGNEE_ID = "TASK_INVALID_ASSIGNEE_ID"
    DUPLICATE_NOT_FOUND = "TASK_DUPLICATE_NOT_FOUND"
    NOT_REPEATING = "TASK_NOT_REPEATING"
    NO_LATER_OCCURRENCE = "TASK_NO_LATER_OCCURRENCE"
    #: An update named a description that is no longer the stored one.
    DESCRIPTION_CHANGED = "TASK_DESCRIPTION_CHANGED"


class ChecklistMessages:
    ITEM_NOT_FOUND = "CHECKLIST_ITEM_NOT_FOUND"
    DUPLICATE_ITEM_ID = "CHECKLIST_DUPLICATE_ITEM_ID"
    TEXT_EMPTY = "CHECKLIST_TEXT_EMPTY"
    TOO_LONG = "CHECKLIST_TOO_LONG"


class TaskStatusMessages:
    NOT_FOUND = "TASK_STATUS_NOT_FOUND"
    DUPLICATE_ID = "TASK_STATUS_DUPLICATE_ID"
    CANNOT_REMOVE_LAST = "TASK_STATUS_CANNOT_REMOVE_LAST"
    FALLBACK_REQUIRED = "TASK_STATUS_FALLBACK_REQUIRED"
    FALLBACK_MUST_DIFFER = "TASK_STATUS_FALLBACK_MUST_DIFFER"


class OidcMessages:
    OIDC_NOT_ENABLED = "OIDC_NOT_ENABLED"
    OIDC_METADATA_INCOMPLETE = "OIDC_METADATA_INCOMPLETE"
    REGISTRATION_DISABLED = "OIDC_REGISTRATION_DISABLED"
    EMAIL_UNVERIFIED = "OIDC_EMAIL_UNVERIFIED"
    ACCOUNT_INACTIVE = "OIDC_ACCOUNT_INACTIVE"
    SESSION_STORE_UNAVAILABLE = "OIDC_SESSION_STORE_UNAVAILABLE"


class AddressMessages:
    """Refusals from the account's own address list."""

    ADDRESS_NOT_FOUND = "ADDRESS_NOT_FOUND"
    #: The address account mail goes to. Make another one primary first.
    PRIMARY_ADDRESS = "PRIMARY_ADDRESS"
    #: The only proven address an account has — removing it leaves no way back.
    LAST_VERIFIED_ADDRESS = "LAST_VERIFIED_ADDRESS"
    #: Account mail only goes to an address its holder has proved.
    ADDRESS_NOT_VERIFIED = "ADDRESS_NOT_VERIFIED"
    #: An account holds a bounded number of addresses.
    TOO_MANY_ADDRESSES = "TOO_MANY_ADDRESSES"
    #: Somebody proved they hold it while this claim was pending.
    ADDRESS_TAKEN = "ADDRESS_TAKEN"


class AuthProviderMessages:
    NOT_FOUND = "AUTH_PROVIDER_NOT_FOUND"
    SLUG_TAKEN = "AUTH_PROVIDER_SLUG_TAKEN"
    IN_USE = "AUTH_PROVIDER_IN_USE"
    #: Nothing answered at the address, or what answered was not reachable.
    DISCOVERY_UNREACHABLE = "AUTH_PROVIDER_DISCOVERY_UNREACHABLE"
    #: Something answered, but it names a different issuer than the one asked
    #: for — usually a copied URL that is one path segment out.
    DISCOVERY_ISSUER_MISMATCH = "AUTH_PROVIDER_DISCOVERY_ISSUER_MISMATCH"
    #: Something answered and is not an OpenID Connect discovery document.
    DISCOVERY_INVALID = "AUTH_PROVIDER_DISCOVERY_INVALID"
    #: The stored row has no issuer to check.
    DISCOVERY_NO_ISSUER = "AUTH_PROVIDER_DISCOVERY_NO_ISSUER"
    #: A community's connection, by an id that is not one of its own.
    CONNECTION_NOT_FOUND = "AUTH_PROVIDER_CONNECTION_NOT_FOUND"
    #: A community connects to a given provider once.
    CONNECTION_EXISTS = "AUTH_PROVIDER_CONNECTION_EXISTS"
    #: A narrowing is a claim and the values that admit somebody; either half
    #: alone would look configured and let nobody in, or nobody out.
    CONNECTION_HALF_NARROWED = "AUTH_PROVIDER_CONNECTION_HALF_NARROWED"
    #: An enabled connection that does not say who on the provider counts.
    CONNECTION_NEEDS_NARROWING = "CONNECTION_NEEDS_NARROWING"
    # Some account signs in only through it; the delete waits until those
    # accounts hold another credential.
    SOLE_CREDENTIAL = "AUTH_PROVIDER_SOLE_CREDENTIAL"
    #: A community's rule, by an id that is not one of its own.
    RULE_NOT_FOUND = "AUTH_PROVIDER_RULE_NOT_FOUND"
    #: A rule reads a provider's groups, so the community has to count that
    #: provider as one of its own before it can say what its groups mean.
    RULE_PROVIDER_NOT_CONNECTED = "AUTH_PROVIDER_RULE_PROVIDER_NOT_CONNECTED"
    #: One group lands in one place. A second rule for the same group and the
    #: same destination would be two answers to one question.
    RULE_EXISTS = "AUTH_PROVIDER_RULE_EXISTS"
    #: A provider rule names a community that neither accepts the platform's
    #: rules for that provider nor is covered by the deployment applying them
    #: everywhere.
    PLACEMENT_NOT_ACCEPTED = "AUTH_PROVIDER_PLACEMENT_NOT_ACCEPTED"
    #: A provider rule names neither a group nor a directory to match.
    RULE_NEEDS_A_MATCH = "AUTH_PROVIDER_RULE_NEEDS_A_MATCH"
    #: A provider rule names a directory claim without a value, or a value
    #: without the claim.
    RULE_SCOPE_HALF_SET = "AUTH_PROVIDER_RULE_SCOPE_HALF_SET"


class TagMessages:
    NOT_FOUND = "TAG_NOT_FOUND"
    NAME_ALREADY_EXISTS = "TAG_NAME_ALREADY_EXISTS"
    # Shared by every set-tags / bulk-tags surface: one or more of the
    # submitted tag ids does not resolve to an active tag in this guild.
    INVALID_TAG_IDS = "INVALID_TAG_IDS"


class PropertyMessages:
    DEFINITION_NOT_FOUND = "PROPERTY_DEFINITION_NOT_FOUND"
    NAME_ALREADY_EXISTS = "PROPERTY_NAME_ALREADY_EXISTS"
    INVALID_VALUE_FOR_TYPE = "PROPERTY_INVALID_VALUE_FOR_TYPE"
    OPTION_NOT_IN_DEFINITION = "PROPERTY_OPTION_NOT_IN_DEFINITION"
    NOT_INITIATIVE_MEMBER = "PROPERTY_NOT_INITIATIVE_MEMBER"
    OPTIONS_REQUIRED = "PROPERTY_OPTIONS_REQUIRED"
    DUPLICATE_OPTION_VALUE = "PROPERTY_DUPLICATE_OPTION_VALUE"


class AttachmentMessages:
    IMAGE_ONLY = "ATTACHMENT_IMAGE_ONLY"
    FILE_EMPTY = "ATTACHMENT_FILE_EMPTY"
    INVALID_IMAGE = "ATTACHMENT_INVALID_IMAGE"
    TOO_LARGE = "ATTACHMENT_TOO_LARGE"
    STORAGE_QUOTA_EXCEEDED = "ATTACHMENT_STORAGE_QUOTA_EXCEEDED"


class FileMessages:
    NAME_ALREADY_EXISTS = "FILE_NAME_ALREADY_EXISTS"
    NAME_REQUIRED = "FILE_NAME_REQUIRED"
    LIVE_SESSION_OWNS_CONTENT = "FILE_LIVE_SESSION_OWNS_CONTENT"
    #: A write named a version of the content that is no longer current.
    CONTENT_CHANGED = "FILE_CONTENT_CHANGED"
    COLLABORATION_UPDATE_INVALID = "FILE_COLLABORATION_UPDATE_INVALID"
    AI_NATIVE_ONLY = "FILE_AI_NATIVE_ONLY"
    SMART_LINK_URL_REQUIRED = "FILE_SMART_LINK_URL_REQUIRED"
    SPREADSHEET_INVALID_PAYLOAD = "FILE_SPREADSHEET_INVALID_PAYLOAD"
    SPREADSHEET_UNREADABLE_FILE = "FILE_SPREADSHEET_UNREADABLE_FILE"
    SPREADSHEET_FILE_TOO_LARGE = "FILE_SPREADSHEET_FILE_TOO_LARGE"
    SMART_LINK_URL_INVALID = "FILE_SMART_LINK_URL_INVALID"
    NOT_AN_UPLOADED_FILE = "FILE_NOT_AN_UPLOADED_FILE"
    VERSION_NOT_FOUND = "FILE_VERSION_NOT_FOUND"
    CANNOT_DELETE_LAST_VERSION = "FILE_CANNOT_DELETE_LAST_VERSION"
    VERSION_TYPE_MISMATCH = "FILE_VERSION_TYPE_MISMATCH"
    VERSION_CONFLICT = "FILE_VERSION_CONFLICT"
    INVALID_FILE = "FILE_INVALID_FILE"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"


class CommentMessages:
    NOT_FOUND = "COMMENT_NOT_FOUND"
    PERMISSION_DENIED = "COMMENT_PERMISSION_DENIED"
    PARENT_NOT_FOUND = "COMMENT_PARENT_NOT_FOUND"
    TARGET_NOT_FOUND = "COMMENT_TARGET_NOT_FOUND"
    PARENT_MISMATCH = "COMMENT_PARENT_MISMATCH"
    PROVIDE_ONE_ENTITY = "COMMENT_PROVIDE_ONE_ENTITY"
    AUTHOR_ONLY_EDIT = "COMMENT_AUTHOR_ONLY_EDIT"
    AUTHOR_ONLY_DELETE = "COMMENT_AUTHOR_ONLY_DELETE"
    #: A moderator took it down, or its author deleted it: it has no words to
    #: edit or react to.
    REMOVED = "COMMENT_REMOVED"
    #: A moderator closed the thread to new comments.
    LOCKED = "COMMENT_THREAD_LOCKED"
    NOT_LINKED = "COMMENT_NOT_LINKED"
    COMMENTS_DISABLED = "COMMENTS_DISABLED"
    #: Only an operations case with somebody to answer takes a comment said to
    #: whoever filed it.
    NOT_SAID_TO_A_FILER = "COMMENT_NOT_SAID_TO_A_FILER"
    #: A reply is said to whoever its parent was said to.
    AUDIENCE_MISMATCH = "COMMENT_AUDIENCE_MISMATCH"


class SharingMessages:
    """Refusals from the sharing flow.

    One code per tool, derived from the enum rather than written out, so a new
    tool has one the day it exists. ``tools_test`` fails if a locale has not
    been given the wording for it.
    """

    #: A grant naming an installed plug-in, sent to a resource's own sharing. What
    #: a plug-in may reach is granted by the community's seat, so this list
    #: neither writes nor removes one.
    PLUGIN_INSTALL_GRANT_NOT_SET_HERE = "SHARING_PLUGIN_INSTALL_GRANT_NOT_SET_HERE"

    @staticmethod
    def grantee_lacks_tool(tool: "Tool") -> str:
        """Sharing was addressed to somebody whose role does not reach ``tool``."""
        return f"GRANTEE_LACKS_{tool.value.upper()}_ACCESS"


class ReactionMessages:
    TARGET_NOT_FOUND = "REACTION_TARGET_NOT_FOUND"
    PERMISSION_DENIED = "REACTION_PERMISSION_DENIED"
    TOO_MANY = "REACTION_TOO_MANY"
    DISABLED = "REACTION_DISABLED"


class RelationshipMessages:
    """One vocabulary for links, whatever two kinds a link is between.

    ``CROSS_INITIATIVE``: a link made from a picker stays inside one initiative.
    """

    BAD_ENDPOINT = "RELATIONSHIP_BAD_ENDPOINT"
    #: A directional link describes its source, so making one asks to change
    #: that end. Refused here with a name, rather than left to arrive as the
    #: database declining the write.
    SOURCE_NOT_WRITABLE = "RELATIONSHIP_SOURCE_NOT_WRITABLE"
    ENDPOINT_NOT_FOUND = "RELATIONSHIP_ENDPOINT_NOT_FOUND"
    CROSS_INITIATIVE = "RELATIONSHIP_CROSS_INITIATIVE"
    ENDPOINT_ARCHIVED = "RELATIONSHIP_ENDPOINT_ARCHIVED"
    SELF = "RELATIONSHIP_SELF"
    EXISTS = "RELATIONSHIP_EXISTS"
    NOT_FOUND = "RELATIONSHIP_NOT_FOUND"
    REMOVE_DENIED = "RELATIONSHIP_REMOVE_DENIED"
    #: A link nobody made by hand, so there is none to make or take back here.
    #: It is written when a body naming the other thing is saved, and withdrawn
    #: by editing that body.
    DERIVED = "RELATIONSHIP_DERIVED"


class SettingsMessages:
    PROVIDE_TEST_EMAIL = "SETTINGS_PROVIDE_TEST_EMAIL"
    SMTP_INCOMPLETE = "SETTINGS_SMTP_INCOMPLETE"
    # Generic code for a failed SMTP delivery — the raw exception (which can
    # carry the SMTP host, port, or server banner) is logged server-side only
    # and never returned to the client.
    EMAIL_SEND_FAILED = "SETTINGS_EMAIL_SEND_FAILED"
    INVALID_GUILD_ROLE = "SETTINGS_INVALID_COMMUNITY_ROLE"
    INITIATIVE_WRONG_GUILD = "SETTINGS_INITIATIVE_WRONG_COMMUNITY"
    INITIATIVE_FIELDS_REQUIRED = "SETTINGS_INITIATIVE_FIELDS_REQUIRED"
    # The permitted sign-in methods.
    #: A guild still requires a sign-in through a provider it connects to.
    LOGIN_METHODS_GUILD_POLICIES = "SETTINGS_LOGIN_METHODS_COMMUNITY_POLICIES"
    LOGIN_METHODS_EMPTY = "SETTINGS_LOGIN_METHODS_EMPTY"
    #: Something is ticked, but nothing that can begin a session — an
    #: authenticator code accompanies a sign-in rather than opening one.
    LOGIN_METHODS_NO_PRIMARY = "SETTINGS_LOGIN_METHODS_NO_PRIMARY"
    LOGIN_METHODS_WOULD_STRAND = "SETTINGS_LOGIN_METHODS_WOULD_STRAND"
    #: The change would leave the account making it with no way in. Not
    #: acknowledgeable: the account adds another way in first.
    LOGIN_METHODS_WOULD_STRAND_SELF = "SETTINGS_LOGIN_METHODS_WOULD_STRAND_SELF"
    #: The acknowledged number no longer matches what withdrawing would strand.
    LOGIN_METHODS_STALE_ACKNOWLEDGEMENT = "SETTINGS_LOGIN_METHODS_STALE_ACK"
    #: The method used to reach this endpoint is not one the platform permits.
    LOGIN_METHOD_NOT_PERMITTED = "SETTINGS_LOGIN_METHOD_NOT_PERMITTED"
    #: Withdrawing the last method that could answer the deployment's own
    #: second-factor requirement, while that requirement stands.
    LOGIN_METHODS_FACTOR_REQUIRED = "SETTINGS_LOGIN_METHODS_FACTOR_REQUIRED"
    #: Permitting the emailed code while the deployment cannot send mail.
    LOGIN_METHODS_NO_EMAIL = "SETTINGS_LOGIN_METHODS_NO_EMAIL"

    # Object storage
    STORAGE_BACKFILL_RUNNING = "SETTINGS_STORAGE_BACKFILL_RUNNING"
    STORAGE_BACKFILL_NOT_CONFIGURED = "SETTINGS_STORAGE_BACKFILL_NOT_CONFIGURED"


class EvidenceMessages:
    """What a person attaches to a ticket or a report."""

    #: The stream takes no files.
    NOT_TAKEN = "EVIDENCE_NOT_TAKEN"
    TOO_MANY = "EVIDENCE_TOO_MANY"
    TOO_LARGE = "EVIDENCE_TOO_LARGE"
    EMPTY = "EVIDENCE_EMPTY"
    #: Its bytes are not one of the types the stream takes.
    TYPE_NOT_ALLOWED = "EVIDENCE_TYPE_NOT_ALLOWED"
    #: A picture that could not be read to take its location out.
    UNREADABLE = "EVIDENCE_UNREADABLE"
    NOT_FOUND = "EVIDENCE_NOT_FOUND"


class ModerationMessages:
    """Reporting something, and settling a report."""

    REPORT_NOT_FOUND = "MODERATION_REPORT_NOT_FOUND"
    REPORT_ALREADY_SETTLED = "MODERATION_REPORT_ALREADY_SETTLED"
    UNKNOWN_TARGET_TYPE = "MODERATION_UNKNOWN_TARGET_TYPE"
    NOWHERE_TO_SEND = "MODERATION_NOWHERE_TO_SEND"
    TARGET_NOT_FOUND = "MODERATION_TARGET_NOT_FOUND"
    NOT_A_MODERATOR = "MODERATION_NOT_A_MODERATOR"
    #: An ``illegal`` report names the law it falls under.
    LEGAL_BASIS_REQUIRED = "MODERATION_LEGAL_BASIS_REQUIRED"
    #: Only an ``illegal`` report names a law.
    LEGAL_BASIS_NOT_TAKEN = "MODERATION_LEGAL_BASIS_NOT_TAKEN"
    #: An ``illegal`` or ``other`` report says what is wrong.
    DETAIL_REQUIRED = "MODERATION_DETAIL_REQUIRED"
    #: A child-safety report names where the material is and attaches none.
    NO_ATTACHMENTS = "MODERATION_NO_ATTACHMENTS"
    #: That act isn't done to that kind of thing.
    ACT_NOT_TAKEN = "MODERATION_ACT_NOT_TAKEN"
    #: It is taken down already.
    ALREADY_REMOVED = "MODERATION_ALREADY_REMOVED"
    #: The removal named was undone already, or what it took down is gone.
    NOT_REMOVED = "MODERATION_NOT_REMOVED"
    #: That log row isn't a removal.
    NOT_A_REMOVAL = "MODERATION_NOT_A_REMOVAL"
    ACTION_NOT_FOUND = "MODERATION_ACTION_NOT_FOUND"
    #: The thread is locked already, or not locked.
    ALREADY_LOCKED = "MODERATION_ALREADY_LOCKED"
    NOT_LOCKED = "MODERATION_NOT_LOCKED"
    #: A warning says what the member is told.
    MESSAGE_REQUIRED = "MODERATION_MESSAGE_REQUIRED"
    #: Nobody wrote it, so there is nobody to warn.
    NOBODY_TO_WARN = "MODERATION_NOBODY_TO_WARN"


class HoldMessages:
    """Holding content for the platform, and releasing a hold."""

    #: There is nothing to hold there, or nothing the reader may hold.
    TARGET_NOT_FOUND = "HOLD_TARGET_NOT_FOUND"
    #: Holding is for the community's moderators and the platform's.
    NOT_ALLOWED = "HOLD_NOT_ALLOWED"
    #: It is held already.
    ALREADY_HELD = "HOLD_ALREADY_HELD"
    #: A hold for illegal content names the law it falls under.
    LEGAL_BASIS_REQUIRED = "HOLD_LEGAL_BASIS_REQUIRED"
    #: The platform takes no moderation cases here, so nobody would see it.
    NOWHERE_TO_SEND = "HOLD_NOWHERE_TO_SEND"
    NOT_FOUND = "HOLD_NOT_FOUND"
    ALREADY_RELEASED = "HOLD_ALREADY_RELEASED"
    #: The case named isn't one the platform is working.
    CASE_NOT_FOUND = "HOLD_CASE_NOT_FOUND"
    #: Another hold still covers it, so it can't be removed or destroyed.
    COVERED_BY_ANOTHER = "HOLD_COVERED_BY_ANOTHER"
    #: The community is being deleted for good.
    COMMUNITY_GONE = "HOLD_COMMUNITY_GONE"


class SecurityMessages:
    """Telling whoever runs this server about a security problem."""

    #: Nothing is set up to receive security reports here.
    NOWHERE_TO_SEND = "SECURITY_NOWHERE_TO_SEND"


class SupportMessages:
    """Asking whoever runs this deployment for help."""

    NOT_AVAILABLE = "SUPPORT_NOT_AVAILABLE"
    NOWHERE_TO_SEND = "SUPPORT_NOWHERE_TO_SEND"


class FeedbackMessages:
    """Telling whoever runs this server what somebody thinks."""

    #: Nothing is set up to receive feedback here.
    NOWHERE_TO_SEND = "FEEDBACK_NOWHERE_TO_SEND"


class AppealMessages:
    """Asking for an account's suspension to be lifted."""

    #: The account is not suspended: there is nothing to appeal.
    NOT_SUSPENDED = "APPEAL_NOT_SUSPENDED"
    #: Nothing is set up to receive appeals here.
    NOWHERE_TO_SEND = "APPEAL_NOWHERE_TO_SEND"


class TicketMessages:
    """Filing a ticket, whatever kind."""

    FILING_TOO_FAST = "TICKET_FILING_TOO_FAST"
    TOO_MANY_OPEN = "TICKET_TOO_MANY_OPEN"
    NOT_FOUND = "TICKET_NOT_FOUND"
    REPLY_NOT_TAKEN = "TICKET_REPLY_NOT_TAKEN"


class IntakeMessages:
    """Binding a stream of operations work to a project."""

    GUILD_NOT_ACTIVE = "INTAKE_COMMUNITY_NOT_ACTIVE"
    NO_OPERATIONS_GUILD = "INTAKE_NO_OPERATIONS_COMMUNITY"
    STATUS_NOT_IN_PROJECT = "INTAKE_STATUS_NOT_IN_PROJECT"
    PROJECT_NOT_LIVE = "INTAKE_PROJECT_NOT_LIVE"
    UNKNOWN_STREAM = "INTAKE_UNKNOWN_STREAM"
    #: A stream that keeps an initiative to itself, or one that would share
    #: such a stream's initiative.
    INITIATIVE_SHARED = "INTAKE_INITIATIVE_SHARED"


class OperatorMessages:
    CANNOT_RESET_INACTIVE = "OPERATOR_CANNOT_RESET_INACTIVE"
    USER_ALREADY_ACTIVE = "OPERATOR_USER_ALREADY_ACTIVE"
    #: Reactivate is for a deactivated account; a suspension is lifted and a
    #: deletion restored through their own actions.
    USER_NOT_DEACTIVATED = "OPERATOR_USER_NOT_DEACTIVATED"
    #: Account actions reach only accounts at or below the caller's own rung.
    CANNOT_MANAGE_HIGHER_ROLE = "OPERATOR_CANNOT_MANAGE_HIGHER_ROLE"
    #: Restore was asked for an account that has not been deleted.
    USER_NOT_DELETED = "OPERATOR_USER_NOT_DELETED"
    #: A confirmation letter was asked for an account with no address left to
    #: confirm.
    NOTHING_TO_VERIFY = "OPERATOR_NOTHING_TO_VERIFY"
    CANNOT_SUSPEND_SELF = "OPERATOR_CANNOT_SUSPEND_SELF"
    CANNOT_SUSPEND_INACTIVE = "OPERATOR_CANNOT_SUSPEND_INACTIVE"
    CANNOT_SUSPEND_HIGHER_ROLE = "OPERATOR_CANNOT_SUSPEND_HIGHER_ROLE"
    ALREADY_ANONYMIZED = "OPERATOR_ALREADY_ANONYMIZED"
    CANNOT_CHANGE_ROLE_INACTIVE = "OPERATOR_CANNOT_CHANGE_ROLE_INACTIVE"
    CANNOT_CHANGE_OWN_ROLE = "OPERATOR_CANNOT_CHANGE_OWN_ROLE"
    CANNOT_ASSIGN_HIGHER_ROLE = "OPERATOR_CANNOT_ASSIGN_HIGHER_ROLE"
    USE_SELF_DELETION = "OPERATOR_USE_SELF_DELETION"
    CANNOT_DELETE_SELF = "OPERATOR_CANNOT_DELETE_SELF"


class AccessGrantMessages:
    NOT_FOUND = "ACCESS_GRANT_NOT_FOUND"
    COMMUNITY_NOT_FOUND = "ACCESS_GRANT_COMMUNITY_NOT_FOUND"
    DURATION_TOO_LONG = "ACCESS_GRANT_DURATION_TOO_LONG"
    ALREADY_MEMBER = "ACCESS_GRANT_ALREADY_MEMBER"
    OVERLAPPING_GRANT = "ACCESS_GRANT_OVERLAPPING"
    NOT_PENDING = "ACCESS_GRANT_NOT_PENDING"
    NOT_ACTIVE = "ACCESS_GRANT_NOT_ACTIVE"
    CANNOT_APPROVE_OWN = "ACCESS_GRANT_CANNOT_APPROVE_OWN"
    CANNOT_CANCEL_OTHERS = "ACCESS_GRANT_CANNOT_CANCEL_OTHERS"
    #: Approving asks whether the requester may still request access: an
    #: active account whose role holds ``access.request``.
    GRANTEE_INELIGIBLE = "ACCESS_GRANT_GRANTEE_INELIGIBLE"
    #: A ``moderate`` grant is for those who hold ``content.moderate``.
    MODERATE_NOT_HELD = "ACCESS_GRANT_MODERATE_NOT_HELD"
    #: A settings rung reads; changing what it reaches takes a read_write
    #: content grant beside it.
    WRITE_GRANT_REQUIRED = "ACCESS_GRANT_WRITE_REQUIRED"
    # Break-glass (self-approved, data.bypass holders): a live grant for this
    # guild already exists, so there's nothing to self-issue.
    ALREADY_LIVE = "ACCESS_GRANT_ALREADY_LIVE"
    # Break-glass carries the account's own second factor once any data.bypass
    # holder has one. ENROLMENT_REQUIRED is the refusal for a holder who has
    # not set one up, whose way on is their own Security page.
    SECOND_FACTOR_REQUIRED = "ACCESS_GRANT_SECOND_FACTOR_REQUIRED"
    SECOND_FACTOR_ENROLMENT_REQUIRED = "ACCESS_GRANT_SECOND_FACTOR_ENROLMENT_REQUIRED"
    # The assertion presented against a break-glass request did not answer.
    PASSKEY_INVALID = "ACCESS_GRANT_PASSKEY_INVALID"


class PasswordMessages:
    TOO_SHORT = "PASSWORD_TOO_SHORT"
    BREACHED = "PASSWORD_BREACHED"


class UserMessages:
    #: The change would leave the platform with nobody who can configure it.
    CANNOT_REMOVE_LAST_OWNER = "USER_CANNOT_REMOVE_LAST_OWNER"
    INVALID_PASSWORD = "USER_INVALID_PASSWORD"
    CONFIRMATION_MISMATCH = "USER_CONFIRMATION_MISMATCH"
    API_KEY_NOT_FOUND = "USER_API_KEY_NOT_FOUND"
    API_KEY_READ_ONLY = "USER_API_KEY_READ_ONLY"
    API_KEY_GUILD_FORBIDDEN = "USER_API_KEY_COMMUNITY_FORBIDDEN"
    #: A key may name one resource of a tool that has a feed, in the community
    #: it is limited to.
    API_KEY_RESOURCE_INVALID = "USER_API_KEY_RESOURCE_INVALID"
    #: A key that names one resource reads that resource's feed and nothing else.
    API_KEY_RESOURCE_ONLY = "USER_API_KEY_RESOURCE_ONLY"
    USERNAME_ALREADY_CHOSEN = "USERNAME_ALREADY_CHOSEN"
    #: The date given puts this account under the minimum age for the parts of
    #: the platform that are open to people they have not met.
    AGE_BELOW_MINIMUM = "USER_AGE_BELOW_MINIMUM"
    #: The date given at sign-up is under the minimum age for an account where
    #: the person is. No account is made.
    AGE_BELOW_ACCOUNT_MINIMUM = "USER_AGE_BELOW_ACCOUNT_MINIMUM"
    #: A date that is not one somebody could have been born on — in the future,
    #: or further back than a person lives.
    AGE_INVALID_BIRTHDATE = "USER_AGE_INVALID_BIRTHDATE"
    #: The account already answered as under age. The answer stands until
    #: somebody with the standing to put it right lifts it.
    AGE_ANSWER_STANDS = "USER_AGE_ANSWER_STANDS"
    #: Asked to lift an age block on an account that has none.
    AGE_NOT_BLOCKED = "USER_AGE_NOT_BLOCKED"
    #: Asked to turn password sign-in back on for an account where it is on.
    SIGN_IN_NOT_LOCKED = "USER_SIGN_IN_NOT_LOCKED"
    #: Asked to revoke an account's API keys when none of them still work.
    NO_LIVE_API_KEYS = "USER_NO_LIVE_API_KEYS"
    CURRENT_PASSWORD_REQUIRED = "USER_CURRENT_PASSWORD_REQUIRED"
    CURRENT_PASSWORD_INCORRECT = "USER_CURRENT_PASSWORD_INCORRECT"
    #: A new password was sent beside a field other than the current password.
    PASSWORD_CHANGED_ALONE = "USER_PASSWORD_CHANGED_ALONE"
    INVALID_WEEK_START = "USER_INVALID_WEEK_START"
    INVALID_TIME_FORMAT = "USER_INVALID_TIME_FORMAT"
    INVALID_REMINDER_MINUTES = "USER_INVALID_REMINDER_MINUTES"
    INVALID_TASK_COMPLETION_VISUAL_FEEDBACK = (
        "USER_INVALID_TASK_COMPLETION_VISUAL_FEEDBACK"
    )
    CANNOT_DELETE_SELF = "USER_CANNOT_DELETE_SELF"
    OWNER_MUST_BE_COMMUNITY_ADMIN = "OWNER_MUST_BE_COMMUNITY_ADMIN"
    OWNER_ALREADY_HOLDS_CONTENT = "OWNER_ALREADY_HOLDS_CONTENT"
    #: The installed plug-in named as the new owner may not own that content: it
    #: is off or gone, lacks the tool's write scope, or is not placed in the
    #: content's initiative.
    OWNER_PLUGIN_NOT_ELIGIBLE = "OWNER_PLUGIN_NOT_ELIGIBLE"
    NOT_IN_GUILD = "USER_NOT_IN_COMMUNITY"
    AVATAR_INVALID_IMAGE = "USER_AVATAR_INVALID_IMAGE"
    AVATAR_NOT_SQUARE = "USER_AVATAR_NOT_SQUARE"
    AVATAR_TOO_LARGE_DIMENSIONS = "USER_AVATAR_TOO_LARGE_DIMENSIONS"
    # A read payload's ``avatar_url`` is a path this API serves; writing one
    # back would store it as though it were an external picture URL.
    #: A decoration this account's library does not answer for — one it does
    #: not have, or one it has for a different slot.
    DECORATION_NOT_OWNED = "USER_DECORATION_NOT_OWNED"
    #: A pack id this build does not ship.
    DECORATION_PACK_NOT_FOUND = "USER_DECORATION_PACK_NOT_FOUND"
    #: A decoration this library already holds from a different pack.
    DECORATION_ALREADY_GRANTED = "USER_DECORATION_ALREADY_GRANTED"


class UsernameMessages:
    """Why a name part cannot be stored."""

    TOO_SHORT = "USERNAME_TOO_SHORT"
    TOO_LONG = "USERNAME_TOO_LONG"
    INVALID_CHARACTERS = "USERNAME_INVALID_CHARACTERS"
    MUST_START_WITH_LETTER = "USERNAME_MUST_START_WITH_LETTER"
    RESERVED = "USERNAME_RESERVED"
    #: Every number behind the name part is taken.
    UNAVAILABLE = "USERNAME_UNAVAILABLE"


class ProjectExportMessages:
    NO_TASK_STATUSES = "PROJECT_EXPORT_NO_TASK_STATUSES"


class ExportMessages:
    EXPORT_UNKNOWN_SOURCE = "EXPORT_UNKNOWN_SOURCE"
    EXPORT_INVALID_FORMAT = "EXPORT_INVALID_FORMAT"
    EXPORT_INVALID_PARAMS = "EXPORT_INVALID_PARAMS"
    EXPORT_TOO_LARGE = "EXPORT_TOO_LARGE"
    EXPORT_JOB_LIMIT_REACHED = "EXPORT_JOB_LIMIT_REACHED"
    EXPORT_WRITE_REQUIRED = "EXPORT_WRITE_REQUIRED"
    EXPORT_OWNER_REQUIRED = "EXPORT_OWNER_REQUIRED"
    EXPORT_JOB_NOT_FOUND = "EXPORT_JOB_NOT_FOUND"
    EXPORT_NOT_READY = "EXPORT_NOT_READY"
    #: A finished export whose artifact is past its expiry.
    EXPORT_EXPIRED = "EXPORT_EXPIRED"
    #: A finished export holding content from an initiative the caller no
    #: longer reaches.
    EXPORT_OUT_OF_REACH = "EXPORT_OUT_OF_REACH"
    EXPORT_SUPERADMIN_REQUIRED = "EXPORT_SUPERADMIN_REQUIRED"
    EXPORT_THIRD_PARTY_PLUGIN = "EXPORT_THIRD_PARTY_PLUGIN"
    EXPORT_DESTINATION_REQUIRED = "EXPORT_DESTINATION_REQUIRED"
    EXPORT_COOLDOWN_ACTIVE = "EXPORT_COOLDOWN_ACTIVE"
    EXPORT_DELIVERED = "EXPORT_DELIVERED"
    #: Recorded on a job whose creator's account is no longer active.
    EXPORT_CREATOR_INACTIVE = "EXPORT_CREATOR_INACTIVE"
    #: Recorded on a job whose creator no longer reaches the community.
    EXPORT_ACCESS_REVOKED = "EXPORT_ACCESS_REVOKED"
    #: Recorded on a job whose render failed for any other reason.
    EXPORT_RENDER_FAILED = "EXPORT_RENDER_FAILED"


class ImportEngineMessages:
    IMPORT_UNKNOWN_TYPE = "IMPORT_UNKNOWN_TYPE"
    IMPORT_INVALID_ENVELOPE = "IMPORT_INVALID_ENVELOPE"
    IMPORT_SCHEMA_VERSION_UNSUPPORTED = "IMPORT_SCHEMA_VERSION_UNSUPPORTED"
    IMPORT_INVALID_PARAMS = "IMPORT_INVALID_PARAMS"
    IMPORT_TOO_LARGE = "IMPORT_TOO_LARGE"
    IMPORT_JOB_LIMIT_REACHED = "IMPORT_JOB_LIMIT_REACHED"
    IMPORT_WRITE_REQUIRED = "IMPORT_WRITE_REQUIRED"
    IMPORT_SUPERADMIN_REQUIRED = "IMPORT_SUPERADMIN_REQUIRED"
    IMPORT_JOB_NOT_FOUND = "IMPORT_JOB_NOT_FOUND"
    IMPORT_NOT_CANCELLABLE = "IMPORT_NOT_CANCELLABLE"
    IMPORT_NOT_CONFIRMABLE = "IMPORT_NOT_CONFIRMABLE"
    IMPORT_ZIP_INVALID = "IMPORT_ZIP_INVALID"
    IMPORT_QUOTA_EXCEEDED = "IMPORT_QUOTA_EXCEEDED"
    IMPORT_ACCESS_REVOKED = "IMPORT_ACCESS_REVOKED"
    IMPORT_INTERRUPTED = "IMPORT_INTERRUPTED"
    IMPORT_APPLY_FAILED = "IMPORT_APPLY_FAILED"
    IMPORT_CREATOR_INACTIVE = "IMPORT_CREATOR_INACTIVE"
    IMPORT_PERMISSION_REQUIRED = "IMPORT_PERMISSION_REQUIRED"
    IMPORT_TOOL_DISABLED = "IMPORT_TOOL_DISABLED"
    #: A zip that does not hold exactly one export at its top level.
    IMPORT_ARCHIVE_NO_ENVELOPE = "IMPORT_ARCHIVE_NO_ENVELOPE"
    #: An export of a different tool than the one it was imported from.
    IMPORT_WRONG_TOOL = "IMPORT_WRONG_TOOL"
    #: A backup's file entry whose file was not restored: left out of the
    #: backup, or refused when it was read.
    IMPORT_ASSET_MISSING = "IMPORT_ASSET_MISSING"

    # Reading a foreign source. These name what the SOURCE said or did, which
    # is a different thing from anything the envelope path can go wrong at:
    # the person has to fix something at the other end, not in this app.
    #: The site did not answer, or did not answer as a site of this kind.
    IMPORT_SOURCE_UNREACHABLE = "IMPORT_SOURCE_UNREACHABLE"
    #: A file offered as one product's export that is not one.
    IMPORT_UNKNOWN_SOURCE = "IMPORT_UNKNOWN_SOURCE"
    #: A file that could not be read as the format it was offered as.
    IMPORT_FILE_UNREADABLE = "IMPORT_FILE_UNREADABLE"
    #: The credential was refused, or it does not reach what was asked for.
    IMPORT_SOURCE_AUTH = "IMPORT_SOURCE_AUTH"
    #: The site asked us to slow down more than the job is willing to wait.
    IMPORT_SOURCE_RATE_LIMITED = "IMPORT_SOURCE_RATE_LIMITED"
    #: The site was still being read when the fetch's time ran out.
    IMPORT_SOURCE_TOO_SLOW = "IMPORT_SOURCE_TOO_SLOW"
    #: The address resolves inside a private network, which this client will
    #: not connect to — the same rule webhooks and the AI client follow.
    IMPORT_SOURCE_PRIVATE_HOST = "IMPORT_SOURCE_PRIVATE_HOST"
    #: The request named nothing to bring over.
    IMPORT_SOURCE_NOTHING_SELECTED = "IMPORT_SOURCE_NOTHING_SELECTED"
    #: The connection a job was started with is not there to use: it aged out,
    #: another job already spent it, or it was never this person's. One code
    #: for all three, because the fix is the same — connect again.
    IMPORT_CREDENTIAL_UNAVAILABLE = "IMPORT_CREDENTIAL_UNAVAILABLE"


class QueryMessages:
    INVALID_CONDITIONS = "QUERY_INVALID_CONDITIONS"
    INVALID_SORT_FIELDS = "QUERY_INVALID_SORT_FIELDS"
    #: A view the tool does not have, such as templates of a tool with none.
    UNKNOWN_VIEW = "QUERY_UNKNOWN_VIEW"

    # The SQL query surface. Each names what a reader has to change about
    # their query, and travels with the offending word as detail so a client
    # can point at it.

    #: The text is not SQL this build can parse.
    UNPARSEABLE = "QUERY_UNPARSEABLE"
    #: More than one statement in the text.
    ONE_STATEMENT_ONLY = "QUERY_ONE_STATEMENT_ONLY"
    #: The statement is not a SELECT.
    READ_ONLY = "QUERY_READ_ONLY"
    #: Valid SQL, but a construct this surface does not accept.
    UNSUPPORTED_SYNTAX = "QUERY_UNSUPPORTED_SYNTAX"
    #: A function outside the allow-list.
    UNSUPPORTED_FUNCTION = "QUERY_UNSUPPORTED_FUNCTION"
    #: A name that is not one of the datasets this deployment offers.
    UNKNOWN_RELATION = "QUERY_UNKNOWN_RELATION"
    #: A statement that reads no relation. A query on this surface asks about
    #: data, and the caller has to know which data to check the reader against.
    MISSING_RELATION = "QUERY_MISSING_RELATION"
    #: A schema-qualified name. Relations are named on their own.
    QUALIFIED_RELATION = "QUERY_QUALIFIED_RELATION"
    #: A column the named dataset does not have.
    UNKNOWN_FIELD = "QUERY_UNKNOWN_FIELD"
    #: A field that exists but is computed rather than stored, so there is no
    #: column for a query to name yet.
    FIELD_NOT_SELECTABLE = "QUERY_FIELD_NOT_SELECTABLE"
    #: A column read beside an aggregate without being grouped, so there is no
    #: one value of it per row of the answer.
    UNGROUPED_FIELD = "QUERY_UNGROUPED_FIELD"
    #: An unqualified column that more than one relation in scope could mean.
    AMBIGUOUS_FIELD = "QUERY_AMBIGUOUS_FIELD"
    #: The same alias used for two relations.
    DUPLICATE_ALIAS = "QUERY_DUPLICATE_ALIAS"
    #: A join with nothing joining it, which pairs every row with every row.
    JOIN_WITHOUT_CONDITION = "QUERY_JOIN_WITHOUT_CONDITION"
    #: More relations in one statement than this surface allows.
    TOO_MANY_RELATIONS = "QUERY_TOO_MANY_RELATIONS"
    #: ``*`` outside ``count(*)``. A query names the columns it wants.
    STAR_NOT_ALLOWED = "QUERY_STAR_NOT_ALLOWED"
    #: A name the surface keeps for itself. ``me`` is the reader, so nothing
    #: else may be called it and nowhere it means nothing may say it.
    RESERVED_NAME = "QUERY_RESERVED_NAME"
    #: ``me`` somewhere it says nothing: the reader is a person, so the only
    #: thing to compare them with is a field that holds one.
    VIEWER_NEEDS_A_PERSON = "QUERY_VIEWER_NEEDS_A_PERSON"

    # Execution.

    #: The planner's estimate for this statement is above what the surface
    #: runs. Nothing was executed.
    TOO_EXPENSIVE = "QUERY_TOO_EXPENSIVE"
    #: The statement ran longer than one query may.
    TIMED_OUT = "QUERY_TIMED_OUT"
    #: This guild already has as many queries running as it may.
    BUSY = "QUERY_BUSY"
    #: The database stopped the statement for reasons of its own — a read
    #: replica catching up with the primary — so the same statement may well
    #: run if asked again.
    INTERRUPTED = "QUERY_INTERRUPTED"
    #: The statement parsed and resolved, and the database refused it while
    #: running it — dividing by zero, a value that will not convert, a
    #: function called with types it does not take.
    EXECUTION_FAILED = "QUERY_EXECUTION_FAILED"


class NotificationMessages:
    NOT_FOUND = "NOTIFICATION_NOT_FOUND"
    #: This deployment does not send push notifications, so there is nothing
    #: for a device to register against.
    PUSH_DISABLED = "PUSH_NOTIFICATIONS_DISABLED"


class AnnouncementMessages:
    NOT_FOUND = "ANNOUNCEMENT_NOT_FOUND"
    IMAGE_NOT_FOUND = "ANNOUNCEMENT_IMAGE_NOT_FOUND"
    IMAGE_TOO_LARGE = "ANNOUNCEMENT_IMAGE_TOO_LARGE"


class CalendarMessages:
    # A guild calendar lives inside the calendar plug-in, which is what reaches it
    # and what its removal takes with it. Without the plug-in there is nowhere to
    # put one.
    GUILD_PLUGIN_REQUIRED = "CALENDAR_COMMUNITY_PLUGIN_REQUIRED"
    # An installed plug-in creates a calendar in an initiative; a guild calendar
    # is recorded on the calendar plug-in's install, which is the community's own
    # configuration.
    PLUGIN_INITIATIVE_REQUIRED = "CALENDAR_PLUGIN_INITIATIVE_REQUIRED"


class CalendarEventMessages:
    NOT_FOUND = "CALENDAR_EVENT_NOT_FOUND"
    ICAL_PARSE_FAILED = "ICAL_PARSE_FAILED"
    ICAL_NO_EVENTS = "ICAL_NO_EVENTS_FOUND"
    ENDS_BEFORE_START = "CALENDAR_EVENT_ENDS_BEFORE_START"
    # A repeat rule that can't be read, or asks for more than tasks and
    # events repeat by (``app.core.recurrence``).
    RECURRENCE_INVALID = "RECURRENCE_INVALID"
    # A change to one occurrence (or from one on) names which, by its start.
    OCCURRENCE_REQUIRED = "CALENDAR_EVENT_OCCURRENCE_REQUIRED"
    NOT_AN_OCCURRENCE = "CALENDAR_EVENT_NOT_AN_OCCURRENCE"
    # One occurrence stays in its series' calendar and repeats with it.
    OCCURRENCE_FOLLOWS_SERIES = "CALENDAR_EVENT_OCCURRENCE_FOLLOWS_SERIES"
    # An event cannot be moved across the guild/initiative line, because it
    # would take its initiative attachments with it.
    CANNOT_CROSS_SCOPE = "CALENDAR_EVENT_CANNOT_CROSS_SCOPE"
    # A calendar read's date window ends before it starts or spans too long.
    WINDOW_INVALID = "CALENDAR_WINDOW_INVALID"
    # A calendar read's window holds more repeating occurrences than one read
    # expands (``app.core.recurrence.MAX_EXPANDED``).
    WINDOW_TOO_FULL = "CALENDAR_WINDOW_TOO_FULL"
    # An answer to an event whose RSVP is closed, from someone not on its list.
    RSVP_CLOSED = "CALENDAR_EVENT_RSVP_CLOSED"


class DashboardMessages:
    # Definition / config validation (app.services.tenant.dashboard_definition).
    DEFINITION_INVALID = "DASHBOARD_DEFINITION_INVALID"
    DEFINITION_VERSION_UNSUPPORTED = "DASHBOARD_DEFINITION_VERSION_UNSUPPORTED"
    WIDGET_INVALID = "DASHBOARD_WIDGET_INVALID"
    WIDGET_TYPE_UNKNOWN = "DASHBOARD_WIDGET_TYPE_UNKNOWN"
    WIDGET_ID_DUPLICATE = "DASHBOARD_WIDGET_ID_DUPLICATE"
    WIDGET_OPTION_INVALID = "DASHBOARD_WIDGET_OPTION_INVALID"
    TOO_MANY_WIDGETS = "DASHBOARD_TOO_MANY_WIDGETS"
    BINDING_INVALID = "DASHBOARD_BINDING_INVALID"
    BINDING_SOURCE_UNKNOWN = "DASHBOARD_BINDING_SOURCE_UNKNOWN"
    BINDING_SOURCE_NOT_ALLOWED = "DASHBOARD_BINDING_SOURCE_NOT_ALLOWED"
    CONFIG_INVALID = "DASHBOARD_CONFIG_INVALID"
    BINDING_SQL_MISSING = "BINDING_SQL_MISSING"
    #: Setting a dashboard to run as its initiative without the role
    #: permission for it (managers always hold it).
    VIEW_MODE_NOT_ALLOWED = "DASHBOARD_VIEW_MODE_NOT_ALLOWED"
    #: Changing the widgets of a dashboard that runs as its initiative without
    #: that same permission.
    VIEW_MODE_EDIT_NOT_ALLOWED = "DASHBOARD_VIEW_MODE_EDIT_NOT_ALLOWED"
    BINDING_SQL_TOO_LONG = "BINDING_SQL_TOO_LONG"
    WIDGET_MAPPING_INVALID = "WIDGET_MAPPING_INVALID"


class PostMessages:
    #: Pinning lifts a notice above everyone else's, so it is initiative
    #: management authority rather than write access on the post.
    PIN_MANAGER_REQUIRED = "POST_PIN_MANAGER_REQUIRED"
    #: A pin whose expiry has already passed would be a no-op that reads as a
    #: pin — refused rather than silently ignored.
    PIN_EXPIRY_IN_PAST = "POST_PIN_EXPIRY_IN_PAST"
    #: More words than a notice is for. A board is read, not studied.
    BODY_TOO_LONG = "POST_BODY_TOO_LONG"
    #: A schedule was sent for a notice that is already up. Publication is not
    #: reversible — the people it was announced to have already been told.
    ALREADY_PUBLISHED = "POST_ALREADY_PUBLISHED"
    #: A poll was asked for on a notice that does not have one.
    POLL_NOT_FOUND = "POST_POLL_NOT_FOUND"
    #: The choices were rewritten after somebody had already answered. A ballot
    #: cast for one option must not become a ballot for whatever replaced it.
    POLL_HAS_VOTES = "POST_POLL_HAS_VOTES"
    #: Voting has stopped.
    POLL_CLOSED = "POST_POLL_CLOSED"
    #: A close time that has already passed would make a poll nobody can answer.
    POLL_CLOSES_IN_PAST = "POST_POLL_CLOSES_IN_PAST"
    #: More than one choice on a poll that takes one.
    POLL_SINGLE_CHOICE = "POST_POLL_SINGLE_CHOICE"
    #: A ballot named a choice that is not on this poll.
    POLL_OPTION_UNKNOWN = "POST_POLL_OPTION_UNKNOWN"
    #: The roster was asked for on an anonymous poll, which has none by design.
    POLL_IS_ANONYMOUS = "POST_POLL_IS_ANONYMOUS"
    #: Anonymity was switched off on a poll people had already answered
    #: anonymously. It can be turned on afterwards, never off.
    POLL_ANONYMITY_LOCKED = "POST_POLL_ANONYMITY_LOCKED"
    #: Multiple choice was switched off on a poll people had already answered
    #: with several. Like anonymity it can be turned on afterwards, never off —
    #: otherwise a single-choice poll would list one voter under two answers.
    POLL_MULTIPLE_LOCKED = "POST_POLL_MULTIPLE_LOCKED"
    #: Two choices that say the same thing are one choice wearing two labels.
    POLL_DUPLICATE_CHOICE = "POST_POLL_DUPLICATE_CHOICE"
    #: The roster was asked for while this poll's results are still withheld.
    POLL_RESULTS_HIDDEN = "POST_POLL_RESULTS_HIDDEN"
    #: A notice that is not up yet has nothing to answer.
    POLL_NOT_PUBLISHED = "POST_POLL_NOT_PUBLISHED"


class GalleryMessages:
    IMAGE_NOT_FOUND = "GALLERY_IMAGE_NOT_FOUND"
    #: The bytes are not a raster image this app can show — or are an SVG,
    #: which is a document rather than a picture.
    INVALID_IMAGE = "GALLERY_INVALID_IMAGE"
    IMAGE_TOO_LARGE = "GALLERY_IMAGE_TOO_LARGE"
    IMAGE_EMPTY = "GALLERY_IMAGE_EMPTY"
    VERSION_NOT_FOUND = "GALLERY_VERSION_NOT_FOUND"
    CANNOT_DELETE_LAST_VERSION = "GALLERY_CANNOT_DELETE_LAST_VERSION"
    VERSION_CONFLICT = "GALLERY_VERSION_CONFLICT"
    #: A cover has to be one of the gallery's own pictures.
    COVER_NOT_IN_GALLERY = "GALLERY_COVER_NOT_IN_GALLERY"


class WikiMessages:
    PAGE_NOT_FOUND = "WIKI_PAGE_NOT_FOUND"
    #: A page cannot be its own parent.
    PAGE_PARENT_ITSELF = "WIKI_PAGE_PARENT_ITSELF"
    #: Filing a page under one of its own descendants would detach the branch
    #: from the wiki.
    PAGE_PARENT_DESCENDANT = "WIKI_PAGE_PARENT_DESCENDANT"
    #: A home page has to be one of the wiki's own pages.
    HOME_NOT_IN_WIKI = "WIKI_HOME_NOT_IN_WIKI"
    #: So does the page new ones are copied from.
    TEMPLATE_NOT_IN_WIKI = "WIKI_TEMPLATE_NOT_IN_WIKI"
    #: A page with a live collaboration room has that room as the writer of
    #: its content; a save from outside the session is refused.
    LIVE_SESSION_OWNS_CONTENT = "WIKI_LIVE_SESSION_OWNS_CONTENT"
    #: A write named a version of the content that is no longer current.
    CONTENT_CHANGED = "WIKI_CONTENT_CHANGED"


class MarketplaceMessages:
    LISTING_NOT_FOUND = "MARKETPLACE_LISTING_NOT_FOUND"
    #: The listing exists but nothing about it can be installed here — withdrawn
    #: by its publisher, or its only versions need a newer app.
    LISTING_UNAVAILABLE = "MARKETPLACE_LISTING_UNAVAILABLE"
    LISTING_VERSION_INCOMPATIBLE = "MARKETPLACE_LISTING_VERSION_INCOMPATIBLE"
    #: The version needs a plug-in API contract (``min_plugin_api``) this
    #: deployment does not serve: a newer one, or another major version.
    LISTING_PLUGIN_API_INCOMPATIBLE = "MARKETPLACE_LISTING_PLUGIN_API_INCOMPATIBLE"
    #: A dashboard that ships with a plug-in, asked for by a guild that does not
    #: have that plug-in installed. Its tiles draw that plug-in's widgets, so there
    #: would be nothing behind any of them.
    LISTING_NEEDS_PLUGIN = "MARKETPLACE_LISTING_NEEDS_PLUGIN"
    #: An upgrade was asked for on a dashboard that was authored here, not
    #: installed — there is no listing to re-pin it to.
    NOT_INSTALLED_FROM_LISTING = "MARKETPLACE_NOT_INSTALLED_FROM_LISTING"
    ALREADY_LATEST_VERSION = "MARKETPLACE_ALREADY_LATEST_VERSION"
    #: An install asked to start from the listing's example, and this listing
    #: carries none: it installs only as itself.
    LISTING_HAS_NO_EXAMPLE = "MARKETPLACE_LISTING_HAS_NO_EXAMPLE"
    #: A share could not be made into a listing — the item has nothing a
    #: listing can carry, or its export is not one this build reads back.
    SHARE_INVALID = "MARKETPLACE_SHARE_INVALID"
    #: The item is larger than a listing may be. Sharing less of it works.
    SHARE_TOO_LARGE = "MARKETPLACE_SHARE_TOO_LARGE"
    #: A new version of a shared listing has to be the same tool as the first.
    SHARE_KIND_MISMATCH = "MARKETPLACE_SHARE_KIND_MISMATCH"
    #: Only somebody who belongs to the community shares its content; a grant
    #: into it does not reach the marketplace.
    SHARE_NOT_PERMITTED = "MARKETPLACE_SHARE_NOT_PERMITTED"
    #: A picture uploaded with a share that the marketplace will not keep:
    #: not a PNG, JPEG, GIF or WebP, larger than a listing's pictures may be,
    #: or one more than a listing takes.
    SHARE_IMAGE_INVALID = "MARKETPLACE_SHARE_IMAGE_INVALID"
    #: An uploaded listing file the catalogue would not publish. The response
    #: carries the validator's reason beside this code.
    LISTING_UPLOAD_INVALID = "MARKETPLACE_LISTING_UPLOAD_INVALID"
    MEDIA_NOT_FOUND = "MARKETPLACE_MEDIA_NOT_FOUND"
    #: A rescan was asked for on a deployment that publishes no catalog
    #: directory of its own — nothing to scan until one is configured.
    OPERATOR_CATALOG_NOT_CONFIGURED = "MARKETPLACE_OPERATOR_CATALOG_NOT_CONFIGURED"
    #: The directory is configured but not present — usually a volume that did
    #: not mount, or a path that differs from the one inside the container.
    OPERATOR_CATALOG_DIR_MISSING = "MARKETPLACE_OPERATOR_CATALOG_DIRECTORY_MISSING"
    #: One scan at a time: the answer a second one would give is the one
    #: already being computed.
    OPERATOR_CATALOG_SCAN_RUNNING = "MARKETPLACE_OPERATOR_CATALOG_SCAN_RUNNING"


class MarketplaceRegistryMessages:
    """Outcomes of a registry refresh or a bundle upload.

    Every code here either answers an operator's "refresh now" or upload, or is
    recorded as the last refusal so the status panel can say why the catalog
    did not move.
    """

    #: This build ships no trusted root yet, so there is no registry to follow.
    NOT_CONFIGURED = "MARKETPLACE_REGISTRY_NOT_CONFIGURED"
    #: The platform switch is off.
    DISABLED = "MARKETPLACE_REGISTRY_DISABLED"
    #: A refresh is already running; the second caller is told rather than
    #: queued, because both would be reading the same repository.
    REFRESH_IN_PROGRESS = "MARKETPLACE_REGISTRY_REFRESH_IN_PROGRESS"
    #: The trusted root file could not be read as TUF root metadata.
    ROOT_INVALID = "MARKETPLACE_REGISTRY_ROOT_INVALID"
    #: The repository's metadata could not be fetched.
    UNREACHABLE = "MARKETPLACE_REGISTRY_UNREACHABLE"
    #: The repository's metadata did not verify against the trusted root.
    METADATA_REJECTED = "MARKETPLACE_REGISTRY_METADATA_REJECTED"
    #: The repository's metadata verified but has expired.
    EXPIRED = "MARKETPLACE_REGISTRY_EXPIRED"
    #: An uploaded bundle is not a readable archive of a repository.
    BUNDLE_INVALID = "MARKETPLACE_REGISTRY_BUNDLE_INVALID"

    #: A file a listing names is not in the repository, could not be fetched,
    #: or does not match the metadata.
    TARGET_REJECTED = "MARKETPLACE_REGISTRY_TARGET_REJECTED"
    #: A listing entry is not in the expected format.
    ENTRY_INVALID = "MARKETPLACE_REGISTRY_ENTRY_INVALID"
    #: ``core.*`` names listings shipped in this repo and is never published
    #: by a registry.
    RESERVED_NAMESPACE = "MARKETPLACE_REGISTRY_RESERVED_NAMESPACE"
    #: The listing's uid or name is already published by another source here.
    SOURCE_CONFLICT = "MARKETPLACE_REGISTRY_SOURCE_CONFLICT"
    #: This deployment's operator added a publisher with the same prefix.
    PUBLISHER_CONFLICT = "MARKETPLACE_REGISTRY_PUBLISHER_CONFLICT"
    #: The listing itself was refused by the catalog's validator.
    LISTING_REJECTED = "MARKETPLACE_REGISTRY_LISTING_REJECTED"


class QueueMessages:
    ITEM_NOT_FOUND = "QUEUE_ITEM_NOT_FOUND"
    NO_ITEMS = "QUEUE_NO_ITEMS"
    NO_CURRENT_ITEM = "QUEUE_NO_CURRENT_ITEM"
    ITEM_NOT_HELD = "QUEUE_ITEM_NOT_HELD"


class CounterMessages:
    NOT_FOUND = "COUNTER_NOT_FOUND"
    VIEW_MODE_REQUIRES_BOUNDS = "COUNTER_VIEW_MODE_REQUIRES_BOUNDS"
    MIN_GREATER_THAN_MAX = "COUNTER_MIN_GREATER_THAN_MAX"
    STEP_MUST_BE_POSITIVE = "COUNTER_STEP_MUST_BE_POSITIVE"


class TrashMessages:
    NOT_FOUND = "TRASH_ITEM_NOT_FOUND"
    PURGE_REQUIRES_ADMIN = "TRASH_PURGE_REQUIRES_ADMIN"
    UNKNOWN_ENTITY_TYPE = "TRASH_UNKNOWN_ENTITY_TYPE"


class GuildPluginMessages:
    NOT_FOUND = "COMMUNITY_PLUGIN_NOT_FOUND"
    #: The listing named is not a plug-in, or names a plug-in kind this build cannot
    #: install.
    NOT_A_PLUGIN = "COMMUNITY_PLUGIN_LISTING_NOT_A_PLUGIN"
    #: This guild already has this listing installed. Plug-ins mount one guild-wide
    #: surface each, so a second copy has nothing to be.
    ALREADY_INSTALLED = "COMMUNITY_PLUGIN_ALREADY_INSTALLED"
    #: A valid plug-in of a kind this build does not mount into a guild yet — see
    #: GUILD_INSTALLABLE_PLUGIN_KINDS. Publishable and browsable, not installable
    #: here, and told so by name rather than half-mounted.
    KIND_NOT_INSTALLABLE = "COMMUNITY_PLUGIN_KIND_NOT_INSTALLABLE"

    # --- configuration ---
    #: The request named a connection the pinned definition does not declare.
    CONFIG_UNKNOWN_CONNECTION = "COMMUNITY_PLUGIN_CONFIG_UNKNOWN_CONNECTION"
    #: The request named a field that connection does not declare.
    CONFIG_UNKNOWN_FIELD = "COMMUNITY_PLUGIN_CONFIG_UNKNOWN_FIELD"
    #: A value that does not match its declared type, or an empty one.
    CONFIG_INVALID_VALUE = "COMMUNITY_PLUGIN_CONFIG_INVALID_VALUE"
    #: A value longer than this build stores for that field.
    CONFIG_VALUE_TOO_LONG = "COMMUNITY_PLUGIN_CONFIG_VALUE_TOO_LONG"
    #: A required field left without a value.
    CONFIG_REQUIRED_FIELD = "COMMUNITY_PLUGIN_CONFIG_REQUIRED_FIELD"
    #: A field the plug-in writes back itself when it completes a vendor flow; the
    #: settings form is not where it is set.
    CONFIG_MANAGED_FIELD = "COMMUNITY_PLUGIN_CONFIG_MANAGED_FIELD"

    # --- connections ---
    #: No such connection on this install, or no such member connection.
    CONNECTION_NOT_FOUND = "COMMUNITY_PLUGIN_CONNECTION_NOT_FOUND"
    #: Connecting runs a vendor's flow, and this connection declares none —
    #: its values are typed into the settings form instead. Named for the
    #: scope because that is what it meant when only one scope could have a
    #: flow; a guild-wide connection may now have one too.
    CONNECTION_NOT_INTERACTIVE = "COMMUNITY_PLUGIN_CONNECTION_NOT_INTERACTIVE"
    #: Guild-wide values are configured through the config endpoint; a
    #: per-member connection is not.
    CONNECTION_NOT_STATIC = "COMMUNITY_PLUGIN_CONNECTION_NOT_STATIC"
    #: A guild admin has stopped this member connecting this one.
    CONNECTION_BLOCKED = "COMMUNITY_PLUGIN_CONNECTION_BLOCKED"
    #: The plug-in is installed but turned off, so nothing flows through it.
    DISABLED = "COMMUNITY_PLUGIN_DISABLED"
    #: The connection's flow needs values this deployment's operator has not
    #: supplied for the plug-in's vendor client, or a field it names is empty.
    CONNECTION_VENDOR_NOT_CONFIGURED = (
        "COMMUNITY_PLUGIN_CONNECTION_VENDOR_NOT_CONFIGURED"
    )

    # --- acting as a member ---
    #: No request from this plug-in to act as the caller, by that id.
    CONSENT_NOT_FOUND = "COMMUNITY_PLUGIN_CONSENT_NOT_FOUND"
    #: The answer allows more than the plug-in asked for.
    CONSENT_EXCEEDS_REQUEST = "COMMUNITY_PLUGIN_CONSENT_EXCEEDS_REQUEST"

    # --- plug-ins the deployment provides ---
    #: The deployment installs this plug-in in every guild and a guild admin does
    #: not remove or disable it. The affordances are absent rather than
    #: erroring; this answers a request that arrives anyway.
    MANDATORY = "COMMUNITY_PLUGIN_MANDATORY"

    # --- service plug-ins ---
    #: This install's plug-in service is not wired up here — never registered, or
    #: the operator turned the registration off. Nothing this plug-in offers can be
    #: reached until that changes.
    SERVICE_NOT_REGISTERED = "COMMUNITY_PLUGIN_SERVICE_NOT_REGISTERED"
    #: The pinned definition declares no surface under that id.
    SURFACE_NOT_FOUND = "COMMUNITY_PLUGIN_SURFACE_NOT_FOUND"
    #: The surface is opened at the community level, or is marked
    #: ``admin_only``, and the caller is not a guild admin.
    SURFACE_ADMIN_ONLY = "COMMUNITY_PLUGIN_SURFACE_ADMIN_ONLY"
    #: The surface was opened in an initiative the plug-in is placed in, and the
    #: caller holds none of the roles that placement allows.
    SURFACE_ROLE_NOT_ALLOWED = "COMMUNITY_PLUGIN_SURFACE_ROLE_NOT_ALLOWED"
    #: The viewer is younger than the plug-in's minimum age where they are, or
    #: has no date of birth on file to say otherwise.
    AGE_RESTRICTED = "COMMUNITY_PLUGIN_AGE_RESTRICTED"
    #: The placement sent names an initiative that is not one of this guild's.
    PLACEMENT_INVALID = "COMMUNITY_PLUGIN_PLACEMENT_INVALID"
    #: The placement names a role that is not one of its initiative's.
    PLACEMENT_ROLE_INVALID = "COMMUNITY_PLUGIN_PLACEMENT_ROLE_INVALID"
    #: A scope granted to an install that its manifest does not request.
    SCOPE_NOT_REQUESTED = "COMMUNITY_PLUGIN_SCOPE_NOT_REQUESTED"
    #: A scope granted to an install beyond what this deployment allows the plug-in.
    SCOPE_ABOVE_CEILING = "COMMUNITY_PLUGIN_SCOPE_ABOVE_CEILING"
    #: A scope to use another plug-in, granted while that plug-in is not installed
    #: in the community.
    SCOPE_TARGET_NOT_INSTALLED = "COMMUNITY_PLUGIN_SCOPE_TARGET_NOT_INSTALLED"
    #: The version an upgrade would apply asks for more than the install holds,
    #: and the request carried no consent to it. The response names what it
    #: asks for.
    UPGRADE_NEEDS_CONSENT = "COMMUNITY_PLUGIN_UPGRADE_NEEDS_CONSENT"
    #: The consent or the decline names a version other than the one the
    #: catalog offers now.
    UPGRADE_VERSION_MOVED = "COMMUNITY_PLUGIN_UPGRADE_VERSION_MOVED"


class BundledChannelMessages:
    """Codes for calls a service this deployment ships makes to it.

    Machine-to-machine, read by that service's logs and retry logic rather than
    ``errors.json`` — the same reasoning :class:`BillingMessages` gives. No
    surface renders one to a person.
    """

    #: No bundled service is named, or its secret is unwired. The channel is
    #: inert on a deployment that ships none.
    NOT_CONFIGURED = "BUNDLED_NOT_CONFIGURED"
    #: The envelope arrived without both halves of its signature.
    MISSING_SIGNATURE = "BUNDLED_MISSING_SIGNATURE"
    #: Outside the clock window, or not a timestamp at all.
    STALE_TIMESTAMP = "BUNDLED_STALE_TIMESTAMP"
    #: The signature is not one this deployment's secret produces.
    BAD_SIGNATURE = "BUNDLED_BAD_SIGNATURE"
    #: The reference names no guild, or names one through an install that is
    #: not the caller's own.
    UNKNOWN_GUILD = "BUNDLED_UNKNOWN_COMMUNITY"
    #: No reference has been minted for that guild in the sector asked about.
    NO_SUCH_NAME = "BUNDLED_NO_SUCH_NAME"
    #: The signed body is not the shape this route takes.
    INVALID_PAYLOAD = "BUNDLED_INVALID_PAYLOAD"
    #: That sector names something inside a guild, so it is not one a caller
    #: holding only a guild reference can ask for.
    SECTOR_NOT_ANSWERABLE = "BUNDLED_SECTOR_NOT_ANSWERABLE"


class PluginServiceMessages:
    """Codes for the deployment-level plug-in service registry.

    Read by an operator wiring a plug-in up, so each code names the step that
    refused rather than a generic failure.
    """

    NOT_FOUND = "PLUGIN_SERVICE_NOT_FOUND"
    #: Another registration already carries this public_id.
    DUPLICATE_PUBLIC_ID = "PLUGIN_SERVICE_DUPLICATE_PUBLIC_ID"
    #: public_id, base_url, an origin, or a version string this build refuses.
    INVALID_PUBLIC_ID = "PLUGIN_SERVICE_INVALID_PUBLIC_ID"
    INVALID_BASE_URL = "PLUGIN_SERVICE_INVALID_BASE_URL"
    #: The browser-facing base, when a plug-in answers there rather than at the
    #: address Initiative's own server calls.
    INVALID_PAGE_ORIGIN = "PLUGIN_SERVICE_INVALID_PAGE_ORIGIN"
    INVALID_ORIGIN = "PLUGIN_SERVICE_INVALID_ORIGIN"
    #: The key set is not a JWKS this build can verify against, or an entry in
    #: it carries no ``kid`` for a JWT to name.
    INVALID_JWKS = "PLUGIN_SERVICE_INVALID_JWKS"
    #: The PLUGIN_PLATFORM_* signing keypair is not configured. It is required and
    #: has no fallback, so registration fails closed until an operator
    #: supplies one.
    SIGNING_NOT_CONFIGURED = "PLUGIN_SERVICE_SIGNING_NOT_CONFIGURED"
    #: A registration entry or request named something only the plug-in's
    #: listing states (its listing, scope ceiling, image or sectors).
    STATED_BY_LISTING = "PLUGIN_SERVICE_STATED_BY_LISTING"
    #: The key set address is not https on the base URL's own origin.
    INVALID_JWKS_URI = "PLUGIN_SERVICE_INVALID_JWKS_URI"
    #: Connect reads the key set from the base URL, and there is none yet.
    CONNECT_NEEDS_BASE_URL = "PLUGIN_SERVICE_CONNECT_NEEDS_BASE_URL"
    #: The plug-in's base URL did not answer with a key set document.
    KEYS_UNREADABLE = "PLUGIN_SERVICE_KEYS_UNREADABLE"
    #: The key set the plug-in serves is not the one the operator confirmed.
    KEYS_CHANGED = "PLUGIN_SERVICE_KEYS_CHANGED"
    #: No publisher has that id.
    PUBLISHER_NOT_FOUND = "PLUGIN_PUBLISHER_NOT_FOUND"
    #: Another publisher already has that prefix.
    DUPLICATE_PUBLISHER = "PLUGIN_PUBLISHER_DUPLICATE_PREFIX"
    #: A publisher prefix this build refuses.
    INVALID_PUBLISHER_PREFIX = "PLUGIN_PUBLISHER_INVALID_PREFIX"
    #: A publisher's name is empty or too long.
    INVALID_PUBLISHER_NAME = "PLUGIN_PUBLISHER_INVALID_NAME"
    #: The registration's plug-in facts come from the registry, whose next refresh
    #: would bring it back, so it is switched off rather than removed.
    REGISTRY_MANAGED = "PLUGIN_SERVICE_REGISTRY_MANAGED"
    #: An address, origin or key given for a declarative plug-in, whose calls
    #: Initiative makes itself.
    DECLARATIVE_NOT_PLACED = "PLUGIN_SERVICE_DECLARATIVE_NOT_PLACED"
    #: A vendor value named a field the plug-in's manifest does not declare.
    UNKNOWN_VENDOR_FIELD = "PLUGIN_SERVICE_UNKNOWN_VENDOR_FIELD"
    #: A vendor value that is too long, or not the address its field asks for.
    INVALID_VENDOR_VALUE = "PLUGIN_SERVICE_INVALID_VENDOR_VALUE"
    #: The plug-in's listing declares no vendor setup flow this build runs.
    VENDOR_SETUP_UNAVAILABLE = "PLUGIN_SERVICE_VENDOR_SETUP_UNAVAILABLE"
    #: The organization named for the vendor's setup is not one it could have.
    VENDOR_SETUP_INVALID_ORGANIZATION = (
        "PLUGIN_SERVICE_VENDOR_SETUP_INVALID_ORGANIZATION"
    )
    #: The setup returning from the vendor is not one this person started for
    #: this plug-in in the last hour, or it was already finished.
    VENDOR_SETUP_EXPIRED = "PLUGIN_SERVICE_VENDOR_SETUP_EXPIRED"
    #: The vendor did not answer the setup's code with the new client's values.
    VENDOR_SETUP_FAILED = "PLUGIN_SERVICE_VENDOR_SETUP_FAILED"


class PluginMessages:
    """Codes for an installed plug-in calling a route with its access token."""

    #: The route names a scope the token does not carry.
    SCOPE_REQUIRED = "PLUGIN_SCOPE_REQUIRED"
    #: The request names a person or a community by something that is not one
    #: of this install's references.
    REFERENCE_UNKNOWN = "PLUGIN_REFERENCE_UNKNOWN"
    #: A consent request names an initiative the install is not placed in.
    CONSENT_INITIATIVE_NOT_PLACED = "PLUGIN_CONSENT_INITIATIVE_NOT_PLACED"
    #: A token narrowed to one initiative asks for consent beyond it.
    CONSENT_OUTSIDE_TOKEN = "PLUGIN_CONSENT_OUTSIDE_TOKEN"
    #: A consent request names an initiative the member is not in.
    CONSENT_MEMBER_NOT_IN_INITIATIVE = "PLUGIN_CONSENT_MEMBER_NOT_IN_INITIATIVE"
    #: The install has asked for consent too often; it tries again later.
    CONSENT_RATE_LIMITED = "PLUGIN_CONSENT_RATE_LIMITED"
    #: The request asks an installed plug-in to change sharing without
    #: ``sharing:write``, or to name an owner for something it creates, which
    #: is its own.
    SHARING_NOT_AVAILABLE = "PLUGIN_SHARING_NOT_AVAILABLE"


class PluginHubMessages:
    """Codes for an installed plug-in calling another plug-in through Initiative.

    OAuth-style, so a caller reads them the way it reads the token endpoint's
    errors: each names the check that refused.
    """

    #: The caller's token, grant or pinned version does not hold
    #: ``plugins:<target>``, or a member's consent allows reading only and the
    #: endpoint writes.
    INSUFFICIENT_SCOPE = "insufficient_scope"
    #: The plug-in called is not installed, switched on and live in this community.
    TARGET_NOT_INSTALLED = "target_not_installed"
    #: The endpoint is not part of the plug-in's public surface.
    ENDPOINT_NOT_PUBLIC = "endpoint_not_public"
    #: The endpoint does not take calls for this actor.
    ACTOR_NOT_SUPPORTED = "actor_not_supported"
    #: The caller is confined to an initiative the plug-in called is not placed in.
    TARGET_NOT_PLACED = "target_not_placed"


class PluginDataMessages:
    """Codes for the widget data proxy.

    Read by a member looking at a dashboard, so each one distinguishes a state
    they can act on (connect an account, ask an admin to configure the plug-in) from
    one they can only wait out (the plug-in is unreachable).
    """

    #: The install names no such data source, or the pinned definition is not a
    #: service plug-in's at all.
    ENDPOINT_NOT_FOUND = "PLUGIN_DATA_ENDPOINT_NOT_FOUND"
    #: The endpoint is marked ``admin_only`` and the caller is not a guild admin.
    ADMIN_ONLY = "PLUGIN_DATA_ADMIN_ONLY"
    #: The source declares no such parameter, so there is nothing to fill in.
    PARAM_NOT_FOUND = "PLUGIN_DATA_PARAM_NOT_FOUND"
    #: The install is turned off in this guild.
    PLUGIN_DISABLED = "PLUGIN_DATA_PLUGIN_DISABLED"
    #: No registration wires this plug-in up on this deployment.
    SERVICE_NOT_REGISTERED = "PLUGIN_DATA_SERVICE_NOT_REGISTERED"
    #: The operator's kill switch is off, or the registration has not verified.
    SERVICE_DISABLED = "PLUGIN_DATA_SERVICE_DISABLED"
    #: A parameter the source does not declare, or a value that does not match
    #: its declared type.
    INVALID_PARAMS = "PLUGIN_DATA_INVALID_PARAMS"
    #: A guild-scoped credential this source needs has not been supplied.
    NEEDS_CONFIGURATION = "PLUGIN_DATA_NEEDS_CONFIGURATION"
    #: The source reads the member's own vendor account and they have not
    #: connected it yet.
    CONNECTION_REQUIRED = "PLUGIN_DATA_CONNECTION_REQUIRED"
    #: The plug-in could not be reached, timed out, or answered with something that
    #: is not a data response.
    SERVICE_UNAVAILABLE = "PLUGIN_SERVICE_UNAVAILABLE"
    #: The plug-in answered past the response ceiling.
    RESPONSE_TOO_LARGE = "PLUGIN_DATA_RESPONSE_TOO_LARGE"
    #: This worker already has as many calls in flight to this plug-in as it will
    #: hold open, so one slow plug-in cannot consume the pool.
    BUSY = "PLUGIN_DATA_BUSY"
    #: Too many calls in a short window: a member's actions, or one plug-in's
    #: calls to others.
    RATE_LIMITED = "PLUGIN_DATA_RATE_LIMITED"
    #: The install's pinned version declares no such action on this kind of
    #: item.
    ACTION_NOT_FOUND = "PLUGIN_ACTION_NOT_FOUND"
    #: The action is not offered on this item for this reader: the install is
    #: not placed in its initiative with a role they hold, or the plug-in
    #: cannot read the item.
    ACTION_NOT_OFFERED = "PLUGIN_ACTION_NOT_OFFERED"


class PluginChannelMessages:
    """Codes for an installed plug-in's calls about its own installation.

    Read by a plug-in author rather than by a person in the UI, so each names the
    step that refused: an install this caller does not own, or a payload
    outside what the pinned manifest declared.
    """

    # --- the install being addressed ---
    #: No install of this plug-in in that guild — never installed, uninstalled, or
    #: the guild is not one this caller may see.
    INSTALL_NOT_FOUND = "PLUGIN_CHANNEL_INSTALL_NOT_FOUND"
    #: The install exists but the guild turned it off.
    INSTALL_DISABLED = "PLUGIN_CHANNEL_INSTALL_DISABLED"
    #: The guild is frozen, so this channel accepts no writes into it.
    GUILD_READ_ONLY = "PLUGIN_CHANNEL_COMMUNITY_READ_ONLY"
    #: No connection on this install answers to that reference.
    CONNECTION_NOT_FOUND = "PLUGIN_CHANNEL_CONNECTION_NOT_FOUND"
    #: A guild admin stopped this member's connection; the plug-in may not revive it.
    CONNECTION_BLOCKED = "PLUGIN_CHANNEL_CONNECTION_BLOCKED"
    #: The member's connection could not be refreshed and has to be made again.
    CONNECTION_EXPIRED = "PLUGIN_CHANNEL_CONNECTION_EXPIRED"
    #: The connection holds no token: never completed, or one whose flow keeps
    #: none and declares no token of its own.
    CONNECTION_NO_TOKEN = "PLUGIN_CHANNEL_CONNECTION_NO_TOKEN"
    #: The vendor did not answer with a token.
    TOKEN_UNAVAILABLE = "PLUGIN_CHANNEL_TOKEN_UNAVAILABLE"

    # --- what the plug-in sent ---
    #: The body is not the JSON object this channel expects.
    INVALID_PAYLOAD = "PLUGIN_CHANNEL_INVALID_PAYLOAD"
    #: An event type the pinned definition does not declare, or one namespaced
    #: under a plug-in other than the caller.
    UNKNOWN_EVENT_TYPE = "PLUGIN_CHANNEL_UNKNOWN_EVENT_TYPE"
    #: The event body is larger than this build will carry.
    EVENT_TOO_LARGE = "PLUGIN_CHANNEL_EVENT_TOO_LARGE"
    #: The event names an initiative the install is not placed in, or one
    #: other than the initiative its token is narrowed to.
    INITIATIVE_NOT_PLACED = "PLUGIN_CHANNEL_INITIATIVE_NOT_PLACED"
    #: A config state outside what a plug-in may report.
    INVALID_CONFIG_STATE = "PLUGIN_CHANNEL_INVALID_CONFIG_STATE"

    # --- metadata ---
    #: A metadata key that is not a lowercase letter followed by lowercase
    #: letters, digits, ``_`` and ``.``, or is longer than the cap.
    METADATA_KEY_INVALID = "PLUGIN_CHANNEL_METADATA_KEY_INVALID"
    #: One value is larger, as JSON, than a value may be.
    METADATA_VALUE_TOO_LARGE = "PLUGIN_CHANNEL_METADATA_VALUE_TOO_LARGE"
    #: The write would leave more keys, or more bytes, on the item or the
    #: install than it may hold.
    METADATA_LIMIT_REACHED = "PLUGIN_CHANNEL_METADATA_LIMIT_REACHED"
    #: No item of that kind and id that the install can read.
    METADATA_ITEM_NOT_FOUND = "PLUGIN_CHANNEL_METADATA_ITEM_NOT_FOUND"


class WebhookSubscriptionMessages:
    INVALID_TARGET_URL = "WEBHOOK_INVALID_TARGET_URL"
    PRIVATE_TARGET_URL = "WEBHOOK_PRIVATE_TARGET_URL"
    NOT_FOUND = "WEBHOOK_SUBSCRIPTION_NOT_FOUND"
    UNKNOWN_EVENT_TYPE = "WEBHOOK_UNKNOWN_EVENT_TYPE"
    UNKNOWN_FIELD = "WEBHOOK_UNKNOWN_FIELD"


class AIMessages:
    INVALID_BASE_URL = "AI_INVALID_BASE_URL"
    CONNECTION_NOT_FOUND = "AI_CONNECTION_NOT_FOUND"
    MEMBER_KEYS_DISABLED = "AI_MEMBER_KEYS_DISABLED"
    INVALID_API_KEY = "AI_INVALID_API_KEY"
    NOT_ENABLED = "AI_NOT_ENABLED"
    #: No provider is chosen, or the chosen one needs a key and has none.
    NOT_CONFIGURED = "AI_NOT_CONFIGURED"
    #: The provider could not be reached or did not answer in time.
    PROVIDER_UNAVAILABLE = "AI_PROVIDER_UNAVAILABLE"
    #: The provider answered with an error or a reply that could not be read.
    PROVIDER_ERROR = "AI_PROVIDER_ERROR"
    DOCUMENT_EMPTY = "AI_DOCUMENT_EMPTY"
    #: The connection names a model its provider does not list.
    MODEL_NOT_FOUND = "AI_MODEL_NOT_FOUND"


class NativeMessages:
    OTA_BUNDLE_NOT_AVAILABLE = "NATIVE_OTA_BUNDLE_NOT_AVAILABLE"
    #: The native app's sign-in is from before the code flow, and its grace has run out.
    APP_UPDATE_REQUIRED = "NATIVE_APP_UPDATE_REQUIRED"


class LegalMessages:
    """Codes for the hosted deployment's terms and privacy policy."""

    #: This deployment has no billing portal, so it has no terms of its own.
    NOT_CONFIGURED = "LEGAL_NOT_CONFIGURED"
    #: The portal that holds the documents could not be reached.
    PORTAL_UNAVAILABLE = "LEGAL_PORTAL_UNAVAILABLE"
    DOCUMENT_NOT_FOUND = "LEGAL_DOCUMENT_NOT_FOUND"


class BillingMessages:
    """Codes for the service-to-service billing write boundary.

    These endpoints are machine-to-machine (the billing service, not the
    SPA), so the codes are consumed by the caller's logs/retry logic rather
    than errors.json.
    """

    NOT_CONFIGURED = "BILLING_NOT_CONFIGURED"
    #: The configured verifying key could not be read. A deployment fault
    #: rather than a caller fault, so it answers alongside NOT_CONFIGURED.
    KEY_UNREADABLE = "BILLING_KEY_UNREADABLE"
    MISSING_SIGNATURE = "BILLING_MISSING_SIGNATURE"
    STALE_TIMESTAMP = "BILLING_STALE_TIMESTAMP"
    INVALID_SIGNATURE = "BILLING_INVALID_SIGNATURE"
    INVALID_TOKEN = "BILLING_INVALID_TOKEN"
    REPLAYED_TOKEN = "BILLING_REPLAYED_TOKEN"
    INVALID_PAYLOAD = "BILLING_INVALID_PAYLOAD"
    COMMUNITY_NOT_FOUND = "BILLING_COMMUNITY_NOT_FOUND"
    SUPPORT_SOURCE_RESTRICTED = "BILLING_SUPPORT_SOURCE_RESTRICTED"
    SUPPORT_CANNOT_LOWER = "BILLING_SUPPORT_CANNOT_LOWER"
    OPERATOR_CANNOT_LOWER_CEILING = "BILLING_OPERATOR_CANNOT_LOWER_CEILING"
    ACTOR_REQUIRED = "BILLING_ACTOR_REQUIRED"
    STATUS_NOT_SETTABLE = "BILLING_STATUS_NOT_SETTABLE"
    #: A community notice from a source that does not send one.
    NOTICE_SOURCE_NOT_ALLOWED = "BILLING_NOTICE_SOURCE_NOT_ALLOWED"
    #: The notice could not be written down. Nothing was recorded, so the same
    #: event id may be sent again.
    NOTICE_NOT_DELIVERED = "BILLING_NOTICE_NOT_DELIVERED"
    PORTAL_NOT_CONFIGURED = "BILLING_PORTAL_NOT_CONFIGURED"
    PORTAL_SIGNING_NOT_CONFIGURED = "BILLING_PORTAL_SIGNING_NOT_CONFIGURED"
    PORTAL_GRANT_UNAVAILABLE = "BILLING_PORTAL_GRANT_UNAVAILABLE"


class DirectMessageMessages:
    """Who may ask to message an account, and who it will not hear from."""

    #: No account with that id that this reader may be shown. Suspended,
    #: anonymized and ignored accounts all answer the same way.
    USER_NOT_FOUND = "DM_USER_NOT_FOUND"
    #: An account that has not answered the age question cannot raise its
    #: policy above ``private``, and cannot be reached at all.
    AGE_CONFIRMATION_REQUIRED = "DM_AGE_CONFIRMATION_REQUIRED"
    CANNOT_IGNORE_SELF = "DM_CANNOT_IGNORE_SELF"
    #: A community named in a toggle write that this account is not in.
    NOT_A_MEMBER = "DM_NOT_A_MEMBER"
    #: This deployment does not offer direct messages. A platform owner's
    #: setting, so it is the same answer for everybody and nothing the caller
    #: can do about it.
    DISABLED_FOR_PLATFORM = "DM_DISABLED_FOR_PLATFORM"


class DirectMessageTransportMessages:
    """Devices, keys, conversations and the queue."""

    #: A device id that names nothing the caller owns.
    DEVICE_NOT_FOUND = "DM_DEVICE_NOT_FOUND"
    #: A key or payload that is not valid base64, or is the wrong length for the
    #: curve it claims to be on.
    MALFORMED_KEY = "DM_MALFORMED_KEY"
    #: Two prekeys published under one name.
    DUPLICATE_KEY_ID = "DM_DUPLICATE_KEY_ID"
    #: A top-up that would take the device past what it may publish.
    TOO_MANY_KEYS = "DM_TOO_MANY_KEYS"
    #: The pair cannot open a channel right now. One code for every refusal,
    #: the same way the permission layer answers.
    NOT_REACHABLE = "DM_NOT_REACHABLE"
    CANNOT_MESSAGE_SELF = "DM_CANNOT_MESSAGE_SELF"
    CONVERSATION_NOT_FOUND = "DM_CONVERSATION_NOT_FOUND"
    #: One message past the size a message may be. Anything larger is an
    #: attachment, which travels out of band.
    MESSAGE_TOO_LARGE = "DM_MESSAGE_TOO_LARGE"
    #: The recipient is holding more undelivered ciphertext than they may.
    #: Refused at the door rather than accepted and dropped later.
    RECIPIENT_QUEUE_FULL = "DM_RECIPIENT_QUEUE_FULL"
    #: Somebody on the proposed roster cannot reach somebody else on it. Which
    #: pair is answered by the roster check, not by this refusal.
    ROSTER_NOT_REACHABLE = "DM_ROSTER_NOT_REACHABLE"
    #: More accounts than one conversation may carry.
    ROSTER_TOO_LARGE = "DM_ROSTER_TOO_LARGE"
    #: Fewer than three, which is a pair and has its own way in.
    ROSTER_TOO_SMALL = "DM_ROSTER_TOO_SMALL"
    #: Answering an invitation that is not there, or is already answered.
    NO_INVITATION = "DM_NO_INVITATION"
    #: A device's or key's signature is missing where one is required, or does
    #: not verify against the device's own fingerprint key.
    INVALID_SIGNATURE = "DM_INVALID_SIGNATURE"
    #: A verification addressed from a device to itself.
    VERIFY_SAME_DEVICE = "DM_VERIFY_SAME_DEVICE"
    #: The account already has as many verification messages waiting as it may.
    TOO_MANY_VERIFICATIONS = "DM_TOO_MANY_VERIFICATIONS"


class ContactGrantMessages:
    """Connections and message requests."""

    #: The pair cannot reach each other right now: a policy that does not admit
    #: them, an account that is not active, or an age question unanswered. One
    #: code for every refusal.
    CANNOT_REACH = "CONTACT_GRANT_CANNOT_REACH"
    #: Accepting something nobody asked for, or accepting your own request.
    NO_REQUEST = "CONTACT_GRANT_NO_REQUEST"
    CANNOT_GRANT_SELF = "CONTACT_GRANT_CANNOT_GRANT_SELF"


class DemoMessages:
    """The demo deployment's links, copies and pitches."""

    #: The link is unknown, revoked, expired or used up, or its pitch has
    #: nothing published.
    DEMO_LINK_NOT_FOUND = "DEMO_LINK_NOT_FOUND"
    #: No demo space is free right now.
    DEMO_BUSY = "DEMO_BUSY"
    #: The account was not made for a demo copy, or its copy is gone.
    DEMO_COPY_NOT_FOUND = "DEMO_COPY_NOT_FOUND"
    #: The community is not a pitch, or the reference names none.
    DEMO_PITCH_NOT_FOUND = "DEMO_PITCH_NOT_FOUND"
    #: Publishing a pitch is for its admins.
    DEMO_PITCH_ADMIN_REQUIRED = "DEMO_PITCH_ADMIN_REQUIRED"
    #: The pitch's bundle can't be imported, or an editor it names has no
    #: account.
    DEMO_PITCH_SOURCE_INVALID = "DEMO_PITCH_SOURCE_INVALID"
    #: The platform holds content in the pitch, so it stays until released.
    DEMO_PITCH_HELD = "DEMO_PITCH_HELD"
    #: A persona's handle belongs to an account that is not a persona.
    DEMO_PERSONA_TAKEN = "DEMO_PERSONA_TAKEN"
    #: A link's end is in the past.
    DEMO_LINK_EXPIRY_INVALID = "DEMO_LINK_EXPIRY_INVALID"


class ContactMessages:
    """My Contacts — the starred list on the personal page."""

    CANNOT_FAVORITE_SELF = "CONTACT_CANNOT_FAVORITE_SELF"
