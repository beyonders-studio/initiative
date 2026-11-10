"""What a listing's package terms change about installing and removing it.

* **Install gating.** An ``entitled`` listing installs only in a community
  holding an active statement for it; the catalog shows it unavailable, with
  where to go about it. A statement is active unless it says ``active: false``.
* **Install pings.** Installing or removing a listing with terms tells
  billing, naming the community by billing's reference; one without terms
  tells nobody. Installing also hands the plug-in the statement already held.
* **The uninstall notice.** The removal dialog asks billing what to say, and
  shows neutral text when billing does not answer in time.
* **The offer.** A listing's page asks billing how this community gets a
  plug-in it can't install, or whose plan has ended, and shows the answer as
  given; with no answer it shows where to go, as before.
"""

from __future__ import annotations

import asyncio
import json
from typing import ClassVar

import httpx2
import pytest
from httpx2 import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import config as config_module
from app.core.messages import GuildPluginMessages
from app.db import post_commit
from app.models.platform.guild import CommunityRole
from app.services import sweep_timers
from app.services.marketplace import plugin_entitlements, tuf_registry
from app.services.platform import billing_ping
from app.services.tenant import plugin_connection_flows as flows
from app.testing import (
    billing_guild_ref,
    create_listing_with_terms,
    create_marketplace_listing,
    create_plugin_service_registration,
    entitlement_statement,
    marketplace_uid,
)
from app.testing.billing_boundary import configure_outbound, served_changes
from app.testing.billing_managed import billing_manages_plans

SERVICE_ID = "tests.paidco"
SERVICE_UID = marketplace_uid("paidco")
BILLING = "https://billing.test"
PORTAL = "https://portal.test"


def _definition() -> dict:
    return {
        "plugin_kind": "service",
        "service": {"public_id": SERVICE_ID, "protocol": 1, "scopes": []},
        "default_name": "PaidCo",
    }


async def _hold(guild_id: int, values: dict, *, version: int = 1) -> str:
    """Keep a statement of ``values`` for the community at ``version``, as the
    billing verb would; the signed statement is returned."""
    statement = entitlement_statement(
        community_ref=await billing_guild_ref(guild_id),
        listing_uid=SERVICE_UID,
        version=version,
        values=values,
    )
    await plugin_entitlements.store_statement(
        guild_id, SERVICE_UID, statement=statement, version=version, values=values
    )
    return statement


@pytest.fixture(autouse=True)
def shipped_root(monkeypatch):
    monkeypatch.setattr(tuf_registry, "configured_root_is_builtin", lambda: True)


@pytest.fixture
async def registered(session: AsyncSession):
    await create_plugin_service_registration(
        session,
        public_id=SERVICE_ID,
        base_url="https://paidco.example.test",
        listing_uid=SERVICE_UID,
    )


@pytest.fixture
async def entitled(session: AsyncSession, registered):
    return await create_listing_with_terms(
        session,
        uid=SERVICE_UID,
        public_id=SERVICE_ID,
        access="entitled",
        name="PaidCo",
        definition=_definition(),
    )


@pytest.fixture
def billing(monkeypatch):
    """Billing configured, with its answers scripted; ``sent`` records every
    request this deployment makes to it."""

    class Billing:
        sent: ClassVar[list[tuple[str, dict]]] = []
        answer: dict | None = None
        status: int = 200
        delay: float = 0.0

    configure_outbound(monkeypatch, BILLING)
    monkeypatch.setattr(config_module.settings, "BILLING_URL", PORTAL)
    Billing.sent = []
    Billing.answer = None
    Billing.status = 200
    Billing.delay = 0.0

    async def answer(request: httpx2.Request) -> httpx2.Response:
        Billing.sent.append((str(request.url), json.loads(request.content)))
        if Billing.delay:
            await asyncio.sleep(Billing.delay)
        if Billing.answer is None:
            return httpx2.Response(204)
        return httpx2.Response(Billing.status, json=Billing.answer)

    real = httpx2.AsyncClient

    def client(**kwargs):
        # A real client on a mock transport, so a streamed read is answered
        # the same as a plain one.
        return real(**kwargs, transport=httpx2.MockTransport(answer))

    monkeypatch.setattr(billing_ping.httpx2, "AsyncClient", client)
    return Billing


