"""a community's plan is its paid rules

What the deployment gives one community moves off ``guild_administration``
into ``community_rules`` as the deployment's rows (see ``app.core.rules``):

- ``max_storage_bytes``, ``max_users`` and ``max_guests``, as ``amount`` rows
  (now ``bigint``, for a storage cap in bytes, and never below zero, as the
  columns were held); no row is no limit;
- ``auth_options`` as two switches, ``community_sign_in`` (``providers``) and
  ``security_standards`` (``restrictions``), named as billing names them;
- ``banner_image_enabled`` as ``banner_image`` and ``support_enabled`` as
  ``help_requests``.

``guild_administration`` keeps the plan label and billing's bookkeeping. The
``guild_auth_option`` type goes with its column.

``community_rules`` gains ``set_by``: ``community`` for what a community's seat
writes, ``deployment`` for what billing's sync or the operator writes. A
deployment row wins. ``rule_key_writers`` says who may write each rule, and a
foreign key holds every row's ``(key, set_by)`` to it, so a paid rule is the
deployment's alone. The seat's policies write only its own rows; billing writes
the deployment's rows of the community it was routed to, and the staff list
reads every community's plan. While billing manages plans, a trigger holds the
deployment's rows to billing, as 0364 held the columns.

``public.guild_holds_option()`` reads the option's row, and
``public.guild_auth_satisfied()`` asks it by the rule's name. Both are restated
here as this revision installs them.

``guild_administration`` and ``community_rules`` are policy-bound for this
revision's own role, so each is unforced for the copy and forced again in the
same transaction, and the copy is counted against its source.

Revision ID: 20261030_0561
Revises: 20261030_0560
Create Date: 2026-10-30
"""

from collections.abc import Iterator
from contextlib import contextmanager

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, ENUM

from app.core.config import settings

revision = "20261030_0561"
down_revision = "20261030_0560"
branch_labels = None
depends_on = None

#: Policy-bound for this revision's role, so unforced while the rows cross.
TABLES = ("guild_administration", "community_rules")
OPTION = ENUM("providers", "restrictions", name="guild_auth_option", create_type=False)

#: (rule key, who may write it), every community rule's.
WRITERS = [
    ("allow_ai", "community"),
    ("allow_ai", "deployment"),
    ("allow_email_notifications", "community"),
    ("allow_email_notifications", "deployment"),
    ("allow_engagement_ranking", "community"),
    ("allow_engagement_ranking", "deployment"),
    ("allow_push_notifications", "community"),
    ("allow_push_notifications", "deployment"),
    ("api_keys", "community"),
    ("api_keys", "deployment"),
    ("auth_policy", "community"),
    ("auth_policy", "deployment"),
    ("banner_image", "deployment"),
    ("community_sign_in", "deployment"),
    ("enforce_compliance_session", "community"),
    ("enforce_compliance_session", "deployment"),
    ("guest_auth_policy", "community"),
    ("guest_auth_policy", "deployment"),
    ("guest_max_days", "community"),
    ("guest_max_days", "deployment"),
    ("help_requests", "deployment"),
    ("max_guests", "deployment"),
    ("max_storage_bytes", "deployment"),
    ("max_users", "deployment"),
    ("redact_notification_content", "community"),
    ("redact_notification_content", "deployment"),
    ("require_second_factor", "community"),
    ("require_second_factor", "deployment"),
    ("security_standards", "deployment"),
]

#: (column, rule key) of each cap: no row is no limit.
CAPS = (
    ("max_storage_bytes", "max_storage_bytes"),
    ("max_users", "max_users"),
    ("max_guests", "max_guests"),
)
#: (option, rule key) of each sign-in option.
OPTIONS = (("providers", "community_sign_in"), ("restrictions", "security_standards"))
#: (column, rule key, its default) of each other entitlement.
SWITCHES = (
    ("banner_image_enabled", "banner_image", True),
    ("support_enabled", "help_requests", False),
)
PAID = (
    "ARRAY["
    + ", ".join(
        f"'{key}'"
        for key in (
            *(key for _column, key in CAPS),
            *(key for _option, key in OPTIONS),
            *(key for _column, key, _default in SWITCHES),
        )
    )
    + "]"
)

GUILD_HOLDS_OPTION = """\
CREATE OR REPLACE FUNCTION public.guild_holds_option(p_guild_id integer, p_option text)
 RETURNS boolean
 LANGUAGE plpgsql
 STABLE
AS $function$
BEGIN
    RETURN EXISTS (
        SELECT 1
        FROM public.community_rules r
        WHERE r.guild_id = p_guild_id
          AND r.key = p_option
          AND r.user_id IS NULL
          AND r.set_by = 'deployment'
          AND r.enabled
    );
END
$function$

"""

