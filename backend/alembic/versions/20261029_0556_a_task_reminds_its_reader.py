"""a task reminds its reader

``personal_items.remind_at``, in every guild schema: when to remind one member
of one task, and ``reminded_at``, when that reminder went out. A row may now
hold a reminder alone, and only a task's row holds one. And an index of the
reminders not yet sent, which the reminder sweep reads.

Revision ID: 20261029_0556
Revises: 20261029_0555
Create Date: 2026-10-29
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261029_0556"
down_revision = "20261029_0555"
branch_labels = None
depends_on = None


def _apply_upgrade() -> None:
    op.add_column(
        "personal_items",
        sa.Column("remind_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "personal_items",
        sa.Column("reminded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.drop_constraint(
        "ck_personal_items_holds_something", "personal_items", type_="check"
    )
    op.create_check_constraint(
        "ck_personal_items_holds_something",
        "personal_items",
        "num_nonnulls(viewed_at, bookmarked_at, subscribed_at,"
        " unsubscribed_at, sort_order, remind_at) > 0",
    )
    op.create_check_constraint(
        "ck_personal_items_remind_at_task",
        "personal_items",
        "remind_at IS NULL OR entity_type = 'task'",
    )
    op.create_check_constraint(
        "ck_personal_items_reminded_with_reminder",
        "personal_items",
        "reminded_at IS NULL OR remind_at IS NOT NULL",
    )
    op.create_index(
        "ix_personal_items_remind_at",
        "personal_items",
        ["remind_at"],
        postgresql_where=sa.text("remind_at IS NOT NULL AND reminded_at IS NULL"),
    )


def _apply_downgrade() -> None:
    op.drop_index("ix_personal_items_remind_at", table_name="personal_items")
    op.drop_constraint(
        "ck_personal_items_reminded_with_reminder", "personal_items", type_="check"
    )
    op.drop_constraint(
        "ck_personal_items_remind_at_task", "personal_items", type_="check"
    )
    # A row that held only a reminder holds nothing once it goes. The
    # table's row security binds its owner, which runs this.
    op.execute("ALTER TABLE personal_items NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "DELETE FROM personal_items WHERE num_nonnulls(viewed_at, bookmarked_at,"
        " subscribed_at, unsubscribed_at, sort_order) = 0"
    )
    op.execute("ALTER TABLE personal_items FORCE ROW LEVEL SECURITY")
    op.drop_constraint(
        "ck_personal_items_holds_something", "personal_items", type_="check"
    )
    op.create_check_constraint(
        "ck_personal_items_holds_something",
        "personal_items",
        "num_nonnulls(viewed_at, bookmarked_at, subscribed_at,"
        " unsubscribed_at, sort_order) > 0",
    )
    op.drop_column("personal_items", "reminded_at")
    op.drop_column("personal_items", "remind_at")


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)
