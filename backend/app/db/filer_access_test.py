"""A filer reads their own cases, and only what of them is theirs to read.

Every assertion here runs as the request login, routed into the operations
community's filer role through the seam — the privilege boundary production
has. A grant or a row that should not be reachable is asserted refused by the
database, not filtered by the code under test.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlmodel import select

from app.api.deps import FilerAccessError, establish_filer_access
from app.core.intake import IntakeStream
from app.db import filer_access
from app.db.request_context import SystemGuild, Unattributed
from app.db.session import set_rls_context
from app.models.platform.app_setting import AppSetting
from app.models.tenant.comment import Comment, CommentAudience
from app.models.tenant.evidence import Evidence
from app.models.tenant.intake import IntakeBinding, IntakeCase
from app.models.tenant.task import Task
from app.services.platform.intake import CaseFiler, open_case
from app.testing import (
    create_guild,
    create_initiative,
    create_project,
    create_user,
)


async def _point_at(session, guild_id: int | None) -> None:
    await set_rls_context(session, Unattributed())
    row = (await session.exec(select(AppSetting).where(AppSetting.id == 1))).first()
    if row is None:
        row = AppSetting(id=1)
    row.operations_guild_id = guild_id
    session.add(row)
    await session.commit()


@pytest.fixture
async def operations(session):
    """An operations community with support bound, its filer role in place,
    and two people's cases in it."""
    staff = await create_user(session)
    guild = await create_guild(session, creator=staff)
    initiative = await create_initiative(session, guild, staff)
    project = await create_project(session, initiative, staff)
    await _point_at(session, guild.id)
    await set_rls_context(session, SystemGuild(guild.id))
    session.add(IntakeBinding(stream=IntakeStream.support, project_id=project.id))
    await session.commit()
    await filer_access.provision_filer_access(guild.id)

    await set_rls_context(session, Unattributed())
    asker = await create_user(session)
    other = await create_user(session)
    mine = await open_case(
        IntakeStream.support,
        title="Staff renamed this",
        body="Internal summary.",
        filer=CaseFiler(user_id=asker.id, subject="Lost my phone", words="Help."),
    )
    theirs = await open_case(
        IntakeStream.support,
        title="Someone else's",
        filer=CaseFiler(user_id=other.id, subject="Not yours", words="Private."),
    )
    assert mine is not None and theirs is not None

    await set_rls_context(session, SystemGuild(guild.id))
    session.add(
        Comment(task_id=mine.task_id, content="Staff only.", created_by=staff.id)
    )
    session.add(
        Comment(
            task_id=mine.task_id,
            content="Have you tried a recovery code?",
            created_by=staff.id,
            audience=CommentAudience.filer,
        )
    )

    def attached(case_id: int, by: int, name: str) -> Evidence:
        return Evidence(
            case_id=case_id,
            origin_guild_id=guild.id,
            origin_id=uuid.uuid4(),
            storage_key=f"evidence-{uuid.uuid4().hex}.iev",
            size_bytes=1,
            content_type="text/plain",
            display_name=name,
            sha256="0" * 64,
            wrapped_dek=b"sealed",
            kek_version=1,
            created_by=by,
        )

    session.add(attached(mine.case_id, asker.id, "mine.txt"))
    session.add(attached(mine.case_id, staff.id, "staff-notes.txt"))
    session.add(attached(theirs.case_id, other.id, "theirs.txt"))
    await session.commit()
    await set_rls_context(session, Unattributed())
    yield {
        "guild": guild,
        "asker": asker,
        "mine": mine.task_id,
        "theirs": theirs.task_id,
    }
    await filer_access.deprovision_filer_access(guild.id)


async def _read_as_filer(role_session, user, statement):
    """Run one read routed as ``user``'s filer access, and close the session,
    so nothing it locked outlives the read."""
    routed = await role_session("app_user")
    try:
        await establish_filer_access(routed, user)
        return (await routed.exec(statement)).all()
    finally:
        await routed.close()


async def test_a_filer_reads_their_own_case_and_nobody_elses(role_session, operations):
    cases = await _read_as_filer(
        role_session,
        operations["asker"],
        select(IntakeCase.task_id, IntakeCase.filer_subject),
    )
    assert cases == [(operations["mine"], "Lost my phone")]


