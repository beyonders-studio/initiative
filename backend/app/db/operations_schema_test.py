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
from app.db import operations_schema
from app.db.request_context import SystemGuild, Unattributed
from app.db.session import set_rls_context
from app.db.tenancy import OPERATIONS_TABLES
from app.models.tenant._mixins import ActorKind
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
    make_operations_community,
)


@pytest.fixture
async def operations(session):
    """An operations community with support bound, its filer role in place,
    and two people's cases in it."""
    staff = await create_user(session)
    guild = await create_guild(session, creator=staff)
    initiative = await create_initiative(session, guild, staff)
    project = await create_project(session, initiative, staff)
    await make_operations_community(session, guild.id)
    await set_rls_context(session, SystemGuild(guild.id))
    session.add(IntakeBinding(stream=IntakeStream.support, project_id=project.id))
    await session.commit()

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
        Comment(
            task_id=mine.task_id,
            content="Staff only.",
            created_by=staff.id,
            created_by_kind=ActorKind.member,
        )
    )
    session.add(
        Comment(
            task_id=mine.task_id,
            content="Have you tried a recovery code?",
            created_by=staff.id,
            created_by_kind=ActorKind.member,
            audience=CommentAudience.filer,
        )
    )

    def attached(case_task_id: int, by: int, name: str) -> Evidence:
        return Evidence(
            case_task_id=case_task_id,
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
            created_by_kind=ActorKind.member,
        )

    session.add(attached(mine.task_id, asker.id, "mine.txt"))
    session.add(attached(mine.task_id, staff.id, "staff-notes.txt"))
    session.add(attached(theirs.task_id, other.id, "theirs.txt"))
    await session.commit()
    await set_rls_context(session, Unattributed())
    yield {
        "guild": guild,
        "asker": asker,
        "mine": mine.task_id,
        "theirs": theirs.task_id,
    }
    await operations_schema.deprovision_operations(guild.id)


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
        "SELECT id, case_task_id, display_name FROM evidence",
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

    await operations_schema.reconcile_operations()

    present = (
        await session.exec(
            text("SELECT rolname FROM pg_roles WHERE rolname ~ :p"),
            params={"p": operations_schema.filer_role_pattern()},
        )
    ).all()
    assert [row[0] for row in present] == [
        operations_schema.filer_role_name(operations["guild"].id)
    ]
    assert operations_schema.filer_role_name(elsewhere.id) not in {
        r[0] for r in present
    }


async def _has_tables(session, guild_id: int) -> set[str]:
    return {
        table
        for table in OPERATIONS_TABLES
        if (
            await session.exec(
                text("SELECT to_regclass(:t) IS NOT NULL"),
                params={"t": f'"guild_{guild_id}".{table}'},
            )
        ).one()[0]
    }


async def test_a_community_has_no_operations_tables_until_it_is_chosen(session):
    guild = await create_guild(session)
    await set_rls_context(session, Unattributed())
    assert await _has_tables(session, guild.id) == set()


async def test_a_moved_operations_community_takes_its_tables_and_role_with_it(
    session, role_session, operations
):
    left = operations["guild"].id
    moved_to = await create_guild(session)
    await set_rls_context(session, Unattributed())

    await make_operations_community(session, moved_to.id)
    await operations_schema.reconcile_operations()

    assert await _has_tables(session, left) == set()
    assert await _has_tables(session, moved_to.id) == OPERATIONS_TABLES
    # The cases' files go with them; the cases' tasks stay.
    assert (
        await session.exec(text(f'SELECT count(*) FROM "guild_{left}".evidence'))
    ).one()[0] == 0

    present = {
        row[0]
        for row in (
            await session.exec(
                text("SELECT rolname FROM pg_roles WHERE rolname ~ :p"),
                params={"p": operations_schema.filer_role_pattern()},
            )
        ).all()
    }
    assert present == {operations_schema.filer_role_name(moved_to.id)}
    await operations_schema.deprovision_operations(moved_to.id)


async def test_clearing_the_choice_keeps_the_tables_and_drops_the_role(
    session, operations
):
    await make_operations_community(session, None)
    await operations_schema.reconcile_operations()

    assert await _has_tables(session, operations["guild"].id) == OPERATIONS_TABLES
    assert (
        await session.exec(
            text("SELECT count(*) FROM pg_roles WHERE rolname ~ :p"),
            params={"p": operations_schema.filer_role_pattern()},
        )
    ).one()[0] == 0


async def test_with_no_operations_community_there_is_nothing_to_route_into(
    session, role_session
):
    await make_operations_community(session, None)
    routed = await role_session("app_user")
    user = await create_user(session)

    with pytest.raises(FilerAccessError):
        await establish_filer_access(routed, user)
