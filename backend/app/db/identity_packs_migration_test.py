"""Migration 20261026_0537 deletes the identity packs' listings, every account's
grants from them, and whatever of them a profile is wearing — and nothing
else.

Loaded by path and run as ``gantt_layout_migration_test`` runs its revision."""

from __future__ import annotations

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from app.db.tool_layouts_migration_test import _load
from app.models.platform.user_decoration import UserDecoration
from app.testing import create_marketplace_listing, create_user

_PRIDE = "5MT2WPY8CHRK61"
_BOOKS = "M0X4JT8PW2GHK6"


def _pack(*pieces: tuple[str, str]) -> dict:
    return {
        "schema_version": 1,
        "kind": "profile_pack",
        "decorations": [
            {"id": piece, "slot": slot, "name": piece} for piece, slot in pieces
        ],
    }


async def test_the_packs_and_every_record_of_them_go(session) -> None:
    await create_marketplace_listing(
        session,
        uid=_PRIDE,
        public_id="core.pride",
        kind="profile_pack",
        definition=_pack(("pride.spectrum", "frame"), ("pride.heart", "trophy")),
    )
    books = await create_marketplace_listing(
        session,
        uid=_BOOKS,
        public_id="core.books",
        kind="profile_pack",
        definition=_pack(("books.quill", "trophy")),
    )
    wearer = await create_user(
        session,
        profile_decorations={
            "banner": "core.aurora",
            "frame": "pride.spectrum",
            "trophies": ["core.fan", "flag.canada", "books.quill", "pride.heart"],
        },
    )
    for piece, kind, source in (
        ("pride.spectrum", "frame", _PRIDE),
        ("pride.heart", "trophy", _PRIDE),
        ("flag.canada", "trophy", None),
        ("books.quill", "trophy", books.uid),
    ):
        session.add(
            UserDecoration(
                user_id=wearer.id, decoration_id=piece, kind=kind, source=source
            )
        )
    await session.commit()

    migration = _load("20261026_0537_identity_packs_leave")

    def upgrade(sync_session) -> None:
        with Operations.context(MigrationContext.configure(sync_session.connection())):
            migration.upgrade()

    await session.run_sync(upgrade)

    async def scalars(statement: str, **params) -> list:
        connection = await session.connection()
        return list((await connection.execute(text(statement), params)).scalars())

    assert await scalars(
        "SELECT public_id FROM public.marketplace_listings ORDER BY public_id"
    ) == ["core.books"]
    assert await scalars(
        "SELECT decoration_id FROM public.user_decorations WHERE user_id = :u",
        u=wearer.id,
    ) == ["books.quill"]
    assert await scalars(
        "SELECT profile_decorations FROM public.users WHERE id = :u", u=wearer.id
    ) == [{"banner": "core.aurora", "trophies": ["core.fan", "books.quill"]}]
