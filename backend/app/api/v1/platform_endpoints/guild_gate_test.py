"""What a community makes of a sign-in it did not serve.

There is one sign-in, at the deployment. A community says which arrivals count
as its own and whether they join on sight, and both are applied afterwards —
the first on every request, the second once, when somebody arrives.

Runs against the same fake IdP harness as the operator flow tests.
"""

from urllib.parse import parse_qs, urlsplit

import httpx
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.v1.platform_endpoints.auth_test import _wire_fake_idp
from app.models.platform.auth_session import AuthSession
from app.models.platform.guild import GuildMembership, CommunityRole
from app.testing.factories import (
    guild_administration,
    create_auth_provider,
    create_federated_identity,
    create_guild,
    create_guild_membership,
    create_guild_auth_policy,
    create_guild_provider_connection,
    create_user,
    get_auth_token,
)
from app.testing.factories import NARROWED_CLAIM, NARROWED_VALUE
from app.testing.oidc import ISSUER as OIDC_ISSUER, FakeIdp, mint_id_token
from app.core.login_methods import LoginMethod
from app.core.rules import SignInRequirement
from app.services.platform import rules


# ── Arriving ───────────────────────────────────────────────────────────────


async def _begin_login(client: AsyncClient, slug: str = "corp") -> tuple[str, str]:
    response = await client.get(f"/api/v1/auth/{slug}/login", follow_redirects=False)
    assert response.status_code in (302, 307), response.text
    location = response.headers["location"]
    assert location.startswith(f"{OIDC_ISSUER}/authorize?")
    query = {k: v[0] for k, v in parse_qs(urlsplit(location).query).items()}
    return query["state"], query["nonce"]


async def _sign_in(
    client: AsyncClient,
    idp: FakeIdp,
    *,
    slug: str = "corp",
    id_token_claims: dict | None = None,
):
    """One sign-in at the deployment, through ``slug``."""
    state, nonce = await _begin_login(client, slug)
    idp.token_response = httpx.Response(
        200,
        json={
            "access_token": "at-1",
            "refresh_token": "rt-1",
            "id_token": mint_id_token(nonce=nonce, **(id_token_claims or {})),
            "token_type": "Bearer",
        },
    )
    return await client.get(
        f"/api/v1/auth/{slug}/callback",
        params={"code": "code-1", "state": state},
        follow_redirects=False,
    )


async def _is_member(session: AsyncSession, *, guild_id: int, user_id: int) -> bool:
    session.expire_all()
    row = (
        await session.exec(
            select(GuildMembership).where(
                GuildMembership.guild_id == guild_id,
                GuildMembership.user_id == user_id,
            )
        )
    ).first()
    return row is not None


async def _who_just_signed_in(session: AsyncSession) -> int | None:
    """The account behind the newest session, as a plain id — the rows are
    written on another session, so nothing here holds a loaded copy."""
    session.expire_all()
    rows = (
        await session.exec(
            select(AuthSession.user_id).order_by(AuthSession.created_at.desc())
        )
    ).all()
    return rows[0] if rows else None


# ── The community's own page ───────────────────────────────────────────────


async def test_a_communitys_page_offers_the_deployments_sign_in(
    client: AsyncClient, session: AsyncSession
):
    """A community lists the ways in it counts as its own. They are the
    deployment's ways in, so the buttons lead there."""
    guild = await create_guild(session)
    provider = await create_auth_provider(session, slug="corp")
    await create_guild_provider_connection(session, guild=guild, provider=provider)

    response = await client.get(f"/api/v1/auth/c/{guild.id}/providers")

    assert response.status_code == 200, response.text
    body = response.json()
    assert [row["slug"] for row in body["providers"]] == ["corp"]
    assert body["providers"][0]["login_url"] == "/api/v1/auth/corp/login"
    assert body["community_name"] == guild.name


async def test_a_provider_it_does_not_connect_to_is_not_listed(
    client: AsyncClient, session: AsyncSession
):
    guild = await create_guild(session)
    await create_auth_provider(session, slug="corp")

    response = await client.get(f"/api/v1/auth/c/{guild.id}/providers")

    assert response.status_code == 200
    assert response.json()["providers"] == []


# ── Joining on arrival ─────────────────────────────────────────────────────


