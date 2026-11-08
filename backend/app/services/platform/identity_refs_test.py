"""The properties a reference has to hold, stated as tests.

Three groups: what a rendered value looks like, what minting and resolving
guarantee, and what the two re-issue levers move — the fine one, which is one
entity and one purpose, and the coarse one, which is every entity for a purpose.
"""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.identity_ref import (
    REF_MAX_LENGTH,
    REF_RANDOM_LENGTH,
    IdentityEntity,
    IdentityPurpose,
    ref_prefix,
)
from app.services.platform.identity_refs import (
    REF_GRACE_PERIOD,
    drop_entity_refs,
    drop_guild_refs,
    ensure_ref,
    mint_ref,
    purge_retired_refs,
    reissue_all_refs,
    reissue_ref,
    resolve_ref,
)

BILLING = IdentityPurpose.billing


class TestTheRenderedValue:
    def test_it_is_a_prefix_and_a_random_half(self):
        ref = mint_ref(IdentityEntity.guild, BILLING)
        prefix, _, random_half = ref.partition("_")
        assert prefix == "gbil"
        assert len(random_half) == REF_RANDOM_LENGTH
        assert len(ref) <= REF_MAX_LENGTH

    def test_it_fits_a_jwt_claim_and_a_url(self):
        random_half = mint_ref(IdentityEntity.user, BILLING).partition("_")[2]
        assert random_half.replace("-", "").replace("_", "").isalnum()

    def test_the_prefix_names_the_entity_and_the_purpose(self):
        assert ref_prefix(IdentityEntity.user, BILLING) == "ubil"
        assert ref_prefix(IdentityEntity.guild, BILLING) == "gbil"
        assert ref_prefix(IdentityEntity.user, IdentityPurpose.plugin) == "uplu"

    def test_two_mints_never_agree(self):
        assert mint_ref(IdentityEntity.user, BILLING) != mint_ref(
            IdentityEntity.user, BILLING
        )


class TestMintingAndResolving:
    async def test_minting_twice_gives_the_same_reference(self, session):
        first = await ensure_ref(
            session, entity_type=IdentityEntity.guild, entity_id=1, purpose=BILLING
        )
        second = await ensure_ref(
            session, entity_type=IdentityEntity.guild, entity_id=1, purpose=BILLING
        )
        assert first == second

    async def test_two_first_callers_racing_get_one_reference(self, session, engine):
        """The claim ``ensure_ref`` makes about concurrency, exercised.

        Two independent sessions mint the same (entity, purpose) at once. The
        partial unique index lets one insert land; the other's
        ``ON CONFLICT DO NOTHING`` waits for it, no-ops, and reads back the
        winner's value.
        """
        maker = async_sessionmaker(
            bind=engine, class_=AsyncSession, expire_on_commit=False
        )

        async def mint() -> str:
            async with maker() as racing:
                ref = await ensure_ref(
                    racing,
                    entity_type=IdentityEntity.guild,
                    entity_id=77,
                    purpose=BILLING,
                )
                await racing.commit()
                return ref

        first, second = await asyncio.gather(mint(), mint())
        assert first == second

        settled = await resolve_ref(session, ref=first)
        assert settled is not None and settled.entity_id == 77

    async def test_one_entity_gets_an_unrelated_value_per_purpose(self, session):
        billing = await ensure_ref(
            session, entity_type=IdentityEntity.user, entity_id=1, purpose=BILLING
        )
        at_plugin = await ensure_ref(
            session,
            entity_type=IdentityEntity.user,
            entity_id=1,
            purpose=IdentityPurpose.plugin,
            sector_guild_id=3,
            sector_plugin="acme.app7",
        )
        assert billing != at_plugin

    async def test_a_user_and_a_guild_of_the_same_id_differ(self, session):
        as_user = await ensure_ref(
            session, entity_type=IdentityEntity.user, entity_id=42, purpose=BILLING
        )
        as_guild = await ensure_ref(
            session, entity_type=IdentityEntity.guild, entity_id=42, purpose=BILLING
        )
        assert as_user != as_guild

    async def test_a_reference_resolves_to_its_entity(self, session):
        ref = await ensure_ref(
            session, entity_type=IdentityEntity.guild, entity_id=9, purpose=BILLING
        )
        row = await resolve_ref(session, ref=ref)
        assert row is not None
        assert row.entity_type == IdentityEntity.guild
        assert row.entity_id == 9
        assert row.purpose == BILLING

    @pytest.mark.parametrize("candidate", ["", "gbil_nope", "x" * (REF_MAX_LENGTH + 1)])
    async def test_a_value_we_never_minted_resolves_to_nothing(
        self, session, candidate
    ):
        assert await resolve_ref(session, ref=candidate) is None


