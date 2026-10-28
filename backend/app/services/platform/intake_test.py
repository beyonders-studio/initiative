"""The intake writer: routing, binding authority, and one case per incident."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import select

from app.core.intake import CaseField, IntakeStream
from app.db.session import set_rls_context
from app.models.platform.app_setting import AppSetting
from app.models.tenant.comment import Comment, CommentAudience
from app.models.tenant.intake import IntakeBinding, IntakeCase
from app.models.tenant.project import Project
from app.models.tenant.task import Task, TaskStatus, TaskStatusCategory
from app.services.tenant import task_statuses as task_statuses_service
from app.models.tenant.metadata import MetadataDefinition
from app.services.platform import case_activity
from app.services.platform import intake as intake_service
from app.services.platform.intake import CaseFiler, CaseRefs
from app.testing import (
    create_guild,
    create_initiative,
    create_project,
    create_task,
    create_user,
)
from app.db.request_context import SystemGuild, Unattributed


async def _point_platform_at(session, guild_id: int | None) -> None:
    """Set (or clear) ``app_settings.operations_guild_id``."""
    await set_rls_context(session, Unattributed())
    row = (await session.exec(select(AppSetting).where(AppSetting.id == 1))).first()
    if row is None:
        row = AppSetting(id=1)
    row.operations_guild_id = guild_id
    session.add(row)
    await session.commit()


async def _bind(session, *, guild, project, stream, **overrides):
    await set_rls_context(session, SystemGuild(guild.id))
    binding = IntakeBinding(stream=stream, project_id=project.id, **overrides)
    session.add(binding)
    await session.commit()
    await session.refresh(binding)
    return binding


@pytest.fixture
async def bound(session):
    """A deployment pointed at a guild with the support stream bound."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    initiative = await create_initiative(session, guild, user)
    project = await create_project(session, initiative, user)
    await _point_platform_at(session, guild.id)
    binding = await _bind(
        session,
        guild=guild,
        project=project,
        stream=IntakeStream.support.value,
    )
    return {
        "user": user,
        "guild": guild,
        "initiative": initiative,
        "project": project,
        "binding": binding,
    }


async def test_unbound_deployment_files_nothing(session):
    """Every install starts here: no pointer, so the writer is a no-op."""
    await _point_platform_at(session, None)
    outcome = await intake_service.open_case(
        IntakeStream.support, title="Cannot sign in"
    )
    assert outcome is None


async def test_pointer_without_a_binding_files_nothing(session):
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await _point_platform_at(session, guild.id)

    outcome = await intake_service.open_case(
        IntakeStream.support, title="Cannot sign in"
    )
    assert outcome is None


async def test_a_bound_stream_lands_a_task_in_its_project(session, bound):
    outcome = await intake_service.open_case(
        IntakeStream.support, title="Cannot sign in", body="It says my code expired."
    )
    assert outcome is not None
    assert outcome.opened is True

    await set_rls_context(session, SystemGuild(bound["guild"].id))
    task = (await session.exec(select(Task).where(Task.id == outcome.task_id))).one()
    assert task.project_id == bound["project"].id
    assert task.title == "Cannot sign in"
    assert task.description == "It says my code expired."


async def test_a_case_is_the_type_its_binding_names(session, bound):
    """A binding naming one of the project's types files cases as it; one
    naming a type since deleted files them as the project's default."""
    from app.models.tenant.task import TaskType
    from app.services.tenant import task_types as task_types_service

    await set_rls_context(session, SystemGuild(bound["guild"].id))
    task_type, bug = (
        await task_types_service.ensure_default_types(
            session, bound["project"].id, locale="en"
        )
    )[:2]
    binding = (
        await session.exec(
            select(IntakeBinding).where(IntakeBinding.id == bound["binding"].id)
        )
    ).one()
    binding.task_type_id = bug.id
    session.add(binding)
    bug.starting_values = {"description": "What happened?", "priority": "high"}
    bug.starting_values["checklist"] = ["Reproduce"]
    session.add(bug)
    await session.commit()

    # It starts as a Bug starts a task, under the body it came with.
    outcome = await intake_service.open_case(IntakeStream.support, title="Broken")
    assert outcome is not None
    await set_rls_context(session, SystemGuild(bound["guild"].id))
    filed = (await session.exec(select(Task).where(Task.id == outcome.task_id))).one()
    assert filed.task_type_id == bug.id
    assert (filed.description, filed.priority) == ("What happened?", "high")
    assert [item["text"] for item in filed.checklist] == ["Reproduce"]
    outcome = await intake_service.open_case(
        IntakeStream.support, title="Crash", body="It crashed on save."
    )
    assert outcome is not None
    await set_rls_context(session, SystemGuild(bound["guild"].id))
    told = (await session.exec(select(Task).where(Task.id == outcome.task_id))).one()
    assert told.description == "It crashed on save."
    filed = (await session.exec(select(Task).where(Task.id == filed.id))).one()

    # Its type goes, its tasks moved off it first; the binding lets go of it.
    for each in (filed, told):
        each.task_type_id = task_type.id
        session.add(each)
    await session.flush()
    await session.delete(
        (await session.exec(select(TaskType).where(TaskType.id == bug.id))).one()
    )
    await session.commit()
    outcome = await intake_service.open_case(IntakeStream.support, title="Again")
    assert outcome is not None
    await set_rls_context(session, SystemGuild(bound["guild"].id))
    again = (await session.exec(select(Task).where(Task.id == outcome.task_id))).one()
    assert again.task_type_id == task_type.id