PREVIOUS_GUILD_HOLDS_OPTION = """\
CREATE OR REPLACE FUNCTION public.guild_holds_option(p_guild_id integer, p_option text)
 RETURNS boolean
 LANGUAGE plpgsql
 STABLE
AS $function$
BEGIN
    RETURN NOT EXISTS (
        SELECT 1
        FROM public.guild_administration a
        WHERE a.guild_id = p_guild_id
          AND NOT p_option::public.guild_auth_option = ANY(a.auth_options)
    );
END
$function$

"""

GUILD_AUTH_SATISFIED = """\
CREATE OR REPLACE FUNCTION public.guild_auth_satisfied()
 RETURNS boolean
 LANGUAGE sql
 STABLE
AS $function$
    SELECT
        -- Pure system routing (no user context) and the explicit sentinel a
        -- user-attributed job sets are not sessions to gate.
        NULLIF(current_setting('app.current_user_id'::text, true), ''::text) IS NULL
        OR current_setting('app.satisfied_providers'::text, true) = 'system'::text
        OR (
        -- What the deployment asks of the account, before what the community
        -- asks of the session. Both have to hold.
        public.platform_factor_satisfied()
        AND NOT EXISTS (
            SELECT 1
            FROM public.community_rules p
            -- The requirement that applies: a request routed into one of the
            -- community's guest roles, each granted the guest floor, is asked
            -- what the community asks of its guests.
            CROSS JOIN LATERAL (
                SELECT EXISTS (
                    SELECT 1 FROM pg_auth_members m
                    WHERE m.member = to_regrole(current_user)
                      AND m.roleid = to_regrole('guest_base')
                ) AS guest
            ) routed
            -- A requirement is a row, so there is one only where it asks
            -- something.
            WHERE p.guild_id = (COALESCE(NULLIF(current_setting('app.current_guild_id'::text, true), ''::text), NULLIF(current_setting('app.pam_guild_id'::text, true), ''::text), NULLIF(current_setting('app.settings_guild_id'::text, true), ''::text)))::integer
              AND p.user_id IS NULL
              AND p.key = CASE WHEN routed.guest
                  THEN 'guest_auth_policy' ELSE 'auth_policy' END
              AND (
                  -- The provider this guild names, if it names one: the
                  -- session came through it, and this community counts the
                  -- arrival as one of its own.
                  (
                      p.provider_id IS NOT NULL
                      AND NOT public.guild_connection_satisfied(
                            p.guild_id, p.provider_id
                          )
                  )
                  -- Or the account's own second factor, where the community
                  -- asks for one. The session records it when a code is
                  -- presented and the request carries that here.
                  -- Both factor legs apply while the community holds
                  -- ``providers``; the arrival legs apply whatever it holds.
                  OR (
                      'totp' = ANY(p.methods)
                      AND NOT ('mfa' = ANY(public.session_amr()))
                      AND public.guild_holds_option(p.guild_id, 'community_sign_in')
                  )
                  -- Or a passkey, where the community asks for one. Its own
                  -- leg rather than the factor's: an assertion records the
                  -- second factor too, so the two are asked for separately.
                  -- Either kind of key answers, which is what the overlap says.
                  OR (
                      'passkey' = ANY(p.methods)
                      AND NOT (public.session_amr() && ARRAY['hwk', 'swk'])
                      AND public.guild_holds_option(p.guild_id, 'community_sign_in')
                  )
                  -- Or any of its own, whichever provider served it. Named
                  -- rather than counted, so a list holding some other method
                  -- is not read as this one.
                  OR (
                      'sso' = ANY(p.methods)
                      AND NOT public.guild_connection_satisfied(p.guild_id)
                  )
              )
        )
        AND NOT EXISTS (
            -- Asked of everybody reaching this community, whatever it says
            -- about how they arrive. A rule of its own rather than part of the
            -- requirement, because a community that asks nothing about arrival
            -- holds no requirement and still asks this, while it holds
            -- ``restrictions``. Unsatisfied is what this finds, like the leg
            -- above it.
            SELECT 1
            FROM public.community_rules r
            WHERE r.guild_id = (COALESCE(NULLIF(current_setting('app.current_guild_id'::text, true), ''::text), NULLIF(current_setting('app.pam_guild_id'::text, true), ''::text), NULLIF(current_setting('app.settings_guild_id'::text, true), ''::text)))::integer
              AND r.user_id IS NULL
              AND r.key = 'require_second_factor'
              AND r.enabled
              AND NOT ('mfa' = ANY(public.session_amr()))
              AND public.guild_holds_option(r.guild_id, 'security_standards')
        ))
$function$

"""