@pytest.fixture
def hooks(monkeypatch) -> list[tuple[str, dict]]:
    delivered: list[tuple[str, dict]] = []

    async def call_hook(name, *, body, **_kwargs):
        if name == plugin_entitlements.ENTITLEMENT_HOOK:
            delivered.append((name, dict(body)))

    monkeypatch.setattr(flows, "call_hook", call_hook)
    return delivered


async def _settle() -> None:
    # A step started by a commit may start a ping of its own.
    for _ in range(3):
        await post_commit.settle_all()
    # And every hook the commits wrote, sent by the timers they armed.
    await sweep_timers.process_due_timers(outward=True)


async def _install(client: AsyncClient, actor):
    response = await client.post(
        actor.g("/plugins/"), headers=actor.headers, json={"listing_uid": SERVICE_UID}
    )
    await _settle()
    return response


async def _seat(acting_user):
    return await acting_user(guild_role=CommunityRole.superadmin)


# --- install gating ------------------------------------------------------------


class TestGating:
    async def test_an_entitled_listing_without_a_statement_does_not_install(
        self, client: AsyncClient, acting_user, entitled, billing
    ):
        a = await _seat(acting_user)

        response = await _install(client, a)

        assert response.status_code == 409
        assert response.json()["detail"] == GuildPluginMessages.ENTITLEMENT_REQUIRED

    async def test_a_full_term_shows_a_request_and_never_hides_the_listing(
        self, client: AsyncClient, acting_user, entitled, billing
    ):
        """Billing marks a community the deployment's term has no seat for:
        the listing is still shown, with a request rather than a purchase, and
        it still doesn't install."""
        a = await _seat(acting_user)
        await _hold(a.guild.id, {"active": False, "reason": "term_full"})

        detail = await client.get(
            a.g(f"/marketplace/listings/by-uid/{SERVICE_UID}"), headers=a.headers
        )
        browse = await client.get(
            a.g("/marketplace/listings"), headers=a.headers, params={"kind": "plugin"}
        )
        install = await _install(client, a)

        assert detail.status_code == 200, detail.text
        assert detail.json()["unavailable"] == {
            "reason": "term_full",
            "action_url": None,
            "offer": None,
        }
        assert [
            item["unavailable"]
            for item in browse.json()["items"]
            if item["uid"] == SERVICE_UID
        ] == [{"reason": "term_full", "action_url": None, "offer": None}]
        assert install.status_code == 409

    async def test_an_install_whose_term_fills_says_so_on_its_page(
        self, client: AsyncClient, acting_user, entitled, billing, hooks
    ):
        """The plug-in's page reads the statement held for the install: once
        billing marks the term full, the page shows the request in place of
        the plug-in."""
        a = await _seat(acting_user)
        await _hold(a.guild.id, {"active": True})
        installed = await _install(client, a)
        assert installed.status_code == 201, installed.text
        page = a.g(f"/plugins/{installed.json()['id']}")

        working = await client.get(page, headers=a.headers)
        await _hold(a.guild.id, {"active": False, "reason": "term_full"}, version=2)
        full = await client.get(page, headers=a.headers)

        assert working.json()["entitlement"] == {
            "active": True,
            "reason": None,
            "action_url": None,
        }
        assert full.json()["entitlement"] == {
            "active": False,
            "reason": "term_full",
            "action_url": None,
        }

    async def test_the_catalog_says_it_is_unavailable_and_where_to_go(
        self, client: AsyncClient, acting_user, entitled, billing
    ):
        a = await _seat(acting_user)
        expected = {
            "reason": "entitlement_required",
            "action_url": f"{PORTAL}/manage?app={SERVICE_UID}",
            "offer": None,
        }

        detail = await client.get(
            a.g(f"/marketplace/listings/by-uid/{SERVICE_UID}"), headers=a.headers
        )
        browse = await client.get(
            a.g("/marketplace/listings"),
            headers=a.headers,
            params={"kind": "plugin"},
        )

        assert detail.status_code == 200, detail.text
        assert detail.json()["unavailable"] == expected
        [card] = [i for i in browse.json()["items"] if i["uid"] == SERVICE_UID]
        assert card["unavailable"] == expected

    async def test_an_active_statement_lets_it_install(
        self, client: AsyncClient, acting_user, entitled, billing, hooks
    ):
        a = await _seat(acting_user)
        statement = await _hold(a.guild.id, {"active": True})

        detail = await client.get(
            a.g(f"/marketplace/listings/by-uid/{SERVICE_UID}"), headers=a.headers
        )
        response = await _install(client, a)

        assert detail.json()["unavailable"] is None
        assert response.status_code == 201, response.text
        # The statement already held is handed to the plug-in it was for.
        assert hooks == [("entitlement", {"statement": statement})]

    async def test_a_statement_that_says_inactive_does_not(
        self, client: AsyncClient, acting_user, entitled, billing
    ):
        a = await _seat(acting_user)
        await _hold(a.guild.id, {"active": False})

        response = await _install(client, a)

        assert response.status_code == 409

    async def test_a_statement_saying_nothing_of_active_counts(
        self, client: AsyncClient, acting_user, entitled, billing, hooks
    ):
        a = await _seat(acting_user)
        await _hold(a.guild.id, {"owned": ["pack-1"]})

        response = await _install(client, a)

        assert response.status_code == 201, response.text

    async def test_under_another_root_nothing_is_gated(
        self, client: AsyncClient, acting_user, entitled, billing, monkeypatch
    ):
        monkeypatch.setattr(tuf_registry, "configured_root_is_builtin", lambda: False)
        a = await _seat(acting_user)

        response = await _install(client, a)

        assert response.status_code == 201, response.text
        # Nor is anybody told: the listing holds no terms here.
        assert billing.sent == []


