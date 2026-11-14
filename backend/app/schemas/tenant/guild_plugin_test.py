"""What a guild-plugin read payload discloses.

Two properties, pulling in opposite directions, and both are load-bearing.

**The pinned definition travels.** A reader — the settings page, and an
installed plug-in reading its own install — has to be able to say what *this*
install is, including the blocks this build assigns no meaning to. Serving the
snapshot the guild pinned rather than whatever the catalog holds today is what
makes that answer true of the install rather than of the listing.

**Stored values never do.** The definition describes the form; what was typed
into it lives in columns this payload does not read. Serializing one alongside
the other would put a stored credential in the payload, so the test reads the
whole payload rather than checking the field somebody remembered.
"""

from datetime import UTC, datetime
from types import SimpleNamespace

from app.db.guild_standing import GuildContext
from app.models.platform.guild import Guild
from app.schemas.tenant.guild_plugin import serialize_guild_plugin
from app.services.tenant.plugin_age import AgeViewer

#: An adult whose country is known, so no age limit is what is under test.
ADULT = AgeViewer(age=30, country="US")


SECRET_DIGEST = "5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8"

DEFINITION = {
    "plugin_kind": "service",
    "service": {"public_id": "tests.shop", "protocol": 1},
    "features": ["events", "automations"],
    "connections": [
        {
            "id": "admin",
            "scope": "static",
            "fields": [{"key": "admin_token", "type": "secret", "required": True}],
        }
    ],
    "events": ["plugin.tests.shop.order_created"],
    # Opaque to this build by design: it belongs to the automation service,
    # which parses it off this same payload.
    "automation": {"nodes": [{"id": "low_stock"}]},
}


#: The standing a request in this plug-in's community carries, which is what the
#: serializer names the community from. Built here because these payloads are
#: built without a request.
CONTEXT = GuildContext(
    guild=Guild(id=7, name="g"),
    user_id=11,
    guild_id=7,
    standing_guild_id=7,
)


def _plugin(**overrides) -> SimpleNamespace:
    now = datetime.now(UTC)
    return SimpleNamespace(
        **{
            "id": 3,
            "guild_id": 7,
            "listing_uid": "TESTAPP0000001",
            "listing_version": "1.2.0",
            "plugin_kind": "service",
            "name": "Shop",
            "enabled": True,
            # Tracking its listing, which is what an install that never opted
            # out says and what the serializer reads.
            "auto_update": True,
            "pending_version": None,
            "definition": DEFINITION,
            "config": {},
            "secret_fields": {"admin": {"admin_token": SECRET_DIGEST}},
            "config_state": "ok",
            "config_state_detail": None,
            "granted_scopes": [],
            "settings": {},
            "created_by": 11,
            "created_at": now,
            "updated_at": now,
            **overrides,
        }
    )


def test_the_pinned_definition_is_passed_through_verbatim():
    payload = serialize_guild_plugin(_plugin(), context=CONTEXT, viewer=ADULT)

    assert payload.definition == DEFINITION
    # Including the block this build never interprets — a plug-in reads it here
    # rather than through an endpoint that would have to understand it.
    assert payload.definition["automation"] == {"nodes": [{"id": "low_stock"}]}


def test_the_config_state_the_plugin_reported_is_carried():
    """Until a plug-in reports, an install has no verdict; once it does, the
    settings page can say whether the plug-in is happy without leaving the app."""
    assert (
        serialize_guild_plugin(_plugin(), context=CONTEXT, viewer=ADULT).config_state
        == "ok"
    )
    assert (
        serialize_guild_plugin(
            _plugin(config_state="invalid", config_state_detail="missing_read_orders"),
            context=CONTEXT,
            viewer=ADULT,
        ).config_state_detail
        == "missing_read_orders"
    )
    assert serialize_guild_plugin(
        _plugin(config_state="unverified"), context=CONTEXT, viewer=ADULT
    ).config_state == ("unverified")


