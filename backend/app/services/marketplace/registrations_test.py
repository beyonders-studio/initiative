"""Tests for the plug-in service registration service.

A registration is stated, not discovered: nothing here calls a plug-in. Its plug-in
facts come from its listing, whatever the source; its deployment facts from
the operator.
"""

import json

import httpx2
import pytest
from fastapi import HTTPException
from sqlmodel import select

from app.core.config import settings
from app.core.messages import PluginServiceMessages
from app.models.platform.plugin_service_registration import (
    LISTING_STATED_FIELDS,
    PluginServiceRegistration,
)
from app.models.platform.publisher import Publisher
from app.services.marketplace import registrations as service
from app.services.marketplace.catalog import (
    CatalogError,
    CatalogSourceConflict,
    upsert_listing,
)
from app.services.marketplace.plugin_keys import jwk_thumbprint
from app.services.marketplace.registration_lookup import load_registrations
from app.services.marketplace.vendor_values import load_vendor_values
from app.testing import create_plugin_service_registration, sample_plugin_jwks
from app.testing.fake_vendor import declarative_plugin
from app.testing.tuf_repository import service_plugin_definition

#: Where the deployment calls the plug-in.
BASE_URL = "http://127.0.0.1:9100"
#: A plug-in served over https, for the key set address.
HTTPS_BASE_URL = "https://widgets.example.com"
#: A public address for the same plug-in, standing in for what a reverse proxy
#: publishes while ``BASE_URL`` stays the address the deployment itself calls.
PAGE_ORIGIN = "https://widgets.example.com"
#: The catalog listing the plug-in speaks for.
LISTING_UID = "K7M2QX8N4TVB9C"


@pytest.fixture(autouse=True)
def _signing_key(monkeypatch):
    """The plug-in platform requires its own keypair; these tests are about the
    registry rather than the fail-closed path, so give it one."""
    monkeypatch.setattr(
        settings,
        "PLUGIN_PLATFORM_SIGNING_PRIVATE_KEY_PEM",
        "-----BEGIN PRIVATE KEY-----",
    )


def _ed25519_jwk(kid: str) -> dict:
    """A usable public JWK, generated rather than pasted so the test asserts on
    the parser rather than on one frozen key."""
    from cryptography.hazmat.primitives.asymmetric import ed25519
    from jwt.algorithms import OKPAlgorithm

    key = ed25519.Ed25519PrivateKey.generate()
    jwk = json.loads(OKPAlgorithm.to_jwk(key.public_key()))
    jwk["kid"] = kid
    return jwk


def test_jwks_accepts_a_usable_key_set():
    key_set = {"keys": [_ed25519_jwk("auto.core-1")]}
    assert service.normalize_jwks(key_set) == key_set


def test_jwks_treats_empty_as_cleared():
    assert service.normalize_jwks(None) is None
    assert service.normalize_jwks({}) is None


def test_jwks_requires_a_kid_on_every_key():
    keyless = _ed25519_jwk("dropped")
    del keyless["kid"]
    with pytest.raises(HTTPException) as excinfo:
        service.normalize_jwks({"keys": [keyless]})
    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == PluginServiceMessages.INVALID_JWKS


def test_jwks_refuses_two_keys_sharing_a_kid():
    with pytest.raises(HTTPException) as excinfo:
        service.normalize_jwks({"keys": [_ed25519_jwk("same"), _ed25519_jwk("same")]})
    assert excinfo.value.detail == PluginServiceMessages.INVALID_JWKS


def test_jwks_refuses_a_private_key():
    """The column is served in full to the owner's settings, so it holds the half
    that is meant to be read."""
    from cryptography.hazmat.primitives.asymmetric import ed25519
    from jwt.algorithms import OKPAlgorithm

    key = ed25519.Ed25519PrivateKey.generate()
    private_jwk = json.loads(OKPAlgorithm.to_jwk(key))
    private_jwk["kid"] = "pasted-the-whole-key"

    with pytest.raises(HTTPException) as excinfo:
        service.normalize_jwks({"keys": [private_jwk]})
    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == PluginServiceMessages.INVALID_JWKS


