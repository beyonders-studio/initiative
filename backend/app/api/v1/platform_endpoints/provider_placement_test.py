"""The platform's sign-in placement rules, written on a provider."""

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.oidc_claim_mapping import ClaimRuleAuthor, OIDCClaimMapping
from app.models.platform.user import UserRole
from app.services.platform import rules
from app.services.tenant.initiatives import get_role_by_name
from app.testing.factories import (
    create_auth_provider,
    create_guild,
    create_guild_provider_connection,
    create_initiative,
    create_user,
    get_auth_headers,
)


BASE = "/api/v1/settings/placement"


async def _headers(session: AsyncSession, role: UserRole) -> dict[str, str]:
    return get_auth_headers(await create_user(session, role=role))


async def _accepting(session: AsyncSession, *, accepts: bool = True):
    """A provider and a community whose connection to it says whether the
    platform's rules may place people there."""
    owner = await create_user(session)
    guild = await create_guild(session, creator=owner, name="Engineering")
    provider = await create_auth_provider(session, slug="corp")
    await create_guild_provider_connection(
        session, guild=guild, provider=provider, accepts_provider_placement=accepts
    )
    return owner, guild, provider


async def test_an_operator_writes_a_rule_for_a_community_that_accepts(
    client: AsyncClient, session: AsyncSession
):
    _, guild, provider = await _accepting(session)
    headers = await _headers(session, UserRole.operator)

    response = await client.post(
        f"{BASE}/rules",
        headers=headers,
        json={
            "provider_id": provider.id,
            "claim_value": " eng ",
            "community_id": guild.id,
            "community_role": "admin",
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["claim_value"] == "eng"
    assert body["community_name"] == "Engineering"
    assert body["applies"] is True
    row = await session.get(OIDCClaimMapping, body["id"])
    assert row is not None and row.author == ClaimRuleAuthor.provider

    listed = (await client.get(f"{BASE}/", headers=headers)).json()
    assert [rule["id"] for rule in listed["rules"]] == [body["id"]]
    assert listed["placement_everywhere"] is False


async def test_a_community_that_has_not_accepted_is_refused_until_everywhere(
    client: AsyncClient, session: AsyncSession
):
    _, guild, provider = await _accepting(session, accepts=False)
    operator = await _headers(session, UserRole.operator)
    owner = await _headers(session, UserRole.owner)
    rule = {"provider_id": provider.id, "claim_value": "eng", "community_id": guild.id}

    refused = await client.post(f"{BASE}/rules", headers=operator, json=rule)
    assert refused.status_code == 400
    assert refused.json()["detail"] == "AUTH_PROVIDER_PLACEMENT_NOT_ACCEPTED"

    # The switch is the owner's.
    assert (
        await client.put(f"{BASE}/everywhere", headers=operator, json={"enabled": True})
    ).status_code == 403
    turned_on = await client.put(
        f"{BASE}/everywhere", headers=owner, json={"enabled": True}
    )
    assert turned_on.status_code == 200, turned_on.text
    assert (await rules.platform_values(session))["provider_placement_everywhere"]

    written = await client.post(f"{BASE}/rules", headers=operator, json=rule)
    assert written.status_code == 201, written.text
    assert written.json()["applies"] is True


async def test_turning_everywhere_on_is_recorded(
    client: AsyncClient, session: AsyncSession, capfd
):
    from app.testing import emitted

    owner = await _headers(session, UserRole.owner)
    capfd.readouterr()

    response = await client.put(
        f"{BASE}/everywhere", headers=owner, json={"enabled": True}
    )

    assert response.status_code == 200, response.text
    records = [
        row
        for row in emitted(capfd)
        if row["event_type"] == "platform.provider_placement_everywhere_changed"
    ]
    assert len(records) == 1
    assert records[0]["detail"] == {"from": False, "to": True}


async def test_placement_is_for_operators_and_owners(
    client: AsyncClient, session: AsyncSession
):
    member = await _headers(session, UserRole.member)
    assert (await client.get(f"{BASE}/", headers=member)).status_code == 403


@pytest.mark.parametrize(
    "match,code",
    [
        pytest.param({}, "AUTH_PROVIDER_RULE_NEEDS_A_MATCH", id="nothing to match"),
        pytest.param(
            {"scope_claim": "idp"},
            "AUTH_PROVIDER_RULE_SCOPE_HALF_SET",
            id="a directory claim without its value",
        ),
    ],
)
async def test_a_rule_matches_a_group_a_directory_or_both(
    client: AsyncClient, session: AsyncSession, match: dict, code: str
):
    _, guild, provider = await _accepting(session)
    headers = await _headers(session, UserRole.operator)

    response = await client.post(
        f"{BASE}/rules",
        headers=headers,
        json={"provider_id": provider.id, "community_id": guild.id, **match},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == code


async def test_a_directory_rule_needs_no_group(
    client: AsyncClient, session: AsyncSession
):
    _, guild, provider = await _accepting(session)
    headers = await _headers(session, UserRole.operator)

    response = await client.post(
        f"{BASE}/rules",
        headers=headers,
        json={
            "provider_id": provider.id,
            "community_id": guild.id,
            "scope_claim": "idp",
            "scope_value": "acme-adfs",
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["claim_value"] is None


async def test_the_initiative_picker_reads_a_placeable_community_only(
    client: AsyncClient, session: AsyncSession
):
    owner, guild, provider = await _accepting(session)
    initiative = await create_initiative(session, guild, owner, name="Roadmap")
    pm_role = await get_role_by_name(
        session, initiative_id=initiative.id, role_name="project_manager"
    )
    closed = await create_guild(session, creator=owner, name="Elsewhere")
    headers = await _headers(session, UserRole.operator)

    listed = await client.get(
        f"{BASE}/providers/{provider.id}/communities/{guild.id}/initiatives",
        headers=headers,
    )
    assert listed.status_code == 200, listed.text
    roadmap = next(row for row in listed.json() if row["name"] == "Roadmap")
    assert pm_role.id in {role["id"] for role in roadmap["roles"]}

    refused = await client.get(
        f"{BASE}/providers/{provider.id}/communities/{closed.id}/initiatives",
        headers=headers,
    )
    assert refused.status_code == 404

    placed = await client.post(
        f"{BASE}/rules",
        headers=headers,
        json={
            "provider_id": provider.id,
            "claim_value": "leads",
            "community_id": guild.id,
            "initiative_id": initiative.id,
            "initiative_role_id": pm_role.id,
        },
    )
    assert placed.status_code == 201, placed.text
    assert placed.json()["initiative_name"] == "Roadmap"


async def test_the_community_search_says_which_communities_accept(
    client: AsyncClient, session: AsyncSession
):
    owner, guild, provider = await _accepting(session)
    await create_guild(session, creator=owner, name="Engine room")
    headers = await _headers(session, UserRole.operator)

    response = await client.get(
        f"{BASE}/communities",
        headers=headers,
        params={"provider_id": provider.id, "search": "engine"},
    )

    assert response.status_code == 200, response.text
    assert {row["name"]: row["placeable"] for row in response.json()} == {
        "Engine room": False,
        "Engineering": True,
    }


async def test_each_surface_edits_only_its_own_rules(
    client: AsyncClient, session: AsyncSession
):
    from app.models.platform.guild import CommunityRole
    from app.testing.factories import create_guild_membership

    seat_holder = await create_user(session)
    guild = await create_guild(session, creator=seat_holder)
    await create_guild_membership(
        session, user=seat_holder, guild=guild, role=CommunityRole.superadmin
    )
    seat = get_auth_headers(seat_holder)
    provider = await create_auth_provider(session, slug="corp")
    await create_guild_provider_connection(
        session, guild=guild, provider=provider, accepts_provider_placement=True
    )
    operator = await _headers(session, UserRole.operator)
    created = await client.post(
        f"{BASE}/rules",
        headers=operator,
        json={
            "provider_id": provider.id,
            "claim_value": "eng",
            "community_id": guild.id,
        },
    )
    assert created.status_code == 201, created.text
    rule_id = created.json()["id"]
    community_rules = f"/api/v1/communities/{guild.id}/auth/rules"

    # The community sees it, read-only, beside its own.
    rules = await client.get(community_rules, headers=seat)
    assert rules.status_code == 200, rules.text
    body = rules.json()
    assert body["rules"] == []
    assert [rule["id"] for rule in body["provider_rules"]] == [rule_id]
    assert body["provider_rules"][0]["applies"] is True

    # And changes it through neither of its own routes.
    removed = await client.delete(f"{community_rules}/{rule_id}", headers=seat)
    assert removed.status_code == 404
    session.expunge_all()
    assert (
        await session.exec(
            select(OIDCClaimMapping).where(OIDCClaimMapping.id == rule_id)
        )
    ).one_or_none() is not None


async def test_the_page_lists_every_community_waiting_for_an_answer(
    client: AsyncClient, session: AsyncSession
):
    owner = await create_user(session)
    asking = await create_guild(session, creator=owner, name="Asking")
    answered = await create_guild(session, creator=owner, name="Answered")
    provider = await create_auth_provider(session, slug="google")
    waiting = await create_guild_provider_connection(
        session,
        guild=asking,
        provider=provider,
        auto_join=True,
        narrowing_approved_at=None,
    )
    await create_guild_provider_connection(session, guild=answered, provider=provider)
    headers = await _headers(session, UserRole.operator)

    listed = await client.get(f"{BASE}/requests", headers=headers)

    assert listed.status_code == 200, listed.text
    assert [(row["community_name"], row["connection_id"]) for row in listed.json()] == [
        ("Asking", waiting.id)
    ]

    agreed = await client.put(
        f"/api/v1/settings/communities/{asking.id}/narrowings/{waiting.id}",
        headers=headers,
        json={"agreed": True},
    )
    assert agreed.status_code == 200, agreed.text
    assert (await client.get(f"{BASE}/requests", headers=headers)).json() == []
