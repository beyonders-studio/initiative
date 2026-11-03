"""An installed plug-in answers to its scopes at every gate.

``install_standing_test`` shows the standing is what the rows say. These show
the gates read it: an install routed through the seam on the real request
login reaches content only under the scope that names it, a token narrowed to
one initiative reaches nothing that belongs to the community as a whole, a
grant naming the install is how sharing reaches it, and the tables no tool
governs ask their own scope. Each surface also runs one ordinary member's
read or write through the same policies, so the legs are seen to leave a
person's request as it was.
"""

from __future__ import annotations

import re

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlmodel import select

from app.core.tools import Tool
from app.db.plugin_rls import PLUGIN_REFUSED_TABLES, PLUGIN_TABLE_ACCESS
from app.db.authorization import IN_POLICY
from app.db.guild_ddl import PLUGIN_POLICY_TABLES, render_guild_rls_ddl
from app.db.install_standing_test import (
    _install,
    _route,
)
from app.models.platform.guild import CommunityRole
from app.models.tenant.calendar import Calendar
from app.models.tenant.calendar_event import CalendarEvent
from app.models.tenant.comment import Comment
from app.core.file_types import FileType
from app.models.tenant.file import File
from app.models.tenant.initiative import InitiativeMember
from app.models.tenant.project import Project
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.models.tenant.tag import Tag
from app.testing import (
    create_resource_grant,
    create_calendar,
    create_calendar_event,
    create_comment,
    create_file,
    create_tag,
    route_as,
    route_session_to_guild,
)

_INSTALL_LEG = IN_POLICY.install_id


# ---------------------------------------------------------------------------
# The render: every table a plug-in reaches asks its scope
# ---------------------------------------------------------------------------

_POLICY = re.compile(
    r"^CREATE POLICY (\w+) ON (\w+) AS (PERMISSIVE|RESTRICTIVE) FOR (\w+)\n  (.*?);$",
    re.M | re.S,
)


def _policies() -> dict[str, list[tuple[str, str, str]]]:
    """table -> (kind, command, predicate) for every rendered policy."""
    out: dict[str, list[tuple[str, str, str]]] = {}
    for _name, table, kind, command, body in _POLICY.findall(render_guild_rls_ddl()):
        out.setdefault(table, []).append((kind, command, body))
    return out


def _asks_the_install(policies, table: str, command: str) -> bool:
    return any(
        _INSTALL_LEG in body
        for _kind, cmd, body in policies.get(table, [])
        if cmd in (command, "ALL")
    )


def _read_asks_the_install(policies, table: str, seen: frozenset[str] = frozenset()):
    """A table's read asks the install itself, or walks into a table whose
    read does: a child's read is an EXISTS into its parent, and the parent's
    own read policy is what runs there."""
    if _asks_the_install(policies, table, "SELECT"):
        return True
    read = " ".join(
        body for _kind, cmd, body in policies.get(table, []) if cmd == "SELECT"
    )
    walked = set(re.findall(r"\b(?:FROM|JOIN) (\w+)\b", read)) - seen - {table}
    return any(
        _read_asks_the_install(policies, parent, seen | {table})
        for parent in walked
        if parent in policies
    )


@pytest.mark.parametrize("command", ["SELECT", "INSERT", "UPDATE", "DELETE"])
def test_every_table_a_plugin_reaches_asks_the_install(command):
    """Each command on each table the plug-in role is granted carries the leg in
    its own policies. A child's read is the one exception: it is an EXISTS
    into its parent, and that parent's own read asks."""
    policies = _policies()
    missing = [
        table
        for table in sorted(PLUGIN_TABLE_ACCESS)
        if not (
            _read_asks_the_install(policies, table)
            if command == "SELECT"
            else _asks_the_install(policies, table, command)
        )
    ]
    assert missing == [], f"{command} asks nothing of an install on {missing}"


def test_the_refused_tables_refuse_every_command():
    policies = _policies()
    for table in sorted(PLUGIN_REFUSED_TABLES):
        assert table not in PLUGIN_TABLE_ACCESS, table
        for command in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            assert _asks_the_install(policies, table, command), (table, command)


def test_the_plugin_policies_are_restrictive():
    """They narrow what the table's own policies admit, and admit nothing."""
    found: dict[str, set[str]] = {}
    for name, table, kind, _command, _body in _POLICY.findall(render_guild_rls_ddl()):
        if name.startswith("plugin_scope_"):
            assert kind == "RESTRICTIVE", (table, name)
            found.setdefault(table, set()).add(name)
    assert set(found) == set(PLUGIN_POLICY_TABLES)


# ---------------------------------------------------------------------------
# A person, for the same surfaces
# ---------------------------------------------------------------------------