@pytest.mark.parametrize("kind", ["rsa", "p-256"])
def test_jwks_refuses_a_key_that_is_not_ed25519(kind):
    """A plug-in signs with Ed25519; any other key is refused when registered,
    not when it first fails to authenticate."""
    from cryptography.hazmat.primitives.asymmetric import ec, rsa
    from jwt.algorithms import ECAlgorithm, RSAAlgorithm

    if kind == "rsa":
        jwk = json.loads(
            RSAAlgorithm.to_jwk(
                rsa.generate_private_key(
                    public_exponent=65537, key_size=2048
                ).public_key()
            )
        )
    else:
        jwk = json.loads(
            ECAlgorithm.to_jwk(ec.generate_private_key(ec.SECP256R1()).public_key())
        )
    jwk["kid"] = "not-ed25519"

    with pytest.raises(HTTPException) as excinfo:
        service.normalize_jwks({"keys": [jwk]})
    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == PluginServiceMessages.INVALID_JWKS


def test_jwks_refuses_a_symmetric_key():
    with pytest.raises(HTTPException) as excinfo:
        service.normalize_jwks(
            {"keys": [{"kid": "shared", "kty": "oct", "k": "c2hhcmVkLXNlY3JldA"}]}
        )
    assert excinfo.value.detail == PluginServiceMessages.INVALID_JWKS


@pytest.mark.parametrize(
    "value",
    [
        {"keys": []},
        {"keys": "not-a-list"},
        {"keys": [{"kid": "k", "kty": "banana"}]},
        {"keys": ["not-an-object"]},
        {"no_keys_member": True},
    ],
)
def test_jwks_refuses_a_set_it_could_not_verify_with(value):
    with pytest.raises(HTTPException) as excinfo:
        service.normalize_jwks(value)
    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == PluginServiceMessages.INVALID_JWKS


def test_base_url_and_origin_shapes_are_enforced():
    assert service.normalize_base_url("http://127.0.0.1:9100/") == (
        "http://127.0.0.1:9100"
    )
    assert service.normalize_origin("https://app.example.com/") == (
        "https://app.example.com"
    )
    for bad in ("ftp://x", "http://", "http://h?a=b", "not-a-url"):
        with pytest.raises(HTTPException):
            service.normalize_base_url(bad)
    for bad in ("https://app.example.com/path", "*", "https://"):
        with pytest.raises(HTTPException):
            service.normalize_origin(bad)


def test_origins_default_to_the_browser_base_origin():
    """The list holds browser origins, so it is derived from the address a
    browser uses — the wire surface only when the plug-in answers on one address."""
    assert service.normalize_origins(None, browser_base=BASE_URL) == [BASE_URL]
    assert service.normalize_origins(None, browser_base=f"{PAGE_ORIGIN}/plugins/x") == [
        PAGE_ORIGIN
    ]


def test_page_origin_accepts_a_base_and_reports_its_own_code():
    """Held to the same shape as base_url, since it stands in for it — a
    deployment publishing a plug-in under a path prefix says so here too."""
    assert service.normalize_page_origin(f"{PAGE_ORIGIN}/auto/") == (
        f"{PAGE_ORIGIN}/auto"
    )
    for bad in ("ftp://x", "http://", "https://h#frag", "not-a-url"):
        with pytest.raises(HTTPException) as excinfo:
            service.normalize_page_origin(bad)
        assert excinfo.value.detail == PluginServiceMessages.INVALID_PAGE_ORIGIN


# --- signing key -------------------------------------------------------------


async def _create(session, **overrides):
    fields = {"public_id": "acme.widgets", "base_url": BASE_URL, **overrides}
    return await service.create_registration(session, **fields)


async def test_registration_fails_closed_without_a_signing_key(session, monkeypatch):
    """The plugin-platform keypair is required and has no fallback to any other
    configured key, so the registry refuses rather than borrowing one."""
    monkeypatch.setattr(settings, "PLUGIN_PLATFORM_SIGNING_PRIVATE_KEY_PEM", None)

    with pytest.raises(HTTPException) as excinfo:
        await _create(session)

    assert excinfo.value.status_code == 503
    assert excinfo.value.detail == PluginServiceMessages.SIGNING_NOT_CONFIGURED


# --- create ------------------------------------------------------------------


async def test_create_stores_what_it_is_told(session):
    """Nothing is fetched: the id and the keys are the operator's, and the plug-in
    facts wait for its listing."""
    key_set = {"keys": [_ed25519_jwk("acme.widgets-1")]}
    row = await _create(session, jwks=key_set)

    assert row.public_id == "acme.widgets"
    assert row.listing_uid is None
    assert row.scope_ceiling == []
    assert row.jwks == key_set
    assert row.jwks_uri is None


async def test_duplicate_public_id_is_refused(session):
    await _create(session)

    with pytest.raises(HTTPException) as excinfo:
        await _create(session)

    assert excinfo.value.status_code == 409
    assert excinfo.value.detail == PluginServiceMessages.DUPLICATE_PUBLIC_ID


