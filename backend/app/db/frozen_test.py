"""Archived and trashed content is read-only, and the database is what says so.

These run under the real ``app_user`` login with a routed context rather than the
superuser-backed ``session`` fixture: the RESTRICTIVE policies are half the
subject, and a superuser would show none of them. The triggers bind everyone, so
they would show either way — but the split is exactly what these pin down, and
mixing the two sessions would hide which half refused a write.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db import gucs
from app.db.errors import dbapi_sqlstate
from app.db.frozen import FROZEN_SQLSTATE
from app.db.session import raise_flag
from app.models.platform.guild import CommunityRole
from app.models.tenant._mixins import ActorKind
from app.models.tenant.project import Project
from app.services.tenant import archive as archive_service
from app.services.tenant.soft_delete import soft_delete_entity
from app.testing import (
    create_comment,
    create_guild,
    create_guild_membership,
    create_initiative,
    create_initiative_member,
    create_project,
    create_resource_grant,
    create_task,
    create_task_status,
    create_user,
    route_as,
)


@pytest.fixture
async def workspace(session):
    """A member, a guild, an initiative, a project and a task inside it."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await create_guild_membership(
        session, user=user, guild=guild, role=CommunityRole.member
    )
    initiative = await create_initiative(session, guild=guild, creator=user)
    project = await create_project(session, initiative=initiative, owner=user)
    task = await create_task(session, project=project)
    return user, guild, initiative, project, task


@pytest.fixture
async def routed(role_session, workspace):
    """The member's own session, routed into the guild — the request path."""
    user, guild, *_ = workspace
    s = await role_session("app_user")
    await route_as(s, user_id=user.id, guild_id=guild.id)
    yield s
    # Every read here opens a transaction, and an open one holds locks the
    # per-test schema teardown then waits on.
    await s.rollback()


@pytest.fixture
async def admin_routed(session, role_session, workspace):
    """The same guild, entered as its admin.

    Hard delete is purge, and ``soft_delete_admin_purge`` already admits only a
    community's administrator — so a member's DELETE never reaches the freeze
    at all. The delete half of the rule is only observable from here. The
    standing says who administers, read from the membership row, so the row is
    what this sets up.
    """
    _user, guild, initiative, *_ = workspace
    admin = await create_user(session)
    await create_guild_membership(
        session, user=admin, guild=guild, role=CommunityRole.admin
    )
    await create_initiative_member(session, initiative=initiative, user=admin)
    s = await role_session("app_user")
    await route_as(s, user_id=admin.id, guild_id=guild.id)
    yield s
    await s.rollback()


async def _frozen(
    s: AsyncSession, kind: str, rid: int, trashed_ok: bool = False
) -> bool:
    return (
        await s.exec(
            text("SELECT resource_frozen(:kind, :rid, :trashed_ok)").bindparams(
                kind=kind, rid=rid, trashed_ok=trashed_ok
            )
        )
    ).scalar()


async def _archive(session, entity) -> None:
    """Archive through the service, because the cascade is part of the state.

    Archiving stamps what is inside it, and the freeze reads that stamp rather
    than walking up to find it — so a raw UPDATE here would set up a state the
    application never produces and the tests below would be describing nothing.
    """
    await archive_service.archive_entity(session, entity)
    await session.commit()


async def _trash(session, entity, by: int) -> None:
    """Trash through the service, for the same reason as ``_archive``: the
    cascade is what puts the contents into the state being tested.

    ``by`` is not optional. A trashed row is visible to whoever deleted it, and
    leaving that unrecorded would set up a row nobody can see — which no request
    path produces, and which would make these tests describe the wrong thing.
    """
    await soft_delete_entity(
        session, entity, deleted_by_user_id=by, retention_days=None
    )
    await session.commit()