PREVIOUS_GUILD_AUTH_SATISFIED = """\
CREATE OR REPLACE FUNCTION public.guild_auth_satisfied()
 RETURNS boolean
 LANGUAGE sql
 STABLE
AS $function$
    SELECT
        -- Pure system routing (no user context) and the explicit sentinel a
        -- user-attributed job sets are not sessions to gate.
        NULLIF(current_setting('app.current_user_id'::text, true), ''::text) IS NULL
        OR current_setting('app.satisfied_providers'::text, true) = 'system'::text
        OR (
        -- What the deployment asks of the account, before what the community
        -- asks of the session. Both have to hold.
        public.platform_factor_satisfied()
        AND NOT EXISTS (
            SELECT 1
            FROM public.community_rules p
            -- The requirement that applies: a request routed into one of the
            -- community's guest roles, each granted the guest floor, is asked
            -- what the community asks of its guests.
            CROSS JOIN LATERAL (
                SELECT EXISTS (
                    SELECT 1 FROM pg_auth_members m
                    WHERE m.member = to_regrole(current_user)
                      AND m.roleid = to_regrole('guest_base')
                ) AS guest
            ) routed
            -- A requirement is a row, so there is one only where it asks
            -- something.
            WHERE p.guild_id = (COALESCE(NULLIF(current_setting('app.current_guild_id'::text, true), ''::text), NULLIF(current_setting('app.pam_guild_id'::text, true), ''::text), NULLIF(current_setting('app.settings_guild_id'::text, true), ''::text)))::integer
              AND p.user_id IS NULL
              AND p.key = CASE WHEN routed.guest
                  THEN 'guest_auth_policy' ELSE 'auth_policy' END
              AND (
                  -- The provider this guild names, if it names one: the
                  -- session came through it, and this community counts the
                  -- arrival as one of its own.
                  (
                      p.provider_id IS NOT NULL
                      AND NOT public.guild_connection_satisfied(
                            p.guild_id, p.provider_id
                          )
                  )
                  -- Or the account's own second factor, where the community
                  -- asks for one. The session records it when a code is
                  -- presented and the request carries that here.
                  -- Both factor legs apply while the community holds
                  -- ``providers``; the arrival legs apply whatever it holds.
                  OR (
                      'totp' = ANY(p.methods)
                      AND NOT ('mfa' = ANY(public.session_amr()))
                      AND public.guild_holds_option(p.guild_id, 'providers')
                  )
                  -- Or a passkey, where the community asks for one. Its own
                  -- leg rather than the factor's: an assertion records the
                  -- second factor too, so the two are asked for separately.
                  -- Either kind of key answers, which is what the overlap says.
                  OR (
                      'passkey' = ANY(p.methods)
                      AND NOT (public.session_amr() && ARRAY['hwk', 'swk'])
                      AND public.guild_holds_option(p.guild_id, 'providers')
                  )
                  -- Or any of its own, whichever provider served it. Named
                  -- rather than counted, so a list holding some other method
                  -- is not read as this one.
                  OR (
                      'sso' = ANY(p.methods)
                      AND NOT public.guild_connection_satisfied(p.guild_id)
                  )
              )
        )
        AND NOT EXISTS (
            -- Asked of everybody reaching this community, whatever it says
            -- about how they arrive. A rule of its own rather than part of the
            -- requirement, because a community that asks nothing about arrival
            -- holds no requirement and still asks this, while it holds
            -- ``restrictions``. Unsatisfied is what this finds, like the leg
            -- above it.
            SELECT 1
            FROM public.community_rules r
            WHERE r.guild_id = (COALESCE(NULLIF(current_setting('app.current_guild_id'::text, true), ''::text), NULLIF(current_setting('app.pam_guild_id'::text, true), ''::text), NULLIF(current_setting('app.settings_guild_id'::text, true), ''::text)))::integer
              AND r.user_id IS NULL
              AND r.key = 'require_second_factor'
              AND r.enabled
              AND NOT ('mfa' = ANY(public.session_amr()))
              AND public.guild_holds_option(r.guild_id, 'restrictions')
        ))
$function$

"""


def _billing_role() -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}initiative_billing"