async def test_a_new_prefix_gets_an_unverified_publisher(session):
    row = await _create(session, public_id="newpub.widgets")

    publisher = await session.get(Publisher, row.publisher_id)
    assert publisher is not None
    assert publisher.prefix == "newpub"
    assert publisher.verified is False
    assert publisher.enabled is True


async def test_a_known_prefix_keeps_its_publisher_as_it_is(session):
    """A registration under a switched-off publisher joins it switched off."""
    session.add(Publisher(prefix="offpub", display_name="Off", enabled=False))
    await session.commit()

    row = await _create(session, public_id="offpub.widgets")

    publisher = await session.get(Publisher, row.publisher_id)
    assert publisher.enabled is False
    snapshot = (await load_registrations(force=True))["offpub.widgets"]
    assert snapshot.enabled is True
    assert snapshot.live is False


# --- keys --------------------------------------------------------------------


async def test_live_needs_a_key_set(session):
    await _create(session, public_id="acme.keyless")
    await _create(
        session,
        public_id="acme.keyed",
        jwks={"keys": [_ed25519_jwk("acme.keyed-1")]},
    )
    await _create(
        session,
        public_id="acme.published",
        base_url=HTTPS_BASE_URL,
        jwks_uri=f"{HTTPS_BASE_URL}/.well-known/jwks.json",
    )

    snapshots = await load_registrations(force=True)
    assert snapshots["acme.keyless"].live is False
    assert snapshots["acme.keyed"].live is True
    assert snapshots["acme.published"].live is True


@pytest.mark.parametrize(
    "jwks_uri",
    [
        # Not https.
        "http://widgets.example.com/jwks.json",
        # Another host.
        "https://keys.example.net/jwks.json",
        # Another port.
        "https://widgets.example.com:8443/jwks.json",
        # A query.
        "https://widgets.example.com/jwks.json?v=1",
    ],
)
async def test_a_key_set_address_is_https_on_the_plugins_own_origin(session, jwks_uri):
    with pytest.raises(HTTPException) as excinfo:
        await _create(session, base_url=HTTPS_BASE_URL, jwks_uri=jwks_uri)

    assert excinfo.value.detail == PluginServiceMessages.INVALID_JWKS_URI


async def test_moving_the_base_url_rechecks_the_key_set_address(session):
    row = await _create(
        session,
        base_url=HTTPS_BASE_URL,
        jwks_uri=f"{HTTPS_BASE_URL}/jwks.json",
    )

    with pytest.raises(HTTPException) as excinfo:
        await service.update_registration(
            session, row.id, base_url="https://elsewhere.example.com"
        )
    assert excinfo.value.detail == PluginServiceMessages.INVALID_JWKS_URI

    cleared = await service.update_registration(session, row.id, jwks_uri="")
    assert cleared.jwks_uri is None


async def test_keys_are_provisioned_and_cleared(session):
    key_set = {"keys": [_ed25519_jwk("acme.shopify-1")]}
    row = await _create(session, jwks=key_set)
    assert row.jwks == key_set

    rotated = {"keys": [_ed25519_jwk("acme.shopify-2")]}
    updated = await service.update_registration(session, row.id, jwks=rotated)
    assert updated.jwks == rotated

    cleared = await service.update_registration(session, row.id, jwks={})
    assert cleared.jwks is None


# --- connect -----------------------------------------------------------------


def _serving(*documents: dict):
    """A transport answering each fetch with the next document, the last one
    from then on."""
    fetched: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        fetched.append(str(request.url))
        return httpx2.Response(
            200, json=documents[min(len(fetched), len(documents)) - 1]
        )

    return fetched, httpx2.MockTransport(handler)


async def test_connect_shows_the_fingerprints_of_the_set_the_plugin_serves(session):
    key = _ed25519_jwk("acme.widgets-1")
    fetched, transport = _serving({"keys": [key]})
    row = await _create(session)

    keys = await service.published_keys(session, row.id, transport=transport)

    assert keys == [
        service.PublishedKey(kid="acme.widgets-1", fingerprint=jwk_thumbprint(key))
    ]
    assert fetched == [f"{BASE_URL}/.well-known/jwks.json"]
    # Nothing is stored until it is confirmed.
    await session.refresh(row)
    assert row.jwks is None


