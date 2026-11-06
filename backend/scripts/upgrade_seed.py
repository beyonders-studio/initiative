"""Fill a database with one community's worth of content, using the checkout's
own test factories.

Run from the ``backend/`` directory of *any* release checkout, with that
release's environment: ``python <path>/upgrade_seed.py``. Every name it imports
is resolved in that release, so the rows are the ones that release writes —
which is what an upgrade from it has to carry. It is kept to the factories
every supported release has; ``upgrade_from_release.py`` runs it against the
release an upgrade starts from, and against the current tree.

The connection is the database owner, as the test suite's is:
``DATABASE_URL_BOOTSTRAP`` where the logins are given explicitly, and
``DATABASE_URL`` where one owner URL is all the app is given: the factories write shared and guild tables directly, the way
fixtures do, rather than through a request.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))

from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402
from sqlmodel.ext.asyncio.session import AsyncSession  # noqa: E402

import app.models.platform.guild as guild_models  # noqa: E402
from app.models.tenant.task import Task  # noqa: E402
import app.testing as testing  # noqa: E402
from app.testing import (  # noqa: E402
    TOOL_FACTORIES,
    checklist_items,
    create_calendar_event,
    create_comment,
    create_counter,
    create_guild,
    create_guild_membership,
    create_initiative,
    create_initiative_member,
    create_project,
    create_property_definition,
    create_reaction,
    create_tag,
    create_task,
    create_upload,
    create_user,
    create_wiki_page,
    enable_all_tools,
)
from app.testing.schema_harness import install_guild_routing  # noqa: E402

# The community role enum was GuildRole before 0.75.
CommunityRole = getattr(guild_models, "CommunityRole", None) or getattr(
    guild_models, "GuildRole"
)


async def seed(session: AsyncSession) -> None:
    owner = await create_user(session)
    member = await create_user(session)
    guild = await create_guild(session, creator=owner)
    await create_guild_membership(session, user=member, guild=guild)
    await create_guild_membership(
        session, user=await create_user(session), guild=guild, role=CommunityRole.admin
    )

    initiative = await create_initiative(session, guild, owner)
    await create_initiative_member(session, initiative, member)
    initiative = await enable_all_tools(session, initiative)

    # One of every tool, from the registry, so a tool added later is seeded
    # without an edit here.
    tools = {
        tool: await factory(session, initiative, owner)
        for tool, factory in TOOL_FACTORIES.items()
    }
    by_name = {tool.value: entity for tool, entity in tools.items()}

    project = await create_project(session, initiative, owner)
    task = await create_task(
        session,
        project,
        assignees=[member],
        checklist=checklist_items("first", "second"),
    )
    definition = await create_property_definition(session, initiative)
    # A release before property values became one table has one factory per
    # tool; this one has a single factory for every target.
    set_value = getattr(testing, "create_property_value", None) or getattr(
        testing, "create_task_property_value"
    )
    await set_value(session, task, definition, value_text="seeded")

    # The files tool was the documents tool before 0.75, its factory and the
    # comment's parent argument named for it.
    file_kind = "file" if hasattr(testing, "create_file") else "document"
    file = await getattr(testing, f"create_{file_kind}")(session, initiative, member)
    comment = await create_comment(session, member, task=task)
    await create_comment(session, owner, **{file_kind: file})
    await create_reaction(session, owner, comment=comment)

    await create_tag(session, guild)
    await create_upload(session, guild, owner)
    if "queue" in by_name:
        # A release with queues gives the upgrade an item to make a task of.
        await testing.create_queue_item(session, by_name["queue"])
    await create_counter(session, by_name["counter_group"])
    await create_calendar_event(session, by_name["calendar"], owner)
    await create_wiki_page(session, by_name["wiki"], owner)

    # Repeats and an all-day event in the shape this release stores, so an
    # upgrade has them to convert: JSON before RRULE, RRULE lines since.
    monday = datetime(2026, 10, 4, 22, 30, tzinfo=timezone.utc)
    if hasattr(Task, "recurrence_until"):
        task_repeat = event_repeat = "RRULE:FREQ=WEEKLY;BYDAY=SU"
    else:
        task_repeat = {"frequency": "weekly", "weekdays": ["monday"], "ends": "never"}
        event_repeat = json.dumps(task_repeat)
    await create_task(session, project, due_date=monday, recurrence=task_repeat)
    await create_calendar_event(
        session,
        by_name["calendar"],
        owner,
        start_at=monday,
        end_at=monday + timedelta(hours=1),
        recurrence=event_repeat,
    )
    await create_calendar_event(
        session,
        by_name["calendar"],
        owner,
        all_day=True,
        start_at=monday,
        end_at=monday + timedelta(hours=23, minutes=59, seconds=59),
    )


async def main() -> None:
    install_guild_routing()
    engine = create_async_engine(
        os.environ.get("DATABASE_URL_BOOTSTRAP") or os.environ["DATABASE_URL"]
    )
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await seed(session)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
