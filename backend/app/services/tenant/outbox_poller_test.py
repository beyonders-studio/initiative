"""The properties the poller has to actually hold.

Each of these covers a way the first cut of this code was wrong: backoff that
unrelated traffic could clear, transactions split across envelopes, two replicas
delivering the same batch under different ids, and a cursor that could run past
an in-flight transaction.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import select, update

from app.db.request_context import SystemGuild
from app.db.session import set_rls_context
from app.models.tenant.event_outbox import EventOutbox
from app.models.tenant.plugin_event_outbox import PluginEventOutbox
from app.models.tenant.webhook_delivery import WebhookDelivery
from app.models.tenant.webhook_subscription import WebhookSubscription
from app.services import outbox_ledger, sweep_timers
from app.services.guild_sweeps import Scope, each_guild
from app.services.tenant import change_log, expiry, outbox_poller

#: Stand-ins for what this subscriber calls the guild and the person who wrote.
#: Minted by the poller before it builds an envelope — these tests are about
#: what the envelope is made of, not where the names come from.
_GUILD_REF = "gweb_lPqTf3Vd8KmY2nRb6ZsXeA1cJhW4tGuN"
_ACTOR_REF = "uweb_9dYkR2pLmX7vQzB4nT6sHfA3eJwC8gUx"


def _subscription(**overrides) -> WebhookSubscription:
    defaults = {
        "id": 7,
        "guild_id": 1,
        "initiative_id": None,
        "created_by": 3,
        "target_url": "https://example.test/hook",
        "hmac_secret": "s3cret",
        "event_types": ["tasks.created", "tasks.updated"],
        "active": True,
    }
    defaults.update(overrides)
    return WebhookSubscription(**defaults)


def _row(row_id: int, txn_id: int, **overrides) -> EventOutbox:
    defaults = {
        "id": row_id,
        "txn_id": txn_id,
        "occurred_at": datetime(2026, 8, 15, tzinfo=UTC),
        "actor_user_id": 3,
        "initiative_id": 11,
        "resource_type": "tasks",
        "resource_id": 100 + row_id,
        "action": "created",
        "changed": [],
    }
    defaults.update(overrides)
    return EventOutbox(**defaults)


def test_event_id_is_the_same_for_the_same_batch():
    """Two replicas delivering one batch must produce one id, or a receiver
    deduping on it sees the duplicate as new work."""
    first = outbox_poller._event_id(7, 4242)
    second = outbox_poller._event_id(7, 4242)
    assert first == second
    assert first != outbox_poller._event_id(7, 4243)
    assert first != outbox_poller._event_id(8, 4242)


def test_grouping_is_by_transaction_not_adjacency():
    """Concurrent commits interleave ids, so one transaction's rows are not
    necessarily contiguous in the log."""
    subscription = _subscription()
    rows = [_row(1, 500), _row(2, 501), _row(3, 500), _row(4, 501)]

    grouped: dict[int, list[EventOutbox]] = {}
    for row in rows:
        if outbox_poller._matches(row, subscription):
            grouped.setdefault(row.txn_id, []).append(row)

    assert sorted(grouped) == [500, 501]
    assert [r.id for r in grouped[500]] == [1, 3]
    assert [r.id for r in grouped[501]] == [2, 4]


def test_one_transaction_is_one_envelope():
    subscription = _subscription()
    rows = [_row(1, 500), _row(3, 500)]
    envelope = outbox_poller._envelope(
        subscription, 500, rows, guild_ref=_GUILD_REF, actor_ref=_ACTOR_REF
    )

    assert len(envelope["changes"]) == 2
    assert envelope["event_id"] == outbox_poller._event_id(subscription.id, 500)
    # Names and ids only — no value from any changed column rides along.
    for change in envelope["changes"]:
        assert set(change) == {
            "event_type",
            "initiative_id",
            "resource",
            "parents",
            "action",
            "changed",
        }


def test_the_envelope_carries_the_parent_chain():
    """A subscriber hears which surfaces a change touches, as identifiers.

    Each parent is addressed exactly like the resource itself, so acting on
    one is the same read through the same gates.
    """
    subscription = _subscription()
    chain = [{"type": "projects", "id": 7}]
    envelope = outbox_poller._envelope(
        subscription,
        500,
        [_row(1, 500, parents=chain)],
        guild_ref=_GUILD_REF,
        actor_ref=_ACTOR_REF,
    )

    (change,) = envelope["changes"]
    assert change["parents"] == chain
    assert all(set(parent) == {"type", "id"} for parent in change["parents"])


async def test_every_subscription_in_a_guild_is_drained(
    session, acting_user, monkeypatch
):
    """Each pass expunges the identity map, so the roster is held as ids and
    each subscription is re-loaded. Held as instances, the second and later ones
    are detached and every one after the first fails."""
    from app.models.platform.guild import CommunityRole
    from app.services.tenant import outbox_poller as poller

    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    guild_id, user_id = a.guild.id, a.user.id

    for index in range(3):
        session.add(
            WebhookSubscription(
                initiative_id=None,
                created_by=user_id,
                target_url=f"https://example.test/hook-{index}",
                hmac_secret=f"secret-{index}",
                event_types=["tasks.created"],
                active=True,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
    await session.commit()

    drained: list[int] = []

    async def _record(session_, subscription, *, guild_id, now, **_reach):
        drained.append(subscription.id)

    monkeypatch.setattr(poller, "_drain_subscription", _record)
    monkeypatch.setattr(poller, "_subscribed", set())

    now = datetime.now(UTC)
    await poller.drain_guild(session, guild_id, now=now)

    assert len(drained) == 3, (
        f"only {len(drained)} of 3 subscriptions drained — the rest were "
        "detached by the per-pass expunge and never delivered to"
    )
    assert poller._subscribed == {guild_id}


def test_a_batch_is_one_transaction_whole():
    """Rows are selected by txn_id, so a batch is every row that transaction
    wrote. A partial batch is not a state this design can reach."""
    subscription = _subscription()
    rows = [_row(1, 500), _row(3, 500), _row(9, 500)]

    envelope = outbox_poller._envelope(
        subscription, 500, rows, guild_ref=_GUILD_REF, actor_ref=_ACTOR_REF
    )

    assert [c["resource"]["id"] for c in envelope["changes"]] == [101, 103, 109]
    assert envelope["event_id"] == outbox_poller._event_id(subscription.id, 500)


async def test_ledger_delivers_each_transaction_once(
    session, role_session, acting_user, monkeypatch
):
    """A drain marks each pending transaction delivered, and a second pass over
    the same log sends nothing further. Past the change log's retention, the
    changes and their ledger rows go together."""
    from app.models.platform.guild import CommunityRole
    from app.services.tenant import outbox_poller as poller
    from app.testing import create_task

    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    guild_id, user_id = a.guild.id, a.user.id
    await create_task(session, a.project)
    await create_task(session, a.project)

    session.add(
        WebhookSubscription(
            initiative_id=None,
            created_by=user_id,
            target_url="https://example.test/hook",
            hmac_secret="secret",
            event_types=["tasks.created"],
            active=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    )
    await session.commit()

    sent: list[dict] = []

    async def _accept(*, target_url, secret, envelope):
        sent.append(envelope)
        return True

    monkeypatch.setattr(poller, "deliver", _accept)

    system = await role_session("app_admin")

    await poller.drain_guild(system, guild_id, now=datetime.now(UTC))
    first_pass = len(sent)
    assert first_pass > 0, "no transaction was delivered"

    await poller.drain_guild(system, guild_id, now=datetime.now(UTC))
    assert len(sent) == first_pass, (
        "a settled transaction was delivered twice — the ledger row should make "
        "it ineligible on every later pass"
    )

    assert (await session.exec(select(WebhookDelivery))).all()
    aged = datetime.now(UTC) - change_log.RETENTION - timedelta(hours=1)
    await session.exec(update(EventOutbox).values(occurred_at=aged))
    await session.commit()
    await each_guild(
        [(Scope.PROVISIONED, await expiry.prepare())], name="test", only=[guild_id]
    )
    assert (await session.exec(select(EventOutbox))).all() == []
    assert (await session.exec(select(WebhookDelivery))).all() == []


async def test_a_refused_batch_is_retried_not_lost_or_overtaken(
    session, role_session, acting_user, monkeypatch
):
    """A refusal leaves the transaction pending, so it comes back once its
    backoff expires rather than being skipped, and the transaction after it
    waits for it on every pass, not only the one that was refused."""
    from app.models.platform.guild import CommunityRole
    from app.services.tenant import outbox_poller as poller
    from app.testing import create_task

    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    guild_id, user_id = a.guild.id, a.user.id
    await create_task(session, a.project)
    await create_task(session, a.project)

    session.add(
        WebhookSubscription(
            initiative_id=None,
            created_by=user_id,
            target_url="https://example.test/hook",
            hmac_secret="secret",
            event_types=["tasks.created"],
            active=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    )
    await session.commit()

    attempts: list[str] = []

    async def _refuse_the_first(*, target_url, secret, envelope):
        attempts.append(envelope["event_id"])
        return len(attempts) > 1

    monkeypatch.setattr(poller, "deliver", _refuse_the_first)

    system = await role_session("app_admin")

    now = datetime.now(UTC)
    await poller.drain_guild(system, guild_id, now=now)
    assert len(attempts) == 1

    # Inside the backoff, the second transaction waits behind the first.
    await poller.drain_guild(system, guild_id, now=now + timedelta(seconds=1))
    assert len(attempts) == 1, "a later transaction overtook a refused one"

    # Past the backoff, the same batch is offered again under the same id,
    # and the second follows it.
    await poller.drain_guild(system, guild_id, now=now + timedelta(hours=2))
    assert len(attempts) == 3, "a refused batch was dropped instead of retried"
    assert attempts[0] == attempts[1], (
        "the retry carried a different event_id, so a receiver deduping on it "
        "would treat the redelivery as new work"
    )
    assert attempts[2] != attempts[0]


async def test_repeated_refusals_escalate_the_backoff(
    session, role_session, acting_user, monkeypatch
):
    """The schedule has to be applied, not merely defined.

    _settle previously incremented attempts but always scheduled the first step,
    so an unreachable target was retried every five seconds forever. This drives
    real refusals and reads the interval Postgres actually stored.
    """
    from sqlalchemy import text as sa_text

    from app.models.platform.guild import CommunityRole
    from app.services.tenant import outbox_poller as poller
    from app.testing import create_task

    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    guild_id, user_id = a.guild.id, a.user.id
    await create_task(session, a.project)

    session.add(
        WebhookSubscription(
            initiative_id=None,
            created_by=user_id,
            target_url="https://example.test/hook",
            hmac_secret="secret",
            event_types=["tasks.created"],
            active=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    )
    await session.commit()

    async def _refuse(*, target_url, secret, envelope):
        return False

    monkeypatch.setattr(poller, "deliver", _refuse)

    system = await role_session("app_admin")

    intervals: list[float] = []
    moment = datetime.now(UTC)
    for _ in range(3):
        await poller.drain_guild(system, guild_id, now=moment)
        await set_rls_context(session, SystemGuild(guild_id))
        row = (
            await session.exec(
                sa_text(
                    "SELECT attempts, next_attempt_at FROM webhook_deliveries "
                    "WHERE delivered_at IS NULL ORDER BY txn_id LIMIT 1"
                )
            )
        ).first()
        intervals.append((row[1] - moment).total_seconds())
        # Jump past the backoff so the next pass re-claims the same batch.
        moment = row[1] + timedelta(seconds=1)

    assert intervals == sorted(intervals) and intervals[0] < intervals[-1], (
        f"backoff did not escalate across repeated refusals: {intervals} — an "
        "unreachable target would be retried at the first interval forever"
    )
    assert intervals[:3] == [float(s) for s in outbox_ledger.BACKOFF_SECONDS[:3]]


async def test_an_exhausted_batch_is_dead_lettered_and_unblocks_the_backlog(
    session, role_session, acting_user, monkeypatch
):
    """A target that never comes back used to be retried at the final backoff
    step forever, holding every later transaction hostage behind it — there
    was no way for a permanently broken batch to stop blocking the queue.

    Once the ledger's backoff schedule is exhausted, the batch gives up
    (recorded via ``dead_lettered_at``, never retried again) instead of
    reusing the last interval indefinitely, and a newer transaction for the
    same subscription is no longer stuck behind it.
    """
    from sqlalchemy import text as sa_text

    from app.models.platform.guild import CommunityRole
    from app.services.tenant import outbox_poller as poller
    from app.testing import create_task

    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    guild_id, user_id = a.guild.id, a.user.id

    # The batch that will be refused until it gives up.
    await create_task(session, a.project)
    subscription = WebhookSubscription(
        initiative_id=None,
        created_by=user_id,
        target_url="https://example.test/hook",
        hmac_secret="secret",
        event_types=["tasks.created"],
        active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session.add(subscription)
    await session.commit()
    await session.refresh(subscription)
    subscription_id = subscription.id

    attempted: list[str] = []

    async def _refuse(*, target_url, secret, envelope):
        attempted.append(envelope["event_id"])
        return False

    monkeypatch.setattr(poller, "deliver", _refuse)

    system = await role_session("app_admin")

    txn_a: int | None = None
    moment = datetime.now(UTC)
    for _ in range(len(outbox_ledger.BACKOFF_SECONDS)):
        await poller.drain_guild(system, guild_id, now=moment)
        await set_rls_context(session, SystemGuild(guild_id))
        row = (
            await session.exec(
                sa_text(
                    "SELECT txn_id, next_attempt_at, dead_lettered_at "
                    "FROM webhook_deliveries "
                    "WHERE delivered_at IS NULL ORDER BY txn_id LIMIT 1"
                )
            )
        ).first()
        txn_a = row[0]
        assert row[2] is None, (
            "the batch was dead-lettered before its backoff schedule was "
            "actually exhausted"
        )
        # Jump past the backoff so the next pass re-claims the same batch.
        moment = row[1] + timedelta(seconds=1)

    event_id_a = poller._event_id(subscription_id, txn_a)
    attempts_on_a_so_far = attempted.count(event_id_a)
    assert attempts_on_a_so_far == len(outbox_ledger.BACKOFF_SECONDS), (
        "the failing batch should have been attempted once per backoff step "
        "before its schedule is exhausted"
    )

    # A second, independent transaction lands while the first is still
    # failing. It must stay queued behind the first — not delivered early —
    # until the first is resolved one way or the other.
    await create_task(session, a.project)
    await session.commit()

    # This pass is what exhausts the first batch's schedule.
    await poller.drain_guild(system, guild_id, now=moment)
    await set_rls_context(session, SystemGuild(guild_id))

    dead_row = (
        await session.exec(
            sa_text(
                "SELECT txn_id FROM webhook_deliveries "
                "WHERE dead_lettered_at IS NOT NULL"
            )
        )
    ).first()
    assert dead_row is not None, (
        "the exhausted batch was retried again instead of being dead-lettered"
    )
    assert dead_row[0] == txn_a

    assert attempted.count(event_id_a) == attempts_on_a_so_far + 1, (
        "the batch's last-ever attempt is the one that dead-letters it"
    )
    second_txn_attempts = len(attempted) - attempts_on_a_so_far - 1
    assert second_txn_attempts == 1, (
        "dead-lettering the exhausted batch should let the newer transaction "
        "through in the same pass — instead it stayed queued behind a batch "
        "that will never be retried again"
    )

    # And it stays given up: whatever else happens on later passes — including
    # the second transaction continuing to retry on its own schedule — the
    # dead-lettered batch is never attempted again, however far forward the
    # next pass looks.
    await poller.drain_guild(system, guild_id, now=moment + timedelta(days=365))
    assert attempted.count(event_id_a) == attempts_on_a_so_far + 1, (
        "a dead-lettered batch was retried — it should never be attempted again"
    )


def test_the_envelope_names_the_guild_and_the_actor_by_reference():
    """Both used to be row ids. A receiver holding subscriptions in several
    guilds was handed one number per person that meant the same person in all
    of them; these are its own (``webhook_refs``).

    The rest stay ids on purpose: they are per-guild-schema sequences, and
    ``subscription_id`` is what a receiver matches a delivery against.
    """
    subscription = _subscription()
    envelope = outbox_poller._envelope(
        subscription, 500, [_row(1, 500)], guild_ref=_GUILD_REF, actor_ref=_ACTOR_REF
    )

    assert envelope["community_ref"] == _GUILD_REF
    assert envelope["actor_ref"] == _ACTOR_REF
    assert "guild_id" not in envelope
    assert "actor_user_id" not in envelope
    assert envelope["subscription_id"] == subscription.id


def test_a_system_write_names_no_actor():
    """A background job is attributed to nobody, so there is nobody to name."""
    subscription = _subscription()
    envelope = outbox_poller._envelope(
        subscription, 500, [_row(1, 500)], guild_ref=_GUILD_REF, actor_ref=None
    )

    assert envelope["actor_ref"] is None


def test_the_envelope_names_the_plugin_that_wrote():
    """A plug-in recognises its own writes by ``actor_plugin``, its registration's
    ``public_id``. Set on its own, beside or without a person."""
    subscription = _subscription()
    by_plugin = outbox_poller._envelope(
        subscription,
        500,
        [_row(1, 500, actor_user_id=None, actor_install_id=4)],
        guild_ref=_GUILD_REF,
        actor_ref=None,
        actor_plugin="tests.plugin",
    )
    assert by_plugin["actor_plugin"] == "tests.plugin"
    assert by_plugin["actor_ref"] is None
    assert "actor_install_id" not in by_plugin

    by_person = outbox_poller._envelope(
        subscription, 500, [_row(1, 500)], guild_ref=_GUILD_REF, actor_ref=_ACTOR_REF
    )
    assert by_person["actor_plugin"] is None
    assert by_person["actor_ref"] == _ACTOR_REF


def _reach(**overrides) -> outbox_poller.InstallReach:
    defaults = {
        "live": True,
        "placed": frozenset({11}),
        "readable": frozenset({"projects"}),
    }
    defaults.update(overrides)
    return outbox_poller.InstallReach(**defaults)


def test_a_plugins_subscription_hears_what_its_reach_covers():
    subscription = _subscription(plugin_install_id=4)
    assert outbox_poller._matches(_row(1, 500), subscription, _reach())


@pytest.mark.parametrize(
    "reach",
    [
        pytest.param(_reach(placed=frozenset()), id="placement-removed"),
        pytest.param(_reach(placed=frozenset({12})), id="placed-elsewhere"),
        pytest.param(_reach(readable=frozenset({"files"})), id="scope-withdrawn"),
        pytest.param(_reach(live=False), id="install-not-live"),
        pytest.param(None, id="no-reach-read"),
    ],
)
def test_a_plugins_subscription_hears_nothing_outside_its_reach(reach):
    subscription = _subscription(plugin_install_id=4)
    assert not outbox_poller._matches(_row(1, 500), subscription, reach)


def test_a_subscription_no_plugin_registered_is_not_asked_for_a_reach():
    assert outbox_poller._matches(_row(1, 500), _subscription(), None)


def test_a_community_event_needs_its_scope_and_no_placement():
    subscription = _subscription(plugin_install_id=4, event_types=["tags.created"])
    tag = _row(1, 500, resource_type="tags", initiative_id=None)
    assert outbox_poller._matches(
        tag, subscription, _reach(placed=frozenset(), readable=frozenset({"tags"}))
    )
    assert not outbox_poller._matches(tag, subscription, _reach())


def test_an_event_no_scope_reaches_is_never_a_plugins():
    subscription = _subscription(plugin_install_id=4, event_types=["plugins.created"])
    install = _row(1, 500, resource_type="plugins", initiative_id=None)
    everything = frozenset(
        r.value for r in outbox_poller.webhook_events._read_scopes().values() if r
    )
    assert not outbox_poller._matches(
        install, subscription, _reach(readable=everything)
    )


def test_the_reach_reads_what_the_grant_lets_it_read():
    reach = outbox_poller.InstallReach.from_row(
        live=True,
        placed=None,
        granted_scopes=[
            "projects:write",
            "tags:read",
            "no-longer:a-scope",
            "plugins:tests.gh",
        ],
    )
    assert reach.readable == frozenset({"projects", "tags"})
    assert reach.plugins == frozenset({"tests.gh"})
    assert reach.placed == frozenset()
    assert outbox_poller.InstallReach.from_row(
        live=None, placed=[1], granted_scopes=None
    ) == outbox_poller.InstallReach(
        live=False, placed=frozenset({1}), readable=frozenset()
    )


async def test_a_hint_wakes_the_drain_only_where_something_subscribes(monkeypatch):
    """A change in a community with no active subscription is dropped before
    the drain, which never visits it."""
    monkeypatch.setattr(outbox_poller, "_subscribed", {7})
    monkeypatch.setattr(sweep_timers, "_woken", {})

    await outbox_poller.hint("guild_8:100")
    await outbox_poller.hint("guild_7:101")

    assert sweep_timers._woken == {"webhooks": {7}}


_GH_EVENT = "plugin.tests.gh.issue_opened"


def _plugin_event(**overrides) -> PluginEventOutbox:
    defaults = {
        "id": 1,
        "txn_id": 500,
        "occurred_at": datetime(2026, 9, 25, tzinfo=UTC),
        "install_id": 9,
        "event_type": _GH_EVENT,
        "initiative_id": None,
        "payload": {"number": 12},
    }
    defaults.update(overrides)
    return PluginEventOutbox(**defaults)


@pytest.mark.parametrize(
    ("subscribed_in", "about", "carried"),
    [(None, None, None), (11, None, 11), (None, 12, 12), (12, 12, 12)],
    ids=["community", "narrowed", "its-own-community", "its-own-narrowed"],
)
def test_a_plugin_event_is_one_change_carrying_its_payload(
    subscribed_in, about, carried
):
    """It carries the initiative it landed in: its own, or the one the
    subscription is narrowed to."""
    envelope = outbox_poller._envelope(
        _subscription(initiative_id=subscribed_in, event_types=[_GH_EVENT]),
        500,
        [],
        guild_ref=_GUILD_REF,
        actor_ref=None,
        actor_plugin="tests.gh",
        plugin_events=[(_plugin_event(initiative_id=about), "tests.gh")],
    )
    assert envelope["actor_plugin"] == "tests.gh"
    assert envelope["changes"] == [
        {
            "event_type": _GH_EVENT,
            "initiative_id": carried,
            "plugin": "tests.gh",
            "payload": {"number": 12},
        }
    ]


def test_a_plugin_event_about_no_initiative_reaches_where_both_plugins_are_placed():
    """A vendor organization is not an initiative, so its events reach an
    initiative's subscription where the emitting plug-in is placed too."""
    narrowed = _subscription(
        plugin_install_id=4, initiative_id=11, event_types=[_GH_EVENT]
    )
    reach = _reach(plugins=frozenset({"tests.gh"}))
    event = _plugin_event()
    matches = outbox_poller._matches_plugin_event

    assert matches(event, "tests.gh", [11], narrowed, reach)
    assert not matches(event, "tests.gh", [12], narrowed, reach)
    assert not matches(event, "tests.gh", [11], narrowed, _reach())
    assert not matches(event, "tests.gh", [11], narrowed, _reach(placed=frozenset()))
    community = _subscription(plugin_install_id=4, event_types=[_GH_EVENT])
    assert matches(event, "tests.gh", [], community, reach)


def test_a_plugin_event_about_an_initiative_reaches_only_that_initiative():
    event = _plugin_event(initiative_id=11)
    reach = _reach(plugins=frozenset({"tests.gh"}), placed=frozenset({11, 12}))
    matches = outbox_poller._matches_plugin_event

    for initiative_id, heard in ((11, True), (12, False), (None, True)):
        subscription = _subscription(
            plugin_install_id=4, initiative_id=initiative_id, event_types=[_GH_EVENT]
        )
        assert matches(event, "tests.gh", [11, 12], subscription, reach) is heard