async def test_connect_pins_the_confirmed_set_in_place_of_a_key_set_address(
    session,
):
    base_url = "https://127.0.0.1:9443"
    key_set = {"keys": [_ed25519_jwk("acme.widgets-1")]}
    _fetched, transport = _serving(key_set)
    row = await _create(
        session, base_url=base_url, jwks_uri=f"{base_url}/.well-known/jwks.json"
    )
    (shown,) = await service.published_keys(session, row.id, transport=transport)

    connected = await service.connect_registration(
        session, row.id, keys=[shown], transport=transport
    )

    assert connected.jwks == key_set
    # Verified against the pinned set alone, with nothing fetched for a kid
    # it does not hold.
    assert connected.jwks_uri is None


def _renamed(key_set: dict, kid: str) -> dict:
    return {"keys": [{**key_set["keys"][0], "kid": kid}]}


@pytest.mark.parametrize(
    "now_served",
    [
        # Another key under the same kid.
        lambda shown: {"keys": [_ed25519_jwk("acme.widgets-1")]},
        # The same key under another kid.
        lambda shown: _renamed(shown, "acme.widgets-2"),
    ],
)
async def test_connect_refuses_a_set_that_changed_since_it_was_shown(
    session, now_served
):
    shown = {"keys": [_ed25519_jwk("acme.widgets-1")]}
    _fetched, transport = _serving(shown, now_served(shown))
    row = await _create(session, jwks={"keys": [_ed25519_jwk("acme.widgets-0")]})
    confirmed = await service.published_keys(session, row.id, transport=transport)

    with pytest.raises(HTTPException) as excinfo:
        await service.connect_registration(
            session, row.id, keys=confirmed, transport=transport
        )

    assert excinfo.value.status_code == 409
    assert excinfo.value.detail == PluginServiceMessages.KEYS_CHANGED
    await session.refresh(row)
    assert row.jwks["keys"][0]["kid"] == "acme.widgets-0"


async def test_connect_refuses_when_the_base_url_moved_during_the_read(
    session, monkeypatch
):
    key_set = {"keys": [_ed25519_jwk("acme.widgets-1")]}
    row = await _create(session)
    registration_id = row.id
    (shown,) = await service.published_keys(
        session, registration_id, transport=_serving(key_set)[1]
    )

    async def read_while_the_operator_repoints_it(url, *, transport=None):
        await service.update_registration(
            session, registration_id, base_url="http://127.0.0.2:9100"
        )
        return key_set

    monkeypatch.setattr(service, "read_key_set", read_while_the_operator_repoints_it)

    with pytest.raises(HTTPException) as excinfo:
        await service.connect_registration(session, registration_id, keys=[shown])

    assert excinfo.value.detail == PluginServiceMessages.KEYS_CHANGED
    stored = await service.get_registration(session, registration_id)
    assert (stored.base_url, stored.jwks) == ("http://127.0.0.2:9100", None)


@pytest.mark.parametrize(
    ("answer", "status", "code"),
    [
        (httpx2.Response(404), 502, PluginServiceMessages.KEYS_UNREADABLE),
        (
            httpx2.Response(200, content=b"<html>"),
            502,
            PluginServiceMessages.KEYS_UNREADABLE,
        ),
        (
            httpx2.Response(200, json={"keys": []}),
            400,
            PluginServiceMessages.INVALID_JWKS,
        ),
    ],
)
async def test_connect_refuses_what_is_not_a_key_set(session, answer, status, code):
    row = await _create(session)

    with pytest.raises(HTTPException) as excinfo:
        await service.published_keys(
            session, row.id, transport=httpx2.MockTransport(lambda request: answer)
        )

    assert (excinfo.value.status_code, excinfo.value.detail) == (status, code)


async def test_connect_needs_a_base_url(session):
    row = await create_plugin_service_registration(
        session, public_id="acme.waiting", base_url=None
    )

    with pytest.raises(HTTPException) as excinfo:
        await service.published_keys(session, row.id)

    assert excinfo.value.detail == PluginServiceMessages.CONNECT_NEEDS_BASE_URL


# --- addresses ---------------------------------------------------------------


async def test_the_browser_address_names_the_allowed_origins(session):
    row = await _create(session, page_origin=PAGE_ORIGIN)

    assert row.page_origin == PAGE_ORIGIN
    # Browser origins, so they come from the browser address.
    assert row.allowed_origins == [PAGE_ORIGIN]


async def test_moving_the_browser_address_moves_a_default_origin_list(session):
    row = await _create(session)
    assert row.allowed_origins == [BASE_URL]

    updated = await service.update_registration(
        session, row.id, page_origin=PAGE_ORIGIN
    )

    # The list was still the plug-in's own origin, so it follows the plug-in.
    assert updated.allowed_origins == [PAGE_ORIGIN]


