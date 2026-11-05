"""The shapes a request's database context can take.

A session is routed by handing :func:`app.db.session.set_rls_context` one of
the classes below. The shape is what the session stores and what every
transaction replays, so what Python believes about a session and what the
database is told are the same value.

Each shape names one community at most, by ``guild_id``: the schema and role
the session assumes follow from that and from the kind of access the shape is.
How it reached the community — membership, a content grant, a settings grant —
is the shape itself; which session variable carries the community for the
shared tables' policies is part of what the shape writes.

Every shape answers three things (:meth:`route`): the variables it writes, the
role it assumes and the schemas it resolves in. The variables it does not name
are written empty, which is what keeps one request's context from reaching the
next on a pooled connection.

A shape checks itself when it is built, so a combination that is no request
this system makes cannot be constructed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Mapping, Optional, Union

from app.db import gucs
from app.db.guild_standing import GuildContext, InstallContext, standing_values
from app.db.public_rls import PLATFORM_ROUTES, platform_tier, role_name

if TYPE_CHECKING:  # pragma: no cover
    from app.db.schema_provisioning import GuildRoleKind

__all__ = [
    "QUERYABLE",
    "SYSTEM_SATISFIED",
    "Billing",
    "ContentGrantee",
    "ContextShapeError",
    "Filer",
    "SignIn",
    "Install",
    "Member",
    "Platform",
    "RequestContext",
    "Route",
    "SettingsGrantee",
    "SystemGuild",
    "SystemMaintenance",
    "Unattributed",
]

#: What ``app.satisfied_providers`` says for work a job does as the person who
#: asked for it. ``public.guild_auth_satisfied()`` reads it as answered.
SYSTEM_SATISFIED = "system"


class ContextShapeError(ValueError):
    """The values do not describe any request this system makes."""


@dataclass(frozen=True)
class Route:
    """What a shape tells the database: the variables it writes, the role it
    assumes and the schemas it resolves in, in order."""

    values: dict[gucs.Guc, Any]
    role: str
    schemas: tuple[str, ...]


@dataclass(frozen=True)
class SignIn:
    """How the session signed in, as the community's sign-in rule reads it.

    ``on_behalf`` is work a job does as the person who asked for it, whose own
    request already met the rule. Only ``app.api.deps.establish_on_behalf``
    sets it.
    """

    #: The providers the credential proved.
    providers: tuple[int, ...] = ()
    #: What those providers asserted, ``{"<provider id>": {claim: [values]}}``.
    claims: Optional[Mapping[str, Any]] = None
    #: The assurance markers the credential recorded.
    amr: frozenset[str] = frozenset()
    #: The account answers the deployment's own second-factor rule.
    platform_factor: bool = False
    on_behalf: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "providers", tuple(sorted(int(p) for p in self.providers))
        )
        object.__setattr__(self, "amr", frozenset(self.amr))

    def writes(self) -> dict[gucs.Guc, Any]:
        return {
            gucs.SATISFIED_PROVIDERS: SYSTEM_SATISFIED
            if self.on_behalf
            else ",".join(str(p) for p in self.providers),
            gucs.SATISFIED_CLAIMS: self.claims,
            gucs.SESSION_AMR: self.amr,
            gucs.PLATFORM_FACTOR: self.platform_factor,
        }


def _guild_role(guild_id: int, kind: "GuildRoleKind") -> str:
    from app.db.schema_provisioning import guild_role_name

    return guild_role_name(guild_id, kind)


def _guild_schemas(guild_id: int, *, query: bool = False) -> tuple[str, ...]:
    from app.db.schema_provisioning import guild_schema_name

    # A query sees its own community alone; what it reads in ``public`` it
    # names by schema.
    schema = guild_schema_name(guild_id)
    return (schema,) if query else (schema, "public")


def _tier_role(tier: Optional[str]) -> str:
    return role_name(platform_tier(tier)) if tier is not None else "none"


def _check_tier(tier: Optional[str]) -> None:
    if tier is not None and tier not in PLATFORM_ROUTES:
        raise ContextShapeError(f"Invalid platform_role: {tier!r}")


def _computed(standing: Any) -> bool:
    return standing is not None and standing.standing_guild_id is not None


# --- No community -------------------------------------------------------------


@dataclass(frozen=True)
class Unattributed:
    """No person and no community: workers, seeding, and the deliberate reset.

    Reads whatever the login role's own grants and policies allow and nothing
    more: with no ``current_user_id`` set, every own-row policy matches nothing.
    """

    guild_id: None = field(default=None, init=False, repr=False)
    user_id: None = field(default=None, init=False, repr=False)
    attributed = False

    def route(self) -> Route:
        return Route({gucs.GUILD_AUTH_OK: True}, "none", ("public",))


@dataclass(frozen=True)
class Platform:
    """A signed-in person with no community in the request.

    Assumes ``platform_<tier>`` so the request is role-scoped at the database
    rather than running as the bare login role; with no tier, the login role.
    """

    user_id: int
    tier: Optional[str] = None
    guild_id: None = field(default=None, init=False, repr=False)
    attributed = True

    def __post_init__(self) -> None:
        _check_tier(self.tier)

    def route(self) -> Route:
        return Route(
            {gucs.USER_ID: self.user_id, gucs.PLATFORM_ROLE: self.tier},
            _tier_role(self.tier),
            ("public",),
        )


@dataclass(frozen=True)
class Billing:
    """The billing service, verified, acting for one community's account.

    No person and no community schema: the ``initiative_billing`` role is the
    whole of what it reads, keyed on the community it names.
    """

    billing_guild_id: int
    guild_id: None = field(default=None, init=False, repr=False)
    user_id: None = field(default=None, init=False, repr=False)
    attributed = False

    def route(self) -> Route:
        return Route(
            {gucs.BILLING_GUILD_ID: self.billing_guild_id},
            role_name("initiative_billing"),
            ("public",),
        )


# --- A person in a community --------------------------------------------------


def _grant_flags(standing: Any, read: bool, write: bool) -> tuple[bool, bool]:
    """The content grant's flags: recomputed from the grant rows by the
    standing statement once it has run, and the lookup's until then."""
    if _computed(standing):
        return standing.pam_read, standing.pam_write
    return read, write


