"""An installed plug-in's standing, computed from rows and read by the gates.

``establish_install_access`` routes a session as ``guild_<id>_plugin`` and runs
the install standing statement. These tests set an install up the way a
community does — placed in initiatives, granted scopes by its seat, registered
by the operator — route a real request login through the seam, and check two
things: that what the statement returned is what the rows say, and that the
existing gates answer from it.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError
from sqlmodel import select

from app.api.deps import InstallAccessError, VerifiedInstall, establish_install_access
from app.core.plugin_scopes import ALL_SCOPES
from app.core.tools import Tool
from app.db.guild_standing import InstallContext
from app.db.request_context import ContextShapeError, Install
from app.db.schema_provisioning import GuildRoleKind, guild_role_name, guild_schema_name
from app.db.session import (
    _RLS_ESTABLISHED_INFO_KEY,
    RLS_CONTEXT_MAX_AGE_SECONDS,
    StaleAuthorizationContext,
    install_context,
)
from app.models.platform.guild import CommunityRole, CommunityStatus
from app.models.platform.identity_ref import IdentityEntity, IdentityPurpose
from app.models.platform.plugin_service_registration import RegistrationKind
from app.models.tenant.file import File
from app.models.tenant.guild_plugin import GuildPlugin
from app.models.tenant.initiative import Initiative, PermissionKey
from app.models.tenant.plugin_placement import PluginPlacement
from app.services.platform.identity_refs import ensure_ref
from app.services.platform.intake_setup import set_operations_guild
from app.testing import (
    create_file,
    create_guild_plugin,
    create_initiative,
    create_plugin_service_registration,
    create_resource_grant,
    route_as,
    route_as_install,
    route_session_to_guild,
)

CLIENT = "tests.install-standing"
LISTING = "INSTALLSTAND01"
_PLUGIN_DEFINITION = {
    "plugin_kind": "service",
    "service": {"public_id": CLIENT, "protocol": 1},
}


# ---------------------------------------------------------------------------
# Setting an install up
# ---------------------------------------------------------------------------


class _Install:
    """What a test needs to name: the community, the install, and the two
    initiatives it may be placed in."""

    def __init__(self, seat, plugin: GuildPlugin, second) -> None:
        self.seat = seat
        self.guild = seat.guild
        self.plugin = plugin
        self.a = seat.initiative
        self.b = second


async def _install(
    session,
    acting_user,
    role_session,
    *,
    granted: list[str],
    placed: str = "ab",
    requested: tuple[str, ...] = ALL_SCOPES,
    declarative: bool = False,
) -> _Install:
    """An install placed in ``placed`` (of initiatives A and B), granted
    ``granted`` by the community's seat, with a live registration and a pinned
    manifest requesting ``requested``: a container's, or a declarative plug-in's
    when ``declarative``."""
    seat = await acting_user(guild_role=CommunityRole.superadmin, initiative=True)
    second = await create_initiative(session, seat.guild, seat.user, name="B")
    definition = (
        {"plugin_kind": "service", "hosts": ["api.test"], "scopes": list(requested)}
        if declarative
        else {
            **_PLUGIN_DEFINITION,
            "service": {**_PLUGIN_DEFINITION["service"], "scopes": list(requested)},
        }
    )
    plugin = await create_guild_plugin(
        session, seat.guild, seat.user, definition=definition, listing_uid=LISTING
    )
    await create_plugin_service_registration(
        session,
        public_id=CLIENT,
        listing_uid=LISTING,
        **(
            {
                "kind": RegistrationKind.DECLARATIVE,
                "base_url": None,
                "allowed_origins": [],
                "jwks": {},
            }
            if declarative
            else {}
        ),
    )
    install = _Install(seat, plugin, second)

    await route_session_to_guild(session, seat.guild.id)
    for key, initiative in (("a", install.a), ("b", install.b)):
        if key in placed:
            session.add(
                PluginPlacement(install_id=plugin.id, initiative_id=initiative.id)
            )
    await session.commit()

    if granted:
        # Granted the way a community grants it: by its seat.
        s = await role_session("app_user")
        await route_as(s, user_id=seat.user.id, guild_id=seat.guild.id)
        row = (
            await s.exec(select(GuildPlugin).where(GuildPlugin.id == plugin.id))
        ).one()
        row.granted_scopes = granted
        s.add(row)
        await s.commit()
    return install


async def _route(role_session, install: _Install, scopes, *, initiative_id=None):
    s = await role_session("app_user")
    context = await route_as_install(
        s,
        guild_id=install.guild.id,
        install_id=install.plugin.id,
        client_id=CLIENT,
        scopes=scopes,
        initiative_id=initiative_id,
    )
    return s, context


def _keys(initiative_ids, keys) -> set[str]:
    return {f"{i}:{k}" for i in initiative_ids for k in keys}


_ALL_KEYS = {key.value for key in PermissionKey}


# ---------------------------------------------------------------------------
# The standing is what the rows say
# ---------------------------------------------------------------------------


async def test_the_standing_is_what_the_rows_say(session, acting_user, role_session):
    install = await _install(
        session,
        acting_user,
        role_session,
        granted=["files:write", "comments:read"],
    )
    s, context = await _route(role_session, install, ["files:write", "comments:read"])

    # What a superuser reads from the same rows.
    await route_session_to_guild(session, install.guild.id)
    placed = sorted(
        (
            await session.exec(
                select(PluginPlacement.initiative_id).where(
                    PluginPlacement.install_id == install.plugin.id
                )
            )
        ).all()
    )
    assert placed == sorted([install.a.id, install.b.id])

    granted = _keys(placed, {"files_enabled", "create_files"})
    assert context.live
    assert context.standing_guild_id == install.guild.id
    assert sorted(context.member_initiatives) == placed
    assert set(context.role_grants) == granted
    assert set(context.role_denies) == _keys(placed, _ALL_KEYS) - granted
    assert f"{install.a.id}:projects_enabled" in context.role_denies
    assert set(context.install_read) == {"files", "comments"}
    assert set(context.install_write) == {"files"}
    switched_on = {
        f"{initiative.id}:{tool.value}"
        for initiative in (
            await session.exec(select(Initiative).where(Initiative.id.in_(placed)))
        ).all()
        for tool in Tool
        if getattr(initiative, tool.view_permission)
    }
    assert set(context.enabled_tools) == switched_on

    # And what the policies will read is the same thing.
    values = (
        await s.exec(
            text(
                "SELECT current_user, "
                "current_setting('app.current_user_id', true), "
                "current_setting('app.current_install_id', true), "
                "current_setting('app.member_initiatives', true), "
                "current_setting('app.guild_admin', true), "
                "current_setting('app.guild_auth_ok', true), "
                "current_setting('app.install_write', true), "
                "(current_standing()).install_id"
            )
        )
    ).one()
    assert values[0] == guild_role_name(install.guild.id, GuildRoleKind.plugin)
    assert values[1] == ""
    assert values[2] == str(install.plugin.id)
    assert values[3] == ",".join(str(i) for i in placed)
    assert values[4] == "false"
    assert values[5] == "true"
    assert values[6] == "files"
    assert values[7] == install.plugin.id
    assert install_context(s) == context
    await s.rollback()


async def test_a_narrowed_token_stands_in_one_initiative(
    session, acting_user, role_session
):
    install = await _install(
        session, acting_user, role_session, granted=["files:write"]
    )
    s, context = await _route(
        role_session, install, ["files:write"], initiative_id=install.a.id
    )
    assert context.member_initiatives == (install.a.id,)
    assert set(context.role_grants) == _keys(
        [install.a.id], {"files_enabled", "create_files"}
    )
    assert {pair.split(":")[0] for pair in context.role_denies} == {str(install.a.id)}
    await s.rollback()


@pytest.mark.parametrize(
    "granted,token,read,write,requested",
    [
        # The token asks for less than the seat granted.
        (
            ["files:write", "projects:write"],
            ["files:read"],
            {"files"},
            set(),
            ALL_SCOPES,
        ),
        # The seat granted less than the token asks for: what both name is
        # used, at the lower of the two levels.
        (
            ["files:read"],
            ["files:write", "projects:write"],
            {"files"},
            set(),
            ALL_SCOPES,
        ),
        (
            ["files:read", "projects:write"],
            ["files:write", "projects:write"],
            {"files", "projects"},
            {"projects"},
            ALL_SCOPES,
        ),
        # A token issued before the pinned version stopped requesting a scope
        # carries it, and it is used no more.
        (
            ["files:write", "projects:write"],
            ["files:write", "projects:write"],
            {"files"},
            {"files"},
            ("files:write",),
        ),
    ],
)
async def test_what_an_install_uses_is_the_grant_and_the_token_together(
    session, acting_user, role_session, granted, token, read, write, requested
):
    install = await _install(
        session, acting_user, role_session, granted=granted, requested=requested
    )
    s, context = await _route(role_session, install, token)
    assert set(context.install_read) == read
    assert set(context.install_write) == write
    await s.rollback()


# ---------------------------------------------------------------------------
# When an install may not act
# ---------------------------------------------------------------------------


async def _disable_install(session, install: _Install) -> None:
    await route_session_to_guild(session, install.guild.id)
    await session.exec(
        text("UPDATE guild_plugins SET enabled = false WHERE id = :id").bindparams(
            id=install.plugin.id
        )
    )
    await session.commit()


async def _set_registration(session, column: str, value) -> None:
    await session.exec(
        text(
            f"UPDATE public.plugin_service_registrations SET {column} = :v "
            "WHERE public_id = :pid"
        ).bindparams(v=value, pid=CLIENT)
    )
    await session.commit()


async def _set_guild_status(
    session, install: _Install, status: CommunityStatus
) -> None:
    await session.exec(
        text("UPDATE public.guilds SET status = :s WHERE id = :id").bindparams(
            s=status.value, id=install.guild.id
        )
    )
    await session.commit()


@pytest.mark.parametrize(
    "reason",
    [
        "install_disabled",
        "registration_disabled",
        "registration_keyless",
        "registration_declarative",
        "publisher_disabled",
        "operations_only_elsewhere",
        "another_client",
        "guild_suspended",
        "guild_on_hold",
    ],
)
async def test_an_install_that_may_not_act_is_refused(
    session, acting_user, role_session, reason
):
    install = await _install(session, acting_user, role_session, granted=["files:read"])
    client = CLIENT
    if reason == "install_disabled":
        await _disable_install(session, install)
    elif reason == "registration_disabled":
        await _set_registration(session, "enabled", False)
    elif reason == "registration_keyless":
        await _set_registration(session, "jwks", None)
    elif reason == "registration_declarative":
        # A declarative plug-in's registration stands only for an install
        # pinned to a declarative version, and this one is a container's.
        await _set_registration(session, "kind", RegistrationKind.DECLARATIVE)
    elif reason == "publisher_disabled":
        await session.exec(
            text(
                "UPDATE public.publishers SET enabled = false WHERE id = "
                "(SELECT publisher_id FROM public.plugin_service_registrations "
                "WHERE public_id = :c)"
            ).bindparams(c=CLIENT)
        )
        await session.commit()
    elif reason == "operations_only_elsewhere":
        await _set_registration(session, "operations_only", True)
    elif reason == "another_client":
        client = "tests.someone-else"
    elif reason == "guild_suspended":
        await _set_guild_status(session, install, CommunityStatus.suspended)
    elif reason == "guild_on_hold":
        await _set_guild_status(session, install, CommunityStatus.on_hold)

    s = await role_session("app_user")
    with pytest.raises(InstallAccessError):
        await route_as_install(
            s,
            guild_id=install.guild.id,
            install_id=install.plugin.id,
            client_id=client,
            scopes=["files:read"],
        )
    # Refused with an empty standing: nothing a gate reads answers yes.
    values = (
        await s.exec(
            text(
                "SELECT current_setting('app.member_initiatives', true), "
                "current_setting('app.role_grants', true), "
                "current_setting('app.install_read', true), "
                "current_setting('app.guild_auth_ok', true)"
            )
        )
    ).one()
    assert tuple(values) == ("", "", "", "false")
    await s.rollback()


async def test_an_operations_only_install_acts_in_the_operations_community(
    session, acting_user, role_session
):
    install = await _install(session, acting_user, role_session, granted=["files:read"])
    await _set_registration(session, "operations_only", True)
    await set_operations_guild(session, install.guild.id)

    s, context = await _route(role_session, install, ["files:read"])
    assert context.live
    await s.rollback()


async def test_a_read_only_community_writes_nothing(session, acting_user, role_session):
    install = await _install(
        session, acting_user, role_session, granted=["files:write"]
    )
    await _set_guild_status(session, install, CommunityStatus.read_only)
    s, context = await _route(role_session, install, ["files:write"])
    assert context.live and context.content_hold
    assert set(context.install_read) == {"files"}
    assert context.install_write == ()
    assert not any(pair.endswith(":create_files") for pair in context.role_grants)
    await s.rollback()


async def test_a_community_that_is_gone_is_refused(session, role_session):
    """No role to assume is the same refusal as an install that may not act,
    and it leaves the session unrouted."""
    s = await role_session("app_user")
    with pytest.raises(InstallAccessError):
        await route_as_install(
            s,
            guild_id=987_654_321,
            install_id=1,
            client_id=CLIENT,
            scopes=["files:read"],
        )
    assert (await s.exec(text("SELECT current_user"))).one()[0] != (
        guild_role_name(987_654_321, GuildRoleKind.plugin)
    )
    await s.rollback()


async def test_an_unknown_scope_is_refused(session, acting_user, role_session):
    install = await _install(session, acting_user, role_session, granted=["files:read"])
    s = await role_session("app_user")
    with pytest.raises(InstallAccessError):
        await route_as_install(
            s,
            guild_id=install.guild.id,
            install_id=install.plugin.id,
            client_id=CLIENT,
            scopes=["files:read", "everything:write"],
        )


# ---------------------------------------------------------------------------
# The gates answer from it
# ---------------------------------------------------------------------------


async def test_the_gates_answer_for_an_install(session, acting_user, role_session):
    """Placement is gate 2, the role keys its scopes give are gate 3, and a
    share with every member of an initiative it is placed in is gate 4. A
    file shared with one person is not the install's."""
    install = await _install(session, acting_user, role_session, granted=["files:read"])
    shared_a = await create_file(session, install.a, install.seat.user, name="Shared A")
    await create_resource_grant(session, shared_a, all_initiative_members=True)
    await create_file(session, install.a, install.seat.user, name="Private A")
    shared_b = await create_file(session, install.b, install.seat.user, name="Shared B")
    await create_resource_grant(session, shared_b, all_initiative_members=True)

    s, _context = await _route(role_session, install, ["files:read"])
    assert set((await s.exec(select(File.name))).all()) == {
        "Shared A",
        "Shared B",
    }
    await s.rollback()

    narrowed, _context = await _route(
        role_session, install, ["files:read"], initiative_id=install.a.id
    )
    assert set((await narrowed.exec(select(File.name))).all()) == {"Shared A"}
    await narrowed.rollback()