async def test_arriving_joins_where_the_community_said_so(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """A community can say that people it counts as its own join on sight,
    which is how somebody reaches a community nobody invited them to."""
    fake_idp = FakeIdp()
    _wire_fake_idp(monkeypatch, fake_idp)
    guild = await create_guild(session)
    provider = await create_auth_provider(session, slug="corp", allow_jit=True)
    await create_guild_provider_connection(
        session, guild=guild, provider=provider, auto_join=True
    )
    guild_id = guild.id

    response = await _sign_in(
        client, fake_idp, id_token_claims={NARROWED_CLAIM: NARROWED_VALUE}
    )

    assert response.status_code in (302, 307), response.text
    arrived = await _who_just_signed_in(session)
    assert arrived is not None
    assert await _is_member(session, guild_id=guild_id, user_id=arrived)


async def test_arriving_joins_nobody_by_default(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """A community that wants to choose who joins leaves it off, and a
    sign-in through its provider is only a sign-in."""
    fake_idp = FakeIdp()
    _wire_fake_idp(monkeypatch, fake_idp)
    guild = await create_guild(session)
    provider = await create_auth_provider(session, slug="corp", allow_jit=True)
    await create_guild_provider_connection(session, guild=guild, provider=provider)
    guild_id = guild.id

    await _sign_in(client, fake_idp)

    arrived = await _who_just_signed_in(session)
    assert arrived is not None
    assert not await _is_member(session, guild_id=guild_id, user_id=arrived)


async def test_the_narrowing_decides_who_joins(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """ "Our workspace, not everyone this provider vouches for" — applied to
    the arrival before the community takes anybody in."""
    fake_idp = FakeIdp()
    _wire_fake_idp(monkeypatch, fake_idp)
    guild = await create_guild(session)
    provider = await create_auth_provider(session, slug="corp", allow_jit=True)
    await create_guild_provider_connection(
        session,
        guild=guild,
        provider=provider,
        claim="hd",
        claim_values=["acme.com"],
        auto_join=True,
    )
    guild_id = guild.id

    await _sign_in(client, fake_idp, id_token_claims={"hd": "elsewhere.com"})

    arrived = await _who_just_signed_in(session)
    assert arrived is not None
    assert not await _is_member(session, guild_id=guild_id, user_id=arrived)


async def test_the_narrowing_admits_the_communitys_own(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    fake_idp = FakeIdp()
    _wire_fake_idp(monkeypatch, fake_idp)
    guild = await create_guild(session)
    provider = await create_auth_provider(session, slug="corp", allow_jit=True)
    await create_guild_provider_connection(
        session,
        guild=guild,
        provider=provider,
        claim="hd",
        claim_values=["acme.com"],
        auto_join=True,
    )
    guild_id = guild.id

    await _sign_in(client, fake_idp, id_token_claims={"hd": "acme.com"})

    arrived = await _who_just_signed_in(session)
    assert arrived is not None
    assert await _is_member(session, guild_id=guild_id, user_id=arrived)


async def test_a_full_community_is_skipped_and_the_sign_in_stands(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """One community being full is that community's business. The person
    signed in to the deployment, and keeps the account they signed in with."""
    fake_idp = FakeIdp()
    _wire_fake_idp(monkeypatch, fake_idp)
    guild = await create_guild(session)
    await guild_administration(session, guild, max_users=0)
    provider = await create_auth_provider(session, slug="corp", allow_jit=True)
    await create_guild_provider_connection(
        session, guild=guild, provider=provider, auto_join=True
    )
    guild_id = guild.id

    response = await _sign_in(client, fake_idp)

    assert response.status_code in (302, 307), response.text
    arrived = await _who_just_signed_in(session)
    assert arrived is not None
    assert not await _is_member(session, guild_id=guild_id, user_id=arrived)


# ── The gate ───────────────────────────────────────────────────────────────


async def _member_of_a_narrowed_community(session: AsyncSession):
    member = await create_user(session)
    guild = await create_guild(session)
    await create_guild_membership(
        session, user=member, guild=guild, role=CommunityRole.member
    )
    provider = await create_auth_provider(session, slug="corp")
    await create_federated_identity(session, user=member, provider=provider)
    connection = await create_guild_provider_connection(
        session,
        guild=guild,
        provider=provider,
        claim="hd",
        claim_values=["acme.com"],
    )
    await create_guild_auth_policy(session, guild, provider)
    return member, guild, provider, connection


def _arrived_as(user, provider_id: int, asserted: dict[str, list[str]] | None):
    token = get_auth_token(
        user,
        satisfied_providers=[provider_id],
        asserted_claims={provider_id: asserted} if asserted else None,
    )
    return {"Authorization": f"Bearer {token}"}


async def test_coming_in_the_named_way_and_counted_as_theirs_admits(
    client: AsyncClient, session: AsyncSession
):
    member, guild, provider, _ = await _member_of_a_narrowed_community(session)

    allowed = await client.get(
        f"/api/v1/c/{guild.id}/initiatives/",
        headers=_arrived_as(member, provider.id, {"hd": ["acme.com"]}),
    )

    assert allowed.status_code == 200, allowed.text


async def test_the_same_provider_without_the_communitys_claim_does_not(
    client: AsyncClient, session: AsyncSession
):
    """The requirement names a provider that vouches for more than this
    community. What the community asked about is the rest of the answer."""
    member, guild, provider, _ = await _member_of_a_narrowed_community(session)

    blocked = await client.get(
        f"/api/v1/c/{guild.id}/initiatives/",
        headers=_arrived_as(member, provider.id, {"hd": ["elsewhere.com"]}),
    )

    assert blocked.status_code == 401, blocked.text
    assert blocked.json()["detail"] == "COMMUNITY_AUTH_STEP_UP_REQUIRED"


async def test_a_session_that_asserted_nothing_does_not(
    client: AsyncClient, session: AsyncSession
):
    member, guild, provider, _ = await _member_of_a_narrowed_community(session)

    blocked = await client.get(
        f"/api/v1/c/{guild.id}/initiatives/",
        headers=_arrived_as(member, provider.id, None),
    )

    assert blocked.status_code == 401, blocked.text


async def test_the_rule_is_the_one_in_force_now(
    client: AsyncClient, session: AsyncSession
):
    """The session records what the provider asserted; the community records
    which values count. Change the second and the answer changes, without
    anybody signing in again — which is the point of reading it here rather
    than deciding it at sign-in.
    """
    member, guild, provider, connection = await _member_of_a_narrowed_community(session)
    headers = _arrived_as(member, provider.id, {"hd": ["acme.com"]})

    assert (
        await client.get(f"/api/v1/c/{guild.id}/initiatives/", headers=headers)
    ).status_code == 200

    connection.claim_values = ["someone-else.com"]
    session.add(connection)
    await session.commit()

    assert (
        await client.get(f"/api/v1/c/{guild.id}/initiatives/", headers=headers)
    ).status_code == 401


async def test_any_of_ours_is_answered_by_the_connections(
    client: AsyncClient, session: AsyncSession
):
    """ "Come in through one of ours, we do not mind which" — read from what
    the community connects to rather than from a marker on the session."""
    member = await create_user(session)
    guild = await create_guild(session)
    await create_guild_membership(
        session, user=member, guild=guild, role=CommunityRole.member
    )
    ours = await create_auth_provider(session, slug="corp")
    await create_guild_provider_connection(session, guild=guild, provider=ours)
    theirs = await create_auth_provider(session, slug="other-corp")
    await rules.put(
        session,
        "auth_policy",
        SignInRequirement("required", None, frozenset({LoginMethod.sso})),
        guild_id=guild.id,
    )
    await session.commit()

    allowed = await client.get(
        f"/api/v1/c/{guild.id}/initiatives/",
        headers=_arrived_as(member, ours.id, {NARROWED_CLAIM: [NARROWED_VALUE]}),
    )
    blocked = await client.get(
        f"/api/v1/c/{guild.id}/initiatives/",
        headers=_arrived_as(member, theirs.id, None),
    )

    assert allowed.status_code == 200, allowed.text
    assert blocked.status_code == 401, blocked.text


async def test_disconnecting_is_what_ends_it(
    client: AsyncClient, session: AsyncSession
):
    """A connection is what makes a provider one of a community's own, so a
    session that satisfied it stops satisfying it once it is gone."""
    member, guild, provider, connection = await _member_of_a_narrowed_community(session)
    headers = _arrived_as(member, provider.id, {"hd": ["acme.com"]})
    assert (
        await client.get(f"/api/v1/c/{guild.id}/initiatives/", headers=headers)
    ).status_code == 200

    connection.enabled = False
    session.add(connection)
    await session.commit()

    assert (
        await client.get(f"/api/v1/c/{guild.id}/initiatives/", headers=headers)
    ).status_code == 401
