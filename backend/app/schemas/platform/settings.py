import json
from typing import Annotated, List, Literal, Optional

from pydantic import AliasChoices, ConfigDict, EmailStr, Field, field_validator

from app.core.config import CaptchaProvider, StorageBackendKind
from app.core.login_methods import LoginMethod, SecondFactorRequirement
from app.core.user_input_validators import validate_provider_slug
from app.core.rules import (
    MAX_GUILD_RETENTION_DAYS,
    MIN_GUILD_RETENTION_DAYS,
)
from app.models.platform.user_dm_settings import DmPolicy
from app.schemas.base import RawTextStr, SanitizedBaseModel, reject_null


class AuthProviderOwnerRead(SanitizedBaseModel):
    """One registry provider as the owner's settings read it — never the secret."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: int
    slug: str
    display_name: str
    kind: str
    enabled: bool
    issuer: Optional[str] = None
    client_id: Optional[str] = None
    scopes: Optional[str] = None
    role_claim_path: Optional[str] = None
    allow_jit: bool
    #: Whether this provider's own account of a sign-in may answer a
    #: request for a second factor.
    asserts_second_factor: bool = False
    #: Whether communities may connect to this provider. Off keeps one
    #: registered for a single customer out of everybody else's picker.
    icon: Optional[str] = None
    button_style: Optional[str] = None
    # Whether a client secret is stored (write-only; its value is never read
    # back on any request path).
    secret_set: bool = False
    #: Where this provider sends the browser back. Shown so an operator can
    #: register it with their IdP; it remains fixed for the provider's lifetime
    #: because the slug is immutable.
    callback_url: str = ""


def _validate_https_issuer(value: str) -> str:
    """https-only, matching discovery's rule — surfaced at write time instead
    of as a stray error mid-login."""
    if not value.startswith("https://") or len(value) <= len("https://"):
        raise ValueError("issuer must be an https:// URL")
    return value


class AuthProviderCreate(SanitizedBaseModel):
    """A new operator-global login provider. Complete rows only — the login
    flow refuses config-incomplete providers, so the CRUD does too."""

    slug: str = Field(max_length=64)
    display_name: str = Field(min_length=1, max_length=128)
    kind: Literal["oidc"] = "oidc"
    enabled: bool = True
    issuer: str
    client_id: str = Field(min_length=1)
    client_secret: Optional[RawTextStr] = None  # None = public / PKCE-only
    scopes: Optional[str] = Field(default="openid email profile", max_length=512)
    role_claim_path: Optional[str] = Field(default=None, max_length=256)
    allow_jit: bool = True
    asserts_second_factor: bool = False
    icon: Optional[str] = Field(default=None, max_length=64)
    button_style: Optional[str] = Field(default=None, max_length=64)

    @field_validator("slug")
    @classmethod
    def _slug_shape(cls, value: str) -> str:
        return validate_provider_slug(value)

    @field_validator("issuer")
    @classmethod
    def _issuer_https(cls, value: str) -> str:
        return _validate_https_issuer(value)


class AuthProviderUpdate(SanitizedBaseModel):
    """Partial update. ``client_secret``: absent = keep, empty = clear,
    value = replace. The slug is immutable — it is the identity the login
    URLs, flow states, and linked identities hang off."""

    display_name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    enabled: Optional[bool] = None
    issuer: Optional[str] = None
    client_id: Optional[str] = Field(default=None, min_length=1)
    client_secret: Optional[RawTextStr] = None
    scopes: Optional[str] = Field(default=None, max_length=512)
    role_claim_path: Optional[str] = Field(default=None, max_length=256)
    allow_jit: Optional[bool] = None
    asserts_second_factor: Optional[bool] = None
    icon: Optional[str] = Field(default=None, max_length=64)
    button_style: Optional[str] = Field(default=None, max_length=64)

    # An explicit null would strip config a login-ready row requires (the login
    # flow refuses config-incomplete providers).
    _required = reject_null(
        "display_name",
        "issuer",
        "client_id",
        "enabled",
        "allow_jit",
        "asserts_second_factor",
    )

    @field_validator("issuer")
    @classmethod
    def _issuer_https(cls, value: Optional[str]) -> Optional[str]:
        return _validate_https_issuer(value) if value is not None else value


class AuthProviderDiscoverRequest(SanitizedBaseModel):
    """An address to look up before anything is saved."""

    issuer: str

    @field_validator("issuer")
    @classmethod
    def _issuer_https(cls, value: str) -> str:
        return _validate_https_issuer(value)


class AuthProviderProbeResult(SanitizedBaseModel):
    """What one look at a provider found.

    Named fields only. The document itself and the status that carried it stay
    server-side; ``error_code`` is what a failure says, and the detail behind
    it is in the log.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    ok: bool
    error_code: Optional[str] = None
    #: Trimmed of a pasted ``.well-known`` suffix, so the form can correct
    #: what somebody copied.
    issuer: Optional[str] = None
    authorization_endpoint: Optional[str] = None
    token_endpoint: Optional[str] = None
    jwks_uri: Optional[str] = None
    userinfo_endpoint: Optional[str] = None
    signing_algs: List[str] = Field(default_factory=list)
    #: What the provider says it offers. Advisory — these fill in the scopes
    #: and groups-claim fields, and no login decision reads them.
    scopes_supported: List[str] = Field(default_factory=list)
    claims_supported: List[str] = Field(default_factory=list)
    #: Where a provider in this namespace sends the browser back, with
    #: ``{slug}`` still to fill in. Computed here rather than guessed by the
    #: caller: it is built from the deployment's own ``APP_URL``, which is what
    #: the finished provider's callback is built from too, and the address has
    #: to match exactly at the far end. Returned by the look-up because that is
    #: when somebody is about to need it.
    callback_url_template: str = ""