async def test_a_cases_starting_outline_records_what_it_points_at(session, bound):
    """An outline naming a task lists the case among that task's references."""
    from app.core.relationships import RelationshipType
    from app.models.tenant.relationship import EntityRelationship
    from app.services.tenant import task_types as task_types_service

    guide = await create_task(session, bound["project"], title="Triage guide")
    await set_rls_context(session, SystemGuild(bound["guild"].id))
    default = await task_types_service.get_default_type(session, bound["project"].id)
    default.starting_values = {"description": f"Read #task[Guide]({guide.id})"}
    session.add(default)
    await session.commit()

    outcome = await intake_service.open_case(IntakeStream.support, title="Help")
    assert outcome is not None

    await set_rls_context(session, SystemGuild(bound["guild"].id))
    edges = await session.exec(
        select(EntityRelationship.target_type, EntityRelationship.target_id).where(
            EntityRelationship.source_type == "task",
            EntityRelationship.source_id == outcome.task_id,
            EntityRelationship.relationship_type == RelationshipType.references.value,
            EntityRelationship.removed_at.is_(None),
        )
    )
    assert set(edges.all()) == {("task", guide.id)}


async def test_a_system_opened_case_names_no_author(session, bound):
    """Nobody signed in created it, and ``created_by`` says so."""
    outcome = await intake_service.open_case(IntakeStream.support, title="Help")
    assert outcome is not None

    await set_rls_context(session, SystemGuild(bound["guild"].id))
    task = (await session.exec(select(Task).where(Task.id == outcome.task_id))).one()
    assert task.created_by is None


async def test_a_disabled_binding_receives_nothing(session, bound):
    await set_rls_context(session, SystemGuild(bound["guild"].id))
    binding = (
        await session.exec(
            select(IntakeBinding).where(IntakeBinding.id == bound["binding"].id)
        )
    ).one()
    binding.enabled = False
    session.add(binding)
    await session.commit()

    assert await intake_service.open_case(IntakeStream.support, title="Help") is None


async def test_a_stream_bound_to_an_archived_project_is_not_bound(session, bound):
    """A form is offered only where a case can land, and an archived project
    takes none — so asking whether the stream is bound answers the same way
    filing would."""
    assert await intake_service.stream_is_bound(IntakeStream.support) is True

    await set_rls_context(session, SystemGuild(bound["guild"].id))
    project = (
        await session.exec(select(Project).where(Project.id == bound["project"].id))
    ).one()
    project.archived_at = datetime.now(timezone.utc)
    session.add(project)
    await session.commit()

    assert await intake_service.stream_is_bound(IntakeStream.support) is False
    assert await intake_service.open_case(IntakeStream.support, title="Help") is None


async def test_refs_land_as_property_values(session, bound):
    outcome = await intake_service.open_case(
        IntakeStream.support,
        title="Help",
        refs=CaseRefs(subject_user=4242, subject_guild=7),
    )
    assert outcome is not None

    await set_rls_context(session, SystemGuild(bound["guild"].id))
    definitions = {
        definition.name: definition
        for definition in await session.exec(
            select(MetadataDefinition).where(
                MetadataDefinition.initiative_id == bound["initiative"].id
            )
        )
    }
    assert CaseField.subject_user.value in definitions
    assert CaseField.subject_guild.value in definitions


async def test_a_sustained_run_makes_one_case(session, bound):
    """Two crossings inside the window are one case, not two."""
    first = await intake_service.open_case(
        IntakeStream.support, title="Refused sign-ins", dedupe_key="refused:42"
    )
    second = await intake_service.open_case(
        IntakeStream.support, title="Refused sign-ins", dedupe_key="refused:42"
    )
    assert first is not None and second is not None
    assert second.task_id == first.task_id
    assert second.opened is False