class TestResourceFrozen:
    """The one walk both halves defer to."""

    async def test_live_content_is_not_frozen(self, routed, workspace):
        _u, _g, initiative, project, task = workspace
        assert await _frozen(routed, "initiatives", initiative.id) is False
        assert await _frozen(routed, "projects", project.id) is False
        assert await _frozen(routed, "tasks", task.id) is False

    async def test_an_archived_project_freezes_its_tasks(
        self, session, routed, workspace
    ):
        _u, _g, _i, project, task = workspace
        await _archive(session, project)
        assert await _frozen(routed, "projects", project.id) is True
        assert await _frozen(routed, "tasks", task.id) is True

    async def test_an_archived_initiative_freezes_everything_under_it(
        self, session, routed, workspace
    ):
        _u, _g, initiative, project, task = workspace
        await _archive(session, initiative)
        assert await _frozen(routed, "projects", project.id) is True
        assert await _frozen(routed, "tasks", task.id) is True

    async def test_a_trashed_parent_ends_the_walk_for_a_delete(
        self, session, routed, workspace
    ):
        """What is under a trashed row is being purged, not edited."""
        user, _g, _i, project, task = workspace
        await _trash(session, project, by=user.id)
        assert await _frozen(routed, "tasks", task.id) is True
        assert await _frozen(routed, "tasks", task.id, trashed_ok=True) is False

    async def test_an_archived_parent_does_not_end_it(self, session, routed, workspace):
        """Archived is not on the way anywhere: a delete under it is refused."""
        _u, _g, _i, project, task = workspace
        await _archive(session, project)
        assert await _frozen(routed, "tasks", task.id, trashed_ok=True) is True

    async def test_an_unknown_kind_and_a_null_id_are_not_frozen(self, routed):
        assert await _frozen(routed, "nothing_like_this", 1) is False
        assert (
            await routed.exec(text("SELECT resource_frozen('tasks', NULL::bigint)"))
        ).scalar() is False


