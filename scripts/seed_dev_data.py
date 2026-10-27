"""TTRPG-themed dev data seeder for Initiative.

Usage:
    python seed_dev_data.py          # Create test data
    python seed_dev_data.py --clean  # Remove seeded test data

Designed to run from the backend/ directory (CWD) so app imports resolve.
Saves created IDs to .vscode/.dev_seed_ids.json. The dataset itself lives in
``scripts/seed/``, one module per area; this file runs them in order.

Creates 3 communities with multiple users, initiatives, projects, tasks, files,
tags, and comments to exercise all features of the app, plus six small communities
that exist to fill the community directory (which this switches on). Communities 1
and 2 stay invite-only so the unlisted case is still there to look at.

Seeded logins (all password "changeme"):
- admin1..admin4@example.com — dedicated community admins (platform tier: member).
- user1..user8@example.com — regular community members only (never community admins);
  several are initiative PMs so PM full access is testable from a non-admin.
- owner@/operator@/moderator@/support@/member@example.com — one user per
  platform tier, plus seeded PAM access-grant rows (pending / live / denied /
  expired / break-glass) to exercise the privileged-access flows.
- superadmin@example.com — the community compliance seat, held in EVERY seeded
  community (platform tier: member, so the community seat is testable on its
  own rather than alongside a platform tier).

Every community also seeds template projects and archived projects (with a spread of
archive dates, tags, and tasks) so the Templates and Archive tabs have the same
variety the active list does.

Sharing variety: resources cover every share status — private (owner-only),
per-user read/write grants, initiative-role grants, and all-initiative-members
"general access" rows at both Viewer (read) and Editor (write) levels.
"""

from __future__ import annotations

import asyncio
import sys
from collections import defaultdict
from pathlib import Path

# Add backend/ to sys.path so `app.*` imports work when invoked as
# `python ../scripts/seed_dev_data.py` from the backend/ directory.
BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import settings  # noqa: E402
from app.core.intake import IntakeStream  # noqa: E402
from app.db.session import SystemSessionLocal  # noqa: E402

from seed import (  # noqa: E402
    access_grants,
    accounts,
    calendars,
    comments,
    counters,
    dashboards,
    directory,
    files,
    libraries,
    guilds,
    initiatives,
    operations,
    posts,
    projects,
    properties,
    queues,
    tags,
    tickets,
    wikis,
)
from seed.state import (  # noqa: E402
    clean,
    load_state,
    mark_seed_incomplete,
    save_state,
    state_outlived_its_database,
)

#: Each community's content, in the order it is written. Tags come first so
#: anything can carry one; archiving waits for the end (see ``projects``).
AREAS = (
    initiatives,
    tags,
    projects,
    files,
    comments,
    queues,
    counters,
    dashboards,
    calendars,
    properties,
    posts,
    libraries,
    wikis,
)


