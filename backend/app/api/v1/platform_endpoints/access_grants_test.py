"""End-to-end tests for the Privileged Access Management (PAM) endpoints."""

from datetime import UTC, datetime, timedelta

import pytest
from httpx2 import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.capabilities import ROLE_MAX_GRANT_MINUTES
from app.core.tools import Tool
from app.models.platform.access_grant import AccessGrant
from app.models.platform.guild import CommunityRole
from app.testing import (
    Actor,
    create_counter_group,
    create_guild,
    create_project,
)

GRANTS = "/api/v1/access-grants/"


async def _approved_grant(
    session: AsyncSession,
    *,
    grantee: Actor,
    host: Actor,
    level: str = "read",
    reason: str = "ticket",
    expires_in: timedelta = timedelta(hours=1),
) -> AccessGrant:
    """A live (or, with a negative ``expires_in``, a lapsed) approved grant on
    ``host``'s community, approved by ``host``."""
    now = datetime.now(UTC)
    grant = AccessGrant(
        user_id=grantee.user.id,
        guild_id=host.guild.id,
        access_level=level,
        status="approved",
        reason=reason,
        requested_duration_minutes=60,
        requested_by_id=grantee.user.id,
        approved_by_id=host.user.id,
        decided_at=now,
        expires_at=now + expires_in,
    )
    session.add(grant)
    await session.commit()
    return grant


async def _request_access(client: AsyncClient, actor: Actor, guild, **body) -> object:
    """Ask for access to ``guild`` through the request->approve flow."""
    return await client.post(
        GRANTS,
        json={"community_id": guild.id, "reason": "debugging a ticket", **body},
        headers=actor.headers,
    )


