"""
Test data factories for creating database models.

This module provides factory functions for creating test instances of database
models with sensible defaults. Each factory function can accept overrides for
any field.

Schema-per-guild: tenant models live in per-guild Postgres schemas, never in
``public``. Every tenant factory therefore routes its session to the target
guild's schema (``route_session_to_guild``) before reading or writing, derived
from the parent object it receives — so factory calls are deterministic
regardless of flush composition. A tenant row carries no ``guild_id`` column,
because the schema it lives in is what says which community it is, so the
parent's community comes from ``guild_of`` — what the harness stamped on it as
it was flushed. Raw ``session.add()`` of tenant models in tests is covered by
the fail-closed flush router in ``schema_harness``.
"""

import base64
import functools
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Sequence

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from jwt.algorithms import OKPAlgorithm
from sqlalchemy import delete as sa_delete
from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.relationships import Provenance, RelationshipType
from app.core.search import SearchEntityType
from app.models.tenant.relationship import EntityRelationship
from app.services.tenant import relationships as relationships_service
from app.services.platform import rules
from app.core.tools import CHILD_KINDS, Tool
from app.core.security import (
    get_password_hash,
    mint_access_token,
)
from app.models.platform.plugin_service_registration import PluginServiceRegistration
from app.models.platform.publisher import Publisher, publisher_prefix
from app.core.reactions import ReactionTarget
from app.models.tenant.calendar import Calendar
from app.models.platform.marketplace import (
    MarketplaceListing,
    UID_ALPHABET,
    UID_LENGTH,
)
from app.models.tenant.dashboard import Dashboard
from app.models.tenant.post import Post
from app.models.tenant.collection import Collection, CollectionFile
from app.models.tenant.wiki import Wiki, WikiPage
from app.models.tenant.post_poll import PostPoll, PostPollOption
from app.models.tenant.guild_plugin import GuildPlugin
from app.models.tenant.guild_plugin_secret import GuildPluginSecret
from app.models.tenant.plugin_connection_secret import PluginConnectionSecret
from app.models.tenant.guild_plugin_user_connection import GuildPluginUserConnection
from app.models.tenant.calendar_event import CalendarEvent, CalendarEventAttendee
from app.models.tenant.comment import Comment
from app.models.tenant.counter import Counter, CounterGroup
from app.core.file_types import FileType, type_of_media
from app.models.tenant.file import File
from app.models.platform.access_grant import AccessGrant
from app.models.platform.guild import Guild, GuildMembership, CommunityRole
from app.core.guild_auth_options import CommunityAuthOption
from app.models.platform.guild_administration import GuildAdministration
from app.services.marketplace import plugin_installs
from app.services.marketplace import catalog as marketplace_catalog
from app.services.marketplace.registration_lookup import invalidate_registrations
from app.services.tenant import file_versions
from app.services.tenant import guild_plugins as guild_plugins_service
from app.services.tenant import plugin_schedules
from app.services.tenant.plugin_config import mint_connection_ref
from app.services.tenant.dashboard_definition import (
    normalize_dashboard_definition,
)
from app.models.tenant.initiative import Initiative, InitiativeMember
from app.models.tenant.project import Project
from app.models.tenant.resource_grant import ResourceGrant, ResourceAccessLevel
from app.models.tenant.metadata import (
    MetadataDefinition,
    MetadataType,
    MetadataValue,
)
from app.models.tenant.queue import Queue, QueueItem
from app.models.tenant.reaction import Reaction
from app.models.tenant.tag import Tag
from app.models.tenant.task import (
    Task,
    TaskAssignee,
    TaskPriority,
    TaskStatus,
    TaskStatusCategory,
)
from app.models.tenant.upload import Upload
from app.models.tenant.data_job import DataJob, DataJobDirection
from app.models.platform.auth_provider import AuthProvider, AuthProviderKind
from app.models.platform.guild_provider_connection import GuildProviderConnection
from app.models.platform.federated_identity import FederatedIdentity
from app.core.login_methods import LoginMethod
from app.core.rules import OPTION_RULES, SetBy, SignInRequirement
from app.models.platform.user import User, UserRole, UserStatus
from app.services.auth.platform_provider import PLATFORM_OIDC_SLUG
from app.core import usernames
from app.services.platform import guilds as guilds_service
from app.services.tenant.initiatives import create_builtin_roles
from app.schemas.tenant.task import mint_checklist_item_id
from app.services.tenant.ownership import tool_for_row
from app.services.tenant.task_completion import sync_completed_at
from app.services.tenant.task_statuses import ensure_default_statuses
from app.services.tenant.task_types import ensure_default_types
from app.services.tenant.names import slugify
from app.testing.schema_harness import guild_of, route_session_to_guild


@functools.cache
def _default_password_hash() -> str:
    """The hash of ``testpassword123``, worked out once per process.

    argon2id is slow on purpose, and nearly every test makes accounts with this
    password, so hashing it per account was a measurable share of the suite.
    Every account sharing one hash still signs in with the password.
    """
    return get_password_hash("testpassword123")


async def create_user(
    session: AsyncSession,
    commit: bool = True,
    **overrides: Any,
) -> User:
    """
    Create a test user with sensible defaults.

    Args:
        session: Database session
        commit: Whether to commit the transaction (default True)
        **overrides: Override any default field values

    Returns:
        Created User instance

    Example:
        user = await create_user(
            session,
            email="test@example.com",
            role=UserRole.operator
        )
    """
    email_raw = (
        overrides.pop(
            "email", f"user-{datetime.now(timezone.utc).timestamp()}@example.com"
        )
        .lower()
        .strip()
    )
    # Whether that address has been proved. It lives on the address row now, so
    # it is popped rather than passed to ``User``.
    address_confirmed = bool(overrides.pop("email_verified", True))
    # A handle is unique on (name, number). Tests that care about a specific
    # one pass it; everything else gets a distinct pair without having to.
    defaults = {
        "username": usernames.random_name(),
        "discriminator": usernames.random_discriminator(),
        "username_chosen": True,
        # Answered, for the same reason the handle is chosen: a test that is
        # not about the age gate should never meet it. The gate's own tests
        # pass ``age_confirmed_at=None`` to get an account that has not.
        "age_confirmed_at": datetime.now(timezone.utc),
        "hashed_password": _default_password_hash(),
        "role": UserRole.member,
        "status": UserStatus.active,
        "week_starts_on": 0,
        "timezone": "UTC",
        "event_reminder_minutes_before": 15,
    }

    user_data = {**defaults, **overrides}
    user = User(**user_data)

    session.add(user)
    await session.flush()

    # Every production path that makes an account seeds its direct-message
    # policy row and records its address, so the factory does too — otherwise a
    # test would be exercising the "no row at all" fallback rather than what a
    # real account looks like.
    from app.services.auth import addresses
    from app.services.auth import subject as subject_service
    from app.services.platform import dm_settings as dm_settings_service

    addresses.record_address(
        session,
        user_id=user.id,
        email=email_raw,
        source=addresses.SOURCE_SIGNUP,
        verified=address_confirmed,
    )
    await dm_settings_service.seed_for_new_account(session, user_id=user.id)
    # The name this account's access tokens carry. Kept on the object because
    # ``get_auth_token`` is called from hundreds of places that have the user
    # and no session; see ``AUTH_SUBJECT_ATTR``.
    setattr(user, SEEDED_ADDRESS_ATTR, email_raw)
    setattr(
        user,
        AUTH_SUBJECT_ATTR,
        await subject_service.subject_for_user(session, user_id=user.id),
    )

    if commit:
        await session.commit()
        await session.refresh(user)

    return user


async def set_notification_prefs(
    session: AsyncSession,
    user: User,
    prefs: dict[str, Any],
    commit: bool = True,
) -> None:
    """Give an account a notification settings document.

    No row is the normal state — it reads as every default — so a test only
    calls this when it is about somebody having changed something. The shape is
    the one ``app.services.platform.notification_prefs`` resolves::

        {"categories": {"comments": {"in_app": False}},
         "guilds": {"7": {"level": "personal"}}}
    """
    from app.services.platform import notification_prefs

    await notification_prefs.save_prefs(session, user.id, prefs)
    if commit:
        await session.commit()


async def create_guild(
    session: AsyncSession,
    creator: User | None = None,
    commit: bool = True,
    **overrides: Any,
) -> Guild:
    """Create a test guild through the service's creation path.

    The guild and its administration row, a named ``creator`` seated as its
    superadmin, its schema provisioned and its settings row seeded — what the
    community-create endpoint does, less the mandatory plug-ins, which tests reach
    through the backfill. Without a ``creator`` the guild is recorded as made by
    a filler account and has no members.

    Overrides for the operator-set fields (``max_storage_bytes``, ``max_users``,
    ``max_guests``, ``tier_name``, ``auth_options``) go through
    :func:`guild_administration`; the rest land on the guild. Example:
    ``guild = await create_guild(session, name="Test")``.
    """
    # Test guilds hold every sign-in option by default so the guild-auth
    # surface is exercisable without extra setup; production guilds hold none
    # (the operator grants each one from the Guilds dashboard). Pass
    # ``auth_options=[]`` to exercise the ungranted paths, or a shorter list to
    # exercise one option without the other.
    administration_data: dict[str, Any] = {
        "auth_options": [option.value for option in CommunityAuthOption],
        **{
            field: overrides.pop(field)
            for field in (
                "max_storage_bytes",
                "max_users",
                "max_guests",
                "tier_name",
                "auth_options",
            )
            if field in overrides
        },
    }
    # Accepts the enum or its value, like every other enum a factory takes.
    administration_data["auth_options"] = [
        option.value if isinstance(option, CommunityAuthOption) else option
        for option in administration_data["auth_options"]
    ]
    if creator is None:
        overrides.setdefault(
            "created_by", (await create_user(session, commit=commit)).id
        )

    guild = await guilds_service.create_guild(
        session,
        name=overrides.pop(
            "name", f"Test Guild {datetime.now(timezone.utc).timestamp()}"
        ),
        description=overrides.pop(
            "description", "A test guild for integration testing"
        ),
        creator=creator,
    )
    for field, value in overrides.items():
        setattr(guild, field, value)
    session.add(guild)
    await guild_administration(session, guild, commit=False, **administration_data)

    if commit:
        await session.commit()
        await session.refresh(guild)
        from app.db.schema_provisioning import provision_guild

        await provision_guild(guild.id)
        await route_session_to_guild(session, guild.id)
        await guilds_service.create_guild_settings(session, guild.id)
        await session.commit()

    return guild


