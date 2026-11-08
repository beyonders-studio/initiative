"""A member token's standing: the member's own reach, within the install's.

``establish_install_access`` routes a member token as ``guild_<id>_plugin`` with
the member as the request's user, and the install standing statement's member
branch computes what the token reaches from rows: the member's membership, their
account, their consent for this install and purpose, and their initiative roles,
each limited by the install's placement and scopes. These tests set that up the
way a community and a member do and check what the statement returned and what
the gates then answer.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, event, text
from sqlalchemy.exc import DBAPIError
from sqlmodel import select

from app.api.deps import InstallAccessError
from app.db.guild_standing import InstallContext
from app.db.schema_provisioning import guild_schema_name, GuildRoleKind, guild_role_name
from app.models.platform.guild import CommunityRole
from app.models.platform.user import User, UserStatus
from app.models.tenant.plugin_member_consent import PluginMemberConsent, ConsentAccess
from app.core.file_types import FileType
from app.models.tenant.file import File
from app.models.tenant.initiative import InitiativeMember
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.testing import (
    create_file,
    create_resource_grant,
    route_as_install,
    route_session_to_guild,
)
from app.testing.plugin_clients import CLIENT, InstalledPlugin, install_plugin

_NOW = datetime.now(timezone.utc)


async def _member(acting_user, installed: InstalledPlugin, *, role: str = "member"):
    """An ordinary member of the initiative the install is placed in."""
    return await acting_user(
        guild_role=CommunityRole.member,
        guild=installed.guild,
        initiative=installed.placed,
        initiative_role=role,
    )


async def _consent(
    session,
    installed: InstalledPlugin,
    user_id: int,
    *,
    purpose: str | None = "node-1",
    requested: ConsentAccess = ConsentAccess.read_write,
    granted: ConsentAccess | None = ConsentAccess.read_write,
    initiative_id: int | None = None,
    revoked: bool = False,
) -> PluginMemberConsent:
    await route_session_to_guild(session, installed.guild.id)
    row = PluginMemberConsent(
        install_id=installed.plugin.id,
        user_id=user_id,
        purpose=purpose,
        label="Comment as you",
        initiative_id=initiative_id,
        requested_access=requested.value,
        granted_access=granted.value if granted else None,
        granted_at=_NOW if granted else None,
        revoked_at=_NOW if revoked else None,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def _route(
    role_session,
    installed: InstalledPlugin,
    user_id: int,
    scopes,
    *,
    purpose: str | None = "node-1",
    initiative_id: int | None = None,
):
    s = await role_session("app_user")
    context = await route_as_install(
        s,
        guild_id=installed.guild.id,
        install_id=installed.plugin.id,
        client_id=CLIENT,
        scopes=scopes,
        initiative_id=initiative_id,
        user_id=user_id,
        purpose=purpose,
    )
    return s, context


async def _refused(role_session, installed, user_id, scopes, **kwargs) -> None:
    s = await role_session("app_user")
    with pytest.raises(InstallAccessError):
        await route_as_install(
            s,
            guild_id=installed.guild.id,
            install_id=installed.plugin.id,
            client_id=CLIENT,
            scopes=scopes,
            user_id=user_id,
            purpose=kwargs.pop("purpose", "node-1"),
            **kwargs,
        )
    await s.rollback()


# ---------------------------------------------------------------------------
# What the standing says
# ---------------------------------------------------------------------------


async def test_a_member_token_stands_as_the_member_within_the_install(
    session, acting_user, role_session
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:write"]
    )
    member = await _member(acting_user, installed)
    await _consent(session, installed, member.user.id)

    s, context = await _route(role_session, installed, member.user.id, ["files:write"])
    placed = installed.placed.id

    assert isinstance(context, InstallContext)
    assert context.live and context.member_user_id is not None
    assert context.member_user_id == member.user.id
    assert context.member_initiatives == (placed,)
    assert context.install_read == ("files",)
    assert context.install_write == ("files",)
    # The built-in member role views files but does not create them, so
    # the write scope does not add a key the member lacks.
    assert f"{placed}:files_enabled" in context.role_grants
    assert f"{placed}:create_files" not in context.role_grants
    assert f"{placed}:create_files" in context.role_denies
    assert f"{placed}:projects_enabled" in context.role_denies
    assert context.member_role_ids and context.override_initiatives == ()

    values = (
        await s.exec(
            text(
                "SELECT current_user, "
                "current_setting('app.current_user_id', true), "
                "current_setting('app.guild_admin', true), "
                "current_setting('app.manager_initiatives', true), "
                "current_setting('app.guild_auth_ok', true)"
            )
        )
    ).one()
    assert tuple(values) == (
        guild_role_name(installed.guild.id, GuildRoleKind.plugin),
        str(member.user.id),
        "false",
        "",
        "true",
    )
    await s.rollback()


async def test_no_live_consent_is_not_live(session, acting_user, role_session):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:read"]
    )
    member = await _member(acting_user, installed)

    # Never asked.
    await _refused(role_session, installed, member.user.id, ["files:read"])
    # Asked, not answered.
    await _consent(session, installed, member.user.id, granted=None)
    await _refused(role_session, installed, member.user.id, ["files:read"])
    # Another purpose's consent does not answer for this one.
    await _consent(session, installed, member.user.id, purpose="node-2")
    await _refused(role_session, installed, member.user.id, ["files:read"])
    await _refused(
        role_session, installed, member.user.id, ["files:read"], purpose=None
    )


async def test_read_consent_on_a_write_request_reads_and_cannot_write(
    session, acting_user, role_session
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:write"]
    )
    member = await _member(acting_user, installed, role="project_manager")
    file = await create_file(session, installed.placed, member.user, name="Theirs")
    await _consent(
        session,
        installed,
        member.user.id,
        requested=ConsentAccess.read_write,
        granted=ConsentAccess.read,
    )

    s, context = await _route(role_session, installed, member.user.id, ["files:write"])
    assert context.install_read == ("files",)
    assert context.install_write == ()
    assert f"{installed.placed.id}:create_files" not in context.role_grants
    assert (await s.exec(select(File.name))).all() == ["Theirs"]
    renamed = await s.exec(
        text("UPDATE files SET name = 'Changed' WHERE id = :id").bindparams(id=file.id)
    )
    assert renamed.rowcount == 0
    await s.rollback()


async def test_what_is_shared_with_the_member_reaches_the_token(
    session, acting_user, role_session
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:read"]
    )
    member = await _member(acting_user, installed)
    private = await create_file(
        session, installed.placed, installed.seat.user, name="Private"
    )
    await _consent(session, installed, member.user.id)

    s, _context = await _route(role_session, installed, member.user.id, ["files:read"])
    assert (await s.exec(select(File.name))).all() == []
    await s.rollback()

    await create_resource_grant(session, private, user=member.user)

    s, _context = await _route(role_session, installed, member.user.id, ["files:read"])
    assert (await s.exec(select(File.name))).all() == ["Private"]
    await s.rollback()


async def test_a_consent_bound_to_an_initiative_needs_a_token_narrowed_to_it(
    session, acting_user, role_session
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:read"]
    )
    member = await _member(acting_user, installed)
    await _consent(
        session, installed, member.user.id, initiative_id=installed.placed.id
    )

    await _refused(role_session, installed, member.user.id, ["files:read"])
    s, context = await _route(
        role_session,
        installed,
        member.user.id,
        ["files:read"],
        initiative_id=installed.placed.id,
    )
    assert context.member_initiatives == (installed.placed.id,)
    await s.rollback()


async def test_a_guild_admins_member_token_administers_nothing(
    session, acting_user, role_session
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:write"]
    )
    seat = installed.seat
    await _consent(session, installed, seat.user.id)

    s, context = await _route(role_session, installed, seat.user.id, ["files:write"])
    # The seat manages both initiatives, and the install is placed in one.
    assert context.member_initiatives == (installed.placed.id,)
    assert f"{installed.placed.id}:create_files" in context.role_grants
    values = (
        await s.exec(
            text(
                "SELECT current_setting('app.guild_admin', true), "
                "current_setting('app.guild_seat', true), "
                "current_setting('app.manager_initiatives', true)"
            )
        )
    ).one()
    assert tuple(values) == ("false", "false", "")
    with pytest.raises(DBAPIError, match="permission denied"):
        await s.exec(
            text(
                f'SELECT count(*) FROM "{guild_schema_name(installed.guild.id)}"'
                ".guild_settings"
            )
        )
    await s.rollback()

    s, _context = await _route(role_session, installed, seat.user.id, ["files:write"])
    with pytest.raises(DBAPIError, match="permission denied"):
        await s.exec(
            text(
                "UPDATE initiative_members SET role_id = role_id "
                "WHERE initiative_id = :i"
            ).bindparams(i=installed.placed.id)
        )
    await s.rollback()


async def test_the_member_leaving_or_revoking_ends_what_the_token_reaches(
    session, acting_user, role_session
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:read"]
    )
    member = await _member(acting_user, installed)
    await create_file(session, installed.placed, member.user, name="Theirs")
    row = await _consent(session, installed, member.user.id)

    s, context = await _route(role_session, installed, member.user.id, ["files:read"])
    assert context.member_initiatives == (installed.placed.id,)
    await s.rollback()

    # Out of the initiative: live, and nothing in it.
    await route_session_to_guild(session, installed.guild.id)
    await session.exec(
        delete(InitiativeMember).where(
            InitiativeMember.initiative_id == installed.placed.id,  # type: ignore[arg-type]
            InitiativeMember.user_id == member.user.id,  # type: ignore[arg-type]
        )
    )
    await session.commit()
    s, context = await _route(role_session, installed, member.user.id, ["files:read"])
    assert context.member_initiatives == ()
    assert (await s.exec(select(File.name))).all() == []
    await s.rollback()

    # Revoked: not live.
    await route_session_to_guild(session, installed.guild.id)
    consent = (
        await session.exec(
            select(PluginMemberConsent).where(PluginMemberConsent.id == row.id)
        )
    ).one()
    consent.revoked_at = _NOW
    session.add(consent)
    await session.commit()
    await _refused(role_session, installed, member.user.id, ["files:read"])


async def test_an_account_that_is_not_active_is_not_live(
    session, acting_user, role_session
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:read"]
    )
    member = await _member(acting_user, installed)
    await _consent(session, installed, member.user.id)

    user = (await session.exec(select(User).where(User.id == member.user.id))).one()
    user.status = UserStatus.suspended
    session.add(user)
    await session.commit()

    await _refused(role_session, installed, member.user.id, ["files:read"])


async def test_an_installation_token_stands_as_it_did(
    session, acting_user, role_session
):
    """The member branch changes nothing for the install itself, however many
    members consented."""
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:write"]
    )
    member = await _member(acting_user, installed)
    await _consent(session, installed, member.user.id)

    s = await role_session("app_user")
    context = await route_as_install(
        s,
        guild_id=installed.guild.id,
        install_id=installed.plugin.id,
        client_id=CLIENT,
        scopes=["files:write"],
    )
    assert context.member_user_id is None
    assert f"{installed.placed.id}:create_files" in context.role_grants
    assert context.member_role_ids == () and context.override_initiatives == ()
    # An installation token reads no member's consent.
    assert (await s.exec(select(PluginMemberConsent.install_id))).all() == []
    await s.rollback()


async def test_a_member_token_is_two_statements(session, acting_user, role_session):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:read"]
    )
    member = await _member(acting_user, installed)
    await _consent(session, installed, member.user.id)

    s = await role_session("app_user")
    await s.connection()
    statements: list[str] = []

    def count(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement)

    engine = s.bind.sync_engine
    event.listen(engine, "before_cursor_execute", count)
    try:
        context = await route_as_install(
            s,
            guild_id=installed.guild.id,
            install_id=installed.plugin.id,
            client_id=CLIENT,
            scopes=["files:read"],
            user_id=member.user.id,
            purpose="node-1",
        )
    finally:
        event.remove(engine, "before_cursor_execute", count)
    assert context.live
    assert len(statements) == 2, statements
    await s.rollback()


async def test_a_new_transaction_replays_the_member(session, acting_user, role_session):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:read"]
    )
    member = await _member(acting_user, installed)
    await _consent(session, installed, member.user.id)

    s, context = await _route(role_session, installed, member.user.id, ["files:read"])
    await s.commit()
    values = (
        await s.exec(
            text(
                "SELECT current_setting('app.current_user_id', true), "
                "current_setting('app.token_purpose', true), "
                "current_setting('app.member_role_ids', true)"
            )
        )
    ).one()
    assert tuple(values) == (
        str(member.user.id),
        "node-1",
        ",".join(str(i) for i in context.member_role_ids),
    )
    await s.rollback()


# ---------------------------------------------------------------------------
# What a member token creates is the member's
# ---------------------------------------------------------------------------


async def test_what_a_member_token_creates_is_owned_by_the_member(
    session, acting_user, role_session
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:write"]
    )
    member = await _member(acting_user, installed, role="project_manager")
    await _consent(session, installed, member.user.id)

    s, _context = await _route(role_session, installed, member.user.id, ["files:write"])
    made = File(
        initiative_id=installed.placed.id,
        name="Made as the member",
        file_type=FileType.lexical,
    )
    s.add(made)
    await s.flush()
    grants = (
        await s.exec(
            select(ResourceGrant).where(
                ResourceGrant.resource_type == "file",
                ResourceGrant.resource_id == made.id,
            )
        )
    ).all()
    assert [
        (g.level, g.user_id, g.plugin_install_id, g.initiative_id) for g in grants
    ] == [(ResourceAccessLevel.owner, member.user.id, None, installed.placed.id)]
    created_by = (await s.exec(select(File.created_by).where(File.id == made.id))).one()
    assert created_by == member.user.id
    await s.rollback()


async def test_a_member_token_writes_no_owner_row_itself(
    session, acting_user, role_session
):
    """The owner row is the trigger's: a member token inserting one naming the
    member on a file that already exists is refused."""
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:write"]
    )
    member = await _member(acting_user, installed, role="project_manager")
    existing = await create_file(
        session, installed.placed, installed.seat.user, name="Not theirs"
    )
    await _consent(session, installed, member.user.id)

    s, _context = await _route(role_session, installed, member.user.id, ["files:write"])
    s.add(
        ResourceGrant(
            resource_type="file",
            resource_id=existing.id,
            user_id=member.user.id,
            level=ResourceAccessLevel.owner,
            initiative_id=installed.placed.id,
        )
    )
    with pytest.raises(DBAPIError, match="row-level security"):
        await s.flush()
    await s.rollback()
