"""rules live in one place

The rules the deployment and each community store move off their settings rows
into two tables of rows, one per layer: ``public.platform_rules`` for the
deployment's and ``public.community_rules`` for each community's (see
``app.core.rules``). A row holds a rule that says something other than its
default, its value in the one slot its kind uses (``enabled`` or ``amount``);
no row is the default.

Moved, and dropped from where they were:

- ``app_settings``: ``session_max_hours``, ``session_idle_minutes``,
  ``push_notifications_enabled``, ``email_notifications_enabled``,
  ``redact_notification_content``, ``engagement_ranking_enabled``;
- ``guilds``: ``enforce_compliance_session``, ``require_second_factor``,
  ``allow_push_notifications``, ``allow_email_notifications``,
  ``redact_notification_content``, ``allow_engagement_ranking``, ``allow_ai``,
  ``guest_max_days``. The seat's column grants on them go with them; it writes
  ``community_rules`` instead.

Each value that differs from its default is copied before anything is locked
down: the tables are created, filled, and only then have row security enabled
and forced. ``guilds`` is policy-bound for this revision's own role, so its
``FORCE`` is lifted for the copy and restored in the same transaction, and the
copy is counted against its source.

``public.guild_auth_satisfied()`` reads a community's second-factor rule from
``community_rules``. Its body is restated here as this revision installs it;
``app/db/authorization.py`` is what every database converges on at boot.

Policies are rendered at boot from ``SHARED_TABLE_REGISTRY``; this revision
grants what the registry records.

Revision ID: 20261028_0554
Revises: 20261028_0553
Create Date: 2026-10-28
"""

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20261028_0554"
down_revision = "20261028_0553"
branch_labels = None
depends_on = None

SEAT_FLOOR = "app_superadmin"

#: (column, slot, default) of each rule moved off ``app_settings``.
PLATFORM = (
    ("session_max_hours", "amount", None),
    ("session_idle_minutes", "amount", None),
    ("push_notifications_enabled", "enabled", True),
    ("email_notifications_enabled", "enabled", True),
    ("redact_notification_content", "enabled", False),
    ("engagement_ranking_enabled", "enabled", True),
)

#: The same for each rule moved off ``guilds``.
COMMUNITY = (
    ("enforce_compliance_session", "enabled", False),
    ("require_second_factor", "enabled", False),
    ("allow_push_notifications", "enabled", True),
    ("allow_email_notifications", "enabled", True),
    ("redact_notification_content", "enabled", False),
    ("allow_engagement_ranking", "enabled", True),
    ("allow_ai", "enabled", True),
    ("guest_max_days", "amount", None),
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
            -- about how they arrive. Its own row rather than the policy's,
            -- because a community that asks nothing about arrival holds no
            -- policy row and still asks this, while it holds
            -- ``restrictions``. Unsatisfied is what this finds, like the leg
            -- above it.
            SELECT 1
            FROM public.guilds g
            WHERE g.id = (COALESCE(NULLIF(current_setting('app.current_guild_id'::text, true), ''::text), NULLIF(current_setting('app.pam_guild_id'::text, true), ''::text), NULLIF(current_setting('app.settings_guild_id'::text, true), ''::text)))::integer
              AND g.require_second_factor
              AND NOT ('mfa' = ANY(public.session_amr()))
              AND public.guild_holds_option(g.id, 'restrictions')
        ))
$function$

"""


def _differs(column: str, default: object, alias: str) -> str:
    """The rows whose value is not the rule's default."""
    if default is None:
        return f"{alias}.{column} IS NOT NULL"
    return f"{alias}.{column} IS DISTINCT FROM {str(default).lower()}"


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