async def community_plan(session: AsyncSession, guild_id: int) -> rules.Values:
    """What one community's rules say now, its plan among them."""
    return (await rules.community_values(session, [guild_id]))[guild_id]


#: The operator's fields by the names its API uses, and the paid rule each is.
_PLAN_FIELDS = {
    "max_storage_bytes": "max_storage_bytes",
    "max_users": "max_users",
    "max_guests": "max_guests",
    "banner_image_enabled": "banner_image",
    "support_enabled": "help_requests",
}


async def guild_administration(
    session: AsyncSession, guild: Guild, commit: bool = True, **fields: Any
) -> GuildAdministration:
    """Read (and optionally set) what the deployment says of one community,
    by the names the operator's API uses.

    The caps and entitlements are its paid rules, written as the deployment's
    rows (``auth_options`` as the two sign-in options); the plan label and
    billing's bookkeeping are on ``guild_administration``, whose row this
    returns. Called with no ``fields`` it is a plain read.
    """
    row = (
        await session.exec(
            select(GuildAdministration).where(GuildAdministration.guild_id == guild.id)
        )
    ).one()
    for name, value in fields.items():
        if name in _PLAN_FIELDS:
            await rules.put(
                session,
                _PLAN_FIELDS[name],
                value,
                guild_id=guild.id,
                set_by=SetBy.deployment,
            )
        elif name == "auth_options":
            held = {CommunityAuthOption(option) for option in value}
            for option, key in OPTION_RULES.items():
                await rules.put(
                    session,
                    key,
                    option in held,
                    guild_id=guild.id,
                    set_by=SetBy.deployment,
                )
        else:
            setattr(row, name, value)
    if fields:
        session.add(row)
        if commit:
            await session.commit()
            await session.refresh(row)
        else:
            await session.flush()
    return row


async def create_access_grant(
    session: AsyncSession,
    *,
    user: User,
    guild: Guild,
    access_level: str = "read",
    purpose: str = "content",
    minutes: int = 60,
    commit: bool = True,
) -> AccessGrant:
    """A live, approved grant — what the seam reads when somebody reaches a
    community they do not belong to.

    Self-approved, which is what a break-glass row is; a requested-then-approved
    one differs only in who decided it, and nothing that reads a grant asks.
    """
    now = datetime.now(timezone.utc)
    grant = AccessGrant(
        user_id=user.id,
        guild_id=guild.id,
        access_level=access_level,
        status="approved",
        purpose=purpose,
        reason="test",
        requested_duration_minutes=minutes,
        requested_by_id=user.id,
        approved_by_id=user.id,
        requested_at=now,
        decided_at=now,
        expires_at=now + timedelta(minutes=minutes),
    )
    session.add(grant)
    if commit:
        await session.commit()
        await session.refresh(grant)
    return grant


async def create_guild_membership(
    session: AsyncSession,
    user: User | None = None,
    guild: Guild | None = None,
    role: CommunityRole = CommunityRole.member,
    commit: bool = True,
    **overrides: Any,
) -> GuildMembership:
    """
    Create a guild membership (linking a user to a guild).

    Args:
        session: Database session
        user: User to add to guild (will be created if not provided)
        guild: Guild to add user to (will be created if not provided)
        role: Guild role for the user (default: member)
        commit: Whether to commit the transaction (default True)
        **overrides: Override any default field values. ``api_keys_allowed``,
            when given, sets the member's ``api_keys`` rule instead.

    Returns:
        Created GuildMembership instance

    Example:
        membership = await create_guild_membership(
            session,
            user=test_user,
            guild=test_guild,
            role=CommunityRole.admin
        )
    """
    if user is None:
        user = await create_user(session, commit=commit)

    if guild is None:
        guild = await create_guild(session, commit=commit)

    defaults = {
        "user_id": user.id,
        "guild_id": guild.id,
        "role": role,
        "position": 0,
    }

    api_keys_allowed = overrides.pop("api_keys_allowed", None)
    membership_data = {**defaults, **overrides}
    # The creator already has one (``create_guild`` seats them), so asking for
    # theirs again says what role they should hold rather than adding a second
    # row the table would refuse.
    existing = (
        await session.exec(
            select(GuildMembership).where(
                GuildMembership.guild_id == guild.id,
                GuildMembership.user_id == user.id,
            )
        )
    ).one_or_none()
    if existing is not None:
        for field, value in membership_data.items():
            setattr(existing, field, value)
        membership = existing
    else:
        membership = GuildMembership(**membership_data)
    session.add(membership)
    if api_keys_allowed is not None:
        await session.flush()
        await rules.put(
            session, "api_keys", api_keys_allowed, guild_id=guild.id, user_id=user.id
        )

    if commit:
        await session.commit()
        await session.refresh(membership)

    return membership


async def create_guest(
    session: AsyncSession,
    guild: Guild,
    *,
    role: CommunityRole = CommunityRole.guest,
    ends_in: timedelta = timedelta(hours=1),
) -> User:
    """A new account that is a guest of ``guild`` until ``ends_in`` from now.
    The platform's guest switch is the caller's to set."""
    user = await create_user(session)
    await create_guild_membership(
        session,
        user=user,
        guild=guild,
        role=role,
        guest_until=datetime.now(timezone.utc) + ends_in,
    )
    return user


#: Where :func:`create_user` leaves the ``client``-sector reference an access
#: token names the account by. Not a column — it is the value of a row in
#: ``identity_refs``, carried on the object so the sync token helpers below can
#: reach it. A user built any other way has none, and asking for a token for it
#: says so rather than falling back to the row id, which would be the one form
#: the shipped token no longer uses.
AUTH_SUBJECT_ATTR = "auth_subject"

#: The address the factory gave the account, attached to the object for the
#: same reason the subject is: a test that asserts an address is absent from a
#: response needs to know which address, and ``users`` no longer carries
#: one. Deliberately not called ``email``: the model has no such field, and a
#: name shaped like one belongs to the model rather than to the factory.
SEEDED_ADDRESS_ATTR = "seeded_address"


def get_auth_token(
    user: User,
    *,
    session_id: uuid.UUID | None = None,
    amr: list[str] | None = None,
    satisfied_providers: list[int] | None = None,
    asserted_claims: dict[int, dict[str, list[str]]] | None = None,
    token_version: int | None = None,
    expires_in: timedelta | None = None,
) -> str:
    """A session credential for ``user`` — the token the app actually issues.

    ``aud=initiative:access``, carrying ``sid``/``amr``/``sat``, so a test
    authenticates through the same verification a signed-in browser does.
    ``sub`` is the account's ``client``-sector reference, ``sid`` a throwaway
    uuid: the access token is stateless and nothing on the request path
    resolves it against an ``auth_sessions`` row.

    ``sat`` defaults to empty, which is what a password sign-in carries — a
    test that needs a guild's sign-in policy satisfied passes the provider ids.
    ``asserted_claims`` is what those providers said about the person, keyed by
    provider id (``{7: {"hd": ["acme.com"]}}``), which is what a community
    narrowing a connection compares against.

    ``token_version`` and ``expires_in`` are for the tests about a credential
    that is no longer good: one minted before a version bump, and one whose
    lifetime has run out. Both default to a token that works.

    Example:
        headers = {"Authorization": f"Bearer {get_auth_token(test_user)}"}
        response = await client.get("/api/v1/me", headers=headers)
    """
    subject = getattr(user, AUTH_SUBJECT_ATTR, None)
    if subject is None:
        raise RuntimeError(
            f"user {user.id} has no {AUTH_SUBJECT_ATTR}: build accounts with "
            "create_user, which mints one the way registration does"
        )
    token, _ = mint_access_token(
        subject=subject,
        token_version=token_version
        if token_version is not None
        else user.token_version,
        session_id=session_id or uuid.uuid4(),
        amr=amr if amr is not None else ["pwd"],
        satisfied_providers=satisfied_providers
        if satisfied_providers is not None
        else [],
        provider_auth={
            str(pid): {"claims": {k: list(v) for k, v in claims.items()}}
            for pid, claims in (asserted_claims or {}).items()
        }
        or None,
        expires_in=expires_in,
    )
    return token


def get_auth_headers(user: User) -> dict[str, str]:
    """
    Get authorization headers for API requests.

    Args:
        user: User to authenticate as

    Returns:
        Dictionary with Authorization header

    Example:
        headers = get_auth_headers(test_user)
        response = await client.get("/api/v1/me", headers=headers)
    """
    token = get_auth_token(user)
    return {"Authorization": f"Bearer {token}"}


async def signed_in_headers(
    session: AsyncSession, user: User, *, amr: list[str] | None = None
) -> dict[str, str]:
    """Authorization headers naming a real ``auth_sessions`` row, as a signed-in
    app's do — for what is tied to the sign-in behind a request, such as a
    registered push token. ``amr`` is how the sign-in was proved; a passkey's
    (``["hwk"]``) makes a change to the account at once rather than holding it."""
    from app.services.auth import sessions as session_service

    user_id = user.id
    amr = amr or ["pwd"]
    issued = await session_service.create_session(
        session, user_id=user_id, amr=amr, satisfied_providers=[]
    )
    session_id = issued.session.id
    await session.commit()
    return {
        "Authorization": f"Bearer {get_auth_token(user, session_id=session_id, amr=amr)}"
    }