class ConnectableProviderRead(SanitizedBaseModel):
    """One provider a community may connect to, as the community sees it.

    Deliberately less than the operator's view: a community picks a provider by
    name. It holds no issuer and no client id, so it is shown neither — which
    also keeps one customer's identity provider out of another's list.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: int
    display_name: str
    icon: Optional[str] = None
    #: False where the operator has switched it off or left it half
    #: configured — said here so a community is not offered a button that
    #: cannot work.
    login_ready: bool = True


#: One value a narrowing counts, bounded to what the column holds so an
#: over-long one is answered with a validation error rather than a database
#: one. The list is bounded too: a narrowing names a tenant, not a directory.
ClaimValue = Annotated[str, Field(max_length=256)]
MAX_CLAIM_VALUES = 64


class CommunityProviderConnectionRead(SanitizedBaseModel):
    """One community signing its members in through one provider.

    Also how an arrangement the community has not made itself is shown: the
    deployment's default for that provider, marked ``inherited``, which the
    community replaces by connecting to the provider itself.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    #: Null on an inherited arrangement — there is no row of this community's
    #: to edit until it makes one.
    id: Optional[int] = None
    #: Whether this is the deployment's answer rather than the community's.
    inherited: bool = False
    provider_id: int
    provider_slug: str
    provider_display_name: str
    provider_icon: Optional[str] = None
    #: Which verified claim decides whether somebody belongs here — ``hd`` for
    #: a Google Workspace domain, ``tid`` for an Entra tenant. Null with an
    #: empty ``claim_values`` is unnarrowed, which is right where the provider
    #: is already the community's own.
    claim: Optional[str] = None
    claim_values: List[str] = Field(default_factory=list)
    enabled: bool
    #: Whether somebody this connection counts as theirs joins on arrival.
    auto_join: bool = False
    #: Whether somebody outside the community has agreed these values are its
    #: to claim. ``auto_join`` waits for it; admitting people the community
    #: already has does not. Changing the values asks again.
    narrowing_approved: bool = False
    #: Whether the platform's rules for this provider may place people here.
    accepts_provider_placement: bool = False
    login_ready: bool = True


class CommunityNarrowingAgreement(SanitizedBaseModel):
    """Whether these values are this community's to claim."""

    agreed: bool


class CommunityNarrowingPending(SanitizedBaseModel):
    """One community's claim, waiting to be answered."""

    connection_id: int
    community_id: int = Field(validation_alias=AliasChoices("community_id", "guild_id"))
    community_name: str = Field(
        validation_alias=AliasChoices("community_name", "guild_name")
    )
    provider_display_name: str
    claim: str
    claim_values: List[str]
    auto_join: bool
    agreed: bool


