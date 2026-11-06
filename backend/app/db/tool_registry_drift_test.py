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

from app.core.relationships import ENDPOINT_KINDS, PERSON, EndpointKind, node_id
from app.core.tools import Tool
from app.db.initiative_rls import COMMENT_PARENT_COLUMNS
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


async def test_every_endpoint_kind_is_known_to_the_database(engine):
    """``relationships`` packs ``(kind, id)`` into one integer using a Postgres
    function, and the generated node columns are persisted. A kind the function
    has no arm for makes every write naming it fail; a kind whose code differs
    between Python and SQL makes the two disagree about what a row points at,
    which nothing would report. The person, an end that is no kind, too."""
    async with engine.connect() as conn:
        for endpoint in (*ENDPOINT_KINDS.values(), PERSON):
            code = (
                await conn.execute(
                    text("SELECT public.relationship_kind_code(:kind)"),
                    {"kind": endpoint.value},
                )
            ).scalar()
            assert code is not None, (
                f"public.relationship_kind_code has no arm for '{endpoint.value}' — "
                "the kind was added to app.core.relationships without the "
                "migration that replaces the function."
            )
            assert code == endpoint.code, (
                f"'{endpoint.value}' is code {endpoint.code} in Python and {code} "
                "in Postgres. A kind's code is permanent; one of them moved."
            )


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
