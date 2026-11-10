"""plug-ins answer to the community's roles

A plug-in's surfaces are reached as the community's own are: inside an
initiative by its roles, which hold a plug-in's permissions as they hold a
tool's keys, and at the community level by its admins, which a custom role on
the admin rung narrows.

In ``guild_template`` and every ``guild_<id>``:

* ``initiative_rules`` gains ``install_id``: a row naming an install is that
  plug-in's permission, by its id, and goes with the install. Its subject
  takes the install, and its key CHECK, as the last start rendered it, admits
  a row naming one; a start renders it whole again.
* ``custom_role_plugin_permissions``: the plug-ins' community permissions a
  custom role keeps. Its policies are rendered at start, as always.
* Every placement's roles become rules: for each non-manager role of the
  initiative, a ``use`` row, on where the placement named the role and off
  where it did not. ``plugin_placements.role_ids`` goes.

And in every stored definition, the listings' versions and every community's
pinned installs, ``admin_only`` goes from pages, actions and endpoints. One
that said true inside an initiative names a permission members do not hold,
``admin_only``, which the definition declares; at the community level only
the admin rung opened a page already, and still does.

Revision ID: 20261110_0606
Revises: 20261110_0605
Create Date: 2026-11-10
"""

import json
from collections.abc import Callable
from typing import Any

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import guild_schema_names, run_for_each_guild_schema

revision = "20261110_0606"
down_revision = "20261110_0605"
branch_labels = None
depends_on = None

#: The permission a surface that said ``admin_only`` names.
_ADMIN_ONLY = "admin_only"
_ADMIN_ONLY_NAME = {"en": "Admins only"}
#: The blocks that said ``admin_only``.
_BLOCKS = ("pages", "actions", "endpoints")
#: What a row naming an install may be, beside what the rule CHECK admits.
_INSTALL_ROW = (
    "(install_id IS NOT NULL"
    " AND ((initiative_id IS NULL) = (initiative_role_id IS NULL)))"
)


def _unforced(table: str, fn: Callable[[], None], *, triggers: bool = True) -> None:
    """Run ``fn`` with ``table``'s FORCE row security, where it has it, lifted,
    and with its user triggers off unless ``triggers``."""
    bind = op.get_bind()
    forced = bind.execute(
        sa.text("SELECT relforcerowsecurity FROM pg_class WHERE oid = to_regclass(:t)"),
        {"t": table},
    ).scalar()
    if forced:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    if not triggers:
        op.execute(f"ALTER TABLE {table} DISABLE TRIGGER USER")
    try:
        fn()
    finally:
        if not triggers:
            op.execute(f"ALTER TABLE {table} ENABLE TRIGGER USER")
        if forced:
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def _rule_check() -> str | None:
    """The rules' key CHECK as the last start rendered it, without its
    ``CHECK`` and ``NOT VALID``."""
    definition = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid = to_regclass('initiative_rules') "
                "AND conname = 'ck_initiative_rules_key'"
            )
        )
        .scalar()
    )
    if definition is None:
        return None
    return definition.removesuffix(" NOT VALID").removeprefix("CHECK ")


def _replace_rule_check(expression: str) -> None:
    op.execute("ALTER TABLE initiative_rules DROP CONSTRAINT ck_initiative_rules_key")
    op.execute(
        "ALTER TABLE initiative_rules ADD CONSTRAINT ck_initiative_rules_key"
        f" CHECK ({expression})"
    )


def _replace_subject(columns: str) -> None:
    op.execute(
        "ALTER TABLE initiative_rules DROP CONSTRAINT uq_initiative_rules_subject"
    )
    op.execute(
        "ALTER TABLE initiative_rules ADD CONSTRAINT uq_initiative_rules_subject"
        f" UNIQUE NULLS NOT DISTINCT ({columns})"
    )