async def test_every_occurrence_is_counted_and_moves_last_seen(session, bound):
    """``last_seen_at`` says when the source was last seen, not when we spoke."""
    start = datetime.now(timezone.utc)
    first = await intake_service.open_case(
        IntakeStream.support,
        title="Refused sign-ins",
        dedupe_key="refused:42",
        now=start,
    )
    assert first is not None

    soon = start + timedelta(minutes=1)
    await intake_service.open_case(
        IntakeStream.support,
        title="Refused sign-ins",
        dedupe_key="refused:42",
        now=soon,
    )

    await set_rls_context(session, SystemGuild(bound["guild"].id))
    case = (
        await session.exec(
            select(IntakeCase).where(IntakeCase.task_id == first.task_id)
        )
    ).one()
    assert case.occurrences == 2
    assert case.last_seen_at == soon
    # Inside the window, so the case is not marked again.
    assert case.noted_at == start


async def test_a_crossing_past_the_window_moves_the_mark(session, bound):
    start = datetime.now(timezone.utc)
    first = await intake_service.open_case(
        IntakeStream.support,
        title="Refused sign-ins",
        dedupe_key="refused:42",
        now=start,
    )
    assert first is not None

    later = start + timedelta(hours=2)
    again = await intake_service.open_case(
        IntakeStream.support,
        title="Refused sign-ins",
        dedupe_key="refused:42",
        now=later,
    )
    assert again is not None
    assert again.task_id == first.task_id
    assert again.opened is False

    await set_rls_context(session, SystemGuild(bound["guild"].id))
    case = (
        await session.exec(
            select(IntakeCase).where(IntakeCase.task_id == first.task_id)
        )
    ).one()
    assert case.last_seen_at == later
    assert case.noted_at == later


async def _notes_on(session, guild_id: int, task_id: int) -> list[Comment]:
    """What the platform has written on a case, oldest first."""
    await set_rls_context(session, SystemGuild(guild_id))
    return list(
        (
            await session.exec(
                select(Comment)
                .where(Comment.task_id == task_id)
                .where(Comment.system_kind.is_not(None))
                .order_by(Comment.id)
            )
        ).all()
    )


async def test_a_repeat_says_what_it_brought_on_the_case(session, bound):
    """A second report of the same thing carries somebody's words, so they
    reach the case every time — not only a counter moving underneath it."""
    start = datetime.now(timezone.utc)
    first = await intake_service.open_case(
        IntakeStream.support,
        title="Reported comment 7",
        body="It names my street.",
        dedupe_key="report:1:comment:7",
        now=start,
    )
    assert first is not None
    await intake_service.open_case(
        IntakeStream.support,
        title="Reported comment 7",
        body="And my workplace.",
        detail="And my workplace.",
        dedupe_key="report:1:comment:7",
        now=start + timedelta(minutes=1),
    )

    (note,) = await _notes_on(session, bound["guild"].id, first.task_id)
    assert "And my workplace." in note.content
    assert "2 times" in note.content
    assert note.created_by is None
    assert note.system_kind == case_activity.ActivityKind.repeat.value
    assert note.audience == CommentAudience.members


async def test_a_repeat_with_nothing_new_is_noted_once_per_window(session, bound):
    """A sustained run is a trail of recurrences, not a comment per event."""
    start = datetime.now(timezone.utc)
    first = await intake_service.open_case(
        IntakeStream.support,
        title="Refused sign-ins",
        body="The same explanation every time.",
        dedupe_key="refused:9",
        now=start,
    )
    assert first is not None
    for minutes in (1, 2, 130):
        # An automatic source sends its unchanged description again, which is
        # not news.
        await intake_service.open_case(
            IntakeStream.support,
            title="Refused sign-ins",
            body="The same explanation every time.",
            dedupe_key="refused:9",
            now=start + timedelta(minutes=minutes),
        )

    notes = await _notes_on(session, bound["guild"].id, first.task_id)
    assert [note.content for note in notes] == ["Seen again (4 times in all)."]


async def test_two_filings_at_once_cannot_pass_the_cap_together(
    session, bound, monkeypatch
):
    """The cap is counted and the case opened under one lock on the filer, so
    two filings racing for the last place open one case between them."""
    import asyncio
    from dataclasses import replace

    from app.core import intake

    monkeypatch.setitem(
        intake.STREAMS,
        IntakeStream.support,
        replace(intake.STREAMS[IntakeStream.support], max_open_per_filer=1),
    )

    async def file() -> object:
        try:
            return await intake_service.open_case(
                IntakeStream.support,
                title="Help",
                filer=CaseFiler(user_id=bound["user"].id, subject="Help", words="Now."),
            )
        except intake_service.CaseCapReached as exc:
            return exc

    outcomes = await asyncio.gather(file(), file())

    assert sum(isinstance(o, intake_service.CaseCapReached) for o in outcomes) == 1
    await set_rls_context(session, SystemGuild(bound["guild"].id))
    assert len((await session.exec(select(IntakeCase))).all()) == 1