async def test_initiative_acts_as_a_declarative_install(
    session, acting_user, role_session
):
    """A declarative plug-in is issued no token: Initiative routes as its
    install, naming the client its registration is, with the read scopes its
    manifest asks for at the top. The gates answer for it as for any install."""
    install = await _install(
        session,
        acting_user,
        role_session,
        granted=["files:read"],
        requested=("files:read",),
        declarative=True,
    )
    shared = await create_file(session, install.a, install.seat.user, name="Shared A")
    await create_resource_grant(session, shared, all_initiative_members=True)
    await create_file(session, install.a, install.seat.user, name="Private A")

    s, context = await _route(role_session, install, ["files:read"])
    assert context.live
    assert (set(context.install_read), context.install_write) == ({"files"}, ())
    assert (await s.exec(select(File.name))).all() == ["Shared A"]
    await s.rollback()


async def test_an_install_without_a_tool_scope_reads_none_of_it(
    session, acting_user, role_session
):
    install = await _install(
        session, acting_user, role_session, granted=["comments:read"]
    )
    shared = await create_file(session, install.a, install.seat.user)
    await create_resource_grant(session, shared, all_initiative_members=True)
    s, context = await _route(role_session, install, ["comments:read"])
    assert f"{install.a.id}:files_enabled" in context.role_denies
    assert (await s.exec(select(File.name))).all() == []
    await s.rollback()


