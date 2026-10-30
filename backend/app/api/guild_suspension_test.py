"""Access-matrix tests for guild lifecycle status (suspension).

The matrix under test:

- ``read_only``: members keep content READS but writes are denied at the
  Postgres role level (routed into ``guild_<id>_ro``); initiative isolation
  still holds.
- ``suspended``: the guild is in time out. Members AND admins lose every
  surface — content, settings, the seat's routes, leaving — with a generic 403
  (the status is never disclosed to a member). The guild vanishes from
  members' guild lists; admins keep a closed entry that carries the status.
- PAM/break-glass grants override the status entirely: a grantee behaves
  byte-identically against a suspended guild and an active one.
- Joins (invite redemption) are refused for any non-active guild, reported as
  an ordinary expired invite.
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.testing import community_plan
from app.core.messages import GuildMessages
from app.core.tools import Tool
from app.models.platform.access_grant import AccessGrant
from app.models.platform.app_setting import AppSetting
from app.models.platform.guild import Guild, CommunityRole, CommunityStatus
from app.models.platform.user import UserRole
from app.services.platform import guilds as guild_service
from app.services.tenant import task_statuses as task_statuses_service
from app.testing import (
    create_guild,
    create_initiative,
    create_task,
    create_user,
    get_auth_headers,
    route_as,
)
from app.db.request_context import Unattributed


async def _set_status(session: AsyncSession, guild: Guild, status: CommunityStatus):
    """Flip a guild's lifecycle status the way the (future) operator endpoint
    will: status + timestamp on the shared row."""
    guild.status = status.value
    guild.status_changed_at = datetime.now(timezone.utc)
    session.add(guild)
    await session.commit()


async def _live_grant(
    session: AsyncSession, *, user, guild, level: str = "read"
) -> AccessGrant:
    """An approved, unexpired PAM grant (the access_grants_test pattern)."""
    now = datetime.now(timezone.utc)
    grant = AccessGrant(
        user_id=user.id,
        guild_id=guild.id,
        access_level=level,
        status="approved",
        reason="ticket",
        requested_duration_minutes=60,
        requested_by_id=user.id,
        approved_by_id=user.id,
        decided_at=now,
        expires_at=now + timedelta(hours=1),
    )
    session.add(grant)
    await session.commit()
    return grant


# ---------------------------------------------------------------------------
# suspended: members and admins lose every surface
# ---------------------------------------------------------------------------


async def test_member_gets_generic_403_on_suspended_guild(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A member's content requests fail closed with the same generic code a
    non-member gets — the lifecycle status is never disclosed."""
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)

    resp = await client.get(a.g("/initiatives/"), headers=a.headers)
    assert resp.status_code == 200

    await _set_status(session, a.guild, CommunityStatus.suspended)

    resp = await client.get(a.g("/initiatives/"), headers=a.headers)
    assert resp.status_code == 403
    assert resp.json()["detail"] == GuildMessages.COMMUNITY_ACCESS_DENIED


@pytest.mark.parametrize("role", [CommunityRole.admin, CommunityRole.superadmin])
async def test_admin_of_suspended_guild_reaches_nothing(
    client: AsyncClient, session: AsyncSession, acting_user, role: CommunityRole
):
    """An administrator of a suspended guild is refused like any member, on
    content, the settings surface and the seat's routes alike, and cannot
    leave: the membership is kept as it was until the suspension lifts."""
    a = await acting_user(guild_role=role, initiative=True)
    await _set_status(session, a.guild, CommunityStatus.suspended)

    refusals = [
        await client.get(a.g("/initiatives/"), headers=a.headers),
        await client.patch(
            f"/api/v1/communities/{a.guild.id}",
            headers=a.headers,
            json={"name": "Still Ours"},
        ),
        await client.get(
            f"/api/v1/communities/{a.guild.id}/auth/connections", headers=a.headers
        ),
        await client.get(
            f"/api/v1/communities/{a.guild.id}/billing/payment-issue", headers=a.headers
        ),
        await client.post(
            f"/api/v1/communities/{a.guild.id}/billing/handoff", headers=a.headers
        ),
        await client.delete(
            f"/api/v1/communities/{a.guild.id}/leave", headers=a.headers
        ),
    ]
    for resp in refusals:
        assert resp.status_code == 403, (resp.request.url, resp.text)
        assert resp.json()["detail"] == GuildMessages.COMMUNITY_ACCESS_DENIED

    await session.refresh(a.guild)
    assert a.guild.name != "Still Ours"
    resp = await client.get("/api/v1/communities/", headers=a.headers)
    assert a.guild.id in [g["id"] for g in resp.json()], "membership is kept"


