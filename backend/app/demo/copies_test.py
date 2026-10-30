"""Pitches, links and copies: opening a link, the pool, expiry and cleanup,
leaving an address, publishing a pitch, and the sales plug-in's API."""

import json
import time
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func
from sqlmodel import select

from app.core import webhook_events
from app.core.config import settings
from app.core.plugin_scopes import LEVEL_SCOPES, InstallLevel
from app.core.messages import DemoMessages, GuildMessages
from app.db import cohorts
from app.demo import accounts, copies, pitches
from app.models.platform.auth_session import AuthSession
from app.models.platform.demo import DemoSandbox, DemoSandboxState, LinkState
from app.models.platform.guild import (
    CommunityRole,
    CommunityStatus,
    Guild,
    GuildInvite,
    GuildMembership,
)
from app.models.platform.user import User
from app.models.tenant.export_job import ExportJob, ExportJobStatus
from app.models.tenant.import_job import ImportJob, ImportJobStatus
from app.models.tenant.initiative import (
    Initiative,
    InitiativeMember,
    InitiativeRoleModel,
)
from app.models.tenant.plugin_event_outbox import PluginEventOutbox
from app.models.tenant.task import Task
from app.schemas.platform.demo import PitchSeat
from app.services.export import worker as export_worker
from app.services.guild_sweeps import Scope, each_guild
from app.services.import_engine import engine as import_engine
from app.services.import_engine import worker as import_worker
from app.services.platform import app_settings as app_settings_service
from app.services.platform import rules
from app.services.platform import users as users_service
from app.services.platform.app_settings import get_app_settings
from app.testing import (
    create_export_job,
    create_guild,
    create_guild_membership,
    create_guild_plugin,
    create_import_job,
    create_initiative_member,
    create_task,
    create_user,
    get_auth_headers,
    route_session_to_guild,
)
from app.testing.plugin_clients import InstalledPlugin, install_headers, install_plugin
from app.services.tenant.webhook_subscriptions_test import _grant_scopes

ADMIN = LEVEL_SCOPES[InstallLevel.community_admin]
REDEEM = "/api/v1/demo/redeem"


@pytest.fixture
async def demo(session, monkeypatch):
    """The demo deployment, as boot records it."""
    monkeypatch.setattr(settings, "DEMO_MODE", True)
    row = await app_settings_service.ensure_settings_row(session)
    row.demo_mode = True
    session.add(row)
    await rules.put(session, "guests_enabled", True)
    await session.commit()


@pytest.fixture
async def pitch(demo, client, acting_user, session):
    """A pitch with a task assigned to a persona, published, and a way to make
    links to it."""
    a = await acting_user(
        guild_role=CommunityRole.superadmin, initiative=True, project=True
    )
    bea = await accounts.create(session, handle="bea#0042")
    await create_guild_membership(session, user=bea, guild=a.guild)
    await create_initiative_member(session, a.initiative, bea)
    await create_task(session, a.project, title="Proof the dough", assignees=[bea])
    queued = await client.get(a.g("/exports/community"), headers=a.headers)
    assert queued.status_code == 202, queued.text
    await export_worker.process_export_jobs()

    host = await accounts.demo_host(session)
    a.guild.created_by = host.id
    session.add(a.guild)
    await session.commit()

    async def link(role: CommunityRole = CommunityRole.admin) -> str:
        _, code = await pitches.make_link(session, pitch_id=a.guild.id, role=role)
        await session.commit()
        return code

    return link, bea.id, a.guild.id


async def _open(
    client, token: str, email: str | None = None
) -> tuple[dict, dict, dict]:
    """Open the link; the answer, the visitor's headers and their account."""
    response = await client.post(REDEEM, json={"token": token, "email": email})
    assert response.status_code == 200, response.text
    opened = response.json()
    headers = {"Authorization": f"Bearer {opened['access_token']}"}
    me = await client.get("/api/v1/me", headers=headers)
    return opened, headers, me.json()


async def _roster(session, guild_id: int) -> dict[int, CommunityRole]:
    return {
        m.user_id: m.role
        for m in await session.exec(
            select(GuildMembership).where(GuildMembership.guild_id == guild_id)
        )
    }