async def test_the_plugin_role_cannot_read_the_communitys_settings(
    session, acting_user, role_session
):
    install = await _install(session, acting_user, role_session, granted=["files:read"])
    s, _context = await _route(role_session, install, ["files:read"])
    with pytest.raises(DBAPIError, match="permission denied"):
        await s.exec(
            text(
                f'SELECT count(*) FROM "{guild_schema_name(install.guild.id)}"'
                ".guild_settings"
            )
        )
    await s.rollback()


# ---------------------------------------------------------------------------
# A standing its token asked for
# ---------------------------------------------------------------------------


async def _files(session, install: _Install, third=None) -> None:
    """One file shared with every member and one shared with nobody, in
    each initiative, and in ``third`` when given."""
    for initiative in (install.a, install.b, *((third,) if third else ())):
        shared = await create_file(
            session, initiative, install.seat.user, name=f"Shared {initiative.name}"
        )
        await create_resource_grant(session, shared, all_initiative_members=True)
        await create_file(
            session, initiative, install.seat.user, name=f"Private {initiative.name}"
        )


async def test_a_moderator_token_moderates_the_initiative_it_names(
    session, acting_user, role_session
):
    """Manager with "Full access" there, as a moderator is: every file in
    the initiative, whoever it is shared with, and nothing in the other."""
    granted = ["files:read", "initiatives:moderate"]
    install = await _install(session, acting_user, role_session, granted=granted)
    await _files(session, install)

    s, context = await _route(
        role_session, install, granted, initiative_id=install.a.id
    )
    assert context.manager_initiatives == (install.a.id,)
    assert context.override_initiatives == (install.a.id,)
    assert context.overrides_sharing(install.a.id)
    assert not context.is_admin
    names = set((await s.exec(select(File.name))).all())
    assert names == {f"Shared {install.a.name}", f"Private {install.a.name}"}
    await s.rollback()