async def test_an_operators_own_origin_list_survives_a_move(session):
    row = await _create(session, allowed_origins=["https://chosen.example.com"])

    updated = await service.update_registration(
        session, row.id, page_origin=PAGE_ORIGIN
    )

    assert updated.allowed_origins == ["https://chosen.example.com"]


async def test_clearing_the_browser_address_puts_both_surfaces_back(session):
    row = await _create(session, page_origin=PAGE_ORIGIN)

    updated = await service.update_registration(session, row.id, page_origin="")

    assert updated.page_origin is None
    assert updated.allowed_origins == [BASE_URL]


# --- plug-in facts, from a listing ------------------------------------------------


def _plugin_listing(registration, *, uid=LISTING_UID, public_id="acme.widgets") -> dict:
    return {
        "uid": uid,
        "public_id": public_id,
        "kind": "plugin",
        "name": "Widgets",
        "publisher": "Acme",
        "description": "Widgets for tests.",
        "version": "1.0.0",
        "definition": service_plugin_definition(public_id),
        "registration": registration,
    }


CONTAINER = {"kind": "container", "scope_ceiling": ["projects:write", "comments:read"]}
IMAGE = "ghcr.io/acme/widgets@sha256:" + "0" * 64
COMPOSE = {
    "service": "widgets:\n  image: ${IMAGE}\n  environment:\n"
    "    INITIATIVE_URL: ${INITIATIVE_URL}\n    PRICE: $$5\n",
    "base_url": "http://widgets:8080",
}


async def _registration(session, public_id="acme.widgets") -> PluginServiceRegistration:
    session.expire_all()
    return (
        await session.exec(
            select(PluginServiceRegistration).where(
                PluginServiceRegistration.public_id == public_id
            )
        )
    ).one()


@pytest.mark.parametrize("source", ["builtin", "operator", "local"])
async def test_a_listing_from_any_source_writes_the_plugin_facts(session, source):
    image = "ghcr.io/acme/widgets@sha256:" + "0" * 64
    await upsert_listing(
        session, _plugin_listing({**CONTAINER, "image": image}), source=source
    )
    await session.commit()

    row = await _registration(session)
    assert row.listing_uid == LISTING_UID
    assert row.scope_ceiling == ["comments:read", "projects:write"]
    assert row.image_digest == image
    assert row.source == "operator"
    # Where it runs and its keys are the deployment's to give.
    assert (row.base_url, row.jwks) == (None, None)
    assert (await load_registrations(force=True))["acme.widgets"].live is False


async def test_a_listing_carries_the_compose_service_its_publisher_wrote(session):
    await upsert_listing(
        session,
        _plugin_listing({**CONTAINER, "image": IMAGE, "compose": COMPOSE}),
        source="local",
    )
    await session.commit()

    row = await _registration(session)
    assert row.compose == COMPOSE
    assert service.filled_compose(row) == (
        f"widgets:\n  image: {IMAGE}\n  environment:\n"
        f"    INITIATIVE_URL: {settings.APP_URL.rstrip('/')}\n    PRICE: $$5\n"
    )


async def test_a_listing_fills_in_the_registration_set_up_before_it(session):
    set_up = await _create(session, jwks=sample_plugin_jwks(), mandatory=True)

    await upsert_listing(session, _plugin_listing(CONTAINER), source="local")
    await session.commit()

    row = await _registration(session)
    assert row.id == set_up.id
    assert (row.listing_uid, row.base_url, row.mandatory) == (
        LISTING_UID,
        BASE_URL,
        True,
    )
    assert row.scope_ceiling == ["comments:read", "projects:write"]


async def test_a_listing_republished_without_a_scope_takes_it_away(session):
    await upsert_listing(session, _plugin_listing(CONTAINER), source="operator")
    await upsert_listing(
        session,
        {
            **_plugin_listing({**CONTAINER, "scope_ceiling": ["comments:read"]}),
            "version": "1.1.0",
        },
        source="operator",
    )
    await session.commit()

    assert (await _registration(session)).scope_ceiling == ["comments:read"]


