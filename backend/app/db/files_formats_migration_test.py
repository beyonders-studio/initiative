"""Migrations 20261026_0540 and 20261026_0541 store a file's format as its
type. Loaded by path and run on a guild the test builds: down to the types an
older release wrote, rows written that way, then up again, the way
``catalogs_rename_migration_test`` runs the catalogs rename."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from app.core.file_types import FileType
from app.testing import create_file, create_guild, create_initiative, create_user

_VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"


def _load(name: str) -> ModuleType:
    path = _VERSIONS / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _types(session, schema: str) -> dict[int, tuple[str, Any]]:
    result = await (await session.connection()).execute(
        text(f"SELECT id, file_type::text, featured_image_url FROM {schema}.files")
    )
    return {row[0]: (row[1], row[2]) for row in result.all()}


async def test_a_file_s_type_becomes_its_format(session, tmp_path, monkeypatch) -> None:
    """The editor's types take their formats' names, an uploaded file takes
    its current version's, and a picture stops featuring itself."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "UPLOADS_DIR", str(tmp_path / "uploads"))
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    schema = f"guild_{guild.id}"
    initiative = await create_initiative(session, guild, user)
    page = await create_file(session, initiative, user)
    board = await create_file(session, initiative, user, file_type=FileType.excalidraw)
    sheet = await create_file(session, initiative, user, file_type=FileType.sheet)
    link = await create_file(
        session,
        initiative,
        user,
        file_type=FileType.url,
        content={"url": "https://a.test"},
    )
    brief = await create_file(
        session, initiative, user, file_url=f"/uploads/{guild.id}/brief.pdf"
    )
    picture_url = f"/uploads/{guild.id}/site.jpg"
    picture = await create_file(
        session, initiative, user, file_url=picture_url, file_content_type="image/png"
    )
    archive = await create_file(
        session, initiative, user, file_url=f"/uploads/{guild.id}/bundle.zip"
    )
    formats = _load("20261026_0540_files_take_their_formats.py")
    public = _load("20261026_0541_files_take_their_formats_in_public.py")

    def run(step):
        def apply(sync_session) -> None:
            bind = sync_session.connection()
            bind.execute(
                text("SELECT set_config('search_path', :sp, true)"),
                {"sp": f"{schema}, public"},
            )
            with Operations.context(MigrationContext.configure(bind)):
                step(bind)

        return apply

    await session.run_sync(run(lambda _bind: public.downgrade()))
    await session.run_sync(run(formats._downgrade_schema))
    # As an older release wrote them: a picture that features itself, typed
    # by an alias, and a file of a type no format names.
    connection = await session.connection()
    await connection.execute(
        text(f"UPDATE {schema}.files SET featured_image_url = :u WHERE id = :id"),
        {"u": picture_url, "id": picture.id},
    )
    for file, media in ((picture, "image/jpg"), (archive, "application/zip")):
        await connection.execute(
            text(
                f"UPDATE {schema}.file_versions SET file_content_type = :m "
                "WHERE file_id = :id"
            ),
            {"m": media, "id": file.id},
        )
    await session.commit()
    try:
        assert {k: v[0] for k, v in (await _types(session, schema)).items()} == {
            page.id: "native",
            board.id: "whiteboard",
            sheet.id: "spreadsheet",
            link.id: "smart_link",
            brief.id: "file",
            picture.id: "file",
            archive.id: "file",
        }
    finally:
        await session.run_sync(run(formats._upgrade_schema))
        await session.run_sync(run(lambda _bind: public.upgrade()))
        await session.commit()

    assert await _types(session, schema) == {
        page.id: ("lexical", None),
        board.id: ("excalidraw", None),
        sheet.id: ("sheet", None),
        link.id: ("url", None),
        brief.id: ("pdf", None),
        picture.id: ("jpeg", None),
        archive.id: ("other", None),
    }