def _value_columns() -> tuple[sa.Column, ...]:
    return (
        sa.Column("enabled", sa.Boolean(), nullable=True),
        sa.Column("amount", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def _create_tables() -> None:
    op.create_table(
        "platform_rules",
        sa.Column("key", sa.String(length=64), primary_key=True),
        *_value_columns(),
        sa.CheckConstraint(
            "num_nonnulls(enabled, amount) = 1", name="ck_platform_rules_one_slot"
        ),
        schema="public",
    )
    op.create_table(
        "community_rules",
        sa.Column("guild_id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        *_value_columns(),
        sa.ForeignKeyConstraint(["guild_id"], ["public.guilds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("guild_id", "key"),
        sa.CheckConstraint(
            "num_nonnulls(enabled, amount) = 1", name="ck_community_rules_one_slot"
        ),
        schema="public",
    )


def _copy_rules() -> None:
    bind = op.get_bind()
    for column, slot, default in PLATFORM:
        bind.exec_driver_sql(
            f"INSERT INTO public.platform_rules (key, {slot}, updated_at)"
            f" SELECT '{column}', s.{column}, now() FROM public.app_settings s"
            f" WHERE s.id = 1 AND {_differs(column, default, 's')}"
        )
    bind.exec_driver_sql("ALTER TABLE public.guilds NO FORCE ROW LEVEL SECURITY")
    try:
        for column, slot, default in COMMUNITY:
            source = bind.exec_driver_sql(
                f"SELECT count(*) FROM public.guilds g"
                f" WHERE {_differs(column, default, 'g')}"
            ).scalar_one()
            bind.exec_driver_sql(
                f"INSERT INTO public.community_rules (guild_id, key, {slot}, updated_at)"
                f" SELECT g.id, '{column}', g.{column}, now() FROM public.guilds g"
                f" WHERE {_differs(column, default, 'g')}"
            )
            copied = bind.exec_driver_sql(
                f"SELECT count(*) FROM public.community_rules WHERE key = '{column}'"
            ).scalar_one()
            if copied != source:
                raise RuntimeError(
                    f"community_rules.{column}: copied {copied} of {source} rows"
                )
    finally:
        bind.exec_driver_sql("ALTER TABLE public.guilds FORCE ROW LEVEL SECURITY")


def _lock_down() -> None:
    prefix = settings.PLATFORM_ROLE_PREFIX
    base = f"{prefix}platform_base"
    read_floor = f"{prefix}platform_base_ro"
    owner = f"{prefix}platform_owner"
    for table in ("platform_rules", "community_rules"):
        for statement in (
            f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY",
            # The schema's default privileges hand every new public table to
            # both floors, so they are wound back before anything is given.
            f'REVOKE ALL ON TABLE public.{table} FROM app_guild_base, "{base}"',
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.{table} TO app_admin",
            f"GRANT SELECT ON TABLE public.{table} TO app_user",
            f"GRANT SELECT ON TABLE public.{table} TO app_guild_base",
            f"GRANT SELECT ON TABLE public.{table} TO app_guild_base_ro",
            f'GRANT SELECT ON TABLE public.{table} TO "{base}"',
            f'GRANT SELECT ON TABLE public.{table} TO "{read_floor}"',
            f"GRANT SELECT ON TABLE public.{table} TO guest_base",
        ):
            op.execute(statement)
    op.execute(
        f'GRANT INSERT, UPDATE, DELETE ON TABLE public.platform_rules TO "{owner}"'
    )
    _on_seat_floor(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.community_rules"
        f" TO {SEAT_FLOOR}"
    )


def upgrade() -> None:
    _create_tables()
    _copy_rules()
    _lock_down()
    # Before the column it read goes.
    op.get_bind().exec_driver_sql(GUILD_AUTH_SATISFIED)
    for column, _slot, _default in PLATFORM:
        op.drop_column("app_settings", column, schema="public")
    for column, _slot, _default in COMMUNITY:
        op.drop_column("guilds", column, schema="public")


def _restore_column(table: str, column: str, slot: str, default: object) -> None:
    if slot == "amount":
        op.add_column(
            table, sa.Column(column, sa.Integer(), nullable=True), schema="public"
        )
        return
    op.add_column(
        table,
        sa.Column(
            column,
            sa.Boolean(),
            nullable=False,
            server_default=sa.text(str(default).lower()),
        ),
        schema="public",
    )


def downgrade() -> None:
    bind = op.get_bind()
    for column, slot, default in PLATFORM:
        _restore_column("app_settings", column, slot, default)
    for column, slot, default in COMMUNITY:
        _restore_column("guilds", column, slot, default)
    op.create_check_constraint(
        "ck_guilds_guest_max_days", "guilds", "guest_max_days >= 1", schema="public"
    )
    bind.exec_driver_sql(PREVIOUS_GUILD_AUTH_SATISFIED)
    # The copy back reads the rule tables and writes the settings rows, all of
    # them policy-bound for this revision's own role, so each is unforced for
    # it and forced again in the same transaction.
    tables = ("app_settings", "guilds", "platform_rules", "community_rules")
    for table in tables:
        bind.exec_driver_sql(f"ALTER TABLE public.{table} NO FORCE ROW LEVEL SECURITY")
    try:
        for column, slot, _default in PLATFORM:
            bind.exec_driver_sql(
                f"UPDATE public.app_settings s SET {column} = r.{slot}"
                f" FROM public.platform_rules r WHERE r.key = '{column}'"
            )
        for column, slot, default in COMMUNITY:
            source = bind.exec_driver_sql(
                f"SELECT count(*) FROM public.community_rules WHERE key = '{column}'"
            ).scalar_one()
            bind.exec_driver_sql(
                f"UPDATE public.guilds g SET {column} = r.{slot}"
                f" FROM public.community_rules r"
                f" WHERE r.guild_id = g.id AND r.key = '{column}'"
            )
            copied = bind.exec_driver_sql(
                f"SELECT count(*) FROM public.guilds g"
                f" WHERE {_differs(column, default, 'g')}"
            ).scalar_one()
            if copied != source:
                raise RuntimeError(f"guilds.{column}: restored {copied} of {source}")
    finally:
        for table in tables:
            bind.exec_driver_sql(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY")
    columns = ", ".join(column for column, _slot, _default in COMMUNITY)
    _on_seat_floor(f"GRANT UPDATE ({columns}) ON public.guilds TO {SEAT_FLOOR}")
    op.drop_table("community_rules", schema="public")
    op.drop_table("platform_rules", schema="public")