async def test_two_openings_make_two_copies_apart(pitch, client, session):
    link, bea, _source = pitch
    token = await link()
    pooled = {await copies.build_copy(), await copies.build_copy()}

    first, first_headers, first_me = await _open(client, token)
    second, second_headers, second_me = await _open(client, token)

    assert {first["community_id"], second["community_id"]} == pooled
    assert first_me["id"] != second_me["id"]
    assert first_me["demo_community_id"] == first["community_id"]
    expires_at = datetime.fromisoformat(first_me["demo_expires_at"])
    signed_in = (
        await session.exec(
            select(AuthSession).where(AuthSession.user_id == first_me["id"])
        )
    ).one()
    assert signed_in.chain_expires_at <= expires_at
    assert first_me["can_create_communities"] is False
    for opened in (first, second):
        assert bea in await _roster(session, opened["community_id"])
    other = await client.get(
        f"/api/v1/c/{second['community_id']}/initiatives/", headers=first_headers
    )
    assert other.status_code == 403
    created = await client.post(
        "/api/v1/communities/", json={"name": "Mine"}, headers=second_headers
    )
    assert created.status_code == 403
    assert created.json()["detail"] == GuildMessages.COMMUNITY_CREATION_DEMO_ACCOUNT
    # The link opens copies; accepting it as an invite joins nobody to the pitch.
    joined = await client.post(
        "/api/v1/communities/invite/accept",
        json={"code": token},
        headers=second_headers,
    )
    assert joined.status_code == 400
    assert joined.json()["detail"] == GuildMessages.INVITE_NOT_FOUND


@pytest.mark.parametrize(
    "role", [CommunityRole.member, CommunityRole.admin, CommunityRole.superadmin]
)
async def test_a_link_seats_the_visitor_in_its_role(pitch, client, session, role):
    link, _bea, _source = pitch
    token = await link(role)
    copy_id = await copies.build_copy()
    opened, headers, me = await _open(client, token)
    await import_worker.process_import_jobs()

    host = await accounts.demo_host(session)
    roster = await _roster(session, copy_id)
    assert roster[me["id"]] is role
    if role is CommunityRole.superadmin:
        assert host.id not in roster
    else:
        assert roster[host.id] is CommunityRole.superadmin

    await route_session_to_guild(session, copy_id)
    job = await session.get(ImportJob, opened["import_job_id"])
    assert job is not None and job.status == ImportJobStatus.done, job
    assert (await session.exec(select(Task.title))).all() == ["Proof the dough"]
    initiatives = set((await session.exec(select(Initiative.id))).all())
    joined = set(
        (
            await session.exec(
                select(InitiativeMember.initiative_id).where(
                    InitiativeMember.user_id == me["id"]
                )
            )
        ).all()
    )
    assert initiatives and joined == initiatives
    tasks = await client.get(f"/api/v1/c/{copy_id}/tasks/", headers=headers)
    assert tasks.status_code == 200, tasks.text
    assert [t["title"] for t in tasks.json()["items"]] == ["Proof the dough"]


async def test_an_expired_copy_leaves_no_community_and_no_account(
    pitch, client, session, monkeypatch
):
    """A pass whose account deletion fails leaves the copy recorded, and the
    next pass finishes it, its seat holder included."""
    link, _bea, _source = pitch
    copy_id = await copies.build_copy()
    _opened, _headers, me = await _open(client, await link(CommunityRole.superadmin))
    later = datetime.now(timezone.utc) + timedelta(days=pitches.COPY_DAYS, minutes=1)

    async def fails(*_args, **_kwargs) -> None:
        raise RuntimeError("account deletion failed")

    with monkeypatch.context() as patched:
        patched.setattr(users_service, "hard_delete_user", fails)
        await copies.expire_copies(later)
    session.expire_all()
    assert await session.get(DemoSandbox, copy_id) is not None
    assert await session.get(User, me["id"]) is not None

    await copies.expire_copies(later)
    session.expire_all()
    assert await session.get(Guild, copy_id) is None
    assert await session.get(User, me["id"]) is None


async def test_a_failed_opening_spends_nothing(pitch, session, monkeypatch):
    """Staging the archive fails: the copy stays pooled, the link unspent and
    no account is left."""
    link, _bea, _source = pitch
    token = await link()
    copy_id = await copies.build_copy()
    users = (await session.exec(select(func.count()).select_from(User))).one()

    def fails(*_args, **_kwargs) -> str:
        raise OSError("storage unavailable")

    monkeypatch.setattr(import_engine, "stage_payload_file", fails)
    async with cohorts.system_session(None) as system:
        with pytest.raises(OSError):
            await copies.redeem(system, token)

    session.expire_all()
    sandbox = await session.get(DemoSandbox, copy_id)
    assert sandbox is not None and sandbox.state == DemoSandboxState.pooled
    assert sandbox.import_job_id is None
    assert (await session.exec(select(GuildInvite.uses))).one() == 0
    assert (
        await session.exec(
            select(GuildMembership).where(GuildMembership.guest_until.is_not(None))
        )
    ).all() == []
    assert (await session.exec(select(func.count()).select_from(User))).one() == users


