"""Migration 20261027_0543 gives file versions thumbnails. Loaded by path and
run on a guild the test builds: down to before it, then up again."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from app.testing import create_file, create_guild, create_initiative, create_user

_REVISION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20261027_0543_file_versions_have_thumbnails.py"
)


async def test_a_picture_uploaded_before_waits_for_its_thumbnail(session) -> None:
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    schema = f"guild_{guild.id}"
    initiative = await create_initiative(session, guild, user)
    picture = await create_file(
        session,
        initiative,
        user,
        file_url=f"/uploads/{guild.id}/a.jpg",
        file_content_type="image/jpeg",
    )
    brief = await create_file(
        session, initiative, user, file_url=f"/uploads/{guild.id}/b.pdf"
    )
    await session.commit()
    spec = importlib.util.spec_from_file_location(_REVISION.stem, _REVISION)
    assert spec and spec.loader
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)

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

    await session.run_sync(run(revision._downgrade_schema))
    await session.run_sync(run(revision._upgrade_schema))
    await session.commit()

    states = dict(
        (
            await (await session.connection()).execute(
                text(f"SELECT file_id, thumbnail_state FROM {schema}.file_versions")
            )
        ).all()
    )
    assert states == {picture.id: "pending", brief.id: None}