def test_no_stored_value_appears_anywhere_in_the_payload():
    payload = serialize_guild_plugin(
        _plugin(config={"admin": {"shop_domain": "example.test"}}),
        context=CONTEXT,
        viewer=ADULT,
    )

    serialized = payload.model_dump_json()
    assert SECRET_DIGEST not in serialized
    assert "secret_fields" not in serialized
    # The definition describes the field; it carries no value for it.
    assert payload.definition["connections"][0]["fields"][0]["key"] == "admin_token"
    assert "value" not in payload.definition["connections"][0]["fields"][0]


def test_needs_config_still_reads_from_presence():
    """A required guild-wide field with nothing in it is the one thing this
    build can know by itself, and it is unaffected by the passthrough."""
    assert (
        serialize_guild_plugin(
            _plugin(secret_fields={}), context=CONTEXT, viewer=ADULT
        ).needs_config
        is True
    )
    assert (
        serialize_guild_plugin(_plugin(), context=CONTEXT, viewer=ADULT).needs_config
        is False
    )


def test_placements_and_permissions_are_read_off_the_rows_and_definition():
    """The serializer reads no placement off the install: the caller loads the
    rows, once for a whole list. The permissions are the definition's, ``use``
    at each level among them."""
    rows = [SimpleNamespace(initiative_id=9), SimpleNamespace(initiative_id=2)]
    payload = serialize_guild_plugin(
        _plugin(), context=CONTEXT, placements=rows, viewer=ADULT
    )

    assert payload.placed_initiative_ids == [2, 9]
    assert [p.model_dump() for p in payload.permissions] == [
        {"id": "use", "level": "initiative", "name": None, "members": False},
        {"id": "use", "level": "community", "name": None, "members": False},
    ]
    assert (
        serialize_guild_plugin(
            _plugin(), context=CONTEXT, viewer=ADULT
        ).placed_initiative_ids
        == []
    )


def test_granted_scopes_are_reported_sorted_and_empty_by_default():
    """What the seat consented to reads back as a set in one order, and an
    install nobody has granted anything holds nothing."""
    assert (
        serialize_guild_plugin(_plugin(), context=CONTEXT, viewer=ADULT).granted_scopes
        == []
    )
    payload = serialize_guild_plugin(
        _plugin(granted_scopes=["projects:write", "comments:read"]),
        context=CONTEXT,
        viewer=ADULT,
    )
    assert payload.granted_scopes == ["comments:read", "projects:write"]


def test_surface_access_is_computed_for_the_viewer():
    """Each declared surface, with where this viewer opens it: inside an
    initiative where their role there holds the permission it names, at the
    community level where they hold it as an admin surface is held."""
    definition = {
        **DEFINITION,
        "permissions": [{"id": "settings", "level": "initiative", "name": {}}],
        "pages": [
            {"id": "board", "path": "/b", "scopes": ["community", "initiative"]},
            {
                "id": "settings",
                "path": "/s",
                "scopes": ["initiative"],
                "permission": "settings",
            },
        ],
    }
    rows = [SimpleNamespace(initiative_id=2), SimpleNamespace(initiative_id=5)]
    member = GuildContext(
        guild=Guild(id=7, name="g"),
        user_id=12,
        guild_id=7,
        standing_guild_id=7,
        member_initiatives=(2, 5),
        plugin_grants=("2:3:use",),
    )
    admin = GuildContext(
        guild=Guild(id=7, name="g"),
        user_id=11,
        guild_id=7,
        standing_guild_id=7,
        guild_admin=True,
        held_plugin_permissions=("*",),
    )

    def access(context):
        payload = serialize_guild_plugin(
            _plugin(definition=definition),
            context=context,
            placements=rows,
            viewer=ADULT,
        )
        return {one.surface_id: one.model_dump() for one in payload.surface_access}

    assert access(member) == {
        "board": {
            "surface_id": "board",
            "openable_community_wide": False,
            "openable_initiatives": [2],
        },
        "settings": {
            "surface_id": "settings",
            "openable_community_wide": False,
            "openable_initiatives": [],
        },
    }
    assert access(admin) == {
        "board": {
            "surface_id": "board",
            "openable_community_wide": True,
            "openable_initiatives": [2, 5],
        },
        "settings": {
            "surface_id": "settings",
            "openable_community_wide": False,
            "openable_initiatives": [2, 5],
        },
    }


