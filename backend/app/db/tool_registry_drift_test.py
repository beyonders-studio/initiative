"""Where a tool registry and the database have to agree.

The registries in ``app.core`` are edited in Python; the shapes they describe
are created by migrations. Nothing in CI notices when one moves and the other
does not, because each is internally consistent — the registry still lists every
tool, and the schema still has every table it was ever told to make.

These assert the join between them, always against the *database* rather than
against another Python list. A test that compared two registries to each other
would pass on exactly the change that breaks a deployment.

Three joins, one per way a tool reaches the schema:

- a tool's own **model**, found by the table name the enum derives;
- the **comment parent column** that model needs on ``comments``;
- the **endpoint kind code** the ``relationships`` node ids are packed from.
"""

import pytest
from sqlalchemy import text

from app.core.relationships import PERSON, EndpointKind, node_id
from app.core.tools import KINDS, Tool
from app.db.initiative_rls import COMMENT_PARENT_COLUMNS
from app.db.kind_codes import apply_kind_codes_if_changed
from app.db.schema_provisioning import (
    drop_guild_schema,
    guild_schema_name,
    provision_guild_schema,
)

pytestmark = pytest.mark.always

_GID_DRIFT = 990_401


def test_every_tool_has_a_model_at_the_table_its_name_derives():
    """A tool's table is its plural. That rule is what every derived registry
    (ownership, tags, comment targets) looks a model up by, so a model whose
    ``__tablename__`` disagrees with the enum silently drops out of all of
    them at once."""
    import app.db.base  # noqa: F401 — registers every model
    from app.models.tenant._mixins import tool_models

    models = tool_models()
    missing = [tool.value for tool in Tool if tool.plural not in models]
    assert not missing, (
        f"no model found at the table name these tools derive: {missing}. "
        "Either the model is not imported, or its __tablename__ is not the "
        "tool's plural."
    )


async def test_every_comment_parent_column_exists_on_comments(engine):
    """Every tool carries a comment thread, and the column that hangs it there
    is derived from the enum — so a tool whose migration forgot the column
    leaves the rendered comment policy naming a column that is not there."""
    schema = guild_schema_name(_GID_DRIFT)
    try:
        async with engine.begin() as conn:
            await provision_guild_schema(conn, _GID_DRIFT)
        async with engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = :schema AND table_name = 'comments'"
                ),
                {"schema": schema},
            )
            present = {row[0] for row in rows}
    finally:
        async with engine.begin() as conn:
            await drop_guild_schema(conn, _GID_DRIFT)

    missing = [column for column in COMMENT_PARENT_COLUMNS if column not in present]
    assert not missing, (
        f"comments is missing parent columns {missing} in a freshly provisioned "
        "schema — a tool was added to the enum without the migration that gives "
        "its comments somewhere to hang."
    )


async def test_every_kind_is_known_to_the_database(engine):
    """``relationships`` packs ``(kind, id)`` into one integer using a Postgres
    function, and the generated node columns are persisted. Boot renders the
    function from ``KINDS`` and the person (``app.db.kind_codes``), as the
    suite's setup does. A kind the function has no arm for makes every write
    naming it fail; a kind whose code differs between Python and SQL makes the
    two disagree about what a row points at, which nothing would report."""
    async with engine.connect() as conn:
        assert not await apply_kind_codes_if_changed(conn), (
            "public.relationship_kind_code differs from what boot renders from "
            "KINDS: the suite's setup did not render it."
        )
        for endpoint in (*KINDS.values(), PERSON):
            code = (
                await conn.execute(
                    text("SELECT public.relationship_kind_code(:kind)"),
                    {"kind": endpoint.value},
                )
            ).scalar()
            assert code == endpoint.code, (
                f"'{endpoint.value}' is code {endpoint.code} in Python and {code} "
                "in Postgres. A kind's code is permanent; one of them moved."
            )
        retired = (
            await conn.execute(text("SELECT public.relationship_kind_code('gallery')"))
        ).scalar()
        assert retired is None, "a retired kind still has a code"


async def test_boot_writes_the_kind_codes_only_when_they_differ(engine):
    """A database whose function an older revision wrote is brought to the
    render once; the next boot leaves it alone."""
    async with engine.connect() as conn:
        await conn.execute(
            text(
                "CREATE OR REPLACE FUNCTION public.relationship_kind_code(kind text)"
                " RETURNS bigint LANGUAGE sql IMMUTABLE STRICT"
                " AS $$ SELECT (CASE kind WHEN 'calendar' THEN 1 END)::bigint $$"
            )
        )
        assert await apply_kind_codes_if_changed(conn)
        assert not await apply_kind_codes_if_changed(conn)
        assert (
            await conn.execute(
                text(
                    "SELECT provolatile::text, proisstrict FROM pg_proc WHERE oid = "
                    "'public.relationship_kind_code(text)'::regprocedure"
                )
            )
        ).one() == ("i", True)
        assert (
            await conn.execute(text("SELECT public.relationship_kind_code('contact')"))
        ).scalar() == KINDS["contact"].code
        await conn.rollback()


async def test_the_database_packs_node_ids_the_way_python_does(engine):
    """The one arithmetic both sides do. Python builds node ids to query the
    edge table by; Postgres builds the stored columns. They are the same
    expression written twice, so this checks they still agree."""
    async with engine.connect() as conn:
        for kind in EndpointKind:
            packed = (
                await conn.execute(
                    text(
                        "SELECT (public.relationship_kind_code(:kind) << 32) | 7::bigint"
                    ),
                    {"kind": kind.value},
                )
            ).scalar()
            assert packed == node_id(kind, 7), (
                f"node id for {kind.value}:7 is {node_id(kind, 7)} in Python and "
                f"{packed} in Postgres."
            )
