"""a sign-in rule's initiative is the community's

``public.oidc_claim_mappings.initiative_id`` and ``initiative_role_id`` named
an initiative and a role in a community's own schema, which no key from
``public`` reaches. The sign-in reads a rule's community across communities,
and its initiative only once it is inside that community. In
``guild_template`` and every ``guild_<id>``, ``claim_rule_initiatives`` keeps
them under the rule's id and a version, with keys holding the row to an
initiative and a role of that initiative: deleting either deletes the row, and
the rule goes on placing people in the community alone. The rule names its
version in ``placement_version``, so moving it switches the claims and the
place together.

Each community's rows are copied from the rules naming it whose initiative and
role are still there. A rule whose initiative or role has since been deleted
is not copied, and places people in the community alone, as such a rule does
from now on. The two columns are then dropped. ``oidc_claim_mappings`` holds
no policy and the community's roles are policy-bound for this revision's role,
so both are unforced for the copy and put back as they were. The new table's
row security is rendered at the next start, as always.

The downgrade puts the columns back and copies each community's rows into
them before the table goes.

Revision ID: 20261031_0573
Revises: 20261031_0572
Create Date: 2026-10-31
"""

from collections.abc import Iterator
from contextlib import contextmanager

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261031_0573"
down_revision = "20261031_0572"
branch_labels = None
depends_on = None

TABLE = "claim_rule_initiatives"
RULES = "public.oidc_claim_mappings"

#: The community whose schema is first on the search path; NULL in
#: ``guild_template``, whose rows are nobody's.
_GUILD_ID = "substring(current_schema() FROM '^guild_([0-9]+)$')::int"


@contextmanager
def _unforced(*tables: str) -> Iterator[sa.engine.Connection]:
    """Row security lifted from ``tables`` for the statements inside, and put
    back as it was."""
    bind = op.get_bind()
    forced = [
        table
        for table in tables
        if bind.execute(
            sa.text(
                "SELECT relforcerowsecurity FROM pg_class WHERE oid = to_regclass(:t)"
            ),
            {"t": table},
        ).scalar()
    ]
    for table in forced:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    yield bind
    for table in forced:
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def _create() -> None:
    op.create_table(
        TABLE,
        sa.Column("rule_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("version", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("initiative_id", sa.Integer(), nullable=False),
        sa.Column("initiative_role_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["initiative_id"], ["initiatives.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["initiative_role_id", "initiative_id"],
            ["initiative_roles.id", "initiative_roles.initiative_id"],
            ondelete="CASCADE",
            name="fk_claim_rule_initiatives_role",
        ),
        sa.PrimaryKeyConstraint("rule_id", "version"),
    )
    op.create_index(f"ix_{TABLE}_initiative_id", TABLE, ["initiative_id"])
    op.create_index(f"ix_{TABLE}_initiative_role_id", TABLE, ["initiative_role_id"])


def _drop() -> None:
    """Drop the table: its rendered policies first, then its row security,
    then the table."""
    bind = op.get_bind()
    for (name,) in bind.execute(
        sa.text("SELECT polname FROM pg_policy WHERE polrelid = to_regclass(:t)"),
        {"t": TABLE},
    ).all():
        op.execute(f'DROP POLICY IF EXISTS "{name}" ON {TABLE}')
    op.execute(f"ALTER TABLE {TABLE} DISABLE ROW LEVEL SECURITY")
    op.drop_table(TABLE)


def _upgrade_schema() -> None:
    _create()
    with _unforced("initiative_roles") as bind:
        bind.execute(
            sa.text(
                f"INSERT INTO {TABLE}"
                " (rule_id, version, initiative_id, initiative_role_id)"
                " SELECT m.id, 0, m.initiative_id, m.initiative_role_id"
                f" FROM {RULES} m"
                " JOIN initiative_roles r"
                " ON r.id = m.initiative_role_id AND r.initiative_id = m.initiative_id"
                f" WHERE m.guild_id = {_GUILD_ID}"
            )
        )


def _downgrade_schema() -> None:
    op.execute(f"ALTER TABLE {TABLE} NO FORCE ROW LEVEL SECURITY")
    op.get_bind().execute(
        sa.text(
            f"UPDATE {RULES} m"
            " SET initiative_id = c.initiative_id,"
            " initiative_role_id = c.initiative_role_id"
            f" FROM {TABLE} c"
            f" WHERE c.rule_id = m.id AND c.version = m.placement_version"
            f" AND m.guild_id = {_GUILD_ID}"
        )
    )
    _drop()


def upgrade() -> None:
    with _unforced(RULES) as bind:
        run_for_each_guild_schema(bind, _upgrade_schema)
    op.drop_column("oidc_claim_mappings", "initiative_role_id", schema="public")
    op.drop_column("oidc_claim_mappings", "initiative_id", schema="public")
    op.add_column(
        "oidc_claim_mappings",
        sa.Column(
            "placement_version", sa.Integer(), nullable=False, server_default="0"
        ),
        schema="public",
    )


def downgrade() -> None:
    for column in ("initiative_id", "initiative_role_id"):
        op.add_column(
            "oidc_claim_mappings",
            sa.Column(column, sa.Integer(), nullable=True),
            schema="public",
        )
    with _unforced(RULES) as bind:
        run_for_each_guild_schema(bind, _downgrade_schema)
    op.drop_column("oidc_claim_mappings", "placement_version", schema="public")
