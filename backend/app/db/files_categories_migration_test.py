"""Migrations 20261027_0548 and 20261027_0549: files take their categories'
formats, and a saved files view's kind filter says ``compressed``. Loaded by
path and run on rows written the way the release before them wrote them, the
way ``files_formats_migration_test`` runs 20261026_0540."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from app.models.platform.user_view_preference import UserViewPreference
from app.testing import create_file, create_guild, create_initiative, create_user

_VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"


def _load(name: str) -> ModuleType:
    path = _VERSIONS / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _in(schema: str, step):
    def apply(sync_session) -> None:
        bind = sync_session.connection()
        bind.execute(
            text("SELECT set_config('search_path', :sp, true)"),
            {"sp": f"{schema}, public"},
        )
        with Operations.context(MigrationContext.configure(bind)):
            step(bind)

    return apply


async def test_files_of_a_category_s_formats_take_them(session) -> None:
    """A file named as one of the new formats, stored as what its bytes
    borrow, takes the format and its versions the format's media type; a file
    whose media type a new format names takes it whatever its name. Anything
    else stays as it was, and the downgrade makes the new ones ``other``."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    schema = f"guild_{guild.id}"
    initiative = await create_initiative(session, guild, user)

    async def uploaded(name: str, media: str):
        return await create_file(
            session,
            initiative,
            user,
            file_url=f"/uploads/{guild.id}/{name}",
            file_content_type=media,
            original_filename=name,
        )

    illustration = await uploaded("logo.ai", "application/pdf")
    script = await uploaded("build.py", "text/plain")
    layers = await uploaded("poster.bin", "image/vnd.adobe.photoshop")
    painting = await uploaded("study.kra", "application/zip")
    brief = await uploaded("brief.pdf", "application/pdf")
    bundle = await uploaded("bundle.zip", "application/zip")
    notes = await uploaded("notes.txt", "text/plain")
    await session.commit()
    files = _load("20261027_0548_files_take_their_categories.py")

    async def types() -> dict[int, tuple[str, str]]:
        result = await (await session.connection()).execute(
            text(
                f"SELECT f.id, f.file_type, v.file_content_type FROM {schema}.files f "
                f"JOIN {schema}.file_versions v ON v.id = f.current_version_id"
            )
        )
        return {row[0]: (row[1], row[2]) for row in result.all()}

    await session.run_sync(_in(schema, files._upgrade_schema))
    await session.commit()

    assert await types() == {
        illustration.id: ("ai", "application/illustrator"),
        script.id: ("py", "text/x-python"),
        layers.id: ("psd", "image/vnd.adobe.photoshop"),
        painting.id: ("kra", "application/x-krita"),
        brief.id: ("pdf", "application/pdf"),
        bundle.id: ("zip", "application/zip"),
        notes.id: ("txt", "text/plain"),
    }

    await session.run_sync(_in(schema, files._downgrade_schema))
    await session.commit()

    downgraded = {k: v[0] for k, v in (await types()).items()}
    assert downgraded == {
        illustration.id: "other",
        script.id: "other",
        layers.id: "other",
        painting.id: "other",
        brief.id: "pdf",
        bundle.id: "zip",
        notes.id: "txt",
    }


async def test_a_saved_files_view_filters_by_compressed(session) -> None:
    """A saved files view's ``archive`` kind filter is ``compressed``; any other
    kind, and a view of another tool, is left as it was."""
    user = await create_user(session)
    saved = {
        "files": {"filters": {"kind": "archive", "search": "x"}},
        "files:other": {"filters": {"kind": "image"}},
        "projects": {"filters": {"kind": "archive"}},
    }
    rows = {
        scope: UserViewPreference(user_id=user.id, scope_key=scope, value=value)
        for scope, value in saved.items()
    }
    session.add_all(rows.values())
    await session.commit()
    kind = _load("20261027_0549_compressed_files_kind.py")

    async def values() -> dict[str, dict]:
        result = await (await session.connection()).execute(
            text(
                "SELECT scope_key, value FROM public.user_view_preferences "
                "WHERE user_id = :u"
            ),
            {"u": user.id},
        )
        return {
            scope: value if isinstance(value, dict) else json.loads(value)
            for scope, value in result.all()
        }

    await session.run_sync(_in("public", lambda _bind: kind.upgrade()))
    await session.commit()
    assert await values() == {
        "files": {"filters": {"kind": "compressed", "search": "x"}},
        "files:other": {"filters": {"kind": "image"}},
        "projects": {"filters": {"kind": "archive"}},
    }

    await session.run_sync(_in("public", lambda _bind: kind.downgrade()))
    await session.commit()
    assert await values() == saved