async def test_a_moderator_scope_does_nothing_on_a_token_naming_no_initiative(
    session, acting_user, role_session
):
    granted = ["files:read", "initiatives:moderate"]
    install = await _install(session, acting_user, role_session, granted=granted)
    await _files(session, install)

    s, context = await _route(role_session, install, granted)
    assert context.manager_initiatives == ()
    assert context.override_initiatives == ()
    names = set((await s.exec(select(File.name))).all())
    assert names == {f"Shared {install.a.name}", f"Shared {install.b.name}"}
    await s.rollback()


@pytest.mark.parametrize(
    ("granted", "token", "narrowed"),
    [
        # The token carries a standing the seat never granted.
        (["files:read"], ["files:read", "initiatives:moderate"], True),
        (["files:read"], ["files:read", "community:admin"], False),
        # The seat granted it and the token did not ask.
        (["files:read", "initiatives:moderate"], ["files:read"], True),
        (["files:read", "community:admin"], ["files:read"], False),
    ],
)
async def test_a_standing_needs_the_grant_and_the_token(
    session, acting_user, role_session, granted, token, narrowed
):
    install = await _install(session, acting_user, role_session, granted=granted)
    s, context = await _route(
        role_session,
        install,
        token,
        initiative_id=install.a.id if narrowed else None,
    )
    assert context.live
    assert context.manager_initiatives == ()
    assert context.override_initiatives == ()
    assert not context.is_admin
    await s.rollback()