async def seed() -> None:
    state = load_state()
    if state is not None and await state_outlived_its_database(state):
        print("The recorded seed data is gone (the database was recreated).")
        print("  Seeding again from scratch.")
        state = None
    if state is not None:
        if state.get("seed_incomplete"):
            print("A previous seed was interrupted and left partial data.")
            print("  Run with --clean, then dev-migrate, then seed again.")
        else:
            print("Seed data already exists (.vscode/.dev_seed_ids.json found).")
            print("  Run with --clean first to remove existing data.")
        return

    print("Seeding dev data (3 communities, multiple users)...")
    mark_seed_incomplete()
    ids: defaultdict[str, list] = defaultdict(list)

    async with SystemSessionLocal() as session:
        print("  Creating users...")
        users = await accounts.seed(session, ids)

        seeded = {}
        for key, spec in guilds.COMMUNITIES.items():
            print(f"\n  --- {spec['title']} ---")
            c = await guilds.open_community(session, ids, users, key)
            for area in AREAS:
                print(f"  Creating {area.__name__.rsplit('.', 1)[-1]}...")
                await area.seed(c)
            await projects.apply_archives(c)
            await session.commit()
            seeded[key] = c.guild

        print("\n  --- Community directory ---")
        await directory.seed(session, ids, users, seeded["tides"])

        print("\n  Creating PAM access grants...")
        await access_grants.seed(
            session, ids, users, {key: guild.id for key, guild in seeded.items()}
        )
        # Last, so it covers every community the run created — including the
        # directory fillers, which are seeded after communities 1-3.
        seated = await guilds.seat_superadmin(session, users["Community Superadmin"])
        print(f"  Seated the community superadmin in {seated} communities")
        await session.commit()

        # After that sweep, so the platform owner keeps the seat here rather
        # than sharing it: this community's seat is a platform role, not the
        # demo account the other communities get.
        print("\n  --- Operations community: intake, set up ---")
        ops_guild = await operations.seed(session, ids, users)
        print(
            f"  {operations.OPERATIONS_GUILD_NAME} (community {ops_guild.id}): "
            f"{len(IntakeStream)} streams bound"
        )
        await session.commit()

        print("  Filing tickets, reports and a hold...")
        filed = await tickets.seed(session, users, seeded["primary"])
        print(f"  {filed} cases waiting in {operations.OPERATIONS_GUILD_NAME}")

    save_state(ids)

    print("\nDone! Dev data seeded successfully.")
    print(f"  {len(ids['users'])} users (password: changeme)")
    print(
        f"  {len(ids['guilds']) + 1} communities "
        f"({len(ids['initiatives'])} initiatives); community directory on"
    )
    print(f"  {len(ids['projects'])} projects, {len(ids['tasks'])} tasks")
    print(f"  {len(ids['files'])} files, {len(ids['tags'])} tags")
    print(f"  {len(ids['queues'])} queues, {len(ids['queue_items'])} queue items")
    print(
        f"  {len(ids['counter_groups'])} counter groups, "
        f"{len(ids['counters'])} counters"
    )
    print(
        f"  {len(ids['calendar_events'])} calendar events, "
        f"{len(ids['calendar_event_attendees'])} attendees"
    )
    print(
        f"  {len(ids['libraries'])} libraries, "
        f"{len(ids['library_items'])} pictures "
        f"({len(ids['library_item_versions'])} versions)"
    )
    print(
        f"  {len(ids['posts'])} posts "
        f"({len(ids['post_polls'])} polls, "
        f"{len(ids['post_poll_votes'])} votes, "
        f"{len(ids['post_reads'])} read receipts)"
    )
    print(
        f"  {len(ids['property_definitions'])} property definitions, "
        f"{len(ids['property_values'])} property values"
    )
    print(f"  {len(ids['comments'])} comments")
    print(
        f"  {len(ids['bookmarks'])} bookmarks, "
        f"{len(ids['content_references'])} content references"
    )
    print(
        f"  {len(ids['access_grants'])} PAM access grants "
        "(pending/live/break-glass/denied/expired)"
    )
    print(
        f"\n  Owner login: {settings.FIRST_OWNER_EMAIL} / {settings.FIRST_OWNER_PASSWORD}"
    )
    print("  Community admins (password: changeme):")
    print("    admin1@example.com (community 1), admin2@example.com (community 2),")
    print("    admin3@example.com (community 3), admin4@example.com (communities 1+3)")
    print("  Regular members: user1@example.com .. user8@example.com / changeme")
    print("    (never community admins; user1 + user6 are initiative PMs,")
    print("     user7 is in community 1 with no initiative membership)")
    print("  Platform-role users (password: changeme):")
    print("    owner@example.com, operator@example.com, moderator@example.com,")
    print("    support@example.com, member@example.com")
    print("  Community superadmin: superadmin@example.com / changeme")
    print("    (the compliance seat, in every seeded community)")


if __name__ == "__main__":
    asyncio.run(clean() if "--clean" in sys.argv else seed())
