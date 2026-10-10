"""A subscription's reach is the scope it names.

Delivery used to read the change log as the account that registered the
subscription, which made ``created_by`` an authorization principal and made a
subscription stop working when that person's standing changed — silently, since
the poller stood down before attempting a delivery and so never counted a
failure. That principal decided nothing the declared scope had not already
decided.

What the tests below hold is the replacement: the scope decides, the scope is
all that decides, and an account going away does not end a community's
integration. What a plug-in may *do* with a delivery is a separate gate in a
separate place — its own token's standing, read on every call — and is not
exercised here.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import CommunityRole
from app.models.tenant.webhook_subscription import WebhookSubscription
from app.testing.schema_harness import route_session_to_guild


async def _subscribe(
    session: AsyncSession, *, guild_id: int, user_id: int, initiative_id: int | None
) -> None:
    await route_session_to_guild(session, guild_id)
    now = datetime.now(timezone.utc)
    session.add(
        WebhookSubscription(
            initiative_id=initiative_id,
            created_by=user_id,
            target_url="https://example.test/hook",
            hmac_secret="secret",
            event_types=["tasks.created"],
            active=True,
            created_at=now,
            updated_at=now,
        )
    )
    await session.commit()


def _collector(monkeypatch, poller) -> list[dict]:
    sent: list[dict] = []

    async def _accept(*, target_url, secret, envelope):
        sent.append(envelope)
        return True

    monkeypatch.setattr(poller, "deliver", _accept)
    return sent


async def test_delivery_outlives_the_account_that_registered_it(
    session: AsyncSession, role_session, acting_user, monkeypatch
):
    """The change this is all for: erasing the registrant is not a decision
    about the community's integration, so it does not end one."""
    from app.services.platform import users as user_service
    from app.services.tenant import outbox_poller as poller
    from app.testing import create_task

    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    guild_id, user_id, project = a.guild.id, a.user.id, a.project
    await _subscribe(session, guild_id=guild_id, user_id=user_id, initiative_id=None)

    sent = _collector(monkeypatch, poller)
    system = await role_session("app_admin")

    session.expunge_all()
    await user_service.hard_delete_user(system, user_id)
    session.expunge_all()
    await create_task(session, project)
    session.expunge_all()

    await poller.drain_guild(system, guild_id, now=datetime.now(timezone.utc))
    assert sent, "an erased registrant ended a subscription that should outlive them"


async def test_erasure_leaves_the_subscription_alone(
    session: AsyncSession, role_session, acting_user
):
    """And the row is untouched — no account's lifecycle reaches it."""
    from app.services.platform import users as user_service

    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    guild_id, user_id = a.guild.id, a.user.id
    await _subscribe(session, guild_id=guild_id, user_id=user_id, initiative_id=None)

    await user_service.hard_delete_user(await role_session("app_admin"), user_id)

    session.expunge_all()
    await route_session_to_guild(session, guild_id)
    rows = list(await session.exec(select(WebhookSubscription)))
    assert len(rows) == 1
    assert rows[0].active is True
    assert rows[0].created_by == user_id


async def test_an_initiative_subscription_hears_only_that_initiative(
    session: AsyncSession, role_session, acting_user, monkeypatch
):
    """The scope is the decision, so a second initiative's changes are not in
    the batch — with nobody's membership consulted to work that out."""
    from app.services.tenant import outbox_poller as poller
    from app.testing import create_task
    from app.testing.factories import create_initiative, create_project

    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    guild_id = a.guild.id
    other = await create_initiative(session, a.guild, a.user)
    other_project = await create_project(session, other, a.user)

    await _subscribe(
        session, guild_id=guild_id, user_id=a.user.id, initiative_id=a.initiative.id
    )
    sent = _collector(monkeypatch, poller)
    system = await role_session("app_admin")

    session.expunge_all()
    await create_task(session, a.project)
    session.expunge_all()
    await create_task(session, other_project)
    session.expunge_all()

    await poller.drain_guild(system, guild_id, now=datetime.now(timezone.utc))

    named = {
        change["initiative_id"] for envelope in sent for change in envelope["changes"]
    }
    assert named == {a.initiative.id}


