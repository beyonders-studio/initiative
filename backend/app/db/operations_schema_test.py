"""A filer reads their own cases, and only what of them is theirs to read;
anybody reads the published ideas, and of their fields only the two the
board's binding names.

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

from app.api.deps import (
    FilerAccessError,
    establish_filer_access,
    establish_ideas_access,
)
from app.core.intake import IntakeStream
from app.db import operations_schema
from app.db.request_context import SystemGuild, Unattributed
from app.db.session import set_rls_context
from app.db.tenancy import OPERATIONS_TABLES
from app.models.tenant._mixins import ActorKind
from app.models.tenant.comment import Comment, CommentAudience
from app.models.tenant.evidence import Evidence
from app.models.tenant.intake import IntakeBinding, IntakeCase
from app.models.tenant.metadata import MetadataDefinition, MetadataType, MetadataValue
from app.models.tenant.task import Task, TaskStatusCategory, TaskType
from app.services.platform.intake import CaseFiler, open_case
from app.testing import (
    create_guild,
    create_initiative,
    create_project,
    create_property_definition,
    create_property_value,
    create_task,
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


@pytest.fixture
async def ideas(session):
    """An operations community whose Ideas board names its category and
    release fields and its shipped status, with a shipped idea, an open one
    and a draft, each with a category and the first two with a release, and
    the shipped one with a field of the team's own."""
    staff = await create_user(session)
    guild = await create_guild(session, creator=staff)
    initiative = await create_initiative(session, guild, staff)
    project = await create_project(session, initiative, staff)
    await make_operations_community(session, guild.id)
    shipped = await create_task(
        session, project, title="Shipped", status_category=TaskStatusCategory.done
    )
    open_idea = await create_task(session, project, title="Open")
    await set_rls_context(session, SystemGuild(guild.id))
    draft_type = (
        await session.exec(
            select(TaskType.id)
            .where(TaskType.project_id == project.id)
            .where(TaskType.id != shipped.task_type_id)
        )
    ).first()
    draft = await create_task(session, project, title="Draft", task_type_id=draft_type)
    category = await create_property_definition(
        session,
        initiative,
        name="Category",
        type=MetadataType.select,
        options=[{"value": "files", "label": "Files"}],
        project=project,
    )
    release = await create_property_definition(
        session, initiative, name="Release", project=project
    )
    secret = await create_property_definition(
        session, initiative, name="Secret", project=project
    )
    for task in (shipped, open_idea, draft):
        await create_property_value(session, task, category, value_text="files")
    for task in (shipped, open_idea):
        await create_property_value(session, task, release, value_text="1.0.0")
    await create_property_value(session, shipped, secret, value_text="Internal.")
    await set_rls_context(session, SystemGuild(guild.id))
    session.add(
        IntakeBinding(
            stream=IntakeStream.ideas,
            project_id=project.id,
            task_type_id=shipped.task_type_id,
            category_field_id=category.id,
            release_field_id=release.id,
            shipped_status_id=shipped.task_status_id,
        )
    )
    await session.commit()
    await set_rls_context(session, Unattributed())
    yield {
        "staff": staff,
        "shipped": shipped.id,
        "open": open_idea.id,
        "category": category.id,
        "release": release.id,
    }
    await operations_schema.deprovision_operations(guild.id)


async def _read_as_idea_reader(role_session, user, statement, *, kept=False):
    """Run one read routed as ``user`` reading the published ideas, or nobody
    signed in; with ``kept``, on a connection that keeps every plan whole."""
    routed = await role_session("app_user")
    try:
        if kept:
            await routed.exec(text("SET plan_cache_mode = force_generic_plan"))
            await routed.commit()
        await establish_ideas_access(routed, user)
        return (await routed.exec(statement)).all()
    finally:
        await routed.close()


@pytest.mark.parametrize("kept", [False, True])
async def test_anybody_reads_an_ideas_category_and_shipped_release_alone(
    role_session, ideas, kept
):
    """The category of each published idea, the release of the one in the
    shipped status, and the category field's options; no draft's, and no
    other field's."""
    values = await _read_as_idea_reader(
        role_session,
        None,
        select(
            MetadataValue.entity_id, MetadataValue.property_id, MetadataValue.value_text
        ),
        kept=kept,
    )
    assert sorted(values) == sorted(
        [
            (ideas["shipped"], ideas["category"], "files"),
            (ideas["shipped"], ideas["release"], "1.0.0"),
            (ideas["open"], ideas["category"], "files"),
        ]
    )
    fields = await _read_as_idea_reader(
        role_session, None, select(MetadataDefinition.id, MetadataDefinition.options)
    )
    assert fields == [(ideas["category"], [{"value": "files", "label": "Files"}])]


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT value_number FROM metadata_values",
        "SELECT value_user_id FROM metadata_values",
        "SELECT name FROM metadata_definitions",
        "SELECT name FROM files",
        "SELECT role_id FROM initiative_members",
    ],
)
async def test_an_idea_reader_is_refused_every_other_column(
    role_session, ideas, statement
):
    with pytest.raises(DBAPIError, match="permission denied"):
        await _read_as_idea_reader(role_session, None, text(statement))


@pytest.mark.parametrize(
    "table",
    sorted(
        set(operations_schema.IDEAS_POLICY_READS)
        - set(operations_schema.IDEAS_TABLE_ACCESS)
    ),
)
async def test_an_idea_reader_reads_no_row_its_policies_only_consult(
    role_session, ideas, table
):
    """Granted so the community's own policies can be evaluated: no row of
    them reads, even for a member of the community."""
    column = operations_schema.IDEAS_POLICY_READS[table][0]
    rows = await _read_as_idea_reader(
        role_session, ideas["staff"], text(f"SELECT {column} FROM {table}")
    )
    assert rows == []
