"""schemas drop what older releases left

Every community schema was re-rendered on each boot with steps that removed
what an earlier render had left there: the ``guild_level_open`` allow-all
policy on the managed tables (the tables that still use it keep it), the ``frozen_ancestor_update`` and
``frozen_ancestor_delete`` policies, the ancestor delete trigger on tables that
no longer have one, and the guild functions under signatures the render no
longer makes. The query role was revoked the read floor it once inherited, and
bootstrap revoked the default privileges an old setup script gave the login
roles. This does each once, everywhere, so the render and bootstrap stop
carrying them.

A healthy community already had all of this removed at its last boot; what
remains is in one whose rebuild kept failing. A retired function a stale policy
still calls is left in place with a notice rather than dropped with the policy:
dropping a restrictive policy would widen access. That community's next
rebuild re-creates its policies without it, and the function is then unused.

Revision ID: 20261109_0599
Revises: 20261109_0598
Create Date: 2026-11-09
"""

from alembic import op

from app.core.config import settings
from app.db.authorization import RETIRED_GUILD_FUNCTION_SIGNATURES
from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261109_0599"
down_revision = "20261109_0598"
branch_labels = None
depends_on = None

#: The policy names earlier renders made and the current one does not.
_RETIRED_POLICIES = ("frozen_ancestor_update", "frozen_ancestor_delete")

#: The tables a manager writes (``app.db.tenancy.MANAGED_TABLES``), whose
#: ``guild_level_open`` allow-all the managed policies replaced. Other tables
#: keep theirs.
_MANAGED = ("initiative_members", "initiative_roles", "initiative_rules", "initiatives")

#: Tables whose ``tr_<table>_frozen_ancestor_delete`` trigger the render
#: stopped making (``app.db.frozen.frozen_write_triggers`` as of this revision).
_NO_ANCESTOR_DELETE_TRIGGER = (
    "batched_notices",
    "case_grants",
    "content_holds",
    "custom_role_claim_rules",
    "custom_role_members",
    "custom_roles",
    "data_jobs",
    "engagement_levels",
    "event_outbox",
    "event_reminder_dispatches",
    "evidence",
    "guest_invite_grants",
    "guild_ai_connection_keys",
    "guild_ai_connections",
    "guild_plugin_secrets",
    "guild_plugin_user_connections",
    "guild_plugins",
    "guild_settings",
    "moderation_report_reporters",
    "personal_items",
    "plugin_connection_secrets",
    "plugin_event_outbox",
    "plugin_hook_deliveries",
    "plugin_schedule_runs",
    "post_reads",
    "relationships",
    "resource_grants",
    "search_entries",
    "subscription_progress",
    "tags",
    "timer_marks",
    "uploads",
    "view_preferences",
    "webhook_deliveries",
    "webhook_refs",
)


def _array(names: tuple[str, ...]) -> str:
    return "ARRAY[" + ", ".join(f"'{name}'" for name in names) + "]"


def _schema_cleanup() -> str:
    retired = " ".join(
        f"""
        IF to_regprocedure(format('%I.{name}{args}', current_schema())) IS NOT NULL THEN
          BEGIN
            EXECUTE format('DROP FUNCTION %I.{name}{args}', current_schema());
          EXCEPTION WHEN dependent_objects_still_exist THEN
            RAISE NOTICE '%.{name}{args} is still called; its next rebuild frees it',
              current_schema();
          END;
        END IF;"""
        for name, args in RETIRED_GUILD_FUNCTION_SIGNATURES
    )
    return f"""
DO $cleanup$
DECLARE found record;
BEGIN
  FOR found IN
    SELECT c.relname, p.polname FROM pg_policy p
    JOIN pg_class c ON c.oid = p.polrelid
    WHERE c.relnamespace = current_schema()::regnamespace
      AND (
        p.polname = ANY({_array(_RETIRED_POLICIES)})
        OR (p.polname = 'guild_level_open' AND c.relname = ANY({_array(_MANAGED)}))
      )
  LOOP
    EXECUTE format('DROP POLICY %I ON %I', found.polname, found.relname);
  END LOOP;
  FOR found IN
    SELECT c.relname, t.tgname FROM pg_trigger t
    JOIN pg_class c ON c.oid = t.tgrelid
    WHERE c.relnamespace = current_schema()::regnamespace
      AND NOT t.tgisinternal
      AND c.relname = ANY({_array(_NO_ANCESTOR_DELETE_TRIGGER)})
      AND t.tgname = 'tr_' || c.relname || '_frozen_ancestor_delete'
  LOOP
    EXECUTE format('DROP TRIGGER %I ON %I', found.tgname, found.relname);
  END LOOP;
  {retired}
END
$cleanup$;
"""


def upgrade() -> None:
    cleanup = _schema_cleanup()
    run_for_each_guild_schema(op.get_bind(), lambda: op.execute(cleanup))

    # The query role reads its own community and the routed members view, and
    # inherits no floor.
    query_role = f"^{settings.GUILD_ROLE_PREFIX}guild_[0-9]+_q$"
    op.execute(
        f"""
DO $floor$
DECLARE found record;
BEGIN
  FOR found IN
    SELECT m.rolname FROM pg_auth_members a
    JOIN pg_roles m ON m.oid = a.member
    JOIN pg_roles g ON g.oid = a.roleid
    WHERE g.rolname = 'app_guild_base_ro' AND m.rolname ~ '{query_role}'
  LOOP
    EXECUTE format('REVOKE app_guild_base_ro FROM %I', found.rolname);
  END LOOP;
END
$floor$;
"""
    )

    # A login role holds no default privilege: a new shared table gives it
    # nothing until a migration grants it from the registry.
    for setting in ("DATABASE_URL_APP", "DATABASE_URL_ADMIN"):
        login = settings.database_login(setting)[0]
        op.execute(
            f"""
DO $defaults$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{login}') THEN
    ALTER DEFAULT PRIVILEGES FOR ROLE CURRENT_USER IN SCHEMA public
      REVOKE ALL ON TABLES FROM "{login}";
    ALTER DEFAULT PRIVILEGES FOR ROLE CURRENT_USER IN SCHEMA public
      REVOKE ALL ON SEQUENCES FROM "{login}";
  END IF;
END
$defaults$;
"""
        )


def downgrade() -> None:
    """Nothing to restore: what this removed was already out of use."""