@pytest.mark.parametrize(
    "role", [CommunityRole.member, CommunityRole.admin, CommunityRole.superadmin]
)
async def test_a_guild_on_hold_is_gone_for_everyone_in_it(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    monkeypatch,
    handoff_signing_key,
    role: CommunityRole,
):
    """On hold refuses every surface and leaves every list, admins' included.
    The billing handoff is the one way back in, and only for the seat: paying
    is what lifts the hold, and paying is the seat's errand."""
    from app.core.config import settings as app_settings

    monkeypatch.setattr(app_settings, "BILLING_URL", "https://billing.example.com")
    a = await acting_user(guild_role=role, initiative=True)
    await _set_status(session, a.guild, CommunityStatus.on_hold)

    for resp in (
        await client.get(a.g("/initiatives/"), headers=a.headers),
        await client.get(
            f"/api/v1/communities/{a.guild.id}/auth/connections", headers=a.headers
        ),
        await client.get(
            f"/api/v1/communities/{a.guild.id}/billing/summary", headers=a.headers
        ),
        await client.delete(
            f"/api/v1/communities/{a.guild.id}/leave", headers=a.headers
        ),
    ):
        assert resp.status_code == 403, (resp.request.url, resp.text)
        assert resp.json()["detail"] == GuildMessages.COMMUNITY_ACCESS_DENIED

    handoff = await client.post(
        f"/api/v1/communities/{a.guild.id}/billing/handoff", headers=a.headers
    )
    if role is CommunityRole.superadmin:
        assert handoff.status_code == 200, handoff.text
        assert handoff.json()["handoff_token"]
    else:
        assert handoff.status_code == 403, handoff.text
        assert handoff.json()["detail"] == GuildMessages.COMMUNITY_ACCESS_DENIED

    listed = (await client.get("/api/v1/communities/", headers=a.headers)).json()
    assert a.guild.id not in [g["id"] for g in listed]