@pytest.mark.parametrize(
    "block",
    [
        {**CONTAINER, "kind": "hosted"},
        {**CONTAINER, "base_url": BASE_URL},
        {**CONTAINER, "jwks": {"keys": []}},
        {**CONTAINER, "image": "ghcr.io/acme/widgets:latest"},
        *(
            {**CONTAINER, "image": IMAGE, "compose": {**COMPOSE, **change}}
            for change in (
                {"service": "widgets:\n  image: ${IMAGES}\n"},
                {"service": "widgets:\n  image: ${IMAGE\n"},
                {"service": "x" * 4097},
                {"base_url": "ftp://widgets"},
                {"base_url": "http://widgets:8080/a b"},
                {"base_url": f"http://{'w' * 506}"},
                {"base_url": "http://["},
                {"ports": []},
            )
        ),
        {**CONTAINER, "compose": COMPOSE},
    ],
    ids=[
        "hosted",
        "location",
        "keys",
        "unpinned-image",
        "unknown-placeholder",
        "unclosed-placeholder",
        "long-service",
        "not-http",
        "space",
        "long-url",
        "malformed-authority",
        "unknown-term",
        "image-placeholder-without-image",
    ],
)
async def test_a_listing_block_with_a_fact_it_cannot_state_is_refused(session, block):
    with pytest.raises(CatalogError):
        await upsert_listing(session, _plugin_listing(block), source="local")


async def test_a_registration_another_listing_holds_is_refused(session):
    await create_plugin_service_registration(
        session, public_id="acme.widgets", listing_uid="ABCDEFGHJKMNPQ"
    )

    with pytest.raises(CatalogSourceConflict):
        await upsert_listing(session, _plugin_listing(CONTAINER), source="local")


DECLARATIVE = {"kind": "declarative", "scope_ceiling": []}


def _declarative_listing(registration) -> dict:
    return {
        **_plugin_listing(registration),
        "definition": declarative_plugin("acme.widgets"),
    }


async def test_a_declarative_plugin_is_live_with_its_vendor_values_and_no_location(
    session,
):
    """It runs nowhere and signs nothing: its registration is live once it is
    on and its vendor values are set, and takes no address or keys."""
    await upsert_listing(session, _declarative_listing(DECLARATIVE), source="local")
    await session.commit()

    row = await _registration(session)
    assert (row.kind, row.base_url, row.jwks) == ("declarative", None, None)
    assert (await load_registrations(force=True))["acme.widgets"].live is False

    await service.update_registration(
        session, row.id, vendor_values={"client_id": "abc"}
    )
    snapshot = (await load_registrations(force=True))["acme.widgets"]
    assert (snapshot.live, snapshot.declarative) == (True, True)

    with pytest.raises(HTTPException) as refused:
        await service.update_registration(session, row.id, base_url=BASE_URL)
    assert refused.value.detail == PluginServiceMessages.DECLARATIVE_NOT_PLACED


async def test_a_container_republished_as_declarative_leaves_its_location(session):
    """What only a container has goes in the same write as the kind."""
    await _create(session, jwks=sample_plugin_jwks())
    await upsert_listing(session, _plugin_listing(CONTAINER), source="local")
    await upsert_listing(
        session,
        {**_declarative_listing(DECLARATIVE), "version": "2.0.0"},
        source="local",
    )
    await session.commit()

    row = await _registration(session)
    assert row.kind == "declarative"
    assert (row.base_url, row.page_origin, row.jwks, row.jwks_uri) == (None,) * 4
    assert row.allowed_origins == []


@pytest.mark.parametrize(
    "listing",
    [
        _declarative_listing(CONTAINER),
        _plugin_listing(DECLARATIVE),
        _declarative_listing({**DECLARATIVE, "image": IMAGE}),
    ],
    ids=[
        "declarative-plugin-container-block",
        "container-plugin-declarative-block",
        "image",
    ],
)
async def test_a_registration_block_says_the_plugins_own_kind(session, listing):
    with pytest.raises(CatalogError):
        await upsert_listing(session, listing, source="local")


# --- boot reconciliation -----------------------------------------------------


def _write_config(tmp_path, entries) -> str:
    path = tmp_path / "plugin-services.json"
    path.write_text(json.dumps(entries), encoding="utf-8")
    return str(path)


async def _listed(session, public_id: str) -> PluginServiceRegistration:
    """A registration as its listing leaves it: plug-in facts, no placement."""
    return await create_plugin_service_registration(
        session,
        public_id=public_id,
        listing_uid=LISTING_UID,
        base_url=None,
        allowed_origins=[],
        jwks={},
    )