class TestAncestorFreeze:
    """A row whose parent is frozen takes no writes."""

    async def test_a_task_in_an_archived_project_cannot_be_updated(
        self, session, routed, workspace
    ):
        _u, _g, _i, project, task = workspace
        await _archive(session, project)
        with pytest.raises(DBAPIError) as excinfo:
            await routed.exec(
                text("UPDATE tasks SET title = 'edited' WHERE id = :id").bindparams(
                    id=task.id
                )
            )
        assert dbapi_sqlstate(excinfo.value) == FROZEN_SQLSTATE

    async def test_a_task_cannot_be_moved_into_an_archived_project(
        self, session, routed, workspace
    ):
        user, _g, initiative, project, _t = workspace
        elsewhere = await create_project(session, initiative=initiative, owner=user)
        loose = await create_task(session, project=elsewhere)
        await _archive(session, project)
        with pytest.raises(DBAPIError) as excinfo:
            await routed.exec(
                text("UPDATE tasks SET project_id = :dest WHERE id = :id").bindparams(
                    dest=project.id, id=loose.id
                )
            )
        assert dbapi_sqlstate(excinfo.value) == FROZEN_SQLSTATE

    async def test_a_task_cannot_be_added_to_an_archived_project(
        self, session, routed, workspace
    ):
        _u, _g, _i, project, task = workspace
        await _archive(session, project)
        with pytest.raises(DBAPIError) as excinfo:
            await routed.exec(
                text(
                    "INSERT INTO tasks (project_id, title, task_status_id, position) "
                    "SELECT :pid, 'new', task_status_id, 1 FROM tasks WHERE id = :id"
                ).bindparams(pid=project.id, id=task.id)
            )
        assert "frozen_ancestor_insert" in str(excinfo.value)

    async def test_an_archived_project_takes_no_new_sharing(
        self, session, routed, workspace
    ):
        """Sharing an archived thing is a change to it. The endpoint refuses
        this too; the point here is that the table does."""
        user, _guild, initiative, project, _t = workspace
        await _archive(session, project)
        with pytest.raises(DBAPIError) as excinfo:
            await routed.exec(
                text(
                    "INSERT INTO resource_grants "
                    "(resource_type, resource_id, user_id, level, "
                    " initiative_id, created_at) "
                    "VALUES ('project', :pid, :uid, 'viewer', :iid, now())"
                ).bindparams(pid=project.id, uid=user.id, iid=initiative.id)
            )
        assert "frozen_ancestor_insert" in str(excinfo.value)

    async def test_an_archived_project_can_still_be_unshared(
        self, session, routed, workspace
    ):
        """Taking somebody's access away changes who can reach the project,
        not the project, so the archive does not hold it."""
        _user, guild, _i, project, _t = workspace
        other = await create_user(session)
        await create_guild_membership(session, user=other, guild=guild)
        grant = await create_resource_grant(session, project, user=other)
        await _archive(session, project)

        await routed.exec(
            text("DELETE FROM resource_grants WHERE id = :id").bindparams(id=grant.id)
        )
        await routed.commit()

    async def test_the_first_grant_on_a_new_resource_is_not_sharing(
        self, routed, workspace
    ):
        """A grant is what makes a resource reachable, so the first one is
        written while the resource still answers to nobody: by the table's
        create trigger, as the row goes in. Asked the way every other ancestor
        is asked, no resource could ever be created."""
        user, _g, initiative, _p, _t = workspace
        routed.add(Project(name="Fresh", initiative_id=initiative.id))
        await routed.flush()

        owners = (
            await routed.exec(
                text(
                    "SELECT g.user_id FROM resource_grants g "
                    "JOIN projects p ON p.id = g.resource_id "
                    "WHERE g.resource_type = 'project' AND g.level = 'owner' "
                    "AND p.name = 'Fresh'"
                )
            )
        ).all()
        assert [row[0] for row in owners] == [user.id]

    async def test_a_trashed_project_takes_no_new_sharing(
        self, session, role_session, workspace
    ):
        """Asked by somebody the trashed row is hidden from.

        Sharing asks only for the initiative, so the lifecycle check is what
        stands between a member and a grant naming a resource that is on its way
        out. The resource is out of sight for them, which is not the same as
        there being nothing to ask about.
        """
        owner, guild, initiative, project, _t = workspace
        await _trash(session, project, by=owner.id)

        bystander = await create_user(session)
        await create_guild_membership(
            session, user=bystander, guild=guild, role=CommunityRole.member
        )
        await create_initiative_member(session, initiative=initiative, user=bystander)
        await session.commit()

        s = await role_session("app_user")
        await route_as(s, user_id=bystander.id, guild_id=guild.id)
        try:
            hidden = await s.exec(
                text("SELECT count(*) FROM projects WHERE id = :id").bindparams(
                    id=project.id
                )
            )
            assert hidden.one()[0] == 0, "the row has to be out of sight to ask this"

            with pytest.raises(DBAPIError) as excinfo:
                await s.exec(
                    text(
                        "INSERT INTO resource_grants "
                        "(resource_type, resource_id, user_id, level, "
                        " initiative_id, created_at) "
                        "VALUES ('project', :pid, :uid, 'viewer', :iid, now())"
                    ).bindparams(
                        pid=project.id,
                        uid=bystander.id,
                        iid=initiative.id,
                    )
                )
            assert "frozen_ancestor_insert" in str(excinfo.value)
        finally:
            await s.rollback()

    async def test_a_refused_delete_says_so_rather_than_removing_nothing(
        self, session, admin_routed, workspace
    ):
        """DELETE has no WITH CHECK, so this half is a trigger — and the point
        of the trigger is that the caller hears about it."""
        _u, _g, _i, project, task = workspace
        await _archive(session, project)
        with pytest.raises(DBAPIError) as excinfo:
            await admin_routed.exec(
                text("DELETE FROM tasks WHERE id = :id").bindparams(id=task.id)
            )
        assert dbapi_sqlstate(excinfo.value) == FROZEN_SQLSTATE

    async def test_a_purge_under_a_trashed_project_still_runs(
        self, session, admin_routed, workspace
    ):
        user, _g, _i, project, task = workspace
        await _trash(session, project, by=user.id)
        result = await admin_routed.exec(
            text("DELETE FROM tasks WHERE id = :id").bindparams(id=task.id)
        )
        assert result.rowcount == 1
        await admin_routed.commit()

    async def test_a_task_cannot_be_moved_out_of_an_archived_project(
        self, session, routed, workspace
    ):
        """Both ancestries are asked about: the one the row has as well as the
        one it would end up under."""
        user, _g, initiative, project, task = workspace
        elsewhere = await create_project(session, initiative=initiative, owner=user)
        await _archive(session, project)
        with pytest.raises(DBAPIError) as excinfo:
            await routed.exec(
                text("UPDATE tasks SET project_id = :dest WHERE id = :id").bindparams(
                    dest=elsewhere.id, id=task.id
                )
            )
        assert dbapi_sqlstate(excinfo.value) == FROZEN_SQLSTATE

    async def test_a_task_under_an_archived_project_can_still_be_restored(
        self, session, routed, workspace
    ):
        """A lifecycle change is the one write a frozen ancestor still admits —
        restoring a trashed project's tasks would be impossible otherwise."""
        user, _g, _i, project, task = workspace
        await _trash(session, task, by=user.id)
        await _archive(session, project)
        await routed.exec(
            text(
                "UPDATE tasks SET deleted_at = NULL, deleted_by = NULL, "
                "purge_at = NULL WHERE id = :id"
            ).bindparams(id=task.id)
        )
        await routed.commit()

    async def test_a_comment_under_an_archived_task_comes_back_with_it(
        self, session, routed, workspace
    ):
        """A comment carries no ``archived_at``, so unstamped inside an archived
        thing is the only state it has — and the state it was in before the
        trash took the whole tree. Coming out of the trash has to put it back.
        """
        user, _g, initiative, project, task = workspace
        comment = await create_comment(session, user, task=task)
        await _archive(session, task)
        await _trash(session, initiative, by=user.id)

        # Shallowest first, the order ``restore_entity`` writes in: each level
        # is out of the trash before the one under it is written, so what the
        # walk still sees above the comment is the archive on its task.
        for table, rid in (
            ("initiatives", initiative.id),
            ("projects", project.id),
            ("tasks", task.id),
            ("comments", comment.id),
        ):
            await routed.exec(
                text(
                    f"UPDATE {table} SET deleted_at = NULL, deleted_by = NULL, "
                    "purge_at = NULL WHERE id = :id"
                ).bindparams(id=rid)
            )
        await routed.commit()

        still_archived = (
            await routed.exec(
                text("SELECT archived_at FROM tasks WHERE id = :id").bindparams(
                    id=task.id
                )
            )
        ).scalar()
        assert still_archived is not None

    async def test_a_comment_cannot_come_out_from_under_a_trashed_task(
        self, session, routed, workspace
    ):
        """The other half of the same rule, kept: the thing above it is in the
        trash, so bringing this back alone would leave it live where nobody can
        reach it — and it would come back a second time with its task."""
        user, _g, _i, _p, task = workspace
        comment = await create_comment(session, user, task=task)
        await _trash(session, task, by=user.id)

        with pytest.raises(DBAPIError) as excinfo:
            await routed.exec(
                text(
                    "UPDATE comments SET deleted_at = NULL, deleted_by = NULL, "
                    "purge_at = NULL WHERE id = :id"
                ).bindparams(id=comment.id)
            )
        assert dbapi_sqlstate(excinfo.value) == FROZEN_SQLSTATE

    async def test_a_reply_does_not_freeze_with_the_comment_it_answers(
        self, session, routed, workspace
    ):
        """A reply is its writer's words, not part of the comment it answers:
        the comment going to its author's trash leaves the reply as it was,
        writable, and a reply thrown away before it comes back on its own."""
        user, _g, _i, _p, task = workspace
        comment = await create_comment(session, user, task=task)
        reply = await create_comment(
            session, user, task=task, parent_comment_id=comment.id
        )
        await _trash(session, comment, by=user.id)

        await routed.exec(
            text("UPDATE comments SET content = 'edited' WHERE id = :id").bindparams(
                id=reply.id
            )
        )
        await routed.commit()
        await _trash(session, reply, by=user.id)
        await routed.exec(
            text(
                "UPDATE comments SET deleted_at = NULL, deleted_by = NULL, "
                "purge_at = NULL WHERE id = :id"
            ).bindparams(id=reply.id)
        )

    async def test_a_comment_under_an_archived_task_is_still_read_only(
        self, session, routed, workspace
    ):
        """Inheriting the archive is not being exempt from it."""
        user, _g, _i, _p, task = workspace
        comment = await create_comment(session, user, task=task)
        await _archive(session, task)

        with pytest.raises(DBAPIError) as excinfo:
            await routed.exec(
                text(
                    "UPDATE comments SET content = 'edited' WHERE id = :id"
                ).bindparams(id=comment.id)
            )
        assert dbapi_sqlstate(excinfo.value) == FROZEN_SQLSTATE

    async def test_live_content_is_untouched(self, routed, workspace):
        _u, _g, _i, _p, task = workspace
        await routed.exec(
            text("UPDATE tasks SET title = 'fine' WHERE id = :id").bindparams(
                id=task.id
            )
        )
        await routed.commit()

    async def test_reading_frozen_content_is_the_point_of_keeping_it(
        self, session, routed, workspace
    ):
        _u, _g, initiative, _project, task = workspace
        await _archive(session, initiative)
        rows = (
            await routed.exec(
                text("SELECT id FROM tasks WHERE id = :id").bindparams(id=task.id)
            )
        ).all()
        assert len(rows) == 1