async def test_a_community_subscription_hears_every_initiative(
    session: AsyncSession, role_session, acting_user, monkeypatch
):
    """Naming no initiative means the community's changes, which is what a
    guild admin registering one is asking for."""
    from app.services.tenant import outbox_poller as poller
    from app.testing import create_task
    from app.testing.factories import create_initiative, create_project

    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    guild_id = a.guild.id
    other = await create_initiative(session, a.guild, a.user)
    other_project = await create_project(session, other, a.user)

    await _subscribe(session, guild_id=guild_id, user_id=a.user.id, initiative_id=None)
    sent = _collector(monkeypatch, poller)
    system = await role_session("app_admin")

    session.expunge_all()
    await create_task(session, a.project)
    session.expunge_all()
    await create_task(session, other_project)
    session.expunge_all()

    await poller.drain_guild(system, guild_id, now=datetime.now(timezone.utc))

    named = {
        change["initiative_id"] for envelope in sent for change in envelope["changes"]
    }
    assert named == {a.initiative.id, other.id}


# ---------------------------------------------------------------------------
# A subscription an installed plug-in registered
# ---------------------------------------------------------------------------


#: Another plug-in's event, and the plug-in that emits it.
_GH_EVENT = "plugin.tests.gh.issue_opened"
_EMITTERS = {_GH_EVENT: "tests.gh"}


def _install_context(**overrides):
    from app.db.guild_standing import InstallContext

    defaults = dict(
        guild_id=1,
        install_id=4,
        client_id="tests.plugin",
        token_scopes=frozenset({"files:read"}),
        live=True,
        member_initiatives=(11, 12),
        install_read=("files",),
    )
    defaults.update(overrides)
    return InstallContext(**defaults)


@pytest.mark.parametrize(
    ("overrides", "event_types", "initiative_id"),
    [
        pytest.param({}, ["files.created"], None, id="community-wide"),
        pytest.param({}, ["files.updated"], 12, id="a-placed-initiative"),
        pytest.param({"scope_initiative_id": 11}, ["files.deleted"], 11, id="narrowed"),
        pytest.param(
            {"install_read": ("files", "projects")},
            ["files.created", "tasks.created"],
            None,
            id="every-tool-held",
        ),
        pytest.param(
            {"token_scopes": frozenset({"plugins:tests.gh"})},
            [_GH_EVENT],
            None,
            id="another-plugins-event",
        ),
        pytest.param(
            {"guild_admin": True}, ["demo.link_opened"], None, id="demo-event-admin"
        ),
    ],
)
def test_an_install_may_subscribe_within_its_standing(
    overrides, event_types, initiative_id
):
    from app.services.tenant.webhook_subscriptions import assert_install_may_subscribe

    assert_install_may_subscribe(
        _install_context(**overrides),
        event_types=event_types,
        initiative_id=initiative_id,
        emitters=_EMITTERS,
    )


@pytest.mark.parametrize(
    ("overrides", "event_types", "initiative_id"),
    [
        pytest.param({}, ["tasks.created"], None, id="tool-scope-missing"),
        pytest.param(
            {}, ["files.created", "tasks.created"], None, id="one-type-uncovered"
        ),
        pytest.param({}, ["plugins.created"], None, id="no-scope-reaches-it"),
        pytest.param(
            {"scope_initiative_id": 11},
            ["files.created"],
            None,
            id="narrowed-community-wide",
        ),
        pytest.param(
            {"scope_initiative_id": 11},
            ["files.created"],
            12,
            id="narrowed-other-initiative",
        ),
        pytest.param({}, ["files.created"], 13, id="not-placed"),
        pytest.param({}, [_GH_EVENT], None, id="plugins-scope-missing"),
        pytest.param(
            {"token_scopes": frozenset({"community:admin"})},
            ["demo.lead_left"],
            None,
            id="demo-event-without-admin-standing",
        ),
    ],
)
def test_an_install_may_not_subscribe_beyond_its_standing(
    overrides, event_types, initiative_id
):
    from app.core.messages import PluginMessages
    from app.services.tenant.webhook_subscriptions import (
        WebhookSubscriptionScopeError,
        assert_install_may_subscribe,
    )

    with pytest.raises(WebhookSubscriptionScopeError) as refused:
        assert_install_may_subscribe(
            _install_context(**overrides),
            event_types=event_types,
            initiative_id=initiative_id,
            emitters=_EMITTERS,
        )
    assert refused.value.code == PluginMessages.SCOPE_REQUIRED


_HOOK = "https://app.example.test/hook"


async def _install_subscribes(role_session, install, *, initiative_id=None):
    """The install registers a subscription to files as its community."""
    from app.db.install_standing_test import _route
    from app.schemas.tenant.webhook_subscription import WebhookSubscriptionCreate
    from app.services.tenant.webhook_subscriptions import create_install_subscription

    s, context = await _route(role_session, install, ["files:write"])
    row, _secret = await create_install_subscription(
        s,
        context=context,
        payload=WebhookSubscriptionCreate(
            target_url=_HOOK,
            event_types=["files.created"],
            initiative_id=initiative_id,
        ),
    )
    return row