async def create_initiative(
    session: AsyncSession,
    guild: Guild,
    creator: User,
    commit: bool = True,
    member_tool_access: bool = True,
    **overrides: Any,
) -> Initiative:
    """
    Create a test initiative with sensible defaults.

    The built-in ``member`` role is given every tool's view permission, because
    the ordinary member this factory stands for is somebody the sharing picker
    would offer — it lists only people whose role already lets them use the
    tool. Product defaults are narrower (an opt-in tool is managers-only until
    a role is given it), so a test about sharing would otherwise be quietly a
    test about roles too, and would fail for the wrong reason.

    Pass ``member_tool_access=False`` for a test that is about the role gate
    itself; ``grant_role_permission`` sets one key either way.

    Args:
        session: Database session
        guild: Guild the initiative belongs to
        creator: User who creates the initiative (will become project manager)
        commit: Whether to commit the transaction (default True)
        member_tool_access: Whether the built-in member role may view each tool
        **overrides: Override any default field values

    Returns:
        Created Initiative instance

    Example:
        initiative = await create_initiative(session, guild, user, name="Test Initiative")
    """
    await route_session_to_guild(session, guild.id)

    from app.core.tools import Tool as _Tool

    defaults: dict[str, Any] = {
        "name": f"Test Initiative {datetime.now(timezone.utc).timestamp()}",
        "description": "A test initiative",
        # Every tool the initiative can switch on, switched on — derived from
        # the enum, so a new tool is usable the day it exists. A test about a
        # tool being OFF says so by overriding its own switch.
        **{
            tool.view_permission: True
            for tool in _Tool
            if tool.view_permission in Initiative.model_fields
        },
    }

    initiative_data = {**defaults, **overrides}
    initiative = Initiative(**initiative_data)
    session.add(initiative)

    if commit:
        await session.flush()

        # Create built-in roles (moderator + PM + member)
        builtin_roles = await create_builtin_roles(session, initiative_id=initiative.id)
        pm_role = builtin_roles["project_manager"]
        member_role = builtin_roles["member"]

        if member_tool_access:
            from sqlalchemy import update as sa_update

            from app.core.tools import Tool as _Tool
            from app.models.tenant.initiative import InitiativeRule

            await session.exec(
                sa_update(InitiativeRule)
                .where(
                    InitiativeRule.initiative_role_id == member_role.id,
                    InitiativeRule.key.in_([tool.view_permission for tool in _Tool]),
                )
                .values(enabled=True)
            )

        # Add creator as project manager with proper role_id
        membership = InitiativeMember(
            initiative_id=initiative.id,
            user_id=creator.id,
            role_id=pm_role.id,
        )
        session.add(membership)
        await session.commit()
        await session.refresh(initiative)

    return initiative


async def create_project(
    session: AsyncSession,
    initiative: Initiative,
    owner: User,
    commit: bool = True,
    **overrides: Any,
) -> Project:
    """
    Create a test project with sensible defaults.

    Args:
        session: Database session
        initiative: Initiative the project belongs to
        owner: User who owns the project
        commit: Whether to commit the transaction (default True)
        **overrides: Override any default field values

    Returns:
        Created Project instance

    Example:
        project = await create_project(session, initiative, user, name="Test Project")
    """
    await route_session_to_guild(session, guild_of(initiative))

    defaults = {
        "name": f"Test Project {datetime.now(timezone.utc).timestamp()}",
        "description": "A test project",
        "initiative_id": initiative.id,
        # Author and owner are different facts that happen to be the same person
        # for a freshly made project: the column below records who made it, the
        # grant further down records who owns it.
        "created_by": owner.id,
    }

    project_data = {**defaults, **overrides}
    project = Project(**project_data)
    session.add(project)

    if commit:
        await session.commit()
        await session.refresh(project)

        # The owner grant IS the ownership — projects carry no owner column.
        await create_resource_grant(
            session, project, level=ResourceAccessLevel.owner, user=owner
        )
        # Every project has its task types from the moment it is made.
        await ensure_default_types(session, project.id, locale="en")
        await session.commit()

    return project


async def create_resource_grant(
    session: AsyncSession,
    resource: Any,
    *,
    level: ResourceAccessLevel = ResourceAccessLevel.read,
    user: User | None = None,
    role_id: int | None = None,
    all_initiative_members: bool = False,
    plugin_install_id: int | None = None,
    commit: bool = True,
) -> ResourceGrant:
    """Share a tool's row: ``level`` for ``user``, for an initiative role, for
    every member of its initiative, or for an installed plug-in — exactly one."""
    await route_session_to_guild(session, guild_of(resource))
    grant = ResourceGrant(
        resource_type=tool_for_row(resource),
        resource_id=resource.id,
        user_id=user.id if user is not None else None,
        role_id=role_id,
        all_initiative_members=all_initiative_members,
        plugin_install_id=plugin_install_id,
        level=level,
        initiative_id=resource.initiative_id,
    )
    session.add(grant)
    if commit:
        await session.commit()
    return grant


async def strip_non_owner_grants(
    session: AsyncSession, resource: Any, owner_id: int
) -> None:
    """Remove every grant on a tool's row except ``owner_id``'s own, so the row
    reaches nobody else. Role and all-member grants carry a NULL ``user_id``,
    hence ``is_distinct_from`` rather than ``!=``."""
    await route_session_to_guild(session, guild_of(resource))
    await session.exec(
        sa_delete(ResourceGrant).where(
            ResourceGrant.resource_type == tool_for_row(resource),
            ResourceGrant.resource_id == resource.id,
            ResourceGrant.user_id.is_distinct_from(owner_id),
        )
    )
    await session.commit()


async def create_task(
    session: AsyncSession,
    project: Project,
    *,
    title: str | None = None,
    status_category: TaskStatusCategory = TaskStatusCategory.todo,
    assignees: list[User] | None = None,
    commit: bool = True,
    **overrides: Any,
) -> Task:
    """Create a test task (guild-scoped), with a status of the requested
    category and optional assignees.

    The project gets its default statuses the way the service seeds them, and
    the task takes the first of the requested category; a category the project
    has no status for gets one. Pass ``status_category=TaskStatusCategory.done``
    and ``assignees=[user]`` to build a completed, assigned task (e.g. for stats).
    """
    await route_session_to_guild(session, guild_of(project))

    statuses = await ensure_default_statuses(session, project.id, locale="en")
    status = next((s for s in statuses if s.category == status_category), None)
    if status is None:
        status = await create_task_status(
            session, project, category=status_category, commit=False
        )
        await session.flush()

    types = await ensure_default_types(session, project.id, locale="en")
    defaults: dict[str, Any] = {
        "title": title or f"Test Task {datetime.now(timezone.utc).timestamp()}",
        "project_id": project.id,
        "task_status_id": status.id,
        "task_type_id": next(t for t in types if t.is_default).id,
        "priority": TaskPriority.medium,
    }
    task = Task(**{**defaults, **overrides})
    # Match what the endpoints do, so a factory-built done task is a valid one:
    # done-ness and completed_at always agree. A ``completed_at`` override on a
    # done task survives (letting a test date a completion), and one on a task
    # that isn't done is dropped rather than persisted as an impossible row.
    sync_completed_at(task, status.category, now=datetime.now(timezone.utc))
    session.add(task)
    if commit:
        await session.commit()
        await session.refresh(task)

    for user in assignees or []:
        session.add(
            TaskAssignee(
                task_id=task.id,
                user_id=user.id,
            )
        )
    if commit and assignees:
        await session.commit()

    return task


async def create_queue(
    session: AsyncSession,
    initiative: Initiative,
    creator: User,
    commit: bool = True,
    **overrides: Any,
) -> Queue:
    """
    Create a test queue with sensible defaults.

    Args:
        session: Database session
        initiative: Initiative the queue belongs to
        creator: User who creates the queue
        commit: Whether to commit the transaction (default True)
        **overrides: Override any default field values

    Returns:
        Created Queue instance
    """
    await route_session_to_guild(session, guild_of(initiative))

    defaults = {
        "name": f"Test Queue {datetime.now(timezone.utc).timestamp()}",
        "description": "A test queue",
        "initiative_id": initiative.id,
        "created_by": creator.id,
    }

    queue_data = {**defaults, **overrides}
    queue = Queue(**queue_data)
    session.add(queue)

    if commit:
        await session.commit()
        await session.refresh(queue)

        await create_resource_grant(
            session, queue, level=ResourceAccessLevel.owner, user=creator
        )

    return queue


async def create_queue_item(
    session: AsyncSession,
    queue: Queue,
    commit: bool = True,
    **overrides: Any,
) -> QueueItem:
    """
    Create a test queue item with sensible defaults.

    Args:
        session: Database session
        queue: Queue the item belongs to
        commit: Whether to commit the transaction (default True)
        **overrides: Override any default field values

    Returns:
        Created QueueItem instance
    """
    await route_session_to_guild(session, guild_of(queue))

    defaults = {
        "queue_id": queue.id,
        "label": f"Item {datetime.now(timezone.utc).timestamp()}",
        "position": 0,
        "is_visible": True,
    }

    item_data = {**defaults, **overrides}
    item = QueueItem(**item_data)
    session.add(item)

    if commit:
        await session.commit()
        await session.refresh(item)

    return item


async def create_initiative_member(
    session: AsyncSession,
    initiative: Initiative,
    user: User,
    role_name: str = "member",
    commit: bool = True,
) -> InitiativeMember:
    """
    Create an initiative member with proper role_id.

    Args:
        session: Database session
        initiative: Initiative to add user to
        user: User to add
        role_name: Role name ("project_manager" or "member")
        commit: Whether to commit the transaction

    Returns:
        Created InitiativeMember instance
    """
    from app.models.tenant.initiative import InitiativeRoleModel
    from sqlmodel import select

    await route_session_to_guild(session, guild_of(initiative))

    # Find the matching role for this initiative
    stmt = select(InitiativeRoleModel).where(
        InitiativeRoleModel.initiative_id == initiative.id,
        InitiativeRoleModel.name == role_name,
    )
    result = await session.exec(stmt)
    role = result.one_or_none()
    if role is None:
        raise ValueError(
            f"Role '{role_name}' not found for initiative {initiative.id}. "
            "Ensure builtin roles exist (use create_initiative factory)."
        )

    membership = InitiativeMember(
        initiative_id=initiative.id,
        user_id=user.id,
        role_id=role.id,
    )
    session.add(membership)

    if commit:
        await session.commit()

    return membership