# --- install pings -----------------------------------------------------------------


class TestInstallChanges:
    """Billing hears of installs and uninstalls from its change log, and only
    of listings a package names terms for."""

    async def test_installing_and_removing_tell_billing(
        self, client: AsyncClient, session: AsyncSession, acting_user, entitled, hooks
    ):
        a = await _seat(acting_user)
        await _hold(a.guild.id, {"active": True})
        ref = await billing_guild_ref(a.guild.id)

        async with billing_manages_plans(session):
            installed = await _install(client, a)
            # The install index follows the installs on its sweep.
            await sweep_timers.process_due_timers()
            removed = await client.delete(
                a.g(f"/plugins/{installed.json()['id']}"), headers=a.headers
            )
            await _settle()
            await sweep_timers.process_due_timers()
            assert removed.status_code == 204, removed.text
            served, _cursor = await served_changes()

        assert [
            (c["kind"], c["community_ref"], c["listing_uid"])
            for c in served
            if c["kind"].startswith("plugin.")
        ] == [
            ("plugin.installed", ref, SERVICE_UID),
            ("plugin.uninstalled", ref, SERVICE_UID),
        ]

    async def test_a_listing_without_terms_tells_nobody(
        self,
        client: AsyncClient,
        acting_user,
        session: AsyncSession,
        registered,
    ):
        await create_marketplace_listing(
            session,
            uid=SERVICE_UID,
            public_id=SERVICE_ID,
            kind="plugin",
            definition=_definition(),
        )
        a = await _seat(acting_user)

        async with billing_manages_plans(session):
            installed = await _install(client, a)
            await client.delete(
                a.g(f"/plugins/{installed.json()['id']}"), headers=a.headers
            )
            await _settle()
            await sweep_timers.process_due_timers()
            served, _cursor = await served_changes()

        assert installed.status_code == 201, installed.text
        assert [c for c in served if c["kind"].startswith("plugin.")] == []


# --- the uninstall notice ----------------------------------------------------------


