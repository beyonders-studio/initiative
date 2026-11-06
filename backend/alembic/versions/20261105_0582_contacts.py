"""Contacts

An address book, as a tool: each contact is an item of its own with its own
sharing, in an initiative or, with no initiative, belonging to the whole
community through the community contacts plug-in. In ``guild_template`` and
every ``guild_<id>``:

* ``contacts`` — the contact: its initiative (or none), name, whether it is an
  organization, its emails, phones, addresses and websites as JSON lists of
  ``{label, value}``, author and dates, and the trash, archive, hold, comment
  and listing state every tool carries. The triggers every tool table has: the
  author filled in on insert, and the owner row written for whoever made it.
* ``comments.contact_id`` — a contact's thread, and the single-parent CHECK
  over it.
* ``initiatives.contacts_enabled`` — the tool's switch, off.

In ``public``: ``public.relationship_kind_code`` reads ``contact``, code 19, so
an edge may name one.

The policies, the search, change-log, freeze and hold triggers, and the CHECKs
that list a kind, a tool or an admin surface are rendered at start from the
registries.

The downgrade removes every row that names a contact by kind, the comments on
one, and the ``community_contacts`` surface from custom roles, in
``guild_template`` and every ``guild_<id>``, with each table's row security
unforced and its user triggers held, both restored in the same transaction. It
then drops the policies and triggers that read what goes, the column, the
switch and the table, and restates the function without ``contact``.

Revision ID: 20261105_0582
Revises: 20261105_0581
Create Date: 2026-11-05
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261105_0582"
down_revision = "20261105_0581"
branch_labels = None
depends_on = None

#: ``public.relationship_kind_code`` as 20261105_0581 left it.
_KIND_CODES_BEFORE = (
    ("calendar", 1),
    ("calendar_event", 2),
    ("counter", 3),
    ("counter_group", 4),
    ("dashboard", 5),
    ("file", 6),
    ("post", 9),
    ("project", 10),
    ("tag", 13),
    ("task", 14),
    ("wiki", 15),
    ("wiki_page", 16),
    ("collection", 17),
    ("user", 18),
)
_KIND_CODES_AFTER = (*_KIND_CODES_BEFORE, ("contact", 19))

#: The columns a comment names its one parent by, as 20261105_0581 left them.
_PARENTS_BEFORE = (
    "task_id",
    "wiki_page_id",
    "collection_id",
    "project_id",
    "file_id",
    "counter_group_id",
    "calendar_id",
    "dashboard_id",
    "post_id",
    "wiki_id",
)
_PARENTS_AFTER = (*_PARENTS_BEFORE, "contact_id")

#: Every (table, column) that names a thing by its kind or its tool.
_NAMED_BY_KIND = (
    ("relationships", "source_type"),
    ("relationships", "target_type"),
    ("resource_grants", "resource_type"),
    ("share_requests", "resource_type"),
    ("guest_invite_grants", "resource_type"),
    ("search_entries", "entity_type"),
    ("personal_items", "entity_type"),
    ("engagement_levels", "entity_type"),
    ("metadata_values", "entity_type"),
    ("batched_notices", "target_type"),
    ("content_holds", "target_type"),
    ("moderation_reports", "target_type"),
    ("moderation_actions", "target_type"),
)
#: The rule keys the tool brought: its role pair, and the community's switch
#: and member-role defaults for it.
_RULE_KEYS = (
    "contacts_enabled",
    "create_contacts",
    "initiative_tool.contact",
    "initiative_role.member.contacts_enabled",
    "initiative_role.member.create_contacts",
)
_SURFACE = "community_contacts"

#: The policies and triggers that read a table, or one column of it.
_READERS = """
    SELECT 'POLICY', p.polname, p.polrelid::regclass::text, p.polrelid
    FROM pg_depend d JOIN pg_policy p ON p.oid = d.objid
    LEFT JOIN pg_attribute a ON a.attrelid = d.refobjid AND a.attnum = d.refobjsubid
    WHERE d.classid = 'pg_policy'::regclass AND d.refobjid = to_regclass(:t)
      AND (CAST(:c AS text) = '' OR a.attname = CAST(:c AS text))
    UNION
    SELECT 'TRIGGER', g.tgname, g.tgrelid::regclass::text, g.tgrelid
    FROM pg_depend d JOIN pg_trigger g ON g.oid = d.objid
    LEFT JOIN pg_attribute a ON a.attrelid = d.refobjid AND a.attnum = d.refobjsubid
    WHERE d.classid = 'pg_trigger'::regclass AND NOT g.tgisinternal
      AND d.refobjid = to_regclass(:t) AND (CAST(:c AS text) = '' OR a.attname = CAST(:c AS text))
