"""a community's sign-in requirement is a rule

What reaching a community asks of its members, and of its guests, moves off
``guild_auth_policies`` into ``community_rules``: one row per half that asks
something, keyed ``auth_policy`` and ``guest_auth_policy``. A requirement keeps
its methods in the new ``methods`` slot and, beside them, the provider it names
in ``provider_id``. That provider key keeps ``ON DELETE RESTRICT``, so deleting
a provider a community requires still surfaces the conflict. The slug the old
row carried is read from the provider where it is wanted.

The old table's checks come with it: a requirement never asks for a password or
an emailed code, and a required one names a provider or a method.

``public.guild_auth_satisfied()`` reads the requirement that applies from
``community_rules``. Its body is restated here as this revision installs it.

Both tables are policy-bound for this revision's own role, so each is unforced
for the copy and forced again in the same transaction, and the copy is counted
against its source. ``guild_auth_policies`` is then dropped; its policies go
with it.

Revision ID: 20261029_0556
Revises: 20261029_0555
Create Date: 2026-10-29
"""

from contextlib import contextmanager

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, ENUM

from app.core.config import settings

revision = "20261029_0556"
down_revision = "20261029_0555"
branch_labels = None
depends_on = None

SEAT_FLOOR = "app_superadmin"
TABLES = ("guild_auth_policies", "community_rules")
LOGIN_METHOD = ENUM(name="login_method", create_type=False)

#: (rule key, the old table's column prefix) for each half.
HALVES = (("auth_policy", ""), ("guest_auth_policy", "guest_"))

ONE_SLOT_BEFORE = "num_nonnulls(enabled, amount) = 1"
ONE_SLOT = (
    "num_nonnulls(enabled, amount, methods) = 1"
    " AND (provider_id IS NULL OR methods IS NOT NULL)"
)
REQUIREMENT = (
    "methods IS NULL OR ("
    "NOT ('password'::login_method = ANY (methods))"
    " AND NOT ('email_otp'::login_method = ANY (methods))"
    " AND (provider_id IS NOT NULL OR cardinality(methods) > 0))"
)

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
            FROM public.guild_auth_policies r
            -- The half that applies: a request routed into one of the
            -- community's guest roles, each granted the guest floor, is asked
            -- what the community asks of its guests.
            CROSS JOIN LATERAL (
                SELECT EXISTS (
                    SELECT 1 FROM pg_auth_members m
                    WHERE m.member = to_regrole(current_user)
                      AND m.roleid = to_regrole('guest_base')
                ) AS guest
            ) routed
            CROSS JOIN LATERAL (
                SELECT
                    r.guild_id,
                    CASE WHEN routed.guest THEN r.guest_policy ELSE r.policy END
                        AS policy,
                    CASE WHEN routed.guest THEN r.guest_provider_id ELSE r.provider_id END
                        AS provider_id,
                    CASE WHEN routed.guest THEN r.guest_require_methods
                        ELSE r.require_methods END
                        AS require_methods
            ) p
            WHERE r.guild_id = (COALESCE(NULLIF(current_setting('app.current_guild_id'::text, true), ''::text), NULLIF(current_setting('app.pam_guild_id'::text, true), ''::text), NULLIF(current_setting('app.settings_guild_id'::text, true), ''::text)))::integer
              AND p.policy <> 'open'
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
                      'totp' = ANY(p.require_methods)
                      AND NOT ('mfa' = ANY(public.session_amr()))
                      AND public.guild_holds_option(p.guild_id, 'providers')
                  )
                  -- Or a passkey, where the community asks for one. Its own
                  -- leg rather than the factor's: an assertion records the
                  -- second factor too, so the two are asked for separately.
                  -- Either kind of key answers, which is what the overlap says.
                  OR (
                      'passkey' = ANY(p.require_methods)
                      AND NOT (public.session_amr() && ARRAY['hwk', 'swk'])
                      AND public.guild_holds_option(p.guild_id, 'providers')
                  )
                  -- Or any of its own, whichever provider served it. Named
                  -- rather than counted, so a list holding some other method
                  -- is not read as this one.
                  OR (
                      'sso' = ANY(p.require_methods)
                      AND NOT public.guild_connection_satisfied(p.guild_id)
                  )
              )
        )
        AND NOT EXISTS (
            -- Asked of everybody reaching this community, whatever it says
            -- about how they arrive. One of its stored rules rather than the
            -- policy's, because a community that asks nothing about arrival
            -- holds no policy row and still asks this, while it holds
            -- ``restrictions``. Unsatisfied is what this finds, like the leg
            -- above it.
            SELECT 1
            FROM public.community_rules r
            WHERE r.guild_id = (COALESCE(NULLIF(current_setting('app.current_guild_id'::text, true), ''::text), NULLIF(current_setting('app.pam_guild_id'::text, true), ''::text), NULLIF(current_setting('app.settings_guild_id'::text, true), ''::text)))::integer
              AND r.key = 'require_second_factor'
              AND r.enabled
              AND NOT ('mfa' = ANY(public.session_amr()))
              AND public.guild_holds_option(r.guild_id, 'restrictions')
        ))
