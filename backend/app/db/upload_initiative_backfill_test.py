"""Migration 20260928_0414 places every existing upload in the initiative
whose content shows it. Loaded by path and run on a guild the test builds, the
way ``role_permission_backfill_migration_test`` runs its revision, after
20261006_0464's downgrade puts back the table names and 20261005_0459's the
file columns it reads."""

from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlmodel import select

from app.core.config import settings
from app.models.tenant.task import Task
from app.models.tenant.upload import Upload
from app.services.storage import get_guild_storage
from app.testing import (
    create_calendar,
    create_calendar_event,
    create_file,
    create_guild,
    create_initiative,
    create_project,
    create_task,
    create_upload,
    create_user,
)
from app.testing.schema_harness import route_session_to_guild

_VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"
_MIGRATION = _VERSIONS / "20260928_0414_an_upload_belongs_to_an_initiative.py"
_FILE_VERSIONS = _VERSIONS / "20261005_0459_file_versions_by_pointer.py"
_FILES = _VERSIONS / "20261006_0464_documents_are_files.py"
_COLLECTIONS = _VERSIONS / "20261027_0545_galleries_are_collections.py"


def _load(path: Path = _MIGRATION) -> ModuleType:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_the_backfill_places_copies_and_leaves_alone(
    session, tmp_path, monkeypatch
) -> None:
    """Shown in one initiative: kept there. Shown in several: the oldest
    showing row's initiative keeps it and each other initiative gets one copy
    that all its rows show. Shown only by the guild's own calendar: kept for
    the guild. Shown by nothing: left as it was, and not deleted."""
    monkeypatch.setattr(settings, "UPLOADS_DIR", str(tmp_path / "uploads"))
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    first = await create_initiative(session, guild, user)
    second = await create_initiative(session, guild, user)
    project = await create_project(session, second, user)
    for name in ("one.png", "shared.png", "guild.png"):
        await create_upload(session, guild, user, filename=name)
    await create_upload(
        session,
        guild,
        user,
        filename="nothing.png",
        claimed_at=datetime.now(timezone.utc),
    )
    get_guild_storage(guild.id).write("shared.png", b"shared")

    def shows(name: str) -> str:
        return f"![shot](/uploads/{guild.id}/{name})"

    await create_file(
        session, first, user, featured_image_url=f"/uploads/{guild.id}/shared.png"
    )
    once = await create_task(session, project, description=shows("one.png"))
    tasks = [
        await create_task(session, project, description=shows("shared.png"))
        for _ in range(2)
    ]
    calendar = await create_calendar(session, first, user, initiative_id=None)
    await create_calendar_event(session, calendar, user, description=shows("guild.png"))

    schema = f"guild_{guild.id}"

    def place(sync_session) -> None:
        bind = sync_session.connection()
        bind.execute(
            text("SELECT set_config('search_path', :sp, true)"),
            {"sp": f"{schema}, public"},
        )
        files = _load(_FILES)
        with Operations.context(MigrationContext.configure(bind)):
            _load(_COLLECTIONS)._apply(False)
            files._apply(False)
            _load(_FILE_VERSIONS)._apply_downgrade()
        _load()._place(bind, schema)

    await session.run_sync(place)
    await session.commit()

    await route_session_to_guild(session, guild.id)
    kept = {
        u.filename: (u.initiative_id, u.claimed_at is not None)
        for u in await session.exec(
            select(Upload).execution_options(populate_existing=True)
        )
    }
    [copy] = set(kept) - {"one.png", "shared.png", "guild.png", "nothing.png"}
    assert kept == {
        "one.png": (second.id, True),
        "shared.png": (first.id, True),
        copy: (second.id, True),
        "guild.png": (None, True),
        "nothing.png": (None, True),
    }
    descriptions = await session.exec(
        select(Task.description)
        .where(Task.id.in_([once.id, *(t.id for t in tasks)]))
        .execution_options(populate_existing=True)
    )
    assert sorted(descriptions.all()) == sorted(
        [shows("one.png"), shows(copy), shows(copy)]
    )
    assert get_guild_storage(guild.id).exists(copy)