"""


def _kind_code_fn(codes: tuple[tuple[str, int], ...]) -> str:
    arms = " ".join(f"WHEN '{kind}' THEN {code}" for kind, code in codes)
    return f"""
        CREATE OR REPLACE FUNCTION public.relationship_kind_code(kind text)
        RETURNS bigint LANGUAGE sql IMMUTABLE STRICT AS $$
            SELECT (CASE kind {arms} END)::bigint
        $$
    """


def _single_parent(columns: tuple[str, ...]) -> None:
    op.drop_constraint("ck_comments_single_parent", "comments", type_="check")
    op.create_check_constraint(
        "ck_comments_single_parent",
        "comments",
        f"num_nonnulls({', '.join(columns)}) = 1",
    )


def upgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(_kind_code_fn(_KIND_CODES_AFTER))
    run_for_each_guild_schema(bind, _apply_upgrade)


def _apply_upgrade() -> None:
    details = sa.text("'[]'::jsonb")
    op.create_table(
        "contacts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("initiative_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "is_organization", sa.Boolean(), server_default="false", nullable=False
        ),
        *(
            sa.Column(field, postgresql.JSONB(), server_default=details, nullable=False)
            for field in ("emails", "phones", "addresses", "websites")
        ),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("listing_uid", sa.String(length=14), nullable=True),
        sa.Column("listing_version", sa.String(length=32), nullable=True),
        sa.Column("held_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hold_id", sa.Integer(), nullable=True),
        sa.Column("comments_locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "comments_enabled", sa.Boolean(), server_default="true", nullable=False
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.Integer(), nullable=True),
        sa.Column("purge_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["initiative_id"], ["initiatives.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_contacts_initiative_id", "contacts", ["initiative_id"])
    op.create_index("ix_contacts_name", "contacts", ["name"])
    op.create_index(
        "ix_contacts_purge",
        "contacts",
        ["purge_at"],
        postgresql_where=sa.text("purge_at IS NOT NULL"),
    )
    op.execute(
        "CREATE TRIGGER tr_contacts_set_created_by BEFORE INSERT "
        "ON contacts FOR EACH ROW EXECUTE FUNCTION public.fn_set_created_by()"
    )
    op.execute(
        "CREATE TRIGGER tr_contacts_install_owns AFTER INSERT ON contacts "
        "FOR EACH ROW EXECUTE FUNCTION public.fn_install_owns_what_it_creates('contact')"
    )
    op.add_column("comments", sa.Column("contact_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "comments_contact_id_fkey",
        "comments",
        "contacts",
        ["contact_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_comments_contact_id", "comments", ["contact_id"])
    _single_parent(_PARENTS_AFTER)
    op.add_column(
        "initiatives",
        sa.Column(
            "contacts_enabled", sa.Boolean(), server_default="false", nullable=False
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()
    run_for_each_guild_schema(bind, _apply_downgrade)
    bind.exec_driver_sql(_kind_code_fn(_KIND_CODES_BEFORE))


def _held(table: str, *statements: str) -> None:
    """Run ``statements`` on ``table`` with its row security unforced and its
    user triggers held, both restored after. A table this schema lacks is
    passed over."""
    bind = op.get_bind()
    forced = bind.execute(
        sa.text("SELECT relforcerowsecurity FROM pg_class WHERE oid = to_regclass(:t)"),
        {"t": table},
    ).scalar()
    if forced is None:
        return
    if forced:
        bind.exec_driver_sql(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    bind.exec_driver_sql(f"ALTER TABLE {table} DISABLE TRIGGER USER")
    for statement in statements:
        bind.exec_driver_sql(statement)
    bind.exec_driver_sql(f"ALTER TABLE {table} ENABLE TRIGGER USER")
    if forced:
        bind.exec_driver_sql(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def _drop_readers(table: str, column: str = "") -> None:
    """Drop the policies and triggers that read ``column`` of ``table``, or,
    with no column, those on other tables that read ``table``. A start renders
    the ones the build has again."""
    bind = op.get_bind()
    own = bind.execute(sa.text("SELECT to_regclass(:t)::oid"), {"t": table}).scalar()
    for what, name, on, relid in bind.execute(
        sa.text(_READERS), {"t": table, "c": column}
    ).all():
        if column or relid != own:
            bind.exec_driver_sql(f'DROP {what} IF EXISTS "{name}" ON {on}')


def _apply_downgrade() -> None:
    for table, column in _NAMED_BY_KIND:
        _held(table, f"DELETE FROM {table} WHERE {column} = 'contact'")
    keys = ", ".join(f"'{key}'" for key in _RULE_KEYS)
    _held("initiative_rules", f"DELETE FROM initiative_rules WHERE key IN ({keys})")
    _held(
        "custom_roles",
        f"UPDATE custom_roles SET surfaces = array_remove(surfaces, '{_SURFACE}')"
        f" WHERE '{_SURFACE}' = ANY (surfaces)",
    )
    _held("comments", "DELETE FROM comments WHERE contact_id IS NOT NULL")
    _single_parent(_PARENTS_BEFORE)
    _drop_readers("comments", "contact_id")
    op.drop_index("ix_comments_contact_id", table_name="comments")
    op.drop_constraint("comments_contact_id_fkey", "comments", type_="foreignkey")
    op.drop_column("comments", "contact_id")
    _drop_readers("initiatives", "contacts_enabled")
    op.drop_column("initiatives", "contacts_enabled")
    _drop_readers("contacts")
    op.drop_table("contacts")
