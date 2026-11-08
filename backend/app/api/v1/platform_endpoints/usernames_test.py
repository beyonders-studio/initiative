"""Handles, end to end: picking one, being given one, and finding someone by it.

Also the two rules that decide what a guild-scoped payload says about a person:
an address never appears in one, and a name appears only where the person set
one in that guild.
"""

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import CommunityRole
from app.testing import create_guild, create_guild_membership, create_user
from app.testing.factories import get_auth_headers

REGISTRATION = {
    "email": "handle-new@example.com",
    "password": "a-long-enough-password-123",
    "username": "newcomer",
}


class TestRegistration:
    async def test_a_new_account_gets_the_name_it_typed(self, client: AsyncClient):
        response = await client.post("/api/v1/auth/register", json=REGISTRATION)

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["username"] == "newcomer"
        assert 0 <= body["discriminator"] <= 9999
        # Typed into a form, so it is chosen — this account never meets the
        # pick screen.
        assert body["username_chosen"] is True

    async def test_the_same_name_twice(self, client: AsyncClient):
        first = await client.post("/api/v1/auth/register", json=REGISTRATION)
        second = await client.post(
            "/api/v1/auth/register",
            json={**REGISTRATION, "email": "handle-other@example.com"},
        )

        assert first.status_code == 201
        assert second.status_code == 201, second.text
        assert first.json()["username"] == second.json()["username"] == "newcomer"
        assert first.json()["discriminator"] != second.json()["discriminator"]

    @pytest.mark.parametrize(
        ("username", "code"),
        [
            ("ab", "USERNAME_TOO_SHORT"),
            ("admin", "USERNAME_RESERVED"),
            ("has spaces", "USERNAME_INVALID_CHARACTERS"),
        ],
    )
    async def test_refuses_a_name_it_cannot_store(
        self, client: AsyncClient, username, code
    ):
        response = await client.post(
            "/api/v1/auth/register", json={**REGISTRATION, "username": username}
        )

        assert response.status_code == 422
        assert response.json()["detail"] == code

    async def test_a_name_is_required(self, client: AsyncClient):
        payload = {k: v for k, v in REGISTRATION.items() if k != "username"}
        response = await client.post("/api/v1/auth/register", json=payload)

        assert response.status_code == 422


class TestAvailability:
    async def test_the_number_shown_is_the_one_the_account_gets(
        self, client: AsyncClient
    ):
        """The check shows a number and signs it; registering with that offer
        keeps it, and the offer names that name only."""
        from app.core.security import read_handle_offer

        response = await client.get(
            "/api/v1/auth/username-available", params={"username": "UnclaimedName"}
        )
        shown = response.json()
        assert shown["available"] is True
        assert 0 <= shown["discriminator"] <= 9999
        assert read_handle_offer(shown["offer"], "someoneelse") is None

        registered = await client.post(
            "/api/v1/auth/register",
            json={
                **REGISTRATION,
                "username": "unclaimedname",
                "username_offer": shown["offer"],
            },
        )
        assert registered.status_code == 201
        assert registered.json()["discriminator"] == shown["discriminator"]

    async def test_a_reserved_name_says_why(self, client: AsyncClient):
        response = await client.get(
            "/api/v1/auth/username-available", params={"username": "admin"}
        )

        assert response.json() == {
            "available": False,
            "reason": "USERNAME_RESERVED",
            "discriminator": None,
            "offer": None,
        }

    async def test_a_name_someone_holds_is_still_available(
        self, client: AsyncClient, session: AsyncSession
    ):
        """The number is what resolves contention, so a name in use is not a
        name that is taken."""
        await create_user(session, username="popular", discriminator=1)

        response = await client.get(
            "/api/v1/auth/username-available", params={"username": "popular"}
        )

        assert response.json()["available"] is True

    async def test_suggestions_are_names_nobody_holds(
        self, client: AsyncClient, session: AsyncSession
    ):
        """Suggestions start from what was typed, and skip a name in use."""
        await create_user(session, username="popular", discriminator=1)

        response = await client.get(
            "/api/v1/auth/username-suggestions", params={"seed": "Popular"}
        )

        suggestions = response.json()["suggestions"]
        assert len(suggestions) == 4
        assert "popular" not in suggestions
        assert suggestions[0].startswith("popular-")

        fresh = await client.get(
            "/api/v1/auth/username-suggestions", params={"seed": "Quiet Otter"}
        )
        assert fresh.json()["suggestions"][0] == "quiet-otter"

        # A long name that is held still yields alternatives built on it.
        long_name = "a-rather-long-handle-for-a-test"
        await create_user(session, username=long_name, discriminator=1)
        long = await client.get(
            "/api/v1/auth/username-suggestions", params={"seed": long_name}
        )
        built_on_it = [
            s for s in long.json()["suggestions"] if s.startswith("a-rather")
        ]
        assert built_on_it
        assert all(len(s) <= 32 and s != long_name for s in built_on_it)


