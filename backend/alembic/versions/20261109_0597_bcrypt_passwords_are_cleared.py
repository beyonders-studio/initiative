"""bcrypt passwords are cleared

Passwords have been hashed with argon2id since passlib went, and a bcrypt
hash from before then was rewritten as argon2id the next time its account
signed in with it. An account still holding one has not signed in with a
password since, so this revision clears it rather than keep a second scheme
to check at every sign-in. Such an account has no password: it signs in the
other ways it has, or sets a new password through reset.

Revision ID: 20261109_0597
Revises: 20261109_0596
Create Date: 2026-11-09
"""

import sqlalchemy as sa
from alembic import op

revision = "20261109_0597"
down_revision = "20261109_0596"
branch_labels = None
depends_on = None


def upgrade() -> None:
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
    try:
        op.execute(
            "UPDATE public.users SET hashed_password = NULL "
            "WHERE left(hashed_password, 4) IN ('$2a$', '$2b$', '$2y$')"
        )
    finally:
        if forced:
            op.execute("ALTER TABLE public.users FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    """Nothing to undo: a cleared hash is not kept anywhere to put back."""