class CommunityProviderConnectionCreate(SanitizedBaseModel):
    """Connect to one of the providers on offer."""

    provider_id: int
    claim: Optional[str] = Field(default=None, max_length=64)
    claim_values: Optional[List[ClaimValue]] = Field(
        default=None, max_length=MAX_CLAIM_VALUES
    )
    enabled: bool = True
    #: Whether somebody this connection counts as theirs joins on arrival.
    auto_join: bool = False
    #: Whether the platform's rules for this provider may place people here.
    accepts_provider_placement: bool = False


class CommunityProviderConnectionUpdate(SanitizedBaseModel):
    """Change the narrowing, or take the button away. The provider a
    connection is to is not editable: pointing it elsewhere would change who
    gets in without saying so. Disconnect and connect instead."""

    claim: Optional[str] = Field(default=None, max_length=64)
    claim_values: Optional[List[ClaimValue]] = Field(
        default=None, max_length=MAX_CLAIM_VALUES
    )
    enabled: Optional[bool] = None
    auto_join: Optional[bool] = None
    accepts_provider_placement: Optional[bool] = None


class PlatformProviderDefaultRead(SanitizedBaseModel):
    """How one provider is arranged for a community that has not said."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    provider_id: int
    claim: Optional[str] = None
    claim_values: List[str] = Field(default_factory=list)
    enabled: bool = True


class PlatformProviderDefaultUpdate(SanitizedBaseModel):
    """Answer for a provider on behalf of the communities that have not.

    Carries the arrangement and nothing else. There is no ``auto_join`` here:
    a default names a provider, never a community, so who joins a community
    stays that community's to say.
    """

    claim: Optional[str] = Field(default=None, max_length=64)
    claim_values: Optional[List[ClaimValue]] = Field(
        default=None, max_length=MAX_CLAIM_VALUES
    )
    enabled: Optional[bool] = None


class CommunityClaimRuleRead(SanitizedBaseModel):
    """One rule a community wrote: a group this provider asserts, and where
    somebody carrying it lands."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: int
    provider_id: int
    provider_display_name: str
    provider_icon: Optional[str] = None
    claim_value: str
    community_role: str = Field(
        validation_alias=AliasChoices("community_role", "guild_role")
    )
    initiative_id: Optional[int] = None
    initiative_name: Optional[str] = None
    initiative_role_id: Optional[int] = None
    initiative_role_name: Optional[str] = None


class CommunityClaimRuleCreate(SanitizedBaseModel):
    """Place the people carrying one group.

    Naming an initiative places them there as well as in the community, since
    somebody has to be in the community to be in one of its initiatives.
    """

    provider_id: int
    claim_value: str = Field(max_length=500)
    community_role: str = "member"
    initiative_id: Optional[int] = None
    initiative_role_id: Optional[int] = None


class CommunityClaimRulesResponse(SanitizedBaseModel):
    """The rules, and whether the providers behind them report groups at all.

    Which claim carries groups is the operator's to set per provider. A
    community can write rules against a provider that has none, and they will
    never match anything, so the surface says which of its connections are
    ready to be written against rather than letting somebody find out later.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    rules: List[CommunityClaimRuleRead] = Field(default_factory=list)
    #: Provider ids this community connects to that report groups.
    reporting_provider_ids: List[int] = Field(default_factory=list)
    #: The platform's rules that name this community, shown so a community
    #: always sees who is placed in it. Read-only here.
    provider_rules: List["ProviderPlacementRuleRead"] = Field(default_factory=list)
    #: Whether the deployment applies its rules to every community they name.
    placement_everywhere: bool = False


class ProviderPlacementRuleRead(SanitizedBaseModel):
    """One rule the platform wrote for a provider: which arrivals it matches,
    and where they land."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: int
    provider_id: int
    provider_display_name: str
    provider_icon: Optional[str] = None
    #: The group it places. Null where it names a directory instead, and
    #: places everybody arriving from it.
    claim_value: Optional[str] = None
    #: The verified claim and value naming which of the provider's directories
    #: the rule is about. Both or neither.
    scope_claim: Optional[str] = None
    scope_value: Optional[str] = None
    community_id: int = Field(validation_alias=AliasChoices("community_id", "guild_id"))
    community_name: str = Field(
        validation_alias=AliasChoices("community_name", "guild_name")
    )
    community_role: str = Field(
        validation_alias=AliasChoices("community_role", "guild_role")
    )
    initiative_id: Optional[int] = None
    initiative_name: Optional[str] = None
    initiative_role_id: Optional[int] = None
    initiative_role_name: Optional[str] = None
    #: Whether it places anybody now: the deployment applies provider rules
    #: everywhere, or the community accepts them on its connection.
    applies: bool