async def test_support_requests_owner_approves_and_the_queue_names_handles(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The whole request->approve flow, and how the queue names the people in
    it: an address is masked wherever it appears, on the row the approver reads
    and on the decision they get back. Both enrichment fields are assigned
    after the row is validated, so this covers the masking applying on
    assignment rather than only on the way in.
    """
    owner = await acting_user("owner", email="owner@example.com")
    support = await acting_user("support", email="support@example.com")
    # A community the support user is NOT a member of.
    guild = await create_guild(session)

    requested = await _request_access(client, support, guild, access_level="read")
    assert requested.status_code == 201, requested.text
    grant = requested.json()
    assert grant["status"] == "pending"
    assert grant["is_live"] is False
    assert grant["community_name"] == guild.name
    grant_id = grant["id"]

    # The owner sees it in the full queue (which requires access.approve).
    queue = await client.get(f"{GRANTS}queue?status=pending", headers=owner.headers)
    assert queue.status_code == 200
    row = next(g for g in queue.json()["items"] if g["id"] == grant_id)
    assert row["user"]["id"] == support.user.id
    assert row["user"]["username"] == support.user.username
    assert "user_email" not in row

    approved = await client.post(
        f"{GRANTS}{grant_id}/approve", json={}, headers=owner.headers
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert approved.json()["is_live"] is True
    assert approved.json()["expires_at"] is not None
    assert approved.json()["approved_by"]["username"] == owner.user.username
    assert "@example.com" not in approved.text
    assert "e***m" not in approved.text


async def test_my_requests_respects_limit_and_order(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """``limit`` caps the my-requests history to the most recent N (newest
    first), so a churny requester's list can't grow unbounded."""
    support = await acting_user("support")

    # Five historical grants with strictly increasing requested_at.
    base = datetime.now(UTC) - timedelta(days=5)
    for i in range(5):
        session.add(
            AccessGrant(
                user_id=support.user.id,
                guild_id=(await create_guild(session)).id,
                access_level="read",
                status="expired",
                reason=f"old {i}",
                requested_duration_minutes=60,
                requested_by_id=support.user.id,
                requested_at=base + timedelta(hours=i),
            )
        )
    await session.commit()

    page = await client.get(f"{GRANTS}?mine=true&page_size=3", headers=support.headers)
    assert page.status_code == 200, page.text
    # Newest-first: the three most-recently-requested ("old 4/3/2").
    assert [g["reason"] for g in page.json()["items"]] == ["old 4", "old 3", "old 2"]
    assert page.json()["total_count"] == 5

    # The second page continues where the first left off.
    rest = await client.get(
        f"{GRANTS}?mine=true&page=2&page_size=3", headers=support.headers
    )
    assert rest.status_code == 200, rest.text
    assert [g["reason"] for g in rest.json()["items"]] == ["old 1", "old 0"]


async def test_queue_live_filter_excludes_expired(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """``live=true`` on the approver queue drops approved-but-expired grants so
    the active list pages accurately."""
    host = await acting_user("owner", guild_role=CommunityRole.admin)
    support = await acting_user("support")
    await _approved_grant(session, grantee=support, host=host, reason="live one")
    await _approved_grant(
        session,
        grantee=support,
        host=host,
        reason="stale one",
        expires_in=-timedelta(hours=1),
    )

    queue = await client.get(
        f"{GRANTS}queue?status=approved&live=true", headers=host.headers
    )
    assert queue.status_code == 200, queue.text
    assert [g["reason"] for g in queue.json()["items"]] == ["live one"]


async def test_member_cannot_request_access(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A plain member lacks access.request and is forbidden."""
    member = await acting_user("member")
    guild = await create_guild(session)

    resp = await _request_access(client, member, guild, reason="no caps")

    assert resp.status_code == 403


async def test_requester_cannot_approve_own(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """An operator can both request and approve, but never their own request."""
    operator = await acting_user("operator")
    guild = await create_guild(session)

    requested = await _request_access(client, operator, guild, reason="self")
    assert requested.status_code == 201, requested.text

    resp = await client.post(
        f"{GRANTS}{requested.json()['id']}/approve",
        json={},
        headers=operator.headers,
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "ACCESS_GRANT_CANNOT_APPROVE_OWN"


async def test_a_requester_who_may_no_longer_ask_is_not_approved(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Approval asks about the requester as they stand when it is decided."""
    from app.models.platform.user import User, UserRole

    support = await acting_user("support")
    owner = await acting_user("owner")
    guild = await create_guild(session)
    requested = await _request_access(client, support, guild, reason="ticket")
    assert requested.status_code == 201, requested.text

    demoted = await session.get(User, support.user.id)
    assert demoted is not None
    demoted.role = UserRole.member
    session.add(demoted)
    await session.commit()

    resp = await client.post(
        f"{GRANTS}{requested.json()['id']}/approve", json={}, headers=owner.headers
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "ACCESS_GRANT_GRANTEE_INELIGIBLE"


@pytest.mark.parametrize(
    "tier,minutes,expected",
    [
        pytest.param("support", 480, 201, id="8h-within-supports-cap"),
        pytest.param("moderator", 480, 400, id="8h-over-a-moderators-4h-cap"),
        pytest.param("support", 10_000, 400, id="a-week-over-every-cap"),
    ],
)
async def test_the_window_a_role_may_ask_for(
    client: AsyncClient, session: AsyncSession, acting_user, tier, minutes, expected
):
    """Lower-trust roles get shorter windows: a moderator is capped at 4h,
    support may go to 8h, and the 24h platform ceiling is over both."""
    requester = await acting_user(tier)
    guild = await create_guild(session)

    resp = await _request_access(
        client,
        requester,
        guild,
        reason="a window",
        access_level="moderate",
        requested_duration_minutes=minutes,
    )

    assert resp.status_code == expected, resp.text
    if expected == 201:
        assert resp.json()["requested_duration_minutes"] == minutes
    else:
        assert resp.json()["detail"] == "ACCESS_GRANT_DURATION_TOO_LONG"


async def test_revoke_and_cancel(
    client: AsyncClient, session: AsyncSession, acting_user
):
    owner = await acting_user("owner")
    support = await acting_user("support")
    guild = await create_guild(session)

    # Cancel own pending.
    pending = await _request_access(client, support, guild, reason="cancel me")
    cancelled = await client.delete(
        f"{GRANTS}{pending.json()['id']}", headers=support.headers
    )
    assert cancelled.status_code == 204

    # Approve then revoke.
    requested = await _request_access(client, support, guild, reason="revoke me")
    grant_id = requested.json()["id"]
    await client.post(f"{GRANTS}{grant_id}/approve", json={}, headers=owner.headers)
    revoked = await client.post(f"{GRANTS}{grant_id}/revoke", headers=owner.headers)
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"
    assert revoked.json()["is_live"] is False


@pytest.mark.parametrize(
    "tool,path,make",
    [
        pytest.param(Tool.project, "projects", create_project, id="a-project"),
        pytest.param(
            Tool.counter_group,
            "counter-groups",
            create_counter_group,
            id="a-counter-group",
        ),
    ],
)
async def test_a_grant_reaches_a_tools_content_not_who_it_is_shared_with(
    client: AsyncClient, session: AsyncSession, acting_user, tool, path, make
):
    """A read_write grant carries content read/write, so managing a tool's
    members is answered as a plain 403 with the tool's own code."""
    host = await acting_user("owner", guild_role=CommunityRole.admin, initiative=True)
    support = await acting_user("support")
    target = await acting_user()
    resource = await make(session, host.initiative, host.user)
    await _approved_grant(session, grantee=support, host=host, level="read_write")

    resp = await client.put(
        host.g(f"/{path}/{resource.id}/grants"),
        json=[{"user_id": target.user.id, "level": "write"}],
        headers=support.headers,
    )

    assert resp.status_code == 403, resp.text
    assert resp.json() == tool.grant_cannot_manage_members().body


async def test_grantee_sees_guild_content(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A read grant exposes the guild's initiatives/projects in the list
    endpoints — not just RLS, but the app-layer membership filters too (the
    'empty guild' bug)."""
    host = await acting_user(
        "owner", guild_role=CommunityRole.admin, initiative=True, project=True
    )
    support = await acting_user("support")
    await _approved_grant(session, grantee=support, host=host)

    headers = support.headers
    initiatives = await client.get(host.g("/initiatives/"), headers=headers)
    assert initiatives.status_code == 200, initiatives.text
    assert any(i["id"] == host.initiative.id for i in initiatives.json())

    projects = await client.get(host.g("/projects/"), headers=headers)
    assert projects.status_code == 200, projects.text
    body = projects.json()
    items = body["items"] if isinstance(body, dict) and "items" in body else body
    assert any(p["id"] == host.project.id for p in items)

    # Initiative tool views: a grantee has no membership row, and reads them
    # read-only, never as a manager.
    initiative = await client.get(
        host.g(f"/initiatives/{host.initiative.id}"), headers=headers
    )
    assert initiative.status_code == 200, initiative.text
    assert initiative.json()["can"]["manage"] is False
    assert initiative.json()["can"]["create"] == []

    members = await client.get(
        host.g(f"/initiatives/{host.initiative.id}/members"), headers=headers
    )
    assert members.status_code == 200, members.text

    events = await client.get(
        host.g("/calendar-entries/"),
        params={
            "start_after": "2026-01-01T00:00:00Z",
            "start_before": "2026-02-01T00:00:00Z",
        },
        headers=headers,
    )
    assert events.status_code == 200, events.text

    # Recording an open answers rather than faulting: a grantee's own view
    # is simply not persisted.
    viewed = await client.put(
        host.g(f"/personal-items/view/project/{host.project.id}"), headers=headers
    )
    assert viewed.status_code == 200, viewed.text


@pytest.mark.parametrize("tier", ["support", "operator"])
async def test_a_scoped_read_write_grant_cannot_author_tools(
    client: AsyncClient, session: AsyncSession, acting_user, tier
):
    """A scoped read_write grant edits *existing* content only. Authoring a
    new top-level tool is an initiative-role permission a grantee never holds,
    so the initiative's ``can.create`` is empty (the UI keys its create
    affordances on these flags) while view flags stay on — and an actual create
    attempt is denied.

    Parametrised over a tier that holds ``data.bypass`` and one that does not:
    holding it changes nothing about what a content grant is. It used to be
    answered from the guild-admin branch, so the create flags came back on for
    an operator; a grant reaches existing content, and authoring is not part of
    it whoever holds it.
    """
    host = await acting_user("owner", guild_role=CommunityRole.admin, initiative=True)
    grantee = await acting_user(tier)
    await _approved_grant(session, grantee=grantee, host=host, level="read_write")

    initiative = await client.get(
        host.g(f"/initiatives/{host.initiative.id}"), headers=grantee.headers
    )
    assert initiative.status_code == 200, initiative.text
    can = initiative.json()["can"]
    assert can["manage"] is False
    assert can["create"] == [], "a scoped read_write grant must not author"
    # View access is unaffected — core tools stay visible.
    assert {Tool.project, Tool.file} <= set(can["view"])

    created = await client.post(
        host.g("/projects/"),
        headers=grantee.headers,
        json={"name": "Grantee Project", "initiative_id": host.initiative.id},
    )
    assert created.status_code == 403, created.text


async def test_grant_read_carries_guild_status(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A grantee's own grant list carries the guild's lifecycle status, so an
    operator sees they're acting in a suspended / read-only guild (surfaced in
    the access banner). Not disclosed to plain members — this is operator
    context."""
    from app.models.platform.guild import CommunityStatus

    host = await acting_user("owner", guild_role=CommunityRole.admin)
    support = await acting_user("support")
    await _approved_grant(session, grantee=support, host=host)

    host.guild.status = CommunityStatus.suspended.value
    session.add(host.guild)
    await session.commit()

    mine = await client.get(f"{GRANTS}?mine=true", headers=support.headers)
    assert mine.status_code == 200, mine.text
    rows = [g for g in mine.json()["items"] if g["community_id"] == host.guild.id]
    assert rows and rows[0]["community_status"] == "suspended"


@pytest.mark.parametrize(
    "tier,expected",
    [
        pytest.param("support", 403, id="support-is-refused"),
        pytest.param("moderator", 403, id="moderator-is-refused"),
        pytest.param("operator", 200, id="operator-reads-it"),
        pytest.param("owner", 200, id="owner-reads-it"),
    ],
)
async def test_the_queue_is_read_by_approvers_on_their_own_tier(
    client: AsyncClient, session: AsyncSession, acting_user, tier, expected
):
    """The queue is its own route behind ``access.approve``, read on the
    caller's platform tier: an approver sees somebody else's grant, named."""
    host = await acting_user("owner", guild_role=CommunityRole.admin)
    support = await acting_user("support")
    grant = await _approved_grant(session, grantee=support, host=host)
    reader = await acting_user(tier)

    queue = await client.get(f"{GRANTS}queue", headers=reader.headers)

    assert queue.status_code == expected, queue.text
    if expected == 200:
        row = next(g for g in queue.json()["items"] if g["id"] == grant.id)
        assert row["community_name"] == host.guild.name
        assert row["user"] is not None


async def test_a_grantee_reads_their_own_grant_and_not_somebody_elses(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """One grant, read on the caller's tier: its holder lists it with the
    community it names; another requester is not shown it."""
    host = await acting_user("owner", guild_role=CommunityRole.admin)
    support = await acting_user("support")
    other = await acting_user("support")
    grant = await _approved_grant(session, grantee=support, host=host)

    own = await client.get(GRANTS, headers=support.headers)
    assert own.status_code == 200, own.text
    row = next(g for g in own.json()["items"] if g["id"] == grant.id)
    assert row["community_name"] == host.guild.name

    listed = await client.get(GRANTS, headers=other.headers)
    assert listed.status_code == 200, listed.text
    assert grant.id not in {g["id"] for g in listed.json()["items"]}


@pytest.mark.parametrize(
    "tier,expected",
    [
        pytest.param("member", 403, id="member-cannot-ask"),
        pytest.param("support", 200, id="support"),
        pytest.param("moderator", 200, id="moderator"),
        pytest.param("operator", 200, id="operator"),
    ],
)
async def test_the_request_form_reads_the_callers_ceiling(
    client: AsyncClient, acting_user, monkeypatch, tier, expected
):
    """The longest window a requester may ask for is the deployment's figure
    for their tier, served rather than mirrored."""
    from app.services.platform import access_grants as service

    # A deployment that configured its own figure for one tier.
    monkeypatch.setitem(ROLE_MAX_GRANT_MINUTES, service.UserRole.support, 90)
    reader = await acting_user(tier)

    limits = await client.get(f"{GRANTS}limits", headers=reader.headers)

    assert limits.status_code == expected, limits.text
    if expected != 200:
        return
    assert limits.json() == {
        "max_duration_minutes": service.max_minutes_for_role(service.UserRole(tier))
    }
    if tier == "support":
        assert limits.json()["max_duration_minutes"] == 90


async def test_break_glass_requirements_carry_the_window(
    client: AsyncClient, acting_user
):
    from app.services.platform import access_grants as service

    operator = await acting_user("operator")

    resp = await client.get(f"{GRANTS}break-glass", headers=operator.headers)

    assert resp.status_code == 200, resp.text
    assert resp.json()["max_duration_minutes"] == service.break_glass_max_minutes(
        service.UserRole.operator
    )


async def test_a_grant_past_its_window_is_marked_expired(
    session: AsyncSession, acting_user, capfd
):
    """Liveness is computed, so nothing breaks while the row still says
    approved — but nothing records the grant ending either. The sweep marks it
    and says so, once, and leaves a grant still inside its window alone."""
    from app.core.audit_events import AuditEventType
    from app.services.platform import access_grants as service
    from app.testing.audit import emitted

    host = await acting_user(guild_role=CommunityRole.admin)
    other_host = await acting_user(guild_role=CommunityRole.admin)
    grantee = await acting_user("support")
    lapsed = await _approved_grant(
        session, grantee=grantee, host=host, expires_in=timedelta(minutes=-5)
    )
    live = await _approved_grant(session, grantee=grantee, host=other_host)
    capfd.readouterr()

    assert await service.expire_due(session) == 1
    await session.commit()
    assert await service.expire_due(session) == 0
    await session.commit()

    await session.refresh(lapsed)
    await session.refresh(live)
    assert lapsed.status == "expired"
    assert live.status == "approved"
    decided = emitted(capfd, AuditEventType.ACCESS_GRANT_DECIDED)
    assert [(e["target"]["id"], e["detail"]["decision"]) for e in decided] == [
        (lapsed.id, "expired")
    ]
    assert decided[0]["actor_user_id"] is None


async def test_a_revoked_grant_is_not_recorded_as_expiring(
    session: AsyncSession, acting_user, capfd
):
    """A grant that ended some other way already has its ending recorded; the
    sweep claims only grants still marked approved."""
    from app.core.audit_events import AuditEventType
    from app.services.platform import access_grants as service
    from app.testing.audit import emitted

    host = await acting_user(guild_role=CommunityRole.admin)
    grantee = await acting_user("support")
    revoked = await _approved_grant(
        session, grantee=grantee, host=host, expires_in=timedelta(minutes=-5)
    )
    revoked.status = "revoked"
    session.add(revoked)
    await session.commit()
    capfd.readouterr()

    assert await service.expire_due(session) == 0
    await session.commit()

    await session.refresh(revoked)
    assert revoked.status == "revoked"
    assert emitted(capfd, AuditEventType.ACCESS_GRANT_DECIDED) == []


async def test_a_moderate_grant_is_for_those_who_moderate(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Reading what the platform holds is moderation work, and it is all a
    moderator may ask for: never a plain read, an edit or the settings."""
    guild = await create_guild(session)
    moderator = await acting_user("moderator")
    for body in (
        {"access_level": "read"},
        {"access_level": "read_write"},
        {"settings_level": "admin"},
        {"access_level": "moderate", "settings_level": "superadmin"},
    ):
        refused = await _request_access(client, moderator, guild, **body)
        assert refused.status_code == 403, body
        assert refused.json()["detail"] == "ACCESS_GRANT_ONLY_MODERATE"

    asked = await _request_access(client, moderator, guild, access_level="moderate")
    assert asked.status_code in (200, 201), asked.text
    assert asked.json()["access_level"] == "moderate"


async def test_a_moderate_grant_is_never_self_issued(
    session: AsyncSession, acting_user
):
    from app.core.messages import AccessGrantMessages
    from app.models.platform.access_grant import AccessLevel
    from app.schemas.platform.access_grant import BreakGlassCreate
    from app.services.platform import access_grants as service

    guild = await create_guild(session)
    operator = await acting_user("operator")
    with pytest.raises(service.AccessGrantError) as refused:
        await service.break_glass(
            session,
            actor=operator.user,
            payload=BreakGlassCreate(community_id=guild.id, reason="looking quickly"),
            level=AccessLevel.moderate.value,
        )
    assert refused.value.code == AccessGrantMessages.MODERATE_NOT_HELD
