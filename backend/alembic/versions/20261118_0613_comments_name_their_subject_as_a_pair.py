"""comments name their subject as a pair

In ``guild_template`` and every ``guild_<id>``, a comment names what it is said
on as ``(subject_type, subject_id)`` — a kind from ``COMMENT_TARGETS`` and that
row's id — in place of a column per kind:

* ``comments.subject_type`` and ``comments.subject_id`` are added, filled from
  whichever of the eleven columns is set, and made required.
* ``ix_comments_subject`` on ``(subject_id, subject_type)``: every read of a
  thread, a count or a lifecycle walk names one kind and its ids.
* The eleven columns go, and with them their foreign keys, their indexes and
  ``ck_comments_single_parent``. The policies and triggers that read them are
  dropped first; a start renders them again, reading the pair, along with the
  CHECK that lists the kinds (``ck_comments_subject_type``).

The fill runs with the table's row security unforced and its user triggers
held, both restored in the same transaction.

The downgrade puts the eleven columns back with their keys and indexes,
filled from the pair, after deleting any comment whose subject is gone, and
drops the pair.

Revision ID: 20261118_0613
Revises: 20261117_0612
Create Date: 2026-11-18
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261118_0613"
down_revision = "20261117_0612"
branch_labels = None
depends_on = None

#: (kind, the column that named it, the table it points at), as 20261117_0612
#: left them.
_KINDS = (
    ("task", "task_id", "tasks"),
    ("wiki_page", "wiki_page_id", "wiki_pages"),
    ("collection", "collection_id", "collections"),
    ("project", "project_id", "projects"),
    ("file", "file_id", "files"),
    ("counter_group", "counter_group_id", "counter_groups"),
    ("calendar", "calendar_id", "calendars"),
    ("dashboard", "dashboard_id", "dashboards"),
    ("post", "post_id", "posts"),
    ("wiki", "wiki_id", "wikis"),
    ("contact", "contact_id", "contacts"),
)
_COLUMNS = tuple(column for _, column, _ in _KINDS)

#: The policies and triggers that read one column of a table.
_READERS = """
    SELECT 'POLICY', p.polname, p.polrelid::regclass::text
    FROM pg_depend d JOIN pg_policy p ON p.oid = d.objid
    JOIN pg_attribute a ON a.attrelid = d.refobjid AND a.attnum = d.refobjsubid
    WHERE d.classid = 'pg_policy'::regclass AND d.refobjid = to_regclass(:t)
      AND a.attname = :c
    UNION
    SELECT 'TRIGGER', g.tgname, g.tgrelid::regclass::text
    FROM pg_depend d JOIN pg_trigger g ON g.oid = d.objid
    JOIN pg_attribute a ON a.attrelid = d.refobjid AND a.attnum = d.refobjsubid
    WHERE d.classid = 'pg_trigger'::regclass AND NOT g.tgisinternal
      AND d.refobjid = to_regclass(:t) AND a.attname = :c
"""


def _held(*statements: str) -> None:
    """Run ``statements`` on ``comments`` with its row security unforced and its
    user triggers held, both restored after."""
    bind = op.get_bind()
    forced = bind.execute(
        sa.text(
            "SELECT relforcerowsecurity FROM pg_class"
            " WHERE oid = to_regclass('comments')"
        )
    ).scalar()
    if forced:
        bind.exec_driver_sql("ALTER TABLE comments NO FORCE ROW LEVEL SECURITY")
    bind.exec_driver_sql("ALTER TABLE comments DISABLE TRIGGER USER")
    try:
        for statement in statements:
            bind.exec_driver_sql(statement)
    finally:
        bind.exec_driver_sql("ALTER TABLE comments ENABLE TRIGGER USER")
        if forced:
            bind.exec_driver_sql("ALTER TABLE comments FORCE ROW LEVEL SECURITY")


def _drop_readers(*columns: str) -> None:
    """Drop the policies and triggers that read these columns of ``comments``.
    A start renders the ones the build has again."""
    bind = op.get_bind()
    for column in columns:
        for what, name, on in bind.execute(
            sa.text(_READERS), {"t": "comments", "c": column}
        ).all():
            bind.exec_driver_sql(f'DROP {what} IF EXISTS "{name}" ON {on}')


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    op.add_column("comments", sa.Column("subject_type", sa.String(32), nullable=True))
    op.add_column("comments", sa.Column("subject_id", sa.Integer(), nullable=True))
    kinds = " ".join(
        f"WHEN {column} IS NOT NULL THEN '{kind}'" for kind, column, _ in _KINDS
    )
    _held(
        f"UPDATE comments SET subject_type = CASE {kinds} END,"
        f" subject_id = COALESCE({', '.join(_COLUMNS)})"
    )
    op.alter_column("comments", "subject_type", nullable=False)
    op.alter_column("comments", "subject_id", nullable=False)
    op.create_index("ix_comments_subject", "comments", ["subject_id", "subject_type"])

    _drop_readers(*_COLUMNS)
    op.drop_constraint("ck_comments_single_parent", "comments", type_="check")
    for column in _COLUMNS:
        # Its foreign key and its index go with it.
        op.drop_column("comments", column)


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _apply_downgrade() -> None:
    for _, column, _ in _KINDS:
        op.add_column("comments", sa.Column(column, sa.Integer(), nullable=True))
    gone = " OR ".join(
        f"(subject_type = '{kind}' AND NOT EXISTS"
        f" (SELECT 1 FROM {table} s WHERE s.id = comments.subject_id))"
        for kind, _, table in _KINDS
    )
    fill = ", ".join(
        f"{column} = CASE WHEN subject_type = '{kind}' THEN subject_id END"
        for kind, column, _ in _KINDS
    )
    _held(f"DELETE FROM comments WHERE {gone}", f"UPDATE comments SET {fill}")
    for _, column, table in _KINDS:
        op.create_foreign_key(
            f"comments_{column}_fkey",
            "comments",
            table,
            [column],
            ["id"],
            ondelete="CASCADE",
        )
        op.create_index(f"ix_comments_{column}", "comments", [column])
    op.create_check_constraint(
        "ck_comments_single_parent",
        "comments",
        f"num_nonnulls({', '.join(_COLUMNS)}) = 1",
    )

    _drop_readers("subject_type", "subject_id")
    op.execute(
        "ALTER TABLE comments DROP CONSTRAINT IF EXISTS ck_comments_subject_type"
    )
    op.drop_index("ix_comments_subject", table_name="comments")
    op.drop_column("comments", "subject_id")
    op.drop_column("comments", "subject_type")
