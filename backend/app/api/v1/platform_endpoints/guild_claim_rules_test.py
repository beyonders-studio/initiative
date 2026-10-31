"""What a community makes of the groups its provider asserts.

The other half of a connection, and under test as such: a rule only exists for
a provider the community already counts as its own, and it says where the
people carrying one group land.
"""

from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.testing import guild_of
from app.core.messages import AuthProviderMessages, SettingsMessages
from app.models.platform.guild import CommunityRole
from app.models.tenant.claim_rule_initiative import ClaimRuleInitiative
from app.testing.schema_harness import route_session_to_guild
from app.testing.factories import (
    create_auth_provider,
    create_guild,
    create_guild_membership,
    create_guild_provider_connection,
    create_initiative,
    create_user,
    get_auth_headers,
)


async def _seat(session: AsyncSession, *, auth_options: list[str] | None = None):
    """A community with somebody in the seat that decides who may enter."""
    admin = await create_user(session)
    kwargs = {} if auth_options is None else {"auth_options": auth_options}
    guild = await create_guild(session, creator=admin, **kwargs)
    await create_guild_membership(
        session, user=admin, guild=guild, role=CommunityRole.superadmin
    )
    return admin, guild


def _base(guild_id: int) -> str:
    return f"/api/v1/communities/{guild_id}/auth/rules"


async def _connected(session: AsyncSession, guild, **provider_kwargs):
    provider = await create_auth_provider(session, **provider_kwargs)
    await create_guild_provider_connection(session, guild=guild, provider=provider)
    return provider


async def _a_role(session: AsyncSession, initiative) -> tuple[int, str]:
    """One of an initiative's roles, as plain values — its roles live in its
    own guild's schema, which the session has to be routed into to read."""
    from sqlmodel import select

    from app.models.tenant.initiative import InitiativeRoleModel

    await route_session_to_guild(session, guild_of(initiative))
    row = (
        await session.exec(
            select(InitiativeRoleModel)
            .where(InitiativeRoleModel.initiative_id == initiative.id)
            .order_by(InitiativeRoleModel.id)
        )
    ).first()
    assert row is not None and row.id is not None
    return row.id, row.display_name


