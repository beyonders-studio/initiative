"""An account can have a new task's title read for its dates and the rest.

Typing "Send the invoice friday !high #billing" into a task being added can
fill in the due date, the priority and the tag, and leave "Send the invoice"
as the title. ``users.smart_task_titles`` is whether that happens for this
account. It sits beside the other ways an account reads tasks.

``true`` is the default, for existing accounts as well as new ones: what a
title is read as is highlighted and listed before the task is added, and each
part can be kept as typed, so nothing is set that the reader has not seen.
An account that wants its titles kept word for word turns it off.

Revision ID: 20261022_0536
Revises: 20261021_0535
Create Date: 2026-10-22
"""

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20261022_0536"
down_revision = "20261021_0535"
branch_labels = None
depends_on = None


def _write_roles() -> tuple[str, ...]:
    """The floors that write ``public.users`` — 0221 took the guild path off
    this table, and 0222 onwards is this pair."""
    return (
        f'"{settings.PLATFORM_ROLE_PREFIX}platform_base"',
        "app_user",
    )


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "smart_task_titles",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
    )
    # UPDATE on ``users`` is a column list computed at 0144, so a column added
    # afterwards is writable by nobody until it is named. This one is written
    # by its own holder through ``PATCH /users/me``, on the platform path; the
    # own-row policies from 0202 still decide whose row that reaches.
    for role in _write_roles():
        op.execute(f"GRANT UPDATE (smart_task_titles) ON TABLE public.users TO {role}")


def downgrade() -> None:
    # The grant goes with the column it names.
    op.drop_column("users", "smart_task_titles")
