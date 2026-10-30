"""
Integration tests for guild endpoints.

Tests the guild API endpoints at /api/v1/communities including:
- Listing guilds
- Creating guilds
- Updating guilds
- Deleting guilds
- Reordering guilds
- Creating and managing invites
- Accepting invites
- Leaving a guild
"""

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from sqlmodel import select

from app.services.platform import rules
from app.testing.schema_harness import route_session_to_guild
from app.models.platform.guild import Guild, GuildMembership, CommunityRole
from app.models.platform.notification import Notification, NotificationType
from app.models.platform.user import UserRole, UserStatus
from app.models.platform.user_passkey import UserPasskey
from app.models.tenant.initiative import Initiative, InitiativeMember
from app.models.platform.user import User
from app.testing.factories import (
    create_federated_identity,
    guild_administration,
    create_guild,
    create_guild_membership,
    create_user,
    get_auth_token,
)
from app.testing import drain_notices


async def _just_signed_in(session: AsyncSession, user: User) -> dict[str, str]:
    """Headers naming a session row opened a moment ago — what an account with
    no password to re-check answers a confirmation with."""
    from app.services.auth import sessions as session_service

    issued = await session_service.create_session(
        session, user_id=user.id, amr=["webauthn"], satisfied_providers=[]
    )
    await session.commit()
    return {
        "Authorization": "Bearer "
        + get_auth_token(user, session_id=issued.session.id, amr=["webauthn"])
    }


async def test_an_account_in_no_guild_lists_nothing(
    client: AsyncClient, acting_user
) -> None:
    """The list is memberships, so an account with none gets an empty one."""
    a = await acting_user("member")

    response = await client.get("/api/v1/communities/", headers=a.headers)

    assert response.status_code == 200
    assert response.json() == []


