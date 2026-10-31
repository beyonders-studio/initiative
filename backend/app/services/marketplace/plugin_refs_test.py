"""The properties a plug-in reference has to hold.

The sector is the plug-in in one guild, so a member has one reference per
plug-in, another again for the same plug-in in a second guild, and the same one
again after the plug-in is uninstalled and installed back. These hold that each
of those values is distinct, and that one stays put once minted until the
guild erases the plug-in's data.

The guild check has its own group. The value lives in a platform-wide table
now, so the guild is a predicate the resolver applies rather than the schema
the query runs in — which makes it worth holding directly.
"""

from app.models.platform.identity_ref import (
    REF_MAX_LENGTH,
    IdentityEntity,
    IdentityPurpose,
)
from app.services.marketplace.plugin_refs import (
    current_install_id,
    drop_guild_plugin_refs,
    drop_plugin_refs,
    ensure_plugin_guild_ref,
    ensure_plugin_ref,
    existing_plugin_guild_ref,
    guild_for_plugin_ref,
    plugins_with_refs,
    reissue_plugin_ref,
    reissue_plugin_refs,
    resolve_plugin_guild_ref,
    resolve_plugin_ref,
)
from app.services.platform.identity_refs import REF_GRACE_PERIOD, ensure_ref
from app.testing import create_guild, create_guild_plugin, create_user


def _definition(public_id: str = "acme.tracker") -> dict:
    return {"plugin_kind": "service", "service": {"public_id": public_id}}


async def _install(
    session, guild, user, *, listing_uid="TESTAPP0000001", public_id="acme.tracker"
):
    return await create_guild_plugin(
        session, guild, user, definition=_definition(public_id), listing_uid=listing_uid
    )


class TestOneReferencePerSector:
    async def test_two_plugins_name_one_person_differently(self, session):
        user = await create_user(session)
        guild = await create_guild(session, creator=user)
        await _install(session, guild, user)
        await _install(
            session, guild, user, listing_uid="TESTAPP0000002", public_id="other.plugin"
        )
        await session.commit()

        first = await ensure_plugin_ref(
            guild_id=guild.id, public_id="acme.tracker", user_id=user.id
        )
        second = await ensure_plugin_ref(
            guild_id=guild.id, public_id="other.plugin", user_id=user.id
        )
        assert first != second

    async def test_one_plugin_names_two_people_differently(self, session):
        owner = await create_user(session)
        other = await create_user(session)
        guild = await create_guild(session, creator=owner)
        await _install(session, guild, owner)
        await session.commit()

        assert await ensure_plugin_ref(
            guild_id=guild.id, public_id="acme.tracker", user_id=owner.id
        ) != await ensure_plugin_ref(
            guild_id=guild.id, public_id="acme.tracker", user_id=other.id
        )

    async def test_one_plugin_in_two_guilds_names_one_person_differently(self, session):
        user = await create_user(session)
        here = await create_guild(session, creator=user)
        there = await create_guild(session, creator=user)
        await _install(session, here, user)
        await _install(session, there, user)
        await session.commit()

        assert await ensure_plugin_ref(
            guild_id=here.id, public_id="acme.tracker", user_id=user.id
        ) != await ensure_plugin_ref(
            guild_id=there.id, public_id="acme.tracker", user_id=user.id
        )

    async def test_minting_twice_gives_the_same_reference(self, session):
        user = await create_user(session)
        guild = await create_guild(session, creator=user)
        await _install(session, guild, user)
        await session.commit()

        first = await ensure_plugin_ref(
            guild_id=guild.id, public_id="acme.tracker", user_id=user.id
        )
        assert first == await ensure_plugin_ref(
            guild_id=guild.id, public_id="acme.tracker", user_id=user.id
        )

    def test_the_value_fits_where_it_has_to_go(self):
        # A JWT claim and a URL bound the width the install parameter accepts.
        assert REF_MAX_LENGTH >= 37


