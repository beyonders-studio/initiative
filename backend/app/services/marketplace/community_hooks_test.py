"""The hooks about a community's install: written, sent, retried, settled.

Each is held to what a plug-in's kit relies on: a lifecycle token naming the
hook, the community by the plug-in's own reference and where it stands; a 2xx
or a 404 settles it for good and anything else is asked again later; an
``erase`` drops the plug-in's references once it is done with; a state hook
says the state when it is sent; and a hook is written, and its timer armed, in
the transaction that caused it, so a rollback sends nothing.

The ``plugin_hooks`` sweep timer drives delivery: a hook written arms it, and
its visit (:func:`community_hooks.visit`) sends what is due.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
from datetime import datetime, timedelta, timezone

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from sqlalchemy import text, update
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.core.config import settings
from app.db import cohorts, post_commit
from app.db.request_context import SystemGuild, Unattributed
from app.db.session import set_rls_context
from app.models.platform.guild import CommunityStatus
from app.models.platform.identity_ref import IdentityEntity
from app.models.platform.plugin_community_hook import PluginCommunityHook
from app.models.platform.plugin_install import PluginInstall
from app.services import safe_http, sweep_timers
from app.services.marketplace import community_hooks, plugin_installs, plugin_refs
from app.services.marketplace.registration_lookup import invalidate_registrations
from app.services.tenant import plugin_connection_flows
from app.services.webhook_target_url import ValidatedTarget
from app.testing import (
    create_guild,
    create_guild_plugin,
    create_plugin_service_registration,
    create_user,
    emitted,
)

PUBLIC_ID = "tests.hooked"
LISTING_UID = "TESTAPP0000071"
OTHER_ID = "tests.other"
OTHER_UID = "TESTAPP0000072"

_KEY = ed25519.Ed25519PrivateKey.generate()
_PEM = _KEY.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode()


class Plugins:
    """Every plug-in's hook route: answers each call to a host with the next
    status in that host's list (the last repeating), and keeps what it was
    sent."""

    def __init__(self, **answers: list[int]) -> None:
        self.answers = {host: list(statuses) for host, statuses in answers.items()}
        self.calls: list[tuple[str, str, dict, dict]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        # The request is sent to the address the name resolved to; the name
        # rides in the Host header.
        host = request.headers["host"].split(".")[0]
        token = request.headers["authorization"].removeprefix("Bearer ")
        claims = jwt.decode(
            token,
            _KEY.public_key(),
            algorithms=["EdDSA"],
            options={"verify_aud": False},
        )
        self.calls.append(
            (host, request.url.path, claims, json.loads(request.content or b"{}"))
        )
        statuses = self.answers.get(host, [204])
        status = statuses.pop(0) if len(statuses) > 1 else statuses[0]
        return httpx.Response(status)

    def paths(self, host: str = "hooked") -> list[str]:
        return [path for called, path, _, _ in self.calls if called == host]


@pytest.fixture(autouse=True)
def _signing(monkeypatch):
    monkeypatch.setattr(settings, "PLUGIN_PLATFORM_SIGNING_PRIVATE_KEY_PEM", _PEM)
    monkeypatch.setattr(settings, "PLUGIN_PLATFORM_SIGNING_KEY_ID", "plugin-platform-1")

    async def resolve(url: str, *, allow_private: bool = False) -> ValidatedTarget:
        return ValidatedTarget(
            hostname=httpx.URL(url).host,
            addresses=(ipaddress.ip_address("93.184.216.34"),),
        )

    monkeypatch.setattr(safe_http, "resolve_validated_target_async", resolve)


def _answering(monkeypatch, **answers: list[int]) -> Plugins:
    plugins = Plugins(**answers)
    monkeypatch.setattr(
        plugin_connection_flows, "http_transport", httpx.MockTransport(plugins.handle)
    )
    return plugins


async def _register(session: AsyncSession, public_id: str, listing_uid: str, host: str):
    await create_plugin_service_registration(
        session,
        public_id=public_id,
        listing_uid=listing_uid,
        base_url=f"https://{host}.example.test",
    )


async def _install(session, guild, user, public_id: str, listing_uid: str):
    return await create_guild_plugin(
        session,
        guild,
        user,
        definition={"plugin_kind": "service", "service": {"public_id": public_id}},
        listing_uid=listing_uid,
    )


async def _setup(session: AsyncSession, *, other: bool = False):
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    install = await _install(session, guild, user, PUBLIC_ID, LISTING_UID)
    await _register(session, PUBLIC_ID, LISTING_UID, "hooked")
    if other:
        await _install(session, guild, user, OTHER_ID, OTHER_UID)
        await _register(session, OTHER_ID, OTHER_UID, "other")
    await session.commit()
    invalidate_registrations()
    await _all_told(session, guild.id)
    return user, guild, install


async def _all_told(session: AsyncSession, guild_id: int) -> None:
    """Mark every install of the community as told its status, so a visit
    sends only the hooks a test writes."""
    await set_rls_context(session, Unattributed())
    await session.exec(
        update(PluginInstall)
        .where(PluginInstall.guild_id == guild_id)
        .values(community_status_sent=CommunityStatus.active.value)
    )
    await session.commit()


async def _visit(guild_id: int):
    """One visit of the community's ``plugin_hooks`` sweep, as the timer
    worker makes it."""
    async with cohorts.system_session(guild_id) as session:
        await set_rls_context(session, SystemGuild(guild_id))
        due = await community_hooks.visit(session, guild_id)
        await session.commit()
    return due


async def _hooks(session: AsyncSession, guild_id: int) -> list[PluginCommunityHook]:
    await set_rls_context(session, Unattributed())
    rows = (
        await session.exec(
            select(PluginCommunityHook)
            .where(PluginCommunityHook.guild_id == guild_id)
            .order_by(PluginCommunityHook.id)
            .execution_options(populate_existing=True)
        )
    ).all()
    await session.commit()
    return list(rows)


async def _timers(session: AsyncSession, guild_id: int) -> int:
    await set_rls_context(session, Unattributed())
    count = (
        await session.exec(
            text(
                "SELECT count(*) FROM community_timers"
                " WHERE community_id = :g AND kind = :k"
            ).bindparams(g=guild_id, k=community_hooks.KIND)
        )
    ).one()[0]
    await session.commit()
    return count


async def _come_due(session: AsyncSession, guild_id: int) -> None:
    """As if every retry's wait had passed."""
    await set_rls_context(session, Unattributed())
    await session.exec(
        update(PluginCommunityHook)
        .where(PluginCommunityHook.guild_id == guild_id)
        .values(next_attempt_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    )
    await session.commit()


async def _deliver(guild_id: int, public_id: str = PUBLIC_ID, **kwargs) -> bool:
    return await community_hooks.deliver_community_hook(
        guild_id=guild_id, public_id=public_id, **kwargs
    )


class TestWritingArmsTheTimer:
    async def test_a_hook_written_arms_the_sweep_and_its_visit_sends_it(
        self, session, monkeypatch
    ):
        _user, guild, install = await _setup(session)
        plugins = _answering(monkeypatch)

        assert await _deliver(guild.id, hook="installed")
        assert await _timers(session, guild.id) == 1
        # The sweep calls plug-ins, so it runs in the outward lane.
        await sweep_timers.process_due_timers(outward=True)

        ((_, path, claims, body),) = plugins.calls
        assert path == "/v1/hooks/installed"
        assert body == {}
        assert claims["aud"] == f"initiative-plugin:{PUBLIC_ID}"
        assert claims["scope"] == "lifecycle"
        assert claims["hook"] == "installed"
        assert claims["community_status"] == "active"
        assert claims["plugin_install_id"] == install.id
        assert claims["community_ref"] == await plugin_refs.ensure_plugin_guild_ref(
            guild_id=guild.id, public_id=PUBLIC_ID
        )
        (row,) = await _hooks(session, guild.id)
        assert (row.outcome, row.attempts) == ("delivered", 1)

    async def test_a_rollback_writes_and_arms_nothing(self, session):
        _user, guild, _install = await _setup(session)

        async with cohorts.system_session(guild.id) as routed:
            await set_rls_context(routed, SystemGuild(guild.id))
            assert await community_hooks.queue_community_hooks(
                routed, guild_id=guild.id, public_id=PUBLIC_ID, hooks=("erase",)
            )
            await routed.rollback()
        assert await _hooks(session, guild.id) == []
        assert await _timers(session, guild.id) == 0

        async with cohorts.system_session(guild.id) as routed:
            await set_rls_context(routed, SystemGuild(guild.id))
            await community_hooks.queue_community_hooks(
                routed, guild_id=guild.id, public_id=PUBLIC_ID, hooks=("erase",)
            )
            await routed.commit()
        assert [row.hook for row in await _hooks(session, guild.id)] == ["erase"]
        assert await _timers(session, guild.id) == 1

    async def test_only_a_community_hook_is_written(self, session):
        _user, guild, _install = await _setup(session)

        with pytest.raises(community_hooks.UnknownCommunityHookError):
            await _deliver(guild.id, hook="after_connect")
        assert await _hooks(session, guild.id) == []

    async def test_an_erase_reaches_names_whose_registration_is_gone(
        self, session, monkeypatch
    ):
        """Uninstalling with erase after the registration was deleted still
        writes the erase, under the public id the install pinned, which is what
        the references key on. It cannot be sent, and once it is given up on
        the names are dropped, so a registration made again finds none."""
        from app.models.platform.plugin_service_registration import (
            PluginServiceRegistration,
        )
        from app.models.tenant.guild_plugin import GuildPlugin
        from app.services.tenant import guild_plugins as guild_plugins_service

        user, guild, install = await _setup(session)
        guild_id, install_id, user_id = guild.id, install.id, user.id
        member = await plugin_refs.ensure_plugin_ref(
            guild_id=guild_id, public_id=PUBLIC_ID, user_id=user_id
        )
        await set_rls_context(session, Unattributed())
        registration = (
            await session.exec(
                select(PluginServiceRegistration).where(
                    PluginServiceRegistration.public_id == PUBLIC_ID
                )
            )
        ).one()
        await session.delete(registration)
        await session.commit()
        invalidate_registrations()

        await set_rls_context(session, SystemGuild(guild_id))
        plugin = await session.get(GuildPlugin, install_id)
        await guild_plugins_service.uninstall_plugin(
            session, plugin, actor_user_id=user_id, erase=True
        )
        await session.commit()
        written = [(row.public_id, row.hook) for row in await _hooks(session, guild_id)]
        assert written == [(PUBLIC_ID, "uninstalled"), (PUBLIC_ID, "erase")]

        monkeypatch.setattr(community_hooks, "MAX_ATTEMPTS", 1)
        await _visit(guild_id)
        uninstalled, erase = await _hooks(session, guild_id)
        assert uninstalled.last_error == "the plug-in is not reachable here"
        await _visit(guild_id)
        _uninstalled, erase = await _hooks(session, guild_id)
        assert erase.outcome == "gave_up"
        assert (
            await plugin_refs.resolve_plugin_ref(session, ref=member, guild_id=guild_id)
            is None
        )


class TestSending:
    async def test_a_404_means_the_hook_is_not_taken_and_is_not_asked_again(
        self, session, monkeypatch
    ):
        _user, guild, _install = await _setup(session)
        plugins = _answering(monkeypatch, hooked=[404])

        await _deliver(guild.id, hook="uninstalled")
        await _visit(guild.id)
        await _come_due(session, guild.id)
        await _visit(guild.id)

        assert len(plugins.calls) == 1
        (row,) = await _hooks(session, guild.id)
        assert row.outcome == "not_taken"

    async def test_anything_else_is_asked_again_after_a_while(
        self, session, monkeypatch
    ):
        _user, guild, _install = await _setup(session)
        plugins = _answering(monkeypatch, hooked=[500, 204])

        await _deliver(guild.id, hook="installed")
        due = await _visit(guild.id)
        (row,) = await _hooks(session, guild.id)
        assert row.done_at is None and row.attempts == 1
        assert "500" in (row.last_error or "")
        # The visit answers the retry as its next due time.
        assert due == row.next_attempt_at > datetime.now(timezone.utc)

        await _visit(guild.id)
        assert len(plugins.calls) == 1

        await _come_due(session, guild.id)
        await _visit(guild.id)
        (row,) = await _hooks(session, guild.id)
        assert (row.outcome, row.attempts) == ("delivered", 2)

    async def test_an_attempt_is_cut_off_before_its_claim_can_lapse(
        self, session, monkeypatch
    ):
        _user, guild, _install = await _setup(session)

        async def trickling(**_kwargs):
            await asyncio.sleep(5)

        monkeypatch.setattr(community_hooks, "_send", trickling)
        monkeypatch.setattr(community_hooks, "SEND_DEADLINE", timedelta(seconds=0.05))
        assert community_hooks.LEASE / 2 == timedelta(minutes=1)

        await _deliver(guild.id, hook="installed")
        await _visit(guild.id)
        (row,) = await _hooks(session, guild.id)
        assert row.done_at is None and row.attempts == 1
        assert row.last_error == "TimeoutError"
        assert row.claimed_until is None

    async def test_a_sender_whose_claim_was_taken_records_nothing(
        self, session, monkeypatch
    ):
        _user, guild, _install = await _setup(session)
        await _deliver(guild.id, hook="installed")
        mine = await community_hooks._claim_head(guild.id, PUBLIC_ID)
        assert mine is not None

        # Its claim lapsed and another sender took the plug-in.
        theirs = datetime.now(timezone.utc) + community_hooks.LEASE
        await set_rls_context(session, Unattributed())
        await session.exec(
            update(PluginCommunityHook)
            .where(PluginCommunityHook.id == mine.id)
            .values(claimed_until=theirs)
        )
        await session.commit()
        assert not await community_hooks._settle(
            mine, community_hooks._Outcome("delivered")
        )
        (row,) = await _hooks(session, guild.id)
        assert (row.done_at, row.attempts, row.claimed_until) == (None, 0, theirs)

        # One whose claim ran out records nothing either.
        mine.claimed_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        assert not await community_hooks._settle(
            mine, community_hooks._Outcome("delivered")
        )
        (row,) = await _hooks(session, guild.id)
        assert row.done_at is None

    async def test_one_plugins_hooks_go_in_the_order_they_were_written(
        self, session, monkeypatch
    ):
        _user, guild, _install = await _setup(session)
        plugins = _answering(monkeypatch, hooked=[500, 204])

        for hook in ("uninstalled", "installed"):
            await _deliver(guild.id, hook=hook)
        await _visit(guild.id)
        # The second waits behind the first.
        assert plugins.paths() == ["/v1/hooks/uninstalled"]

        await _come_due(session, guild.id)
        await _visit(guild.id)
        assert plugins.paths() == [
            "/v1/hooks/uninstalled",
            "/v1/hooks/uninstalled",
            "/v1/hooks/installed",
        ]

    async def test_a_plugin_that_is_down_holds_back_only_its_own(
        self, session, monkeypatch
    ):
        _user, guild, _install = await _setup(session, other=True)
        plugins = _answering(monkeypatch, hooked=[503])

        for public_id in (PUBLIC_ID, OTHER_ID):
            await _deliver(guild.id, public_id=public_id, hook="installed")
            await _deliver(guild.id, public_id=public_id, hook="uninstalled")
        await _visit(guild.id)

        assert plugins.paths("hooked") == ["/v1/hooks/installed"]
        assert plugins.paths("other") == [
            "/v1/hooks/installed",
            "/v1/hooks/uninstalled",
        ]

    async def test_the_next_visit_is_due_at_the_heads_retry(self, session, monkeypatch):
        """A hook queued behind one waiting out a retry goes when that one does,
        so it does not bring the community's next visit forward."""
        _user, guild, _install = await _setup(session)
        _answering(monkeypatch, hooked=[503])

        await _deliver(guild.id, hook="installed")
        due = await _visit(guild.id)
        await _deliver(guild.id, hook="uninstalled")
        head, _behind = await _hooks(session, guild.id)

        assert due == head.next_attempt_at
        outside = await community_hooks.due_outside(
            guild.id, datetime.now(timezone.utc)
        )
        assert outside == head.next_attempt_at

    async def test_a_state_waiting_to_be_superseded_is_due_now(
        self, session, monkeypatch
    ):
        _user, guild, _install = await _setup(session)
        _answering(monkeypatch, hooked=[503])

        await _deliver(guild.id, hook="community_status")
        await _visit(guild.id)
        await _deliver(guild.id, hook="community_status")

        due = await community_hooks.due_outside(guild.id, datetime.now(timezone.utc))
        assert due is not None and due <= datetime.now(timezone.utc)

    async def test_it_is_given_up_on_in_the_end(self, session, monkeypatch):
        _user, guild, _install = await _setup(session)
        _answering(monkeypatch, hooked=[503])
        monkeypatch.setattr(community_hooks, "MAX_ATTEMPTS", 2)

        await _deliver(guild.id, hook="installed")
        await _visit(guild.id)
        await _come_due(session, guild.id)
        await _visit(guild.id)
        (row,) = await _hooks(session, guild.id)
        assert (row.outcome, row.attempts) == ("gave_up", 2)


class TestState:
    async def test_the_current_status_goes_and_an_old_failure_never_holds_it(
        self, session, monkeypatch
    ):
        """An older ``community_status`` that failed and waits out its backoff
        is overtaken by a newer one, which says the status as it is when it is
        sent."""
        _user, guild, _install = await _setup(session)
        plugins = _answering(monkeypatch, hooked=[500, 204])

        await _deliver(guild.id, hook="community_status")
        await _visit(guild.id)
        guild.status = CommunityStatus.on_hold.value
        session.add(guild)
        await session.commit()
        await _deliver(guild.id, hook="community_status")
        await _visit(guild.id)

        assert [body for _, _, _, body in plugins.calls] == [
            {"status": "active"},
            {"status": "on_hold"},
        ]
        older, newer = await _hooks(session, guild.id)
        assert (older.outcome, newer.outcome) == ("superseded", "delivered")

    async def test_a_status_counts_as_told_only_once_it_is_answered(
        self, session, monkeypatch
    ):
        """An install whose plug-in has no registration here is not told, and
        is not marked as told, so a registration made later gets the status."""
        user = await create_user(session)
        guild = await create_guild(session, creator=user)
        install = await _install(session, guild, user, PUBLIC_ID, LISTING_UID)
        await session.commit()
        await plugin_installs.record(guild.id, install)
        plugins = _answering(monkeypatch)

        assert (
            await community_hooks.due_outside(guild.id, datetime.now(timezone.utc))
            is None
        )
        await _visit(guild.id)
        assert await _hooks(session, guild.id) == []
        assert await _sent(session, guild.id) is None

        await _register(session, PUBLIC_ID, LISTING_UID, "hooked")
        await session.commit()
        invalidate_registrations()
        # The daily reconcile sees an install not told, now that it can be.
        assert await community_hooks.due_outside(guild.id, datetime.now(timezone.utc))
        await _visit(guild.id)

        assert [body for _, _, _, body in plugins.calls] == [{"status": "active"}]
        assert await _sent(session, guild.id) == "active"
        await _visit(guild.id)
        assert len(plugins.calls) == 1

    async def test_a_status_change_arms_the_sweep_once_it_commits(self, session):
        from app.services.platform import guilds as guilds_service

        _user, guild, _install = await _setup(session)
        guild_id = guild.id

        await guilds_service.set_guild_status(
            session, guild_id=guild_id, status=CommunityStatus.read_only
        )
        await session.rollback()
        await post_commit.settle_all()
        assert await _timers(session, guild_id) == 0

        await guilds_service.set_guild_status(
            session, guild_id=guild_id, status=CommunityStatus.read_only
        )
        await session.commit()
        await post_commit.settle_all()
        assert await _timers(session, guild_id) == 1


async def _sent(session: AsyncSession, guild_id: int):
    await set_rls_context(session, Unattributed())
    value = (
        await session.exec(
            select(PluginInstall.community_status_sent).where(
                PluginInstall.guild_id == guild_id
            )
        )
    ).first()
    await session.commit()
    return value


class TestErasing:
    async def test_the_references_go_only_once_it_has_answered(
        self, session, monkeypatch, capfd
    ):
        user, guild, _install = await _setup(session)
        member = await plugin_refs.ensure_plugin_ref(
            guild_id=guild.id, public_id=PUBLIC_ID, user_id=user.id
        )
        community = await plugin_refs.ensure_plugin_guild_ref(
            guild_id=guild.id, public_id=PUBLIC_ID
        )
        plugins = _answering(monkeypatch, hooked=[502, 204])

        await _deliver(guild.id, hook="erase")
        await _visit(guild.id)
        assert await community_hooks.erase_pending(
            guild_id=guild.id, public_id=PUBLIC_ID
        )
        assert await plugin_refs.resolve_plugin_ref(
            session, ref=member, guild_id=guild.id
        )
        assert plugins.calls[0][2]["community_ref"] == community

        await _come_due(session, guild.id)
        await _visit(guild.id)
        assert (
            await plugin_refs.resolve_plugin_ref(session, ref=member, guild_id=guild.id)
            is None
        )
        assert not await community_hooks.erase_pending(
            guild_id=guild.id, public_id=PUBLIC_ID
        )
        assert emitted(capfd, AuditEventType.PLUGIN_ERASE_ABANDONED) == []

    async def test_an_erase_is_finished_and_its_names_dropped_together(
        self, session, monkeypatch
    ):
        """Nothing can find the erase finished and still find the names: an
        install checking while the names are being dropped is still refused."""
        from app.services.platform import identity_refs

        user, guild, _install = await _setup(session)
        await plugin_refs.ensure_plugin_ref(
            guild_id=guild.id, public_id=PUBLIC_ID, user_id=user.id
        )
        await plugin_refs.ensure_plugin_guild_ref(
            guild_id=guild.id, public_id=PUBLIC_ID
        )
        _answering(monkeypatch, hooked=[204])
        seen: list[bool] = []
        drop = identity_refs.drop_sector_refs

        async def dropping(*args, **kwargs):
            # Another session asks as an install would, mid-drop.
            seen.append(
                await community_hooks.erase_pending(
                    guild_id=guild.id, public_id=PUBLIC_ID
                )
            )
            return await drop(*args, **kwargs)

        monkeypatch.setattr(identity_refs, "drop_sector_refs", dropping)
        await _deliver(guild.id, hook="erase")
        await _visit(guild.id)

        assert seen == [True]
        assert not await community_hooks.erase_pending(
            guild_id=guild.id, public_id=PUBLIC_ID
        )

    async def test_a_plugin_that_takes_no_erase_hook_is_forgotten_too(
        self, session, monkeypatch
    ):
        user, guild, _install = await _setup(session)
        member = await plugin_refs.ensure_plugin_ref(
            guild_id=guild.id, public_id=PUBLIC_ID, user_id=user.id
        )
        await plugin_refs.ensure_plugin_guild_ref(
            guild_id=guild.id, public_id=PUBLIC_ID
        )
        _answering(monkeypatch, hooked=[404])

        await _deliver(guild.id, hook="erase")
        await _visit(guild.id)
        assert (
            await plugin_refs.resolve_plugin_ref(session, ref=member, guild_id=guild.id)
            is None
        )

    async def test_an_erase_never_answered_drops_the_names_and_says_so(
        self, session, monkeypatch, capfd
    ):
        user, guild, _install = await _setup(session)
        member = await plugin_refs.ensure_plugin_ref(
            guild_id=guild.id, public_id=PUBLIC_ID, user_id=user.id
        )
        await plugin_refs.ensure_plugin_guild_ref(
            guild_id=guild.id, public_id=PUBLIC_ID
        )
        _answering(monkeypatch, hooked=[503])
        monkeypatch.setattr(community_hooks, "MAX_ATTEMPTS", 2)

        await _deliver(guild.id, hook="erase")
        await _visit(guild.id)
        await _come_due(session, guild.id)
        await _visit(guild.id)

        (row,) = await _hooks(session, guild.id)
        assert row.outcome == "gave_up"
        assert (
            await plugin_refs.resolve_plugin_ref(session, ref=member, guild_id=guild.id)
            is None
        )
        assert not await community_hooks.erase_pending(
            guild_id=guild.id, public_id=PUBLIC_ID
        )
        (record,) = emitted(capfd, AuditEventType.PLUGIN_ERASE_ABANDONED)
        assert record["guild_id"] == guild.id

    async def test_an_erase_is_retried_after_the_install_has_gone(
        self, session, monkeypatch
    ):
        _user, guild, install = await _setup(session)
        await plugin_refs.ensure_plugin_guild_ref(
            guild_id=guild.id, public_id=PUBLIC_ID
        )
        install_id = install.id
        await session.delete(install)
        await session.commit()
        plugins = _answering(monkeypatch, hooked=[500, 204])

        await _deliver(guild.id, hook="erase", install_id=install_id)
        await _visit(guild.id)
        await _come_due(session, guild.id)
        await _visit(guild.id)

        assert [claims["plugin_install_id"] for _, _, claims, _ in plugins.calls] == [
            install_id,
            install_id,
        ]
        (row,) = await _hooks(session, guild.id)
        assert row.outcome == "delivered"

    async def test_no_process_hands_out_a_name_once_it_is_erased(self, session):
        """An install's own requests remember names per install, and an erase
        comes only once that install is gone; the system-engine lookups
        remember nothing. So neither hands out a dropped name."""
        user, guild, first = await _setup(session)
        async with cohorts.system_session(guild.id) as routed:
            await set_rls_context(routed, SystemGuild(guild.id))
            await routed.exec(
                text("SELECT set_config('app.token_client_id', :c, true)").bindparams(
                    c=PUBLIC_ID
                )
            )
        before = await plugin_refs.ensure_plugin_ref(
            guild_id=guild.id, public_id=PUBLIC_ID, user_id=user.id
        )
        # This process remembers what the first install was told.
        plugin_refs._install_ref_cache[
            plugin_refs._cache_key(guild.id, first.id, IdentityEntity.user, user.id)
        ] = (before, float("inf"))

        await plugin_refs.drop_plugin_refs(guild_id=guild.id, public_id=PUBLIC_ID)
        after = await plugin_refs.ensure_plugin_ref(
            guild_id=guild.id, public_id=PUBLIC_ID, user_id=user.id
        )
        assert after != before
        # A later install is another key: nothing remembered for it.
        assert (
            plugin_refs._cache_key(guild.id, first.id + 1, IdentityEntity.user, user.id)
            not in plugin_refs._install_ref_cache
        )


async def _deleted(session: AsyncSession, guild_id: int) -> datetime:
    """Delete the community, and answer a moment past its retention window."""
    from app.core.rules import DEFAULT_GUILD_RETENTION_DAYS
    from app.models.platform.guild import Guild

    await set_rls_context(session, Unattributed())
    now = datetime.now(timezone.utc)
    await session.exec(
        update(Guild)
        .where(Guild.id == guild_id)
        .values(status=CommunityStatus.deleted.value, status_changed_at=now)
    )
    await session.commit()
    return now + timedelta(days=DEFAULT_GUILD_RETENTION_DAYS, minutes=1)


async def _purge(session: AsyncSession, when: datetime) -> int:
    from app.services.platform import guild_purge

    session.expunge_all()
    return await guild_purge.purge_due_guilds(session, now=when)


async def _standing(session: AsyncSession, guild_id: int):
    """The community's row, or None once it is purged."""
    from app.models.platform.guild import Guild

    await set_rls_context(session, Unattributed())
    row = (
        await session.exec(
            select(Guild)
            .where(Guild.id == guild_id)
            .execution_options(populate_existing=True)
        )
    ).first()
    await session.commit()
    return row


async def _queue_revoke(guild_id: int, install_id: int) -> None:
    from app.core.encryption import SALT_PLUGIN_CONFIG, encrypt_field

    async with cohorts.system_session(guild_id) as routed:
        await set_rls_context(routed, SystemGuild(guild_id))
        await community_hooks.queue_community_hooks(
            routed,
            guild_id=guild_id,
            public_id=PUBLIC_ID,
            hooks=("revoke",),
            install_id=install_id,
            body={
                "connection": "github",
                "sealed_tokens": {
                    "access_token": encrypt_field("gho_kept", SALT_PLUGIN_CONFIG)
                },
            },
        )
        await routed.commit()


class TestPurging:
    async def test_a_queued_revoke_goes_before_the_erase_and_the_row_after_both(
        self, session, monkeypatch
    ):
        """A purge queues its erase behind what is waiting and keeps the
        community until it is answered; the sweep, which still visits a
        deleted community, sends them in order."""
        _user, guild, install = await _setup(session)
        guild_id = guild.id
        await plugin_refs.ensure_plugin_guild_ref(
            guild_id=guild_id, public_id=PUBLIC_ID
        )
        await _queue_revoke(guild_id, install.id)
        plugins = _answering(monkeypatch, hooked=[204])
        when = await _deleted(session, guild_id)

        assert await _purge(session, when) == 0
        standing = await _standing(session, guild_id)
        assert standing is not None and standing.purge_started_at is not None
        assert [row.hook for row in await _hooks(session, guild_id)] == [
            "revoke",
            "erase",
        ]
        assert plugins.calls == []

        await sweep_timers.process_due_timers(outward=True)
        assert plugins.paths() == ["/v1/hooks/revoke", "/v1/hooks/erase"]
        assert plugins.calls[0][3]["access_token"] == "gho_kept"
        assert await _standing(session, guild_id) is not None

        assert await _purge(session, when) == 1
        assert await _standing(session, guild_id) is None

    async def test_a_plugin_that_is_down_keeps_the_community_until_it_is_given_up_on(
        self, session, monkeypatch, capfd
    ):
        user, guild, _install = await _setup(session)
        guild_id = guild.id
        member = await plugin_refs.ensure_plugin_ref(
            guild_id=guild_id, public_id=PUBLIC_ID, user_id=user.id
        )
        await plugin_refs.ensure_plugin_guild_ref(
            guild_id=guild_id, public_id=PUBLIC_ID
        )
        _answering(monkeypatch, hooked=[503])
        monkeypatch.setattr(community_hooks, "MAX_ATTEMPTS", 2)
        when = await _deleted(session, guild_id)

        assert await _purge(session, when) == 0
        await _visit(guild_id)
        assert await _purge(session, when) == 0
        assert await _standing(session, guild_id) is not None
        assert await plugin_refs.resolve_plugin_ref(
            session, ref=member, guild_id=guild_id
        )

        await _come_due(session, guild_id)
        await _visit(guild_id)
        (erase,) = await _hooks(session, guild_id)
        assert erase.outcome == "gave_up"
        assert (
            await plugin_refs.resolve_plugin_ref(session, ref=member, guild_id=guild_id)
            is None
        )
        (record,) = emitted(capfd, AuditEventType.PLUGIN_ERASE_ABANDONED)
        assert record["guild_id"] == guild_id

        assert await _purge(session, when) == 1
        assert await _standing(session, guild_id) is None

    async def test_an_answered_purge_erase_lets_the_purge_finish(
        self, session, monkeypatch
    ):
        # Billing learns of the purge from the change log (community.purged),
        # not from the erase: the erase only has to be answered.
        _user, guild, _install = await _setup(session)
        guild_id = guild.id
        await plugin_refs.ensure_plugin_guild_ref(
            guild_id=guild_id, public_id=PUBLIC_ID
        )
        _answering(monkeypatch, hooked=[204])
        when = await _deleted(session, guild_id)

        assert await _purge(session, when) == 0
        await _visit(guild_id)

        assert await _purge(session, when) == 1

    async def test_a_community_being_purged_names_nobody_new_and_stays_gone(
        self, session, client, acting_user, monkeypatch
    ):
        """Once its plug-ins are asked to erase it, nothing mints a name there,
        nothing reaches the plug-in at once, and it cannot be restored."""
        from app.core.messages import GuildMessages

        operator = await acting_user("owner")
        user, guild, install = await _setup(session)
        guild_id = guild.id
        await plugin_refs.ensure_plugin_guild_ref(
            guild_id=guild_id, public_id=PUBLIC_ID
        )
        newcomer = await create_user(session)
        plugins = _answering(monkeypatch, hooked=[503])
        when = await _deleted(session, guild_id)
        assert await _purge(session, when) == 0

        with pytest.raises(plugin_refs.PluginNameRefused):
            await plugin_refs.ensure_plugin_ref(
                guild_id=guild_id, public_id=PUBLIC_ID, user_id=newcomer.id
            )
        with pytest.raises(plugin_connection_flows.HookNameRefused):
            await community_hooks.call_now(
                "webhook",
                public_id=PUBLIC_ID,
                base_url="https://hooked.example.test",
                guild_id=guild_id,
                install_id=install.id,
                body={},
            )
        assert plugins.calls == []

        response = await client.post(
            f"/api/v1/settings/communities/{guild_id}/restore",
            headers=operator.headers,
            json={"status": "active"},
        )
        assert response.status_code == 409, response.text
        assert response.json()["detail"] == GuildMessages.COMMUNITY_PURGE_STARTED
        from app.services.platform import guilds as guilds_service

        await set_rls_context(session, Unattributed())
        with pytest.raises(ValueError, match=GuildMessages.COMMUNITY_PURGE_STARTED):
            await guilds_service.set_guild_status(
                session, guild_id=guild_id, status=CommunityStatus.suspended
            )
        await session.rollback()

    async def test_a_community_destroyed_at_once_is_closed_while_it_waits(
        self, session, monkeypatch
    ):
        """A demo's pitch goes straight from live to destroyed: while its
        plug-ins are asked to erase it, it is deleted, so nobody reads or
        writes what the purge is about to remove."""
        from app.services.platform import guild_purge

        _user, guild, _install = await _setup(session)
        guild_id = guild.id
        await plugin_refs.ensure_plugin_guild_ref(
            guild_id=guild_id, public_id=PUBLIC_ID
        )
        _answering(monkeypatch, hooked=[204])

        await set_rls_context(session, Unattributed())
        live = await _standing(session, guild_id)
        assert live is not None and live.status == CommunityStatus.active.value
        await set_rls_context(session, Unattributed())
        assert not await guild_purge.destroy_now(session, live)

        waiting = await _standing(session, guild_id)
        assert waiting is not None
        assert waiting.status == CommunityStatus.deleted.value
        assert waiting.purge_started_at is not None

        await _visit(guild_id)
        session.expunge_all()
        assert await guild_purge.finish_started_purges(session) == 1
        assert await _standing(session, guild_id) is None


class TestSendingAtOnce:
    async def test_a_hook_sent_at_once_goes_and_answers(self, session, monkeypatch):
        _user, guild, install = await _setup(session)
        plugins = _answering(monkeypatch, hooked=[204])

        await community_hooks.call_now(
            "schedule",
            public_id=PUBLIC_ID,
            base_url="https://hooked.example.test",
            guild_id=guild.id,
            install_id=install.id,
            body={"schedule": "nightly"},
        )

        ((_, path, claims, body),) = plugins.calls
        assert (path, claims["hook"], body) == (
            "/v1/hooks/schedule",
            "schedule",
            {"schedule": "nightly"},
        )

    async def test_nothing_goes_at_once_while_an_erase_waits(
        self, session, monkeypatch
    ):
        _user, guild, install = await _setup(session)
        await plugin_refs.ensure_plugin_guild_ref(
            guild_id=guild.id, public_id=PUBLIC_ID
        )
        plugins = _answering(monkeypatch, hooked=[204])
        await _deliver(guild.id, hook="erase")

        with pytest.raises(plugin_connection_flows.HookNameRefused):
            await community_hooks.call_now(
                "webhook",
                public_id=PUBLIC_ID,
                base_url="https://hooked.example.test",
                guild_id=guild.id,
                install_id=install.id,
                body={},
            )
        assert plugins.calls == []

    async def test_only_an_answered_hook_is_sent_at_once(self, session):
        _user, guild, install = await _setup(session)

        with pytest.raises(community_hooks.UnknownCommunityHookError):
            await community_hooks.call_now(
                "erase",
                public_id=PUBLIC_ID,
                base_url="https://hooked.example.test",
                guild_id=guild.id,
                install_id=install.id,
                body={},
            )

    async def test_it_waits_for_a_send_in_flight_and_takes_a_lapsed_claim(
        self, session, monkeypatch
    ):
        """One sender per plug-in comes from a lease on the rows: a hook sent
        at once waits while another send holds the plug-in, gives up past its
        wait, and takes the plug-in once that claim has lapsed."""
        _user, guild, install = await _setup(session)
        guild_id = guild.id
        plugins = _answering(monkeypatch, hooked=[204])
        await _deliver(guild_id, hook="installed")
        await set_rls_context(session, Unattributed())
        await session.exec(
            update(PluginCommunityHook)
            .where(PluginCommunityHook.guild_id == guild_id)
            .values(claimed_until=datetime.now(timezone.utc) + timedelta(minutes=1))
        )
        await session.commit()
        monkeypatch.setattr(community_hooks, "CALL_WAIT_SECONDS", 0.3)

        async def schedule():
            return await community_hooks.call_now(
                "schedule",
                public_id=PUBLIC_ID,
                base_url="https://hooked.example.test",
                guild_id=guild_id,
                install_id=install.id,
                body={},
            )

        with pytest.raises(plugin_connection_flows.HookError, match="did not finish"):
            await schedule()
        # Nor does a visit send what another sender holds.
        await _visit(guild_id)
        assert plugins.calls == []

        await set_rls_context(session, Unattributed())
        await session.exec(
            update(PluginCommunityHook)
            .where(PluginCommunityHook.guild_id == guild_id)
            .values(claimed_until=datetime.now(timezone.utc) - timedelta(seconds=1))
        )
        await session.commit()
        await schedule()
        await _visit(guild_id)
        assert plugins.paths() == ["/v1/hooks/schedule", "/v1/hooks/installed"]
        rows = await _hooks(session, guild_id)
        assert [(row.hook, row.outcome, row.claimed_until) for row in rows] == [
            ("installed", "delivered", None),
            ("schedule", "answered", None),
        ]

    async def test_a_send_holds_no_database_connection(self, session, monkeypatch):
        """While a hook is in flight the plug-in's answer waits on nothing
        here: the visit's own claims and settles are short transactions."""
        from app.db import session as db_session

        _user, guild, _install = await _setup(session)
        open_during_send: list[int] = []
        plugins = Plugins()

        def handle(request: httpx.Request) -> httpx.Response:
            engine = db_session.SystemSessionLocal.kw["bind"]
            open_during_send.append(engine.sync_engine.pool.checkedout())
            return plugins.handle(request)

        monkeypatch.setattr(
            plugin_connection_flows, "http_transport", httpx.MockTransport(handle)
        )
        await _deliver(guild.id, hook="installed")
        await _visit(guild.id)

        assert plugins.paths() == ["/v1/hooks/installed"]
        assert open_during_send == [0]