async def _member(acting_user, install):
    """An ordinary member of initiative A."""
    return await acting_user(
        guild_role=CommunityRole.member,
        guild=install.guild,
        initiative=install.a,
        initiative_role="member",
    )


async def _as_person(role_session, actor, install):
    s = await role_session("app_user")
    await route_as(s, user_id=actor.user.id, guild_id=install.guild.id)
    return s


async def _rename(s, file_id: int, name: str) -> int:
    result = await s.exec(
        text("UPDATE files SET name = :n WHERE id = :id").bindparams(n=name, id=file_id)
    )
    return result.rowcount


# ---------------------------------------------------------------------------
# Tool content
# ---------------------------------------------------------------------------


async def test_a_file_is_read_with_read_and_changed_with_write(
    session, acting_user, role_session
):
    install = await _install(
        session, acting_user, role_session, granted=["files:write"]
    )
    file = await create_file(session, install.a, install.seat.user, name="Shared")
    await create_resource_grant(session, file, all_initiative_members=True)
    # A write grant naming the install; the scope still decides.
    await create_resource_grant(
        session,
        file,
        plugin_install_id=install.plugin.id,
        level=ResourceAccessLevel.write,
    )

    reader, _ = await _route(role_session, install, ["files:read"])
    assert (await reader.exec(select(File.name))).all() == ["Shared"]
    assert await _rename(reader, file.id, "Changed by a reader") == 0
    await reader.rollback()

    writer, _ = await _route(role_session, install, ["files:write"])
    assert await _rename(writer, file.id, "Changed by a writer") == 1
    await writer.rollback()

    # A member's own write grant still answers for them.
    member = await _member(acting_user, install)
    await create_resource_grant(
        session, file, user=member.user, level=ResourceAccessLevel.write
    )
    person = await _as_person(role_session, member, install)
    assert (await person.exec(select(File.name))).all() == ["Shared"]
    assert await _rename(person, file.id, "Changed by a member") == 1
    await person.rollback()


async def test_a_private_file_is_the_installs_once_a_grant_names_it(
    session, acting_user, role_session
):
    install = await _install(session, acting_user, role_session, granted=["files:read"])
    private = await create_file(session, install.a, install.seat.user, name="Private")

    s, _ = await _route(role_session, install, ["files:read"])
    assert (await s.exec(select(File.name))).all() == []
    await s.rollback()

    await create_resource_grant(
        session,
        private,
        plugin_install_id=install.plugin.id,
        level=ResourceAccessLevel.read,
    )
    s, _ = await _route(role_session, install, ["files:read"])
    assert (await s.exec(select(File.name))).all() == ["Private"]
    await s.rollback()


async def test_creating_asks_the_scope_of_what_is_created(
    session, acting_user, role_session
):
    install = await _install(
        session, acting_user, role_session, granted=["files:write"]
    )

    s, _ = await _route(role_session, install, ["files:write"])
    s.add(Project(initiative_id=install.a.id, name="Not the plug-in's to make"))
    with pytest.raises(DBAPIError, match="row-level security"):
        await s.flush()
    await s.rollback()

    s, _ = await _route(role_session, install, ["files:write"])
    made = File(
        initiative_id=install.a.id,
        name="Made by the plug-in",
        file_type=FileType.lexical,
    )
    s.add(made)
    await s.flush()
    # The database wrote the owner row, naming the install and nobody else.
    grants = (
        await s.exec(
            select(ResourceGrant).where(
                ResourceGrant.resource_type == Tool.file.value,
                ResourceGrant.resource_id == made.id,
            )
        )
    ).all()
    assert [
        (g.level, g.plugin_install_id, g.user_id, g.initiative_id) for g in grants
    ] == [(ResourceAccessLevel.owner, install.plugin.id, None, install.a.id)]
    assert (await s.exec(select(File.name).where(File.id == made.id))).all() == [
        "Made by the plug-in"
    ]
    await s.rollback()


async def test_a_person_creating_a_file_gets_no_install_grant(
    session, acting_user, role_session
):
    install = await _install(
        session, acting_user, role_session, granted=["files:write"]
    )
    person = await _as_person(role_session, install.seat, install)
    made = File(
        initiative_id=install.a.id,
        name="Made by a person",
        file_type=FileType.lexical,
    )
    person.add(made)
    await person.flush()
    rows = (
        await person.exec(
            select(ResourceGrant).where(
                ResourceGrant.resource_type == Tool.file.value,
                ResourceGrant.resource_id == made.id,
            )
        )
    ).all()
    assert [(row.level, row.user_id, row.plugin_install_id) for row in rows] == [
        (ResourceAccessLevel.owner, install.seat.user.id, None)
    ]
    await person.rollback()


