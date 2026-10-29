"""The direct-message policy row that hangs off an account.

One row per account, created with the account. It is seeded here rather than in
each of the three places an account is made — registration, provisioning from
an identity provider, and the bootstrap owner — so the operator's default is
applied wherever an account arrives from.

A missing row still reads as ``private`` in ``public.dm_can_ask``, so a path
that somehow skips this is closed rather than open; what it would lose is the
operator's choice, silently, which is what ``dm_settings_test`` is for.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from sqlmodel import col, select

from app.core.errors import CodedError
from app.models.platform.guild import LIVE_STATUS_VALUES, Guild, GuildMembership
from app.models.platform.guild_image import GuildImageVariant
from app.models.platform.user_dm_guild_optout import UserDmGuildOptout
from app.models.platform.user_dm_settings import DmPolicy, UserDmSettings
from app.schemas.platform.dm import (
    CommunityDmToggle,
    CommunityDmToggleUpdate,
    DirectMessageSettingsRead,
)


async def seed_for_new_account(session: AsyncSession, *, user_id: int) -> None:
    """Give a newly created account the policy the operator set as the default.

    Runs on the session that created the account, which is the system engine on
    every path — the row belongs to an account that has no request context of
    its own yet.

    Idempotent by constraint: a second call for the same account does nothing,
    so a retried registration does not overwrite a policy its owner has since
    changed.
    """
    from app.services.platform import rules

    policy = (await rules.platform_values(session))["default_dm_policy"]
    # A core insert, so the model's default factories do not run: the
    # timestamps are named here.
    now = datetime.now(timezone.utc)
    await session.exec(
        pg_insert(UserDmSettings)
        .values(
            user_id=user_id,
            dm_policy=policy,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_nothing(index_elements=["user_id"])
    )


async def _row_for(session: AsyncSession, user_id: int) -> UserDmSettings:
    """The account's policy row, created closed if it is somehow missing.

    Only reached on the account's own request path, so the insert satisfies the
    own-row policy.
    """
    row = await session.get(UserDmSettings, user_id)
    if row is None:
        row = UserDmSettings(user_id=user_id, dm_policy=DmPolicy.private)
        session.add(row)
        await session.flush()
    return row


async def _rail_ordered_communities(
    session: AsyncSession, *, user_id: int
) -> list[tuple[int, str]]:
    """The reader's communities in the order they dragged the rail into.

    Same rule My Contacts uses, so the toggle list and the contacts page name
    the same communities in the same order. A suspended community is left out:
    it does not count towards ``can_ask`` either.
    """
    rows = (
        await session.exec(
            select(Guild.id, Guild.name)
            .join(GuildMembership, GuildMembership.guild_id == Guild.id)
            .where(
                GuildMembership.user_id == user_id,
                Guild.status.in_(LIVE_STATUS_VALUES),
            )
            .order_by(col(GuildMembership.position).asc(), col(Guild.id).asc())
        )
    ).all()
    return [(row[0], row[1]) for row in rows]


async def read_settings(
    session: AsyncSession, *, user, include_icons: bool = True
) -> DirectMessageSettingsRead:
    """The policy, and one toggle per community the reader is in.

    The toggles are the reader's communities LEFT JOINed against their own
    opt-out rows, so a community joined since the last write arrives switched
    on with nothing written for it.
    """
    from app.services.platform import app_settings as app_settings_service
    from app.services.platform import guild_images as guild_images_service

    row = await _row_for(session, user.id)
    communities = await _rail_ordered_communities(session, user_id=user.id)
    guild_ids = [guild_id for guild_id, _ in communities]

    switched_off = set(
        (
            await session.exec(
                select(UserDmGuildOptout.guild_id).where(
                    UserDmGuildOptout.user_id == user.id
                )
            )
        ).all()
    )
    icons: dict[int, dict] = {}
    if include_icons and guild_ids:
        icons = await guild_images_service.image_urls(
            session, guild_ids, GuildImageVariant.icon
        )

    return DirectMessageSettingsRead(
        dm_policy=row.dm_policy,
        age_confirmed_at=user.age_confirmed_at,
        age_answer_required=(
            user.age_confirmed_at is None
            and await app_settings_service.community_age_gate_enabled(session)
        ),
        send_receipts=row.send_receipts,
        communities=[
            CommunityDmToggle(
                community_id=guild_id,
                name=name,
                icon_url=icons.get(guild_id, {}).get(GuildImageVariant.icon),
                enabled=guild_id not in switched_off,
            )
            for guild_id, name in communities
        ],
    )


class DirectMessageSettingsError(CodedError):
    """A settings write refused with a message code."""

    status_code = 422


async def update_settings(
    session: AsyncSession,
    *,
    user,
    dm_policy: DmPolicy | None = None,
    communities: list[CommunityDmToggleUpdate] | None = None,
    send_receipts: bool | None = None,
) -> DirectMessageSettingsRead:
    """Write whichever parts were sent, leaving the rest alone.

    Raising the policy above ``private`` needs the age question answered,
    unless the deployment's owner has turned the age check off — then every
    account counts as an adult. The DM surface asks this itself rather than
    waiting on the community directory's own switch.

    A toggle for a community the account is not in is refused rather than
    ignored: it is a client sending something it cannot have rendered.
    """
    from app.core.messages import DirectMessageMessages
    from app.services.platform import app_settings as app_settings_service

    row = await _row_for(session, user.id)

    if dm_policy is not None and dm_policy is not DmPolicy.private:
        if (
            user.age_confirmed_at is None
            and await app_settings_service.community_age_gate_enabled(session)
        ):
            raise DirectMessageSettingsError(
                DirectMessageMessages.AGE_CONFIRMATION_REQUIRED
            )

    if communities:
        member_of = {
            guild_id
            for guild_id, _ in await _rail_ordered_communities(session, user_id=user.id)
        }
        unknown = [
            t.community_id for t in communities if t.community_id not in member_of
        ]
        if unknown:
            raise DirectMessageSettingsError(DirectMessageMessages.NOT_A_MEMBER)
        for toggle in communities:
            existing = await session.get(
                UserDmGuildOptout, (user.id, toggle.community_id)
            )
            if toggle.enabled and existing is not None:
                await session.delete(existing)
            elif not toggle.enabled and existing is None:
                session.add(
                    UserDmGuildOptout(user_id=user.id, guild_id=toggle.community_id)
                )

    if dm_policy is not None:
        row.dm_policy = dm_policy
    # Receipts are not part of who may reach this account, so they change
    # nothing about an open channel and start no re-test below.
    if send_receipts is not None:
        row.send_receipts = send_receipts
    if dm_policy is not None or communities or send_receipts is not None:
        row.updated_at = datetime.now(timezone.utc)
        session.add(row)

    if dm_policy is not None or communities:
        # A policy change or a switched-off community takes a leg of can_ask
        # away, so every open channel that rested on it is re-tested — the same
        # sweep every other lost leg runs, on the same after-commit queue.
        from app.services.platform import contact_grants as contact_grants_service

        contact_grants_service.queue_stale_grant_sweep(session, user.id)

    await session.commit()
    return await read_settings(session, user=user)