class ProviderPlacementRuleCreate(SanitizedBaseModel):
    """Place the people a provider asserts a group or a directory for.

    Naming an initiative places them there as well as in the community.
    """

    provider_id: int
    claim_value: Optional[str] = Field(default=None, max_length=500)
    scope_claim: Optional[str] = Field(default=None, max_length=64)
    scope_value: Optional[str] = Field(default=None, max_length=256)
    community_id: int
    community_role: str = "member"
    initiative_id: Optional[int] = None
    initiative_role_id: Optional[int] = None


class ProviderPlacementRuleUpdate(SanitizedBaseModel):
    """Change what a rule matches or where it lands. Its provider and its
    community are not editable: a rule pointed elsewhere is a different rule."""

    claim_value: Optional[str] = Field(default=None, max_length=500)
    scope_claim: Optional[str] = Field(default=None, max_length=64)
    scope_value: Optional[str] = Field(default=None, max_length=256)
    community_role: Optional[str] = None
    initiative_id: Optional[int] = None
    initiative_role_id: Optional[int] = None


CommunityClaimRulesResponse.model_rebuild()


class PlacementProviderRead(SanitizedBaseModel):
    """A provider rules can be written for, as the placement page lists it."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: int
    display_name: str
    icon: Optional[str] = None
    #: Whether the operator has said which claim carries its groups. Rules
    #: naming a group match nothing until it has.
    reports_groups: bool


class ProviderPlacementResponse(SanitizedBaseModel):
    """Everything the placement page shows."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    placement_everywhere: bool
    providers: List[PlacementProviderRead] = Field(default_factory=list)
    rules: List[ProviderPlacementRuleRead] = Field(default_factory=list)


class PlacementEverywhereUpdate(SanitizedBaseModel):
    """Apply the platform's rules to every community they name, or only to
    the ones that accepted them."""

    enabled: bool


class PlacementCommunityRead(SanitizedBaseModel):
    """A community a rule may name, and whether a rule naming it applies."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: int
    name: str
    #: The deployment applies rules everywhere, or this community accepts the
    #: provider's rules on its connection.
    placeable: bool


class PlacementInitiativeRoleRead(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: int
    name: str
    is_manager: bool


class PlacementInitiativeRead(SanitizedBaseModel):
    """An initiative a rule may place people in, with the roles it offers."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: int
    name: str
    roles: List[PlacementInitiativeRoleRead] = Field(default_factory=list)


class OIDCSettingsResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    enabled: bool
    issuer: Optional[str] = None
    client_id: Optional[str] = None
    redirect_uri: Optional[str] = None
    post_login_redirect: Optional[str] = None
    mobile_redirect_uri: Optional[str] = None
    provider_name: Optional[str] = None
    scopes: List[str] = Field(default_factory=list)


class LoginMethodStatus(SanitizedBaseModel):
    """One way in, and what withdrawing it would cost."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    method: LoginMethod
    enabled: bool
    #: Whether this method can begin a session on its own. False for a second
    #: factor, which accompanies a sign-in rather than opening one — the one
    #: distinction that decides where the surface asks about it, so it is
    #: derived from ``PRIMARY_LOGIN_METHODS`` here rather than listed again
    #: in the frontend.
    primary: bool
    #: Whether this method can answer a second-factor requirement. Derived
    #: from ``FACTOR_METHODS``, and orthogonal to ``primary``: a passkey is
    #: both — a way in on its own, and an answer to being asked for a factor.
    answers_factor: bool = False
    #: Accounts that can sign in today and could not if this method were
    #: withdrawn. Computed for every method, withdrawn or not, so the settings
    #: page can warn before the write rather than after a refusal — and so the
    #: number an operator acknowledges is one they were shown.
    would_strand: int


class AccountsWithoutFactor(SanitizedBaseModel):
    """How many accounts each level would ask to set a second factor up.

    Both figures on every read, so the page states the consequence of a choice
    before it is made rather than after it binds anybody.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    #: Accounts above ``member`` on the platform ladder holding neither an
    #: authenticator nor a passkey.
    platform_roles: int
    #: Every live account holding neither.
    everyone: int