class TestTheGuildPredicate:
    async def test_a_reference_resolves_inside_its_own_guild(self, session):
        user = await create_user(session)
        guild = await create_guild(session, creator=user)
        await _install(session, guild, user)
        await session.commit()

        ref = await ensure_plugin_ref(
            guild_id=guild.id, public_id="acme.tracker", user_id=user.id
        )
        row = await resolve_plugin_ref(session, ref=ref, guild_id=guild.id)
        assert row is not None
        assert row.entity_id == user.id
        assert row.sector_plugin == "acme.tracker"

    async def test_it_does_not_resolve_for_another_guild(self, session):
        user = await create_user(session)
        here = await create_guild(session, creator=user)
        there = await create_guild(session, creator=user)
        await _install(session, here, user)
        await session.commit()

        ref = await ensure_plugin_ref(
            guild_id=here.id, public_id="acme.tracker", user_id=user.id
        )
        assert await resolve_plugin_ref(session, ref=ref, guild_id=there.id) is None

    async def test_a_reference_for_another_purpose_does_not_resolve(self, session):
        user = await create_user(session)
        guild = await create_guild(session, creator=user)
        await session.commit()

        billing = await ensure_ref(
            session,
            entity_type=IdentityEntity.user,
            entity_id=user.id,
            purpose=IdentityPurpose.billing,
        )
        await session.commit()
        assert await resolve_plugin_ref(session, ref=billing, guild_id=guild.id) is None

    async def test_a_guild_reference_does_not_resolve_as_a_member(self, session):
        user = await create_user(session)
        guild = await create_guild(session, creator=user)
        await session.commit()

        as_guild = await ensure_ref(
            session,
            entity_type=IdentityEntity.guild,
            entity_id=guild.id,
            purpose=IdentityPurpose.plugin,
            sector_guild_id=guild.id,
            sector_plugin="acme.tracker",
        )
        await session.commit()
        assert (
            await resolve_plugin_ref(session, ref=as_guild, guild_id=guild.id) is None
        )


class TestMovingOne:
    async def test_a_member_can_be_made_unrecognisable_to_a_plugin(self, session):
        user = await create_user(session)
        guild = await create_guild(session, creator=user)
        await _install(session, guild, user)
        await session.commit()

        before = await ensure_plugin_ref(
            guild_id=guild.id, public_id="acme.tracker", user_id=user.id
        )
        after = await reissue_plugin_ref(
            session, guild_id=guild.id, public_id="acme.tracker", user_id=user.id
        )
        await session.commit()

        assert after != before
        # In flight during the swap still lands.
        assert (
            await resolve_plugin_ref(session, ref=before, guild_id=guild.id) is not None
        )

    async def test_every_member_for_one_plugin_can_be_moved_together(self, session):
        owner = await create_user(session)
        other = await create_user(session)
        guild = await create_guild(session, creator=owner)
        await _install(session, guild, owner)
        await session.commit()

        before = {
            u.id: await ensure_plugin_ref(
                guild_id=guild.id, public_id="acme.tracker", user_id=u.id
            )
            for u in (owner, other)
        }
        moved = await reissue_plugin_refs(
            session, guild_id=guild.id, public_id="acme.tracker"
        )
        await session.commit()

        assert moved == 2
        for user_id, old in before.items():
            assert (
                await ensure_plugin_ref(
                    guild_id=guild.id, public_id="acme.tracker", user_id=user_id
                )
                != old
            )