async def test_a_guild_admin_token_administers_the_community(
    session, acting_user, role_session
):
    """A guild admin's standing reaches every initiative, placed in or not."""
    granted = ["files:read", "community:admin"]
    install = await _install(
        session, acting_user, role_session, granted=granted, placed="a"
    )
    await _files(session, install)

    s, context = await _route(role_session, install, granted)
    assert context.is_admin
    assert context.manager_initiatives == ()
    admin = (
        await s.exec(text("SELECT current_setting('app.guild_admin', true)"))
    ).one()
    assert admin[0] == "true"
    names = set((await s.exec(select(File.name))).all())
    assert names == {
        f"{shared} {initiative.name}"
        for shared in ("Shared", "Private")
        for initiative in (install.a, install.b)
    }
    await s.rollback()


async def test_a_narrowed_guild_admin_token_administers_that_initiative(
    session, acting_user, role_session
):
    """The narrowing still confines it: everything in the initiative it names,
    nothing in the other."""
    granted = ["files:read", "community:admin"]
    install = await _install(session, acting_user, role_session, granted=granted)
    await _files(session, install)

    s, context = await _route(
        role_session, install, granted, initiative_id=install.a.id
    )
    assert context.is_admin
    names = set((await s.exec(select(File.name))).all())
    assert names == {f"Shared {install.a.name}", f"Private {install.a.name}"}
    await s.rollback()