class TestUninstallNotice:
    async def _installed(self, client, acting_user):
        a = await _seat(acting_user)
        await _hold(a.guild.id, {"active": True})
        response = await _install(client, a)
        assert response.status_code == 201, response.text
        return a, response.json()["id"]

    async def _notice(self, client, a, plugin_id, locale="de"):
        return await client.get(
            a.g(f"/plugins/{plugin_id}/uninstall-notice"),
            headers=a.headers,
            params={"locale": locale},
        )

    async def test_billing_words_are_shown_as_given(
        self, client: AsyncClient, acting_user, entitled, billing, hooks
    ):
        a, plugin_id = await self._installed(client, acting_user)
        billing.sent = []
        billing.answer = {
            "message": "Die App läuft bis zum 30. November weiter.",
            "action_url": "https://portal.test/apps/x",
        }

        response = await self._notice(client, a, plugin_id)

        assert response.status_code == 200, response.text
        assert response.json() == {
            "managed": True,
            "message": "Die App läuft bis zum 30. November weiter.",
            "action_url": "https://portal.test/apps/x",
        }
        [(url, body)] = billing.sent
        assert url == f"{BILLING}/api/v1/plugin-uninstall-notice"
        assert body == {
            "community_ref": await billing_guild_ref(a.guild.id),
            "listing_uid": SERVICE_UID,
            "locale": "de",
        }

    async def test_billing_too_slow_is_neutral_text(
        self, client: AsyncClient, acting_user, entitled, billing, hooks, monkeypatch
    ):
        a, plugin_id = await self._installed(client, acting_user)
        monkeypatch.setattr(billing_ping, "UNINSTALL_NOTICE_SECONDS", 0.05)
        billing.answer = {"message": "Too late to be read."}
        billing.delay = 1.0

        response = await self._notice(client, a, plugin_id)

        assert response.status_code == 200
        assert response.json() == {
            "managed": True,
            "message": None,
            "action_url": f"{PORTAL}/manage?app={SERVICE_UID}",
        }

    async def test_an_unreadable_answer_is_neutral_text(
        self, client: AsyncClient, acting_user, entitled, billing, hooks
    ):
        a, plugin_id = await self._installed(client, acting_user)
        billing.answer = {"message": "", "action_url": "javascript:alert(1)"}

        response = await self._notice(client, a, plugin_id)

        assert response.json()["message"] is None
        assert response.json()["action_url"].startswith(PORTAL)

    async def test_without_billing_the_text_is_neutral(
        self, client: AsyncClient, acting_user, entitled, hooks, monkeypatch
    ):
        monkeypatch.setattr(config_module.settings, "BILLING_SERVICE_URL", None)
        monkeypatch.setattr(config_module.settings, "BILLING_URL", None)
        a, plugin_id = await self._installed(client, acting_user)

        response = await self._notice(client, a, plugin_id)

        assert response.json() == {"managed": True, "message": None, "action_url": None}

    async def test_a_listing_without_terms_has_nothing_to_say(
        self,
        client: AsyncClient,
        acting_user,
        session: AsyncSession,
        registered,
        billing,
    ):
        await create_marketplace_listing(
            session,
            uid=SERVICE_UID,
            public_id=SERVICE_ID,
            kind="plugin",
            definition=_definition(),
        )
        a = await _seat(acting_user)
        installed = await _install(client, a)

        response = await self._notice(client, a, installed.json()["id"])

        assert response.json() == {
            "managed": False,
            "message": None,
            "action_url": None,
        }
        assert billing.sent == []

    async def test_a_member_does_not_read_it(
        self, client: AsyncClient, acting_user, entitled, billing, hooks
    ):
        a, plugin_id = await self._installed(client, acting_user)
        member = await acting_user(guild_role=CommunityRole.member, guild=a.guild)

        response = await self._notice(client, member, plugin_id)

        assert response.status_code == 403


# --- the offer ------------------------------------------------------------------------

_OFFER = {
    "charge": "subscription",
    "way": "buy",
    "upgrade": False,
    "lines": [{"id": "paidco-small", "name": "Klein", "display": "12 $/Monat"}],
}


