"""themes take their own names

Three color themes were named for tabletop creatures while they reproduce
published palettes: Displacer is Catppuccin, Strahd is Dracula and Aboleth is
Monokai. They now go by those names, so an account wearing one is moved to its
new id. An id the app does not know falls back to the default theme, so the
downgrade puts the old ids back for an older app.

Revision ID: 20261110_0605
Revises: 20261110_0604
Create Date: 2026-11-10
"""

import sqlalchemy as sa
from alembic import op

revision = "20261110_0605"
down_revision = "20261110_0604"
branch_labels = None
depends_on = None

RENAMED = {
    "displacer": "catppuccin",
    "strahd": "dracula",
    "aboleth": "monokai",
}


def _rename(pairs: dict[str, str]) -> None:
    bind = op.get_bind()
    forced = bool(
        bind.execute(
            sa.text(
                "SELECT relforcerowsecurity FROM pg_class "
                "WHERE oid = to_regclass('public.users')"
            )
        ).scalar()
    )
    if forced:
        op.execute("ALTER TABLE public.users NO FORCE ROW LEVEL SECURITY")
    for old, new in pairs.items():
        bind.execute(
            sa.text(
                "UPDATE public.users SET color_theme = :new WHERE color_theme = :old"
            ),
            {"old": old, "new": new},
        )
    if forced:
        op.execute("ALTER TABLE public.users FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    _rename(RENAMED)


def downgrade() -> None:
    _rename({new: old for old, new in RENAMED.items()})