async def test_the_seat_writes_reads_and_removes_a_rule(
    client: AsyncClient, session: AsyncSession
):
    admin, guild = await _seat(session)
    provider = await _connected(
        session, guild, slug="entra", display_name="Entra", role_claim_path="groups"
    )
    headers = get_auth_headers(admin)

    created = await client.post(
        _base(guild.id),
        headers=headers,
        json={
            "provider_id": provider.id,
            "claim_value": "eng-platform",
            "community_role": "member",
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["claim_value"] == "eng-platform"
    assert body["provider_display_name"] == "Entra"
    assert body["initiative_id"] is None

    listed = await client.get(_base(guild.id), headers=headers)
    assert listed.status_code == 200, listed.text
    assert [r["claim_value"] for r in listed.json()["rules"]] == ["eng-platform"]
    # The operator told this provider where groups live, so a rule against it
    # can match something.
    assert listed.json()["reporting_provider_ids"] == [provider.id]

    removed = await client.delete(f"{_base(guild.id)}/{body['id']}", headers=headers)
    assert removed.status_code == 204, removed.text
    after = await client.get(_base(guild.id), headers=headers)
    assert after.json()["rules"] == []


async def test_a_rule_needs_the_provider_to_be_one_of_ours(
    client: AsyncClient, session: AsyncSession
):
    """The tie between the two halves. Saying what a provider's groups mean is
    the same sentence as saying its people are yours, so there is no writing
    one without the other."""
    admin, guild = await _seat(session)
    stranger = await create_auth_provider(session, slug="someone-elses")
    headers = get_auth_headers(admin)

    refused = await client.post(
        _base(guild.id),
        headers=headers,
        json={"provider_id": stranger.id, "claim_value": "staff"},
    )
    assert refused.status_code == 400, refused.text
    assert refused.json()["detail"] == AuthProviderMessages.RULE_PROVIDER_NOT_CONNECTED

    await create_guild_provider_connection(session, guild=guild, provider=stranger)
    accepted = await client.post(
        _base(guild.id),
        headers=headers,
        json={"provider_id": stranger.id, "claim_value": "staff"},
    )
    assert accepted.status_code == 201, accepted.text


async def test_a_rule_can_place_somebody_in_an_initiative(
    client: AsyncClient, session: AsyncSession
):
    admin, guild = await _seat(session)
    provider = await _connected(session, guild, role_claim_path="groups")
    initiative = await create_initiative(session, guild=guild, creator=admin)
    initiative_id, initiative_name = initiative.id, initiative.name
    role_id, role_name = await _a_role(session, initiative)
    guild_id = guild.id
    headers = get_auth_headers(admin)
    rule = {
        "provider_id": provider.id,
        "claim_value": "design",
        "community_role": "member",
        "initiative_id": initiative_id,
        "initiative_role_id": role_id,
    }

    created = await client.post(_base(guild_id), headers=headers, json=rule)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["initiative_id"] == initiative_id
    assert body["initiative_name"] == initiative_name
    assert body["initiative_role_name"] == role_name
    listed = (await client.get(_base(guild_id), headers=headers)).json()["rules"]
    assert [(r["initiative_id"], r["initiative_role_id"]) for r in listed] == [
        (initiative_id, role_id)
    ]

    # The same group into the same initiative is the same rule; into the
    # community alone it is another.
    again = await client.post(_base(guild_id), headers=headers, json=rule)
    assert again.status_code == 409, again.text
    assert again.json()["detail"] == AuthProviderMessages.RULE_EXISTS
    community_only = {
        key: rule[key] for key in ("provider_id", "claim_value", "community_role")
    }
    assert (
        await client.post(_base(guild_id), headers=headers, json=community_only)
    ).status_code == 201

    # Its initiative is kept in the community's schema and goes with it.
    removed = await client.delete(f"{_base(guild_id)}/{body['id']}", headers=headers)
    assert removed.status_code == 204, removed.text
    await route_session_to_guild(session, guild_id)
    assert await session.get(ClaimRuleInitiative, body["id"]) is None


async def test_an_initiative_rule_names_both_halves_or_neither(
    client: AsyncClient, session: AsyncSession
):
    admin, guild = await _seat(session)
    provider = await _connected(session, guild)
    initiative = await create_initiative(session, guild=guild, creator=admin)
    initiative_id = initiative.id
    headers = get_auth_headers(admin)

    refused = await client.post(
        _base(guild.id),
        headers=headers,
        json={
            "provider_id": provider.id,
            "claim_value": "design",
            "initiative_id": initiative_id,
        },
    )
    assert refused.status_code == 400, refused.text
    assert refused.json()["detail"] == SettingsMessages.INITIATIVE_FIELDS_REQUIRED


async def test_a_rule_reaches_only_this_communitys_own_initiatives(
    client: AsyncClient, session: AsyncSession
):
    admin, guild = await _seat(session)
    provider = await _connected(session, guild)
    elsewhere_admin, elsewhere = await _seat(session)
    theirs = await create_initiative(session, guild=elsewhere, creator=elsewhere_admin)
    theirs_id = theirs.id
    theirs_role_id, _ = await _a_role(session, theirs)
    headers = get_auth_headers(admin)

    refused = await client.post(
        _base(guild.id),
        headers=headers,
        json={
            "provider_id": provider.id,
            "claim_value": "design",
            "initiative_id": theirs_id,
            "initiative_role_id": theirs_role_id,
        },
    )
    assert refused.status_code == 400, refused.text
    assert refused.json()["detail"] == SettingsMessages.INITIATIVE_WRONG_GUILD


async def test_a_rule_hands_out_no_seat_that_decides_who_may_enter(
    client: AsyncClient, session: AsyncSession
):
    admin, guild = await _seat(session)
    provider = await _connected(session, guild)
    headers = get_auth_headers(admin)

    refused = await client.post(
        _base(guild.id),
        headers=headers,
        json={
            "provider_id": provider.id,
            "claim_value": "staff",
            "community_role": "superadmin",
        },
    )
    assert refused.status_code == 400, refused.text
    assert refused.json()["detail"] == SettingsMessages.INVALID_GUILD_ROLE


async def test_one_group_lands_in_one_place(client: AsyncClient, session: AsyncSession):
    admin, guild = await _seat(session)
    provider = await _connected(session, guild)
    headers = get_auth_headers(admin)
    rule = {"provider_id": provider.id, "claim_value": "staff"}

    assert (
        await client.post(_base(guild.id), headers=headers, json=rule)
    ).status_code == 201
    again = await client.post(_base(guild.id), headers=headers, json=rule)
    assert again.status_code == 409, again.text
    assert again.json()["detail"] == AuthProviderMessages.RULE_EXISTS


async def test_another_communitys_rule_is_not_there(
    client: AsyncClient, session: AsyncSession
):
    """A rule naming another community is indistinguishable from one that does
    not exist, on every verb."""
    admin, guild = await _seat(session)
    other_admin, other = await _seat(session)
    provider = await _connected(session, other)
    headers = get_auth_headers(admin)

    created = await client.post(
        _base(other.id),
        headers=get_auth_headers(other_admin),
        json={"provider_id": provider.id, "claim_value": "staff"},
    )
    assert created.status_code == 201, created.text
    theirs = created.json()["id"]

    assert (await client.get(_base(guild.id), headers=headers)).json()["rules"] == []
    removed = await client.delete(f"{_base(guild.id)}/{theirs}", headers=headers)
    assert removed.status_code == 404, removed.text


async def test_an_ordinary_admin_reads_but_does_not_write(
    client: AsyncClient, session: AsyncSession
):
    admin, guild = await _seat(session)
    provider = await _connected(session, guild)
    ordinary = await create_user(session)
    await create_guild_membership(
        session, user=ordinary, guild=guild, role=CommunityRole.admin
    )
    headers = get_auth_headers(ordinary)

    assert (await client.get(_base(guild.id), headers=headers)).status_code == 200
    refused = await client.post(
        _base(guild.id),
        headers=headers,
        json={"provider_id": provider.id, "claim_value": "staff"},
    )
    assert refused.status_code == 403, refused.text


async def test_a_member_sees_none_of_it(client: AsyncClient, session: AsyncSession):
    admin, guild = await _seat(session)
    member = await create_user(session)
    await create_guild_membership(
        session, user=member, guild=guild, role=CommunityRole.member
    )
    listed = await client.get(_base(guild.id), headers=get_auth_headers(member))
    assert listed.status_code == 403, listed.text


async def test_the_surface_is_absent_without_the_operators_grant(
    client: AsyncClient, session: AsyncSession
):
    """The same 404 the rest of the guild auth surface gives: the option the
    operator has not granted leaves nothing to find."""
    admin, guild = await _seat(session, auth_options=[])
    listed = await client.get(_base(guild.id), headers=get_auth_headers(admin))
    assert listed.status_code == 404, listed.text