async def test_suspended_guild_hidden_from_members_listed_for_admins(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The guild list drops a suspended guild for members but keeps it for
    guild admins, carrying the status so the app shows it closed. Members don't
    even see the row."""
    admin = await acting_user(guild_role=CommunityRole.admin)
    member = await acting_user(guild_role=CommunityRole.member, guild=admin.guild)
    await _set_status(session, admin.guild, CommunityStatus.suspended)

    resp = await client.get("/api/v1/communities/", headers=member.headers)
    assert resp.status_code == 200
    assert admin.guild.id not in [g["id"] for g in resp.json()]

    resp = await client.get("/api/v1/communities/", headers=admin.headers)
    assert resp.status_code == 200
    listed = [g for g in resp.json() if g["id"] == admin.guild.id]
    assert listed, "admin must still see the suspended guild"
    assert listed[0]["status"] == "suspended", "admin sees the lifecycle status"


async def test_suspended_guild_names_who_to_contact_for_admins(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The closed entry carries the moderation contact, falling back to the
    general one; a read-only guild's entry carries none."""
    admin = await acting_user(guild_role=CommunityRole.admin)
    other_guild = await create_guild(session, creator=admin.user)
    await _set_status(session, admin.guild, CommunityStatus.suspended)
    await _set_status(session, other_guild, CommunityStatus.read_only)

    settings_row = await session.get(AppSetting, 1) or AppSetting(id=1)
    settings_row.intake_general_contact = "ops@example.com"
    session.add(settings_row)
    await session.commit()

    def entry(body, guild):
        return next(g for g in body if g["id"] == guild.id)

    body = (await client.get("/api/v1/communities/", headers=admin.headers)).json()
    assert entry(body, admin.guild)["contact_email"] == "ops@example.com"
    assert entry(body, other_guild)["contact_email"] is None

    settings_row = await session.get(AppSetting, 1) or AppSetting(id=1)
    settings_row.intake_contacts = {"moderation": "trust@example.com"}
    session.add(settings_row)
    await session.commit()
    body = (await client.get("/api/v1/communities/", headers=admin.headers)).json()
    assert entry(body, admin.guild)["contact_email"] == "trust@example.com"


async def test_read_only_status_visible_to_admin_not_member(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """For a read_only guild (listed for everyone), the status reaches the guild
    admin but is null for a plain member — the hold isn't disclosed to members."""
    admin = await acting_user(guild_role=CommunityRole.admin)
    member = await acting_user(guild_role=CommunityRole.member, guild=admin.guild)
    await _set_status(session, admin.guild, CommunityStatus.read_only)

    admin_row = [
        g
        for g in (
            await client.get("/api/v1/communities/", headers=admin.headers)
        ).json()
        if g["id"] == admin.guild.id
    ][0]
    member_row = [
        g
        for g in (
            await client.get("/api/v1/communities/", headers=member.headers)
        ).json()
        if g["id"] == admin.guild.id
    ][0]
    assert admin_row["status"] == "read_only"
    assert member_row["status"] is None


async def test_establish_guild_access_refuses_suspended(
    session: AsyncSession, acting_user
):
    """The WS/keepalive entry point shares the resolver, so a suspended guild
    refuses the socket path identically (GuildAccessError → 1008)."""
    from app.api.deps import GuildAccessError, establish_guild_access

    a = await acting_user(guild_role=CommunityRole.member)
    await _set_status(session, a.guild, CommunityStatus.suspended)

    with pytest.raises(GuildAccessError):
        await establish_guild_access(session, a.user, a.guild.id)


async def test_establish_for_settings_refuses_suspended_admin(
    session: AsyncSession, acting_user
):
    """The settings surface is refused the same way: nobody in a suspended
    guild is routed into it, whatever the surface."""
    from app.api.deps import GuildAccessError, establish_guild_access

    a = await acting_user(guild_role=CommunityRole.admin)
    await _set_status(session, a.guild, CommunityStatus.suspended)

    with pytest.raises(GuildAccessError):
        await establish_guild_access(session, a.user, a.guild.id, for_settings=True)


# ---------------------------------------------------------------------------
# read_only: reads survive, writes die in Postgres
# ---------------------------------------------------------------------------


async def test_read_only_member_reads_but_writes_denied_at_role_level(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Under ``read_only`` a member still reads content (initiative RLS legs
    intact) but writes are refused: the DAC engine caps the request at read
    (clean app-layer 403), and even without it the INSERT would die in
    Postgres (``guild_<id>_ro`` has no write privileges)."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    await task_statuses_service.ensure_default_statuses(
        session, a.project.id, locale="en"
    )
    status = await task_statuses_service.get_default_status(session, a.project.id)
    await session.commit()

    await _set_status(session, a.guild, CommunityStatus.read_only)

    # Reads: fine.
    resp = await client.get(a.g("/initiatives/"), headers=a.headers)
    assert resp.status_code == 200
    assert any(i["id"] == a.initiative.id for i in resp.json())

    # Writes: refused with the ordinary write-denied code (NOT a
    # status-specific one — the lifecycle status is not disclosed to members).
    resp = await client.post(
        a.g("/tasks/"),
        headers=a.headers,
        json={
            "title": "frozen",
            "project_id": a.project.id,
            "task_status_id": status.id,
        },
    )
    assert resp.status_code == 403, resp.text
    assert resp.json() == Tool.project.write_required().body


async def test_read_only_guild_admin_writes_denied_too(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """``read_only`` freezes GUILD ADMINS exactly like members: the request is
    routed into ``guild_<id>_ro`` regardless of the membership role, so the
    admin RLS leg can read everything but no content write survives."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    await task_statuses_service.ensure_default_statuses(
        session, a.project.id, locale="en"
    )
    status = await task_statuses_service.get_default_status(session, a.project.id)
    task = await create_task(session, a.project, title="before")
    await session.commit()

    await _set_status(session, a.guild, CommunityStatus.read_only)

    resp = await client.post(
        a.g("/tasks/"),
        headers=a.headers,
        json={
            "title": "frozen-admin",
            "project_id": a.project.id,
            "task_status_id": status.id,
        },
    )
    assert resp.status_code == 403, resp.text
    assert resp.json() == Tool.project.write_required().body

    resp = await client.patch(
        a.g(f"/tasks/{task.id}"), headers=a.headers, json={"title": "after"}
    )
    assert resp.status_code == 403, resp.text
    assert resp.json() == Tool.project.write_required().body


async def test_read_only_establishes_content_read_only_context(
    session: AsyncSession, acting_user
):
    """The WS/keepalive entry point resolves ``content_read_only`` for real
    members of a read_only guild — the collaboration socket derives its
    ``can_write`` from this, so a frozen guild can't be edited over Yjs."""
    from app.api.deps import establish_guild_access
    from app.db.session import set_rls_context

    a = await acting_user(guild_role=CommunityRole.admin)
    ctx = await establish_guild_access(session, a.user, a.guild.id)
    assert ctx.content_read_only is False

    # establish_guild_access left the session routed as the guild role, whose
    # column-scoped grant can't write status — reset to the setup baseline.
    await set_rls_context(session, Unattributed())
    await _set_status(session, a.guild, CommunityStatus.read_only)
    ctx = await establish_guild_access(session, a.user, a.guild.id)
    assert ctx.content_read_only is True


async def test_read_only_caps_serialized_permission_level(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A frozen guild turns off every change a row reports under ``can`` — the
    same checks the routes run, and the collaboration socket's ``can_write`` —
    so the UI can't drift into showing editors the backend will refuse.
    Exporting changes nothing and stays. Writable-project filters dry up the
    create pickers the same way."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)

    resp = await client.get(a.g(f"/projects/{a.project.id}"), headers=a.headers)
    assert resp.json()["can"]["edit"] is True

    await _set_status(session, a.guild, CommunityStatus.read_only)

    resp = await client.get(a.g(f"/projects/{a.project.id}"), headers=a.headers)
    assert resp.status_code == 200
    can = resp.json()["can"]
    assert (can["edit"], can["delete"], can["share"]) == (False, False, False)
    assert can["export"] is True

    resp = await client.get(a.g("/projects/?writable=true"), headers=a.headers)
    assert resp.status_code == 200
    assert resp.json()["items"] == []


@pytest.mark.parametrize(
    "role", [CommunityRole.member, CommunityRole.admin], ids=lambda r: r.value
)
async def test_read_only_zeroes_an_initiatives_create_flags(
    client: AsyncClient, session: AsyncSession, acting_user, role
):
    """An initiative's ``can.create`` is empty while the guild is frozen — for
    guild admins too — so tool pages hide their create buttons instead of
    offering writes the database role will refuse. What may be viewed is
    untouched (reads survive read_only)."""
    a = await acting_user(guild_role=role, initiative=True)
    url = a.g(f"/initiatives/{a.initiative.id}")

    resp = await client.get(url, headers=a.headers)
    assert resp.status_code == 200, resp.text
    can = resp.json()["can"]
    assert {Tool.project, Tool.file} <= set(can["create"])

    await _set_status(session, a.guild, CommunityStatus.read_only)

    resp = await client.get(url, headers=a.headers)
    assert resp.status_code == 200, resp.text
    can = resp.json()["can"]
    assert can["create"] == [], "no create flag may survive a frozen guild"
    assert {Tool.project, Tool.file} <= set(can["view"])


async def test_read_only_keeps_initiative_isolation(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The read-only route keeps the membership GUCs, so gate 2 (initiative
    isolation) still filters: a member sees only their own initiatives."""
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    b = await acting_user(
        guild_role=CommunityRole.member, guild=a.guild, initiative=True
    )
    await _set_status(session, a.guild, CommunityStatus.read_only)

    resp = await client.get(a.g("/initiatives/"), headers=a.headers)
    assert resp.status_code == 200
    ids = [i["id"] for i in resp.json()]
    assert a.initiative.id in ids
    assert b.initiative.id not in ids


async def test_read_only_admin_settings_still_writable(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Settings stay writable for guild admins under read_only too."""
    a = await acting_user(guild_role=CommunityRole.admin)
    await _set_status(session, a.guild, CommunityStatus.read_only)

    resp = await client.patch(
        f"/api/v1/communities/{a.guild.id}",
        headers=a.headers,
        json={"description": "billing sorted soon"},
    )
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# PAM / break-glass: the override
# ---------------------------------------------------------------------------


async def test_break_glass_reads_a_suspended_guild(
    client: AsyncClient, session: AsyncSession
):
    """Suspension never locks an operator out of *reaching* a guild.

    What they may do once there is the grant's business, and the same as
    anybody else's: managing an initiative is not something a content grant
    confers, on a suspended guild or an active one.
    """
    owner = await create_user(session, role=UserRole.owner)
    guild = await create_guild(session, creator=owner)
    initiative = await create_initiative(session, guild, owner, name="Frozen Wing")
    await _set_status(session, guild, CommunityStatus.suspended)

    platform_operator = await create_user(session, role=UserRole.operator)
    headers = get_auth_headers(platform_operator)
    resp = await client.post(
        "/api/v1/access-grants/break-glass",
        json={
            "community_id": guild.id,
            "reason": "billing hold review",
            "access_level": "read_write",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text

    # Read.
    resp = await client.get(f"/api/v1/c/{guild.id}/initiatives/", headers=headers)
    assert resp.status_code == 200, resp.text
    assert any(i["name"] == "Frozen Wing" for i in resp.json())

    # And gets no further than any other grantee would.
    resp = await client.patch(
        f"/api/v1/c/{guild.id}/initiatives/{initiative.id}",
        headers=headers,
        json={"description": "reviewed under a grant"},
    )
    assert resp.status_code == 403, resp.text

    # The settings grant beside it reaches the community's configuration,
    # which its own administrators no longer do.
    resp = await client.get(
        f"/api/v1/communities/{guild.id}/auth-settings", headers=headers
    )
    assert resp.status_code == 200, resp.text


async def test_scoped_read_grant_reads_suspended_guild(
    client: AsyncClient, session: AsyncSession
):
    """A scoped PAM read grant (support's request→approve flow) still reads a
    suspended guild — the resolver's grant branch never consults the status."""
    owner = await create_user(session, role=UserRole.owner)
    guild = await create_guild(session, creator=owner)
    await create_initiative(session, guild, owner, name="Held Wing")
    await _set_status(session, guild, CommunityStatus.suspended)

    support = await create_user(session, role=UserRole.support)
    await _live_grant(session, user=support, guild=guild, level="read")

    resp = await client.get(
        f"/api/v1/c/{guild.id}/initiatives/", headers=get_auth_headers(support)
    )
    assert resp.status_code == 200, resp.text
    assert any(i["name"] == "Held Wing" for i in resp.json())


async def test_scoped_read_write_grant_edits_suspended_guild(
    client: AsyncClient, session: AsyncSession
):
    """A scoped read_write grant held by a NON-bypass user keeps its
    edit-existing power against a suspended guild (routed via pam_write, so
    neither the suspension gate nor the read-only role applies)."""
    owner = await create_user(session, role=UserRole.owner)
    guild = await create_guild(session, creator=owner)
    initiative = await create_initiative(session, guild, owner)
    from app.testing import create_project

    project = await create_project(session, initiative, owner)
    task = await create_task(session, project, title="held task")
    await _set_status(session, guild, CommunityStatus.suspended)

    support = await create_user(session, role=UserRole.support)
    await _live_grant(session, user=support, guild=guild, level="read_write")

    resp = await client.patch(
        f"/api/v1/c/{guild.id}/tasks/{task.id}",
        headers=get_auth_headers(support),
        json={"title": "edited under grant"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["title"] == "edited under grant"


# ---------------------------------------------------------------------------
# joins are frozen
# ---------------------------------------------------------------------------


async def _invite_for(session: AsyncSession, guild: Guild) -> str:
    _, code = await guild_service.create_guild_invite(
        session, guild_id=guild.id, created_by=guild.created_by, max_uses=5
    )
    await session.commit()
    return code


@pytest.mark.parametrize(
    "status",
    [CommunityStatus.read_only, CommunityStatus.suspended],
    ids=lambda s: s.value,
)
async def test_invite_redemption_refused_on_non_active_guild(
    client: AsyncClient, session: AsyncSession, acting_user, status
):
    """Joining a non-active guild is refused, reported as a plain expired
    invite (never the guild's lifecycle status)."""
    admin = await acting_user(guild_role=CommunityRole.admin)
    code = await _invite_for(session, admin.guild)
    await _set_status(session, admin.guild, status)

    joiner = await acting_user()
    resp = await client.post(
        "/api/v1/communities/invite/accept",
        headers=joiner.headers,
        json={"code": code},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == GuildMessages.INVITE_EXPIRED_OR_USED

    # The describe endpoint reports it like any expired code.
    resp = await client.get(
        f"/api/v1/communities/invite/{code}", headers=joiner.headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_valid"] is False
    assert body["reason"] == GuildMessages.INVITE_EXPIRED


# ---------------------------------------------------------------------------
# cross-guild "/me" aggregates honor the status
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "role", [CommunityRole.member, CommunityRole.admin], ids=lambda r: r.value
)
async def test_suspended_guild_content_hidden_from_me_aggregates(
    client: AsyncClient, session: AsyncSession, acting_user, role
):
    """/me/* visits each member guild's schema directly (no ``/c/`` choke
    point), so it must apply the same suspension rule itself: a suspended
    guild's content vanishes from the aggregates — for admins too, who keep
    only the settings surface."""
    a = await acting_user(guild_role=role, initiative=True, project=True)
    await create_task(session, a.project, title="mine", assignees=[a.user])

    resp = await client.get("/api/v1/me/tasks", headers=a.headers)
    assert resp.status_code == 200
    assert any(t["title"] == "mine" for t in resp.json()["items"])

    await _set_status(session, a.guild, CommunityStatus.suspended)

    resp = await client.get("/api/v1/me/tasks", headers=a.headers)
    assert resp.status_code == 200
    assert resp.json()["items"] == []


async def test_read_only_guild_content_still_in_me_aggregates(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """read_only keeps reads: the aggregate path routes that guild through the
    SELECT-only role but the content stays visible."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    await create_task(session, a.project, title="mine", assignees=[a.user])
    await _set_status(session, a.guild, CommunityStatus.read_only)

    resp = await client.get("/api/v1/me/tasks", headers=a.headers)
    assert resp.status_code == 200
    assert any(t["title"] == "mine" for t in resp.json()["items"])


# ---------------------------------------------------------------------------
# the member-facing read-only signal
# ---------------------------------------------------------------------------


async def test_content_read_only_flag_serialized_to_members(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Members never see the status itself, but they DO get the effect flag —
    the UI must drop write affordances when the guild is frozen."""
    admin = await acting_user(guild_role=CommunityRole.admin)
    member = await acting_user(guild_role=CommunityRole.member, guild=admin.guild)

    row = [
        g
        for g in (
            await client.get("/api/v1/communities/", headers=member.headers)
        ).json()
        if g["id"] == admin.guild.id
    ][0]
    assert row["content_read_only"] is False

    await _set_status(session, admin.guild, CommunityStatus.read_only)

    row = [
        g
        for g in (
            await client.get("/api/v1/communities/", headers=member.headers)
        ).json()
        if g["id"] == admin.guild.id
    ][0]
    assert row["content_read_only"] is True
    assert row["status"] is None, "the status itself stays undisclosed to members"


# ---------------------------------------------------------------------------
# enforcement columns: operator/billing only, database-enforced
# ---------------------------------------------------------------------------


async def test_guild_admin_patch_cannot_touch_enforcement_fields(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The guild-facing PATCH no longer carries cap/status fields — a payload
    that carries them is ignored (unknown fields), never applied."""
    a = await acting_user(guild_role=CommunityRole.admin)

    resp = await client.patch(
        f"/api/v1/communities/{a.guild.id}",
        headers=a.headers,
        json={
            "name": "Renamed",
            "max_storage_bytes": 5,
            "max_users": 1,
            "status": "active",
            "tier_name": "Enterprise",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "Renamed"
    assert body["max_storage_bytes"] is None
    assert body["max_users"] is None
    assert body["tier_name"] is None

    await session.refresh(a.guild)
    assert (await community_plan(session, a.guild.id))["max_storage_bytes"] is None
    assert a.guild.status == CommunityStatus.active.value


async def test_guild_role_lacks_update_on_enforcement_columns(
    session: AsyncSession, acting_user, role_session
):
    """Grants, not app code, are the boundary: the assumed ``guild_<id>`` role
    can rename its guild, but a direct UPDATE of the lifecycle ``status`` pair
    (column-scoped on ``guilds``, migration 0138) or of the caps and plan label
    (a whole table it holds no write verb on, migration 0179) dies with
    insufficient_privilege."""
    import sqlalchemy.exc
    from sqlalchemy import text as sa_text

    a = await acting_user(guild_role=CommunityRole.admin)

    s = await role_session("app_user")
    await route_as(s, user_id=a.user.id, guild_id=a.guild.id)

    # Identity columns: allowed.
    await s.exec(
        sa_text("UPDATE public.guilds SET name = 'renamed-by-role' WHERE id = :gid"),
        params={"gid": a.guild.id},
    )
    await s.rollback()

    for table, key, column, value in [
        ("public.guilds", "id", "status", "'suspended'"),
        ("public.guilds", "id", "status_changed_at", "now()"),
        ("public.guild_administration", "guild_id", "tier_name", "'Enterprise'"),
    ]:
        await route_as(s, user_id=a.user.id, guild_id=a.guild.id)
        with pytest.raises(sqlalchemy.exc.ProgrammingError, match="permission denied"):
            await s.exec(
                sa_text(f"UPDATE {table} SET {column} = {value} WHERE {key} = :gid"),
                params={"gid": a.guild.id},
            )
        await s.rollback()

    # Nor does it write its plan, which is the deployment's rows of its rules.
    await route_as(s, user_id=a.user.id, guild_id=a.guild.id)
    with pytest.raises(sqlalchemy.exc.ProgrammingError, match="permission denied"):
        await s.exec(
            sa_text(
                "INSERT INTO public.community_rules"
                " (guild_id, key, set_by, amount, updated_at)"
                " VALUES (:gid, 'max_users', 'deployment', 1, now())"
            ),
            params={"gid": a.guild.id},
        )
    await s.rollback()

    # Reading its own caps is allowed — the settings page shows usage against them.
    await route_as(s, user_id=a.user.id, guild_id=a.guild.id)
    readable = (
        await s.exec(
            sa_text(
                "SELECT guild_id FROM public.guild_administration WHERE guild_id = :gid"
            ),
            params={"gid": a.guild.id},
        )
    ).one_or_none()
    assert readable is not None
    await s.rollback()


async def test_platform_guild_status_endpoint_requires_guilds_manage(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The operator endpoint stays capability-gated: a plain member (and the
    guild's own admin) get 403; a platform operator flips the status."""
    a = await acting_user(guild_role=CommunityRole.admin)

    resp = await client.patch(
        f"/api/v1/settings/communities/{a.guild.id}",
        headers=a.headers,
        json={"status": "suspended"},
    )
    assert resp.status_code == 403

    platform_operator = await create_user(session, role=UserRole.operator)
    resp = await client.patch(
        f"/api/v1/settings/communities/{a.guild.id}",
        headers=get_auth_headers(platform_operator),
        json={"status": "suspended"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "suspended"