async def grant_role_permission(
    session: AsyncSession,
    initiative: Initiative,
    permission_key: str,
    *,
    role_name: str = "member",
    enabled: bool = True,
) -> None:
    """Set one initiative-role permission — gate 3, for a test that needs it.

    A built-in ``member`` role holds the documented defaults: it may view the
    two core tools and nothing else. Since the initiative-role gate is enforced
    by the tables' policies, a test that shares an opt-in tool with a plain
    member has to say that their role may engage that tool, exactly as an
    initiative's settings screen would.
    """
    from app.models.tenant.initiative import (
        InitiativeRoleModel,
        InitiativeRule,
    )
    from sqlmodel import select

    await route_session_to_guild(session, guild_of(initiative))
    role = (
        await session.exec(
            select(InitiativeRoleModel).where(
                InitiativeRoleModel.initiative_id == initiative.id,
                InitiativeRoleModel.name == role_name,
            )
        )
    ).one()
    existing = (
        await session.exec(
            select(InitiativeRule).where(
                InitiativeRule.initiative_role_id == role.id,
                InitiativeRule.key == permission_key,
            )
        )
    ).one_or_none()
    if existing is None:
        session.add(
            InitiativeRule(
                initiative_id=initiative.id,
                initiative_role_id=role.id,
                key=permission_key,
                enabled=enabled,
            )
        )
    else:
        existing.enabled = enabled
        session.add(existing)
    await session.commit()


async def create_property_definition(
    session: AsyncSession,
    initiative: Initiative | None,
    *,
    name: str | None = None,
    type: MetadataType = MetadataType.text,
    options: list[dict] | None = None,
    color: str | None = None,
    position: float = 0.0,
    project: Project | None = None,
    collection: Collection | None = None,
    plugin: GuildPlugin | None = None,
    key: str | None = None,
    commit: bool = True,
    **overrides: Any,
) -> MetadataDefinition:
    """
    Create a test metadata definition with sensible defaults.

    Auto-generates a unique name if not provided. When ``type`` is a
    select/multi_select and ``options`` is None, seeds a default option
    list so the definition is valid; money is in US dollars. With
    ``project`` or ``collection``, it is that project's or collection's
    metadata. With ``plugin`` (and no ``initiative``), it is the install's
    metadata under ``key``, named by it; ``list`` and ``shown_on`` go in
    ``overrides``.

    Args:
        session: Database session
        initiative: Initiative the definition belongs to
        name: Property name (auto-generated if None)
        type: Property type (default: text)
        options: Option list for select/multi_select types
        color: Optional hex color
        position: Sort position (default: 0.0)
        commit: Whether to commit the transaction (default True)
        **overrides: Override any default field values

    Returns:
        Created MetadataDefinition instance
    """
    await route_session_to_guild(session, guild_of(initiative or plugin))

    if name is None:
        name = key or f"Prop {datetime.now(timezone.utc).timestamp()}"

    if type in {MetadataType.select, MetadataType.multi_select} and options is None:
        options = [
            {"value": "a", "label": "A"},
            {"value": "b", "label": "B"},
        ]
    elif type not in {MetadataType.select, MetadataType.multi_select}:
        # Non-select types don't store options.
        options = None

    defaults = {
        "initiative_id": initiative.id if initiative is not None else None,
        "project_id": project.id if project is not None else None,
        "collection_id": collection.id if collection is not None else None,
        "install_id": plugin.id if plugin is not None else None,
        "key": key,
        "name": name,
        "type": type,
        "position": position,
        "color": color,
        "options": options,
        "currency": "USD" if type is MetadataType.currency else None,
    }

    data = {**defaults, **overrides}
    definition = MetadataDefinition(**data)
    session.add(definition)

    if commit:
        await session.commit()
        await session.refresh(definition)

    return definition


async def create_property_value(
    session: AsyncSession,
    entity: Any,
    definition: MetadataDefinition,
    *,
    commit: bool = True,
    **value_kwargs: Any,
) -> MetadataValue:
    """
    Attach a typed metadata value to any tool or sub-tool row.

    Accepts any of ``value_text``, ``value_number``, ``value_boolean``,
    ``value_date``, ``value_datetime``, ``value_user_id``, ``value_json``,
    and a plug-in value's ``ref`` and ``state``.

    Args:
        session: Database session
        entity: The row to attach the value to (a task, a file, a queue, …)
        definition: MetadataDefinition the value references
        commit: Whether to commit the transaction (default True)
        **value_kwargs: Typed column values

    Returns:
        Created MetadataValue instance
    """
    from app.services.tenant.metadata import link_for

    await route_session_to_guild(session, guild_of(entity))

    row = MetadataValue(
        entity_type=link_for(entity).target,
        entity_id=entity.id,
        property_id=definition.id,
        **value_kwargs,
    )
    session.add(row)

    if commit:
        await session.commit()

    return row


async def create_calendar(
    session: AsyncSession,
    initiative: Initiative,
    creator: User,
    *,
    name: str | None = None,
    commit: bool = True,
    **overrides: Any,
) -> Calendar:
    """Create a test calendar with sensible defaults.

    Mirrors the create endpoint's default sharing: the creator owns it and
    every initiative member can read it. The initiative is expected to be
    calendars-enabled — callers that need to test the feature flag should
    toggle that on the passed-in ``initiative``.
    """
    await route_session_to_guild(session, guild_of(initiative))

    defaults = {
        "initiative_id": initiative.id,
        "created_by": creator.id,
        "name": name or f"Calendar {datetime.now(timezone.utc).timestamp()}",
    }

    data = {**defaults, **overrides}
    calendar = Calendar(**data)
    session.add(calendar)

    if commit:
        await session.commit()
        await session.refresh(calendar)

        await create_resource_grant(
            session,
            calendar,
            level=ResourceAccessLevel.owner,
            user=creator,
            commit=False,
        )
        await create_resource_grant(session, calendar, all_initiative_members=True)

    return calendar


async def create_guild_calendar(
    session: AsyncSession,
    guild: Guild,
    creator: User,
    *,
    name: str | None = None,
    shared_with_everyone: bool = True,
    plugin: GuildPlugin | None = None,
    **overrides: Any,
) -> Calendar:
    """A guild calendar — the one the calendar plug-in installs.

    Belongs to no initiative, which is the whole of what makes it different: it
    holds its own events and reaches into nothing. Given ``plugin``, it is what
    ``guild_plugins.create_plugin_artifacts`` builds: owned by that install. Without
    one, ``creator`` owns it.
    """
    await route_session_to_guild(session, guild.id)

    calendar = Calendar(
        **{
            "initiative_id": None,
            "created_by": creator.id,
            "name": name or "Community calendar",
            **overrides,
        }
    )
    session.add(calendar)
    await session.commit()
    await session.refresh(calendar)

    await create_resource_grant(
        session,
        calendar,
        level=ResourceAccessLevel.owner,
        user=creator if plugin is None else None,
        plugin_install_id=plugin.id if plugin is not None else None,
        commit=False,
    )
    if shared_with_everyone:
        # At guild scope the everyone grant reads as every member of the guild.
        await create_resource_grant(
            session, calendar, all_initiative_members=True, commit=False
        )
    await session.commit()
    return calendar


async def create_guild_plugin(
    session: AsyncSession,
    guild: Guild,
    creator: User,
    *,
    definition: dict[str, Any],
    listing_uid: str = "TESTAPP0000001",
    listing_version: str = "1.0.0",
    name: str = "Test plug-in",
    secrets: dict[str, Any] | None = None,
    **overrides: Any,
) -> GuildPlugin:
    """An installed plug-in, written straight into the guild's schema.

    ``secrets`` is its secret values, ``{connection_id: {key: ciphertext}}``,
    stored in ``guild_plugin_secrets``. An assigned setting it holds no value
    for is given one, as an install's is.

    Deliberately not routed through the install endpoint. A ``service`` plug-in's
    definition is publishable and storable today but the install path does not
    mount one yet (``GUILD_INSTALLABLE_PLUGIN_KINDS``), and the configuration and
    connection machinery it carries needs an install to exist to be exercised
    at all. This is that install: the same row the endpoint will write once the
    kind is admitted, so the tests hold the real endpoints rather than a mock.
    """
    await route_session_to_guild(session, guild.id)

    plugin = GuildPlugin(
        **{
            "listing_uid": listing_uid,
            "listing_version": listing_version,
            "plugin_kind": definition.get("plugin_kind", "service"),
            "name": name,
            "definition": definition,
            "created_by": creator.id,
            **overrides,
        }
    )
    session.add(plugin)
    await session.commit()
    if secrets:
        session.add(GuildPluginSecret(install_id=plugin.id, secrets=secrets))
        await session.commit()
    await session.refresh(plugin)
    await plugin_installs.record(guild.id, plugin)
    await guild_plugins_service.assign_settings(session, plugin, guild_id=guild.id)
    await plugin_schedules.reconcile(guild.id, plugin.id, plugin.definition)
    return plugin


async def create_plugin_user_connection(
    session: AsyncSession,
    plugin: GuildPlugin,
    user: User,
    *,
    connection_id: str = "github",
    secrets: dict[str, Any] | None = None,
    **overrides: Any,
) -> GuildPluginUserConnection:
    """A member's credential for one of ``plugin``'s connections, as a
    completed flow leaves it. ``secrets`` is what it holds, ``{key:
    ciphertext}``, kept beside it."""
    await route_session_to_guild(session, guild_of(plugin))
    row = GuildPluginUserConnection(
        **{
            "plugin_id": plugin.id,
            "connection_id": connection_id,
            "user_id": user.id,
            "connection_ref": mint_connection_ref(),
            "status": "connected",
            **overrides,
        }
    )
    session.add(row)
    await session.commit()
    if secrets:
        session.add(PluginConnectionSecret(connection_row_id=row.id, secrets=secrets))
        await session.commit()
    await session.refresh(row)
    return row


