"""Revision 0444 takes the names out of mentions written before.

Loaded by path, as migrations are not on the import path, and run on one
guild's schema the way the upgrade runs it on each, with the tables named as
they were before 20261006_0464.
"""

from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.orm import undefer
from sqlmodel import select

from app.models.tenant.comment import Comment
from app.models.tenant.file import File
from app.models.tenant.task import Task
from app.services.tenant.mention_parser import nameless_state
from app.testing import MENTIONING_YJS_STATE, route_session_to_guild
from app.testing.factories import (
    checklist_items,
    create_comment,
    create_file,
    create_guild,
    create_initiative,
    create_project,
    create_task,
    create_user,
    lexical_body,
)

_VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"
_REVISION = _VERSIONS / "20261002_0444_a_mention_keeps_no_name.py"
_FILES = _VERSIONS / "20261006_0464_documents_are_files.py"
_COLLECTIONS = _VERSIONS / "20261026_0543_galleries_are_collections.py"


def _revision(path: Path = _REVISION) -> ModuleType:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_a_mention_written_before_keeps_no_name(session):
    """In markdown and in an editor state, archived and trashed rows included,
    and in a collaboration state as an edit on top of it. A mention with no
    account keeps its name, text typed in an editor is left as it was, a state
    that cannot be read is skipped, and the search index is left to be
    rebuilt."""
    author = await create_user(session)
    guild = await create_guild(session, creator=author)
    initiative = await create_initiative(session, guild, author)
    project = await create_project(session, initiative, author)
    named = f"@[Ada]({author.id}) and @[Bo]()"
    task = await create_task(
        session,
        project,
        description=named,
        checklist=checklist_items(named),
        archived_at=datetime.now(timezone.utc),
    )
    comment = await create_comment(
        session, author, task=task, content=named, deleted_at=datetime.now(timezone.utc)
    )
    mentioning = await create_file(
        session,
        initiative,
        author,
        content=lexical_body("Hi ", mentioning=author.id, name="Ada"),
        yjs_state=MENTIONING_YJS_STATE,
    )
    unreadable = await create_file(
        session,
        initiative,
        author,
        content=lexical_body("Hi ", mentioning=author.id, name="Ada"),
        yjs_state=b"unreadable",
    )
    typed = lexical_body(f"Hi @[Ada]({author.id})")
    plain = await create_file(
        session, initiative, author, content=typed, yjs_state=b"kept"
    )
    schema = f"guild_{guild.id}"
    await session.commit()

    def strip(sync) -> str | None:
        bind = sync.connection()
        # Later revisions, newest last: taken off newest first, put back
        # oldest first.
        later = (
            _revision(_FILES)._apply,
            _revision(_COLLECTIONS)._apply,
        )

        def renamed(forward: bool) -> None:
            bind.execute(
                text("SELECT set_config('search_path', :sp, true)"),
                {"sp": f"{schema}, public"},
            )
            with Operations.context(MigrationContext.configure(bind)):
                for apply in later if forward else reversed(later):
                    apply(forward)

        renamed(False)
        bind.execute(text(f"COMMENT ON TABLE \"{schema}\".search_entries IS 'current'"))
        _revision().strip_schema(bind, schema)
        marker = bind.execute(
            text("SELECT obj_description(to_regclass(:t), 'pg_class')"),
            {"t": f'"{schema}".search_entries'},
        ).scalar()
        renamed(True)
        return marker

    marker = await session.run_sync(strip)
    await session.commit()

    session.expunge_all()
    await route_session_to_guild(session, guild.id)
    nameless = f"@[]({author.id}) and @[Bo]()"
    stored = (
        await session.exec(
            select(Task.description, Task.checklist)
            .where(Task.id == task.id)
            .execution_options(include_archived=True)
        )
    ).one()
    assert (stored[0], stored[1][0]["text"]) == (nameless, nameless)
    content = (
        await session.exec(
            select(Comment.content)
            .where(Comment.id == comment.id)
            .execution_options(include_deleted=True)
        )
    ).one()
    assert content == nameless
    files = {
        row.id: (row.content, row.yjs_state)
        for row in (
            await session.exec(
                select(File)
                .where(File.id.in_([mentioning.id, plain.id, unreadable.id]))  # type: ignore[union-attr]
                .options(undefer(File.content), undefer(File.yjs_state))
            )
        ).all()
    }
    content, state = files[mentioning.id]
    assert content == lexical_body("Hi ", mentioning=author.id)
    assert state != MENTIONING_YJS_STATE and b"Ada" not in state
    assert nameless_state(state) is None
    assert files[plain.id] == (typed, b"kept")
    assert files[unreadable.id] == (
        lexical_body("Hi ", mentioning=author.id),
        b"unreadable",
    )
    assert marker is None