@pytest.mark.parametrize(
    ("standing", "narrowed"),
    [("initiatives:moderate", True), ("community:admin", False)],
)
async def test_a_standing_reaches_no_tool_its_scopes_do_not(
    session, acting_user, role_session, standing, narrowed
):
    granted = ["comments:read", standing]
    install = await _install(session, acting_user, role_session, granted=granted)
    await _files(session, install)

    s, context = await _route(
        role_session,
        install,
        granted,
        initiative_id=install.a.id if narrowed else None,
    )
    assert context.is_admin or context.manager_initiatives
    assert (await s.exec(select(File.name))).all() == []
    assert set(context.install_read) == {"comments"}
    await s.rollback()


# ---------------------------------------------------------------------------
# Round trips and replay
# ---------------------------------------------------------------------------


async def test_the_seam_is_two_statements(session, acting_user, role_session):
    install = await _install(session, acting_user, role_session, granted=["files:read"])
    s = await role_session("app_user")
    await s.connection()
    statements: list[str] = []

    def count(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement)

    engine = s.bind.sync_engine
    event.listen(engine, "before_cursor_execute", count)
    try:
        await route_as_install(
            s,
            guild_id=install.guild.id,
            install_id=install.plugin.id,
            client_id=CLIENT,
            scopes=["files:read"],
        )
    finally:
        event.remove(engine, "before_cursor_execute", count)
    assert len(statements) == 2, statements
    await s.rollback()


async def test_a_new_transaction_replays_the_install(
    session, acting_user, role_session
):
    install = await _install(session, acting_user, role_session, granted=["files:read"])
    s, context = await _route(role_session, install, ["files:read"])
    await s.commit()
    values = (
        await s.exec(
            text(
                "SELECT current_user, "
                "current_setting('app.member_initiatives', true), "
                "current_setting('app.install_read', true), "
                "current_setting('app.guild_auth_ok', true)"
            )
        )
    ).one()
    assert tuple(values) == (
        guild_role_name(install.guild.id, GuildRoleKind.plugin),
        ",".join(str(i) for i in context.member_initiatives),
        "files",
        "true",
    )
    await s.commit()

    s.info[_RLS_ESTABLISHED_INFO_KEY] -= RLS_CONTEXT_MAX_AGE_SECONDS + 1
    with pytest.raises(StaleAuthorizationContext):
        await s.exec(text("SELECT 1"))


# ---------------------------------------------------------------------------
# What the install floor holds in public
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "table,readable",
    [
        ("guilds", {"id", "status"}),
        (
            "plugin_service_registrations",
            {
                "public_id",
                "listing_uid",
                "enabled",
                "publisher_id",
                "jwks",
                "jwks_uri",
                "base_url",
                "vendor_ready",
                # Whether it is a declarative plug-in's, which needs no location
                # or keys to be live.
                "kind",
                # Whether it is live outside the operations community.
                "operations_only",
            },
        ),
        # Whether the registration's publisher is on.
        ("publishers", {"id", "enabled"}),
        # A member token's standing: the member's own membership row, whether
        # it is live (a guest's ends), and whether their account is active.
        ("guild_memberships", {"guild_id", "user_id", "guest_until", "role"}),
        ("users", {"id", "status"}),
    ],
)
async def test_the_install_floor_reads_only_what_its_standing_needs(
    session, table, readable
):
    rows = (
        await session.exec(
            text(
                "SELECT column_name, "
                "has_column_privilege('plugin_install_base', "
                "CAST(:t AS text), column_name, 'SELECT') "
                "FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = :name"
            ).bindparams(t=f"public.{table}", name=table)
        )
    ).all()
    assert {name for name, held in rows if held} == readable


async def _sector_refs(session, install: _Install) -> dict[str, str]:
    """References in and around the install's sector, minted as the system
    engine would: the seat's and the community's in its own plug-in's sector,
    the seat's for another plug-in, and the seat's for billing."""
    guild_id, user_id = install.guild.id, install.seat.user.id
    refs = {
        "own": await ensure_ref(
            session,
            entity_type=IdentityEntity.user,
            entity_id=user_id,
            purpose=IdentityPurpose.plugin,
            sector_guild_id=guild_id,
            sector_plugin=CLIENT,
        ),
        "guild": await ensure_ref(
            session,
            entity_type=IdentityEntity.guild,
            entity_id=guild_id,
            purpose=IdentityPurpose.plugin,
            sector_guild_id=guild_id,
            sector_plugin=CLIENT,
        ),
        "other_install": await ensure_ref(
            session,
            entity_type=IdentityEntity.user,
            entity_id=user_id,
            purpose=IdentityPurpose.plugin,
            sector_guild_id=guild_id,
            sector_plugin="someone.else",
        ),
        "billing": await ensure_ref(
            session,
            entity_type=IdentityEntity.user,
            entity_id=user_id,
            purpose=IdentityPurpose.billing,
        ),
    }
    await session.commit()
    return refs