async def test_the_guild_list_is_the_callers_memberships_with_their_roles(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    """Every guild the caller belongs to, each carrying the role they hold
    there — and nothing they do not belong to, whether it is somebody else's or
    nobody's. Which guild is open is the client's business, so no entry says."""
    admin_guild = await create_guild(session, name="Admin Guild")
    a = await acting_user(guild_role=CommunityRole.admin, guild=admin_guild)
    member_guild = await create_guild(session, name="Member Guild")
    await create_guild_membership(
        session, user=a.user, guild=member_guild, role=CommunityRole.member
    )
    await create_guild(session, name="Nobody's Guild")
    elsewhere = await create_guild(session, name="Somebody Else's Guild")
    await acting_user(guild_role=CommunityRole.admin, guild=elsewhere)

    response = await client.get("/api/v1/communities/", headers=a.headers)

    assert response.status_code == 200
    data = response.json()
    assert {entry["name"]: entry["role"] for entry in data} == {
        "Admin Guild": "admin",
        "Member Guild": "member",
    }
    assert "is_active" not in data[0]


#: The administration half of ``CommunityRead`` — caps, plan label, retention
#: window, lifecycle status, sign-in entitlement. Each backs an admin-only
#: surface, so a plain member's entry carries ``None`` for all of them.
ADMIN_ONLY_GUILD_FIELDS = (
    "retention_days",
    "max_storage_bytes",
    "max_users",
    "tier_name",
    "status",
    "auth_options",
)


async def test_list_guilds_administration_fields_are_admin_only(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The guild list serves two audiences from one schema: every member gets
    the guild's identity, their own membership and the roster size; only guild
    admins get the administration fields."""
    admin = await acting_user(guild_role=CommunityRole.admin)
    member = await acting_user(guild_role=CommunityRole.member, guild=admin.guild)

    await guild_administration(
        session,
        admin.guild,
        max_storage_bytes=5_000_000,
        max_users=25,
        tier_name="Bespoke Plan",
        # Both switches, so every administration field has a value to show.
        auth_options=["restrictions", "providers"],
    )

    async def entry(headers: dict[str, str]) -> dict:
        resp = await client.get("/api/v1/communities/", headers=headers)
        assert resp.status_code == 200, resp.text
        return next(g for g in resp.json() if g["id"] == admin.guild.id)

    member_row = await entry(member.headers)
    for field in ADMIN_ONLY_GUILD_FIELDS:
        assert member_row[field] is None, f"{field} must not reach a plain member"
    # What a member does get: the guild itself, their membership, the roster
    # size, and whether content is frozen.
    assert member_row["name"] == admin.guild.name
    assert member_row["role"] == "member"
    assert member_row["member_count"] == 2
    assert member_row["content_read_only"] is False

    admin_row = await entry(admin.headers)
    for field in ADMIN_ONLY_GUILD_FIELDS:
        assert admin_row[field] is not None, f"{field} must reach the guild admin"
    assert admin_row["max_storage_bytes"] == 5_000_000
    assert admin_row["max_users"] == 25
    assert admin_row["tier_name"] == "Bespoke Plan"
    assert admin_row["retention_days"] == 90
    assert admin_row["auth_options"] == ["providers", "restrictions"]


async def test_accepting_an_invite_answers_with_the_member_tier_guild(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Redeeming a code hands back the guild the caller has just joined, in the
    same member-tier payload the list serves: they are not an admin, so the
    administration fields come back ``None``."""
    guild = await create_guild(session, name="Test Guild")
    admin = await acting_user(guild_role=CommunityRole.admin, guild=guild)
    await guild_administration(session, guild, max_users=25, tier_name="Bespoke Plan")

    invite = await client.post(
        f"/api/v1/communities/{guild.id}/invites", headers=admin.headers, json={}
    )
    assert invite.status_code == 201, invite.text

    joiner = await acting_user("member")
    resp = await client.post(
        "/api/v1/communities/invite/accept",
        headers=joiner.headers,
        json={"code": invite.json()["code"]},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == guild.id
    assert body["name"] == "Test Guild"
    assert body["role"] == "member"
    for field in ADMIN_ONLY_GUILD_FIELDS:
        assert body[field] is None, f"{field} must not reach a plain member"


async def test_an_invite_with_no_use_limit_takes_any_number_of_people(
    client: AsyncClient, session: AsyncSession, acting_user
):
    from app.services.platform import guilds as guilds_service

    admin = await acting_user(guild_role=CommunityRole.admin)
    _, code = await guilds_service.create_guild_invite(
        session, guild_id=admin.guild.id, created_by=admin.user.id, max_uses=None
    )
    await session.commit()

    for _ in range(2):
        joiner = await acting_user("member")
        resp = await client.post(
            "/api/v1/communities/invite/accept",
            headers=joiner.headers,
            json={"code": code},
        )
        assert resp.status_code == 200, resp.text


async def test_creating_a_guild_seats_its_creator_and_leaves_the_icon_unset(
    client: AsyncClient, acting_user
):
    """Whoever makes a community holds its seat. An icon is a picture rather
    than a field, so a new guild has none until ``PUT /communities/{id}/icon``."""
    a = await acting_user("member")

    response = await client.post(
        "/api/v1/communities/",
        headers=a.headers,
        json={"name": "New Guild", "description": "A test guild"},
    )

    assert response.status_code == 201, response.text
    data = response.json()
    assert data["name"] == "New Guild"
    assert data["description"] == "A test guild"
    assert data["role"] == "superadmin"
    assert data["icon_url"] is None


async def test_create_guild_requires_name(client: AsyncClient, acting_user):
    """Test that creating a guild requires a name."""
    a = await acting_user("member")

    response = await client.post(
        "/api/v1/communities/",
        headers=a.headers,
        json={"name": "   ", "description": "No name"},
    )

    assert response.status_code == 422


# --- free communities are billing's ------------------------------------------


@pytest.fixture
def billed(monkeypatch):
    """A deployment with a billing service behind it."""
    from app.core import config as config_module

    monkeypatch.setattr(config_module.settings, "BILLING_PUBLIC_KEY_PEM", "a-key")
    monkeypatch.setattr(
        config_module.settings, "BILLING_STATEMENT_PUBLIC_KEY_PEM", "a-statement-key"
    )


async def test_a_billed_deployment_refuses_no_second_community(
    client: AsyncClient, acting_user, billed
):
    """How many free communities a person may hold is billing's to say, from
    its catalog, when it hears a community was created: an enterprise contract
    may have no such limit, and one admin setting up many is normal. Here the
    only limit is the daily allowance below."""
    a = await acting_user("member")
    for name in ("My notebook", "One more"):
        created = await client.post(
            "/api/v1/communities/", headers=a.headers, json={"name": name}
        )
        assert created.status_code == 201, created.text


async def test_an_account_creates_only_its_daily_allowance_of_guilds(
    client: AsyncClient, session: AsyncSession, acting_user, monkeypatch
):
    """Past the allowance the request is refused before anything is made, and
    deleting a community does not give the allowance back; the staff who stand
    communities up for others are not counted."""
    from app.services.platform import guilds as guilds_service

    await rules.put(session, "community_creation_daily_limit", 1)
    await session.commit()
    a = await acting_user("member")
    first = await client.post(
        "/api/v1/communities/", headers=a.headers, json={"name": "First"}
    )
    assert first.status_code == 201, first.text
    await guilds_service.soft_delete_guild(
        session, await session.get(Guild, first.json()["id"])
    )
    await session.commit()

    second = await client.post(
        "/api/v1/communities/", headers=a.headers, json={"name": "Second"}
    )
    assert second.status_code == 429
    assert second.json()["detail"] == "COMMUNITY_CREATION_LIMIT_REACHED"
    made = (await session.exec(select(Guild).where(Guild.name == "Second"))).all()
    assert made == []

    staff = await acting_user(UserRole.owner)
    for name in ("Staff one", "Staff two"):
        created = await client.post(
            "/api/v1/communities/", headers=staff.headers, json={"name": name}
        )
        assert created.status_code == 201, created.text


async def test_staff_standing_a_community_up_for_somebody_are_not_refused(
    client: AsyncClient, acting_user, billed
):
    """An enterprise onboarding is a community made for a customer who is about
    to be invoiced, not a second free notebook — and the person it is for may
    well already have one of those."""
    staff = await acting_user(UserRole.owner)
    customer = await acting_user("member")
    theirs = await client.post(
        "/api/v1/communities/",
        headers=customer.headers,
        json={"name": "Their notebook"},
    )
    assert theirs.status_code == 201, theirs.text

    for_them = await client.post(
        "/api/v1/communities/",
        headers=staff.headers,
        json={"name": "Acme", "owner_user_id": customer.user.id},
    )
    assert for_them.status_code == 201, for_them.text


# --- creating a guild for another account ----------------------------------


@pytest.mark.parametrize(
    "billing_url", [None, "https://billing.example.com"], ids=["unbilled", "billed"]
)
async def test_creating_a_guild_for_another_account_seats_them_and_records_both(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    monkeypatch,
    billing_url: str | None,
):
    """The named account holds the seat and the creator holds nothing in it.
    Who did it and who it was for are both in the row, not only in a log line.
    Where billing sets plans, the owner — not the creator — is welcomed and
    invited to set one up; elsewhere nobody is.
    """
    from app.core.config import settings as app_settings
    from app.services.platform import email_outbox

    monkeypatch.setattr(app_settings, "BILLING_URL", billing_url)
    letters: list = []

    async def _letter(_session, recipient, *, pieces, **_kwargs):
        letters.append((recipient.id, pieces))
        return True

    monkeypatch.setattr(email_outbox, "enqueue", _letter)
    staff = await acting_user(UserRole.owner)
    customer = await acting_user("member")

    response = await client.post(
        "/api/v1/communities/",
        headers=staff.headers,
        json={"name": "Acme", "owner_user_id": customer.user.id},
    )

    assert response.status_code == 201, response.text
    guild = await session.get(Guild, response.json()["id"])
    assert guild.created_by == staff.user.id
    memberships = (
        await session.exec(
            select(GuildMembership).where(GuildMembership.guild_id == guild.id)
        )
    ).all()
    assert [(m.user_id, m.role) for m in memberships] == [
        (customer.user.id, CommunityRole.superadmin)
    ]

    await drain_notices()
    welcomed = (
        await session.exec(
            select(Notification).where(
                Notification.type == NotificationType.community_welcome
            )
        )
    ).all()
    if billing_url is None:
        assert welcomed == [] and letters == []
        return
    (line,) = welcomed
    assert line.user_id == customer.user.id
    assert line.data == {
        "community": "Acme",
        "community_id": guild.id,
        "target_path": "/settings/usage",
    }
    ((recipient_id, pieces),) = letters
    assert recipient_id == customer.user.id
    assert pieces.subject == "Acme is ready"
    assert pieces.link.endswith(f"/c/{guild.id}/billing?page=upgrade")


@pytest.mark.parametrize(
    "for_another_account",
    [False, True],
    ids=["for themselves", "for another account"],
)
async def test_a_new_guild_is_created_with_no_initiatives(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    for_another_account: bool,
):
    """A new guild holds no initiative at all, and so nobody inside its content
    — the creator of a guild made for somebody else included. Naming a body of
    work is the owner's first decision, and a seeded "Default Initiative"
    answered it for them; the guild home offers them the empty state instead."""
    creator = await acting_user(
        UserRole.owner if for_another_account else UserRole.member
    )
    body: dict = {"name": "Acme"}
    if for_another_account:
        body["owner_user_id"] = (await acting_user("member")).user.id

    response = await client.post(
        "/api/v1/communities/", headers=creator.headers, json=body
    )
    assert response.status_code == 201, response.text

    await route_session_to_guild(session, response.json()["id"])
    assert (await session.exec(select(Initiative))).all() == []
    assert (await session.exec(select(InitiativeMember))).all() == []


async def test_an_ordinary_user_cannot_name_another_owner(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Refused, not silently ignored: the guild is not created at all."""
    a = await acting_user("member")
    other = await acting_user("member")

    response = await client.post(
        "/api/v1/communities/",
        headers=a.headers,
        json={"name": "Not yours", "owner_user_id": other.user.id},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "COMMUNITY_OWNER_REQUIRES_CAPABILITY"
    assert (
        await session.exec(select(Guild).where(Guild.name == "Not yours"))
    ).all() == []


async def test_naming_yourself_needs_no_capability(client: AsyncClient, acting_user):
    """The field is about handing a guild to someone else; spelling out your
    own id is the ordinary path."""
    a = await acting_user("member")

    response = await client.post(
        "/api/v1/communities/",
        headers=a.headers,
        json={"name": "Mine", "owner_user_id": a.user.id},
    )

    assert response.status_code == 201, response.text
    assert response.json()["role"] == "superadmin"


@pytest.mark.parametrize(
    "owner_id_of",
    ["missing", "deactivated"],
    ids=["unknown user", "deactivated user"],
)
async def test_an_unusable_owner_is_refused(
    client: AsyncClient, session: AsyncSession, acting_user, owner_id_of: str
):
    """This never creates an account, and never hands a guild to one that
    cannot sign in to run it."""
    staff = await acting_user(UserRole.owner)
    if owner_id_of == "missing":
        owner_id = 999_999_999
    else:
        deactivated = await create_user(session, status=UserStatus.deactivated)
        owner_id = deactivated.id

    response = await client.post(
        "/api/v1/communities/",
        headers=staff.headers,
        json={"name": "Acme", "owner_user_id": owner_id},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "COMMUNITY_OWNER_NOT_FOUND"


async def test_update_guild_as_admin(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test that admin can update guild."""
    guild = await create_guild(session, name="Old Name", description="Old description")
    admin = await acting_user(guild_role=CommunityRole.admin, guild=guild)

    response = await client.patch(
        f"/api/v1/communities/{guild.id}",
        headers=admin.headers,
        json={"name": "New Name", "description": "New description"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "New Name"
    assert data["description"] == "New description"


async def test_an_ordinary_admin_cannot_delete_the_community(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Deleting a community is the seat's, not an admin's. It is the one
    action an admin could not undo and could not have undone for them."""
    guild = await create_guild(session, name="Not Yours To End")
    admin = await acting_user(guild_role=CommunityRole.admin, guild=guild)

    refused = await client.request(
        "DELETE",
        f"/api/v1/communities/{guild.id}",
        headers=admin.headers,
        json={
            "password": "testpassword123",
            "confirmation_text": "DELETE NOT YOURS TO END",
        },
    )

    assert refused.status_code == 403, refused.text


@pytest.mark.parametrize(
    "password,confirmation,expected_status,expected_detail",
    [
        pytest.param(
            "testpassword123",
            "DELETE COMMUNITY TO DELETE",
            204,
            None,
            id="the password and the phrase",
        ),
        pytest.param(
            "wrongpassword",
            "DELETE COMMUNITY TO DELETE",
            400,
            "COMMUNITY_INVALID_PASSWORD",
            id="a password that does not match",
        ),
        pytest.param(
            "testpassword123",
            "To Delete",
            400,
            "COMMUNITY_CONFIRMATION_MISMATCH",
            id="a phrase that does not match",
        ),
    ],
)
async def test_deleting_a_guild_asks_for_the_password_and_the_phrase(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    password: str,
    confirmation: str,
    expected_status: int,
    expected_detail: str | None,
):
    """Both answers have to be right. A refusal is 400 rather than 401, which
    is the status the SPA reads as a session ending."""
    guild = await create_guild(session, name="To Delete")
    admin = await acting_user(guild_role=CommunityRole.superadmin, guild=guild)

    response = await client.request(
        "DELETE",
        f"/api/v1/communities/{guild.id}",
        headers=admin.headers,
        json={"password": password, "confirmation_text": confirmation},
    )

    assert response.status_code == expected_status, response.text
    if expected_detail is not None:
        assert response.json()["detail"] == expected_detail


@pytest.mark.parametrize(
    "credential", ["federated identity", "passkey"], ids=["SSO", "passkey"]
)
async def test_an_admin_holding_no_password_confirms_with_a_recent_sign_in(
    client: AsyncClient, session: AsyncSession, acting_user, credential: str
):
    """An account that signs in another way holds no password for the gate to
    ask for, so the phrase and a sign-in from a moment ago are the whole
    confirmation."""
    guild = await create_guild(session, name="To Delete")
    admin = await acting_user(
        guild_role=CommunityRole.superadmin, guild=guild, hashed_password=None
    )
    if credential == "federated identity":
        await create_federated_identity(session, admin.user, subject="sso-123")
    else:
        session.add(
            UserPasskey(
                user_id=admin.user.id,
                credential_id=b"delete-guild-key",
                public_key=b"public-key-bytes",
                rp_id="localhost",
                sign_count=0,
                transports=["internal"],
                name="Laptop",
            )
        )
        await session.commit()

    response = await client.request(
        "DELETE",
        f"/api/v1/communities/{guild.id}",
        headers=await _just_signed_in(session, admin.user),
        json={"confirmation_text": "DELETE COMMUNITY TO DELETE"},
    )

    assert response.status_code == 204, response.text


async def test_delete_guild_linked_admin_holding_a_password_is_asked_for_it(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """An identity link is not the question: an account can hold both, and one
    that holds a password confirms with it."""
    guild = await create_guild(session, name="To Delete")
    admin = await acting_user(guild_role=CommunityRole.superadmin, guild=guild)
    await create_federated_identity(session, admin.user, subject="linked-admin-1")

    response = await client.request(
        "DELETE",
        f"/api/v1/communities/{guild.id}",
        headers=admin.headers,
        json={
            "password": "wrongpassword",
            "confirmation_text": "DELETE COMMUNITY TO DELETE",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "COMMUNITY_INVALID_PASSWORD"


@pytest.mark.parametrize(
    "role", ["member", "support", "moderator", "operator", "owner"]
)
async def test_reorder_guilds(
    client: AsyncClient, session: AsyncSession, acting_user, role: str
):
    """EVERY platform tier can reorder their own guilds in personal mode.

    The request runs as ``platform_<role>`` with no guild context, and the write
    is an ordinary UPDATE of the caller's own ``position`` values —
    ``guild_memberships_update`` matches on ``user_id`` (migration 0266), so no
    role relies on a standing all-guild bypass. Parametrized across the whole
    ladder so a member (lowest) and an owner (highest) are both proven to work
    the same way, and run through ``client`` rather than the superuser session
    so the policy is the thing being exercised.
    """
    a = await acting_user(role, guild_role=CommunityRole.member)
    guild2 = await create_guild(session, name="Guild 2")
    guild3 = await create_guild(session, name="Guild 3")
    for guild in (guild2, guild3):
        await create_guild_membership(session, user=a.user, guild=guild)

    wanted = [guild3.id, a.guild.id, guild2.id]
    response = await client.put(
        "/api/v1/communities/order", headers=a.headers, json={"community_ids": wanted}
    )

    assert response.status_code == 204

    listing = await client.get("/api/v1/communities/", headers=a.headers)
    assert [g["id"] for g in listing.json()] == wanted


async def test_a_member_names_themselves_in_one_community(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The member's own row, on the routed session: set, read back on the
    community, and cleared by a blank. Another community keeps no name."""
    a = await acting_user(guild_role=CommunityRole.member)
    other = await create_guild(session, name="Elsewhere")
    await create_guild_membership(session, user=a.user, guild=other)
    route = f"/api/v1/communities/{a.guild.id}/membership/display-name"

    async def names() -> dict[int, str | None]:
        listing = await client.get("/api/v1/communities/", headers=a.headers)
        return {g["id"]: g["display_name"] for g in listing.json()}

    named = await client.put(route, headers=a.headers, json={"display_name": " Ana "})
    assert named.status_code == 204, named.text
    assert await names() == {a.guild.id: "Ana", other.id: None}

    cleared = await client.put(route, headers=a.headers, json={"display_name": "  "})
    assert cleared.status_code == 204, cleared.text
    assert await names() == {a.guild.id: None, other.id: None}


async def test_an_admin_names_a_member(
    client: AsyncClient, session: AsyncSession, acting_user
):
    admin = await acting_user(guild_role=CommunityRole.admin)
    member = await acting_user(guild_role=CommunityRole.member, guild=admin.guild)
    route = (
        f"/api/v1/communities/{admin.guild.id}/members/{member.user.id}/display-name"
    )

    named = await client.put(route, headers=admin.headers, json={"display_name": "Bo"})
    assert named.status_code == 204, named.text
    roster = await client.get(
        f"/api/v1/c/{admin.guild.id}/users/", headers=admin.headers
    )
    rows = {row["id"]: row for row in roster.json()["items"]}
    assert rows[member.user.id]["display_name"] == "Bo"

    stranger = await create_user(session)
    missing = await client.put(
        f"/api/v1/communities/{admin.guild.id}/members/{stranger.id}/display-name",
        headers=admin.headers,
        json={"display_name": "Nobody"},
    )
    assert missing.status_code == 404, missing.text


async def test_create_guild_invite_as_admin(client: AsyncClient, acting_user):
    """An admin mints an invite, with a use count and an expiry it chooses."""
    admin = await acting_user(guild_role=CommunityRole.admin)

    response = await client.post(
        f"/api/v1/communities/{admin.guild.id}/invites",
        headers=admin.headers,
        json={
            "max_uses": 5,
            "invitee_email": "invitee@example.com",
            "expires_at": "2025-12-31T23:59:59Z",
        },
    )

    assert response.status_code == 201, response.text
    data = response.json()
    assert data["community_id"] == admin.guild.id
    assert data["max_uses"] == 5
    assert data["uses"] == 0
    assert len(data["code"]) == 22
    assert "2025-12-31" in data["expires_at"]
    # Read back masked: whoever typed the address already has it, and a
    # guild's other admins never did. Redemption still matches the whole
    # address, from the ciphertext. The domain is elided too — a bare domain
    # narrows an address to one organisation.
    assert data["invitee_email"] == "i***e@e***m"


@pytest.mark.parametrize(
    "max_users,extra_members,expected_status",
    [
        pytest.param(1, 0, 403, id="every seat taken"),
        pytest.param(2, 0, 201, id="a seat still free"),
        pytest.param(None, 3, 201, id="no cap at all"),
    ],
)
async def test_minting_an_invite_respects_the_seat_cap(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    max_users: int | None,
    extra_members: int,
    expected_status: int,
):
    """A guild whose membership has reached ``max_users`` mints no new invite;
    a free seat leaves minting untouched, and a ``NULL`` cap is unlimited
    however many members the guild already has."""
    guild = await create_guild(session, max_users=max_users)
    admin = await acting_user(guild_role=CommunityRole.admin, guild=guild)
    for _ in range(extra_members):
        await acting_user(guild_role=CommunityRole.member, guild=guild)

    response = await client.post(
        f"/api/v1/communities/{guild.id}/invites",
        headers=admin.headers,
        json={"max_uses": 1},
    )

    assert response.status_code == expected_status, response.text
    if expected_status == 403:
        assert response.json()["detail"] == "COMMUNITY_USER_LIMIT_REACHED"


async def test_an_admin_lists_and_revokes_the_guilds_invites(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The two halves of running a guild's invites: see them all, drop one."""
    from app.services.platform import guilds as guild_service

    admin = await acting_user(guild_role=CommunityRole.admin)
    invites = [
        (
            await guild_service.create_guild_invite(
                session,
                guild_id=admin.guild.id,
                created_by=admin.user.id,
                max_uses=max_uses,
            )
        )[0]
        for max_uses in (1, 2)
    ]
    await session.commit()
    url = f"/api/v1/communities/{admin.guild.id}/invites"

    listed = await client.get(url, headers=admin.headers)
    assert listed.status_code == 200
    assert {row["id"] for row in listed.json()} == {i.id for i in invites}

    revoked = await client.delete(f"{url}/{invites[0].id}", headers=admin.headers)
    assert revoked.status_code == 204

    remaining = await client.get(url, headers=admin.headers)
    assert [row["id"] for row in remaining.json()] == [invites[1].id]


async def test_get_invite_status_valid(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test getting status of a valid invite."""
    from app.services.platform import guilds as guild_service

    guild = await create_guild(session, name="Test Guild")
    admin = await acting_user(guild_role=CommunityRole.admin, guild=guild)
    invite, invite_code = await guild_service.create_guild_invite(
        session, guild_id=guild.id, created_by=admin.user.id, max_uses=5
    )
    await session.commit()

    response = await client.get(f"/api/v1/communities/invite/{invite_code}")

    assert response.status_code == 200
    data = response.json()
    assert data["code"] == invite_code
    assert data["community_id"] == guild.id
    assert data["community_name"] == "Test Guild"
    assert data["is_valid"] is True
    assert data["max_uses"] == 5
    assert data["uses"] == 0


async def test_get_invite_status_invalid_code(client: AsyncClient):
    """Test getting status of invalid invite code."""
    response = await client.get("/api/v1/communities/invite/invalidcode123")

    assert response.status_code == 200
    data = response.json()
    assert data["is_valid"] is False
    assert data["reason"] is not None


async def test_accept_invite_blocked_when_guild_full(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Accepting an invite into a guild at its user cap returns 403."""
    from app.services.platform import guilds as guild_service

    guild = await create_guild(session, name="Full Guild", max_users=1)
    creator = await create_user(session)
    invitee = await acting_user("member")

    # Minted while the seat is still free, redeemed after it is taken — minting
    # itself is capacity-gated, so the order here is the scenario.
    invite, invite_code = await guild_service.create_guild_invite(
        session, guild_id=guild.id, created_by=creator.id, max_uses=5
    )
    await acting_user(guild_role=CommunityRole.member, guild=guild)
    await session.commit()

    response = await client.post(
        "/api/v1/communities/invite/accept",
        headers=invitee.headers,
        json={"code": invite_code},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "COMMUNITY_USER_LIMIT_REACHED"


@pytest.mark.parametrize(
    "kind,expected_detail",
    [
        pytest.param("unknown", "INVITE_NOT_FOUND", id="a code nobody minted"),
        pytest.param("expired", "INVITE_EXPIRED_OR_USED", id="a code past its date"),
    ],
)
async def test_an_invite_that_cannot_be_redeemed_is_refused(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    kind: str,
    expected_detail: str,
):
    """Both refusals are 400, each naming which one it was."""
    from datetime import datetime, timedelta, timezone
    from app.services.platform import guilds as guild_service

    invitee = await acting_user("member")
    if kind == "unknown":
        code = "invalidcode123"
    else:
        admin = await acting_user(guild_role=CommunityRole.admin)
        invite, invite_code = await guild_service.create_guild_invite(
            session,
            guild_id=admin.guild.id,
            created_by=admin.user.id,
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        await session.commit()
        code = invite_code

    response = await client.post(
        "/api/v1/communities/invite/accept",
        headers=invitee.headers,
        json={"code": code},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == expected_detail


# --- who each guild-router surface answers --------------------------------


#: Surfaces only a guild's own administrators reach. The body is the one a
#: well-formed request carries, so the status is the gate's answer rather than
#: the schema's.
ADMIN_ONLY_ROUTES = (
    ("PATCH", "/api/v1/communities/{guild}", {"name": "Renamed"}),
    (
        "DELETE",
        "/api/v1/communities/{guild}",
        {"password": "testpassword123", "confirmation_text": "DELETE COMMUNITY X"},
    ),
    ("POST", "/api/v1/communities/{guild}/invites", {"max_uses": 1}),
    ("GET", "/api/v1/communities/{guild}/invites", None),
    ("DELETE", "/api/v1/communities/{guild}/invites/{invite}", None),
    ("POST", "/api/v1/communities/{guild}/billing/handoff", None),
    (
        "PUT",
        "/api/v1/communities/{guild}/members/{admin}/display-name",
        {"display_name": "Renamed"},
    ),
)

#: Surfaces any signed-in account may call, listed here for the one caller they
#: all turn away.
SIGNED_IN_ROUTES = (
    ("GET", "/api/v1/communities/", None),
    ("POST", "/api/v1/communities/", {"name": "Fresh"}),
    ("PUT", "/api/v1/communities/order", {"community_ids": []}),
    ("POST", "/api/v1/communities/invite/accept", {"code": "notarealcode000000"}),
    ("GET", "/api/v1/communities/{guild}/leave/eligibility", None),
    ("DELETE", "/api/v1/communities/{guild}/leave", None),
    (
        "PUT",
        "/api/v1/communities/{guild}/membership/display-name",
        {"display_name": "Me"},
    ),
)

#: Leaving is about a membership, so an account holding none in this guild is
#: told there is none rather than refused.
MEMBERSHIP_ROUTES = (
    ("GET", "/api/v1/communities/{guild}/leave/eligibility", None),
    ("DELETE", "/api/v1/communities/{guild}/leave", None),
)


def _gate_cases():
    """(method, path, body, actor_kind, expected_status) for every surface."""
    for method, path, body in ADMIN_ONLY_ROUTES:
        for actor_kind, expected in (
            ("member", 403),
            ("stranger", 403),
            ("anonymous", 401),
        ):
            yield pytest.param(
                method,
                path,
                body,
                actor_kind,
                expected,
                id=f"{method} {path} {actor_kind}",
            )
    for method, path, body in SIGNED_IN_ROUTES:
        yield pytest.param(
            method, path, body, "anonymous", 401, id=f"{method} {path} anonymous"
        )
    for method, path, body in MEMBERSHIP_ROUTES:
        yield pytest.param(
            method, path, body, "stranger", 404, id=f"{method} {path} stranger"
        )


@pytest.fixture
async def guild_gate_world(session: AsyncSession, acting_user, monkeypatch):
    """One guild with an invite in it, and the three callers who do not
    administer it: a plain member of it, an admin of a different guild, and
    nobody at all. ``BILLING_URL`` is configured so the billing surface is
    reached rather than answering "no portal here"."""
    from app.core.config import settings as app_settings
    from app.services.platform import guilds as guild_service

    monkeypatch.setattr(app_settings, "BILLING_URL", "https://billing.example.com")
    admin = await acting_user(guild_role=CommunityRole.admin)
    member = await acting_user(guild_role=CommunityRole.member, guild=admin.guild)
    stranger = await acting_user(guild_role=CommunityRole.admin)
    invite, invite_code = await guild_service.create_guild_invite(
        session, guild_id=admin.guild.id, created_by=admin.user.id
    )
    await session.commit()
    return {
        "guild": admin.guild.id,
        "invite": invite.id,
        "admin": admin.user.id,
        "member": member.headers,
        "stranger": stranger.headers,
        "anonymous": None,
    }


@pytest.mark.parametrize(
    "method,path,body,actor_kind,expected_status", list(_gate_cases())
)
async def test_each_guild_surface_answers_by_what_the_caller_holds(
    client: AsyncClient,
    guild_gate_world,
    method: str,
    path: str,
    body: dict | None,
    actor_kind: str,
    expected_status: int,
):
    """Every guild-router surface these tests reach, against every caller who
    is not the guild's administrator: administration is refused, an unsigned
    request is unauthenticated, and leaving a guild you are not in is missing.
    """
    response = await client.request(
        method,
        path.format(
            guild=guild_gate_world["guild"],
            invite=guild_gate_world["invite"],
            admin=guild_gate_world["admin"],
        ),
        headers=guild_gate_world[actor_kind],
        json=body,
    )

    assert response.status_code == expected_status, response.text


# --- Billing-portal handoff endpoint --------------------------------------


@pytest.mark.parametrize(
    "billing_url,clear_signing_key,expected_status,expected_detail",
    [
        pytest.param(
            None,
            False,
            404,
            "BILLING_PORTAL_NOT_CONFIGURED",
            id="no portal configured",
        ),
        pytest.param(
            "https://billing.example.com",
            True,
            503,
            "BILLING_PORTAL_SIGNING_NOT_CONFIGURED",
            id="a portal with nothing to sign with",
        ),
    ],
)
async def test_the_billing_handoff_needs_a_portal_and_a_signing_key(
    client: AsyncClient,
    acting_user,
    monkeypatch,
    billing_url: str | None,
    clear_signing_key: bool,
    expected_status: int,
    expected_detail: str,
):
    """Each half of the configuration is reported as its own answer."""
    from app.core.config import settings as app_settings

    monkeypatch.setattr(app_settings, "BILLING_URL", billing_url)
    if clear_signing_key:
        monkeypatch.setattr(app_settings, "HANDOFF_SIGNING_PRIVATE_KEY_PEM", None)
    seat = await acting_user(guild_role=CommunityRole.superadmin)

    response = await client.post(
        f"/api/v1/communities/{seat.guild.id}/billing/handoff", headers=seat.headers
    )

    assert response.status_code == expected_status, response.text
    assert response.json()["detail"] == expected_detail


async def test_guild_billing_handoff_succeeds_for_admin(
    client: AsyncClient, acting_user, monkeypatch, handoff_signing_key
):
    """Admin gets an EdDSA token with the billing-portal audience and role."""
    from app.core.config import settings as app_settings
    from app.core.security import BILLING_PORTAL_AUDIENCE
    import jwt

    monkeypatch.setattr(app_settings, "BILLING_URL", "https://billing.example.com")
    seat = await acting_user(guild_role=CommunityRole.superadmin)

    response = await client.post(
        f"/api/v1/communities/{seat.guild.id}/billing/handoff", headers=seat.headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["expires_in_seconds"] > 0

    assert jwt.get_unverified_header(body["handoff_token"])["alg"] == "EdDSA"
    payload = jwt.decode(body["handoff_token"], options={"verify_signature": False})
    assert payload["aud"] == BILLING_PORTAL_AUDIENCE
    assert payload["iss"] == "initiative"
    assert payload["community_role"] == "admin"
    # The pair is named by reference and by nothing else, `sub` included.
    assert payload["sub"] == payload["user_ref"]
    assert payload["user_ref"].startswith("ubil_")
    assert payload["community_ref"].startswith("gbil_")
    assert "guild_id" not in payload


# --- Leave guild: the seat a community keeps ------------------------------


@pytest.mark.parametrize(
    "leaver_role,other_roles,can_leave,expected_status,expected_detail",
    [
        pytest.param(
            CommunityRole.admin,
            (CommunityRole.superadmin,),
            True,
            204,
            None,
            id="an ordinary admin, the seat still held",
        ),
        pytest.param(
            CommunityRole.superadmin,
            (CommunityRole.member,),
            False,
            400,
            "CANNOT_VACATE_LAST_SUPERADMIN",
            id="the only seat, with somebody to strand",
        ),
        pytest.param(
            CommunityRole.superadmin,
            (),
            True,
            204,
            None,
            id="the only member there is",
        ),
    ],
)
async def test_a_departure_is_counted_against_the_communitys_last_seat(
    client: AsyncClient,
    acting_user,
    leaver_role: CommunityRole,
    other_roles: tuple[CommunityRole, ...],
    can_leave: bool,
    expected_status: int,
    expected_detail: str | None,
):
    """Holding a community's only superadmin seat is the one thing that stops a
    departure, and only while somebody is left behind. Being its last *admin*
    stops nobody — the seat is still there to appoint another. The eligibility
    read answers the same question ahead of time."""
    leaver = await acting_user(guild_role=leaver_role)
    for role in other_roles:
        await acting_user(guild_role=role, guild=leaver.guild)

    eligibility = await client.get(
        f"/api/v1/communities/{leaver.guild.id}/leave/eligibility",
        headers=leaver.headers,
    )
    assert eligibility.status_code == 200, eligibility.text
    assert eligibility.json() == {
        "can_leave": can_leave,
        "is_last_superadmin": not can_leave,
    }

    response = await client.delete(
        f"/api/v1/communities/{leaver.guild.id}/leave", headers=leaver.headers
    )
    assert response.status_code == expected_status, response.text
    if expected_detail is not None:
        assert response.json()["detail"] == expected_detail


async def test_a_second_seat_frees_the_first(client: AsyncClient, acting_user):
    """Two seats, so either may go; the one left behind then stays."""
    first = await acting_user(guild_role=CommunityRole.superadmin)
    second = await acting_user(guild_role=CommunityRole.superadmin, guild=first.guild)
    await acting_user(guild_role=CommunityRole.member, guild=first.guild)

    left = await client.delete(
        f"/api/v1/communities/{first.guild.id}/leave", headers=second.headers
    )
    assert left.status_code == 204, left.text

    refused = await client.delete(
        f"/api/v1/communities/{first.guild.id}/leave", headers=first.headers
    )
    assert refused.status_code == 400
    assert refused.json()["detail"] == "CANNOT_VACATE_LAST_SUPERADMIN"


async def test_leaving_takes_the_lock_before_it_counts_anyone(
    client: AsyncClient, acting_user, monkeypatch
):
    """A departure's guard asks how many seats a community has left, and that
    answer has to still be true when the departure is written. So the lock
    comes first.

    Pinned as an order because that is what the invariant is.
    """
    from app.services.platform import guilds as guilds_service

    order: list[str] = []
    real_lock = guilds_service.lock_guild_seats
    real_seat = guilds_service.stranded_seats

    async def record(name, fn, *args, **kwargs):
        order.append(name)
        return await fn(*args, **kwargs)

    monkeypatch.setattr(
        guilds_service,
        "lock_guild_seats",
        lambda *a, **k: record("lock", real_lock, *a, **k),
    )
    monkeypatch.setattr(
        guilds_service,
        "stranded_seats",
        lambda *a, **k: record("last seat", real_seat, *a, **k),
    )

    seat = await acting_user(guild_role=CommunityRole.superadmin)
    leaving = await acting_user(guild_role=CommunityRole.admin, guild=seat.guild)

    response = await client.delete(
        f"/api/v1/communities/{seat.guild.id}/leave", headers=leaving.headers
    )
    assert response.status_code == 204, response.text
    assert order == ["lock", "last seat"]