async def test_a_filer_reads_what_is_said_to_them_and_nothing_else(
    role_session, operations
):
    said = await _read_as_filer(
        role_session,
        operations["asker"],
        select(Comment.content).where(Comment.task_id == operations["mine"]),
    )
    assert sorted(said) == ["Have you tried a recovery code?", "Help."]


async def test_a_filer_reads_the_files_they_sent_and_not_their_keys(
    role_session, operations
):
    sent = await _read_as_filer(
        role_session, operations["asker"], select(Evidence.display_name)
    )
    assert sent == ["mine.txt"]
    with pytest.raises(DBAPIError, match="permission denied"):
        await _read_as_filer(
            role_session, operations["asker"], select(Evidence.wrapped_dek)
        )


async def test_a_filer_reads_their_task_s_status_and_not_its_words(
    role_session, operations
):
    (status_id,) = await _read_as_filer(
        role_session, operations["asker"], select(Task.task_status_id)
    )
    assert status_id is not None
    with pytest.raises(DBAPIError, match="permission denied"):
        await _read_as_filer(role_session, operations["asker"], select(Task.title))


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT task_id, filer_subject FROM intake_cases",
        "SELECT id, task_status_id, updated_at FROM tasks",
        # As the service reads it: text, so the driver decodes no enum.
        "SELECT id, category::text FROM task_statuses",
        "SELECT id, awaiting_filer_status_id FROM intake_bindings",
        "SELECT id, content, created_by FROM comments",
        "SELECT id, case_id, display_name FROM evidence",
    ],
)
async def test_a_filer_reads_on_a_connection_whose_plans_are_kept(
    role_session, operations, statement
):
    """A connection that has served the gate functions before keeps their
    plans whole, every branch included. What a filer reads must still be
    readable then, which forcing kept plans from the start shows."""
    routed = await role_session("app_user")
    try:
        await routed.exec(text("SET plan_cache_mode = force_generic_plan"))
        await routed.commit()
        await establish_filer_access(routed, operations["asker"])
        rows = (await routed.exec(text(statement))).all()
    finally:
        await routed.close()
    assert rows


@pytest.mark.parametrize(
    "table",
    [
        "initiatives",
        "initiative_members",
        "uploads",
        "metadata_values",
        "task_assignees",
    ],
)
async def test_a_filer_is_refused_the_rest_of_the_community(
    role_session, operations, table
):
    with pytest.raises(DBAPIError, match="permission denied"):
        await _read_as_filer(
            role_session, operations["asker"], text(f"SELECT 1 FROM {table} LIMIT 1")
        )


async def test_there_is_no_filer_role_outside_the_operations_community(
    session, role_session, operations
):
    elsewhere = await create_guild(session)
    await set_rls_context(session, Unattributed())

    await filer_access.reconcile_filer_access(operations["guild"].id)

    present = (
        await session.exec(
            text("SELECT rolname FROM pg_roles WHERE rolname ~ :p"),
            params={"p": filer_access.filer_role_pattern()},
        )
    ).all()
    assert [row[0] for row in present] == [
        filer_access.filer_role_name(operations["guild"].id)
    ]
    assert filer_access.filer_role_name(elsewhere.id) not in {r[0] for r in present}


async def test_a_moved_operations_community_takes_the_role_with_it(
    session, role_session, operations
):
    moved_to = await create_guild(session)
    await set_rls_context(session, Unattributed())

    await filer_access.reconcile_filer_access(moved_to.id)

    present = {
        row[0]
        for row in (
            await session.exec(
                text("SELECT rolname FROM pg_roles WHERE rolname ~ :p"),
                params={"p": filer_access.filer_role_pattern()},
            )
        ).all()
    }
    assert present == {filer_access.filer_role_name(moved_to.id)}
    await filer_access.deprovision_filer_access(moved_to.id)


async def test_with_no_operations_community_there_is_nothing_to_route_into(
    session, role_session
):
    await _point_at(session, None)
    routed = await role_session("app_user")
    user = await create_user(session)

    with pytest.raises(FilerAccessError):
        await establish_filer_access(routed, user)
