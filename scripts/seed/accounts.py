"""Seeded accounts: the players, the community admins, one person per platform
tier, and the community compliance seat. Every password is ``changeme``."""

from __future__ import annotations

import sys

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.encryption import hash_email
from app.core.security import get_password_hash
from app.models.platform.user import User, UserRole, UserStatus
from app.services.auth import addresses
from app.services.platform import dm_settings
from app.services.platform.usernames import allocate_from_seed

#: ``(email, name, timezone, colour theme[, platform tier])``. The name keys
#: the account in this seed and is what its handle is drawn from.
#:
#: user1..8 are ALWAYS regular community members (several are initiative PMs);
#: admin1..4 carry every community-admin membership instead, on the member
#: tier, because community admin is a community role, orthogonal to the
#: platform ladder. The platform-role accounts are one per tier. The compliance
#: seat is held in every community this run creates, on the member tier, which
#: keeps the two axes separable.
USERS: list[tuple] = [
    ("user1@example.com", "Dungeon Master", "America/New_York", "dracula"),
    ("user2@example.com", "Thorn Ironforge", "America/Chicago", "kobold"),
    ("user3@example.com", "Elara Moonwhisper", "Europe/London", "catppuccin"),
    ("user4@example.com", "Vex Shadowstep", "America/Los_Angeles", "dracula"),
    ("user5@example.com", "Seraphina Dawnlight", "Europe/Berlin", "kobold"),
    ("user6@example.com", "Finley Goldtongue", "Asia/Tokyo", "catppuccin"),
    ("user7@example.com", "Kael Windrunner", "Australia/Sydney", "kobold"),
    ("user8@example.com", "Aurelia Brightshield", "America/Denver", "dracula"),
    ("admin1@example.com", "Guildmaster Aldric", "America/New_York", "kobold"),
    ("admin2@example.com", "Overseer Nova", "America/Los_Angeles", "catppuccin"),
    ("admin3@example.com", "Harbormaster Marisol", "Europe/Lisbon", "dracula"),
    ("admin4@example.com", "Archivist Okoro", "Africa/Lagos", "kobold"),
    ("owner@example.com", "Platform Owner", "UTC", "kobold", UserRole.owner),
    ("operator@example.com", "Platform Operator", "UTC", "dracula", UserRole.operator),
    (
        "moderator@example.com",
        "Platform Moderator",
        "UTC",
        "catppuccin",
        UserRole.moderator,
    ),
    ("support@example.com", "Platform Support", "UTC", "kobold", UserRole.support),
    ("member@example.com", "Platform Member", "UTC", "dracula", UserRole.member),
    ("superadmin@example.com", "Community Superadmin", "UTC", "catppuccin"),
]

#: Seeded accounts whose week starts on Monday; everyone else keeps Sunday.
MONDAY_WEEK = {
    "Dungeon Master",
    "Elara Moonwhisper",
    "Seraphina Dawnlight",
    "Aurelia Brightshield",
    "Harbormaster Marisol",
}


async def seed(session: AsyncSession, ids: dict[str, list]) -> dict[str, User]:
    """Every seeded account by name, the bootstrap owner as "Admin User"."""
    owner = await _find_superuser(session)
    owner.timezone = "America/Los_Angeles"
    owner.color_theme = "kobold"
    owner.week_starts_on = 0
    session.add(owner)
    users = {"Admin User": owner}
    for email, name, tz, theme, *tier in USERS:
        users[name] = await _account(
            session,
            email,
            name,
            timezone=tz,
            color_theme=theme,
            role=tier[0] if tier else UserRole.member,
            week_starts_on=1 if name in MONDAY_WEEK else 0,
        )
        ids["users"].append(users[name].id)
    await session.flush()
    return users


async def _find_superuser(session: AsyncSession) -> User:
    """Find the superuser created by init_db."""
    email = settings.FIRST_OWNER_EMAIL
    if not email:
        print("ERROR: FIRST_OWNER_EMAIL is not set in .env or environment.")
        sys.exit(1)
    user = await addresses.account_holding(session, email)
    if user is None:
        print(f"ERROR: Superuser {email} not found.")
        print("  Make sure init_db has run (dev:migrate task).")
        sys.exit(1)
    return user


async def _account(session: AsyncSession, email: str, name: str, **fields) -> User:
    """One seeded account, made or picked back up.

    A prior interrupted seed run may have committed this user (users commit
    before the later steps): reuse the existing row so a re-run resumes instead
    of violating the unique email constraint.
    """
    user = await addresses.account_holding(session, email)
    if user is None:
        # The handle is drawn from the seed's name, with the number drawn for
        # them.
        handle, discriminator = await allocate_from_seed(session, seed=name)
        user = User(
            username=handle,
            discriminator=discriminator,
            hashed_password=get_password_hash("changeme"),
            status=UserStatus.active,
            **fields,
        )
    # Seeded accounts are set up ready to use, so they never meet the
    # choose-your-handle screen — including one the handle backfill gave a
    # handle it marks unchosen.
    user.username_chosen = True
    session.add(user)
    await session.flush()
    # Everything that makes an account records its address and seeds its
    # direct-message policy; an account seeded before addresses were rows of
    # their own catches up here. Asked of every row the account holds rather
    # than the proven ones, so a claim already recorded is left alone.
    if hash_email(email) not in await addresses.held_hashes(session, user_id=user.id):
        addresses.record_address(
            session,
            user_id=user.id,
            email=email,
            source=addresses.SOURCE_SIGNUP,
            # The address is proved: it signs them in and takes their mail.
            verified=True,
        )
    await dm_settings.seed_for_new_account(session, user_id=user.id)
    await session.flush()
    return user