async def test_an_unkeyed_case_still_gets_a_row(session, bound):
    """Every case is recorded, so "when did this last open one" is read."""
    outcome = await intake_service.open_case(IntakeStream.support, title="Help")
    assert outcome is not None

    await set_rls_context(session, SystemGuild(bound["guild"].id))
    case = (
        await session.exec(
            select(IntakeCase).where(IntakeCase.task_id == outcome.task_id)
        )
    ).one()
    assert case.dedupe_key is None
    assert case.stream == IntakeStream.support


async def test_a_closed_case_opens_a_new_one(session, bound):
    first = await intake_service.open_case(
        IntakeStream.support, title="Refused sign-ins", dedupe_key="refused:42"
    )
    assert first is not None

    await set_rls_context(session, SystemGuild(bound["guild"].id))
    task = (await session.exec(select(Task).where(Task.id == first.task_id))).one()
    done = (
        await session.exec(
            select(TaskStatus)
            .where(TaskStatus.project_id == bound["project"].id)
            .where(TaskStatus.category == TaskStatusCategory.done)
        )
    ).first()
    assert done is not None
    task.task_status_id = done.id
    session.add(task)
    await session.commit()

    second = await intake_service.open_case(
        IntakeStream.support, title="Refused sign-ins", dedupe_key="refused:42"
    )
    assert second is not None
    assert second.opened is True
    assert second.task_id != first.task_id


async def test_a_key_longer_than_its_column_is_refused(session, bound):
    with pytest.raises(ValueError):
        await intake_service.open_case(
            IntakeStream.support, title="x", dedupe_key="k" * 500
        )


async def test_a_case_whose_task_was_moved_away_is_not_this_projects_case(
    session, bound
):
    """The project a case is in is the task's column, so it moves with it."""
    first = await intake_service.open_case(
        IntakeStream.support, title="Refused", dedupe_key="refused:42"
    )
    assert first is not None

    await set_rls_context(session, SystemGuild(bound["guild"].id))
    elsewhere = await create_project(session, bound["initiative"], bound["user"])
    await task_statuses_service.ensure_default_statuses(
        session, elsewhere.id, locale="en"
    )
    task = (await session.exec(select(Task).where(Task.id == first.task_id))).one()
    task.project_id = elsewhere.id
    task.task_status_id = (
        await session.exec(
            select(TaskStatus.id).where(TaskStatus.project_id == elsewhere.id).limit(1)
        )
    ).first()
    session.add(task)
    await session.commit()

    again = await intake_service.open_case(
        IntakeStream.support, title="Refused", dedupe_key="refused:42"
    )
    assert again is not None
    assert again.opened is True
    assert again.task_id != first.task_id

    await set_rls_context(session, SystemGuild(bound["guild"].id))
    landed = (await session.exec(select(Task).where(Task.id == again.task_id))).one()
    assert landed.project_id == bound["project"].id


@pytest.mark.parametrize(
    ("kind", "linked"),
    [
        ("comment", True),
        ("task", True),
        ("queue_item", True),
        ("collection", True),
        ("tag", False),
    ],
)
async def test_a_moderation_case_links_to_what_it_is_about(
    session, bound, kind, linked
):
    """The link a case carries opens the thing in its community, through the
    app's resolver; a kind with no page of its own gets none."""
    from app.core.config import settings
    from app.services.tenant.metadata import summaries_by_id

    await _bind(
        session,
        guild=bound["guild"],
        project=bound["project"],
        stream=IntakeStream.moderation.value,
    )
    outcome = await intake_service.open_case(
        IntakeStream.moderation,
        title="Reported",
        refs=CaseRefs(subject_guild=7, resource_type=kind, resource_id=12),
    )
    assert outcome is not None

    await set_rls_context(session, SystemGuild(bound["guild"].id))
    values = {
        summary.name: summary.value
        for summary in (await summaries_by_id(session, "task", [outcome.task_id]))[
            outcome.task_id
        ]
    }
    expected = (
        f"{settings.APP_URL.rstrip('/')}/c/7/go/{kind.replace('_', '-')}/12"
        if linked
        else None
    )
    assert values.get(CaseField.subject_link.value) == expected
