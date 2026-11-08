"""a link can end at a person

``public.relationship_kind_code`` reads ``user``, code 18: a person on one end
of an edge (``app.core.relationships.PERSON``). The node columns are generated
from it, so it is restated before any edge names one. The type CHECKs and the
row security that admit the new end are rendered at start from the registry.

The downgrade deletes every edge with a person on either end, in
``guild_template`` and every ``guild_<id>``, with the table's triggers held,
then restates the function without ``user``.

Revision ID: 20261105_0580
Revises: 20261105_0579
Create Date: 2026-11-05
"""

from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261105_0580"
down_revision = "20261105_0579"
branch_labels = None
depends_on = None

#: ``public.relationship_kind_code`` as 20261027_0546 left it.
_KIND_CODES_BEFORE = (
    ("calendar", 1),
    ("calendar_event", 2),
    ("counter", 3),
    ("counter_group", 4),
    ("dashboard", 5),
    ("file", 6),
    ("post", 9),
    ("project", 10),
    ("queue", 11),
    ("queue_item", 12),
    ("tag", 13),
    ("task", 14),
    ("wiki", 15),
    ("wiki_page", 16),
    ("collection", 17),
)
_KIND_CODES_AFTER = (*_KIND_CODES_BEFORE, ("user", 18))


def _kind_code_fn(codes: tuple[tuple[str, int], ...]) -> str:
    arms = " ".join(f"WHEN '{kind}' THEN {code}" for kind, code in codes)
    return f"""
        CREATE OR REPLACE FUNCTION public.relationship_kind_code(kind text)
        RETURNS bigint LANGUAGE sql IMMUTABLE STRICT AS $$
            SELECT (CASE kind {arms} END)::bigint
        $$
    """


def upgrade() -> None:
    op.get_bind().exec_driver_sql(_kind_code_fn(_KIND_CODES_AFTER))


def downgrade() -> None:
    bind = op.get_bind()

    def drop_person_edges() -> None:
        bind.exec_driver_sql("ALTER TABLE relationships NO FORCE ROW LEVEL SECURITY")
        bind.exec_driver_sql("ALTER TABLE relationships DISABLE TRIGGER USER")
        try:
            bind.exec_driver_sql(
                "DELETE FROM relationships "
                "WHERE source_type = 'user' OR target_type = 'user'"
            )
        finally:
            bind.exec_driver_sql("ALTER TABLE relationships ENABLE TRIGGER USER")
            bind.exec_driver_sql("ALTER TABLE relationships FORCE ROW LEVEL SECURITY")

    run_for_each_guild_schema(bind, drop_person_edges)
    bind.exec_driver_sql(_kind_code_fn(_KIND_CODES_BEFORE))