class TestReissuingOne:
    async def test_it_returns_a_new_value(self, session):
        before = await ensure_ref(
            session, entity_type=IdentityEntity.guild, entity_id=1, purpose=BILLING
        )
        after = await reissue_ref(
            session, entity_type=IdentityEntity.guild, entity_id=1, purpose=BILLING
        )
        assert after != before

    async def test_the_replaced_value_keeps_resolving_for_its_grace_window(
        self, session
    ):
        before = await ensure_ref(
            session, entity_type=IdentityEntity.guild, entity_id=1, purpose=BILLING
        )
        await reissue_ref(
            session, entity_type=IdentityEntity.guild, entity_id=1, purpose=BILLING
        )
        row = await resolve_ref(session, ref=before)
        assert row is not None and row.entity_id == 1

    async def test_the_replaced_value_stops_resolving_after_it(self, session):
        before = await ensure_ref(
            session, entity_type=IdentityEntity.guild, entity_id=1, purpose=BILLING
        )
        await reissue_ref(
            session, entity_type=IdentityEntity.guild, entity_id=1, purpose=BILLING
        )
        later = datetime.now(UTC) + REF_GRACE_PERIOD + timedelta(days=1)
        assert await resolve_ref(session, ref=before, now=later) is None

    async def test_it_moves_nothing_else(self, session):
        target = await ensure_ref(
            session, entity_type=IdentityEntity.guild, entity_id=1, purpose=BILLING
        )
        neighbour = await ensure_ref(
            session, entity_type=IdentityEntity.guild, entity_id=2, purpose=BILLING
        )
        other_purpose = await ensure_ref(
            session,
            entity_type=IdentityEntity.guild,
            entity_id=1,
            purpose=IdentityPurpose.plugin,
            sector_guild_id=3,
            sector_plugin="acme.app7",
        )
        await reissue_ref(
            session, entity_type=IdentityEntity.guild, entity_id=1, purpose=BILLING
        )

        assert (
            await ensure_ref(
                session, entity_type=IdentityEntity.guild, entity_id=2, purpose=BILLING
            )
            == neighbour
        )
        assert (
            await ensure_ref(
                session,
                entity_type=IdentityEntity.guild,
                entity_id=1,
                purpose=IdentityPurpose.plugin,
                sector_guild_id=3,
                sector_plugin="acme.app7",
            )
            == other_purpose
        )
        assert (
            await ensure_ref(
                session, entity_type=IdentityEntity.guild, entity_id=1, purpose=BILLING
            )
            != target
        )