class PlatformAuthSettingsResponse(SanitizedBaseModel):
    """The ways in this deployment permits, with the facts a change would turn
    on."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    methods: List[LoginMethodStatus]
    #: Guilds that require a sign-in through a provider of their own.
    #: Withdrawing single sign-on is refused while any exist; lifting the
    #: requirement releases it.
    communities_requiring_sign_in: int = Field(
        validation_alias=AliasChoices(
            "communities_requiring_sign_in", "guilds_requiring_sign_in"
        )
    )
    #: Whether anything this deployment permits could answer a second-factor
    #: requirement — the authenticator app or a passkey, either will do. False
    #: means the requirement below cannot be raised, and the server refuses it
    #: with ``AUTH_RULE_NOT_OFFERED``. Answered here so the
    #: surface can say so before the write, and so it never has to work out
    #: which methods count.
    factor_methods_permitted: bool = True
    #: How long somebody may stay signed in before signing in again, in hours.
    #: ``None`` asks for no limit, which is the default. A community held to
    #: the compliance standard overrides it downwards for its own members.
    session_max_hours: Optional[int] = None
    #: How long a session may be left alone before it lapses, in minutes.
    #: ``None`` leaves the deployment's configured refresh window. A community
    #: held to the compliance standard narrows it further for its members.
    session_idle_minutes: Optional[int] = None
    #: Who this deployment asks to hold a second factor.
    second_factor_requirement: SecondFactorRequirement = SecondFactorRequirement.nobody
    #: What each level would ask for, as things stand.
    accounts_without_factor: AccountsWithoutFactor


class PlatformAuthSettingsUpdate(SanitizedBaseModel):
    """The rules to change. An omitted field is left as it is.

    The whole request is one change: it is applied together or refused
    together, and a rule it loosens is loosened before one it tightens is
    checked. Nobody is signed out by any of it.
    """

    #: The ways in to permit from now on, at least one. Order and repetition
    #: are ignored.
    methods: Optional[List[LoginMethod]] = Field(default=None, min_length=1)
    #: Set to proceed with a change to ``methods`` that strands accounts. It
    #: must equal the number the server currently computes, so it cannot be
    #: sent blind or replayed once the number has moved — an operator
    #: acknowledges a figure they were actually shown.
    acknowledge_stranded: Optional[int] = Field(default=None, ge=0)
    #: Who to ask for a second factor. An account the level covers is asked at
    #: its next request and answers it where it stands; one that cannot
    #: present a factor — the app on a phone, a personal API key — works again
    #: once its owner holds one.
    second_factor_requirement: Optional[SecondFactorRequirement] = None
    #: The absolute limit on staying signed in, in hours. Sent as ``null``, no
    #: limit. It has to be longer than the idle window to mean anything: set
    #: shorter, it is the only thing ending a session — which is a fair thing
    #: to ask for, and the reason the field is free rather than a list of
    #: blessed figures.
    session_max_hours: Optional[int] = Field(default=None, ge=1, le=87600)
    #: The idle window, in minutes. Sent as ``null``, no limit of its own,
    #: which leaves ``AUTH_REFRESH_TTL_DAYS``. Floored at a minute — anything
    #: less ends a session while somebody is still reading the page.
    session_idle_minutes: Optional[int] = Field(default=None, ge=1, le=525600)


class InterfaceSettingsResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    light_accent_color: str
    dark_accent_color: str
    #: Whether arriving visitors are asked what this deployment may keep in
    #: their browser. Read, like the colours, from ``GET /config``.
    cookie_consent_enabled: bool


class InterfaceSettingsUpdate(SanitizedBaseModel):
    light_accent_color: str
    dark_accent_color: str
    #: Omitted leaves it as it was, so saving a colour does not silently
    #: answer a separate question.
    cookie_consent_enabled: bool | None = None


class CommunitySettingsResponse(SanitizedBaseModel):
    """Whether this deployment runs a community directory.

    Read back by the owner's settings page after a write; everyone else learns
    the same fact from ``GET /config``, which is where the SPA reads it to
    decide whether to offer the directory at all.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    community_directory_enabled: bool
    age_gate_enabled: bool
    #: The policy a newly created account starts on. Read once, when the
    #: account is made; changing it moves no existing account.
    default_dm_policy: DmPolicy
    #: Whether this deployment offers direct messages at all. Also on
    #: ``GET /config``, which is where every signed-in page reads it.
    direct_messages_enabled: bool
    #: How long a deleted community is kept before it is destroyed, in days.
    #: ``None`` means it is never destroyed — a deployment that has undertaken
    #: to keep what its members put in it. Owner-only, deployment-wide; a
    #: community has no say in its own.
    deleted_community_retention_days: Optional[int] = None
    #: How long a deleted account is kept before it is erased, in days. Its own
    #: figure rather than the one above: what a deployment owes the people in a
    #: community and what it owes the person leaving are different questions.
    #: ``None`` means never, for a deployment required to keep accounts.
    deleted_account_retention_days: Optional[int] = None
    #: How long a community stays on hold before it is deleted, in days,
    #: counted from when it was put there. ``None`` means never: it waits for
    #: somebody to lift the hold or delete it.
    on_hold_community_deletion_days: Optional[int] = None
    #: Whether search may order a community's content by how many members
    #: engaged with it lately. Each community is asked too, and off wins.
    engagement_ranking_enabled: bool
    #: Whether communities may have guests, and the longest a guest may stay,
    #: in days. Off, no guest reaches anything until it is back on.
    guests_enabled: bool
    max_guest_days: int


