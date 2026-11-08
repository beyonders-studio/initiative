"""What a request-path session may write on ``public.users``.

An account belongs to the person it names. A platform-tier session reads other
people — rosters, pickers and member management all do it — and writes one row,
its own. A guild-routed session reads people through
``public.guild_member_profiles`` and does not reach the table in either
direction. Platform user management (reactivate, platform role, delete, avatar
takedown) runs on the system engine instead, where a capability check is the
authorization.

These run under the real ``app_user`` login with a routed context rather than
the superuser-backed ``session`` fixture: the subject is what a policy does,
and a superuser session would show none of it.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.public_rls import platform_tier, role_name
from app.db.request_context import Platform, Unattributed
from app.db.schema_provisioning import guild_role_name
from app.db.session import set_rls_context
from app.models.platform.guild import CommunityRole
from app.models.platform.user import UserRole
from app.testing import create_guild, create_guild_membership, create_user, route_as

# The columns an account holder alone writes.
# The address columns left ``users`` with H3; what stays here is the one
# credential the row still carries.
CREDENTIAL_COLUMNS = ("hashed_password",)


async def _update_returning(
    session: AsyncSession, user_id: int, column: str, value: str
) -> list[int]:
    """Run one column update and report which rows it actually reached.

    ``RETURNING`` rather than ``rowcount``: a policy that filters the row makes
    the statement succeed against nothing, which is the outcome under test.

    Rolled back before returning. These are separate connections to the shared
    test database, so a write left behind — or the transaction still holding
    it — would follow the worker into every test after this one.
    """
    result = await session.exec(
        text(
            f"UPDATE public.users SET {column} = :v WHERE id = :i RETURNING id"
        ).bindparams(v=value, i=user_id)
    )
    reached = [row[0] for row in result.all()]
    await session.rollback()
    return reached


async def _count_visible(session: AsyncSession, user_id: int) -> int:
    visible = (
        await session.exec(
            text("SELECT count(*) FROM public.users WHERE id = :i").bindparams(
                i=user_id
            )
        )
    ).scalar()
    await session.rollback()
    return visible


async def _assumed_role(session: AsyncSession) -> str:
    """The Postgres role the session is currently wearing."""
    role = (await session.exec(text("SELECT current_user"))).scalar()
    await session.rollback()
    return role


class TestGuildSession:
    """A guild-scoped session — ``SET ROLE guild_<id>``, the request path for
    everything under ``/c/{community_id}``.

    It does not reach ``public.users`` at all. People are read through
    ``public.guild_member_profiles``, the projection that carries who somebody
    is and none of their account (migrations 0220/0221), so the questions here
    are about the table being unreachable and the view answering instead.
    """

    @pytest.fixture
    async def guild_with_two_members(self, session):
        admin = await create_user(session)
        guild = await create_guild(session, creator=admin)
        member = await create_user(session)
        await create_guild_membership(
            session, user=member, guild=guild, role=CommunityRole.member
        )
        return admin, member, guild

    @pytest.fixture
    async def guild_session(self, role_session, guild_with_two_members):
        admin, _member, guild = guild_with_two_members
        s = await role_session("app_user")
        await route_as(s, user_id=admin.id, guild_id=guild.id)
        return s

    async def test_does_not_read_the_users_table(
        self, guild_session, guild_with_two_members
    ):
        _admin, member, _guild = guild_with_two_members
        with pytest.raises(ProgrammingError):
            await _count_visible(guild_session, member.id)
        await guild_session.rollback()

    @pytest.mark.parametrize("column", CREDENTIAL_COLUMNS)
    async def test_does_not_write_another_members_credentials(
        self, guild_session, guild_with_two_members, column
    ):
        _admin, member, _guild = guild_with_two_members
        with pytest.raises(ProgrammingError):
            await _update_returning(guild_session, member.id, column, "rewritten")
        await guild_session.rollback()

    async def test_does_not_write_its_own_row_either(
        self, guild_session, guild_with_two_members
    ):
        """An account is edited on the platform path, never from inside a
        guild — so the own-row write goes with the rest."""
        admin, _member, _guild = guild_with_two_members
        with pytest.raises(ProgrammingError):
            await _update_returning(guild_session, admin.id, "timezone", "UTC")
        await guild_session.rollback()

    async def test_reads_another_member_through_the_projection(
        self, guild_session, guild_with_two_members
    ):
        _admin, member, _guild = guild_with_two_members
        found = (
            await guild_session.exec(
                text(
                    "SELECT username FROM public.guild_member_profiles WHERE id = :i"
                ).bindparams(i=member.id)
            )
        ).scalar()
        await guild_session.rollback()
        assert found == member.username

    async def test_the_projection_carries_no_account_columns(
        self, guild_session, guild_with_two_members
    ):
        """The view is the whole vocabulary: a column that is not in it cannot
        be named through it, whatever the query asks for."""
        _admin, member, _guild = guild_with_two_members
        for column in CREDENTIAL_COLUMNS:
            with pytest.raises(ProgrammingError):
                await guild_session.exec(
                    text(
                        f"SELECT {column} FROM public.guild_member_profiles "
                        "WHERE id = :i"
                    ).bindparams(i=member.id)
                )
            await guild_session.rollback()


class TestPlatformSession:
    """A platform-tier session — ``SET ROLE platform_<tier>``, the request path
    for everything outside a guild."""

    @pytest.fixture
    async def moderator_and_subject(self, session):
        moderator = await create_user(session, role=UserRole.moderator)
        subject = await create_user(session)
        return moderator, subject

    async def test_moderator_reads_every_account(
        self, session, role_session, moderator_and_subject
    ):
        moderator, subject = moderator_and_subject
        s = await role_session("app_user")
        await set_rls_context(s, Platform(user_id=moderator.id, tier="moderator"))

        assert await _count_visible(s, subject.id) == 1

    @pytest.mark.parametrize("column", CREDENTIAL_COLUMNS)
    async def test_moderator_does_not_write_another_accounts_credentials(
        self, session, role_session, moderator_and_subject, column
    ):
        moderator, subject = moderator_and_subject
        s = await role_session("app_user")
        await set_rls_context(s, Platform(user_id=moderator.id, tier="moderator"))

        assert await _update_returning(s, subject.id, column, "rewritten") == []

    async def test_a_member_changes_their_own_password(
        self, session, role_session, moderator_and_subject
    ):
        _moderator, subject = moderator_and_subject
        s = await role_session("app_user")
        await set_rls_context(s, Platform(user_id=subject.id, tier="member"))

        assert await _update_returning(
            s, subject.id, "hashed_password", "self-chosen"
        ) == [subject.id]


class TestReestablishedContext:
    """A request that re-establishes its own context keeps the role it came in
    with.

    Services do this part-way through a request — coming back from a walk
    across the caller's communities, or narrowing before a lookup — by naming
    the user again. The tier is not theirs to re-derive, and on this table the
    login role underneath reads every account while a ``member`` reads one, so
    what the request may read must not widen on the way through.
    """

    @pytest.fixture
    async def two_accounts(self, session):
        return await create_user(session), await create_user(session)

    async def test_naming_the_user_again_keeps_the_tier(
        self, session, role_session, two_accounts
    ):
        member, other = two_accounts
        s = await role_session("app_user")
        await set_rls_context(s, Platform(user_id=member.id, tier="member"))
        assert await _assumed_role(s) == role_name(platform_tier("member"))
        assert await _count_visible(s, other.id) == 0

        # The shape of every "back to the platform path" call in the services.
        await set_rls_context(s, Platform(user_id=member.id))

        assert await _assumed_role(s) == role_name(platform_tier("member"))
        assert await _count_visible(s, other.id) == 0

    async def test_a_guild_trip_comes_back_at_the_same_tier(
        self, session, role_session, two_accounts
    ):
        """The tier is recorded on the guild path too, where it does not route.

        A guild request assumes ``guild_<id>``; the tier is what it re-assumes
        when a cross-guild aggregate steps back out to ``public``.
        """
        member, other = two_accounts
        guild = await create_guild(session, creator=member)
        s = await role_session("app_user")
        await route_as(s, user_id=member.id, guild_id=guild.id)
        assert await _assumed_role(s) == guild_role_name(guild.id)

        await set_rls_context(s, Platform(user_id=member.id))

        assert await _assumed_role(s) == role_name(platform_tier("member"))
        assert await _count_visible(s, other.id) == 0

    async def test_it_crosses_a_transaction_boundary(
        self, session, role_session, two_accounts
    ):
        """The carried tier reaches Postgres the way every other value does.

        It is resolved once, into the stored parameters, and from there the
        replay hook applies it as a transaction-local ``set_config`` at the
        start of each transaction. Nothing is held on the connection, so the
        role is whatever the parameters say on whichever backend the next
        transaction lands on — which is what this commit forces.
        """
        member, other = two_accounts
        s = await role_session("app_user")
        await set_rls_context(s, Platform(user_id=member.id, tier="member"))
        await set_rls_context(s, Platform(user_id=member.id))
        await s.commit()

        assert await _assumed_role(s) == role_name(platform_tier("member"))
        assert await _count_visible(s, other.id) == 0

    async def test_an_unattributed_context_forgets_it(
        self, session, role_session, two_accounts
    ):
        """Naming no user is how a worker says it is acting for nobody.

        It clears the tier rather than leaving one for the next call to inherit,
        so a session cannot pick up an identity it was never given.
        """
        member, _other = two_accounts
        s = await role_session("app_user")
        await set_rls_context(s, Platform(user_id=member.id, tier="member"))
        await set_rls_context(s, Unattributed())
        assert await _assumed_role(s) == "app_user"

        await set_rls_context(s, Platform(user_id=member.id))

        assert await _assumed_role(s) == "app_user"