async def test_a_link_that_ends_while_opening_opens_nothing(
    pitch, client, session, monkeypatch
):
    """The link is checked again once it is locked."""
    link, _bea, _source = pitch
    token = await link()
    await copies.build_copy()
    answers = iter([True, False])
    monkeypatch.setattr(
        copies.guilds_service, "invite_is_active", lambda _invite: next(answers)
    )

    response = await client.post(REDEEM, json={"token": token})
    assert response.status_code == 404
    assert response.json()["detail"] == DemoMessages.DEMO_LINK_NOT_FOUND


async def test_the_export_gc_keeps_what_a_pitch_publishes(pitch, client, session):
    """Past their expiry, a pitch's newest backup stays and its links still
    open; its older backup and another community's export go."""
    link, _bea, source = pitch
    token = await link()
    host = await accounts.demo_host(session)
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    backup = {
        "source": "community",
        "format": "zip",
        "params": {"mode": "backup"},
        "status": ExportJobStatus.done,
        "expires_at": past,
    }
    other_guild = await create_guild(session)
    other_id = other_guild.id
    superseded = (
        await create_export_job(
            session,
            await session.get(Guild, source),
            host,
            artifact_ref="exports/superseded.zip",
            created_at=past - timedelta(days=8),
            **backup,
        )
    ).id
    other = (
        await create_export_job(
            session, other_guild, host, artifact_ref="exports/other.zip", **backup
        )
    ).id
    await route_session_to_guild(session, source)
    published = (
        await session.exec(select(ExportJob).where(ExportJob.id != superseded))
    ).one()
    published.expires_at = past
    session.add(published)
    await session.commit()
    published_id = published.id

    await each_guild([(Scope.PROVISIONED, export_worker.expire_artifacts)], name="t")

    statuses = {}
    for guild_id, job_id in (
        (source, published_id),
        (source, superseded),
        (other_id, other),
    ):
        session.expunge_all()
        await route_session_to_guild(session, guild_id)
        job = await session.get(ExportJob, job_id)
        assert job is not None
        statuses[job_id] = job.status
    assert statuses == {
        published_id: ExportJobStatus.done,
        superseded: ExportJobStatus.expired,
        other: ExportJobStatus.expired,
    }
    await copies.build_copy()
    await _open(client, token)


async def test_busy_when_the_pool_is_empty(pitch, client):
    link, _bea, _source = pitch
    response = await client.post(REDEEM, json={"token": await link()})
    assert response.status_code == 503
    assert response.json()["detail"] == DemoMessages.DEMO_BUSY


async def test_links_open_nothing_outside_demo_mode(client):
    response = await client.post(REDEEM, json={"token": "anything"})
    assert response.status_code == 404


async def test_making_a_pitch_imports_and_publishes(pitch, session):
    """A pitch made from a bundle: another pitch's published export."""
    _link, bea, source = pitch
    editor = await create_user(session, username="rev", discriminator=1000)
    await session.commit()
    newest = await pitches.newest_export(source)
    assert newest is not None
    async with import_engine.open_payload(source, newest[0]) as bundle:
        assert bundle is not None
        pitch_id = await pitches.make_pitch(
            bundle=bundle, name="Rosie's", editors=["rev#1000"]
        )
    await export_worker.process_export_jobs()

    made = await session.get(Guild, pitch_id)
    assert made is not None and made.name == "Rosie's"
    roster = await _roster(session, pitch_id)
    assert roster[(await accounts.demo_host(session)).id] is CommunityRole.superadmin
    assert roster[editor.id] is CommunityRole.admin
    assert bea in roster
    assert await pitches.newest_export(pitch_id) is not None
    await route_session_to_guild(session, pitch_id)
    assert (await session.exec(select(Task.title))).all() == ["Proof the dough"]


