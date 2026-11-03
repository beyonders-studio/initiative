"""The platform switch behind My Messages.

The switch is one column, but it has to reach three places that are easy to let
drift: the boot config the SPA reads, every direct-message route, and the one
roster built on the messaging rule that is not itself a messaging route. Each
is asserted here, along with the thing an operator is actually promised —
that turning it off keeps what people already had.
"""

import pytest
from sqlalchemy import text

from app.models.platform.contact_grant import (
    ContactGrant,
    ContactGrantKind,
    ContactGrantState,
    canonical_pair,
)
from app.models.platform.guild import CommunityRole
from app.models.platform.user import UserRole
from app.services.platform import rules
from app.testing import create_guild_membership, create_user, get_auth_headers


async def _reachable_from_their_communities(session, *user_ids: int) -> None:
    """Put these accounts on the policy that makes co-members contacts.

    The default is ``private``, on which nobody is anybody's contact -- so
    without this the roster assertion below would pass whatever the switch did.
    """
    await session.exec(
        text(
            "UPDATE public.user_dm_settings "
            "SET dm_policy = CAST('community' AS user_dm_policy) "
            "WHERE user_id = ANY(CAST(:ids AS int[]))"
        ).bindparams(ids=list(user_ids))
    )
    await session.commit()


async def _set_switch(session, *, enabled: bool) -> None:
    """Write the switch straight to the row, as an owner's PUT would."""
    await rules.put(session, "community_directory_enabled", False)
    await rules.put(session, "direct_messages_enabled", enabled)
    await session.commit()


# ------------------------------------------------------------------ config ---


async def test_config_reports_messaging_on_by_default(client) -> None:
    """A deployment that upgrades into the switch keeps its messaging."""
    body = (await client.get("/api/v1/config")).json()
    assert body["direct_messages_enabled"] is True


async def test_owner_switches_messaging_off_and_back_on(client, session) -> None:
    owner = await create_user(
        session, email="owner-dm-switch@example.com", role=UserRole.owner
    )
    headers = get_auth_headers(owner)

    off = await client.put(
        "/api/v1/settings/community",
        json={"community_directory_enabled": False, "direct_messages_enabled": False},
        headers=headers,
    )
    assert off.status_code == 200, off.text
    assert off.json()["direct_messages_enabled"] is False
    assert (await client.get("/api/v1/config")).json()[
        "direct_messages_enabled"
    ] is False

    on = await client.put(
        "/api/v1/settings/community",
        json={"community_directory_enabled": False, "direct_messages_enabled": True},
        headers=headers,
    )
    assert on.status_code == 200, on.text
    assert on.json()["direct_messages_enabled"] is True
    assert (await client.get("/api/v1/config")).json()[
        "direct_messages_enabled"
    ] is True


async def test_omitting_the_switch_leaves_it_alone(client, session) -> None:
    """The directory is written far more often, and must not carry this with it."""
    owner = await create_user(
        session, email="owner-dm-untouched@example.com", role=UserRole.owner
    )
    headers = get_auth_headers(owner)
    await client.put(
        "/api/v1/settings/community",
        json={"community_directory_enabled": False, "direct_messages_enabled": False},
        headers=headers,
    )

    directory_only = await client.put(
        "/api/v1/settings/community",
        json={"community_directory_enabled": True},
        headers=headers,
    )

    assert directory_only.status_code == 200, directory_only.text
    assert directory_only.json()["direct_messages_enabled"] is False


@pytest.mark.parametrize(
    "role",
    [UserRole.member, UserRole.support, UserRole.moderator, UserRole.operator],
)
async def test_the_switch_is_owner_only(client, session, role: UserRole) -> None:
    user = await create_user(session, role=role)

    response = await client.put(
        "/api/v1/settings/community",
        json={"community_directory_enabled": False, "direct_messages_enabled": False},
        headers=get_auth_headers(user),
    )

    assert response.status_code == 403, f"{role.value}: {response.status_code}"


# ------------------------------------------------------------------ routes ---


#: One route from each half of the surface, and one of each verb, so the gate
#: is shown to sit on the routers rather than on whichever handler was
#: remembered.
DM_ROUTES = [
    ("GET", "/api/v1/me/dm-settings", None),
    ("PATCH", "/api/v1/me/dm-settings", {"dm_policy": "private"}),
    ("GET", "/api/v1/me/connections", None),
    ("GET", "/api/v1/me/message-requests", None),
    ("GET", "/api/v1/me/ignored", None),
    ("POST", "/api/v1/me/dm-permissions", {"user_ids": [1]}),
    ("GET", "/api/v1/me/dm/conversations", None),
    ("GET", "/api/v1/me/dm/devices", None),
]


@pytest.mark.parametrize("method, path, body", DM_ROUTES)
async def test_every_dm_route_refuses_while_messaging_is_off(
    client, session, acting_user, method: str, path: str, body
) -> None:
    a = await acting_user(guild_role=CommunityRole.member)
    await _set_switch(session, enabled=False)

    response = await client.request(method, path, json=body, headers=a.headers)

    assert response.status_code == 403, f"{method} {path}: {response.text}"
    assert response.json()["detail"] == "DM_DISABLED_FOR_PLATFORM"


@pytest.mark.parametrize("method, path, body", DM_ROUTES)
async def test_every_dm_route_answers_again_once_it_is_back_on(
    client, session, acting_user, method: str, path: str, body
) -> None:
    a = await acting_user(guild_role=CommunityRole.member)
    await _set_switch(session, enabled=False)
    await _set_switch(session, enabled=True)

    response = await client.request(method, path, json=body, headers=a.headers)

    assert response.status_code != 403, f"{method} {path}: {response.text}"


async def test_an_accepted_channel_survives_the_switch(
    client, session, acting_user
) -> None:
    """The promise an operator is making: off is off, not gone.

    A channel two people agreed on is still there when messaging comes back, so
    switching twice does not quietly make everybody ask each other again.
    """
    a = await acting_user(guild_role=CommunityRole.member)
    b = await acting_user(guild_role=CommunityRole.member, guild=a.guild)
    low, high = canonical_pair(a.user.id, b.user.id)
    session.add(
        ContactGrant(
            user_id_low=low,
            user_id_high=high,
            kind=ContactGrantKind.connection,
            state=ContactGrantState.accepted,
            requested_by=a.user.id,
        )
    )
    await session.commit()

    await _set_switch(session, enabled=False)
    await _set_switch(session, enabled=True)

    response = await client.get("/api/v1/me/connections", headers=a.headers)
    assert response.status_code == 200, response.text
    assert [g["user_id"] for g in response.json()["accepted"]] == [b.user.id]


# ---------------------------------------------------------------- contacts ---


async def test_contacts_list_nobody_while_messaging_is_off(
    client, session, acting_user
) -> None:
    """A contact is somebody you could reach out to, and there is nothing to
    reach them with."""
    a = await acting_user(guild_role=CommunityRole.member)
    b = await create_user(session)
    await create_guild_membership(session, user=b, guild=a.guild)
    await _reachable_from_their_communities(session, a.user.id, b.id)

    listed = await client.get("/api/v1/me/contacts", headers=a.headers)
    assert listed.status_code == 200, listed.text
    assert any(section["items"] for section in listed.json()["sections"]), (
        "the fixture must list somebody for the assertion below to mean anything"
    )

    await _set_switch(session, enabled=False)

    response = await client.get("/api/v1/me/contacts", headers=a.headers)
    assert response.status_code == 200, response.text
    assert all(not section["items"] for section in response.json()["sections"])
