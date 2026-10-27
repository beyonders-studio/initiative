"""The query endpoint: who may ask, and what they get back.

The interesting test is the last one. A query surface is only as safe as its
answer to "does this return more than the asker could already reach", and the
way to know is to ask two people with different standing the same question.
"""

import json
from typing import Any
from pathlib import Path


from app.core.messages import QueryMessages
from app.core.relationships import RelationshipType
from app.core.search import SearchEntityType
from app.db.session import routed_context
from app.models.platform.guild import CommunityRole
from app.services.fields.spec import FieldType
from app.services.marketplace import builtin
from app.services.tenant import relationships as relationships_service
from app.services.tenant.dashboard_definition import WIDGET_SPECS
from app.testing import (
    create_file,
    create_initiative_member,
    create_project,
    create_relationship,
    create_task,
)


async def test_a_member_can_run_a_query(client, acting_user):
    actor = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    response = await client.post(
        actor.g("/query"),
        json={"sql": "SELECT count(*) AS n FROM projects"},
        headers=actor.headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["columns"] == [
        {"name": "n", "type": "number", "grain": None, "date_only": False}
    ]
    assert body["truncated"] is False


async def test_the_rows_come_back_positionally(client, acting_user):
    actor = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    response = await client.post(
        actor.g("/query"),
        json={"sql": "SELECT 1 AS a, 2 AS b FROM projects LIMIT 1"},
        headers=actor.headers,
    )
    assert response.status_code == 200
    assert response.json()["columns"] == [
        {"name": "a", "type": "number", "grain": None, "date_only": False},
        {"name": "b", "type": "number", "grain": None, "date_only": False},
    ]


async def test_a_statement_the_surface_refuses_says_which_word(client, acting_user):
    actor = await acting_user(guild_role=CommunityRole.member, initiative=True)
    response = await client.post(
        actor.g("/query"),
        json={"sql": "SELECT id FROM users"},
        headers=actor.headers,
    )
    assert response.status_code == 400
    assert response.json()["detail"] == QueryMessages.UNKNOWN_RELATION


async def test_a_write_is_refused_before_it_reaches_the_database(client, acting_user):
    actor = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    response = await client.post(
        actor.g("/query"),
        json={"sql": "DELETE FROM tasks"},
        headers=actor.headers,
    )
    assert response.status_code == 400
    assert response.json()["detail"] == QueryMessages.READ_ONLY


async def test_a_statement_the_database_cannot_finish_is_a_refusal(client, acting_user):
    """It parsed and resolved; the database had the last word on it. That is
    still something the reader can correct, so it comes back as one."""
    actor = await acting_user(guild_role=CommunityRole.member, initiative=True)
    response = await client.post(
        actor.g("/query"),
        json={"sql": "SELECT count(*) / 0 AS n FROM projects"},
        headers=actor.headers,
    )
    assert response.status_code == 400
    assert response.json()["detail"] == QueryMessages.EXECUTION_FAILED


async def test_describing_a_statement_names_its_columns_and_types(client, acting_user):
    actor = await acting_user(guild_role=CommunityRole.member, initiative=True)
    response = await client.post(
        actor.g("/query/describe"),
        json={"sql": "SELECT name, created_at, archived_at, id FROM projects"},
        headers=actor.headers,
    )
    assert response.status_code == 200
    assert response.json()["columns"] == [
        {"name": "name", "type": "text", "grain": None, "date_only": False},
        {"name": "created_at", "type": "date", "grain": None, "date_only": False},
        {"name": "archived_at", "type": "date", "grain": None, "date_only": False},
        {"name": "id", "type": "number", "grain": None, "date_only": False},
    ]


async def test_calendar_date_kind_survives_describing_and_running(
    client, session, acting_user
):
    actor = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await create_project(session, actor.initiative, actor.user)
    sql = (
        "SELECT date '2026-08-03' AS day,"
        " timestamp '2026-08-03 00:00:00' AS local_at,"
        " timestamptz '2026-08-03T00:00:00Z' AS at FROM projects LIMIT 1"
    )
    for route in ("/query/describe", "/query"):
        response = await client.post(
            actor.g(route), json={"sql": sql}, headers=actor.headers
        )
        assert response.status_code == 200, response.text
        assert [column["date_only"] for column in response.json()["columns"]] == [
            True,
            False,
            False,
        ]
        if route == "/query":
            assert response.json()["rows"] == [
                [1785715200000, 1785715200000, 1785715200000]
            ]


async def test_a_closed_vocabulary_describes_as_one(client, acting_user):
    """``priority`` is a database enum, which is the same signal the field
    registry reads — so a query's shape and a dataset's fields say it the
    same way."""
    actor = await acting_user(guild_role=CommunityRole.member, initiative=True)
    response = await client.post(
        actor.g("/query/describe"),
        json={"sql": "SELECT priority FROM tasks"},
        headers=actor.headers,
    )
    assert response.status_code == 200
    assert response.json()["columns"] == [
        {"name": "priority", "type": "enum", "grain": None, "date_only": False}
    ]


async def test_a_field_that_names_a_row_describes_as_a_reference(client, acting_user):
    """``project_id`` holds an integer and means a project. A query's shape says
    that in the same word the dataset's fields do."""
    actor = await acting_user(guild_role=CommunityRole.member, initiative=True)
    response = await client.post(
        actor.g("/query/describe"),
        json={"sql": "SELECT project_id, title FROM tasks"},
        headers=actor.headers,
    )
    assert response.status_code == 200
    assert response.json()["columns"] == [
        {"name": "project_id", "type": "reference", "grain": None, "date_only": False},
        {"name": "title", "type": "text", "grain": None, "date_only": False},
    ]


async def test_describing_runs_nothing(client, session, acting_user):
    """A statement that would fail while running still describes, because
    describing plans and does not execute."""
    actor = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await create_project(session, actor.initiative, actor.user)
    described = await client.post(
        actor.g("/query/describe"),
        json={"sql": "SELECT count(*) / 0 AS n FROM projects"},
        headers=actor.headers,
    )
    ran = await client.post(
        actor.g("/query"),
        json={"sql": "SELECT count(*) / 0 AS n FROM projects"},
        headers=actor.headers,
    )
    assert described.status_code == 200
    assert described.json()["columns"] == [
        {"name": "n", "type": "number", "grain": None, "date_only": False}
    ]
    assert ran.status_code == 400


async def test_a_statement_that_does_not_resolve_does_not_describe(client, acting_user):
    actor = await acting_user(guild_role=CommunityRole.member, initiative=True)
    response = await client.post(
        actor.g("/query/describe"),
        json={"sql": "SELECT id FROM users"},
        headers=actor.headers,
    )
    assert response.status_code == 400
    assert response.json()["detail"] == QueryMessages.UNKNOWN_RELATION


async def test_a_non_member_cannot_reach_the_guilds_queries(client, acting_user):
    resident = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    outsider = await acting_user(guild_role=CommunityRole.member)
    response = await client.post(
        resident.g("/query"),
        json={"sql": "SELECT count(*) AS n FROM projects"},
        headers=outsider.headers,
    )
    assert response.status_code == 403


async def test_a_query_returns_what_its_author_reaches_and_no_more(
    client, session, acting_user
):
    """Two members of one guild, one of them not in the initiative. The same
    statement answers differently, because the policies read who is asking."""
    author = await acting_user(guild_role=CommunityRole.member, initiative=True)
    await create_project(session, author.initiative, author.user)

    stranger = await acting_user(guild_role=CommunityRole.member, guild=author.guild)

    statement = {"sql": "SELECT count(*) AS n FROM projects"}
    mine = await client.post(author.g("/query"), json=statement, headers=author.headers)
    theirs = await client.post(
        stranger.g("/query"), json=statement, headers=stranger.headers
    )

    assert mine.status_code == 200
    assert theirs.status_code == 200
    assert mine.json()["rows"] == [[1]]
    assert theirs.json()["rows"] == [[0]]


async def test_a_built_query_answers_with_its_sql_and_its_shape(client, acting_user):
    """The builder describes and the server writes the SQL, so what comes back
    is both halves the builder needs: the statement to store, and the columns
    its slot pickers offer."""
    actor = await acting_user(guild_role=CommunityRole.member, initiative=True)
    response = await client.post(
        actor.g("/query/build"),
        json={
            "dataset": "tasks",
            "columns": [
                {"field": "priority"},
                {"field": "*", "aggregate": "count", "alias": "tasks"},
            ],
            "group_by": ["priority"],
            "order_by": {"field": "tasks", "descending": True},
            "limit": 10,
        },
        headers=actor.headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["sql"].startswith("SELECT priority, count(*) AS tasks FROM tasks")
    assert body["columns"] == [
        {"name": "priority", "type": "enum", "grain": None, "date_only": False},
        {"name": "tasks", "type": "number", "grain": None, "date_only": False},
    ]
    assert body["relations"] == ["tasks"]


async def test_a_built_query_can_be_run_as_it_came_back(client, session, acting_user):
    """The whole point of building server-side: a statement somebody clicked
    together is one this surface will run."""
    actor = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await create_project(session, actor.initiative, actor.user)
    built = await client.post(
        actor.g("/query/build"),
        json={"dataset": "projects", "columns": [{"field": "*", "aggregate": "count"}]},
        headers=actor.headers,
    )
    assert built.status_code == 200
    ran = await client.post(
        actor.g("/query"), json={"sql": built.json()["sql"]}, headers=actor.headers
    )
    assert ran.status_code == 200
    assert ran.json()["rows"] == [[1]]


async def test_a_built_query_brackets_what_it_was_told_to(client, session, acting_user):
    """ "High or urgent, and mine" is one description and two words. What comes
    back has to be a statement this surface runs, brackets and all."""
    actor = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    project = await create_project(session, actor.initiative, actor.user)
    await create_task(session, project, priority="high")
    await create_task(session, project, priority="low")

    built = await client.post(
        actor.g("/query/build"),
        json={
            "dataset": "tasks",
            "columns": [{"field": "*", "aggregate": "count", "alias": "n"}],
            "where": [
                {
                    "logic": "or",
                    "conditions": [
                        {"field": "priority", "op": "eq", "value": "high"},
                        {"field": "priority", "op": "eq", "value": "urgent"},
                    ],
                },
                {"field": "archived_at", "op": "is_null", "value": True},
            ],
            "initiative_id": actor.initiative.id,
        },
        headers=actor.headers,
    )
    assert built.status_code == 200, built.json()
    assert "OR" in built.json()["sql"]

    ran = await client.post(
        actor.g("/query"),
        json={"sql": built.json()["sql"], "initiative_id": actor.initiative.id},
        headers=actor.headers,
    )
    assert ran.status_code == 200, ran.json()
    assert ran.json()["rows"] == [[1]]


async def test_a_built_query_keeps_a_date_a_distance(client, acting_user):
    """A tile asking about the next 30 days has to still be asking that next
    month, so the offset is what the statement carries."""
    actor = await acting_user(guild_role=CommunityRole.member, initiative=True)
    response = await client.post(
        actor.g("/query/build"),
        json={
            "dataset": "tasks",
            "columns": [{"field": "*", "aggregate": "count", "alias": "n"}],
            "where": [{"field": "due_date", "op": "lte", "value": {"relative": 30}}],
        },
        headers=actor.headers,
    )
    assert response.status_code == 200, response.json()
    assert "interval" in response.json()["sql"].lower()
    assert "now()" in response.json()["sql"].lower()


async def test_a_builder_cannot_describe_a_dataset_nobody_declared(client, acting_user):
    actor = await acting_user(guild_role=CommunityRole.member, initiative=True)
    response = await client.post(
        actor.g("/query/build"),
        json={"dataset": "pg_shadow", "columns": [{"field": "usename"}]},
        headers=actor.headers,
    )
    assert response.status_code == 400
    assert response.json()["detail"] == QueryMessages.UNKNOWN_RELATION


class TestReadingOneInitiative:
    """A statement names datasets, not a scope.

    Which means a reader in three initiatives asking about tasks gets all
    three, and a surface that belongs to one of them has to say so. What
    follows is that saying so works, and that saying it never widens.
    """

    async def test_a_query_answers_for_the_initiative_it_names(
        self, client, session, acting_user
    ):
        actor = await acting_user(guild_role=CommunityRole.member, initiative=True)
        await create_project(session, actor.initiative, actor.user)

        # A second initiative in the same guild, with the same reader in it
        # and a project of theirs in it — so what the narrowing removes is
        # something this reader can otherwise see.
        other = await acting_user(
            guild_role=CommunityRole.member, guild=actor.guild, initiative=True
        )
        await create_initiative_member(session, other.initiative, actor.user)
        await create_project(session, other.initiative, actor.user)

        both = await client.post(
            actor.g("/query"),
            json={"sql": "SELECT count(*) AS n FROM projects"},
            headers=actor.headers,
        )
        assert both.status_code == 200
        assert both.json()["rows"] == [[2]]

        one = await client.post(
            actor.g("/query"),
            json={
                "sql": "SELECT count(*) AS n FROM projects",
                "initiative_id": actor.initiative.id,
            },
            headers=actor.headers,
        )
        assert one.status_code == 200
        assert one.json()["rows"] == [[1]]

    async def test_naming_an_initiative_never_widens(
        self, client, session, acting_user
    ):
        """Naming one the reader is not in returns nothing, rather than its
        rows: the scope narrows an answer, it does not authorize one."""
        actor = await acting_user(guild_role=CommunityRole.member, initiative=True)
        stranger = await acting_user(
            guild_role=CommunityRole.member, guild=actor.guild, initiative=True
        )
        await create_project(session, stranger.initiative, stranger.user)

        response = await client.post(
            actor.g("/query"),
            json={
                "sql": "SELECT count(*) AS n FROM projects",
                "initiative_id": stranger.initiative.id,
            },
            headers=actor.headers,
        )
        assert response.status_code == 200
        assert response.json()["rows"] == [[0]]

    async def test_the_scope_reaches_a_dataset_through_its_parent(
        self, client, session, acting_user
    ):
        """Tasks resolve their initiative through their project, so narrowing
        has to follow the same path the policies do."""
        actor = await acting_user(guild_role=CommunityRole.member, initiative=True)
        mine = await create_project(session, actor.initiative, actor.user)
        await create_task(session, mine)

        other = await acting_user(
            guild_role=CommunityRole.member, guild=actor.guild, initiative=True
        )
        await create_initiative_member(session, other.initiative, actor.user)
        theirs = await create_project(session, other.initiative, actor.user)
        await create_task(session, theirs)

        both = await client.post(
            actor.g("/query"),
            json={"sql": "SELECT count(*) AS n FROM tasks"},
            headers=actor.headers,
        )
        assert both.json()["rows"] == [[2]]

        response = await client.post(
            actor.g("/query"),
            json={
                "sql": "SELECT count(*) AS n FROM tasks",
                "initiative_id": actor.initiative.id,
            },
            headers=actor.headers,
        )
        assert response.status_code == 200
        assert response.json()["rows"] == [[1]]


class TestEveryShippedDashboardDrawsItsShape:
    """The statements the built-in dashboards ship with.

    A widget declares the columns it draws; a statement returns some. Nothing
    checks that they agree at save time, because a shape is decided by what the
    database says a column holds — so it is checked here, against the real
    describe path, for every dashboard the build ships.
    """

    @staticmethod
    def _widgets():
        for path in sorted(Path(builtin.CATALOG_DIR).glob("*.json")):
            listing = json.loads(path.read_text())
            if listing.get("kind") != "dashboard":
                continue
            for widget in listing["definition"]["widgets"]:
                sql = widget.get("binding", {}).get("sql")
                if sql:
                    yield listing["public_id"], widget, sql

    async def test_each_widget_gets_the_columns_it_draws(self, client, acting_user):
        actor = await acting_user(guild_role=CommunityRole.admin, initiative=True)
        checked = 0
        for public_id, widget, sql in self._widgets():
            response = await client.post(
                actor.g("/query/describe"), json={"sql": sql}, headers=actor.headers
            )
            where = f"{public_id}/{widget['id']}"
            assert response.status_code == 200, f"{where}: {response.json()}"
            columns = [
                FieldType(column["type"]) for column in response.json()["columns"]
            ]
            shape = WIDGET_SPECS[widget["type"]].shape
            unfilled = _unfilled(columns, shape)
            assert not unfilled, f"{where} cannot fill {unfilled} from {columns}"
            checked += 1
        assert checked, "no shipped dashboard widgets were checked"


def _unfilled(columns: list[FieldType], shape) -> list[str]:
    """The required slots no column can fill — the inference the client runs,
    asked of the shipped statements before anybody installs one."""
    taken: set[int] = set()
    missing = []
    for slot in shape:
        found = next(
            (
                index
                for index, column in enumerate(columns)
                if index not in taken and column in slot.types
            ),
            None,
        )
        if found is None:
            if slot.required:
                missing.append(slot.name)
        else:
            taken.add(found)
    return missing


class TestGroupingByPerson:
    """The one thing the old sources could do that a statement could not.

    Naming a person needs the account projection, and the query surface had no
    way to reach one — so the cutover turned every "by assignee" widget into a
    grouping by project. It reaches the guild's own view of its members now,
    which is what makes this a question about *these* people.
    """

    async def test_work_can_be_counted_by_the_person_doing_it(
        self, client, session, acting_user
    ):
        actor = await acting_user(guild_role=CommunityRole.admin, initiative=True)
        project = await create_project(session, actor.initiative, actor.user)
        await create_task(session, project, assignees=[actor.user])
        await create_task(session, project, assignees=[actor.user])
        await create_task(session, project)

        response = await client.post(
            actor.g("/query"),
            json={
                "sql": (
                    "SELECT m.display_name AS person, count(*) AS tasks "
                    "FROM tasks t JOIN task_assignees a ON a.task_id = t.id "
                    "JOIN members m ON m.id = a.user_id "
                    "GROUP BY m.display_name"
                ),
                "initiative_id": actor.initiative.id,
            },
            headers=actor.headers,
        )
        assert response.status_code == 200, response.json()
        body = response.json()
        assert body["columns"] == [
            {"name": "person", "type": "text", "grain": None, "date_only": False},
            {"name": "tasks", "type": "number", "grain": None, "date_only": False},
        ]
        # The unassigned task is not somebody's work, so it is not a row here.
        assert body["rows"] == [[body["rows"][0][0], 2]]

    async def test_the_members_it_names_are_this_guilds(
        self, client, session, acting_user
    ):
        """A person is an account platform-wide; a member is a member of this
        guild. Listing them answers the second question."""
        actor = await acting_user(guild_role=CommunityRole.member, initiative=True)
        stranger = await acting_user(guild_role=CommunityRole.member, initiative=True)

        response = await client.post(
            actor.g("/query"),
            json={"sql": "SELECT id FROM members"},
            headers=actor.headers,
        )
        assert response.status_code == 200
        found = {row[0] for row in response.json()["rows"]}
        assert actor.user.id in found
        assert stranger.user.id not in found

    async def test_a_name_the_guild_does_not_render_falls_back_to_the_handle(
        self, client, session, acting_user
    ):
        """``display_name`` is what a chart groups by either way, so a member
        who set no name in the guild still gets a column of their own."""
        actor = await acting_user(guild_role=CommunityRole.member, initiative=True)
        response = await client.post(
            actor.g("/query"),
            json={"sql": "SELECT display_name FROM members"},
            headers=actor.headers,
        )
        assert response.status_code == 200
        names = [row[0] for row in response.json()["rows"]]
        assert names and all(name for name in names)


class TestAskingAboutTheReader:
    """One saved statement, two people, two answers.

    A dashboard is placed once and read by everybody in the initiative, so a
    tile that is about *you* cannot hold anybody's id. ``me`` is what makes the
    same stored SQL answer from whoever opened it.
    """

    async def test_the_same_statement_answers_from_whoever_asks(
        self, client, session, acting_user
    ):
        author = await acting_user(guild_role=CommunityRole.admin, initiative=True)
        # Both reach every row here, so the only thing that can separate the
        # two answers is who is asking.
        reader = await acting_user(
            guild_role=CommunityRole.admin,
            guild=author.guild,
            initiative=author.initiative,
            initiative_role="member",
        )
        project = await create_project(session, author.initiative, author.user)
        await create_task(session, project, assignees=[author.user])
        await create_task(session, project, assignees=[author.user])
        await create_task(session, project, assignees=[reader.user])

        sql = (
            "SELECT count(*) AS mine FROM tasks "
            "JOIN task_assignees a ON a.task_id = tasks.id "
            "WHERE a.user_id = me"
        )
        answers = {}
        for actor in (author, reader):
            response = await client.post(
                actor.g("/query"),
                json={"sql": sql, "initiative_id": author.initiative.id},
                headers=actor.headers,
            )
            assert response.status_code == 200, response.json()
            answers[actor.user.id] = response.json()["rows"][0][0]

        assert answers == {author.user.id: 2, reader.user.id: 1}

    async def test_it_reaches_the_person_through_a_relation(
        self, client, session, acting_user
    ):
        actor = await acting_user(guild_role=CommunityRole.admin, initiative=True)
        project = await create_project(session, actor.initiative, actor.user)
        await create_task(session, project, assignees=[actor.user])
        await create_task(session, project)

        response = await client.post(
            actor.g("/query"),
            json={
                "sql": ("SELECT count(*) AS mine FROM tasks WHERE assignee.id = me"),
                "initiative_id": actor.initiative.id,
            },
            headers=actor.headers,
        )
        assert response.status_code == 200, response.json()
        assert response.json()["rows"] == [[1]]

    async def test_a_file_is_read_through_the_version_it_shows(
        self, client, session, acting_user
    ):
        actor = await acting_user(guild_role=CommunityRole.admin, initiative=True)
        await create_file(
            session,
            actor.initiative,
            actor.user,
            file_url="/uploads/1/brief.pdf",
            file_size=2048,
        )

        response = await client.post(
            actor.g("/query"),
            json={
                "sql": (
                    "SELECT current_version.file_content_type AS type,"
                    " current_version.file_size AS size FROM files"
                ),
                "initiative_id": actor.initiative.id,
            },
            headers=actor.headers,
        )
        assert response.status_code == 200, response.json()
        assert response.json()["rows"] == [["application/pdf", 2048]]

    async def test_a_name_the_surface_keeps_is_refused_where_it_is_written(
        self, client, acting_user
    ):
        actor = await acting_user(guild_role=CommunityRole.member, initiative=True)
        response = await client.post(
            actor.g("/query"),
            json={"sql": "SELECT count(*) AS me FROM projects"},
            headers=actor.headers,
        )
        assert response.status_code == 400
        assert response.json()["detail"] == QueryMessages.RESERVED_NAME


async def test_a_trashed_task_is_not_in_the_answer(client, acting_user, session):
    """The trash is a place to recover from, not rows to report on.

    Asked as the guild admin, who manages the trash and reaches it where it is
    managed. A dashboard is not where it is managed: what a board counts should
    be the same figure for everybody reading it, whoever asks.
    """
    from datetime import datetime, timezone

    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    await create_task(session, a.project, title="kept")
    binned = await create_task(session, a.project, title="binned")

    counted = await client.post(
        a.g("/query"),
        json={"sql": "SELECT count(*) AS n FROM tasks"},
        headers=a.headers,
    )
    assert counted.json()["rows"] == [[2]]

    binned.deleted_at = datetime.now(timezone.utc)
    session.add(binned)
    await session.commit()

    counted = await client.post(
        a.g("/query"),
        json={"sql": "SELECT count(*) AS n FROM tasks"},
        headers=a.headers,
    )
    assert counted.json()["rows"] == [[1]], "a trashed task is still being counted"

    listed = await client.post(
        a.g("/query"),
        json={"sql": "SELECT title FROM tasks"},
        headers=a.headers,
    )
    assert listed.json()["rows"] == [["kept"]]


async def test_the_trash_is_still_reachable_where_it_is_managed(
    client, acting_user, session
):
    """The rule is the query surface's, not a new rule about the trash.

    Worth pinning beside the test above: the same reader, the same trashed row,
    asked for through the endpoint whose job is the trash — and it is there.
    """
    from datetime import datetime, timezone

    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    binned = await create_task(session, a.project, title="binned")
    task_id = binned.id

    binned.deleted_at = datetime.now(timezone.utc)
    session.add(binned)
    await session.commit()

    found = await client.get(
        a.g(f"/tasks/{task_id}"), params={"include_deleted": "true"}, headers=a.headers
    )
    assert found.status_code == 200, found.text


async def test_a_subtask_reads_its_parent_through_its_link(
    client, acting_user, session
):
    """A link names each end by kind and id, so a statement joins both: what
    a timeline groups its bars by. A link somebody took back is no link."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    parent = await create_task(session, a.project, title="parent")
    for title in ("child", "unlinked"):
        child = await create_task(session, a.project, title=title)
        edge = await create_relationship(
            session,
            a.guild,
            source=(SearchEntityType.task, child.id),
            target=(SearchEntityType.task, parent.id),
            relationship_type=RelationshipType.part_of,
        )
    await relationships_service.remove(session, edge, removed_by=a.user.id)
    await session.commit()

    response = await client.post(
        a.g("/query"),
        json={
            "sql": (
                "SELECT t.title, p.title AS parent FROM tasks t"
                " LEFT JOIN relationships r ON r.source_id = t.id"
                " AND r.source_type = 'task' AND r.relationship_type = 'part_of'"
                " LEFT JOIN tasks p ON p.id = r.target_id AND r.target_type = 'task'"
                " ORDER BY t.title"
            )
        },
        headers=a.headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["rows"] == [
        ["child", "parent"],
        ["parent", None],
        ["unlinked", None],
    ]


class TestEveryShippedDashboardReportsOnLiveWork:
    """What the shipped statements leave out.

    The check is invariance rather than wording: run each statement, add work
    that should not count — a task in the trash, an archived task, a task in a
    template project — and run it again. Every answer has to be the same one.

    Asked this way because the statements have no common shape. A count, a
    grouping and a list would each need their own assertion about which row is
    missing; "adding these rows changed nothing" is the property itself, and it
    holds whatever the statement returns.

    Run through the service rather than the endpoint. There are a few dozen
    statements and each is asked twice, and a test that spends a hundred
    requests to make one point is a slow test that also shares a rate limit
    with everything around it. The endpoint adds nothing here: the same
    executor, under the context the request would have established, is what
    decides the rows.
    """

    async def test_none_of_them_counts_work_that_is_not_live(
        self, client, acting_user, session, reading_as
    ):
        from datetime import datetime, timezone

        from app.services import query as query_service

        actor = await acting_user(guild_role=CommunityRole.admin, initiative=True)
        live = await create_project(session, actor.initiative, actor.user)
        await create_task(session, live, title="live work")

        statements = list(TestEveryShippedDashboardDrawsItsShape._widgets())
        assert statements, "no shipped dashboard widgets were checked"

        # What the request that runs a dashboard's tiles established: this
        # reader's own routing and standing, taken off the session the seam
        # routed rather than restated here.
        reader = await reading_as(actor.user.id, actor.guild.id)
        context = routed_context(reader)

        async def answers() -> dict[str, Any]:
            out = {}
            for public_id, widget, sql in statements:
                where = f"{public_id}/{widget['id']}"
                try:
                    result = await query_service.run(sql, context=context)
                except query_service.QueryError as refused:
                    raise AssertionError(f"{where}: {refused}") from refused
                out[where] = [list(row) for row in result.rows]
            return out

        before = await answers()

        # Three kinds of row that must not reach a dashboard. The trash is the
        # database's rule; the other two are the statements' own.
        binned = await create_task(session, live, title="binned")
        binned.deleted_at = datetime.now(timezone.utc)
        archived = await create_task(session, live, title="archived")
        archived.archived_at = datetime.now(timezone.utc)
        template = await create_project(
            session, actor.initiative, actor.user, is_template=True
        )
        await create_task(session, template, title="in a template")
        session.add_all([binned, archived])
        await session.commit()

        after = await answers()

        differing = {
            where: (before[where], rows)
            for where, rows in after.items()
            if before[where] != rows
        }
        assert not differing, (
            f"these statements counted work that is not live: {differing}"
        )