def _person_values(
    shape: "Member | ContentGrantee | SettingsGrantee",
    community: dict[gucs.Guc, Optional[int]],
    *,
    pam_read: bool,
    pam_write: bool,
) -> dict[gucs.Guc, Any]:
    standing = shape.standing
    return {
        **standing_values(standing),
        gucs.USER_ID: shape.user_id,
        **community,
        gucs.PLATFORM_ROLE: shape.tier,
        **shape.sign_in.writes(),
        gucs.PAM_READ: pam_read,
        gucs.PAM_WRITE: pam_write,
        gucs.SCOPE_INITIATIVE_ID: getattr(shape, "scope_initiative_id", None),
        gucs.QUERY: getattr(shape, "query", False),
        gucs.GUILD_AUTH_OK: shape.sign_in.on_behalf
        or (standing is not None and standing.guild_auth_ok),
    }


@dataclass(frozen=True)
class Member:
    """A member of the community, routed by the establishment seam.

    ``standing`` is the ``GuildContext`` the seam built. Nothing here says who
    the reader is in the community: that is the membership row, which the
    standing statement reads.

    ``read_only`` is the community's content hold: the SELECT-only role, with
    the membership legs evaluated normally. ``seat`` is the seat's own
    configuration routes asking for the seat's role. ``query`` is the reader's
    own SQL on the query surface, narrowed to ``scope_initiative_id``. A guest's
    membership routes into the community's guest role, and asks for neither.
    """

    guild_id: int
    user_id: int
    standing: GuildContext
    tier: Optional[str] = None
    sign_in: SignIn = SignIn()
    read_only: bool = False
    seat: bool = False
    query: bool = False
    scope_initiative_id: Optional[int] = None
    attributed = True

    def __post_init__(self) -> None:
        _check_tier(self.tier)
        if not isinstance(self.standing, GuildContext):
            raise ContextShapeError(
                "routing a member takes the GuildContext the seam builds; call "
                "app.api.deps.establish_guild_access"
            )
        if self.standing.routes_as_guest and (self.seat or self.query):
            raise ContextShapeError("a guest holds no seat and no query surface")

    def route(self) -> Route:
        from app.db.schema_provisioning import GuildRoleKind

        if self.standing.routes_as_guest:
            kind = (
                GuildRoleKind.guest_read_only if self.read_only else GuildRoleKind.guest
            )
        elif self.seat:
            kind = GuildRoleKind.seat
        elif self.query:
            kind = GuildRoleKind.query
        elif self.read_only:
            kind = GuildRoleKind.read_only
        else:
            kind = GuildRoleKind.full
        pam_read, pam_write = _grant_flags(self.standing, False, False)
        return Route(
            _person_values(
                self,
                {gucs.GUILD_ID: self.guild_id},
                pam_read=pam_read,
                pam_write=pam_write,
            ),
            _guild_role(self.guild_id, kind),
            _guild_schemas(self.guild_id, query=self.query),
        )