class TestReissuingEvery:
    async def test_it_moves_every_entity_holding_that_purpose(self, session):
        before = {
            entity_id: await ensure_ref(
                session,
                entity_type=IdentityEntity.user,
                entity_id=entity_id,
                purpose=BILLING,
            )
            for entity_id in (1, 2, 3)
        }

        moved = await reissue_all_refs(
            session, entity_type=IdentityEntity.user, purpose=BILLING
        )
        assert moved == 3

        for entity_id, old in before.items():
            current = await ensure_ref(
                session,
                entity_type=IdentityEntity.user,
                entity_id=entity_id,
                purpose=BILLING,
            )
            assert current != old
            # Still resolvable, so nothing already in flight breaks.
            assert (await resolve_ref(session, ref=old)) is not None

    async def test_it_leaves_other_purposes_and_entities_alone(self, session):
        at_plugin = await ensure_ref(
            session,
            entity_type=IdentityEntity.user,
            entity_id=1,
            purpose=IdentityPurpose.plugin,
            sector_guild_id=3,
            sector_plugin="acme.app7",
        )
        a_guild = await ensure_ref(
            session, entity_type=IdentityEntity.guild, entity_id=1, purpose=BILLING
        )
        await ensure_ref(
            session, entity_type=IdentityEntity.user, entity_id=1, purpose=BILLING
        )

        await reissue_all_refs(
            session, entity_type=IdentityEntity.user, purpose=BILLING
        )

        assert (
            await ensure_ref(
                session,
                entity_type=IdentityEntity.user,
                entity_id=1,
                purpose=IdentityPurpose.plugin,
                sector_guild_id=3,
                sector_plugin="acme.app7",
            )
            == at_plugin
        )
        assert (
            await ensure_ref(
                session, entity_type=IdentityEntity.guild, entity_id=1, purpose=BILLING
            )
            == a_guild
        )

    async def test_a_run_that_stopped_after_retiring_is_finished_by_the_next(
        self, session
    ):
        await ensure_ref(
            session, entity_type=IdentityEntity.user, entity_id=1, purpose=BILLING
        )
        # An interrupted run leaves the entity retired with nothing live.
        await reissue_ref(
            session, entity_type=IdentityEntity.user, entity_id=1, purpose=BILLING
        )
        await drop_live_ref(session, entity_id=1)

        moved = await reissue_all_refs(
            session, entity_type=IdentityEntity.user, purpose=BILLING
        )
        assert moved == 1
        assert (
            await ensure_ref(
                session, entity_type=IdentityEntity.user, entity_id=1, purpose=BILLING
            )
            is not None
        )


class TestRemoval:
    async def test_erasing_an_entity_drops_what_every_party_held(self, session):
        billing = await ensure_ref(
            session, entity_type=IdentityEntity.user, entity_id=1, purpose=BILLING
        )
        at_plugin = await ensure_ref(
            session,
            entity_type=IdentityEntity.user,
            entity_id=1,
            purpose=IdentityPurpose.plugin,
            sector_guild_id=3,
            sector_plugin="acme.app7",
        )

        dropped = await drop_entity_refs(
            session, entity_type=IdentityEntity.user, entity_id=1
        )
        assert dropped == 2
        assert await resolve_ref(session, ref=billing) is None
        assert await resolve_ref(session, ref=at_plugin) is None

    async def test_a_deleted_guild_leaves_neither_half(self, session):
        """A guild is in this table twice and both have to go.

        Its members are named to each plug-in installed there, in sectors the guild
        owns. The guild itself is named by billing, whose sector is the whole
        deployment — so those rows carry no ``sector_guild_id`` and a sweep
        looking for one never finds them.
        """
        own = await ensure_ref(
            session, entity_type=IdentityEntity.guild, entity_id=5, purpose=BILLING
        )
        member = await ensure_ref(
            session,
            entity_type=IdentityEntity.user,
            entity_id=9,
            purpose=IdentityPurpose.plugin,
            sector_guild_id=5,
            sector_plugin="acme.app2",
        )
        elsewhere = await ensure_ref(
            session, entity_type=IdentityEntity.guild, entity_id=6, purpose=BILLING
        )

        assert await drop_guild_refs(session, guild_id=5) == 2
        assert await resolve_ref(session, ref=own) is None
        assert await resolve_ref(session, ref=member) is None
        # Another guild's name is not this guild's to take.
        assert await resolve_ref(session, ref=elsewhere) is not None

    async def test_the_sweep_takes_only_what_has_stopped_resolving(self, session):
        live = await ensure_ref(
            session, entity_type=IdentityEntity.user, entity_id=1, purpose=BILLING
        )
        retired = await ensure_ref(
            session, entity_type=IdentityEntity.user, entity_id=2, purpose=BILLING
        )
        await reissue_ref(
            session, entity_type=IdentityEntity.user, entity_id=2, purpose=BILLING
        )

        purged = await purge_retired_refs(session)
        assert purged == 0

        later = datetime.now(UTC) + REF_GRACE_PERIOD + timedelta(days=1)
        assert await purge_retired_refs(session, now=later) == 1
        assert await resolve_ref(session, ref=live) is not None
        assert await resolve_ref(session, ref=retired) is None