async def test_a_pitch_seats_each_named_account_where_it_says(pitch, session):
    _link, _bea, source = pitch
    named = {
        seat: await create_user(session, username=f"pt-{seat.value}", discriminator=1)
        for seat in PitchSeat
    }
    await session.commit()
    newest = await pitches.newest_export(source)
    assert newest is not None
    async with import_engine.open_payload(source, newest[0]) as bundle:
        assert bundle is not None
        pitch_id = await pitches.make_pitch(
            bundle=bundle,
            name="Seated",
            seats={f"pt-{seat.value}#0001": seat for seat in PitchSeat},
        )
        with pytest.raises(ValueError):
            await pitches.make_pitch(
                bundle=bundle, name="Nobody", seats={"nobody#0001": PitchSeat.member}
            )

    roster = await _roster(session, pitch_id)
    assert roster[named[PitchSeat.member].id] is CommunityRole.member
    assert roster[named[PitchSeat.manager].id] is CommunityRole.member
    assert roster[named[PitchSeat.admin].id] is CommunityRole.admin
    assert roster[named[PitchSeat.superadmin].id] is CommunityRole.superadmin
    assert roster[(await accounts.demo_host(session)).id] is CommunityRole.superadmin
    await route_session_to_guild(session, pitch_id)
    held = (
        await session.exec(
            select(InitiativeMember.user_id, InitiativeRoleModel.name).join(
                InitiativeRoleModel,
                InitiativeRoleModel.id == InitiativeMember.role_id,
            )
        )
    ).all()
    assert (named[PitchSeat.member].id, "member") in held
    assert (named[PitchSeat.manager].id, "project_manager") in held
    assert named[PitchSeat.admin].id not in {user_id for user_id, _ in held}


async def test_a_pitch_whose_import_fails_is_not_left_behind(
    pitch, session, monkeypatch
):
    _link, _bea, source = pitch
    newest = await pitches.newest_export(source)
    assert newest is not None

    async def fails(*_args, **_kwargs) -> None:
        raise RuntimeError("the import left out an entry")

    monkeypatch.setattr(pitches, "_wait_for_import", fails)
    async with import_engine.open_payload(source, newest[0]) as bundle:
        assert bundle is not None
        with pytest.raises(RuntimeError):
            await pitches.make_pitch(bundle=bundle, name="Half made")

    session.expire_all()
    assert (
        await session.exec(select(Guild).where(Guild.name == "Half made"))
    ).all() == []


async def test_cleanup_removes_an_idle_pitch_and_leftovers(demo, session):
    host = await accounts.demo_host(session)
    now = datetime.now(timezone.utc)
    old = now - copies.CLEANUP_AFTER - timedelta(days=10)
    idle = await create_guild(session, creator=host, created_at=old)
    kept = await create_guild(session, creator=host, created_at=old)
    seeded = await create_guild(session, creator=host, created_at=old)
    links = {}
    for name, guild in (("idle", idle), ("live", kept), ("stale", kept)):
        links[name], _ = await pitches.make_link(session, pitch_id=guild.id)
    links["idle"].expires_at = old
    links["stale"].expires_at = old
    session.add_all(links.values())
    leftover = await create_user(session)
    member = await create_user(session)
    await create_guild_membership(session, user=member, guild=kept)
    persona = await accounts.create(session, handle="ned#0007")
    await session.commit()
    ids = {name: link.id for name, link in links.items()}
    idle_id, kept_id, seeded_id = idle.id, kept.id, seeded.id
    leftover_id, member_id, persona_id = leftover.id, member.id, persona.id
    host_id = host.id

    await copies.clean_up()

    session.expire_all()
    assert await session.get(Guild, idle_id) is None
    assert await session.get(Guild, kept_id) is not None
    assert await session.get(Guild, seeded_id) is not None
    remaining = set((await session.exec(select(GuildInvite.id))).all())
    assert remaining == {ids["live"], ids["stale"]}
    assert await session.get(User, leftover_id) is None
    for user_id in (member_id, persona_id, host_id):
        assert await session.get(User, user_id) is not None


async def test_the_pool_loop_cleans_up_once_a_day(monkeypatch):
    runs = []

    async def clean_up() -> None:
        runs.append(True)

    monkeypatch.setattr(copies, "clean_up", clean_up)
    monkeypatch.setattr(copies, "POOL_SIZE", 0)
    monkeypatch.setattr(copies, "_cleaned_at", None)

    await copies.pool_pass()
    await copies.pool_pass()
    assert len(runs) == 1

    a_day_ago = time.monotonic() - copies.CLEANUP_EVERY_SECONDS
    monkeypatch.setattr(copies, "_cleaned_at", a_day_ago)
    await copies.pool_pass()
    assert len(runs) == 2