class TestRowFreeze:
    """A frozen row may change only the columns that describe the freeze."""

    async def test_an_archived_project_cannot_be_renamed(
        self, session, routed, workspace
    ):
        _u, _g, _i, project, _t = workspace
        await _archive(session, project)
        with pytest.raises(DBAPIError) as excinfo:
            await routed.exec(
                text("UPDATE projects SET name = 'renamed' WHERE id = :id").bindparams(
                    id=project.id
                )
            )
        assert dbapi_sqlstate(excinfo.value) == FROZEN_SQLSTATE

    async def test_an_archived_project_can_be_unarchived(
        self, session, routed, workspace
    ):
        _u, _g, _i, project, _t = workspace
        await _archive(session, project)
        await routed.exec(
            text(
                "UPDATE projects SET archived_at = NULL, updated_at = now() "
                "WHERE id = :id"
            ).bindparams(id=project.id)
        )
        await routed.commit()

    async def test_a_trashed_project_can_be_restored(self, session, routed, workspace):
        user, _g, _i, project, _t = workspace
        await _trash(session, project, by=user.id)
        await routed.exec(
            text(
                "UPDATE projects SET deleted_at = NULL, deleted_by = NULL, "
                "purge_at = NULL WHERE id = :id"
            ).bindparams(id=project.id)
        )
        await routed.commit()

    async def test_unarchiving_cannot_smuggle_an_edit_along(
        self, session, routed, workspace
    ):
        _u, _g, _i, project, _t = workspace
        await _archive(session, project)
        with pytest.raises(DBAPIError) as excinfo:
            await routed.exec(
                text(
                    "UPDATE projects SET archived_at = NULL, name = 'renamed' "
                    "WHERE id = :id"
                ).bindparams(id=project.id)
            )
        assert dbapi_sqlstate(excinfo.value) == FROZEN_SQLSTATE

    async def test_an_archived_task_is_read_only(self, session, routed, workspace):
        _u, _g, _i, _p, task = workspace
        await _archive(session, task)
        with pytest.raises(DBAPIError) as excinfo:
            await routed.exec(
                text("UPDATE tasks SET title = 'edited' WHERE id = :id").bindparams(
                    id=task.id
                )
            )
        assert dbapi_sqlstate(excinfo.value) == FROZEN_SQLSTATE

    async def test_a_board_restructure_moves_an_archived_task_with_its_column(
        self, session, routed, workspace
    ):
        """The column is what changes; the task keeps its stamp and follows."""
        _u, _g, _i, project, task = workspace
        other = await create_task_status(session, project, name="Elsewhere")
        await _archive(session, task)
        await raise_flag(routed, gucs.RESTRUCTURING)
        await routed.exec(
            text("UPDATE tasks SET task_status_id = :status WHERE id = :id").bindparams(
                status=other.id, id=task.id
            )
        )
        await routed.commit()

    async def test_a_board_restructure_ends_with_its_transaction(
        self, session, routed, workspace
    ):
        _u, _g, _i, _p, task = workspace
        await _archive(session, task)
        await raise_flag(routed, gucs.RESTRUCTURING)
        await routed.commit()
        with pytest.raises(DBAPIError) as excinfo:
            await routed.exec(
                text("UPDATE tasks SET title = 'edited' WHERE id = :id").bindparams(
                    id=task.id
                )
            )
        assert dbapi_sqlstate(excinfo.value) == FROZEN_SQLSTATE


