"""the deployment's switches and limits are rules

The rest of the deployment's switches and limits move off ``app_settings`` into
``platform_rules`` (see ``app.core.rules``), one row per rule that differs from
its default:

- ``cookie_consent_enabled``, ``community_directory_enabled``,
  ``community_age_gate_enabled``, ``guests_enabled``,
  ``provider_placement_everywhere``, ``direct_messages_enabled``,
  ``marketplace_members_publish_directly``, ``marketplace_registry_enabled``;
- ``max_guest_days``;
- the three retention windows. A window's figure is an ``amount`` row, and
  "never", which the column said with NULL, is an ``enabled`` row beside it
  switched off: ``erase_deleted_accounts``, ``destroy_deleted_communities``
  and ``delete_held_communities``.

``public.guest_membership_live()`` and ``public.dm_reachable()`` read their
switch from ``platform_rules``. Their bodies are restated here as this
revision installs them. The plug-in floor reads guest memberships, so it reads
``platform_rules`` as it read ``app_settings``; the direct-message reader reads
the two columns its rule needs.

``platform_rules`` is policy-bound for this revision's own role, so it is
unforced for the copy and forced again in the same transaction, and the copy is
counted against its source. The columns are then dropped.

Revision ID: 20261029_0558
Revises: 20261029_0557
Create Date: 2026-10-29
"""

from contextlib import contextmanager

import sqlalchemy as sa
from alembic import op

revision = "20261029_0558"
down_revision = "20261029_0557"
branch_labels = None
depends_on = None

#: Policy-bound for this revision's role, so unforced while the rows cross.
TABLES = ("app_settings", "platform_rules")
#: The reader role that owns the direct-message rule's functions (0223, 0417).
DM_READER = "app_dm_reader"

#: (column, slot, default) of each switch and limit that moves as it is.
MOVED = (
    ("cookie_consent_enabled", "enabled", False),
    ("community_directory_enabled", "enabled", False),
    ("community_age_gate_enabled", "enabled", True),
    ("guests_enabled", "enabled", False),
    ("max_guest_days", "amount", 90),
    ("provider_placement_everywhere", "enabled", False),
    ("direct_messages_enabled", "enabled", True),
    ("marketplace_members_publish_directly", "enabled", False),
    ("marketplace_registry_enabled", "enabled", True),
)

#: (column, the rule that says whether it runs, default) of each window.
WINDOWS = (
    ("deleted_account_retention_days", "erase_deleted_accounts", 30),
    ("deleted_community_retention_days", "destroy_deleted_communities", 90),
    ("on_hold_community_deletion_days", "delete_held_communities", 30),
)

KEYS = tuple(column for column, _slot, _default in MOVED) + tuple(
    key for column, switch, _default in WINDOWS for key in (column, switch)
)

GUEST_MEMBERSHIP_LIVE = """\
CREATE OR REPLACE FUNCTION public.guest_membership_live(p_until timestamp with time zone, p_role guild_role)
 RETURNS boolean
 LANGUAGE plpgsql
 STABLE
AS $function$
BEGIN
    RETURN p_until > now() AND EXISTS (
        SELECT 1
        FROM public.app_settings s
        WHERE s.id = 1
          AND COALESCE(
              (SELECT r.enabled FROM public.platform_rules r
                WHERE r.key = 'guests_enabled'),
              false
          )
          AND (p_role = 'guest' OR s.demo_mode)
    );
END
$function$

"""

PREVIOUS_GUEST_MEMBERSHIP_LIVE = """\
CREATE OR REPLACE FUNCTION public.guest_membership_live(p_until timestamp with time zone, p_role guild_role)
 RETURNS boolean
 LANGUAGE plpgsql
 STABLE
AS $function$
BEGIN
    RETURN p_until > now() AND EXISTS (
        SELECT 1
        FROM public.app_settings s
        WHERE s.id = 1
          AND s.guests_enabled
          AND (p_role = 'guest' OR s.demo_mode)
    );
END
$function$

"""


def _reachable(age_rule: str) -> str:
    return f"""
    CREATE OR REPLACE FUNCTION public.dm_reachable(account_id int)
    RETURNS boolean
    LANGUAGE sql STABLE PARALLEL SAFE SECURITY DEFINER
    SET search_path = pg_catalog, public
    AS $fn$
      SELECT EXISTS (
        SELECT 1 FROM public.users u
        WHERE u.id = account_id
          AND u.status = 'active'
          AND {age_rule}
      )
    $fn$
    """


#: Answered, or not asked on this deployment.
ANSWERED_OR_NOT_ASKED = """(
            u.age_confirmed_at IS NOT NULL
            OR NOT COALESCE(
              (SELECT r.enabled FROM public.platform_rules r
                 WHERE r.key = 'community_age_gate_enabled'),
              true
            )
          )"""