@pytest.mark.parametrize("target", ["owned", "unowned", "its_own", "for_a_person"])
async def test_an_install_writes_no_grant_itself(
    session, acting_user, role_session, target
):
    """Every grant row an install's request inserts directly is refused: an
    owner row naming itself on a file it can read, owned or not, and any
    row on a file it has just made."""
    install = await _install(
        session, acting_user, role_session, granted=["files:write"]
    )
    owned = await create_file(session, install.a, install.seat.user)
    await create_resource_grant(session, owned, all_initiative_members=True)
    unowned = await create_file(session, install.a, install.seat.user)
    await create_resource_grant(session, unowned, all_initiative_members=True)
    await route_session_to_guild(session, install.guild.id)
    await session.exec(
        text(
            "DELETE FROM resource_grants WHERE resource_type = 'file' "
            "AND resource_id = :id AND level = 'owner'"
        ).bindparams(id=unowned.id)
    )
    await session.commit()

    s, _ = await _route(role_session, install, ["files:write"])
    if target in ("owned", "unowned"):
        resource_id = (owned if target == "owned" else unowned).id
        row = ResourceGrant(
            resource_type=Tool.file.value,
            resource_id=resource_id,
            plugin_install_id=install.plugin.id,
            level=ResourceAccessLevel.owner,
            initiative_id=install.a.id,
        )
    else:
        made = File(
            initiative_id=install.a.id,
            name="Made by the plug-in",
            file_type=FileType.lexical,
        )
        s.add(made)
        await s.flush()
        row = ResourceGrant(
            resource_type=Tool.file.value,
            resource_id=made.id,
            level=ResourceAccessLevel.read,
            initiative_id=install.a.id,
            **(
                {"all_initiative_members": True}
                if target == "its_own"
                else {"user_id": install.seat.user.id}
            ),
        )
    s.add(row)
    with pytest.raises(DBAPIError, match="row-level security"):
        await s.flush()
    await s.rollback()


async def test_a_narrowed_token_reaches_nothing_of_the_community_as_a_whole(
    session, acting_user, role_session
):
    install = await _install(
        session, acting_user, role_session, granted=["calendars:read"]
    )
    calendar = await create_calendar(
        session, install.a, install.seat.user, name="Community", initiative_id=None
    )
    await create_calendar_event(session, calendar, install.seat.user, title="Picnic")

    calendars = select(Calendar.name).where(Calendar.id == calendar.id)
    events = select(CalendarEvent.title).where(CalendarEvent.calendar_id == calendar.id)

    whole, _ = await _route(role_session, install, ["calendars:read"])
    assert (await whole.exec(calendars)).all() == ["Community"]
    assert (await whole.exec(events)).all() == ["Picnic"]
    await whole.rollback()

    narrowed, _ = await _route(
        role_session, install, ["calendars:read"], initiative_id=install.a.id
    )
    assert (await narrowed.exec(calendars)).all() == []
    assert (await narrowed.exec(events)).all() == []
    await narrowed.rollback()


# ---------------------------------------------------------------------------
# The surfaces that span tools
# ---------------------------------------------------------------------------


async def test_comments_ask_the_comments_scope(session, acting_user, role_session):
    install = await _install(
        session,
        acting_user,
        role_session,
        granted=["files:read", "comments:write"],
    )
    file = await create_file(session, install.a, install.seat.user)
    await create_resource_grant(session, file, all_initiative_members=True)
    await create_comment(session, install.seat.user, file=file, content="First")

    s, _ = await _route(role_session, install, ["files:read"])
    assert (await s.exec(select(Comment.content))).all() == []
    await s.rollback()

    s, _ = await _route(role_session, install, ["files:read", "comments:read"])
    assert (await s.exec(select(Comment.content))).all() == ["First"]
    s.add(Comment(content="From a reader", file_id=file.id))
    with pytest.raises(DBAPIError, match="row-level security"):
        await s.flush()
    await s.rollback()

    s, _ = await _route(role_session, install, ["files:read", "comments:write"])
    s.add(Comment(content="From the plug-in", file_id=file.id))
    await s.flush()
    assert set((await s.exec(select(Comment.content))).all()) == {
        "First",
        "From the plug-in",
    }
    await s.rollback()

    member = await _member(acting_user, install)
    person = await _as_person(role_session, member, install)
    assert (await person.exec(select(Comment.content))).all() == ["First"]
    person.add(Comment(content="From a member", file_id=file.id))
    await person.flush()
    await person.rollback()