class TestTheInstallComesAndGoes:
    async def test_a_reinstall_finds_the_same_names(self, session):
        """The install row is not the sector: removing it and installing the
        same plug-in again names the guild and the member as before."""
        user = await create_user(session)
        guild = await create_guild(session, creator=user)
        first = await _install(session, guild, user)
        await session.commit()

        member = await ensure_plugin_ref(
            guild_id=guild.id, public_id="acme.tracker", user_id=user.id
        )
        community = await ensure_plugin_guild_ref(
            guild_id=guild.id, public_id="acme.tracker"
        )
        first_id = first.id
        await session.delete(first)
        await session.commit()
        second = await _install(session, guild, user)
        await session.commit()

        assert second.id != first_id
        assert (
            await ensure_plugin_ref(
                guild_id=guild.id, public_id="acme.tracker", user_id=user.id
            )
            == member
        )
        assert (
            await ensure_plugin_guild_ref(guild_id=guild.id, public_id="acme.tracker")
            == community
        )

    async def test_a_community_reference_says_which_plugin_it_is_for(self, session):
        user = await create_user(session)
        guild = await create_guild(session, creator=user)
        await _install(session, guild, user)
        await session.commit()

        ref = await ensure_plugin_guild_ref(guild_id=guild.id, public_id="acme.tracker")
        assert await resolve_plugin_guild_ref(ref=ref) == (guild.id, "acme.tracker")

    async def test_the_current_install_is_read_from_the_guild(self, session):
        user = await create_user(session)
        guild = await create_guild(session, creator=user)
        plugin = await _install(session, guild, user)
        await session.commit()

        assert (
            await current_install_id(guild_id=guild.id, public_id="acme.tracker")
            == plugin.id
        )
        assert (
            await current_install_id(guild_id=guild.id, public_id="other.plugin")
            is None
        )

    async def test_a_reference_is_its_plugins_only_while_installed(self, session):
        user = await create_user(session)
        guild = await create_guild(session, creator=user)
        plugin = await _install(session, guild, user)
        await session.commit()

        ref = await ensure_plugin_guild_ref(guild_id=guild.id, public_id="acme.tracker")
        assert await guild_for_plugin_ref(ref=ref, public_id="acme.tracker") == guild.id
        assert await guild_for_plugin_ref(ref=ref, public_id="other.plugin") is None

        await session.delete(plugin)
        await session.commit()
        assert await guild_for_plugin_ref(ref=ref, public_id="acme.tracker") is None
        # The name itself stands, for when it comes back.
        assert (
            await existing_plugin_guild_ref(guild_id=guild.id, public_id="acme.tracker")
            == ref
        )