$function$

"""


@contextmanager
def _unforced():
    """Both tables unforced for this revision's role, forced again after."""
    bind = op.get_bind()
    for table in TABLES:
        bind.exec_driver_sql(f"ALTER TABLE public.{table} NO FORCE ROW LEVEL SECURITY")
    try:
        yield bind
    finally:
        for table in TABLES:
            bind.exec_driver_sql(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY")


def _check(what: str, copied: int, source: int) -> None:
    if copied != source:
        raise RuntimeError(f"{what}: copied {copied} of {source} rows")


def _replace_one_slot(expression: str) -> None:
    op.drop_constraint(
        "ck_community_rules_one_slot", "community_rules", schema="public"
    )
    op.create_check_constraint(
        "ck_community_rules_one_slot", "community_rules", expression, schema="public"
    )


def upgrade() -> None:
    op.add_column(
        "community_rules",
        sa.Column("methods", ARRAY(LOGIN_METHOD), nullable=True),
        schema="public",
    )
    op.add_column(
        "community_rules",
        sa.Column(
            "provider_id",
            sa.Integer(),
            sa.ForeignKey("public.auth_providers.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        schema="public",
    )
    _replace_one_slot(ONE_SLOT)
    op.create_check_constraint(
        "ck_community_rules_requirement",
        "community_rules",
        REQUIREMENT,
        schema="public",
    )

    with _unforced() as bind:
        for key, prefix in HALVES:
            source = bind.exec_driver_sql(
                "SELECT count(*) FROM public.guild_auth_policies"
                f" WHERE {prefix}policy <> 'open'"
            ).scalar_one()
            bind.exec_driver_sql(
                "INSERT INTO public.community_rules"
                " (guild_id, key, methods, provider_id, updated_at)"
                f" SELECT guild_id, '{key}', {prefix}require_methods,"
                f" {prefix}provider_id, updated_at"
                f" FROM public.guild_auth_policies WHERE {prefix}policy <> 'open'"
            )
            copied = bind.exec_driver_sql(
                "SELECT count(*) FROM public.community_rules"
                f" WHERE key = '{key}' AND user_id IS NULL"
            ).scalar_one()
            _check(f"community_rules.{key}", copied, source)

    # Before the table it read goes.
    op.get_bind().exec_driver_sql(GUILD_AUTH_SATISFIED)
    op.drop_table("guild_auth_policies", schema="public")


def _on_seat_floor(statement: str) -> None:
    """Run ``statement`` if the seat floor exists: the roles are cluster-global,
    and a database restored beside another deployment's may not carry them."""
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{SEAT_FLOOR}') THEN
                EXECUTE '{statement}';
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    methods = sa.text("'{}'::public.login_method[]")
    op.create_table(
        "guild_auth_policies",
        sa.Column("guild_id", sa.Integer(), nullable=False),
        sa.Column("policy", sa.String(length=16), nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=True),
        sa.Column("provider_slug", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "require_methods",
            ARRAY(LOGIN_METHOD),
            nullable=False,
            server_default=methods,
        ),
        sa.Column(
            "guest_policy", sa.String(length=16), nullable=False, server_default="open"
        ),
        sa.Column("guest_provider_id", sa.Integer(), nullable=True),
        sa.Column("guest_provider_slug", sa.Text(), nullable=True),
        sa.Column(
            "guest_require_methods",
            ARRAY(LOGIN_METHOD),
            nullable=False,
            server_default=methods,
        ),
        sa.PrimaryKeyConstraint("guild_id"),
        sa.ForeignKeyConstraint(["guild_id"], ["public.guilds.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["provider_id"], ["public.auth_providers.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["guest_provider_id"], ["public.auth_providers.id"], ondelete="RESTRICT"
        ),
        *(
            check
            for prefix in ("", "guest_")
            for check in (
                sa.CheckConstraint(
                    f"{prefix}policy IN ('open', 'required')",
                    name=f"ck_guild_auth_policies_{prefix}policy",
                ),
                sa.CheckConstraint(
                    f"NOT ('email_otp'::login_method = ANY ({prefix}require_methods))",
                    name=f"ck_guild_auth_policies_{prefix}require_methods_no_email_otp",
                ),
                sa.CheckConstraint(
                    f"NOT ('password'::login_method = ANY ({prefix}require_methods))",
                    name=f"ck_guild_auth_policies_{prefix}require_methods_no_password",
                ),
                sa.CheckConstraint(
                    f"{prefix}policy = 'open'"
                    f" OR ({prefix}provider_id IS NOT NULL"
                    f" AND {prefix}provider_slug IS NOT NULL)"
                    f" OR cardinality({prefix}require_methods) > 0",
                    name=f"ck_guild_auth_policies_{prefix}required_names_something",
                ),
            )
        ),
        schema="public",
    )
    with _unforced() as bind:
        source = bind.exec_driver_sql(
            "SELECT count(DISTINCT guild_id) FROM public.community_rules"
            " WHERE key IN ('auth_policy', 'guest_auth_policy') AND user_id IS NULL"
        ).scalar_one()
        bind.exec_driver_sql(
            "INSERT INTO public.guild_auth_policies"
            " (guild_id, policy, provider_id, provider_slug, require_methods,"
            " guest_policy, guest_provider_id, guest_provider_slug,"
            " guest_require_methods, updated_at)"
            " SELECT g.guild_id,"
            " CASE WHEN m.guild_id IS NULL THEN 'open' ELSE 'required' END,"
            " m.provider_id, mp.slug, COALESCE(m.methods, '{}'),"
            " CASE WHEN q.guild_id IS NULL THEN 'open' ELSE 'required' END,"
            " q.provider_id, qp.slug, COALESCE(q.methods, '{}'), now()"
            " FROM (SELECT DISTINCT guild_id FROM public.community_rules"
            "  WHERE key IN ('auth_policy', 'guest_auth_policy')"
            "  AND user_id IS NULL) g"
            " LEFT JOIN public.community_rules m ON m.guild_id = g.guild_id"
            "  AND m.key = 'auth_policy' AND m.user_id IS NULL"
            " LEFT JOIN public.auth_providers mp ON mp.id = m.provider_id"
            " LEFT JOIN public.community_rules q ON q.guild_id = g.guild_id"
            "  AND q.key = 'guest_auth_policy' AND q.user_id IS NULL"
            " LEFT JOIN public.auth_providers qp ON qp.id = q.provider_id"
        )
        copied = bind.exec_driver_sql(
            "SELECT count(*) FROM public.guild_auth_policies"
        ).scalar_one()
        _check("guild_auth_policies", copied, source)
        bind.exec_driver_sql(
            "DELETE FROM public.community_rules"
            " WHERE key IN ('auth_policy', 'guest_auth_policy')"
        )

    prefix = settings.PLATFORM_ROLE_PREFIX
    base, read_floor = f"{prefix}platform_base", f"{prefix}platform_base_ro"
    for statement in (
        "ALTER TABLE public.guild_auth_policies ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE public.guild_auth_policies FORCE ROW LEVEL SECURITY",
        f'REVOKE ALL ON TABLE public.guild_auth_policies FROM app_guild_base, "{base}"',
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.guild_auth_policies"
        " TO app_admin",
        "GRANT SELECT ON TABLE public.guild_auth_policies TO app_user",
        "GRANT SELECT ON TABLE public.guild_auth_policies TO app_guild_base",
        "GRANT SELECT ON TABLE public.guild_auth_policies TO app_guild_base_ro",
        f'GRANT SELECT ON TABLE public.guild_auth_policies TO "{base}"',
        f'GRANT SELECT ON TABLE public.guild_auth_policies TO "{read_floor}"',
        "GRANT SELECT ON TABLE public.guild_auth_policies TO guest_base",
    ):
        op.execute(statement)
    _on_seat_floor(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.guild_auth_policies"
        f" TO {SEAT_FLOOR}"
    )
    op.get_bind().exec_driver_sql(PREVIOUS_GUILD_AUTH_SATISFIED)

    op.drop_constraint(
        "ck_community_rules_requirement", "community_rules", schema="public"
    )
    _replace_one_slot(ONE_SLOT_BEFORE)
    op.drop_column("community_rules", "provider_id", schema="public")
    op.drop_column("community_rules", "methods", schema="public")
