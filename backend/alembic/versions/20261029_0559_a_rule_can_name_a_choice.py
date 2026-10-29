"""a rule can name a choice, and the deployment's ways in are a rule

The last of the deployment's rules move off ``app_settings`` into
``platform_rules`` (see ``app.core.rules``):

- ``second_factor_requirement``, ``default_dm_policy`` and ``ai_config_mode``,
  each in the new ``choice`` slot. ``rule_choices`` holds the values each such
  rule may take, and a foreign key holds a row's ``(key, choice)`` to them, so
  the database refuses a value its rule does not have. The
  ``second_factor_requirement`` type goes with its column.
- ``login_methods``, in a ``methods`` slot of its own. It keeps the column's
  rule that one of the ways in can begin a session.

``rule_choices`` is filled before it is locked down. ``platform_rules`` and
``app_settings`` are policy-bound for this revision's own role, so each is
unforced for the copy and forced again in the same transaction, and the copy is
counted against its source.

``public.platform_factor_satisfied()`` reads the factor rule from
``platform_rules``; no row asks nobody. Its body is restated here as this
revision installs it.

Revision ID: 20261029_0559
Revises: 20261029_0558
Create Date: 2026-10-29
"""

from collections.abc import Iterator
from contextlib import contextmanager

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, ENUM

from app.core.config import settings

revision = "20261029_0559"
down_revision = "20261029_0558"
branch_labels = None
depends_on = None

#: Policy-bound for this revision's role, so unforced while the rows cross.
TABLES = ("app_settings", "platform_rules")
LOGIN_METHOD = ENUM(name="login_method", create_type=False)

#: (rule key, default) of each choice that moves, and every value it may take.
CHOICES = (
    ("second_factor_requirement", "nobody", ("nobody", "platform_roles", "everyone")),
    ("default_dm_policy", "private", ("private", "community", "public")),
    ("ai_config_mode", "disabled", ("disabled", "platform", "community")),
)
#: The type each choice's column had on ``app_settings``.
COLUMN_TYPES = {
    "second_factor_requirement": "second_factor_requirement",
    "default_dm_policy": "user_dm_policy",
    "ai_config_mode": "text",
}
#: The ways in a deployment permits until it says otherwise.
DEFAULT_METHODS = "'{password,sso,totp,passkey}'::login_method[]"
#: One of the ways in can begin a session.
BEGINS_A_SESSION = (
    "methods IS NULL OR methods && '{password,sso,passkey}'::login_method[]"
)
ONE_SLOT_BEFORE = "num_nonnulls(enabled, amount) = 1"
ONE_SLOT = "num_nonnulls(enabled, amount, choice, methods) = 1"
KEYS = "ARRAY[" + ", ".join(f"'{key}'" for key, *_ in CHOICES) + ", 'login_methods']"

PLATFORM_FACTOR_SATISFIED = """\
CREATE OR REPLACE FUNCTION public.platform_factor_satisfied()
 RETURNS boolean
 LANGUAGE sql
 STABLE
AS $function$
    SELECT NOT EXISTS (
        SELECT 1 FROM public.platform_rules r
        WHERE r.key = 'second_factor_requirement'
          AND r.choice <> 'nobody'
          AND (
              r.choice = 'everyone'
              OR NULLIF(current_setting('app.platform_role'::text, true), ''::text) IS DISTINCT FROM 'member'
          )
          AND (current_setting('app.platform_factor'::text, true) = 'true'::text) IS NOT TRUE
    )
$function$

"""

PREVIOUS_PLATFORM_FACTOR_SATISFIED = """\
CREATE OR REPLACE FUNCTION public.platform_factor_satisfied()
 RETURNS boolean
 LANGUAGE sql
 STABLE
AS $function$
    SELECT NOT EXISTS (
        SELECT 1 FROM public.app_settings s
        WHERE s.id = 1
          AND s.second_factor_requirement <> 'nobody'
          AND (
              s.second_factor_requirement = 'everyone'
              OR NULLIF(current_setting('app.platform_role'::text, true), ''::text) IS DISTINCT FROM 'member'
          )
          AND (current_setting('app.platform_factor'::text, true) = 'true'::text) IS NOT TRUE
    )
$function$

"""