@dataclass(frozen=True)
class ContentGrantee:
    """A time-bound grant into a community the person does not belong to.

    ``read_write`` is the grant's level as the lookup found it; the standing
    statement recomputes both flags from the grant rows. ``standing`` is
    ``None`` only inside the seam, between routing on the grant and computing
    the standing. ``settings`` is the other half of break-glass: a settings
    grant into the same community, beside this one.
    """

    guild_id: int
    user_id: int
    standing: Optional[GuildContext] = None
    read_write: bool = False
    settings: bool = False
    tier: Optional[str] = None
    sign_in: SignIn = SignIn()
    seat: bool = False
    query: bool = False
    scope_initiative_id: Optional[int] = None
    attributed = True

    def __post_init__(self) -> None:
        _check_tier(self.tier)

    def route(self) -> Route:
        from app.db.schema_provisioning import GuildRoleKind

        pam_read, pam_write = _grant_flags(self.standing, True, self.read_write)
        values = _person_values(
            self,
            {
                gucs.PAM_GUILD_ID: self.guild_id,
                gucs.SETTINGS_GUILD_ID: self.guild_id if self.settings else None,
            },
            pam_read=pam_read,
            pam_write=pam_write,
        )
        if not (pam_read or pam_write or self.settings):
            # The standing found no live grant: nothing of the community.
            return Route(values, _tier_role(self.tier), ("public",))
        if self.seat:
            kind = GuildRoleKind.seat
        elif self.query:
            kind = GuildRoleKind.query
        elif pam_write:
            kind = GuildRoleKind.support
        else:
            kind = GuildRoleKind.read_only
        return Route(
            values,
            _guild_role(self.guild_id, kind),
            _guild_schemas(self.guild_id, query=self.query),
        )


@dataclass(frozen=True)
class SettingsGrantee:
    """A settings grant alone: the community's configuration, read.

    Writing what it reaches takes a ``read_write`` content grant beside it,
    which is a :class:`ContentGrantee` with ``settings``.
    """

    guild_id: int
    user_id: int
    standing: GuildContext
    tier: Optional[str] = None
    sign_in: SignIn = SignIn()
    seat: bool = False
    attributed = True

    def __post_init__(self) -> None:
        _check_tier(self.tier)
        if not isinstance(self.standing, GuildContext):
            raise ContextShapeError(
                "routing a settings grant takes the GuildContext the seam builds"
            )

    def route(self) -> Route:
        from app.db.schema_provisioning import GuildRoleKind

        pam_read, pam_write = _grant_flags(self.standing, False, False)
        if self.seat:
            kind = GuildRoleKind.seat
        elif pam_write:
            kind = GuildRoleKind.support
        else:
            kind = GuildRoleKind.read_only
        return Route(
            _person_values(
                self,
                {gucs.SETTINGS_GUILD_ID: self.guild_id},
                pam_read=pam_read,
                pam_write=pam_write,
            ),
            _guild_role(self.guild_id, kind),
            _guild_schemas(self.guild_id),
        )


# --- An installed plug-in -----------------------------------------------------