def _upgrade() -> None:
    op.add_column(
        "initiative_rules",
        sa.Column(
            "install_id",
            sa.Integer(),
            sa.ForeignKey("guild_plugins.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_initiative_rules_install_id", "initiative_rules", ["install_id"]
    )
    _replace_subject("initiative_id, key, initiative_role_id, install_id")
    check = _rule_check()
    if check is not None:
        _replace_rule_check(f"(install_id IS NULL AND ({check})) OR {_INSTALL_ROW}")
    op.create_table(
        "custom_role_plugin_permissions",
        sa.Column("role_id", sa.Integer(), nullable=False),
        sa.Column("install_id", sa.Integer(), nullable=False),
        sa.Column("permission", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["role_id"], ["custom_roles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["install_id"], ["guild_plugins.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("role_id", "install_id", "permission"),
    )
    op.create_index(
        "ix_custom_role_plugin_permissions_install_id",
        "custom_role_plugin_permissions",
        ["install_id"],
    )
    _unforced(
        "initiative_rules",
        lambda: op.execute(
            "INSERT INTO initiative_rules"
            " (initiative_id, initiative_role_id, key, enabled, install_id)"
            " SELECT p.initiative_id, r.id, 'use', r.id = ANY (p.role_ids),"
            " p.install_id"
            " FROM plugin_placements p"
            " JOIN initiative_roles r"
            "   ON r.initiative_id = p.initiative_id AND NOT r.is_manager"
            " ON CONFLICT DO NOTHING"
        ),
    )
    op.drop_column("plugin_placements", "role_ids")


def _downgrade() -> None:
    op.execute(
        "ALTER TABLE plugin_placements"
        " ADD COLUMN role_ids integer[] NOT NULL DEFAULT '{}'"
    )
    _unforced(
        "plugin_placements",
        lambda: op.execute(
            "UPDATE plugin_placements p SET role_ids = ARRAY("
            " SELECT r.initiative_role_id FROM initiative_rules r"
            " WHERE r.install_id = p.install_id"
            "   AND r.initiative_id = p.initiative_id"
            "   AND r.key = 'use' AND r.enabled"
            " ORDER BY r.initiative_role_id)"
        ),
    )
    _unforced(
        "initiative_rules",
        lambda: op.execute("DELETE FROM initiative_rules WHERE install_id IS NOT NULL"),
    )
    # With its own policies and the custom roles' that read it, which a start
    # renders again.
    op.execute("DROP TABLE custom_role_plugin_permissions CASCADE")
    # Admitting everything until a start renders it whole again, so the
    # revisions below find a CHECK to replace.
    if _rule_check() is not None:
        _replace_rule_check("true")
    _replace_subject("initiative_id, key, initiative_role_id")
    op.drop_index("ix_initiative_rules_install_id", "initiative_rules")
    op.drop_column("initiative_rules", "install_id")


def _named(definition: Any) -> Any:
    """``definition`` with ``admin_only`` spelled as a permission, or ``None``
    when it says nothing of it."""
    if not isinstance(definition, dict) or not any(
        isinstance(entry, dict) and "admin_only" in entry
        for block in _BLOCKS
        for entry in (definition.get(block) or [])
    ):
        return None
    out = dict(definition)
    levels: set[str] = set()
    for block in _BLOCKS:
        if not isinstance(definition.get(block), list):
            continue
        entries = []
        for original in definition[block]:
            entry = original
            if isinstance(original, dict) and "admin_only" in original:
                entry = {k: v for k, v in original.items() if k != "admin_only"}
                scopes = original.get("scopes") or ["community"]
                here = (
                    (list(scopes) if "initiative" in scopes else [])
                    if block == "pages"
                    else ["initiative"]
                )
                if original["admin_only"] is True and here:
                    entry["permission"] = _ADMIN_ONLY
                    levels.update(here)
            entries.append(entry)
        out[block] = entries
    if levels:
        declared = list(out.get("permissions") or [])
        out["permissions"] = declared + [
            {"id": _ADMIN_ONLY, "name": _ADMIN_ONLY_NAME, "level": level}
            for level in sorted(levels)
        ]
    return out


def _unnamed(definition: Any) -> Any:
    """``definition`` with the permission :func:`_named` wrote spelled
    ``admin_only`` again, or ``None`` when it names none."""
    if not isinstance(definition, dict) or not any(
        isinstance(entry, dict) and entry.get("id") == _ADMIN_ONLY
        for entry in (definition.get("permissions") or [])
    ):
        return None
    out = dict(definition)
    for block in _BLOCKS:
        if isinstance(definition.get(block), list):
            out[block] = [
                (
                    {
                        **{k: v for k, v in entry.items() if k != "permission"},
                        "admin_only": True,
                    }
                    if isinstance(entry, dict)
                    and entry.get("permission") == _ADMIN_ONLY
                    else entry
                )
                for entry in definition[block]
            ]
    out["permissions"] = [
        entry for entry in definition["permissions"] if entry.get("id") != _ADMIN_ONLY
    ]
    if not out["permissions"]:
        del out["permissions"]
    return out


def _rewrite(table: str, spell: Callable[[Any], Any]) -> None:
    """Every definition in ``table`` that ``spell`` changes, as it changes
    it. Nothing about the rows changes but their spelling, so their user
    triggers stay off."""
    bind = op.get_bind()

    def run() -> None:
        for row_id, definition in bind.execute(
            sa.text(
                f"SELECT id, definition FROM {table}"  # noqa: S608
                " WHERE definition::text LIKE '%admin_only%'"
            )
        ).all():
            spelled = spell(definition)
            if spelled is not None:
                bind.execute(
                    sa.text(
                        f"UPDATE {table} SET definition = CAST(:d AS jsonb)"  # noqa: S608
                        " WHERE id = :id"
                    ),
                    {"d": json.dumps(spelled), "id": row_id},
                )

    _unforced(table, run, triggers=False)


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _upgrade)
    _rewrite("public.marketplace_listing_versions", _named)
    for schema in guild_schema_names(op.get_bind()):
        _rewrite(f'"{schema}".guild_plugins', _named)


def downgrade() -> None:
    _rewrite("public.marketplace_listing_versions", _unnamed)
    for schema in guild_schema_names(op.get_bind()):
        _rewrite(f'"{schema}".guild_plugins', _unnamed)
    run_for_each_guild_schema(op.get_bind(), _downgrade)