@contextmanager
def _unforced() -> Iterator[sa.engine.Connection]:
    """Both tables unforced for this revision's role, forced again after."""
    bind = op.get_bind()
    for table in TABLES:
        bind.exec_driver_sql(f"ALTER TABLE public.{table} NO FORCE ROW LEVEL SECURITY")
    try:
        yield bind
    finally:
        for table in TABLES:
            bind.exec_driver_sql(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY")


def _replace_one_slot(expression: str) -> None:
    op.drop_constraint("ck_platform_rules_one_slot", "platform_rules", schema="public")
    op.create_check_constraint(
        "ck_platform_rules_one_slot", "platform_rules", expression, schema="public"
    )


def upgrade() -> None:
    op.create_table(
        "rule_choices",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("key", "value"),
        schema="public",
    )
    op.bulk_insert(
        sa.table("rule_choices", sa.column("key"), sa.column("value"), schema="public"),
        [
            {"key": key, "value": value}
            for key, _default, values in CHOICES
            for value in values
        ],
    )
    base = f"{settings.PLATFORM_ROLE_PREFIX}platform_base"
    for statement in (
        "ALTER TABLE public.rule_choices ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE public.rule_choices FORCE ROW LEVEL SECURITY",
        # The schema's default privileges hand every new public table to both
        # floors; nothing reads this one.
        f'REVOKE ALL ON TABLE public.rule_choices FROM app_guild_base, "{base}"',
    ):
        op.execute(statement)

    op.add_column(
        "platform_rules",
        sa.Column("choice", sa.String(length=64), nullable=True),
        schema="public",
    )
    op.add_column(
        "platform_rules",
        sa.Column("methods", ARRAY(LOGIN_METHOD), nullable=True),
        schema="public",
    )
    _replace_one_slot(ONE_SLOT)
    op.create_check_constraint(
        "ck_platform_rules_begins_a_session",
        "platform_rules",
        BEGINS_A_SESSION,
        schema="public",
    )
    op.create_foreign_key(
        "fk_platform_rules_choice",
        "platform_rules",
        "rule_choices",
        ["key", "choice"],
        ["key", "value"],
        source_schema="public",
        referent_schema="public",
    )

    differs_from_default = (
        f"NOT (s.login_methods @> {DEFAULT_METHODS}"
        f" AND s.login_methods <@ {DEFAULT_METHODS})"
    )
    with _unforced() as bind:
        source = bind.exec_driver_sql(
            "SELECT "
            + " + ".join(
                f"(s.{key}::text <> '{default}')::int" for key, default, _ in CHOICES
            )
            + f" + ({differs_from_default})::int"
            " FROM public.app_settings s WHERE s.id = 1"
        ).scalar()
        for key, default, _values in CHOICES:
            bind.exec_driver_sql(
                "INSERT INTO public.platform_rules (key, choice, updated_at)"
                f" SELECT '{key}', s.{key}::text, now() FROM public.app_settings s"
                f" WHERE s.id = 1 AND s.{key}::text <> '{default}'"
            )
        bind.exec_driver_sql(
            "INSERT INTO public.platform_rules (key, methods, updated_at)"
            " SELECT 'login_methods', s.login_methods, now()"
            " FROM public.app_settings s"
            f" WHERE s.id = 1 AND {differs_from_default}"
        )
        copied = bind.exec_driver_sql(
            f"SELECT count(*) FROM public.platform_rules WHERE key = ANY({KEYS})"
        ).scalar_one()
        if copied != (source or 0):
            raise RuntimeError(f"platform_rules: copied {copied} of {source} rows")

    op.get_bind().exec_driver_sql(PLATFORM_FACTOR_SATISFIED)
    for column in ("login_methods", *(key for key, *_ in CHOICES)):
        op.drop_column("app_settings", column, schema="public")
    op.execute("DROP TYPE public.second_factor_requirement")


def downgrade() -> None:
    requirement = ENUM(
        "nobody", "platform_roles", "everyone", name="second_factor_requirement"
    )
    requirement.create(op.get_bind())
    op.add_column(
        "app_settings",
        sa.Column(
            "login_methods",
            ARRAY(LOGIN_METHOD),
            nullable=False,
            server_default=sa.text(DEFAULT_METHODS),
        ),
        schema="public",
    )
    op.create_check_constraint(
        "ck_app_settings_login_methods_nonempty",
        "app_settings",
        "cardinality(login_methods) >= 1",
        schema="public",
    )
    op.create_check_constraint(
        "ck_app_settings_login_methods_has_primary",
        "app_settings",
        "'password' = ANY(login_methods) OR 'sso' = ANY(login_methods)"
        " OR 'passkey' = ANY(login_methods)",
        schema="public",
    )
    op.add_column(
        "app_settings",
        sa.Column(
            "second_factor_requirement",
            ENUM(name="second_factor_requirement", create_type=False),
            nullable=False,
            server_default="nobody",
        ),
        schema="public",
    )
    op.add_column(
        "app_settings",
        sa.Column(
            "default_dm_policy",
            ENUM(name="user_dm_policy", create_type=False),
            nullable=False,
            server_default="private",
        ),
        schema="public",
    )
    op.add_column(
        "app_settings",
        sa.Column(
            "ai_config_mode",
            sa.String(length=20),
            nullable=False,
            server_default="disabled",
        ),
        schema="public",
    )

    with _unforced() as bind:
        bind.exec_driver_sql(
            "UPDATE public.app_settings s SET login_methods = r.methods"
            " FROM public.platform_rules r WHERE r.key = 'login_methods'"
        )
        for key, _default, _values in CHOICES:
            bind.exec_driver_sql(
                f"UPDATE public.app_settings s SET {key} = r.choice::{COLUMN_TYPES[key]}"
                f" FROM public.platform_rules r WHERE r.key = '{key}'"
            )
        bind.exec_driver_sql(
            f"DELETE FROM public.platform_rules WHERE key = ANY({KEYS})"
        )

    op.get_bind().exec_driver_sql(PREVIOUS_PLATFORM_FACTOR_SATISFIED)
    op.drop_constraint(
        "fk_platform_rules_choice",
        "platform_rules",
        type_="foreignkey",
        schema="public",
    )
    op.drop_constraint(
        "ck_platform_rules_begins_a_session", "platform_rules", schema="public"
    )
    _replace_one_slot(ONE_SLOT_BEFORE)
    op.drop_column("platform_rules", "methods", schema="public")
    op.drop_column("platform_rules", "choice", schema="public")
    op.drop_table("rule_choices", schema="public")