class TestOffer:
    async def _page(self, client, a, locale="de"):
        return await client.get(
            a.g(f"/marketplace/listings/by-uid/{SERVICE_UID}"),
            headers=a.headers,
            params={"locale": locale},
        )

    async def test_the_page_shows_billings_offer_as_given(
        self, client: AsyncClient, acting_user, entitled, billing
    ):
        a = await _seat(acting_user)
        ref = await billing_guild_ref(a.guild.id)
        billing.answer = _OFFER

        response = await self._page(client, a)

        assert response.status_code == 200, response.text
        assert response.json()["unavailable"] == {
            "reason": "entitlement_required",
            "action_url": f"{PORTAL}/manage?app={SERVICE_UID}",
            "offer": _OFFER,
        }
        [(url, body)] = billing.sent
        assert url == f"{BILLING}/api/v1/plugin-offer"
        assert body == {
            "community_ref": ref,
            "listing_uid": SERVICE_UID,
            "locale": "de",
        }

    async def test_the_page_by_public_id_shows_it_too(
        self, client: AsyncClient, acting_user, entitled, billing
    ):
        a = await _seat(acting_user)
        await billing_guild_ref(a.guild.id)
        billing.answer = {**_OFFER, "way": "none", "upgrade": True}

        response = await client.get(
            a.g(f"/marketplace/listings/{SERVICE_ID}"),
            headers=a.headers,
            params={"locale": "fr"},
        )

        assert response.status_code == 200, response.text
        offer = response.json()["unavailable"]["offer"]
        assert (offer["way"], offer["upgrade"]) == ("none", True)
        [(_url, body)] = billing.sent
        assert body["locale"] == "fr"

    async def test_an_installed_plug_in_whose_plan_ended_is_offered_again(
        self, client: AsyncClient, acting_user, entitled, billing, hooks
    ):
        a = await _seat(acting_user)
        await _hold(a.guild.id, {"active": True})
        installed = await _install(client, a)
        assert installed.status_code == 201, installed.text
        await _hold(a.guild.id, {"active": False}, version=2)
        billing.sent = []
        billing.answer = _OFFER

        page = await self._page(client, a)
        plugin = await client.get(
            a.g(f"/plugins/{installed.json()['id']}"), headers=a.headers
        )

        assert page.json()["unavailable"]["offer"] == _OFFER
        assert [url for url, _body in billing.sent] == [
            f"{BILLING}/api/v1/plugin-offer"
        ]
        # The install's own read says it ended, and where to get it again.
        assert plugin.json()["entitlement"] == {
            "active": False,
            "reason": None,
            "action_url": f"{PORTAL}/manage?app={SERVICE_UID}",
        }

    async def test_a_listing_billing_does_not_sell_has_no_offer(
        self, client: AsyncClient, acting_user, entitled, billing
    ):
        a = await _seat(acting_user)
        await billing_guild_ref(a.guild.id)
        billing.status = 404
        billing.answer = {"detail": "OFFER_UNKNOWN_LISTING"}

        response = await self._page(client, a)

        assert response.status_code == 200, response.text
        assert response.json()["unavailable"] == {
            "reason": "entitlement_required",
            "action_url": f"{PORTAL}/manage?app={SERVICE_UID}",
            "offer": None,
        }

    async def test_a_full_term_asks_billing_nothing(
        self, client: AsyncClient, acting_user, entitled, billing
    ):
        a = await _seat(acting_user)
        await _hold(a.guild.id, {"active": False, "reason": "term_full"})
        billing.answer = _OFFER

        response = await self._page(client, a)

        assert response.json()["unavailable"]["offer"] is None
        assert billing.sent == []

    async def test_an_installable_listing_asks_billing_nothing(
        self, client: AsyncClient, acting_user, entitled, billing
    ):
        a = await _seat(acting_user)
        await _hold(a.guild.id, {"active": True})
        billing.answer = _OFFER

        response = await self._page(client, a)

        assert response.json()["unavailable"] is None
        assert billing.sent == []

    async def test_the_shelf_asks_billing_nothing(
        self, client: AsyncClient, acting_user, entitled, billing
    ):
        a = await _seat(acting_user)
        await billing_guild_ref(a.guild.id)
        billing.answer = _OFFER

        browse = await client.get(
            a.g("/marketplace/listings"), headers=a.headers, params={"kind": "plugin"}
        )

        [card] = [i for i in browse.json()["items"] if i["uid"] == SERVICE_UID]
        assert card["unavailable"]["offer"] is None
        assert billing.sent == []

    async def test_without_billing_there_is_no_offer(
        self, client: AsyncClient, acting_user, entitled, monkeypatch
    ):
        monkeypatch.setattr(config_module.settings, "BILLING_SERVICE_URL", None)
        monkeypatch.setattr(config_module.settings, "BILLING_URL", None)
        a = await _seat(acting_user)

        response = await self._page(client, a)

        assert response.status_code == 200, response.text
        assert response.json()["unavailable"] == {
            "reason": "entitlement_required",
            "action_url": None,
            "offer": None,
        }

    async def test_a_locale_that_is_not_one_is_refused(
        self, client: AsyncClient, acting_user, entitled, billing
    ):
        a = await _seat(acting_user)

        response = await self._page(client, a, locale="de; drop")

        assert response.status_code == 422