async def test_the_standing_resolves_only_the_install_s_own_references(
    session, acting_user, role_session
):
    install = await _install(session, acting_user, role_session, granted=["files:read"])
    refs = await _sector_refs(session, install)

    s = await role_session("app_user")
    context = await establish_install_access(
        s,
        VerifiedInstall(
            guild_id=install.guild.id,
            install_id=install.plugin.id,
            client_id=CLIENT,
            scopes=frozenset({"files:read"}),
        ),
        [*refs.values(), "uplu_nobody-at-all", "plain text"],
    )

    assert context.guild_ref == refs["guild"]
    assert context.named_refs == tuple(
        sorted(
            [
                (refs["own"], IdentityEntity.user.value, install.seat.user.id),
                (refs["guild"], IdentityEntity.guild.value, install.guild.id),
            ]
        )
    )
    await s.rollback()


async def test_the_install_role_reads_and_mints_in_its_own_sector_only(
    session, acting_user, role_session
):
    install = await _install(session, acting_user, role_session, granted=["files:read"])
    refs = await _sector_refs(session, install)
    s, _context = await _route(role_session, install, ["files:read"])

    visible = set(
        (await s.exec(text("SELECT ref FROM public.identity_refs"))).scalars().all()
    )
    assert visible == {refs["own"], refs["guild"]}

    insert = text(
        "INSERT INTO public.identity_refs "
        "(ref, entity_type, entity_id, purpose, sector_guild_id, sector_plugin, "
        "created_at, retired_at) "
        "VALUES (:ref, :kind, :entity, :purpose, :g, :i, now(), :retired)"
    )
    own_sector = {
        "kind": "user",
        "entity": install.seat.user.id + 1,
        "purpose": "plugin",
        "g": install.guild.id,
        "i": CLIENT,
        "retired": None,
    }

    async def attempt(sql, **values) -> bool:
        try:
            async with s.begin_nested():
                await s.exec(sql.bindparams(**values))
        except DBAPIError:
            return False
        return True

    assert await attempt(insert, ref="uplu_minted-here", **own_sector)
    for n, refused in enumerate(
        (
            {"i": "someone.else"},
            {"g": install.guild.id + 1000},
            {"purpose": "billing"},
            {"kind": "guild", "entity": install.guild.id + 1000},
            {"retired": datetime.now(UTC)},
        )
    ):
        assert not await attempt(
            insert, ref=f"uplu_refused-{n}", **{**own_sector, **refused}
        ), refused
    assert not await attempt(
        text("UPDATE public.identity_refs SET retired_at = now() WHERE ref = :r"),
        r=refs["own"],
    )
    assert not await attempt(
        text("DELETE FROM public.identity_refs WHERE ref = :r"), r=refs["own"]
    )
    await s.rollback()


# ---------------------------------------------------------------------------
# The routing shape
# ---------------------------------------------------------------------------


def _pending(**overrides) -> InstallContext:
    fields = {
        "guild_id": 3,
        "install_id": 5,
        "client_id": CLIENT,
        "token_scopes": frozenset(),
    }
    fields.update(overrides)
    return InstallContext(**fields)


@pytest.mark.parametrize(
    "overrides",
    [
        # A context for another install.
        {"install_id": 6},
        # No context.
        {"standing": None},
        # No client.
        {"token_client_id": ""},
        # A purpose without the member who consented to it.
        {"token_purpose": "sync"},
        # A member the context does not name.
        {"member_user_id": 7},
    ],
)
def test_an_install_routing_refuses_what_is_not_its_own(overrides):
    with pytest.raises(ContextShapeError):
        Install(
            **{
                "guild_id": 3,
                "install_id": 5,
                "standing": _pending(),
                "token_client_id": CLIENT,
                **overrides,
            }
        )