def test_item_access_is_where_the_viewer_meets_the_plugin_on_items():
    """Per initiative it is placed in, the fields, parts and actions whose
    permission the viewer holds there, an action's endpoint's too where it
    names one; of those, the fields and parts whose connections hold a value,
    and every action but one whose community connections hold nothing, and
    none while the community is frozen. A member's own connection an action
    requires is theirs to make when they run it, as is one a declarative
    plug-in's endpoint requires; a container's endpoint is called as the
    installation, which no member's connection answers. A declarative
    plug-in's fields, parts and actions are offered as a container's are."""
    definition = {
        **DEFINITION,
        "connections": [
            *DEFINITION["connections"],
            {"id": "account", "scope": "interactive", "fields": []},
        ],
        "permissions": [{"id": "manage", "level": "initiative", "name": {}}],
        "endpoints": [
            {"id": "link", "direction": "write"},
            {"id": "purge", "direction": "write", "permission": "manage"},
            {"id": "sync", "direction": "write", "requires": {"all_of": ["admin"]}},
            {
                "id": "assign",
                "direction": "write",
                "requires": {"all_of": ["admin", "account"]},
            },
        ],
        "fields": [
            {"key": "ci.state", "on": ["task"]},
            {"key": "ci.owner", "on": ["task"], "requires": {"any_of": ["admin"]}},
        ],
        "parts": [{"id": "builds", "on": ["task"], "requires": {"all_of": ["admin"]}}],
        "actions": [
            {"id": "new-link", "endpoint": "link", "on": ["task"]},
            {"id": "purge", "endpoint": "purge", "on": ["task"]},
            {"id": "sync", "endpoint": "sync", "on": ["task"]},
            {
                "id": "audit",
                "endpoint": "link",
                "on": ["task"],
                "requires": {"all_of": ["admin", "account"]},
            },
            {"id": "close", "endpoint": "link", "on": ["task"], "permission": "manage"},
            {"id": "assign", "endpoint": "assign", "on": ["task"]},
        ],
        "minimum_age": {"default": 18},
    }
    rows = [SimpleNamespace(initiative_id=2), SimpleNamespace(initiative_id=5)]

    def context(**standing):
        return GuildContext(
            guild=Guild(id=7, name="g"),
            user_id=12,
            guild_id=7,
            standing_guild_id=7,
            **standing,
        )

    def access(standing, viewer=ADULT, **plugin):
        payload = serialize_guild_plugin(
            _plugin(definition=definition, **plugin),
            context=standing,
            placements=rows,
            viewer=viewer,
        )
        return [
            (one.initiative_id, one.fields, one.parts, one.actions)
            for one in payload.item_access
        ]

    every_field = ["ci.state", "ci.owner"]
    member = context(member_initiatives=(2, 5), plugin_grants=("2:3:use",))
    admin = context(guild_admin=True)
    assert access(member) == [
        (2, every_field, ["builds"], ["new-link", "sync", "audit"])
    ]
    everything = ["new-link", "purge", "sync", "audit", "close"]
    assert access(admin) == [
        (2, every_field, ["builds"], everything),
        (5, every_field, ["builds"], everything),
    ]
    # The connection holds nothing.
    assert access(admin, secret_fields={}) == [
        (2, ["ci.state"], [], ["new-link", "purge", "close"]),
        (5, ["ci.state"], [], ["new-link", "purge", "close"]),
    ]
    assert access(context(guild_admin=True, content_read_only=True)) == [
        (2, every_field, ["builds"], []),
        (5, every_field, ["builds"], []),
    ]
    assert access(context(member_initiatives=(2, 5))) == []
    assert access(admin, AgeViewer(age=15, country="US")) == []
    del definition["service"]
    assert access(admin)[0] == (2, every_field, ["builds"], [*everything, "assign"])
    assert access(admin, secret_fields={})[0] == (
        2,
        ["ci.state"],
        [],
        ["new-link", "purge", "close"],
    )
