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
- the **comment subject kind** ``comments`` admits for that model;
- the **endpoint kind code** the ``relationships`` node ids are packed from.
"""

import pytest
from sqlalchemy import text

from app.core.relationships import PERSON, EndpointKind, node_id
from app.core.tools import COMMENT_TARGETS, KINDS, Tool
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


async def test_every_comment_subject_is_admitted_on_comments(engine):
    """Every tool carries a comment thread, and the kinds a comment may be said
    on are derived from the enum — so a freshly provisioned schema's CHECK on
    ``comments.subject_type`` admits every one of them."""
    schema = guild_schema_name(_GID_DRIFT)
    try:
        async with engine.begin() as conn:
            await provision_guild_schema(conn, _GID_DRIFT)
        async with engine.connect() as conn:
            check = await conn.scalar(
                text(
                    "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c"
                    " JOIN pg_namespace n ON n.oid = c.connamespace"
                    " WHERE n.nspname = :schema AND c.conname = 'ck_comments_subject_type'"
                ),
                {"schema": schema},
            )
    finally:
        async with engine.begin() as conn:
            await drop_guild_schema(conn, _GID_DRIFT)

    assert check is not None, "comments carries no CHECK on its subject's kind"
    missing = [target for target in COMMENT_TARGETS if f"'{target}'" not in check]
    assert not missing, (
        f"comments cannot be said on {missing} in a freshly provisioned schema"
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