async def test_an_install_registers_a_subscription_naming_no_person(
    session: AsyncSession, role_session, acting_user
):
    from app.db.install_standing_test import _install

    install = await _install(
        session, acting_user, role_session, granted=["files:write"]
    )
    row = await _install_subscribes(role_session, install)
    assert row.plugin_install_id == install.plugin.id
    assert row.created_by is None
    assert row.initiative_id is None


async def test_a_narrowed_install_cannot_write_a_community_subscription(
    session: AsyncSession, role_session, acting_user
):
    """The same rule the service states, held by the table's own policy."""
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    from app.db.install_standing_test import _install, _route

    install = await _install(session, acting_user, role_session, granted=["files:read"])
    s, _ = await _route(
        role_session, install, ["files:read"], initiative_id=install.a.id
    )
    insert = text(
        "INSERT INTO webhook_subscriptions (initiative_id, plugin_install_id,"
        " target_url, hmac_secret, event_types, created_at, updated_at)"
        " VALUES (:i, :a, 'https://app.example.test/hook', 's3cret',"
        " ARRAY['files.created'], now(), now())"
    )
    with pytest.raises(DBAPIError, match="row-level security"):
        await s.exec(insert.bindparams(i=None, a=install.plugin.id))
    await s.rollback()

    s, _ = await _route(
        role_session, install, ["files:read"], initiative_id=install.a.id
    )
    await s.exec(insert.bindparams(i=install.a.id, a=install.plugin.id))
    await s.rollback()


async def _grant_scopes(role_session, install, scopes: list[str]) -> None:
    """Change the install's grant the way a community does: by its seat."""
    from app.models.tenant.guild_plugin import GuildPlugin
    from app.testing import route_as

    s = await role_session("app_user")
    await route_as(s, user_id=install.seat.user.id, guild_id=install.guild.id)
    row = (
        await s.exec(select(GuildPlugin).where(GuildPlugin.id == install.plugin.id))
    ).one()
    row.granted_scopes = scopes
    s.add(row)
    await s.commit()


async def _withdraw(session, role_session, install, what: str) -> None:
    """Take one part of the install's reach away."""
    from sqlalchemy import delete

    from app.models.platform.plugin_service_registration import (
        PluginServiceRegistration,
    )
    from app.models.tenant.plugin_placement import PluginPlacement
    from app.models.tenant.guild_plugin import GuildPlugin
    from app.services.marketplace.registration_lookup import invalidate_registrations

    session.expunge_all()
    if what == "placement":
        await route_session_to_guild(session, install.guild.id)
        await session.exec(
            delete(PluginPlacement).where(
                PluginPlacement.install_id == install.plugin.id
            )
        )
        await session.commit()
    elif what == "scope":
        await _grant_scopes(role_session, install, ["comments:read"])
    elif what == "install":
        await route_session_to_guild(session, install.guild.id)
        plugin = await session.get(GuildPlugin, install.plugin.id)
        plugin.enabled = False
        session.add(plugin)
        await session.commit()
    elif what == "registration":
        registration = (
            await session.exec(
                select(PluginServiceRegistration).where(
                    PluginServiceRegistration.listing_uid == install.plugin.listing_uid
                )
            )
        ).one()
        registration.enabled = False
        session.add(registration)
        await session.commit()
        invalidate_registrations()
    else:
        raise AssertionError(what)
    session.expunge_all()


async def test_an_install_hears_what_it_writes_and_is_named_for_it(
    session: AsyncSession, role_session, acting_user, monkeypatch
):
    """An install's subscription carries the files of the initiative it
    is placed in, and names the plug-in when the plug-in wrote the change."""
    from app.db.install_standing_test import CLIENT, _install, _route
    from app.models.tenant.file import File, FileType
    from app.services.tenant import outbox_poller as poller
    from app.testing import create_file

    install = await _install(
        session, acting_user, role_session, granted=["files:write"], placed="a"
    )
    await _install_subscribes(role_session, install)
    sent = _collector(monkeypatch, poller)
    system = await role_session("app_admin")

    session.expunge_all()
    in_a = await create_file(session, install.a, install.seat.user)
    session.expunge_all()
    await create_file(session, install.b, install.seat.user)
    session.expunge_all()

    s, _ = await _route(role_session, install, ["files:write"])
    made = File(
        initiative_id=install.a.id,
        name="By the plug-in",
        file_type=FileType.native,
    )
    s.add(made)
    await s.commit()
    made_id = made.id

    await poller.drain_guild(system, install.guild.id, now=datetime.now(timezone.utc))

    changes = {
        change["resource"]["id"]: envelope
        for envelope in sent
        for change in envelope["changes"]
    }
    # B is not a placed initiative, so its file is not heard.
    assert set(changes) == {in_a.id, made_id}
    assert changes[made_id]["actor_plugin"] == CLIENT
    assert changes[made_id]["actor_ref"] is None
    assert changes[in_a.id]["actor_plugin"] is None