class NotificationSettingsResponse(SanitizedBaseModel):
    """What this deployment permits a notification to leave the app carrying.

    Three answers, each also asked of every community; the stricter of the pair
    applies, so a community may decline what this permits and never the other
    way round.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    #: Whether a notification may reach a phone. Off, nothing is sent, the
    #: registration endpoint declines, and no push token is held.
    push_notifications_enabled: bool
    #: Whether a notification may reach a mailbox. The notification half of
    #: email only — a sign-in code, an address to confirm, a password reset and
    #: the notices an account gets about itself are unaffected.
    email_notifications_enabled: bool
    #: Whether a notification that leaves the app may name the thing it is
    #: about. Set, it says the kind of thing that happened and the app is where
    #: the rest of it is. The bell inside the app is unaffected.
    redact_notification_content: bool


class NotificationSettingsUpdate(SanitizedBaseModel):
    push_notifications_enabled: bool
    email_notifications_enabled: bool
    redact_notification_content: bool


class CommunitySettingsUpdate(SanitizedBaseModel):
    community_directory_enabled: bool
    #: Whether an account must confirm it is 16 or older to join a listed
    #: guild from the directory. Omitted leaves it as it was — the two switches
    #: are separate decisions and the directory one is written far more often.
    age_gate_enabled: Optional[bool] = None
    #: Omitted leaves it as it was, like the switch above.
    default_dm_policy: Optional[DmPolicy] = None
    #: Whether this deployment offers direct messages at all. Omitted leaves it
    #: as it was; it is independent of the directory, which a deployment can
    #: run with or without messaging.
    direct_messages_enabled: Optional[bool] = None
    #: Whether search may rank by engagement in any community. Omitted leaves
    #: it as it was.
    engagement_ranking_enabled: Optional[bool] = None
    #: How long a deleted community is kept, in days. This one reads its
    #: presence rather than its value, because ``null`` is an answer here
    #: ("never destroy one") and not the absence of one: omit the field to
    #: leave the window alone, send a number to set it, send ``null`` to turn
    #: destruction off. The endpoint inspects ``model_fields_set``.
    deleted_community_retention_days: Optional[int] = Field(
        default=None,
        ge=MIN_GUILD_RETENTION_DAYS,
        le=MAX_GUILD_RETENTION_DAYS,
    )
    #: The account window, read the same way: omit to leave it alone, send a
    #: number to set it, send ``null`` to stop erasing on a timer.
    deleted_account_retention_days: Optional[int] = Field(
        default=None,
        ge=MIN_GUILD_RETENTION_DAYS,
        le=MAX_GUILD_RETENTION_DAYS,
    )
    #: The hold window, read the same way: omit to leave it alone, send a
    #: number to set it, send ``null`` to stop deleting held communities.
    on_hold_community_deletion_days: Optional[int] = Field(
        default=None,
        ge=MIN_GUILD_RETENTION_DAYS,
        le=MAX_GUILD_RETENTION_DAYS,
    )
    #: Omitted, each is left as it was.
    guests_enabled: Optional[bool] = None
    max_guest_days: Optional[int] = Field(
        default=None, ge=1, le=MAX_GUILD_RETENTION_DAYS
    )


class EmailSettingsResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    host: Optional[str] = None
    port: Optional[int] = None
    secure: bool = False
    reject_unauthorized: bool = True
    username: Optional[str] = None
    has_password: bool = False
    from_address: Optional[str] = None
    test_recipient: Optional[EmailStr] = None


class EmailSettingsUpdate(SanitizedBaseModel):
    host: Optional[str] = None
    port: Optional[int] = Field(default=None, ge=1, le=65535)
    secure: bool = False
    reject_unauthorized: bool = True
    username: Optional[str] = None
    password: Optional[RawTextStr] = None
    from_address: Optional[str] = None
    test_recipient: Optional[EmailStr] = None


class EmailTestRequest(SanitizedBaseModel):
    recipient: Optional[EmailStr] = None


class EmailTestResponse(SanitizedBaseModel):
    """Result of a test-email send. ``status`` is ``"sent"`` on success;
    failures surface as HTTP errors, not a status value here."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    status: str


