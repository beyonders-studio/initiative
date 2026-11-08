"""Guild auth policy: admin endpoints, the step-up gate, and the DB-layer
session-satisfaction enforcement inside the guild RLS."""

import json
from dataclasses import dataclass
from collections.abc import Awaitable, Callable

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import (
    GuildAccessError,
    _enforce_guild_auth_policy,
    establish_guild_access,
)
from app.core import auth_context
from app.db.schema_provisioning import GuildRoleKind, guild_role_name
from app.db.session import set_rls_context
from app.models.platform.guild import Guild, CommunityRole
from app.core.login_methods import LoginMethod
from app.core.rules import SetBy, SignInRequirement
from app.models.platform.rule import CommunityRule
from app.models.platform.user import User, UserRole
from app.models.tenant.project import Project
from app.services.auth.assurance import SECOND_FACTOR_AMR
from app.services.platform import api_keys as api_keys_service
from app.services.platform.ws_auth import authenticate_ws_token
from app.testing.actor import Actor
from app.testing.factories import (
    satisfied_claims_for,
    create_access_grant,
    create_auth_provider,
    create_file,
    create_guest,
    create_guild,
    create_guild_auth_policy,
    create_guild_membership,
    create_guild_provider_connection,
    create_initiative,
    create_user,
    get_auth_token,
    guild_administration,
)
from app.testing import route_as
from app.db.request_context import SystemGuild
from app.services.platform import app_settings as app_settings_service
from app.services.platform import rules


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _sat_headers(user: User, provider_ids: list[int]) -> dict[str, str]:
    """A session that came in through those providers, carrying what they
    asserted: a community's connection is narrowed, so arriving through a
    provider is not on its own what makes the arrival one of its own."""
    return _bearer(
        get_auth_token(
            user,
            satisfied_providers=provider_ids,
            asserted_claims=satisfied_claims_for(*provider_ids),
        )
    )


def _settings(guild_id: int) -> str:
    """The surface the seat holds: one community's sign-in rules."""
    return f"/api/v1/communities/{guild_id}/auth-settings"


async def _both_open(session: AsyncSession, guild_id: int) -> bool:
    """Whether the community asks nothing of its members or its guests."""
    stored = (await rules.community_values(session, [guild_id], applied=False))[
        guild_id
    ]
    return stored["auth_policy"] == stored["guest_auth_policy"] == SignInRequirement()


async def _members_rule(session: AsyncSession, guild_id: int) -> SignInRequirement:
    return await rules.community_value(session, guild_id, "auth_policy", applied=False)


# --- Setting, reading and lifting a requirement ------------------------------


async def test_the_seat_sets_reads_and_clears_the_policy(
    client: AsyncClient, session: AsyncSession, acting_user
):
    seat = await acting_user(guild_role=CommunityRole.superadmin)
    provider = await create_auth_provider(session, slug="corp")
    await create_guild_provider_connection(session, guild=seat.guild, provider=provider)
    headers = _sat_headers(seat.user, [provider.id])
    guild_id = seat.guild.id

    put = await client.patch(
        _settings(guild_id),
        headers=headers,
        json={"auth_policy": {"policy": "required", "provider_id": provider.id}},
    )
    assert put.status_code == 200, put.text
    assert put.json()["auth_policy"] == {
        "policy": "required",
        "provider_id": provider.id,
        "provider_slug": "corp",
        "provider_display_name": "Corp SSO",
        "require_methods": [],
        # The deployment asks nothing of its own, so the community's box for a
        # second factor is still the community's to tick.
        "factor_required_by_platform": False,
    }

    got = await client.get(_settings(guild_id), headers=headers)
    assert got.json()["auth_policy"]["policy"] == "required"

    cleared = await client.patch(
        _settings(guild_id), headers=headers, json={"auth_policy": {"policy": "open"}}
    )
    assert cleared.json()["auth_policy"]["policy"] == "open"
    session.expire_all()
    assert await _both_open(session, guild_id)