class TestWhatTheFreezeLeavesAlone:
    async def test_a_reader_still_records_where_they_were(
        self, session, routed, workspace
    ):
        """Reading frozen content writes rows. If the freeze reached them,
        opening an archived project would be an error."""
        user, _g, _i, project, _t = workspace
        await _archive(session, project)
        await routed.exec(
            text(
                "INSERT INTO personal_items"
                " (user_id, entity_type, entity_id, viewed_at, view_source)"
                " VALUES (:uid, 'project', :pid, now(), 'direct')"
            ).bindparams(uid=user.id, pid=project.id)
        )
        await routed.commit()


class TestTrashedRowsAreOutOfSight:
    """Deleting something takes it out of sight, not just out of the way."""

    @pytest.fixture
    async def other_member(self, session, workspace):
        """A second member of the same initiative, who deleted nothing."""
        _u, guild, initiative, _p, _t = workspace
        user = await create_user(session)
        await create_guild_membership(
            session, user=user, guild=guild, role=CommunityRole.member
        )
        await create_initiative_member(session, initiative=initiative, user=user)
        return user

    @pytest.fixture
    async def other_admin(self, session, workspace):
        """A second member who administers the community, and deleted nothing."""
        _u, guild, initiative, _p, _t = workspace
        user = await create_user(session)
        await create_guild_membership(
            session, user=user, guild=guild, role=CommunityRole.admin
        )
        await create_initiative_member(session, initiative=initiative, user=user)
        return user

    async def _routed_as(self, role_session, user, guild):
        s = await role_session("app_user")
        await route_as(s, user_id=user.id, guild_id=guild.id)
        return s

    async def test_a_member_does_not_see_what_somebody_else_deleted(
        self, session, role_session, workspace, other_member
    ):
        user, guild, _i, _p, task = workspace
        task.deleted_at = datetime.now(UTC)
        task.deleted_by = user.id
        task.deleted_by_kind = ActorKind.member
        session.add(task)
        await session.commit()

        s = await self._routed_as(role_session, other_member, guild)
        rows = (
            await s.exec(
                text("SELECT id FROM tasks WHERE id = :id").bindparams(id=task.id)
            )
        ).all()
        await s.rollback()
        assert rows == []

    async def test_whoever_deleted_it_still_sees_it(
        self, session, role_session, workspace
    ):
        user, guild, _i, _p, task = workspace
        task.deleted_at = datetime.now(UTC)
        task.deleted_by = user.id
        task.deleted_by_kind = ActorKind.member
        session.add(task)
        await session.commit()

        s = await self._routed_as(role_session, user, guild)
        rows = (
            await s.exec(
                text("SELECT id FROM tasks WHERE id = :id").bindparams(id=task.id)
            )
        ).all()
        await s.rollback()
        assert len(rows) == 1

    async def test_the_guild_admin_sees_everything_in_the_trash(
        self, session, role_session, workspace, other_admin
    ):
        user, guild, _i, _p, task = workspace
        task.deleted_at = datetime.now(UTC)
        task.deleted_by = user.id
        task.deleted_by_kind = ActorKind.member
        session.add(task)
        await session.commit()

        s = await self._routed_as(role_session, other_admin, guild)
        rows = (
            await s.exec(
                text("SELECT id FROM tasks WHERE id = :id").bindparams(id=task.id)
            )
        ).all()
        await s.rollback()
        assert len(rows) == 1

    async def test_the_freeze_still_sees_it_when_deciding(
        self, session, role_session, workspace, other_member
    ):
        """The guard asks the database about a row the asker cannot read. If
        hiding it also hid it from the guard, everything hanging off a trashed
        row would become writable by anyone who did not delete it."""
        user, guild, _i, _p, task = workspace
        task.deleted_at = datetime.now(UTC)
        task.deleted_by = user.id
        task.deleted_by_kind = ActorKind.member
        session.add(task)
        await session.commit()

        s = await self._routed_as(role_session, other_member, guild)
        frozen = await _frozen(s, "tasks", task.id)
        await s.rollback()
        assert frozen is True
