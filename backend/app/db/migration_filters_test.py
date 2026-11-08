"""What guild autogenerate is allowed to write, and what it must not."""

from alembic.operations import ops
from sqlalchemy import ForeignKeyConstraint
from sqlmodel import SQLModel

from app.db import base  # noqa: F401 — registers every model on the metadata
from app.db.migration_filters import strip_cross_schema_foreign_keys
from app.db.tenancy import GUILD_SCOPED_TABLES

#: A guild table carrying both kinds of key: one to a table in its own schema
#: and one to ``public.users``.
_TABLE = "wiki_pages"


def _script(*table_names: str):
    """The directive autogenerate hands the hook for these new tables."""
    return [
        ops.MigrationScript(
            "rev",
            ops.UpgradeOps(
                ops=[
                    ops.CreateTableOp.from_table(SQLModel.metadata.tables[name])
                    for name in table_names
                ]
            ),
            ops.DowngradeOps(ops=[]),
        )
    ]


def _keys(operation) -> set[str]:
    return {
        element.target_fullname
        for item in operation.to_table().constraints
        if isinstance(item, ForeignKeyConstraint)
        for element in item.elements
    }


def test_a_new_guild_table_is_written_without_the_key_to_users():
    """A table being created carries its constraints inside the CreateTableOp,
    so ``include_object`` never sees them — this is where the key that no guild
    schema can hold is taken back out."""
    directives = _script(_TABLE)
    operation = directives[0].upgrade_ops.ops[0]
    assert "users.id" in _keys(operation), (
        f"{_TABLE} no longer declares created_by; pick another table"
    )

    strip_cross_schema_foreign_keys(directives)

    assert "users.id" not in _keys(operation)


def test_the_keys_inside_the_schema_are_left_alone():
    """Only the reference out of the schema goes. A guild table's keys to its
    own schema are real, and provisioning does copy them."""
    directives = _script(_TABLE)
    operation = directives[0].upgrade_ops.ops[0]
    intra = {k for k in _keys(operation) if k.rsplit(".", 1)[0] in GUILD_SCOPED_TABLES}
    assert intra, f"{_TABLE} declares no key inside its own schema"

    strip_cross_schema_foreign_keys(directives)

    assert _keys(operation) == intra


def test_the_column_and_its_reference_survive_on_the_model():
    """The stripping happens to the migration, not to the model.

    ``created_by`` keeps saying it names a person, which is what
    ``app.services.fields.derive`` reads to give the column a member picker
    rather than a number box."""
    column = SQLModel.metadata.tables[_TABLE].columns["created_by"]
    directives = _script(_TABLE)
    strip_cross_schema_foreign_keys(directives)

    assert {fk.target_fullname for fk in column.foreign_keys} == {"users.id"}