@pytest.mark.parametrize("swept_first", [False, True])
async def test_a_copy_ends_a_day_after_its_claim_whatever_its_guest_holds(
    pitch, client, session, swept_first
):
    """Its guest's end moved out, or its guest row already taken by the guest
    sweep: the copy and the visitor's account still go when the day is up."""
    link, _bea, _source = pitch
    copy_id = await copies.build_copy()
    _opened, _headers, me = await _open(client, await link())
    membership = (
        await session.exec(
            select(GuildMembership).where(
                GuildMembership.guild_id == copy_id,
                GuildMembership.user_id == me["id"],
            )
        )
    ).one()
    if swept_first:
        await session.delete(membership)
    else:
        membership.guest_until = datetime.now(timezone.utc) + timedelta(days=30)
        session.add(membership)
    await session.commit()

    await copies.expire_copies(
        datetime.now(timezone.utc) + timedelta(days=pitches.COPY_DAYS, minutes=1)
    )

    session.expire_all()
    assert await session.get(Guild, copy_id) is None
    assert await session.get(User, me["id"]) is None


async def test_a_pitch_no_longer_active_opens_nothing(pitch, client, session):
    link, _bea, source = pitch
    token = await link()
    await copies.build_copy()
    guild = await session.get(Guild, source)
    guild.status = CommunityStatus.deleted.value
    session.add(guild)
    await session.commit()

    response = await client.post(REDEEM, json={"token": token})

    assert response.status_code == 404
    assert response.json()["detail"] == DemoMessages.DEMO_LINK_NOT_FOUND


async def test_a_link_used_up_ends_then(pitch, client, session):
    """So the daily cleanup counts from its last opening."""
    _link, _bea, source = pitch
    invite, token = await pitches.make_link(session, pitch_id=source, max_redemptions=1)
    await session.commit()
    invite_id = invite.id
    await copies.build_copy()

    await _open(client, token)

    session.expire_all()
    ended = await session.get(GuildInvite, invite_id)
    assert ended is not None and ended.expires_at <= datetime.now(timezone.utc)


async def test_a_visitor_neither_extends_nor_promotes_itself(pitch, client, session):
    link, _bea, _source = pitch
    copy_id = await copies.build_copy()
    _opened, headers, me = await _open(client, await link(CommunityRole.admin))
    guest_url = f"/api/v1/communities/{copy_id}/guests/{me['id']}"

    extended = await client.patch(guest_url, json={"days": 30}, headers=headers)
    promoted = await client.post(f"{guest_url}/member", headers=headers)

    for response in (extended, promoted):
        assert response.status_code == 400, response.text
        assert response.json()["detail"] == GuildMessages.CANNOT_CHANGE_OWN_ROLE