async def test_tags_ask_the_tags_scope(session, acting_user, role_session):
    install = await _install(
        session,
        acting_user,
        role_session,
        granted=["tags:write", "files:read"],
    )
    await create_tag(session, install.guild, name="urgent")

    s, _ = await _route(role_session, install, ["files:read"])
    assert (await s.exec(select(Tag.name))).all() == []
    await s.rollback()

    s, _ = await _route(role_session, install, ["tags:read"])
    assert "urgent" in (await s.exec(select(Tag.name))).all()
    s.add(Tag(name="from-a-reader"))
    with pytest.raises(DBAPIError, match="row-level security"):
        await s.flush()
    await s.rollback()

    s, _ = await _route(role_session, install, ["tags:write"])
    s.add(Tag(name="from-the-plug-in"))
    await s.flush()
    await s.rollback()

    member = await _member(acting_user, install)
    person = await _as_person(role_session, member, install)
    assert "urgent" in (await person.exec(select(Tag.name))).all()
    await person.rollback()


# ---------------------------------------------------------------------------
# Structure and subscriptions
# ---------------------------------------------------------------------------


async def test_the_roster_is_read_with_members_read_and_never_written(
    session, acting_user, role_session
):
    install = await _install(
        session,
        acting_user,
        role_session,
        granted=["members:read", "files:read"],
    )

    s, _ = await _route(role_session, install, ["files:read"])
    assert (await s.exec(select(InitiativeMember.user_id))).all() == []
    await s.rollback()

    s, _ = await _route(role_session, install, ["members:read"])
    assert (
        install.seat.user.id in (await s.exec(select(InitiativeMember.user_id))).all()
    )
    with pytest.raises(DBAPIError):
        await s.exec(
            text("DELETE FROM initiative_members WHERE user_id = :u").bindparams(
                u=install.seat.user.id
            )
        )
    await s.rollback()


async def _subscription(session, install, *, plugin_install_id, url: str) -> None:
    await route_session_to_guild(session, install.guild.id)
    await session.exec(
        text(
            "INSERT INTO webhook_subscriptions (initiative_id, plugin_install_id,"
            " target_url, hmac_secret, event_types, created_at, updated_at)"
            " VALUES (:i, :a, :u, 's3cret', ARRAY['files.created'],"
            " now(), now())"
        ).bindparams(i=install.a.id, a=plugin_install_id, u=url)
    )
    await session.commit()


async def test_an_install_sees_only_its_own_subscriptions(
    session, acting_user, role_session
):
    install = await _install(session, acting_user, role_session, granted=["files:read"])
    await _subscription(
        session,
        install,
        plugin_install_id=install.plugin.id,
        url="https://app.test/own",
    )
    await _subscription(
        session, install, plugin_install_id=None, url="https://member.test/theirs"
    )

    s, _ = await _route(role_session, install, ["files:read"])
    urls = (await s.exec(text("SELECT target_url FROM webhook_subscriptions"))).all()
    assert [row[0] for row in urls] == ["https://app.test/own"]
    changed = await s.exec(
        text(
            "UPDATE webhook_subscriptions SET active = false WHERE plugin_install_id IS NULL"
        )
    )
    assert changed.rowcount == 0
    await s.rollback()


async def test_an_install_reaches_the_timer_marks_only_through_its_writes(
    session, acting_user, role_session
):
    install = await _install(session, acting_user, role_session, granted=["tags:write"])
    await route_session_to_guild(session, install.guild.id)
    await session.exec(text("DELETE FROM timer_marks"))
    await session.commit()

    s, _ = await _route(role_session, install, ["tags:write"])
    with pytest.raises(DBAPIError, match="row-level security"):
        await s.exec(
            text("INSERT INTO timer_marks (kind, due_at) VALUES ('reconcile', now())")
        )
    await s.rollback()

    s, _ = await _route(role_session, install, ["tags:write"])
    s.add(Tag(name="arms-a-timer"))
    await s.flush()
    assert (await s.exec(text("SELECT kind FROM timer_marks"))).all() == []
    await s.commit()

    await route_session_to_guild(session, install.guild.id)
    marks = (await session.exec(text("SELECT kind FROM timer_marks"))).all()
    assert marks != []


async def test_every_tool_table_writes_an_installs_owner_row(session, acting_user):
    """The trigger list is stated in its migration; the catalog is what a new
    tool has to match."""
    a = await acting_user(guild_role=CommunityRole.admin)
    rows = await session.exec(
        text(
            "SELECT c.relname FROM pg_trigger t "
            "JOIN pg_class c ON c.oid = t.tgrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = :schema AND NOT t.tgisinternal "
            "AND t.tgfoid = 'public.fn_install_owns_what_it_creates()'::regprocedure"
        ).bindparams(schema=f"guild_{a.guild.id}")
    )
    assert set(rows.all()) >= {(tool.plural,) for tool in Tool}