async def test_a_guest_is_asked_the_guests_rule_and_a_member_the_members(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Two halves, each asked of its own people. The seat writes the guests'
    half without meeting it, since it is not asked it."""
    await app_settings_service.ensure_settings_row(session)
    await rules.put(session, "guests_enabled", True)
    await session.commit()
    seat = await acting_user(guild_role=CommunityRole.superadmin)
    provider = await create_auth_provider(session, slug="corp")
    await create_guild_provider_connection(session, guild=seat.guild, provider=provider)
    guest = await create_guest(session, seat.guild)
    guild_id, provider_id = seat.guild.id, provider.id
    guest_headers = _bearer(get_auth_token(guest))
    through_corp = _sat_headers(seat.user, [provider_id])

    asked = await client.patch(
        _settings(guild_id),
        headers=seat.headers,
        json={"guest_auth_policy": {"policy": "required", "provider_id": provider_id}},
    )
    assert asked.status_code == 200, asked.text
    assert asked.json()["auth_policy"]["policy"] == "open"
    assert asked.json()["guest_auth_policy"]["provider_slug"] == "corp"

    refused = await client.get(seat.g("/initiatives/"), headers=guest_headers)
    assert refused.status_code == 401
    assert refused.headers["X-Auth-Step-Up"] == "corp"
    member_in = await client.get(seat.g("/initiatives/"), headers=seat.headers)
    assert member_in.status_code == 200

    # The other way round: members come through corp, guests come as they are.
    swapped = await client.patch(
        _settings(guild_id),
        headers=through_corp,
        json={
            "auth_policy": {"policy": "required", "provider_id": provider_id},
            "guest_auth_policy": {"policy": "open"},
        },
    )
    assert swapped.status_code == 200, swapped.text
    guest_in = await client.get(seat.g("/initiatives/"), headers=guest_headers)
    assert guest_in.status_code == 200
    member_refused = await client.get(seat.g("/initiatives/"), headers=seat.headers)
    assert member_refused.status_code == 401

    # Both open is no row at all.
    await client.patch(
        _settings(guild_id),
        headers=through_corp,
        json={"auth_policy": {"policy": "open"}},
    )
    session.expire_all()
    assert await _both_open(session, guild_id)


@pytest.mark.parametrize("connected", [True, False])
async def test_a_guests_sso_rule_needs_a_connection_to_answer_it(
    client: AsyncClient, session: AsyncSession, acting_user, connected: bool
):
    """Nobody meets a guests' rule before it is written, so asking guests for
    the community's own single sign-on needs a connection that can answer."""
    seat = await acting_user(guild_role=CommunityRole.superadmin)
    if connected:
        provider = await create_auth_provider(session, slug="corp")
        await create_guild_provider_connection(
            session, guild=seat.guild, provider=provider
        )

    response = await client.patch(
        _settings(seat.guild.id),
        headers=seat.headers,
        json={"guest_auth_policy": {"policy": "required", "require_methods": ["sso"]}},
    )

    if connected:
        assert response.status_code == 200, response.text
    else:
        assert response.status_code == 409, response.text
        assert response.json()["detail"] == "AUTH_RULE_NOT_OFFERED"


async def test_non_admin_cannot_manage_policy(
    client: AsyncClient, session: AsyncSession, acting_user
):
    member = await acting_user(guild_role=CommunityRole.member)
    provider = await create_auth_provider(session, slug="corp")

    response = await client.patch(
        _settings(member.guild.id),
        headers=_sat_headers(member.user, [provider.id]),
        json={"auth_policy": {"policy": "required", "provider_id": provider.id}},
    )
    assert response.status_code == 403


async def _one_the_deployment_switched_off(
    session: AsyncSession, guild: Guild
) -> int | None:
    """Connected, and no longer login-ready."""
    provider = await create_auth_provider(session, slug="off", enabled=False)
    await create_guild_provider_connection(session, guild=guild, provider=provider)
    return provider.id


async def _one_nobody_connects_to(session: AsyncSession, guild: Guild) -> int | None:
    return (await create_auth_provider(session, slug="corp")).id


async def _another_communitys(session: AsyncSession, guild: Guild) -> int | None:
    provider = await create_auth_provider(session, slug="other-corp")
    await create_guild_provider_connection(
        session, guild=await create_guild(session), provider=provider
    )
    return provider.id


async def _no_provider_and_no_method(session: AsyncSession, guild: Guild) -> None:
    return None


@pytest.mark.parametrize(
    "name_a_provider",
    [
        pytest.param(_one_the_deployment_switched_off, id="switched off"),
        pytest.param(_one_nobody_connects_to, id="nobody connects to it"),
        pytest.param(_another_communitys, id="another community's"),
        pytest.param(_no_provider_and_no_method, id="none, and no method either"),
    ],
)
async def test_a_requirement_names_a_working_provider_of_this_communitys(
    client: AsyncClient, session: AsyncSession, acting_user, name_a_provider
):
    """A connection is what makes a provider this community's, and the
    provider has to be one the deployment still offers. A requirement naming
    anything else is refused, and so is one that names nothing at all —
    ``required`` has to require something."""
    seat = await acting_user(guild_role=CommunityRole.superadmin)
    provider_id = await name_a_provider(session, seat.guild)
    body: dict[str, object] = {"policy": "required"}
    if provider_id is not None:
        body["provider_id"] = provider_id

    response = await client.patch(
        _settings(seat.guild.id),
        headers=_sat_headers(seat.user, [provider_id] if provider_id else []),
        json={"auth_policy": body},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "COMMUNITY_AUTH_POLICY_INVALID_PROVIDER"


async def test_policy_requires_admin_own_session_to_satisfy(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """An admin can only require a provider their own session has satisfied —
    proving it works and keeping them from locking out their guild."""
    seat = await acting_user(guild_role=CommunityRole.superadmin)
    provider = await create_auth_provider(session, slug="corp")
    await create_guild_provider_connection(session, guild=seat.guild, provider=provider)

    response = await client.patch(
        _settings(seat.guild.id),
        headers=seat.headers,  # legacy token: sat is empty
        json={"auth_policy": {"policy": "required", "provider_id": provider.id}},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "AUTH_RULE_SELF_UNSATISFIED"
    # One code for four different asks, so the header is what tells the page
    # which line of the form the refusal is about.
    assert response.headers["X-Auth-Policy-Unmet"] == "provider"


async def test_without_the_entitlement_a_requirement_is_read_and_lifted_only(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """With the operator toggle off the config surface closes, and the three
    verbs part company: reading a standing requirement works, tightening it
    404s with the same COMMUNITY_AUTH_NOT_ENABLED shape as platform posture and
    writes nothing, and lifting the standing one is still reachable.

    Enforcement reads the policy row alone, so a requirement outlives the
    entitlement that allowed it to be set; the way to lift one outlives it too.
    Lifting only ever admits more, so it carries none of the gating the setting
    path does."""
    guild = await create_guild(session, auth_options=[])
    seat = await acting_user(guild_role=CommunityRole.superadmin, guild=guild)
    provider = await create_auth_provider(session, slug="corp")
    await create_guild_auth_policy(session, guild, provider)
    headers = _sat_headers(seat.user, [provider.id])
    guild_id, provider_id = guild.id, provider.id

    got = await client.get(_settings(guild_id), headers=headers)
    assert got.status_code == 200
    assert got.json()["auth_policy"]["policy"] == "required"
    assert got.json()["auth_policy"]["provider_slug"] == "corp"

    put = await client.patch(
        _settings(guild_id),
        headers=headers,
        json={
            "auth_policy": {
                "policy": "required",
                "provider_id": provider_id,
                "require_methods": ["sso"],
            }
        },
    )
    assert put.status_code == 404
    assert put.json()["detail"] == "COMMUNITY_AUTH_NOT_ENABLED"
    session.expire_all()
    assert (await _members_rule(session, guild_id)).policy == "required"

    cleared = await client.patch(
        _settings(guild_id), headers=headers, json={"auth_policy": {"policy": "open"}}
    )
    assert cleared.status_code == 200
    assert cleared.json()["auth_policy"]["policy"] == "open"
    session.expire_all()
    assert await _both_open(session, guild_id)


# --- The gate: what a standing requirement does to a session -----------------


async def test_a_required_provider_steps_up_every_session_that_lacks_it(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The answer a standing requirement gives, and how long it gives it for:
    turning the operator toggle OFF closes the config surface and leaves
    enforcement where it was (parity with the posture gate — management is
    gated, enforcement is not)."""
    member = await acting_user(guild_role=CommunityRole.member)
    provider = await create_auth_provider(session, slug="corp")
    await create_guild_auth_policy(session, member.guild, provider)
    satisfied = _sat_headers(member.user, [provider.id])

    # Unsatisfied (legacy) session: 401 naming the provider to step up with.
    blocked = await client.get(member.g("/initiatives/"), headers=member.headers)
    assert blocked.status_code == 401
    assert blocked.json()["detail"] == "COMMUNITY_AUTH_STEP_UP_REQUIRED"
    assert blocked.headers["X-Auth-Step-Up"] == "corp"
    # And the same answer in the standard form (RFC 9470 §3), for a client
    # that knows OAuth and nothing about this app.
    assert (
        blocked.headers["WWW-Authenticate"]
        == 'Bearer error="insufficient_user_authentication"'
    )

    # A session that satisfied the provider passes.
    allowed = await client.get(member.g("/initiatives/"), headers=satisfied)
    assert allowed.status_code == 200

    # Operator turns per-guild sign-in off after the requirement was set: both
    # answers stay as they were.
    await guild_administration(session, member.guild, auth_options=[])

    still_blocked = await client.get(member.g("/initiatives/"), headers=member.headers)
    assert still_blocked.status_code == 401
    assert still_blocked.json()["detail"] == "COMMUNITY_AUTH_STEP_UP_REQUIRED"
    assert still_blocked.headers["X-Auth-Step-Up"] == "corp"

    still_allowed = await client.get(member.g("/initiatives/"), headers=satisfied)
    assert still_allowed.status_code == 200


async def test_the_step_up_challenge_is_not_what_an_ordinary_401_says(
    client: AsyncClient, session: AsyncSession
):
    """Both answers are 401 and both name Bearer, and a client has to tell them
    apart: one is renewed by refreshing, the other by presenting a factor. The
    ``error`` parameter is the difference, so an ordinary 401 must not carry
    it."""
    guild = await create_guild(session)

    no_credential = await client.get(f"/api/v1/c/{guild.id}/initiatives/")

    assert no_credential.status_code == 401
    assert no_credential.headers["WWW-Authenticate"] == "Bearer"
    assert "error=" not in no_credential.headers["WWW-Authenticate"]


async def test_open_guild_admits_any_session(
    client: AsyncClient, session: AsyncSession, acting_user
):
    member = await acting_user(guild_role=CommunityRole.member)

    response = await client.get(member.g("/initiatives/"), headers=member.headers)
    assert response.status_code == 200


# --- Credentials that record no sign-in --------------------------------------


async def _an_api_key(
    client: AsyncClient, session: AsyncSession, user: User
) -> dict[str, str]:
    secret, _row = await api_keys_service.create_api_key(session, user=user, name="ci")
    await session.commit()
    return _bearer(secret)


async def _require_one_named_provider(session: AsyncSession, guild: Guild) -> None:
    provider = await create_auth_provider(session, slug="corp")
    await create_guild_auth_policy(session, guild, provider)


async def _require_any_of_ours(session: AsyncSession, guild: Guild) -> None:
    provider = await create_auth_provider(session, slug="corp")
    await create_guild_provider_connection(session, guild=guild, provider=provider)
    await create_guild_auth_policy(session, guild, methods=[LoginMethod.sso])


@pytest.mark.parametrize(
    "require_a_sign_in,step_up_slug",
    [
        pytest.param(_require_one_named_provider, "corp", id="one named provider"),
        pytest.param(_require_any_of_ours, "", id="any of ours"),
    ],
)
async def test_a_credential_that_records_no_sign_in_satisfies_no_requirement(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    require_a_sign_in,
    step_up_slug: str,
):
    """An API key is derived from a sign-in that already happened and records
    nothing about it, so it carries no providers. Whichever shape the
    requirement takes — one named provider, or any of this community's — it
    gets the answer every unsatisfied session gets, and the challenge names
    what would serve it."""
    member = await acting_user(guild_role=CommunityRole.member)
    await require_a_sign_in(session, member.guild)
    headers = await _an_api_key(client, session, member.user)

    blocked = await client.get(member.g("/initiatives/"), headers=headers)
    assert blocked.status_code == 401, blocked.text
    assert blocked.json()["detail"] == "COMMUNITY_AUTH_STEP_UP_REQUIRED"
    assert blocked.headers["X-Auth-Step-Up"] == step_up_slug


# --- The seat itself: who holds it, and what holds it in place ---------------


async def _a_seat_and_a_requirement(session: AsyncSession, acting_user) -> Actor:
    """A community with a standing requirement, one superadmin holding it, and
    an ordinary admin beside them. Returns the keyholder."""
    keyholder = await acting_user(guild_role=CommunityRole.superadmin)
    await acting_user(guild_role=CommunityRole.admin, guild=keyholder.guild)
    provider = await create_auth_provider(session, slug="corp")
    await create_guild_auth_policy(session, keyholder.guild, provider)
    return keyholder


async def test_an_ordinary_admin_reads_the_connections_and_writes_neither(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The split in one test, across both surfaces the seat holds: reading the
    connections is an admin's, so they can see which providers the community
    signs in through. Deciding who may enter, and through which providers, is
    not, and neither is reading the sign-in rules."""
    keyholder = await _a_seat_and_a_requirement(session, acting_user)
    admin = await acting_user(guild_role=CommunityRole.admin, guild=keyholder.guild)
    guild_id = keyholder.guild.id
    connections = f"/api/v1/communities/{guild_id}/auth/connections"

    read = await client.get(_settings(guild_id), headers=admin.headers)
    assert read.status_code == 403
    assert read.json()["detail"] == "COMMUNITY_SUPERADMIN_REQUIRED"

    listed = await client.get(connections, headers=admin.headers)
    assert listed.status_code == 200
    assert [row["provider_slug"] for row in listed.json()] == ["corp"]

    offered = await client.get(f"{connections}/available", headers=admin.headers)
    assert offered.status_code == 200

    writes = (
        lambda: client.patch(
            _settings(guild_id),
            headers=admin.headers,
            json={"auth_policy": {"policy": "open"}},
        ),
        lambda: client.patch(
            _settings(guild_id),
            headers=admin.headers,
            json={"auth_policy": {"policy": "required", "provider_id": 1}},
        ),
        lambda: client.post(
            connections, headers=admin.headers, json={"provider_id": 1}
        ),
    )
    for write in writes:
        refused = await write()
        assert refused.status_code == 403, refused.text
        assert refused.json()["detail"] == "COMMUNITY_SUPERADMIN_REQUIRED"

    # And the row is untouched.
    session.expire_all()
    assert (await _members_rule(session, guild_id)).policy == "required"


async def test_the_last_seat_cannot_be_vacated_while_a_requirement_stands(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The requirement is lifted from the surface the seat holds, so the last
    holder stays for as long as the requirement does — asked for by their own
    hand on the way out."""
    keyholder = await _a_seat_and_a_requirement(session, acting_user)
    guild_id = keyholder.guild.id

    left = await client.delete(
        f"/api/v1/communities/{guild_id}/leave", headers=keyholder.headers
    )
    assert left.status_code == 400, left.text
    assert left.json()["detail"] == "CANNOT_VACATE_LAST_SUPERADMIN"


async def test_the_last_seat_stays_even_with_no_requirement(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Lifting the sign-in requirement does not free the seat.

    It did once, while the seat was about sign-in alone. It now holds billing
    too, and a guild that has emptied it has nobody inside who can seat
    another — so a guild keeps one whatever its sign-in rule says.
    """
    keyholder = await _a_seat_and_a_requirement(session, acting_user)
    await rules.put(
        session, "auth_policy", SignInRequirement(), guild_id=keyholder.guild.id
    )
    await session.commit()

    refused = await client.delete(
        f"/api/v1/communities/{keyholder.guild.id}/leave", headers=keyholder.headers
    )
    assert refused.status_code == 400, refused.text
    assert refused.json()["detail"] == "CANNOT_VACATE_LAST_SUPERADMIN"

    # A second holder is what frees the first.
    second = await acting_user(
        guild_role=CommunityRole.superadmin, guild=keyholder.guild
    )
    allowed = await client.patch(
        f"/api/v1/communities/{keyholder.guild.id}/members/{keyholder.user.id}",
        headers=second.headers,
        json={"role": "member"},
    )
    assert allowed.status_code == 204, allowed.text


async def test_provider_delete_refused_while_required(
    client: AsyncClient, session: AsyncSession, acting_user
):
    owner = await acting_user("owner")
    guild = await create_guild(session)
    provider = await create_auth_provider(session, slug="corp")
    await create_guild_auth_policy(session, guild, provider)

    response = await client.delete(
        f"/api/v1/settings/auth/providers/{provider.id}", headers=owner.headers
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "AUTH_PROVIDER_IN_USE"


# --- The gate on paths that are not a REST read of the guild's own content ---


async def test_me_aggregate_includes_policy_guild_only_when_satisfied(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Cross-guild /me/* views carry the session's real ``sat``: a policy-gated
    guild's content appears exactly when the session satisfies its provider —
    and its RLS keeps an unsatisfied session's aggregate empty for that guild
    without failing the whole request."""
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    await create_file(session, a.initiative, a.user, name="open doc")

    # The same person in a second community, which requires a sign-in.
    gated_guild = await create_guild(session)
    await create_guild_membership(session, user=a.user, guild=gated_guild)
    gated_initiative = await create_initiative(session, gated_guild, a.user)
    await create_file(session, gated_initiative, a.user, name="gated doc")
    provider = await create_auth_provider(session, slug="corp")
    await create_guild_auth_policy(session, gated_guild, provider)
    provider_id = provider.id

    # Legacy/unsatisfied session: only the open guild's file.
    unsatisfied = await client.get("/api/v1/me/files", headers=a.headers)
    assert unsatisfied.status_code == 200, unsatisfied.text
    assert [d["name"] for d in unsatisfied.json()["items"]] == ["open doc"]

    # A session that satisfied the provider sees both guilds' files.
    satisfied = await client.get(
        "/api/v1/me/files", headers=_sat_headers(a.user, [provider_id])
    )
    names = {d["name"] for d in satisfied.json()["items"]}
    assert names == {"open doc", "gated doc"}


async def test_ws_token_sat_gates_policy_guild(session: AsyncSession, acting_user):
    """The WebSocket join path: ``authenticate_ws_token`` records the token's
    ``sat``, and the ``establish_guild_access`` that follows applies the guild
    auth-policy gate to the socket exactly as REST would."""
    member = await acting_user(guild_role=CommunityRole.member)
    provider = await create_auth_provider(session, slug="corp")
    await create_guild_auth_policy(session, member.guild, provider)
    guild_id, provider_id = member.guild.id, provider.id

    # A session that satisfied nothing: authenticates, gate refuses.
    plain_user = await authenticate_ws_token(get_auth_token(member.user), session)
    assert plain_user is not None
    assert auth_context.current().satisfied_providers == frozenset()
    with pytest.raises(GuildAccessError):
        await establish_guild_access(session, plain_user, guild_id)

    # A satisfied session token joins.
    sat_user = await authenticate_ws_token(
        get_auth_token(
            member.user,
            satisfied_providers=[provider_id],
            asserted_claims=satisfied_claims_for(provider_id),
        ),
        session,
    )
    assert sat_user is not None
    assert auth_context.current().satisfied_providers == frozenset({provider_id})
    ctx = await establish_guild_access(session, sat_user, guild_id)
    assert ctx.guild_id == guild_id


async def test_ws_token_carries_the_passkey_to_the_gate(
    session: AsyncSession, acting_user
):
    """The same join path against a community that asks for a passkey:
    ``authenticate_ws_token`` records what the session's ``amr`` proved, and
    the ``establish_guild_access`` that follows reads it — so a socket is
    admitted on the terms a page is."""
    member = await acting_user(guild_role=CommunityRole.member)
    await create_guild_auth_policy(session, member.guild, methods=[LoginMethod.passkey])
    guild_id = member.guild.id

    with_a_password = await authenticate_ws_token(
        get_auth_token(member.user, amr=["pwd"]), session
    )
    assert with_a_password is not None
    with pytest.raises(GuildAccessError):
        await establish_guild_access(session, with_a_password, guild_id)

    with_a_key = await authenticate_ws_token(
        get_auth_token(member.user, amr=["pwd", "hwk", "mfa"]), session
    )
    assert with_a_key is not None
    ctx = await establish_guild_access(session, with_a_key, guild_id)
    assert ctx.guild_id == guild_id


async def test_system_sentinel_passes_policy_gate(session: AsyncSession, acting_user):
    """User-attributed system work (export/import workers) passes the gate via
    the explicit sentinel — its enqueueing request already satisfied it."""
    member = await acting_user(guild_role=CommunityRole.member)
    provider = await create_auth_provider(session, slug="corp")
    await create_guild_auth_policy(session, member.guild, provider)
    guild_id = member.guild.id

    ctx = await establish_guild_access(session, member.user, guild_id, on_behalf=True)
    assert ctx.guild_id == guild_id


async def test_a_required_rule_names_something(session: AsyncSession):
    """The check constraint: a requirement names a provider or a method; one
    naming neither would ask nothing and refuse nobody."""
    guild = await create_guild(session)
    session.add(CommunityRule(guild_id=guild.id, key="auth_policy", methods=[]))
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


async def test_the_database_refuses_a_password_requirement(session: AsyncSession):
    """Whether passwords exist at all is the deployment's question, held as a
    constraint so it holds for every writer rather than only the endpoint."""
    guild = await create_guild(session)
    session.add(
        CommunityRule(guild_id=guild.id, key="auth_policy", methods=["password"])
    )
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


async def test_db_layer_blocks_unsatisfied_session(
    session: AsyncSession, role_session, acting_user
):
    """The RLS gate itself: with a required policy, the standing a session
    carries is what the content policies read, and a session whose standing
    does not answer the policy sees ZERO content rows. Satisfied sessions, the
    user-attributed system sentinel, and pure system routings (no user) all see
    the rows."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    provider = await create_auth_provider(session, slug="corp")
    await create_guild_auth_policy(session, a.guild, provider)
    user_id, guild_id = a.user.id, a.guild.id

    app_session = await role_session("app_user")

    async def _visible_projects() -> int:
        return len((await app_session.exec(select(Project))).all())

    # Unsatisfied member/admin session: the seam refuses it outright.
    with pytest.raises(GuildAccessError):
        await route_as(app_session, user_id=user_id, guild_id=guild_id)

    # User-attributed system work carries the sentinel, and reads the rows.
    await route_as(
        app_session,
        user_id=user_id,
        guild_id=guild_id,
        on_behalf=True,
    )
    assert await _visible_projects() == 1

    # And the database is the backstop rather than that refusal: with the one
    # value the standing recorded cleared, the same session reads nothing.
    await app_session.exec(text("SELECT set_config('app.guild_auth_ok', '', true)"))
    assert await _visible_projects() == 0
    await app_session.rollback()

    # A routing with nobody behind it is not a session to gate — and on the
    # request login it is not a sweep either: what admits a sweep is the
    # connection's own login, which this is not, so it reads nothing.
    await set_rls_context(app_session, SystemGuild(guild_id))
    assert await _visible_projects() == 0


async def test_a_grantee_answers_the_rule_a_member_does(
    session: AsyncSession, role_session, acting_user
):
    """A content grant reaches the community's work, and the community's
    sign-in rule governs that work whoever reaches it. The database answers
    for the grantee's routing as it does for a member's."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    provider = await create_auth_provider(session, slug="corp")
    await create_guild_auth_policy(session, a.guild, provider)
    operator = await create_user(session, role=UserRole.operator)
    await create_access_grant(session, user=operator, guild=a.guild)

    app_session = await role_session("app_user")

    with pytest.raises(GuildAccessError) as refused:
        await route_as(app_session, user_id=operator.id, guild_id=a.guild.id)
    assert refused.value.detail == "COMMUNITY_AUTH_STEP_UP_REQUIRED"
    assert refused.value.step_up_provider_slug == "corp"
    await app_session.rollback()

    # Routed on the grant, with nothing on the session that answers the rule.
    await route_as(
        app_session,
        user_id=operator.id,
        guild_id=a.guild.id,
        on_behalf=True,
    )
    verdict = (
        await app_session.exec(
            text(
                "SELECT set_config('app.satisfied_providers', '', true), "
                "public.guild_auth_satisfied() AS verdict"
            )
        )
    ).one()
    assert verdict.verdict is False


# --- The rule is decided twice, and the two must agree ----------------------


async def _database_admits(
    session: AsyncSession,
    *,
    guild_id: int,
    user_id: int,
    satisfied: list[int],
    asserted: dict | None = None,
    markers: frozenset[str] = frozenset(),
    role: str | None = None,
) -> bool:
    """What ``public.guild_auth_satisfied()`` says, given the GUCs a request
    with this standing would have set, asked as ``role`` where one is named.

    One statement, so the settings and the question are certainly in the same
    transaction — the context is transaction-local and replays on each new one.
    """
    if role is not None:
        await session.exec(text(f'SET LOCAL ROLE "{role}"'))
    verdict = (
        await session.exec(
            text(
                "SELECT set_config('app.current_user_id', :uid, true), "
                "set_config('app.current_guild_id', :gid, true), "
                "set_config('app.satisfied_providers', :satp, true), "
                "set_config('app.satisfied_claims', :satc, true), "
                "set_config('app.session_amr', :amr, true), "
                "public.guild_auth_satisfied() AS verdict"
            ),
            params={
                "uid": str(user_id),
                "gid": str(guild_id),
                "satp": ",".join(str(p) for p in satisfied),
                "satc": json.dumps(asserted or {}),
                "amr": ",".join(sorted(markers)),
            },
        )
    ).one()
    if role is not None:
        await session.exec(text("RESET ROLE"))
    return bool(verdict.verdict)


async def _app_admits(
    session: AsyncSession,
    policy,
    guild_id: int,
    satisfied,
    asserted: dict | None = None,
    markers: frozenset[str] = frozenset(),
) -> bool:
    """What the gate in ``deps.py`` says, given the same standing."""
    auth_context.record(
        satisfied_providers=frozenset(satisfied), satisfied_claims=asserted or {}
    )
    try:
        await _enforce_guild_auth_policy(
            session,
            policy,
            guild_id,
            frozenset(satisfied),
            markers,
        )
    except GuildAccessError:
        return False
    finally:
        auth_context.reset()
    return True


async def test_the_deployments_factor_rule_stands_over_the_communitys(
    session: AsyncSession, acting_user
):
    """Where the deployment sets the community's second-factor rule, the
    database gate reads its row rather than the community's own beneath it."""
    member = await acting_user(guild_role=CommunityRole.member)
    guild_id = member.guild.id
    await guild_administration(session, member.guild, auth_options=["restrictions"])
    await rules.put(session, "require_second_factor", True, guild_id=guild_id)
    await session.commit()

    async def admits() -> bool:
        return await _database_admits(
            session, guild_id=guild_id, user_id=member.user.id, satisfied=[]
        )

    assert not await admits()
    await rules.put(
        session,
        "require_second_factor",
        False,
        guild_id=guild_id,
        set_by=SetBy.deployment,
    )
    await session.commit()
    assert await admits()


@pytest.mark.parametrize("guest", [False, True], ids=["members", "guests"])
async def test_the_gate_and_the_database_agree_on_every_rule(
    session: AsyncSession, acting_user, guest: bool
):
    """A rule is enforced in two places — Python before the request is routed,
    SQL inside the community's own row-level rules — and a disagreement between
    them is either a rule that does nothing or a refusal nobody can explain.

    Every shape a rule can take, against every standing a session can have:
    the members' half, and the guests' half asked from the community's guest
    role while the members' half asks for something no standing here has.
    """
    member = await acting_user(guild_role=CommunityRole.member)
    provider = await create_auth_provider(session, slug="corp")
    await create_guild_provider_connection(
        session,
        guild=member.guild,
        provider=provider,
        claim="hd",
        claim_values=["acme.com"],
    )
    guild_id, user_id = int(member.guild.id), int(member.user.id)
    provider_id = int(provider.id)
    other_provider_id = provider_id + 1000

    async def db_admits(**proved) -> bool:
        """The database's verdict on a session that satisfied no provider and
        proved this much about itself."""
        return await _database_admits(
            session,
            guild_id=guild_id,
            user_id=user_id,
            satisfied=[],
            asserted={},
            **proved,
        )

    def asks(*methods: LoginMethod, provider: int | None = None) -> SignInRequirement:
        return SignInRequirement("required", provider, frozenset(methods))

    shapes: list[tuple[str, SignInRequirement]] = [
        ("open", SignInRequirement()),
        ("one named provider", asks(provider=provider_id)),
        ("any of ours", asks(LoginMethod.sso)),
        ("a second factor", asks(LoginMethod.totp)),
        ("a passkey", asks(LoginMethod.passkey)),
        ("any of ours, and a second factor", asks(LoginMethod.sso, LoginMethod.totp)),
        ("that provider, and any of ours", asks(LoginMethod.sso, provider=provider_id)),
    ]
    ours = {str(provider_id): {"hd": ["acme.com"]}}
    theirs = {str(provider_id): {"hd": ["elsewhere.com"]}}
    bare: list[tuple[str, list[int], dict]] = [
        ("nothing at all", [], {}),
        ("that provider, counted as theirs", [provider_id], ours),
        ("that provider, counted as somebody else's", [provider_id], theirs),
        ("that provider, asserting nothing", [provider_id], {}),
        ("some other provider", [other_provider_id], {}),
        (
            "some other provider, asserting what this community counts",
            [other_provider_id],
            {str(other_provider_id): {"hd": ["acme.com"]}},
        ),
    ]
    # Each of those against what a session can have recorded about itself. A
    # rule asking for one marker is answered by nothing else on this list.
    # Both kinds of key appear, because the passkey leg takes either and a leg
    # naming only one of them would still pass a matrix that never showed it
    # the other. The key-without-a-factor row is not a session this codebase
    # opens — every ceremony verifies the person, so an assertion records
    # ``mfa`` too — and it is here to hold the two legs apart: it is the only
    # standing that answers a passkey rule and not a factor rule.
    proofs = [
        (", with a factor", frozenset({SECOND_FACTOR_AMR})),
        (", with a device-bound key", frozenset({"hwk", SECOND_FACTOR_AMR})),
        (", with a synced key", frozenset({"swk", SECOND_FACTOR_AMR})),
        (", with a key and no factor", frozenset({"hwk"})),
        ("", frozenset()),
    ]
    standings: list[tuple[str, list[int], dict, frozenset[str]]] = [
        (f"{name}{suffix}", sat, asserted, markers)
        for name, sat, asserted in bare
        for suffix, markers in proofs
    ]

    role = guild_role_name(guild_id, GuildRoleKind.guest) if guest else None
    # A provider no standing below came through, for the members' half the
    # guests are never asked.
    elsewhere_id = int((await create_auth_provider(session, slug="elsewhere")).id)
    for rule_name, requirement in shapes:
        # The guests' rule is asked while the members' one asks for something
        # no standing below has.
        members = asks(provider=elsewhere_id) if guest else requirement
        await rules.put(session, "auth_policy", members, guild_id=guild_id)
        await rules.put(
            session,
            "guest_auth_policy",
            requirement if guest else SignInRequirement(),
            guild_id=guild_id,
        )
        await session.commit()

        for standing, satisfied, asserted, markers in standings:
            in_app = await _app_admits(
                session, requirement, guild_id, satisfied, asserted, markers
            )
            in_db = await _database_admits(
                session,
                guild_id=guild_id,
                user_id=user_id,
                satisfied=satisfied,
                asserted=asserted,
                markers=markers,
                role=role,
            )
            assert in_app == in_db, (
                f"rule {rule_name!r} against a session showing {standing!r}: "
                f"the gate says {in_app}, the database says {in_db}"
            )
    if guest:
        return

    # The matrix says the two layers agree; it does not say what they agree
    # on. Name one answer outright: a community asking for a passkey takes the
    # key and takes nothing else for it.
    key_rule = asks(LoginMethod.passkey)
    await rules.put(session, "auth_policy", key_rule, guild_id=guild_id)
    await session.commit()
    a_key = frozenset({"hwk", SECOND_FACTOR_AMR})
    a_code = frozenset({SECOND_FACTOR_AMR})
    assert await _app_admits(session, key_rule, guild_id, [], None, a_key)
    assert await db_admits(markers=a_key)
    assert not await _app_admits(session, key_rule, guild_id, [], None, a_code)
    assert not await db_admits(markers=a_code)

    # The matrix would pass if both layers refused everything, so pin the two
    # ends of it: an open community admits a bare session, and a rule refuses one.
    await rules.put(session, "auth_policy", SignInRequirement(), guild_id=guild_id)
    await session.commit()
    assert await db_admits()
    await rules.put(session, "auth_policy", asks(LoginMethod.sso), guild_id=guild_id)
    await session.commit()
    assert not await db_admits()


# --- The three things a rule can ask for -------------------------------------
#
# ``require_methods`` names none, one or several of them, and each is read as
# itself. The table below is one row per ask: how a session that has met it is
# opened, what one that has not looks like and is told, and what the deployment
# has to offer before a community may write the ask down.


@dataclass(frozen=True, eq=False)
class Ask:
    """One thing ``require_methods`` can name, and what answers it."""

    id: str
    method: str
    # Opens a session that has met the ask, putting whatever the community
    # needs for it (a provider connection, say) in place first.
    met_by: Callable[[AsyncSession, Guild, User], Awaitable[dict[str, str]]]
    # The ``amr`` of a session that has not met it. Each is the strongest such
    # session for its ask, so the key's row carries a second factor.
    unmet_amr: list[str]
    # What that session is told, and the part of the challenge that is this
    # ask's own.
    refusal: str
    challenge: dict[str, str]
    # The deployment's login methods with this one left out; ``None`` where the
    # ask has no deployment-level switch of its own.
    withheld_by_the_deployment: list[str] | None


async def _a_session_through_one_of_ours(
    session: AsyncSession, guild: Guild, user: User
) -> dict[str, str]:
    """Came in through a provider this community connects to. Which sign-ins
    count is read from those connections, so one is made here."""
    provider = await create_auth_provider(session, slug="corp")
    await create_guild_provider_connection(session, guild=guild, provider=provider)
    return _bearer(
        get_auth_token(
            user,
            amr=["oidc:whatever"],
            satisfied_providers=[provider.id],
            asserted_claims=satisfied_claims_for(provider),
        )
    )


async def _a_session_carrying_the_factor(
    session: AsyncSession, guild: Guild, user: User
) -> dict[str, str]:
    return _bearer(get_auth_token(user, amr=["pwd", "otp", "mfa"]))


async def _a_session_opened_with_a_passkey(
    session: AsyncSession, guild: Guild, user: User
) -> dict[str, str]:
    return _bearer(get_auth_token(user, amr=["pwd", "hwk", "mfa"]))


ANY_OF_OURS = Ask(
    id="any of ours",
    method="sso",
    met_by=_a_session_through_one_of_ours,
    unmet_amr=["pwd"],
    refusal="COMMUNITY_AUTH_STEP_UP_REQUIRED",
    # Named no provider, so the challenge names the community: its own login
    # page is what serves the rule.
    challenge={"X-Auth-Step-Up": ""},
    withheld_by_the_deployment=None,
)
A_SECOND_FACTOR = Ask(
    id="a second factor",
    method="totp",
    met_by=_a_session_carrying_the_factor,
    unmet_amr=["pwd"],
    refusal="COMMUNITY_AUTH_FACTOR_REQUIRED",
    challenge={},
    withheld_by_the_deployment=["password", "sso"],
)
A_PASSKEY = Ask(
    id="a passkey",
    method="passkey",
    met_by=_a_session_opened_with_a_passkey,
    # An assertion records the second factor as well as the key, and a rule
    # naming the key reads the key's own markers.
    unmet_amr=["pwd", "otp", "mfa"],
    refusal="COMMUNITY_AUTH_PASSKEY_REQUIRED",
    challenge={},
    withheld_by_the_deployment=["password", "sso", "totp"],
)
ASKS = [ANY_OF_OURS, A_SECOND_FACTOR, A_PASSKEY]


def _asks(*, the_deployment_can_withhold: bool = False) -> list:
    rows = [
        ask
        for ask in ASKS
        if not the_deployment_can_withhold or ask.withheld_by_the_deployment
    ]
    return [pytest.param(ask, id=ask.id) for ask in rows]


async def _a_community_asking_for(
    session: AsyncSession, acting_user, ask: Ask
) -> Actor:
    """A member of a community whose rule names ``ask``."""
    member = await acting_user(guild_role=CommunityRole.member)
    await create_guild_auth_policy(
        session, member.guild, methods=[LoginMethod(ask.method)]
    )
    return member


@pytest.mark.parametrize("ask", _asks())
async def test_a_session_that_has_met_the_ask_is_admitted(
    client: AsyncClient, session: AsyncSession, acting_user, ask: Ask
):
    """Each ask has its own answer, and a member holding it is let in."""
    member = await _a_community_asking_for(session, acting_user, ask)
    headers = await ask.met_by(session, member.guild, member.user)

    allowed = await client.get(member.g("/initiatives/"), headers=headers)
    assert allowed.status_code == 200, allowed.text


@pytest.mark.parametrize("ask", _asks())
async def test_a_session_that_has_not_is_asked_for_it(
    client: AsyncClient, session: AsyncSession, acting_user, ask: Ask
):
    """The refusal says which ask is unmet, so a page knows what to put in
    front of the member: this community's login page for its own providers, a
    code or a ceremony against the session already open for the other two."""
    member = await _a_community_asking_for(session, acting_user, ask)
    guild_id = member.guild.id

    refused = await client.get(
        member.g("/initiatives/"),
        headers=_bearer(get_auth_token(member.user, amr=ask.unmet_amr)),
    )
    assert refused.status_code == 401
    assert refused.json()["detail"] == ask.refusal
    assert refused.headers["X-Auth-Step-Up-Community"] == str(guild_id)
    # And the standard form beside it (RFC 9470), for a client that knows
    # OAuth and nothing about this app.
    assert "insufficient_user_authentication" in refused.headers["WWW-Authenticate"]
    for header, value in ask.challenge.items():
        assert refused.headers[header] == value


async def test_a_key_a_password_manager_syncs_answers_a_passkey_rule(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """``hwk`` is a key the device holds and ``swk`` one a password manager
    syncs between devices; a community asking for a passkey takes either."""
    member = await _a_community_asking_for(session, acting_user, A_PASSKEY)

    allowed = await client.get(
        member.g("/initiatives/"),
        headers=_bearer(get_auth_token(member.user, amr=["pwd", "swk", "mfa"])),
    )
    assert allowed.status_code == 200, allowed.text


async def test_a_recovery_code_session_is_admitted_too(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The set exists to be used. A recovery code records ``mfa`` without
    ``otp``, and the rule asks for the factor rather than for a live one."""
    member = await _a_community_asking_for(session, acting_user, A_SECOND_FACTOR)

    allowed = await client.get(
        member.g("/initiatives/"),
        headers=_bearer(get_auth_token(member.user, amr=["pwd", "mfa"])),
    )
    assert allowed.status_code == 200, allowed.text


async def test_another_communitys_sign_in_does_not_satisfy_any_of_ours(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Single sign-on somewhere else — the deployment's own providers included
    — is not this community's single sign-on."""
    member = await _a_community_asking_for(session, acting_user, ANY_OF_OURS)
    await create_guild_provider_connection(
        session,
        guild=member.guild,
        provider=await create_auth_provider(session, slug="corp"),
    )
    elsewhere = await create_auth_provider(session, slug="somewhere-else")

    blocked = await client.get(
        member.g("/initiatives/"),
        headers=_bearer(
            get_auth_token(
                member.user, amr=["oidc:whatever"], satisfied_providers=[elsewhere.id]
            )
        ),
    )
    assert blocked.status_code == 401
    assert blocked.json()["detail"] == "COMMUNITY_AUTH_STEP_UP_REQUIRED"


@pytest.mark.parametrize("ask", _asks())
async def test_the_ask_is_written_only_by_a_session_that_has_met_it(
    client: AsyncClient, session: AsyncSession, acting_user, ask: Ask
):
    """The rule the provider check makes, for every other ask too: prove it
    before it binds anybody, so an ask is only ever written by somebody it
    already applies to. One code for four different asks, so the header is
    what tells the page which line of the form the refusal is about."""
    seat = await acting_user(guild_role=CommunityRole.superadmin)
    # Whatever the ask needs of the community is in place, so the seat's own
    # session is the only thing standing between the form and the row.
    met = await ask.met_by(session, seat.guild, seat.user)
    body = {"policy": "required", "require_methods": [ask.method]}

    refused = await client.patch(
        _settings(seat.guild.id),
        headers=_bearer(get_auth_token(seat.user, amr=ask.unmet_amr)),
        json={"auth_policy": body},
    )
    assert refused.status_code == 400
    assert refused.json()["detail"] == "AUTH_RULE_SELF_UNSATISFIED"
    assert refused.headers["X-Auth-Policy-Unmet"] == ask.method

    saved = await client.patch(
        _settings(seat.guild.id), headers=met, json={"auth_policy": body}
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["auth_policy"]["require_methods"] == [ask.method]


@pytest.mark.parametrize("ask", _asks(the_deployment_can_withhold=True))
async def test_a_community_cannot_ask_for_what_the_deployment_withholds(
    client: AsyncClient, session: AsyncSession, acting_user, ask: Ask
):
    """A community's rule reaches only as far as the deployment's own list of
    login methods, and the header names the one that is not on it."""
    seat = await acting_user(guild_role=CommunityRole.superadmin)
    headers = await ask.met_by(session, seat.guild, seat.user)
    assert ask.withheld_by_the_deployment is not None
    await rules.put(
        session,
        "login_methods",
        frozenset(LoginMethod(m) for m in ask.withheld_by_the_deployment),
    )
    await session.commit()

    refused = await client.patch(
        _settings(seat.guild.id),
        headers=headers,
        json={"auth_policy": {"policy": "required", "require_methods": [ask.method]}},
    )
    assert refused.status_code == 409
    assert refused.json()["detail"] == "AUTH_RULE_NOT_OFFERED"
    assert refused.headers["X-Auth-Policy-Unmet"] == ask.method


async def test_a_community_is_told_when_the_deployment_asks_everybody(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Its own box for a second factor has nothing left to add, so the page
    reads this and stops offering one. Asking only the platform rungs leaves a
    community's members untouched, so that box stays."""
    from datetime import datetime, timezone

    from app.core.login_methods import SecondFactorRequirement
    from app.models.platform.user_totp import UserTotp

    seat = await acting_user(guild_role=CommunityRole.superadmin)
    # Under ``everyone`` this admin is asked for a factor like anybody else,
    # so they hold one — which is the state the page is read in.
    session.add(UserTotp(user_id=seat.user.id, confirmed_at=datetime.now(timezone.utc)))
    await session.commit()
    url = _settings(seat.guild.id)

    for level, told in (
        (SecondFactorRequirement.platform_roles, False),
        (SecondFactorRequirement.everyone, True),
    ):
        await rules.put(session, "second_factor_requirement", level)
        await session.commit()

        read = await client.get(url, headers=seat.headers)

        assert read.status_code == 200, read.text
        assert read.json()["auth_policy"]["factor_required_by_platform"] is told


# --- a second factor, asked for on its own -----------------------------------


async def test_a_community_asks_for_a_factor_without_asking_about_arrival(
    client, session: AsyncSession, acting_user
):
    """No sign-in rule, and still a requirement: the two are separate answers,
    which is what lets a community that lets people arrive however they like
    ask them to hold a factor.

    A factor applies while the community holds the option it needs: the
    community's own while it holds ``restrictions``, a sign-in rule's while it
    holds ``providers``. Withdrawn, the rule stays set and stops applying;
    granted back, it applies again."""
    seat = await acting_user(guild_role=CommunityRole.superadmin)
    await guild_administration(session, seat.guild, auth_options=["restrictions"])
    # A session that has presented one; the seat has to answer its own ask.
    headers = _bearer(get_auth_token(seat.user, amr=[SECOND_FACTOR_AMR]))

    response = await client.patch(
        _settings(seat.guild.id),
        json={"require_second_factor": True},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["require_second_factor"] is True
    assert await rules.community_value(
        session, seat.guild.id, "require_second_factor", applied=False
    )

    async def asked() -> bool:
        reached = await client.get(seat.g("/initiatives/"), headers=seat.headers)
        if reached.status_code == 200:
            return False
        assert reached.json()["detail"] == "COMMUNITY_AUTH_FACTOR_REQUIRED", (
            reached.text
        )
        return True

    assert await asked()
    await guild_administration(session, seat.guild, auth_options=[])
    assert not await asked()
    await guild_administration(session, seat.guild, auth_options=["restrictions"])
    assert await asked()

    await guild_administration(
        session, seat.guild, auth_options=["providers", "restrictions"]
    )
    await rules.put(session, "require_second_factor", False, guild_id=seat.guild.id)
    await create_guild_auth_policy(session, seat.guild, methods=[LoginMethod.totp])
    assert await asked()
    await guild_administration(session, seat.guild, auth_options=["restrictions"])
    assert not await asked()


async def test_a_refused_rule_leaves_the_communitys_others_as_they_were(
    client, session: AsyncSession, acting_user
):
    """One change across the seat's rules: switching push off beside a factor
    the seat has not presented is refused as a whole, and a mixed change the
    seat meets is written as a whole."""
    seat = await acting_user(guild_role=CommunityRole.superadmin)
    await guild_administration(session, seat.guild, auth_options=["restrictions"])
    body = {"allow_push_notifications": False, "require_second_factor": True}

    refused = await client.patch(
        _settings(seat.guild.id), json=body, headers=seat.headers
    )
    assert refused.status_code == 400, refused.text
    read = await client.get(_settings(seat.guild.id), headers=seat.headers)
    assert read.json()["allow_push_notifications"] is True
    assert read.json()["require_second_factor"] is False

    met = _bearer(get_auth_token(seat.user, amr=[SECOND_FACTOR_AMR]))
    written = await client.patch(_settings(seat.guild.id), json=body, headers=met)
    assert written.status_code == 200, written.text
    assert written.json()["allow_push_notifications"] is False
    assert written.json()["require_second_factor"] is True