def _deployment_rows_follow_billing() -> str:
    """While billing manages plans, only billing writes a deployment row. A
    row going with its community or its member is not a write anybody made."""
    return f"""\
CREATE OR REPLACE FUNCTION public.community_rule_follows_billing()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
BEGIN
    IF current_user = '{_billing_role()}' OR NOT public.billing_managed() THEN
        RETURN COALESCE(NEW, OLD);
    END IF;
    IF TG_OP = 'DELETE' AND NOT EXISTS (
        SELECT 1 FROM public.guilds g WHERE g.id = OLD.guild_id
    ) THEN
        RETURN OLD;
    END IF;
    IF (TG_OP <> 'INSERT' AND OLD.set_by = 'deployment')
        OR (TG_OP <> 'DELETE' AND NEW.set_by = 'deployment')
    THEN
        RAISE EXCEPTION 'COMMUNITY_PLAN_SET_BY_BILLING'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN COALESCE(NEW, OLD);
END
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


def _replace_subject(*columns: str) -> None:
    op.drop_constraint("uq_community_rules_subject", "community_rules", schema="public")
    op.create_unique_constraint(
        "uq_community_rules_subject",
        "community_rules",
        list(columns),
        schema="public",
        postgresql_nulls_not_distinct=True,
    )


def upgrade() -> None:
    op.create_table(
        "rule_key_writers",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("set_by", sa.String(length=16), nullable=False),
        sa.PrimaryKeyConstraint("key", "set_by"),
        schema="public",
    )
    op.bulk_insert(
        sa.table(
            "rule_key_writers", sa.column("key"), sa.column("set_by"), schema="public"
        ),
        [{"key": key, "set_by": set_by} for key, set_by in WRITERS],
    )
    base = f"{settings.PLATFORM_ROLE_PREFIX}platform_base"
    for statement in (
        "ALTER TABLE public.rule_key_writers ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE public.rule_key_writers FORCE ROW LEVEL SECURITY",
        # The schema's default privileges hand every new public table to both
        # floors; nothing reads this one.
        f'REVOKE ALL ON TABLE public.rule_key_writers FROM app_guild_base, "{base}"',
    ):
        op.execute(statement)

    op.add_column(
        "community_rules",
        sa.Column(
            "set_by", sa.String(length=16), nullable=False, server_default="community"
        ),
        schema="public",
    )
    op.alter_column(
        "community_rules",
        "amount",
        type_=sa.BigInteger(),
        existing_type=sa.Integer(),
        schema="public",
    )
    _replace_subject("guild_id", "key", "user_id", "set_by")
    op.create_check_constraint(
        "ck_community_rules_amount_nonnegative",
        "community_rules",
        "amount IS NULL OR amount >= 0",
        schema="public",
    )
    op.create_foreign_key(
        "fk_community_rules_writer",
        "community_rules",
        "rule_key_writers",
        ["key", "set_by"],
        ["key", "set_by"],
        source_schema="public",
        referent_schema="public",
    )

    copies = [
        (key, "amount", f"a.{column}", f"a.{column} IS NOT NULL")
        for column, key in CAPS
    ]
    copies += [
        (key, "enabled", "true", f"'{option}' = ANY(a.auth_options)")
        for option, key in OPTIONS
    ]
    copies += [
        (key, "enabled", f"a.{column}", f"a.{column} <> {str(default).lower()}")
        for column, key, default in SWITCHES
    ]
    with _unforced() as bind:
        for key, slot, value, condition in copies:
            source = bind.exec_driver_sql(
                f"SELECT count(*) FROM public.guild_administration a WHERE {condition}"
            ).scalar_one()
            bind.exec_driver_sql(
                "INSERT INTO public.community_rules"
                f" (guild_id, key, set_by, {slot}, updated_at)"
                f" SELECT a.guild_id, '{key}', 'deployment', {value}, now()"
                f" FROM public.guild_administration a WHERE {condition}"
            )
            copied = bind.exec_driver_sql(
                "SELECT count(*) FROM public.community_rules"
                f" WHERE key = '{key}' AND set_by = 'deployment'"
            ).scalar_one()
            if copied != source:
                raise RuntimeError(
                    f"community_rules.{key}: copied {copied} of {source}"
                )

    bind = op.get_bind()
    # Before the column it read goes.
    bind.exec_driver_sql(GUILD_HOLDS_OPTION)
    bind.exec_driver_sql(GUILD_AUTH_SATISFIED)
    bind.exec_driver_sql(_deployment_rows_follow_billing())
    op.execute(
        "CREATE TRIGGER community_rule_follows_billing"
        " BEFORE INSERT OR UPDATE OR DELETE ON public.community_rules"
        " FOR EACH ROW EXECUTE FUNCTION public.community_rule_follows_billing()"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.community_rules"
        f' TO "{_billing_role()}"'
    )
    for column, _key in CAPS:
        op.drop_column("guild_administration", column, schema="public")
    for column, _key, _default in SWITCHES:
        op.drop_column("guild_administration", column, schema="public")
    op.drop_column("guild_administration", "auth_options", schema="public")
    op.execute("DROP TYPE public.guild_auth_option")


def downgrade() -> None:
    OPTION.create(op.get_bind())
    for column, kind in (
        ("max_storage_bytes", sa.BigInteger()),
        ("max_users", sa.Integer()),
        ("max_guests", sa.Integer()),
    ):
        op.add_column(
            "guild_administration",
            sa.Column(column, kind, nullable=True),
            schema="public",
        )
        op.create_check_constraint(
            f"ck_guild_administration_{column}_nonnegative",
            "guild_administration",
            f"{column} IS NULL OR {column} >= 0",
            schema="public",
        )
    op.add_column(
        "guild_administration",
        sa.Column(
            "auth_options",
            ARRAY(OPTION),
            nullable=False,
            server_default=sa.text("'{}'::public.guild_auth_option[]"),
        ),
        schema="public",
    )
    for column, _key, default in SWITCHES:
        op.add_column(
            "guild_administration",
            sa.Column(
                column,
                sa.Boolean(),
                nullable=False,
                server_default=sa.text(str(default).lower()),
            ),
            schema="public",
        )
    billing = _billing_role()
    for statement in (
        "REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLE public.community_rules"
        f' FROM "{billing}"',
        "GRANT SELECT (max_storage_bytes, max_users, max_guests, auth_options,"
        " banner_image_enabled, support_enabled) ON public.guild_administration"
        f' TO "{billing}"',
        "GRANT UPDATE (max_storage_bytes, max_users, max_guests, auth_options,"
        " banner_image_enabled, support_enabled) ON public.guild_administration"
        f' TO "{billing}"',
    ):
        op.execute(statement)

    with _unforced() as bind:
        for column, key in CAPS:
            bind.exec_driver_sql(
                f"UPDATE public.guild_administration a SET {column} = r.amount"
                " FROM public.community_rules r"
                f" WHERE r.guild_id = a.guild_id AND r.key = '{key}'"
                " AND r.set_by = 'deployment' AND r.user_id IS NULL"
            )
        for option, key in OPTIONS:
            bind.exec_driver_sql(
                "UPDATE public.guild_administration a"
                f" SET auth_options = a.auth_options || '{option}'::public.guild_auth_option"
                " FROM public.community_rules r"
                f" WHERE r.guild_id = a.guild_id AND r.key = '{key}'"
                " AND r.set_by = 'deployment' AND r.user_id IS NULL AND r.enabled"
            )
        for column, key, _default in SWITCHES:
            bind.exec_driver_sql(
                f"UPDATE public.guild_administration a SET {column} = r.enabled"
                " FROM public.community_rules r"
                f" WHERE r.guild_id = a.guild_id AND r.key = '{key}'"
                " AND r.set_by = 'deployment' AND r.user_id IS NULL"
            )
        bind.exec_driver_sql(
            "DROP TRIGGER community_rule_follows_billing ON public.community_rules"
        )
        bind.exec_driver_sql(
            f"DELETE FROM public.community_rules WHERE key = ANY({PAID})"
        )
        bind.exec_driver_sql(
            "DELETE FROM public.community_rules WHERE set_by = 'deployment'"
        )

    bind = op.get_bind()
    bind.exec_driver_sql("DROP FUNCTION public.community_rule_follows_billing()")
    bind.exec_driver_sql(PREVIOUS_GUILD_HOLDS_OPTION)
    bind.exec_driver_sql(PREVIOUS_GUILD_AUTH_SATISFIED)
    op.drop_constraint(
        "fk_community_rules_writer",
        "community_rules",
        type_="foreignkey",
        schema="public",
    )
    op.drop_constraint(
        "ck_community_rules_amount_nonnegative", "community_rules", schema="public"
    )
    _replace_subject("guild_id", "key", "user_id")
    op.alter_column(
        "community_rules",
        "amount",
        type_=sa.Integer(),
        existing_type=sa.BigInteger(),
        schema="public",
    )
    op.drop_column("community_rules", "set_by", schema="public")
    op.drop_table("rule_key_writers", schema="public")