@pytest.mark.parametrize("what", ["placement", "scope", "install", "registration"])
async def test_an_install_hears_nothing_once_its_reach_is_withdrawn(
    session: AsyncSession, role_session, acting_user, monkeypatch, what
):
    from app.db.install_standing_test import _install
    from app.services.tenant import outbox_poller as poller
    from app.testing import create_file

    install = await _install(
        session, acting_user, role_session, granted=["files:read"], placed="a"
    )
    await _install_subscribes(role_session, install, initiative_id=install.a.id)
    sent = _collector(monkeypatch, poller)
    system = await role_session("app_admin")

    session.expunge_all()
    before = await create_file(session, install.a, install.seat.user)
    session.expunge_all()
    await poller.drain_guild(system, install.guild.id, now=datetime.now(timezone.utc))
    assert [c["resource"]["id"] for e in sent for c in e["changes"]] == [before.id]

    await _withdraw(session, role_session, install, what)
    await create_file(session, install.a, install.seat.user)
    session.expunge_all()
    system.expunge_all()
    await poller.drain_guild(system, install.guild.id, now=datetime.now(timezone.utc))
    assert [c["resource"]["id"] for e in sent for c in e["changes"]] == [before.id]


async def test_a_plugins_event_is_kept_until_the_subscriber_accepts_it(
    session: AsyncSession, role_session, acting_user, client, monkeypatch
):
    """An install holding ``plugins:<emitter>`` subscribes to another plug-in's event,
    and an event that plug-in emits is delivered through the poller, retried
    after a refusal."""
    from app.core.plugin_access_token import seal_install_token
    from app.db.install_standing_test import _install, _route
    from app.schemas.tenant.webhook_subscription import WebhookSubscriptionCreate
    from app.services.tenant import outbox_poller as poller
    from app.services.tenant.webhook_subscriptions import create_install_subscription
    from app.testing import create_plugin_service_registration, create_guild_plugin

    install = await _install(
        session, acting_user, role_session, granted=["plugins:tests.gh"], placed="a"
    )
    emitter = await create_guild_plugin(
        session,
        install.guild,
        install.seat.user,
        listing_uid="GHEMTTER000001",
        definition={
            "plugin_kind": "service",
            "service": {"public_id": "tests.gh", "protocol": 1},
            "endpoints": [{"id": _GH_EVENT, "direction": "emit"}],
        },
    )
    await create_plugin_service_registration(
        session, public_id="tests.gh", listing_uid="GHEMTTER000001"
    )
    s, context = await _route(role_session, install, ["plugins:tests.gh"])
    await create_install_subscription(
        s,
        context=context,
        payload=WebhookSubscriptionCreate(target_url=_HOOK, event_types=[_GH_EVENT]),
    )

    token, _ = seal_install_token(
        guild_id=install.guild.id,
        install_id=emitter.id,
        client_id="tests.gh",
        scopes=frozenset(),
        initiative_id=None,
        user_id=None,
        purpose=None,
    )
    emitted = await client.post(
        "/api/v1/plugin-platform/installation/events",
        json={"event_type": _GH_EVENT, "payload": {"number": 12}},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert emitted.status_code == 202, emitted.text

    attempts: list[dict] = []

    async def _refuse_the_first(*, target_url, secret, envelope):
        attempts.append(envelope)
        return len(attempts) > 1

    monkeypatch.setattr(poller, "deliver", _refuse_the_first)
    system = await role_session("app_admin")
    now = datetime.now(timezone.utc)
    await poller.drain_guild(system, install.guild.id, now=now)
    system.expunge_all()
    await poller.drain_guild(system, install.guild.id, now=now + timedelta(hours=2))

    assert [attempt["event_id"] for attempt in attempts] == [
        attempts[0]["event_id"]
    ] * 2
    assert attempts[1]["actor_plugin"] == "tests.gh"
    assert attempts[1]["changes"] == [
        {
            "event_type": _GH_EVENT,
            "initiative_id": None,
            "plugin": "tests.gh",
            "payload": {"number": 12},
        }
    ]


async def test_a_declarative_plugins_event_reaches_a_subscriber_as_a_containers_does(
    session: AsyncSession, role_session, acting_user, client, monkeypatch
):
    """A plug-in whose deliveries Initiative maps is named by its listing, so an
    install may subscribe to its event; what reaches the subscriber is what
    the same plug-in emitting the same event from a container delivers."""
    from app.core.plugin_access_token import seal_install_token
    from app.db.install_standing_test import _install, _route
    from app.models.platform.plugin_service_registration import RegistrationKind
    from app.models.tenant.guild_plugin import GuildPlugin
    from app.schemas.tenant.webhook_subscription import WebhookSubscriptionCreate
    from app.services.marketplace.registration_lookup import invalidate_registrations
    from app.services.tenant import outbox_poller as poller
    from app.services.tenant.webhook_subscriptions import create_install_subscription
    from app.testing import (
        create_plugin_service_registration,
        create_guild_plugin,
        create_marketplace_listing,
        sealed_vendor_values,
    )
    from app.testing.fake_vendor import FakeVendor, declarative_github

    public_id, listing_uid = "tests.ghd", "GHDECXARE00001"
    event_type = f"plugin.{public_id}.issue-opened"
    vendor = FakeVendor()
    vendor.install(monkeypatch)
    install = await _install(
        session, acting_user, role_session, granted=[f"plugins:{public_id}"], placed="a"
    )
    definition = declarative_github(public_id)
    registration = await create_plugin_service_registration(
        session,
        public_id=public_id,
        listing_uid=listing_uid,
        kind="declarative",
        vendor_values=sealed_vendor_values(
            {field["key"]: "x" for field in definition["vendor"]["fields"]}
            | {"webhook_secret": vendor.webhook_secret}
        ),
    )
    await create_marketplace_listing(
        session,
        uid=listing_uid,
        public_id=public_id,
        kind="plugin",
        definition=definition,
    )
    emitter = await create_guild_plugin(
        session,
        install.guild,
        install.seat.user,
        listing_uid=listing_uid,
        definition=definition,
        config={"workspace": {"owner": "acme", "installation_id": "42"}},
    )
    s, context = await _route(role_session, install, [f"plugins:{public_id}"])
    await create_install_subscription(
        s,
        context=context,
        payload=WebhookSubscriptionCreate(target_url=_HOOK, event_types=[event_type]),
    )
    sent = _collector(monkeypatch, poller)
    system = await role_session("app_admin")

    body, headers = vendor.webhook(
        {
            "action": "opened",
            "installation": {"id": 42},
            "repository": {"full_name": "acme/web"},
            "issue": {"number": 12, "title": "Broken build"},
        }
    )
    response = await client.post(
        f"/api/v1/plugin-hooks/{public_id}", content=body, headers=headers
    )
    assert response.status_code == 202, response.text
    await poller.drain_guild(system, install.guild.id, now=datetime.now(timezone.utc))
    [declared] = sent
    assert declared["changes"] == [
        {
            "event_type": event_type,
            "initiative_id": None,
            "plugin": public_id,
            "payload": {
                "repository": "acme/web",
                "number": 12,
                "title": "Broken build",
            },
        }
    ]

    # The same plug-in, as a container emitting the same event.
    registration.kind = RegistrationKind.CONTAINER
    session.add(registration)
    await session.commit()
    invalidate_registrations()
    await route_session_to_guild(session, install.guild.id)
    row = (
        await session.exec(select(GuildPlugin).where(GuildPlugin.id == emitter.id))
    ).one()
    row.definition = {
        "plugin_kind": "service",
        "service": {"public_id": public_id, "protocol": 1},
        "endpoints": [
            entry for entry in definition["endpoints"] if entry["id"] == event_type
        ],
    }
    session.add(row)
    await session.commit()
    token, _ = seal_install_token(
        guild_id=install.guild.id,
        install_id=emitter.id,
        client_id=public_id,
        scopes=frozenset(),
        initiative_id=None,
        user_id=None,
        purpose=None,
    )
    emitted = await client.post(
        "/api/v1/plugin-platform/installation/events",
        json={"event_type": event_type, "payload": declared["changes"][0]["payload"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert emitted.status_code == 202, emitted.text
    system.expunge_all()
    await poller.drain_guild(system, install.guild.id, now=datetime.now(timezone.utc))
    [_, contained] = sent

    def _same(envelope: dict) -> dict:
        return {
            key: value
            for key, value in envelope.items()
            if key not in ("event_id", "occurred_at")
        }

    assert _same(declared) == _same(contained)
