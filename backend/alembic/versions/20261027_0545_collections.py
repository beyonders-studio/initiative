"""Collections

A collection groups files in an initiative's Files, and a file can be in any
number of them. In ``guild_template`` and every ``guild_<id>``:

* ``collections`` — the collection: its initiative, name, description, cover
  file, author and dates, and the trash, archive, hold and comment state
  content carries. Unique on ``(id, initiative_id)``, which its entries name.
* ``collection_files`` — one row per file in a collection, with who added it
  and when. Both of its keys carry the initiative, so a collection holds only
  its own initiative's files. ``files`` gains the unique ``(id,
  initiative_id)`` that key names.
* ``comments.collection_id`` — a collection's thread.
* ``file_versions.created_by`` may be null: a plug-in acting as its community
  uploads with no person to name, as ``20261006_0462`` let it on a picture.
* ``file_versions`` gains ``width`` and ``height``: a picture's size, which
  the ``thumbnails`` sweep measures when it draws it, and a collection's wall
  lays it out by.
* ``property_definitions.collection_id`` — a collection's own field, keyed
  with its ``initiative_id`` to the collection, so the field is in the
  collection's initiative and goes with it. A rating is one only a
  collection's field may be (a CHECK). A name is unique among the
  initiative's properties, as it was, and among a collection's fields.
* ``property_definitions.currency`` — the ISO 4217 code a money field's
  amounts are in, set exactly when the field is money (a CHECK). An amount is
  kept in ``property_values.value_number``, a ``numeric``, as any number is.
* ``public.property_type`` gains ``currency`` and ``rating``. The labels are
  committed on their own first, since a label cannot be used in the
  transaction that adds it, and a downgrade leaves them: Postgres cannot drop
  a label, and no row holds one after it.

The CHECKs that list kinds and parents, and their policies, are not touched
here; a start renders the policies from the registries.

Revision ID: 20261027_0545
Revises: 20261027_0544
Create Date: 2026-10-26
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261027_0545"
down_revision = "20261027_0544"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("COMMIT")
    for label in ("currency", "rating"):
        op.execute(f"ALTER TYPE public.property_type ADD VALUE IF NOT EXISTS '{label}'")
    op.execute("BEGIN")
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    op.create_unique_constraint(
        "uq_files_id_initiative", "files", ["id", "initiative_id"]
    )
    op.create_table(
        "collections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("initiative_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("cover_file_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.ForeignKeyConstraint(["cover_file_id"], ["files.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "initiative_id", name="uq_collections_id_initiative"),
    )
    op.create_index("ix_collections_initiative_id", "collections", ["initiative_id"])
    op.execute(
        "CREATE TRIGGER tr_collections_set_created_by BEFORE INSERT "
        "ON collections FOR EACH ROW EXECUTE FUNCTION public.fn_set_created_by()"
    )
    op.create_table(
        "collection_files",
        sa.Column("collection_id", sa.Integer(), nullable=False),
        sa.Column("file_id", sa.Integer(), nullable=False),
        sa.Column("initiative_id", sa.Integer(), nullable=False),
        sa.Column("added_by", sa.Integer(), nullable=True),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["collection_id", "initiative_id"],
            ["collections.id", "collections.initiative_id"],
            name="fk_collection_files_collection",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["file_id", "initiative_id"],
            ["files.id", "files.initiative_id"],
            name="fk_collection_files_file",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("collection_id", "file_id"),
    )
    op.create_index("ix_collection_files_file_id", "collection_files", ["file_id"])
    op.add_column("comments", sa.Column("collection_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "comments_collection_id_fkey",
        "comments",
        "collections",
        ["collection_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_comments_collection_id", "comments", ["collection_id"])
    op.alter_column("file_versions", "created_by", nullable=True)
    op.add_column("file_versions", sa.Column("width", sa.Integer(), nullable=True))
    op.add_column("file_versions", sa.Column("height", sa.Integer(), nullable=True))
    op.add_column(
        "property_definitions", sa.Column("collection_id", sa.Integer(), nullable=True)
    )
    op.add_column(
        "property_definitions",
        sa.Column("currency", sa.String(length=3), nullable=True),
    )
    op.create_foreign_key(
        "fk_property_definitions_collection",
        "property_definitions",
        "collections",
        ["collection_id", "initiative_id"],
        ["id", "initiative_id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_property_definitions_collection_id",
        "property_definitions",
        ["collection_id"],
    )
    op.drop_index(
        "ix_property_definitions_initiative_lower_name",
        table_name="property_definitions",
    )
    op.create_index(
        "ix_property_definitions_initiative_lower_name",
        "property_definitions",
        ["initiative_id", sa.text("lower((name)::text)")],
        unique=True,
        postgresql_where=sa.text("collection_id IS NULL"),
    )
    op.create_index(
        "ix_property_definitions_collection_lower_name",
        "property_definitions",
        ["collection_id", sa.text("lower((name)::text)")],
        unique=True,
        postgresql_where=sa.text("collection_id IS NOT NULL"),
    )
    op.create_check_constraint(
        "ck_property_definitions_currency",
        "property_definitions",
        "(type = 'currency') = (currency IS NOT NULL)",
    )


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _apply_downgrade() -> None:
    # Row security binds the owner too, and a migration has no standing to
    # meet it, so it is lifted for the delete and put back.
    op.execute("ALTER TABLE property_definitions NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "DELETE FROM property_definitions WHERE collection_id IS NOT NULL "
        "OR type::text IN ('currency', 'rating')"
    )
    op.execute("ALTER TABLE property_definitions FORCE ROW LEVEL SECURITY")
    op.drop_constraint(
        "ck_property_definitions_currency", "property_definitions", type_="check"
    )
    op.drop_index(
        "ix_property_definitions_collection_lower_name",
        table_name="property_definitions",
    )
    op.drop_index(
        "ix_property_definitions_initiative_lower_name",
        table_name="property_definitions",
    )
    op.create_index(
        "ix_property_definitions_initiative_lower_name",
        "property_definitions",
        ["initiative_id", sa.text("lower((name)::text)")],
        unique=True,
    )
    op.drop_index(
        "ix_property_definitions_collection_id", table_name="property_definitions"
    )
    op.drop_constraint(
        "fk_property_definitions_collection",
        "property_definitions",
        type_="foreignkey",
    )
    op.drop_column("property_definitions", "currency")
    op.drop_column("property_definitions", "collection_id")
    op.drop_column("file_versions", "height")
    op.drop_column("file_versions", "width")
    op.execute(
        "UPDATE file_versions fv SET created_by = f.created_by FROM files f "
        "WHERE fv.created_by IS NULL AND f.id = fv.file_id"
    )
    op.execute("DELETE FROM file_versions WHERE created_by IS NULL")
    op.alter_column("file_versions", "created_by", nullable=False)
    op.drop_index("ix_comments_collection_id", table_name="comments")
    op.drop_constraint("comments_collection_id_fkey", "comments", type_="foreignkey")
    op.drop_column("comments", "collection_id")
    op.drop_index("ix_collection_files_file_id", table_name="collection_files")
    op.drop_table("collection_files")
    op.drop_index("ix_collections_initiative_id", table_name="collections")
    op.drop_table("collections")
    op.drop_constraint("uq_files_id_initiative", "files", type_="unique")