#: 0469's rule.
PREVIOUS_ANSWERED_OR_NOT_ASKED = """(
            u.age_confirmed_at IS NOT NULL
            OR NOT COALESCE(
              (SELECT s.community_age_gate_enabled
                 FROM public.app_settings s WHERE s.id = 1),
              true
            )
          )"""

#: What the direct-message reader reads of each table, before and after.
DM_READER_RULES = "SELECT (key, enabled) ON TABLE public.platform_rules"
DM_READER_SETTINGS = (
    "SELECT (id, community_age_gate_enabled) ON TABLE public.app_settings"
)

#: The moved keys, as a SQL array.
MOVED_KEYS = "ARRAY[" + ", ".join(f"'{key}'" for key in KEYS) + "]"


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


def _copies() -> list[tuple[str, str, str, str]]:
    """(key, slot, value, condition) of every row the settings row says, each
    over ``app_settings s``."""
    copies: list[tuple[str, str, str, str]] = [
        (column, slot, f"s.{column}", f"s.{column} IS DISTINCT FROM {default}")
        for column, slot, default in MOVED
    ]
    for column, switch, default in WINDOWS:
        copies.append((switch, "enabled", "false", f"s.{column} IS NULL"))
        copies.append((column, "amount", f"s.{column}", f"s.{column} <> {default}"))
    return copies


def upgrade() -> None:
    copies = _copies()
    with _unforced() as bind:
        source = bind.exec_driver_sql(
            "SELECT "
            + " + ".join(f"({condition})::int" for *_, condition in copies)
            + " FROM public.app_settings s WHERE s.id = 1"
        ).scalar()
        for key, slot, value, condition in copies:
            bind.exec_driver_sql(
                f"INSERT INTO public.platform_rules (key, {slot}, updated_at)"
                f" SELECT '{key}', {value}, now() FROM public.app_settings s"
                f" WHERE s.id = 1 AND {condition}"
            )
        copied = bind.exec_driver_sql(
            f"SELECT count(*) FROM public.platform_rules WHERE key = ANY({MOVED_KEYS})"
        ).scalar_one()
        _check("platform_rules", copied, source or 0)

    bind = op.get_bind()
    bind.exec_driver_sql(GUEST_MEMBERSHIP_LIVE)
    op.execute(f'GRANT "{DM_READER}" TO CURRENT_USER WITH INHERIT TRUE, SET TRUE')
    op.execute(f'GRANT {DM_READER_RULES} TO "{DM_READER}"')
    op.execute(_reachable(ANSWERED_OR_NOT_ASKED))
    op.execute(f'REVOKE {DM_READER_SETTINGS} FROM "{DM_READER}"')
    op.execute("GRANT SELECT ON TABLE public.platform_rules TO plugin_install_base")

    for column, _slot, _default in MOVED:
        op.drop_column("app_settings", column, schema="public")
    for column, _switch, _default in WINDOWS:
        op.drop_column("app_settings", column, schema="public")


def downgrade() -> None:
    for column, slot, default in MOVED:
        kind = sa.Integer() if slot == "amount" else sa.Boolean()
        op.add_column(
            "app_settings",
            sa.Column(
                column,
                kind,
                nullable=False,
                server_default=sa.text(str(default).lower()),
            ),
            schema="public",
        )
    op.create_check_constraint(
        "ck_app_settings_max_guest_days",
        "app_settings",
        "max_guest_days >= 1",
        schema="public",
    )
    for column, _switch, default in WINDOWS:
        op.add_column(
            "app_settings",
            sa.Column(column, sa.Integer(), nullable=True, server_default=str(default)),
            schema="public",
        )

    with _unforced() as bind:
        for column, slot, _default in MOVED:
            bind.exec_driver_sql(
                f"UPDATE public.app_settings s SET {column} = r.{slot}"
                f" FROM public.platform_rules r WHERE r.key = '{column}'"
            )
        for column, switch, _default in WINDOWS:
            bind.exec_driver_sql(
                f"UPDATE public.app_settings s SET {column} = r.amount"
                f" FROM public.platform_rules r WHERE r.key = '{column}'"
            )
            bind.exec_driver_sql(
                f"UPDATE public.app_settings s SET {column} = NULL"
                f" FROM public.platform_rules r"
                f" WHERE r.key = '{switch}' AND NOT r.enabled"
            )
        bind.exec_driver_sql(
            f"DELETE FROM public.platform_rules WHERE key = ANY({MOVED_KEYS})"
        )

    bind = op.get_bind()
    bind.exec_driver_sql(PREVIOUS_GUEST_MEMBERSHIP_LIVE)
    op.execute("REVOKE SELECT ON TABLE public.platform_rules FROM plugin_install_base")
    op.execute(f'GRANT "{DM_READER}" TO CURRENT_USER WITH INHERIT TRUE, SET TRUE')
    op.execute(f'GRANT {DM_READER_SETTINGS} TO "{DM_READER}"')
    op.execute(_reachable(PREVIOUS_ANSWERED_OR_NOT_ASKED))
    op.execute(f'REVOKE {DM_READER_RULES} FROM "{DM_READER}"')