class TestClaimingAHandle:
    async def test_an_assigned_handle_can_be_picked_once(
        self, client: AsyncClient, session: AsyncSession
    ):
        user = await create_user(session, username_chosen=False)

        response = await client.patch(
            "/api/v1/me/username",
            headers=get_auth_headers(user),
            json={"username": "mine-now"},
        )

        assert response.status_code == 200, response.text
        assert response.json()["username"] == "mine-now"
        assert response.json()["username_chosen"] is True

    async def test_a_chosen_handle_is_not_changed_again(
        self, client: AsyncClient, session: AsyncSession
    ):
        user = await create_user(session, username_chosen=True)

        response = await client.patch(
            "/api/v1/me/username",
            headers=get_auth_headers(user),
            json={"username": "second-thoughts"},
        )

        assert response.status_code == 409
        assert response.json()["detail"] == "USERNAME_ALREADY_CHOSEN"

    async def test_the_picked_name_is_validated(
        self, client: AsyncClient, session: AsyncSession
    ):
        user = await create_user(session, username_chosen=False)

        response = await client.patch(
            "/api/v1/me/username",
            headers=get_auth_headers(user),
            json={"username": "owner"},
        )

        assert response.status_code == 422
        assert response.json()["detail"] == "USERNAME_RESERVED"


class TestWhatAGuildPayloadSays:
    @pytest.fixture
    async def guild_with_member(self, session):
        admin = await create_user(session)
        guild = await create_guild(session, creator=admin)
        await create_guild_membership(
            session, user=admin, guild=guild, role=CommunityRole.admin
        )
        member = await create_user(session, username="member", discriminator=77)
        await create_guild_membership(
            session, user=member, guild=guild, role=CommunityRole.member
        )
        return admin, member, guild

    async def test_no_address_reaches_the_guild(self, client, guild_with_member):
        """An account is a person's, not a tenant's — not even on the guild's
        own member-management surface."""
        admin, _member, guild = guild_with_member

        response = await client.get(
            f"/api/v1/c/{guild.id}/users/", headers=get_auth_headers(admin)
        )

        assert response.status_code == 200
        for row in response.json()["items"]:
            assert "email" not in row

    async def test_handles_are_always_there(self, client, guild_with_member):
        admin, member, guild = guild_with_member

        response = await client.get(
            f"/api/v1/c/{guild.id}/users/", headers=get_auth_headers(admin)
        )

        row = next(r for r in response.json()["items"] if r["id"] == member.id)
        assert row["username"] == "member"
        assert row["discriminator"] == 77

    async def test_the_name_set_in_the_guild_does(
        self, client, session, guild_with_member
    ):
        admin, member, guild = guild_with_member
        await create_guild_membership(
            session, user=member, guild=guild, display_name="Mem"
        )

        response = await client.get(
            f"/api/v1/c/{guild.id}/users/", headers=get_auth_headers(admin)
        )

        row = next(r for r in response.json()["items"] if r["id"] == member.id)
        assert row["display_name"] == "Mem"


class TestFindingSomeone:
    @pytest.fixture
    async def searchable_guild(self, session):
        # The searcher is a member too, so their own handle is in the
        # corpus. Pinned rather than generated: matching is fuzzy, and a random
        # name that happens to share three letters with a search term ("Three"
        # against "ivory-thrush") would fail an assertion about somebody else.
        admin = await create_user(session, username="zeph", discriminator=9001)
        guild = await create_guild(session, creator=admin)
        await create_guild_membership(
            session, user=admin, guild=guild, role=CommunityRole.admin
        )
        for username, discriminator, display_name in [
            ("jordan", 1234, "Jordan One"),
            ("jordan", 5678, "Jordan Two"),
            ("morgan", 12, "Morgan Three"),
            ("riley", 3, None),
        ]:
            member = await create_user(
                session, username=username, discriminator=discriminator
            )
            await create_guild_membership(
                session,
                user=member,
                guild=guild,
                role=CommunityRole.member,
                display_name=display_name,
            )
        return admin, guild

    async def _search(self, client, admin, guild, term):
        response = await client.get(
            f"/api/v1/c/{guild.id}/users/search",
            headers=get_auth_headers(admin),
            params={"search": term},
        )
        assert response.status_code == 200, response.text
        return response.json()["items"]

    async def test_a_name_part_matches_a_family_of_handles(
        self, client, searchable_guild
    ):
        admin, guild = searchable_guild

        items = await self._search(client, admin, guild, "jordan")

        assert {item["discriminator"] for item in items} == {1234, 5678}

    async def test_the_whole_handle_pins_one(self, client, searchable_guild):
        admin, guild = searchable_guild

        items = await self._search(client, admin, guild, "jordan#5678")

        assert [item["discriminator"] for item in items] == [5678]

    async def test_a_partial_number_is_a_prefix_of_the_four_digits(
        self, client, searchable_guild
    ):
        """The number renders zero-padded, so a prefix is a prefix of what is
        on screen: ``#00`` finds ``0012``."""
        admin, guild = searchable_guild

        items = await self._search(client, admin, guild, "morgan#00")

        assert [item["discriminator"] for item in items] == [12]

    async def test_a_display_name_is_searchable(self, client, searchable_guild):
        admin, guild = searchable_guild

        items = await self._search(client, admin, guild, "Three")

        assert [item["username"] for item in items] == ["morgan"]