async def test_a_copys_other_guests_keep_their_accounts(pitch, client, session):
    link, _bea, _source = pitch
    copy_id = await copies.build_copy()
    _opened, _headers, me = await _open(client, await link())
    invited = await create_user(session)
    await create_guild_membership(
        session,
        user=invited,
        guild=await session.get(Guild, copy_id),
        role=CommunityRole.guest,
        guest_until=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    invited_id = invited.id

    await copies.expire_copies(
        datetime.now(timezone.utc) + timedelta(days=pitches.COPY_DAYS, minutes=1)
    )

    session.expire_all()
    assert await session.get(Guild, copy_id) is None
    assert await session.get(User, me["id"]) is None
    assert await session.get(User, invited_id) is not None


# --- publishing a pitch ----------------------------------------------------------


async def test_a_pitch_admin_publishes_it(pitch, client, session, acting_user):
    _link, _bea, source = pitch
    host = await accounts.demo_host(session)
    guild = await session.get(Guild, source)
    await create_guild_membership(
        session, user=host, guild=guild, role=CommunityRole.superadmin
    )
    editor = await acting_user(guild_role=CommunityRole.admin, guild=guild)
    member = await acting_user(guild_role=CommunityRole.member, guild=guild)

    published = await client.post(editor.g("/demo/publish"), headers=editor.headers)
    assert published.status_code == 202, published.text
    refused = await client.post(member.g("/demo/publish"), headers=member.headers)
    assert refused.status_code == 403
    assert refused.json()["detail"] == DemoMessages.DEMO_PITCH_ADMIN_REQUIRED

    before = (await client.get(editor.g("/demo/pitch"), headers=editor.headers)).json()
    await export_worker.process_export_jobs()
    after = (await client.get(member.g("/demo/pitch"), headers=member.headers)).json()
    assert before["is_pitch"] and after["is_pitch"]
    assert after["last_published_at"] > before["last_published_at"]


async def test_a_community_that_is_no_pitch_publishes_nothing(
    client, acting_user, monkeypatch
):
    monkeypatch.setattr(settings, "DEMO_MODE", True)
    a = await acting_user(guild_role=CommunityRole.admin)
    published = await client.post(a.g("/demo/publish"), headers=a.headers)
    assert published.status_code == 404
    assert published.json()["detail"] == DemoMessages.DEMO_PITCH_NOT_FOUND
    status = await client.get(a.g("/demo/pitch"), headers=a.headers)
    assert status.json() == {"is_pitch": False, "last_published_at": None}


# --- the sales plug-in -----------------------------------------------------------


async def _sales_install(session, acting_user, role_session) -> InstalledPlugin:
    """An install the seat granted community admin, in the operations
    community."""
    installed = await install_plugin(
        session,
        acting_user,
        role_session,
        granted=[ADMIN],
        requested=[ADMIN],
    )
    row = await get_app_settings(session)
    row.operations_guild_id = installed.guild.id
    session.add(row)
    await session.commit()
    return installed


def _api(ops: int, path: str) -> str:
    return f"/api/v1/c/{ops}/demo/{path}"


async def test_the_demo_api_answers_only_the_operations_install_with_admin_standing(
    client, session, acting_user, role_session, monkeypatch
):
    installed = await _sales_install(session, acting_user, role_session)
    ops = installed.guild.id
    links_read = _api(ops, "links/read")
    body = {"link_refs": ["dplu_unknown"]}

    monkeypatch.setattr(settings, "DEMO_MODE", False)
    off = await client.post(
        links_read, json=body, headers=install_headers(installed, [ADMIN])
    )
    assert off.status_code == 404

    monkeypatch.setattr(settings, "DEMO_MODE", True)
    allowed = await client.post(
        links_read, json=body, headers=install_headers(installed, [ADMIN])
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.json() == {"links": []}
    # The SDK writes 0 for an install's community; the token's is the one used.
    as_the_sdk = await client.post(
        "/api/v1/c/0/demo/links/read",
        json=body,
        headers=install_headers(installed, [ADMIN]),
    )
    assert as_the_sdk.status_code == 200, as_the_sdk.text
    naive = await client.post(
        _api(ops, "links"),
        json={
            "pitch_ref": "dplu_unknown",
            "expires_at": "2099-01-01T00:00:00",
        },
        headers=install_headers(installed, [ADMIN]),
    )
    assert naive.status_code == 422
    unscoped = await client.post(
        links_read, json=body, headers=install_headers(installed, [])
    )
    assert unscoped.status_code == 403
    await _grant_scopes(role_session, installed, [])
    taken_back = await client.post(
        links_read, json=body, headers=install_headers(installed, [ADMIN])
    )
    assert taken_back.status_code == 403
    await _grant_scopes(role_session, installed, [ADMIN])
    person = await acting_user(guild_role=CommunityRole.admin, guild=installed.guild)
    as_a_person = await client.post(links_read, json=body, headers=person.headers)
    assert as_a_person.status_code == 401

    elsewhere = await create_guild(session)
    row = await get_app_settings(session)
    row.operations_guild_id = elsewhere.id
    session.add(row)
    await session.commit()
    outside = await client.post(
        links_read, json=body, headers=install_headers(installed, [ADMIN])
    )
    assert outside.status_code == 403


async def test_personas_are_ensured_once_and_never_over_a_real_account(
    client, session, acting_user, role_session, monkeypatch
):
    monkeypatch.setattr(settings, "DEMO_MODE", True)
    installed = await _sales_install(session, acting_user, role_session)
    ops = installed.guild.id
    headers = install_headers(installed, [ADMIN])
    body = {"personas": [{"handle": "Bea#0042", "display_name": "Bea"}]}

    first = await client.post(_api(ops, "personas"), json=body, headers=headers)
    assert first.status_code == 200, first.text
    assert first.json() == {"handles": ["bea#0042"]}
    bea = await accounts.by_handle(session, "bea#0042")
    assert bea is not None and bea.age_confirmed_at is not None
    await create_guild_membership(session, user=bea, guild=installed.guild)

    body["personas"][0]["display_name"] = "Bea the baker"
    again = await client.post(_api(ops, "personas"), json=body, headers=headers)
    assert again.status_code == 200, again.text
    session.expire_all()
    assert (await accounts.by_handle(session, "bea#0042")).id == bea.id
    membership = (
        await session.exec(
            select(GuildMembership).where(GuildMembership.user_id == bea.id)
        )
    ).one()
    assert membership.display_name == "Bea the baker"

    await create_user(session, username="sam", discriminator=7)
    taken = await client.post(
        _api(ops, "personas"),
        json={
            "personas": [
                {"handle": "ada#0001", "display_name": "Ada"},
                {"handle": "sam#0007", "display_name": "Sam"},
            ]
        },
        headers=headers,
    )
    assert taken.status_code == 409
    assert taken.json()["detail"] == DemoMessages.DEMO_PERSONA_TAKEN
    assert await accounts.by_handle(session, "ada#0001") is None


async def test_a_listed_pitch_from_the_api_and_its_deletion(
    pitch, client, session, acting_user, role_session
):
    _link, bea, source = pitch
    installed = await _sales_install(session, acting_user, role_session)
    ops = installed.guild.id
    headers = install_headers(installed, [ADMIN])
    await create_user(session, username="rev", discriminator=1000)

    newest = await pitches.newest_export(source)
    assert newest is not None
    async with import_engine.open_payload(source, newest[0]) as bundle:
        assert bundle is not None
        made = await client.post(
            _api(ops, "pitches"),
            data={
                "name": "Alumni",
                "editors": ["rev#1000"],
                "directory": json.dumps(
                    {"categories": ["education"], "join_policy": "request"}
                ),
            },
            files={"bundle": ("alumni.zip", bundle.read_bytes(), "application/zip")},
            headers=headers,
        )
    assert made.status_code == 200, made.text
    pitch_ref = made.json()["pitch_ref"]
    pitch_id = (
        await session.exec(select(Guild.id).where(Guild.name == "Alumni"))
    ).one()
    listed = await session.get(Guild, pitch_id)
    created_at = listed.created_at
    assert listed.is_community and listed.categories == ["education"]
    assert listed.has_adult_content is False
    assert (await rules.platform_values(session))["community_directory_enabled"]
    await route_session_to_guild(session, pitch_id)
    assert set((await session.exec(select(Initiative.join_policy))).all()) == {
        "request"
    }
    await export_worker.process_export_jobs()
    linked = await client.post(
        _api(ops, "links"),
        json={"pitch_ref": pitch_ref},
        headers=headers,
    )
    assert linked.status_code == 200, linked.text
    found = await client.post(
        _api(ops, "pitches/find"),
        json={"names": ["Alumni", "alumni", "Nobody"]},
        headers=headers,
    )
    assert found.status_code == 200, found.text
    assert [
        (one["pitch_ref"], one["name"], datetime.fromisoformat(one["created_at"]))
        for one in found.json()["pitches"]
    ] == [(pitch_ref, "Alumni", created_at)]

    deleted = await client.post(
        _api(ops, "pitches/delete"),
        json={"pitch_ref": pitch_ref},
        headers=headers,
    )
    assert deleted.status_code == 204, deleted.text
    session.expire_all()
    assert await session.get(Guild, pitch_id) is None
    assert (
        await session.exec(
            select(GuildInvite.id).where(GuildInvite.guild_id == pitch_id)
        )
    ).all() == []
    gone = await client.post(
        _api(ops, "pitches/delete"),
        json={"pitch_ref": pitch_ref},
        headers=headers,
    )
    assert gone.status_code == 404
    assert gone.json()["detail"] == DemoMessages.DEMO_PITCH_NOT_FOUND
    after = await client.post(
        _api(ops, "pitches/find"), json={"names": ["Alumni"]}, headers=headers
    )
    assert after.json() == {"pitches": []}


async def test_a_link_from_the_api_reports_its_opening_and_its_leads(
    pitch, client, session, acting_user, role_session
):
    _link, _bea, source = pitch
    installed = await _sales_install(session, acting_user, role_session)
    headers = install_headers(installed, [ADMIN])
    ops = installed.guild.id
    unscoped = await create_guild_plugin(
        session,
        installed.guild,
        installed.seat.user,
        definition={"plugin_kind": "service", "service": {"public_id": "x.other"}},
        listing_uid="OTHERLISTING01",
    )
    unscoped_id = unscoped.id

    newest = await pitches.newest_export(source)
    assert newest is not None
    async with import_engine.open_payload(source, newest[0]) as bundle:
        assert bundle is not None
        made = await client.post(
            _api(ops, "pitches"),
            data={"name": "Rosie's"},
            files={"bundle": ("rosies.zip", bundle.read_bytes(), "application/zip")},
            headers=headers,
        )
    assert made.status_code == 200, made.text
    await export_worker.process_export_jobs()
    linked = await client.post(
        _api(ops, "links"),
        json={"pitch_ref": made.json()["pitch_ref"]},
        headers=headers,
    )
    assert linked.status_code == 200, linked.text
    link_ref = linked.json()["link_ref"]
    token = linked.json()["url"].rpartition("#")[2]

    await copies.build_copy()
    opened, visitor, _me = await _open(client, token, email="Rosie@Example.com")
    copy = await client.get("/api/v1/demo/copy", headers=visitor)
    assert copy.json()["community_id"] == opened["community_id"]
    assert copy.json()["ready"] is False
    await import_worker.process_import_jobs()
    await create_import_job(
        session,
        await session.get(Guild, opened["community_id"]),
        await accounts.demo_host(session),
        status=ImportJobStatus.cancelled,
    )
    copy = await client.get("/api/v1/demo/copy", headers=visitor)
    assert copy.json()["ready"] is True

    async def read() -> dict:
        response = await client.post(
            _api(ops, "links/read"),
            json={"link_refs": [link_ref]},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        (report,) = response.json()["links"]
        return report

    first = await read()
    assert (first["state"], first["redemption_count"]) == ("live", 1)
    assert [lead["email"] for lead in first["leads"]] == ["rosie@example.com"]
    assert first["leads"][0]["id"] and first["leads"][0]["created_at"]
    assert (await read())["leads"] == first["leads"]

    left = await client.post(
        "/api/v1/demo/lead", json={"email": "baker@example.com"}, headers=visitor
    )
    assert left.status_code == 204, left.text
    again = await client.post(
        "/api/v1/demo/lead", json={"email": "baker@example.com"}, headers=visitor
    )
    assert again.status_code == 204, again.text
    assert [lead["email"] for lead in (await read())["leads"]] == [
        "rosie@example.com",
        "baker@example.com",
    ]

    await route_session_to_guild(session, ops)
    events = (
        await session.exec(
            select(
                PluginEventOutbox.install_id,
                PluginEventOutbox.event_type,
                PluginEventOutbox.payload,
            ).order_by(PluginEventOutbox.id)
        )
    ).all()
    assert unscoped_id not in {install_id for install_id, _type, _payload in events}
    assert [(install_id, kind) for install_id, kind, _payload in events] == [
        (installed.plugin.id, webhook_events.DEMO_LINK_OPENED),
        (installed.plugin.id, webhook_events.DEMO_LEAD_LEFT),
        (installed.plugin.id, webhook_events.DEMO_LEAD_LEFT),
    ]
    assert {payload["link_ref"] for _id, _kind, payload in events} == {link_ref}

    revoked = await client.post(
        _api(ops, "links/revoke"), json={"link_ref": link_ref}, headers=headers
    )
    assert revoked.status_code == 204
    assert (await read())["state"] == "expired"


def test_a_used_up_link_says_so_though_it_ended_then():
    now = datetime.now(timezone.utc)
    link = GuildInvite(
        code_hash="x",
        guild_id=1,
        created_by=None,
        max_uses=1,
        uses=1,
        expires_at=now,
    )
    assert pitches.link_state(link, now) is LinkState.used_up
    link.max_uses = None
    assert pitches.link_state(link, now) is LinkState.expired


async def test_a_guest_invited_into_a_copy_has_no_copy_of_its_own(
    pitch, client, session
):
    link, _bea, _source = pitch
    copy_id = await copies.build_copy()
    await _open(client, await link())
    invited = await create_user(session)
    await create_guild_membership(
        session,
        user=invited,
        guild=await session.get(Guild, copy_id),
        role=CommunityRole.guest,
        guest_until=datetime.now(timezone.utc) + timedelta(hours=1),
    )

    copy = await client.get("/api/v1/demo/copy", headers=get_auth_headers(invited))

    assert copy.status_code == 404


async def test_a_copy_whose_import_failed_says_so(pitch, client, session):
    link, _bea, _source = pitch
    copy_id = await copies.build_copy()
    opened, visitor, _me = await _open(client, await link())
    await route_session_to_guild(session, copy_id)
    job = await session.get(ImportJob, opened["import_job_id"])
    assert job is not None
    job.status = ImportJobStatus.failed
    session.add(job)
    await session.commit()

    copy = await client.get("/api/v1/demo/copy", headers=visitor)

    assert copy.json()["ready"] is False
    assert copy.json()["failed"] is True