class TestRemoval:
    async def test_erasing_removes_what_that_plugin_called_people(self, session):
        user = await create_user(session)
        guild = await create_guild(session, creator=user)
        await _install(session, guild, user)
        await _install(
            session, guild, user, listing_uid="TESTAPP0000002", public_id="other.plugin"
        )
        await session.commit()

        gone = await ensure_plugin_ref(
            guild_id=guild.id, public_id="acme.tracker", user_id=user.id
        )
        await ensure_plugin_guild_ref(guild_id=guild.id, public_id="acme.tracker")
        kept = await ensure_plugin_ref(
            guild_id=guild.id, public_id="other.plugin", user_id=user.id
        )
        assert await plugins_with_refs(guild_id=guild.id) == [
            "acme.tracker",
            "other.plugin",
        ]

        assert await drop_plugin_refs(guild_id=guild.id, public_id="acme.tracker") == 2
        assert await resolve_plugin_ref(session, ref=gone, guild_id=guild.id) is None
        assert (
            await resolve_plugin_ref(session, ref=kept, guild_id=guild.id) is not None
        )
        assert await plugins_with_refs(guild_id=guild.id) == ["other.plugin"]
        # A later install starts afresh.
        assert (
            await ensure_plugin_ref(
                guild_id=guild.id, public_id="acme.tracker", user_id=user.id
            )
            != gone
        )

    async def test_deleting_a_guild_removes_its_plugin_references(self, session):
        user = await create_user(session)
        here = await create_guild(session, creator=user)
        there = await create_guild(session, creator=user)
        await _install(session, here, user)
        await _install(session, there, user)
        await session.commit()

        gone = await ensure_plugin_ref(
            guild_id=here.id, public_id="acme.tracker", user_id=user.id
        )
        kept = await ensure_plugin_ref(
            guild_id=there.id, public_id="acme.tracker", user_id=user.id
        )

        assert await drop_guild_plugin_refs(guild_id=here.id) == 1
        await session.commit()
        assert await resolve_plugin_ref(session, ref=gone, guild_id=here.id) is None
        assert (
            await resolve_plugin_ref(session, ref=kept, guild_id=there.id) is not None
        )

    async def test_the_deletion_sequence_its_callers_follow(self, session):
        """Delete, commit, then drop — the order `delete_guild` documents.

        The references are on a different connection and cannot join the
        deletion's transaction, so they go after the commit that made it real.
        A guild whose deletion then failed still holds the identities its plug-ins
        know its members by.
        """
        from app.services.platform import guilds as guilds_service

        user = await create_user(session)
        guild = await create_guild(session, creator=user)
        await _install(session, guild, user)
        await session.commit()

        guild_id = guild.id
        ref = await ensure_plugin_ref(
            guild_id=guild_id, public_id="acme.tracker", user_id=user.id
        )
        await guilds_service.delete_guild(session, guild)

        # Still resolvable until the deletion is committed.
        assert await resolve_plugin_ref(session, ref=ref, guild_id=guild_id) is not None

        await session.commit()
        await drop_guild_plugin_refs(guild_id=guild_id)

        assert await resolve_plugin_ref(session, ref=ref, guild_id=guild_id) is None

    async def test_the_sweep_reclaims_a_removed_guilds_references(self, session):
        """What a failed post-commit cleanup leaves behind.

        The sector columns cannot be foreign keys, so nothing removes these on
        the guild's way out except the removal path. When that does not manage
        it, this is what reclaims them.
        """
        from app.services.platform import guilds as guilds_service
        from app.services.platform.identity_refs import purge_orphaned_sector_refs

        user = await create_user(session)
        gone = await create_guild(session, creator=user)
        kept = await create_guild(session, creator=user)
        await _install(session, gone, user)
        await _install(session, kept, user)
        await session.commit()

        orphaned = await ensure_plugin_ref(
            guild_id=gone.id, public_id="acme.tracker", user_id=user.id
        )
        live = await ensure_plugin_ref(
            guild_id=kept.id, public_id="acme.tracker", user_id=user.id
        )

        # The guild goes and the cleanup does not run — the case this covers.
        kept_id = kept.id
        await guilds_service.delete_guild(session, gone)
        await session.commit()

        assert await purge_orphaned_sector_refs(session) == 1
        await session.commit()
        assert await resolve_plugin_ref(session, ref=orphaned, guild_id=kept_id) is None
        assert await resolve_plugin_ref(session, ref=live, guild_id=kept_id) is not None

    async def test_the_sweep_leaves_a_deleted_guild_its_references(self, session):
        """A deleted guild can come back, and is purged only after its
        plug-ins are told to erase: its names stand until then."""
        from app.models.platform.guild import CommunityStatus
        from app.services.platform.identity_refs import purge_orphaned_sector_refs

        user = await create_user(session)
        guild = await create_guild(session, creator=user)
        await _install(session, guild, user)
        await session.commit()
        ref = await ensure_plugin_ref(
            guild_id=guild.id, public_id="acme.tracker", user_id=user.id
        )
        guild_id = guild.id
        guild.status = CommunityStatus.deleted.value
        session.add(guild)
        await session.commit()

        assert await purge_orphaned_sector_refs(session) == 0
        await session.commit()
        assert await resolve_plugin_ref(session, ref=ref, guild_id=guild_id) is not None

    def test_the_grace_window_is_the_shared_one(self):
        # Plug-in references retire on the same clock as every other sector's.
        assert REF_GRACE_PERIOD.days == 30
