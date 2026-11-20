"""Handing out the number behind a name."""

import pytest
from sqlalchemy import func, select

from app.core import usernames
from app.models.platform.user import User
from app.services.platform import usernames as username_service
from app.testing import create_user


class TestAllocate:
    async def test_skips_a_number_already_behind_the_name(self, session, monkeypatch):
        """Every draw lands on the one number already held, so the free-number
        scan is what answers — a handle is the pair, and the pair is unique."""
        await create_user(session, username="jordan", discriminator=1234)
        monkeypatch.setattr(usernames, "random_discriminator", lambda: 1234)

        _, number = await username_service.allocate(session, name="jordan")

        assert number != 1234


class TestAllocateFromSeed:
    async def test_uses_the_seed(self, session):
        name, _ = await username_service.allocate_from_seed(
            session, seed="Jordan Drako"
        )
        assert name == "jordan-drako"

    @pytest.mark.parametrize("seed", [None, "", "jordan@example.com", "admin"])
    async def test_falls_back_to_a_generated_name(self, session, seed):
        """An address, a reserved word and an empty seed all have to end in
        something storable — this is the path every SSO account takes."""
        name, number = await username_service.allocate_from_seed(session, seed=seed)
        usernames.validate(name)
        assert 0 <= number <= 9999


class TestClaim:
    async def test_sets_the_handle_and_marks_it_chosen(self, session):
        user = await create_user(session, username_chosen=False)

        await username_service.claim_for_user(
            session, user=user, name="Picked", prefer=4821
        )
        await session.commit()

        assert (user.username, user.discriminator) == ("picked", 4821)
        assert user.username_chosen is True

    async def test_the_pair_is_unique(self, session):
        """Two accounts may hold the same name; the number is what separates
        them, and the index is what enforces it."""
        first = await create_user(session, username_chosen=False)
        second = await create_user(session, username_chosen=False)

        await username_service.claim_for_user(session, user=first, name="shared")
        await session.commit()
        await username_service.claim_for_user(session, user=second, name="shared")
        await session.commit()

        assert first.username == second.username == "shared"
        assert first.discriminator != second.discriminator

        held = (
            await session.exec(
                select(func.count())
                .select_from(User)
                .where(func.lower(User.username) == "shared")
            )
        ).scalar_one()
        assert held == 2


class TestInsertWithHandle:
    async def test_redraws_when_the_pair_is_gone(self, session, monkeypatch):
        """``allocate`` reads which numbers are taken and then picks one, so a
        concurrent registration can take the pair in between. The index refuses
        it and the insert draws again rather than turning a valid registration
        away."""
        from app.models.platform.user import User

        held = await create_user(session, username="racer", discriminator=4242)

        # The read that finds which numbers are taken ran before the other
        # registration landed, so the number it draws first looks free.
        async def nothing_taken(session, name):
            return set()

        monkeypatch.setattr(username_service, "_taken", nothing_taken)
        draws = iter([4242, 777])
        monkeypatch.setattr(usernames, "random_discriminator", lambda: next(draws))

        user = User(
            username="",
            discriminator=0,
            hashed_password="x",
        )
        await username_service.insert_with_handle(session, user=user, name="racer")
        await session.commit()

        assert user.username == "racer"
        assert user.discriminator == 777
        assert held.discriminator == 4242