async def test_reconcile_writes_the_deployment_facts_from_the_mounted_file(
    session, tmp_path, monkeypatch
):
    await _listed(session, "acme.declared")
    monkeypatch.setattr(
        settings,
        "PLUGIN_SERVICES_CONFIG",
        _write_config(
            tmp_path,
            [
                {
                    "public_id": "acme.declared",
                    "base_url": BASE_URL,
                    "allowed_origins": ["https://app.example.com"],
                    "mandatory": True,
                    "operations_only": True,
                }
            ],
        ),
    )

    result = await service.reconcile_from_config(session)

    assert (result.updated, result.skipped) == (1, 0)
    row = await _registration(session, "acme.declared")
    assert row.base_url == BASE_URL
    assert row.allowed_origins == ["https://app.example.com"]
    assert row.mandatory is True
    assert row.operations_only is True
    assert row.listing_uid == LISTING_UID


async def test_an_entry_waits_for_its_listing(session, tmp_path, monkeypatch):
    """An entry whose plug-in has no listing here yet is kept, and the listing
    apply that creates the registration applies it."""
    monkeypatch.setattr(
        settings,
        "PLUGIN_SERVICES_CONFIG",
        _write_config(
            tmp_path,
            [
                {
                    "public_id": "acme.widgets",
                    "base_url": BASE_URL,
                    "jwks": sample_plugin_jwks(),
                    "mandatory": True,
                }
            ],
        ),
    )
    result = await service.reconcile_from_config(session)
    assert (result.waiting, result.updated) == (1, 0)
    assert (await session.exec(select(PluginServiceRegistration))).all() == []

    await upsert_listing(session, _plugin_listing(CONTAINER), source="operator")
    await session.commit()

    row = await _registration(session)
    assert (row.base_url, row.jwks, row.mandatory) == (
        BASE_URL,
        sample_plugin_jwks(),
        True,
    )
    assert (await load_registrations(force=True))["acme.widgets"].live is True


@pytest.mark.parametrize("stated", LISTING_STATED_FIELDS)
async def test_an_entry_naming_what_the_listing_states_is_refused(
    session, tmp_path, monkeypatch, stated
):
    await _listed(session, "acme.widgets")
    entry = {"public_id": "acme.widgets", "base_url": BASE_URL, stated: True}
    monkeypatch.setattr(
        settings, "PLUGIN_SERVICES_CONFIG", _write_config(tmp_path, [entry])
    )

    result = await service.reconcile_from_config(session)

    assert (result.updated, result.skipped) == (0, 1)
    assert service.configured_facts("acme.widgets") is None
    assert (await _registration(session)).base_url is None


async def test_reconcile_seals_the_vendor_values_it_names(
    session, tmp_path, monkeypatch
):
    """``vendor_env`` names environment variables; their values are sealed into
    the registration on every pass, so rotating one is changing the variable
    and restarting."""
    await _listed(session, "acme.vendored")
    monkeypatch.setenv("TEST_VENDOR_SECRET", "first-secret")
    entry = {
        "public_id": "acme.vendored",
        "base_url": BASE_URL,
        "vendor_env": {"client_secret": "TEST_VENDOR_SECRET", "absent": "NOT_SET_X"},
    }
    monkeypatch.setattr(
        settings, "PLUGIN_SERVICES_CONFIG", _write_config(tmp_path, [entry])
    )
    await service.reconcile_from_config(session)
    assert await load_vendor_values("acme.vendored") == {
        "client_secret": "first-secret"
    }

    monkeypatch.setenv("TEST_VENDOR_SECRET", "rotated-secret")
    result = await service.reconcile_from_config(session)
    assert result.updated == 1
    assert await load_vendor_values("acme.vendored") == {
        "client_secret": "rotated-secret"
    }
    row = await _registration(session, "acme.vendored")
    # Sealed, never stored as the variable held it.
    assert "rotated-secret" not in str(row.vendor_values)


async def test_reconcile_reads_the_browser_address_from_the_file(
    session, tmp_path, monkeypatch
):
    """A chart states both addresses, so the two-address case is wired with no
    owner clicks — and adding one later is an update."""
    await _listed(session, "acme.two-addresses")
    entry = {"public_id": "acme.two-addresses", "base_url": BASE_URL}
    monkeypatch.setattr(
        settings, "PLUGIN_SERVICES_CONFIG", _write_config(tmp_path, [entry])
    )
    await service.reconcile_from_config(session)

    entry["page_origin"] = PAGE_ORIGIN
    monkeypatch.setattr(
        settings, "PLUGIN_SERVICES_CONFIG", _write_config(tmp_path, [entry])
    )
    result = await service.reconcile_from_config(session)

    assert (result.updated, result.unchanged) == (1, 0)
    row = await _registration(session, "acme.two-addresses")
    assert row.page_origin == PAGE_ORIGIN
    assert row.allowed_origins == [PAGE_ORIGIN]