async def drop_live_ref(session, *, entity_id: int) -> None:
    """Remove the live row for a user's billing reference, leaving retired ones.

    Stands in for a bulk run that stopped between retiring and re-minting.
    """
    from sqlmodel import delete

    from app.models.platform.identity_ref import IdentityRef

    await session.exec(
        delete(IdentityRef).where(
            IdentityRef.entity_type == IdentityEntity.user,
            IdentityRef.entity_id == entity_id,
            IdentityRef.purpose == BILLING,
            IdentityRef.retired_at.is_(None),
        )
    )


class TestTheBillingPair:
    async def test_it_names_the_user_and_the_guild_differently(self, session):
        from app.services.platform.identity_refs import billing_refs

        user_ref, guild_ref = await billing_refs(user_id=1, guild_id=1)
        assert user_ref.startswith("ubil_")
        assert guild_ref.startswith("gbil_")
        assert user_ref != guild_ref

    async def test_asking_twice_gives_the_same_pair(self, session):
        from app.services.platform.identity_refs import billing_refs

        first = await billing_refs(user_id=3, guild_id=4)
        assert await billing_refs(user_id=3, guild_id=4) == first


class TestTheSweep:
    async def test_it_takes_what_names_nobody_and_keeps_what_can_come_back(
        self, session
    ):
        from sqlmodel import select

        from app.models.platform.guild import CommunityStatus
        from app.models.platform.identity_ref import IdentityRef
        from app.models.platform.user import UserStatus
        from app.services.platform.identity_refs import sweep_identity_refs
        from app.testing import create_guild, create_user

        active = await create_user(session)
        leaving = await create_user(session, status=UserStatus.deleted)
        erased = await create_user(session, status=UserStatus.anonymized)
        live_guild = await create_guild(session, creator=active)
        retained_guild = await create_guild(session, creator=active)
        retained_guild.status = CommunityStatus.deleted.value
        session.add(retained_guild)
        await session.commit()
        gone_id = retained_guild.id + 1000

        async def user_ref(user_id: int) -> str:
            return await ensure_ref(
                session,
                entity_type=IdentityEntity.user,
                entity_id=user_id,
                purpose=BILLING,
            )

        async def guild_ref(guild_id: int) -> str:
            return await ensure_ref(
                session,
                entity_type=IdentityEntity.guild,
                entity_id=guild_id,
                purpose=BILLING,
            )

        async def plugin_ref(guild_id: int) -> str:
            return await ensure_ref(
                session,
                entity_type=IdentityEntity.user,
                entity_id=active.id,
                purpose=IdentityPurpose.plugin,
                sector_guild_id=guild_id,
                sector_plugin="acme.app1",
            )

        kept = [
            await user_ref(active.id),
            await user_ref(leaving.id),
            await guild_ref(live_guild.id),
            await guild_ref(retained_guild.id),
            await plugin_ref(live_guild.id),
            # A deleted guild's plug-ins are told to erase at its purge.
            await plugin_ref(retained_guild.id),
        ]
        swept = [
            await user_ref(erased.id),
            await user_ref(gone_id),
            await guild_ref(gone_id),
            await plugin_ref(gone_id),
        ]
        await session.commit()

        assert await sweep_identity_refs(session) > 0
        for ref in kept:
            assert await resolve_ref(session, ref=ref) is not None, ref
        for ref in swept:
            assert await resolve_ref(session, ref=ref) is None, ref
        # Every purpose goes, not only the ones minted here: each account
        # carries a client reference from the moment it exists.
        left = await session.exec(
            select(IdentityRef).where(
                IdentityRef.entity_type == IdentityEntity.user,
                IdentityRef.entity_id == erased.id,
            )
        )
        assert left.all() == []
        assert await sweep_identity_refs(session) == 0