# --- Object storage schemas ---


class StorageSettingsResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    backend: StorageBackendKind = StorageBackendKind.local
    s3_bucket: Optional[str] = None
    s3_region: str = "us-east-1"
    s3_endpoint_url: Optional[str] = None
    s3_access_key_id: Optional[str] = None
    has_secret_access_key: bool = False
    s3_use_path_style: bool = False
    s3_local_fallback: bool = False


class StorageSettingsUpdate(SanitizedBaseModel):
    backend: StorageBackendKind = StorageBackendKind.local
    s3_bucket: Optional[str] = None
    s3_region: str = "us-east-1"
    s3_endpoint_url: Optional[str] = None
    s3_access_key_id: Optional[str] = None
    s3_secret_access_key: Optional[RawTextStr] = None
    s3_use_path_style: bool = False
    s3_local_fallback: bool = False


class CaptchaSettingsResponse(SanitizedBaseModel):
    """What the settings page shows for the registration captcha.

    The secret is reported as stored or not, never returned — the same contract
    as the storage and email pages above.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    provider: Optional[CaptchaProvider] = None
    site_key: Optional[str] = None
    has_secret_key: bool = False
    #: Whether enforcement is actually on — all three of provider, site key and
    #: secret. Shown rather than inferred in the client, because the client
    #: cannot see the third one.
    enforcing: bool = False


class CaptchaSettingsUpdate(SanitizedBaseModel):
    provider: Optional[CaptchaProvider] = None
    site_key: Optional[str] = None
    #: Omit to keep the stored secret; send null or "" to clear it. Raw text:
    #: a provider secret is opaque and must not be sanitized.
    secret_key: Optional[RawTextStr] = None


class PushSettingsResponse(SanitizedBaseModel):
    """What the settings page shows for push notifications (FCM)."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    enabled: bool = False
    project_id: Optional[str] = None
    application_id: Optional[str] = None
    api_key: Optional[str] = None
    sender_id: Optional[str] = None
    has_service_account: bool = False


class PushSettingsUpdate(SanitizedBaseModel):
    enabled: bool = False
    project_id: Optional[str] = None
    application_id: Optional[str] = None
    api_key: Optional[str] = None
    sender_id: Optional[str] = None
    #: The service-account JSON. Omit to keep the stored one; send null or ""
    #: to clear it. Raw text, and long: a Google service account is ~2.4 kB.
    service_account_json: Optional[RawTextStr] = None

    @field_validator("service_account_json")
    @classmethod
    def _service_account_is_a_json_object(cls, value: Optional[str]) -> Optional[str]:
        """The key file Firebase issues is one JSON object; anything else is
        refused here rather than stored and failed on at the first send."""
        if value is None or not value.strip():
            return value
        try:
            parsed = json.loads(value)
        except ValueError:
            raise ValueError("service_account_json must be JSON") from None
        if not isinstance(parsed, dict):
            raise ValueError("service_account_json must be a JSON object")
        return value


class StorageTestResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    success: bool
    message: str


class StorageBackfillStatusResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    status: Literal["idle", "running", "complete", "failed"] = "idle"
    copied: int = 0
    skipped: int = 0
    failed: int = 0
    hash_mismatches: int = 0
    failed_keys: List[str] = Field(default_factory=list)
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error: Optional[str] = None