async def test_reconcile_is_idempotent(session, tmp_path, monkeypatch):
    await _listed(session, "acme.idempotent")
    monkeypatch.setattr(
        settings,
        "PLUGIN_SERVICES_CONFIG",
        _write_config(
            tmp_path, [{"public_id": "acme.idempotent", "base_url": BASE_URL}]
        ),
    )

    first = await service.reconcile_from_config(session)
    second = await service.reconcile_from_config(session)

    assert first.updated == 1
    assert (second.updated, second.unchanged) == (0, 1)


async def test_reconcile_never_re_enables_a_disabled_registration(
    session, tmp_path, monkeypatch
):
    """Deactivating a plug-in is the operator's kill switch, so a restart must not
    quietly reverse it — the file still governs everything else."""
    row = await _listed(session, "acme.killswitch")
    entry = {"public_id": "acme.killswitch", "base_url": BASE_URL, "mandatory": False}
    monkeypatch.setattr(
        settings, "PLUGIN_SERVICES_CONFIG", _write_config(tmp_path, [entry])
    )
    await service.reconcile_from_config(session)
    await service.update_registration(session, row.id, enabled=False)

    entry["mandatory"] = True
    monkeypatch.setattr(
        settings, "PLUGIN_SERVICES_CONFIG", _write_config(tmp_path, [entry])
    )
    result = await service.reconcile_from_config(session)

    assert result.updated == 1
    stored = await _registration(session, "acme.killswitch")
    assert stored.enabled is False
    assert stored.mandatory is True


async def test_reconcile_reads_the_key_set_address(session, tmp_path, monkeypatch):
    await _listed(session, "acme.published")
    entry = {
        "public_id": "acme.published",
        "base_url": HTTPS_BASE_URL,
        "jwks_uri": f"{HTTPS_BASE_URL}/jwks.json",
    }
    monkeypatch.setattr(
        settings, "PLUGIN_SERVICES_CONFIG", _write_config(tmp_path, [entry])
    )

    assert (await service.reconcile_from_config(session)).updated == 1
    row = await _registration(session, "acme.published")
    assert row.jwks_uri == f"{HTTPS_BASE_URL}/jwks.json"


async def test_reconcile_ignores_grants_in_a_file_written_for_an_earlier_release(
    session, tmp_path, monkeypatch, caplog
):
    """A registration no longer has grants. An entry that still names them is
    applied without them and the pass says so, so the file does not stop a
    boot."""
    await _listed(session, "acme.earlier")
    monkeypatch.setattr(
        settings,
        "PLUGIN_SERVICES_CONFIG",
        _write_config(
            tmp_path,
            [
                {
                    "public_id": "acme.earlier",
                    "base_url": BASE_URL,
                    "grants": ["delegation", "plugin_directory"],
                }
            ],
        ),
    )

    with caplog.at_level("WARNING", logger="app.services.marketplace.registrations"):
        result = await service.reconcile_from_config(session)

    assert (result.updated, result.skipped) == (1, 0)
    assert any("names grants" in record.getMessage() for record in caplog.records)
    row = await _registration(session, "acme.earlier")
    assert not hasattr(row, "grants")


async def test_reconcile_is_a_no_op_without_the_setting(session, monkeypatch):
    monkeypatch.setattr(settings, "PLUGIN_SERVICES_CONFIG", None)
    assert (await service.reconcile_from_config(session)).total == 0


async def test_reconcile_survives_an_unreadable_file(session, tmp_path, monkeypatch):
    """A malformed file costs the file, never the boot."""
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(settings, "PLUGIN_SERVICES_CONFIG", str(path))

    assert (await service.reconcile_from_config(session)).total == 0


async def test_a_repeated_public_id_costs_only_that_entry(
    session, tmp_path, monkeypatch
):
    """A duplicate in the file is one operator mistake, not a failed boot: the
    later entry is skipped, and the first one applies."""
    await _listed(session, "acme.twice")
    await _listed(session, "acme.innocent")
    monkeypatch.setattr(
        settings,
        "PLUGIN_SERVICES_CONFIG",
        _write_config(
            tmp_path,
            [
                {"public_id": "acme.twice", "base_url": BASE_URL},
                {"public_id": "acme.twice", "base_url": "https://other.example.com"},
                {"public_id": "acme.innocent", "base_url": BASE_URL},
            ],
        ),
    )

    result = await service.reconcile_from_config(session)

    assert (result.updated, result.skipped) == (2, 1)
    # The first entry won, so the duplicate did not quietly retarget the plug-in.
    assert (await _registration(session, "acme.twice")).base_url == BASE_URL