@dataclass(frozen=True)
class Install:
    """An installed plug-in acting in the community it is installed in.

    The install is the principal, routed into ``guild_<id>_plugin``. ``standing``
    is the ``InstallContext`` the install seam built, which names the same
    community and install. A member token also names the member it acts for and
    the purpose they consented to, both carried by that context; it is never a
    person's own routing. It narrows to one initiative the way a person's read
    does; no other narrowing, grant or credential value belongs to it.
    """

    guild_id: int
    install_id: int
    standing: InstallContext
    token_client_id: str
    token_scopes: frozenset[str] = frozenset()
    scope_initiative_id: Optional[int] = None
    member_user_id: Optional[int] = None
    token_purpose: Optional[str] = None
    user_id: None = field(default=None, init=False, repr=False)
    attributed = True

    def __post_init__(self) -> None:
        standing = self.standing
        if not isinstance(standing, InstallContext):
            raise ContextShapeError(
                "routing an install takes the InstallContext the seam builds; call "
                "app.api.deps.establish_install_access"
            )
        if (standing.install_id, standing.guild_id) != (self.install_id, self.guild_id):
            raise ContextShapeError(
                "an install routing and its context name the same install in the "
                "same community"
            )
        if not self.token_client_id:
            raise ContextShapeError("an install routing names its token's client")
        if self.token_purpose is not None and self.member_user_id is None:
            raise ContextShapeError("a purpose belongs to a member token")
        if (standing.member_user_id, standing.purpose) != (
            self.member_user_id,
            self.token_purpose,
        ):
            raise ContextShapeError(
                "a member token's routing and its context name the same member "
                "and purpose"
            )
        object.__setattr__(self, "token_scopes", frozenset(self.token_scopes))

    def route(self) -> Route:
        from app.db.schema_provisioning import GuildRoleKind

        completed = _computed(self.standing)
        return Route(
            {
                **standing_values(self.standing if completed else None),
                gucs.USER_ID: self.member_user_id,
                gucs.GUILD_ID: self.guild_id,
                gucs.INSTALL_ID: self.install_id,
                gucs.TOKEN_CLIENT_ID: self.token_client_id,
                gucs.TOKEN_SCOPES: self.token_scopes,
                gucs.TOKEN_PURPOSE: self.token_purpose,
                gucs.SCOPE_INITIATIVE_ID: self.scope_initiative_id,
                gucs.GUILD_AUTH_OK: completed and self.standing.guild_auth_ok,
            },
            _guild_role(self.guild_id, GuildRoleKind.plugin),
            _guild_schemas(self.guild_id),
        )


# --- Somebody who filed a case ------------------------------------------------


@dataclass(frozen=True)
class Filer:
    """A person reading the cases they filed, in the operations community.

    Not a member and not a grantee: they hold no standing in the community and
    are routed into the one role that exists for this, ``guild_<id>_filer``,
    whose grants and row policies admit their own cases and nothing else (see
    ``app.db.operations_schema``). Only the account and its cases are written. The community is the
    schema and the role, never ``app.current_guild_id``, which the shared
    tables read as membership.
    """

    guild_id: int
    user_id: int
    #: The tasks of the cases they filed, as the seam read them through the
    #: filer role. Empty on the first routing, which is what reads them.
    cases: tuple[int, ...] = ()
    attributed = True

    def __post_init__(self) -> None:
        if self.user_id is None or self.guild_id is None:
            raise ContextShapeError(
                "a filer routing names the account and the community"
            )
        object.__setattr__(self, "cases", tuple(sorted(int(c) for c in self.cases)))

    def route(self) -> Route:
        from app.db.operations_schema import filer_role_name

        return Route(
            {gucs.USER_ID: self.user_id, gucs.FILER_CASES: self.cases},
            filer_role_name(self.guild_id),
            _guild_schemas(self.guild_id),
        )


# --- Nobody behind it ---------------------------------------------------------


@dataclass(frozen=True)
class SystemGuild:
    """Guild-scoped work with no person behind it: a sweep, a poller, a
    lifecycle job. Assumes the community's role (``read_only``: its
    SELECT-only role); the policies' system leg admits it by the connection's
    own login."""

    guild_id: int
    read_only: bool = False
    user_id: None = field(default=None, init=False, repr=False)
    attributed = False

    def route(self) -> Route:
        from app.db.schema_provisioning import GuildRoleKind

        kind = GuildRoleKind.read_only if self.read_only else GuildRoleKind.full
        return Route(
            {gucs.GUILD_ID: self.guild_id, gucs.GUILD_AUTH_OK: True},
            _guild_role(self.guild_id, kind),
            _guild_schemas(self.guild_id),
        )


@dataclass(frozen=True)
class SystemMaintenance:
    """Trusted system maintenance in one community's schema, keeping the
    system login rather than assuming the community's role.

    A small set of lifecycle operations must process every matching row
    whatever the tenant policies say; provisioning grants the system login
    direct access to exactly the tables those use. ``set_rls_context`` refuses
    this shape on any other login.
    """

    guild_id: int
    user_id: None = field(default=None, init=False, repr=False)
    attributed = False

    def route(self) -> Route:
        return Route(
            {gucs.GUILD_ID: self.guild_id, gucs.GUILD_AUTH_OK: True},
            "none",
            _guild_schemas(self.guild_id),
        )


RequestContext = Union[
    Unattributed,
    Platform,
    Billing,
    Member,
    ContentGrantee,
    SettingsGrantee,
    Install,
    Filer,
    SystemGuild,
    SystemMaintenance,
]

#: The shapes a reader's own SQL may run as on the query surface.
QUERYABLE = (Member, ContentGrantee)
