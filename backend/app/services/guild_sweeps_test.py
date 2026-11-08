"""The runner every community-by-community sweep goes through."""

from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db import cohorts
from app.models.platform.guild import CommunityStatus
from app.services.guild_sweeps import Scope, Visit, each_guild
from app.testing.factories import create_guild


async def test_each_scope_is_visited_on_its_communitys_cohort(session: AsyncSession):
    """Active is the one status taking writes, live adds read-only, and
    provisioned is every community whose schema exists, whatever its status.
    Each visit runs on a session from its own community's cohort."""
    ids = {
        status: (await create_guild(session, status=status.value)).id
        for status in (
            CommunityStatus.active,
            CommunityStatus.read_only,
            CommunityStatus.suspended,
            CommunityStatus.deleted,
        )
    }
    # A row whose schema was never made is left out of every scope.
    await create_guild(session, commit=False, status=CommunityStatus.deleted.value)
    await session.commit()
    assert {cohorts.cohort_of(guild_id) for guild_id in ids.values()} == {0, 1}
    seen: set[tuple[Scope, int]] = set()

    def recorder(scope: Scope) -> tuple[Scope, Visit]:
        async def visit(routed: AsyncSession, guild_id: int) -> None:
            assert routed.bind is cohorts.system_sessionmaker(guild_id).kw["bind"]
            seen.add((scope, guild_id))

        return scope, visit

    await each_guild([recorder(scope) for scope in Scope], name="test")

    assert seen == {
        (Scope.ACTIVE, ids[CommunityStatus.active]),
        (Scope.LIVE, ids[CommunityStatus.active]),
        (Scope.LIVE, ids[CommunityStatus.read_only]),
        *((Scope.PROVISIONED, guild_id) for guild_id in ids.values()),
    }


async def test_a_failing_visit_is_rolled_back_and_the_rest_carry_on(
    session: AsyncSession,
):
    first, second = await create_guild(session), await create_guild(session)
    seen: list[tuple[str, int]] = []

    async def fails_in_first(routed: AsyncSession, guild_id: int) -> None:
        if guild_id == first.id:
            await routed.exec(text("SELECT 1 / 0"))
        seen.append(("fails_in_first", guild_id))

    async def reads(routed: AsyncSession, guild_id: int) -> None:
        await routed.exec(text("SELECT 1"))
        seen.append(("reads", guild_id))

    await each_guild(
        [(Scope.ACTIVE, fails_in_first), (Scope.ACTIVE, reads)], name="test"
    )

    assert sorted(seen) == sorted(
        [("reads", first.id), ("fails_in_first", second.id), ("reads", second.id)]
    )


async def test_only_restricts_the_pass(session: AsyncSession):
    named = await create_guild(session)
    await create_guild(session)
    seen: list[int] = []

    async def visit(_routed: AsyncSession, guild_id: int) -> None:
        seen.append(guild_id)

    await each_guild([(Scope.ACTIVE, visit)], name="test", only=[named.id])

    assert seen == [named.id]