_TEST_PLUGIN_KEY = ed25519.Ed25519PrivateKey.generate()


def sample_plugin_jwks(kid: str = "tests-plugin-key") -> dict[str, Any]:
    """A public key set for a test registration: one Ed25519 key under ``kid``.

    A registration is live only with a key set, so every test registration
    carries one unless the test says otherwise.
    """
    entry = json.loads(OKPAlgorithm.to_jwk(_TEST_PLUGIN_KEY.public_key()))
    entry["kid"] = kid
    return {"keys": [entry]}


async def create_publisher(
    session: AsyncSession,
    *,
    prefix: str = "tests",
    display_name: str | None = None,
    verified: bool = True,
    enabled: bool = True,
    source: str = "operator",
) -> Publisher:
    """The publisher for ``prefix``: the existing row, or a new one."""
    row = (
        await session.exec(select(Publisher).where(Publisher.prefix == prefix))
    ).first()
    if row is None:
        row = Publisher(
            prefix=prefix,
            display_name=display_name or prefix,
            verified=verified,
            enabled=enabled,
            source=source,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        invalidate_registrations()
    return row


def sealed_vendor_values(values: dict[str, str]) -> dict[str, str]:
    """Vendor values as a registration stores them: one ciphertext per key."""
    from app.core.encryption import SALT_PLUGIN_VENDOR, encrypt_field

    return {
        key: encrypt_field(value, SALT_PLUGIN_VENDOR) for key, value in values.items()
    }


async def create_plugin_service_registration(
    session: AsyncSession,
    *,
    public_id: str = "tests.plugin-service",
    base_url: str | None = "https://app.example.test",
    listing_uid: str | None = None,
    allowed_origins: list[str] | None = None,
    mandatory: bool = False,
    enabled: bool = True,
    jwks: dict[str, Any] | None = None,
    **overrides: Any,
) -> PluginServiceRegistration:
    """A deployment-level registration, written straight into ``public``.

    Its publisher is the row for its ``public_id`` prefix, made when there is
    none. It carries :func:`sample_plugin_jwks` unless ``jwks`` is given, so it is
    live unless the test switches it or its publisher off; pass
    ``jwks={}`` for one with no key set.

    The in-process snapshot is dropped afterwards, so the very next read sees
    this registration rather than whatever a previous test left cached.
    """
    publisher = await create_publisher(session, prefix=publisher_prefix(public_id))
    row = PluginServiceRegistration(
        **{
            "public_id": public_id,
            "listing_uid": listing_uid,
            "publisher_id": publisher.id,
            "base_url": base_url,
            "allowed_origins": allowed_origins
            if allowed_origins is not None
            else [base_url],
            "jwks": (jwks or None) if jwks is not None else sample_plugin_jwks(),
            "mandatory": mandatory,
            "enabled": enabled,
            **overrides,
        }
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    invalidate_registrations()
    return row


def marketplace_uid(label: str) -> str:
    """A valid catalog uid from a readable label.

    Crockford base32 leaves out I, L, O and U so a code can be transcribed by
    hand — which makes most words unusable verbatim. This drops the letters the
    alphabet does not have and pads to length, so a test can say what a listing
    is instead of carrying an opaque literal.
    """
    kept = [c for c in label.upper() if c in UID_ALPHABET]
    return "".join(kept)[:UID_LENGTH].ljust(UID_LENGTH, "0")


async def create_marketplace_listing(
    session: AsyncSession,
    *,
    uid: str = "TEST0000000001",
    public_id: str = "test.listing",
    kind: str = "dashboard",
    version: str = "1.0.0",
    definition: dict[str, Any] | None = None,
    min_app_version: str | None = None,
    available: bool = True,
    commit: bool = True,
    **overrides: Any,
) -> MarketplaceListing:
    """A catalog listing with one published version.

    Built through the real upsert, so a test listing is held to the same
    validation a shipped or downloaded one is — a definition this build cannot
    render fails here rather than in the assertion.
    """
    manifest = {
        "uid": uid,
        "public_id": public_id,
        "kind": kind,
        "name": overrides.pop("name", "Test listing"),
        # Required on every ingestion path, so a test listing carries one too.
        "publisher": overrides.pop("publisher", "Tests"),
        "description": overrides.pop("description", "A listing for tests."),
        "avatar_url": overrides.pop("avatar_url", "/marketplace/test.svg"),
        "version": version,
        "min_app_version": min_app_version,
        "definition": definition
        if definition is not None
        else {
            "widgets": [
                {
                    "id": "w1",
                    "type": "stat",
                    "binding": {
                        "source": "query",
                        "sql": "SELECT count(*) AS n FROM tasks",
                    },
                }
            ]
        },
        **overrides,
    }
    listing = await marketplace_catalog.upsert_listing(
        session, manifest, source="builtin"
    )
    if not available:
        listing.available = False
        session.add(listing)
    if commit:
        await session.commit()
        await session.refresh(listing)
    return listing


async def create_listing_with_terms(
    session: AsyncSession,
    *,
    uid: str,
    public_id: str,
    access: str,
    mandatory: bool = False,
    meters: Sequence[str] = (),
    **overrides: Any,
) -> MarketplaceListing:
    """A plug-in listing as the registry carries one a package names terms for.

    Published like any listing, then given the registry's source and the
    terms a refresh writes from the ``package`` role. A test honouring them
    also patches ``tuf_registry.configured_root_is_builtin`` to answer true.
    """
    overrides.setdefault(
        "definition",
        {"plugin_kind": "service", "service": {"public_id": public_id}},
    )
    listing = await create_marketplace_listing(
        session, uid=uid, public_id=public_id, kind="plugin", commit=False, **overrides
    )
    listing.source = "registry"
    listing.access = access
    listing.mandatory = mandatory
    listing.meters = list(meters)
    session.add(listing)
    await session.commit()
    await session.refresh(listing)
    return listing


#: The key test entitlement statements are signed with. Nothing here verifies
#: the signature (the plug-in does), so one key serves every test.
_STATEMENT_KEY = ed25519.Ed25519PrivateKey.generate()
#: The public half of the key :func:`entitlement_statement` signs with: what
#: a test sets ``BILLING_STATEMENT_PUBLIC_KEY_PEM`` to.
STATEMENT_PUBLIC_PEM = (
    _STATEMENT_KEY.public_key()
    .public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    .decode()
)


def entitlement_statement(
    *,
    community_ref: str,
    listing_uid: str,
    version: int,
    values: dict[str, Any],
    header: dict[str, Any] | None = None,
    drop: Sequence[str] = (),
    **claims: Any,
) -> str:
    """A compact JWS entitlement statement, as the issuer signs one.

    ``header`` replaces header fields, ``claims`` replaces or adds claims, and
    ``drop`` removes claims, so a test can build each malformed shape.
    """

    def segment(value: dict[str, Any]) -> str:
        raw = json.dumps(value, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    body: dict[str, Any] = {
        "iss": "initiative-billing",
        "listing_uid": listing_uid,
        "community_ref": community_ref,
        "version": version,
        "values": values,
        "iat": int(datetime.now(timezone.utc).timestamp()),
        **claims,
    }
    for name in drop:
        body.pop(name, None)
    signing_input = ".".join(
        [
            segment(
                {
                    "alg": "EdDSA",
                    "typ": "initiative-entitlement+jwt",
                    "kid": "test-statement-key",
                    **(header or {}),
                }
            ),
            segment(body),
        ]
    )
    signature = _STATEMENT_KEY.sign(signing_input.encode())
    return (
        f"{signing_input}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"
    )


async def create_profile_pack(
    session: AsyncSession,
    *,
    uid: str = "TESTPACK000001",
    public_id: str = "test.pack",
    slug: str = "test",
    commit: bool = True,
    **overrides: Any,
) -> MarketplaceListing:
    """A profile-pack listing granting one decoration of each slot.

    ``slug`` namespaces the decoration ids, the way a real pack's do, so two
    packs in one test never collide. Goes through the real upsert, so the
    definition is held to the same validator a published pack would be.
    """
    return await create_marketplace_listing(
        session,
        uid=uid,
        public_id=public_id,
        kind="profile_pack",
        definition={
            "schema_version": 1,
            "kind": "profile_pack",
            "decorations": [
                {"id": f"{slug}.banner", "slot": "banner", "name": "A banner"},
                {"id": f"{slug}.frame", "slot": "frame", "name": "A frame"},
                {"id": f"{slug}.trophy", "slot": "trophy", "name": "A trophy"},
            ],
        },
        commit=commit,
        **overrides,
    )


async def create_dashboard(
    session: AsyncSession,
    initiative: Initiative,
    creator: User,
    *,
    name: str | None = None,
    definition: dict[str, Any] | None = None,
    commit: bool = True,
    **overrides: Any,
) -> Dashboard:
    """Create a test dashboard with sensible defaults.

    Mirrors the create endpoint's default sharing: the creator owns it and
    every initiative member can read it. ``definition`` defaults to a single
    KPI widget so the row carries a realistic, already-normalized canvas; the
    initiative is expected to be dashboards-enabled.
    """
    await route_session_to_guild(session, guild_of(initiative))

    defaults = {
        "initiative_id": initiative.id,
        "created_by": creator.id,
        "name": name or f"Dashboard {datetime.now(timezone.utc).timestamp()}",
        "definition": definition
        if definition is not None
        else normalize_dashboard_definition(
            {
                "widgets": [
                    {
                        "id": "w1",
                        "type": "stat",
                        "binding": {
                            "source": "query",
                            "sql": "SELECT count(*) AS n FROM tasks",
                        },
                    }
                ]
            }
        ),
        "config": {"widgets": {}},
    }

    data = {**defaults, **overrides}
    dashboard = Dashboard(**data)
    session.add(dashboard)

    if commit:
        await session.commit()
        await session.refresh(dashboard)

        await create_resource_grant(
            session,
            dashboard,
            level=ResourceAccessLevel.owner,
            user=creator,
            commit=False,
        )
        await create_resource_grant(session, dashboard, all_initiative_members=True)

    return dashboard


#: A collaboration state as the editor's binding writes one: a paragraph,
#: ``Hi `` and a mention of user 42 holding the name ``Ada``, the way an editor
#: from before mentions stopped storing names wrote it. Made with ``yjs``.
MENTIONING_YJS_STATE = base64.b64decode(
    "AQeWo/S3AwAHAQRyb290BigAlqP0twMABl9fdHlwZQF3CXBhcmFncmFwaAQAlqP0twMAA0hp"
    "IIeWo/S3AwQDB21lbnRpb24oAJaj9LcDBQZfX3R5cGUBdwdtZW50aW9uKACWo/S3AwUJX19t"
    "ZW50aW9uAXcDQWRhKACWo/S3AwUPX19tZW50aW9uVXNlcklkAX0qAA=="
)


def lexical_body(
    text: str, *, mentioning: int | str | None = None, name: str = ""
) -> dict[str, Any]:
    """The smallest valid Lexical editor state holding one paragraph.

    Spelled out here rather than in each test so a post body in a test is the
    same shape the editor actually saves — which is what the search extractor
    and the excerpt walk both read. ``mentioning`` ends the paragraph with a
    mention of that person, written as ``name``.
    """
    body = {
        "root": {
            "type": "root",
            "format": "",
            "indent": 0,
            "version": 1,
            "direction": "ltr",
            "children": [
                {
                    "type": "paragraph",
                    "format": "",
                    "indent": 0,
                    "version": 1,
                    "direction": "ltr",
                    "children": [
                        {
                            "type": "text",
                            "text": text,
                            "format": 0,
                            "style": "",
                            "mode": "normal",
                            "detail": 0,
                            "version": 1,
                        }
                    ],
                }
            ],
        }
    }
    if mentioning is not None:
        body["root"]["children"][0]["children"].append(
            {
                "type": "mention",
                "mentionName": name,
                "mentionUserId": mentioning,
                "text": name,
                "version": 1,
            }
        )
    return body


async def create_post(
    session: AsyncSession,
    initiative: Initiative,
    creator: User,
    *,
    name: str | None = None,
    body: dict[str, Any] | None = None,
    commit: bool = True,
    **overrides: Any,
) -> Post:
    """Create a test post with sensible defaults.

    Mirrors the create endpoint's default sharing: the author owns it and every
    initiative member can read it, which is what posting to a board means. The
    initiative is expected to be posts-enabled.
    """
    await route_session_to_guild(session, guild_of(initiative))

    defaults = {
        "initiative_id": initiative.id,
        "created_by": creator.id,
        "name": name or f"Post {datetime.now(timezone.utc).timestamp()}",
        "body": body if body is not None else lexical_body("Notice body."),
        # Live by default, like a notice posted rather than scheduled. Pass
        # ``published_at=None`` with a ``scheduled_for`` to build a draft.
        "published_at": datetime.now(timezone.utc),
    }

    data = {**defaults, **overrides}
    post = Post(**data)
    session.add(post)

    if commit:
        await session.commit()
        await session.refresh(post)

        await create_resource_grant(
            session, post, level=ResourceAccessLevel.owner, user=creator, commit=False
        )
        await create_resource_grant(session, post, all_initiative_members=True)

    return post


async def create_post_poll(
    session: AsyncSession,
    post: Post,
    *,
    options: list[str] | None = None,
    commit: bool = True,
    **overrides: Any,
) -> PostPoll:
    """Give a test post a question. Two choices by default — the shortest poll
    that is still a poll — in the order they are given."""
    await route_session_to_guild(session, guild_of(post))

    defaults: dict[str, Any] = {
        "post_id": post.id,
        "question": "Which night works?",
    }
    poll = PostPoll(**{**defaults, **overrides})
    poll.options = [
        PostPollOption(position=index, text=text)
        for index, text in enumerate(options or ["Tuesday", "Thursday"])
    ]
    session.add(poll)

    if commit:
        await session.commit()
        # Re-read with the options attached: a plain refresh expires them, and
        # a test that then touched ``poll.options`` would lazy-load inside the
        # async session.
        poll = (
            await session.exec(
                select(PostPoll)
                .where(PostPoll.id == poll.id)
                .options(selectinload(PostPoll.options))
                .execution_options(populate_existing=True)
            )
        ).one()

    return poll


def png_bytes(
    width: int = 4, height: int = 4, rgb: tuple[int, int, int] = (200, 60, 60)
) -> bytes:
    """A valid flat-colour PNG, written by hand so a test picture needs no
    image library and is a few dozen bytes. What the upload endpoint's header
    check reads — signature, IHDR, dimensions — is all real."""
    import zlib

    raw = bytearray()
    for _ in range(height):
        raw.append(0)
        raw.extend(bytes(rgb) * width)

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            len(payload).to_bytes(4, "big")
            + kind
            + payload
            + zlib.crc32(kind + payload).to_bytes(4, "big")
        )

    header = (
        width.to_bytes(4, "big") + height.to_bytes(4, "big") + bytes((8, 2, 0, 0, 0))
    )
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


async def create_collection(
    session: AsyncSession,
    initiative: Initiative,
    creator: User,
    *,
    files: Sequence[File] = (),
    name: str | None = None,
    shape: str | None = None,
    commit: bool = True,
    **overrides: Any,
) -> Collection:
    """Create a test collection holding ``files``, each added by ``creator``,
    made as the ready-made ``shape`` of that key (its words in English) when
    one is named.

    A collection is seen through its files, so one made with none reads as
    absent to everyone but the community's admins.
    """
    await route_session_to_guild(session, guild_of(initiative))

    defaults = {
        "initiative_id": initiative.id,
        "created_by": creator.id,
        "name": name or f"Collection {datetime.now(timezone.utc).timestamp()}",
    }
    collection = Collection(**{**defaults, **overrides})
    session.add(collection)
    await session.flush()
    session.add_all(
        CollectionFile(
            collection_id=collection.id,
            file_id=file.id,
            initiative_id=initiative.id,
            added_by=creator.id,
        )
        for file in files
    )
    await session.flush()
    if shape is not None:
        from app.core.collection_shapes import SHAPES_BY_KEY
        from app.services.tenant.collections import apply_shape

        await apply_shape(session, collection, SHAPES_BY_KEY[shape], locale="en")
    if commit:
        await session.commit()
        await session.refresh(collection)
    return collection


async def create_calendar_event(
    session: AsyncSession,
    calendar: Calendar,
    creator: User,
    *,
    title: str | None = None,
    attendees: list[User] | None = None,
    commit: bool = True,
    **overrides: Any,
) -> CalendarEvent:
    """Create a test calendar event with sensible defaults, and optional
    attendees.

    Defaults to a one-hour event starting "now"; callers that care about
    the timing should override ``start_at`` / ``end_at``. Events carry no
    grants of their own — access derives from the parent ``calendar``.
    """
    await route_session_to_guild(session, guild_of(calendar))

    now = datetime.now(timezone.utc)
    defaults = {
        "calendar_id": calendar.id,
        "created_by": creator.id,
        "title": title or f"Event {now.timestamp()}",
        "start_at": now,
        "end_at": now + timedelta(hours=1),
        "all_day": False,
    }

    data = {**defaults, **overrides}
    event = CalendarEvent(**data)
    session.add(event)

    if commit:
        await session.commit()
        await session.refresh(event)
    elif attendees:
        await session.flush()

    for user in attendees or []:
        session.add(CalendarEventAttendee(calendar_event_id=event.id, user_id=user.id))
    if commit and attendees:
        await session.commit()

    return event


async def create_file(
    session: AsyncSession,
    initiative: Initiative,
    creator: User,
    *,
    name: str | None = None,
    commit: bool = True,
    **overrides: Any,
) -> File:
    """Create a test file with sensible defaults.

    Defaults to a ``lexical`` (editor) file with empty content and an
    owner grant for ``creator``, mirroring the create endpoint's DAC setup.
    File overrides (``file_url``, …) make its first version, as an upload does,
    typed ``application/pdf`` unless one is given; the file takes its type.
    """
    await route_session_to_guild(session, guild_of(initiative))

    stored = _file_overrides(overrides)
    if stored:
        stored.setdefault("file_content_type", "application/pdf")
    defaults = {
        "initiative_id": initiative.id,
        "name": name or f"Test File {datetime.now(timezone.utc).timestamp()}",
        "file_type": (
            type_of_media(stored["file_content_type"]) if stored else FileType.lexical
        ),
        "created_by": creator.id,
    }
    file = File(**{**defaults, **overrides})
    session.add(file)

    # The owner grant is part of the factory's contract in BOTH modes; with
    # commit=False it is flushed (id available) but left uncommitted with the
    # rest of the caller's transaction.
    await (session.commit() if commit else session.flush())
    if commit:
        # Every column, the deferred body included: tests read it off the row.
        await session.refresh(file, [c.key for c in File.__table__.columns])
    await create_resource_grant(
        session, file, level=ResourceAccessLevel.owner, user=creator, commit=commit
    )
    if stored:
        await file_versions.add_version(session, file, created_by=creator.id, **stored)
        await (session.commit() if commit else session.flush())

    return file


def _file_overrides(overrides: dict[str, Any]) -> dict[str, Any]:
    """Take a factory's file overrides out of ``overrides``: they describe the
    version it makes, not the row."""
    return {
        key: overrides.pop(key)
        for key in (
            "file_url",
            "file_content_type",
            "file_size",
            "original_filename",
        )
        if key in overrides
    }


async def create_comment(
    session: AsyncSession,
    author: User,
    *,
    task: Task | None = None,
    wiki_page: WikiPage | None = None,
    wiki: Wiki | None = None,
    file: File | None = None,
    project: Project | None = None,
    queue: Queue | None = None,
    counter_group: CounterGroup | None = None,
    calendar: Calendar | None = None,
    dashboard: Dashboard | None = None,
    post: Post | None = None,
    collection: Collection | None = None,
    content: str = "A test comment",
    commit: bool = True,
    **overrides: Any,
) -> Comment:
    """Create a comment on exactly one parent — any tool entity, or one of the
    content-level extras (a task, a wiki page, a collection)."""
    named = {
        "task": task,
        "wiki_page": wiki_page,
        "collection": collection,
        Tool.project.value: project,
        Tool.file.value: file,
        Tool.queue.value: queue,
        Tool.counter_group.value: counter_group,
        Tool.calendar.value: calendar,
        Tool.dashboard.value: dashboard,
        Tool.post.value: post,
        Tool.wiki.value: wiki,
    }
    # Keyed by the enum rather than by string literals, and checked against it:
    # a new tool that has no keyword here fails on the first test that comments
    # on one, naming the tool, instead of looking like a caller mistake.
    missing = [tool.value for tool in Tool if tool.value not in named]
    if missing:
        raise ValueError(f"create_comment has no parent keyword for: {missing}")
    provided = {f"{name}_id": row for name, row in named.items() if row is not None}
    if len(provided) != 1:
        raise ValueError("pass exactly one comment parent")
    column, parent = next(iter(provided.items()))
    await route_session_to_guild(session, guild_of(parent))

    defaults = {
        "content": content,
        "created_by": author.id,
        column: parent.id,
    }
    comment = Comment(**{**defaults, **overrides})
    session.add(comment)

    if commit:
        await session.commit()
        await session.refresh(comment)

    return comment


async def create_reaction(
    session: AsyncSession,
    user: User,
    *,
    comment: Comment,
    emoji: str = "\N{THUMBS UP SIGN}",
    commit: bool = True,
    **overrides: Any,
) -> Reaction:
    """Put one person's emoji on one comment.

    Takes the target as a typed keyword rather than a ``(type, id)`` pair so a
    second reactable kind adds a keyword here and nothing has to remember the
    string.
    """
    await route_session_to_guild(session, guild_of(comment))
    defaults = {
        "target_type": ReactionTarget.comment.value,
        "target_id": comment.id,
        "emoji": emoji,
        "created_by": user.id,
    }
    reaction = Reaction(**{**defaults, **overrides})
    session.add(reaction)

    if commit:
        await session.commit()
        await session.refresh(reaction)

    return reaction


async def create_tag(
    session: AsyncSession,
    guild: Guild,
    *,
    name: str | None = None,
    commit: bool = True,
    **overrides: Any,
) -> Tag:
    """Create a guild-scoped tag."""
    await route_session_to_guild(session, guild.id)

    defaults = {
        "name": name or f"tag-{datetime.now(timezone.utc).timestamp()}",
    }
    tag = Tag(**{**defaults, **overrides})
    session.add(tag)

    if commit:
        await session.commit()
        await session.refresh(tag)

    return tag


async def assign_tag(session, entity, tag, *, commit: bool = False):
    """Put a tag on something — the edge a tagging surface writes.

    The session is routed from the tag's own community first: a tenant write
    has to land in a schema, and the edge itself names no community.
    """
    from app.services.tenant import tags as tags_service

    await route_session_to_guild(session, guild_of(tag))
    row = tags_service.tag_edge(tags_service.spec_for(entity), entity.id, tag.id)
    session.add(row)
    if commit:
        await session.commit()
    return row


def checklist_items(*texts: str, done: bool = False) -> list[dict]:
    """A checklist for ``create_task(checklist=...)`` — one item per text."""
    return [
        {"id": mint_checklist_item_id(), "text": text, "done": done} for text in texts
    ]


async def create_task_status(
    session: AsyncSession,
    project: Project,
    *,
    name: str | None = None,
    category: TaskStatusCategory = TaskStatusCategory.todo,
    commit: bool = True,
    **overrides: Any,
) -> TaskStatus:
    """Create a task status for ``project`` (does not deduplicate; use
    ``create_task`` when you just need a task in a given category)."""
    await route_session_to_guild(session, guild_of(project))

    defaults = {
        "project_id": project.id,
        "name": name or category.value.replace("_", " ").title(),
        "category": category,
        "position": 0,
    }
    status = TaskStatus(**{**defaults, **overrides})
    session.add(status)

    if commit:
        await session.commit()
        await session.refresh(status)

    return status


async def create_counter_group(
    session: AsyncSession,
    initiative: Initiative,
    creator: User,
    *,
    name: str | None = None,
    commit: bool = True,
    **overrides: Any,
) -> CounterGroup:
    """Create a counter group with an owner grant for ``creator``."""
    await route_session_to_guild(session, guild_of(initiative))

    defaults = {
        "initiative_id": initiative.id,
        "name": name or f"Test Counters {datetime.now(timezone.utc).timestamp()}",
        "created_by": creator.id,
    }
    group = CounterGroup(**{**defaults, **overrides})
    session.add(group)

    if commit:
        await session.commit()
        await session.refresh(group)

        await create_resource_grant(
            session, group, level=ResourceAccessLevel.owner, user=creator
        )

    return group


async def create_counter(
    session: AsyncSession,
    group: CounterGroup,
    *,
    name: str | None = None,
    commit: bool = True,
    **overrides: Any,
) -> Counter:
    """Create a counter inside ``group``."""
    await route_session_to_guild(session, guild_of(group))

    defaults = {
        "counter_group_id": group.id,
        "name": name or f"Counter {datetime.now(timezone.utc).timestamp()}",
    }
    counter = Counter(**{**defaults, **overrides})
    session.add(counter)

    if commit:
        await session.commit()
        await session.refresh(counter)

    return counter


async def create_upload(
    session: AsyncSession,
    guild: Guild,
    uploader: User,
    *,
    filename: str | None = None,
    commit: bool = True,
    **overrides: Any,
) -> Upload:
    """Create an upload row (metadata only; writes no file to disk)."""
    await route_session_to_guild(session, guild.id)

    defaults = {
        "created_by": uploader.id,
        "filename": filename or f"file-{datetime.now(timezone.utc).timestamp()}.txt",
        "size_bytes": 1,
    }
    upload = Upload(**{**defaults, **overrides})
    session.add(upload)

    if commit:
        await session.commit()
        await session.refresh(upload)

    return upload


async def create_export_job(
    session: AsyncSession, guild: Guild, creator: User, **overrides: Any
) -> DataJob:
    """Create a task-list PDF export job, queued unless ``status`` says
    otherwise."""
    await route_session_to_guild(session, guild.id)
    defaults = {
        "direction": DataJobDirection.export,
        "created_by": creator.id,
        "source": "tasks",
        "template_id": "task-table",
        "format": "pdf",
    }
    job = DataJob(**{**defaults, **overrides})
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def create_import_job(
    session: AsyncSession, guild: Guild, creator: User, **overrides: Any
) -> DataJob:
    """Create a backup import job, queued unless ``status`` says otherwise."""
    await route_session_to_guild(session, guild.id)
    job = DataJob(
        **{
            "direction": DataJobDirection.import_,
            "created_by": creator.id,
            "source": "backup",
            **overrides,
        }
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def create_auth_provider(
    session: AsyncSession,
    commit: bool = True,
    **overrides: Any,
) -> AuthProvider:
    """Create an auth provider registry row. Every provider is the operator's;
    a community reaches one through ``create_guild_provider_connection``.

    Defaults to a login-ready OIDC row pointing at the test IdP constants
    (``app.testing.oidc``), so a fake-IdP flow verifies against it as-is.
    """
    from app.testing.oidc import CLIENT_ID as _TEST_CLIENT_ID, ISSUER as _TEST_ISSUER

    defaults = {
        "slug": "corp",
        "display_name": "Corp SSO",
        "kind": AuthProviderKind.oidc.value,
        "enabled": True,
        "issuer": _TEST_ISSUER,
        "client_id": _TEST_CLIENT_ID,
        "scopes": "openid email",
        "allow_jit": True,
    }
    provider = AuthProvider(**{**defaults, **overrides})
    session.add(provider)

    if commit:
        await session.commit()
        await session.refresh(provider)

    return provider


#: What :func:`create_guild_provider_connection` narrows on, and what
#: :func:`satisfied_claims_for` answers it with. Named rather than written
#: twice: a session only reaches a narrowed connection by asserting the value
#: it counts, so the two have to agree.
NARROWED_CLAIM = "hd"
NARROWED_VALUE = "example.com"


def satisfied_claims_for(*providers) -> dict:
    """What a session has to carry to satisfy connections these providers serve.

    Keyed by provider id and shaped as the gate reads it — a list, because the
    claim a provider asserts may name more than one value. The same shape both
    consumers take: ``get_auth_token(asserted_claims=...)`` for a credential,
    and ``set_rls_context(satisfied_claims=...)`` for a routed session, which
    serialises the integer keys to the strings the gate indexes by.
    """
    return {
        int(getattr(provider, "id", provider)): {NARROWED_CLAIM: [NARROWED_VALUE]}
        for provider in providers
    }


async def create_guild_provider_connection(
    session: AsyncSession,
    *,
    guild,
    provider: AuthProvider,
    commit: bool = True,
    **overrides: Any,
) -> GuildProviderConnection:
    """Connect a community to one of the operator's providers.

    Narrowed by default, because an enabled connection has to be: communities
    here are separate tenants, so a provider vouching for somebody is not the
    same as them belonging to one. Pass ``claim=None, claim_values=None`` with
    ``enabled=False`` for the row a community writes to decline the
    deployment's answer for a provider.

    Its narrowing is agreed by default too, so a connection this makes joins
    people on arrival where it says to. ``narrowing_approved_at=None`` is the
    state a community's own new connection starts in.
    """
    defaults = {
        "guild_id": guild.id,
        "provider_id": provider.id,
        "claim": NARROWED_CLAIM,
        "claim_values": [NARROWED_VALUE],
        "enabled": True,
        # Agreed, like the narrowing itself: this makes a connection that
        # works, so a test about what happens before somebody agrees says
        # ``narrowing_approved_at=None`` and means it.
        "narrowing_approved_at": datetime.now(timezone.utc),
    }
    connection = GuildProviderConnection(**{**defaults, **overrides})
    session.add(connection)
    if commit:
        await session.commit()
        await session.refresh(connection)
    return connection


async def create_guild_auth_policy(
    session: AsyncSession,
    guild: "Guild",
    provider: "AuthProvider | None" = None,
    *,
    commit: bool = True,
    guest: bool = False,
    methods: Iterable[LoginMethod] = (),
) -> SignInRequirement:
    """Make ``guild`` require a sign-in of its members or, with ``guest``, of
    its guests: through ``provider``, by ``methods``, or both.

    Connects the community to the provider first where it is not connected
    already: the endpoint refuses a requirement naming a provider the
    community does not count as its own, and the gate answers the same way, so
    a requirement without a connection is a state production cannot reach.
    """
    if provider is not None:
        connected = (
            await session.exec(
                select(GuildProviderConnection).where(
                    GuildProviderConnection.guild_id == guild.id,
                    GuildProviderConnection.provider_id == provider.id,
                )
            )
        ).first()
        if connected is None:
            await create_guild_provider_connection(
                session, guild=guild, provider=provider, commit=commit
            )
    requirement = SignInRequirement(
        "required", provider.id if provider else None, frozenset(methods)
    )
    await rules.put(
        session,
        "guest_auth_policy" if guest else "auth_policy",
        requirement,
        guild_id=guild.id,
    )
    if commit:
        await session.commit()
    return requirement


async def create_federated_identity(
    session: AsyncSession,
    user: User,
    *,
    subject: str | None = None,
    provider: "AuthProvider | None" = None,
    commit: bool = True,
    **overrides: Any,
) -> FederatedIdentity:
    """Link ``user`` to an auth provider (the platform row by default).

    Gets-or-creates the operator-global platform provider so tests can mark a
    user as SSO-linked without configuring OIDC.
    """
    if provider is None:
        provider = (
            await session.exec(
                select(AuthProvider).where(AuthProvider.slug == PLATFORM_OIDC_SLUG)
            )
        ).one_or_none()
        if provider is None:
            provider = AuthProvider(
                slug=PLATFORM_OIDC_SLUG,
                display_name="Test SSO",
                kind=AuthProviderKind.oidc.value,
                enabled=True,
                issuer="https://idp.test.example",
                client_id="test-client",
                allow_jit=True,
            )
            session.add(provider)
            await session.flush()

    defaults = {
        "user_id": user.id,
        "provider_id": provider.id,
        "subject": subject or f"test-sub-{user.id}",
        "email_verified": True,
    }
    identity = FederatedIdentity(**{**defaults, **overrides})
    session.add(identity)

    if commit:
        await session.commit()
        await session.refresh(identity)

    return identity


# --- generic tool construction ---------------------------------------------
#
async def create_wiki(
    session: AsyncSession,
    initiative: Initiative,
    creator: User,
    *,
    name: str | None = None,
    commit: bool = True,
    **overrides: Any,
) -> Wiki:
    """Create a test wiki with sensible defaults.

    Mirrors the create endpoint's default sharing: the creator owns it and
    every initiative member can read it. The initiative is expected to be
    wikis-enabled.
    """
    await route_session_to_guild(session, guild_of(initiative))

    defaults = {
        "initiative_id": initiative.id,
        "created_by": creator.id,
        "name": name or f"Wiki {datetime.now(timezone.utc).timestamp()}",
    }
    wiki = Wiki(**{**defaults, **overrides})
    session.add(wiki)

    if commit:
        await session.commit()
        await session.refresh(wiki)

        await create_resource_grant(
            session, wiki, level=ResourceAccessLevel.owner, user=creator, commit=False
        )
        await create_resource_grant(session, wiki, all_initiative_members=True)

    return wiki


async def create_wiki_page(
    session: AsyncSession,
    wiki: Wiki,
    creator: User,
    *,
    title: str | None = None,
    commit: bool = True,
    **overrides: Any,
) -> WikiPage:
    """Create a page in a wiki.

    Pass ``parent_page_id`` to file it under another page; without one it sits
    at the top of the wiki. What nests inside a page — its headings — is
    content, and lives in its body.
    """
    await route_session_to_guild(session, guild_of(wiki))

    stamp = datetime.now(timezone.utc).timestamp()
    page_title = title or f"Page {stamp}"
    defaults: dict[str, Any] = {
        "wiki_id": wiki.id,
        "created_by": creator.id,
        "title": page_title,
        "slug": slugify(page_title, fallback=f"page-{stamp}"),
    }
    page = WikiPage(**{**defaults, **overrides})
    session.add(page)

    if commit:
        await session.commit()
        await session.refresh(page)

    return page


# One arm per Tool, so a test that needs "an instance of every tool" derives it
# from the enum instead of restating the list. The completeness check runs at
# import time: a new Tool member fails here once, with a message naming it,
# rather than in each test that happens to enumerate tools.

TOOL_FACTORIES: dict[Tool, Any] = {
    Tool.project: create_project,
    Tool.file: create_file,
    Tool.queue: create_queue,
    Tool.counter_group: create_counter_group,
    Tool.calendar: create_calendar,
    Tool.dashboard: create_dashboard,
    Tool.post: create_post,
    Tool.wiki: create_wiki,
}

if set(TOOL_FACTORIES) != set(Tool):
    missing = set(Tool) - set(TOOL_FACTORIES)
    extra = set(TOOL_FACTORIES) - set(Tool)
    raise RuntimeError(
        f"TOOL_FACTORIES must cover the Tool enum exactly "
        f"(missing: {sorted(t.value for t in missing)}, "
        f"unknown: {sorted(getattr(t, 'value', t) for t in extra)})"
    )


async def create_tool_entity(
    session: AsyncSession,
    tool: Tool,
    initiative: Initiative,
    creator: User,
    **overrides: Any,
) -> Any:
    """Create one instance of ``tool``'s content, whichever tool it is."""
    return await TOOL_FACTORIES[tool](session, initiative, creator, **overrides)


async def _collection_holding(
    session: AsyncSession, file: File, creator: User, **overrides: Any
) -> Collection:
    await route_session_to_guild(session, guild_of(file))
    initiative = await session.get(Initiative, file.initiative_id)
    assert initiative is not None
    return await create_collection(
        session, initiative, creator, files=[file], **overrides
    )


# The same for what lives inside a tool, keyed by ``CHILD_KINDS``: each takes
# its tool's row and a creator, and the ones that name no creator ignore it.
CHILD_FACTORIES: dict[str, Any] = {
    "task": lambda session, project, creator, **kw: create_task(session, project, **kw),
    "queue_item": lambda session, queue, creator, **kw: create_queue_item(
        session, queue, **kw
    ),
    "calendar_event": create_calendar_event,
    "counter": lambda session, group, creator, **kw: create_counter(
        session, group, **kw
    ),
    "wiki_page": create_wiki_page,
    # A collection is in Files rather than in one file: its tool row is the
    # file it starts with.
    "collection": _collection_holding,
}

if set(CHILD_FACTORIES) != set(CHILD_KINDS):
    raise RuntimeError(
        f"CHILD_FACTORIES must cover CHILD_KINDS exactly "
        f"(missing: {sorted(set(CHILD_KINDS) - set(CHILD_FACTORIES))}, "
        f"unknown: {sorted(set(CHILD_FACTORIES) - set(CHILD_KINDS))})"
    )


async def create_child_entity(
    session: AsyncSession, kind: str, tool_row: Any, creator: User, **overrides: Any
) -> Any:
    """Create one row of ``kind`` inside ``tool_row``, whichever kind it is."""
    return await CHILD_FACTORIES[kind](session, tool_row, creator, **overrides)


async def enable_all_tools(session: AsyncSession, initiative: Initiative) -> Initiative:
    """Flip on every tool's master switch, derived from the enum so a new tool
    is enabled here without an edit."""
    await route_session_to_guild(session, guild_of(initiative))
    fresh = await session.get(Initiative, initiative.id)
    assert fresh is not None
    for tool in Tool:
        setattr(fresh, tool.view_permission, True)
    session.add(fresh)
    await session.commit()
    await session.refresh(fresh)
    return fresh


async def create_relationship(
    session: AsyncSession,
    guild: Guild,
    *,
    source: tuple[SearchEntityType, int],
    target: tuple[SearchEntityType, int],
    relationship_type: RelationshipType = RelationshipType.attached,
    provenance: Provenance = Provenance.manual,
    created_by: int | None = None,
    commit: bool = True,
) -> EntityRelationship:
    """Create one edge between two things.

    Endpoints are ``(kind, id)`` pairs, and a symmetric type is stored in the
    order the constraint requires, so a test may name its two ends in whichever
    order reads better.
    """
    await route_session_to_guild(session, guild.id)

    source_endpoint = relationships_service.Endpoint(*source)
    target_endpoint = relationships_service.Endpoint(*target)
    row = await relationships_service.create(
        session,
        source=source_endpoint,
        relationship_type=relationship_type,
        target=target_endpoint,
        provenance=provenance,
        created_by=created_by,
    )
    if row is None:  # already present — hand back the live one
        row = await relationships_service.find(
            session,
            source=source_endpoint,
            relationship_type=relationship_type,
            target=target_endpoint,
        )
    assert row is not None

    if commit:
        await session.commit()
        await session.refresh(row)

    return row


async def billing_guild_ref(guild_id: int) -> str:
    """The reference the billing service knows one guild by, minted on demand.

    Billing names a guild by its reference and never by a row id, so a test
    that posts to the billing boundary needs the value that boundary would
    actually receive — which is the one the service itself would mint.
    """
    from app.models.platform.identity_ref import IdentityEntity
    from app.services.platform import identity_refs

    return await identity_refs.billing_ref(IdentityEntity.guild, guild_id)
