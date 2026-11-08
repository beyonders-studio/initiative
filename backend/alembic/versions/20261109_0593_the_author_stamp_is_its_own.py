"""the author stamp is its own function

``who_made_it`` (0591) first rewrote ``public.fn_set_created_by`` to read
``created_by_kind``, which every caller of that shared function then had to
carry. It now adds ``public.fn_set_author`` for the author tables instead and
leaves ``fn_set_created_by`` as it was. A database that ran it the first way
converges here: ``fn_set_author`` holds the stamp, ``fn_set_created_by`` its
kindless body again, and every schema's triggers on a table with
``created_by_kind`` call ``fn_set_author``. Each step is a no-op on a database
that ran 0591 as it stands now.

Revision ID: 20261109_0593
Revises: 20261109_0592
Create Date: 2026-11-09
"""

from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261109_0593"
down_revision = "20261109_0592"
branch_labels = None
depends_on = None

_AUTHOR_STAMP = """
CREATE OR REPLACE FUNCTION public.fn_set_author() RETURNS trigger
    LANGUAGE plpgsql AS $stamp$
BEGIN
    IF NEW.created_by_kind IS NULL THEN
        IF NEW.created_by IS NOT NULL THEN
            RAISE EXCEPTION 'created_by names no kind' USING ERRCODE = '23514';
        END IF;
        NEW.created_by := NULLIF(
            current_setting('app.current_user_id', true), ''
        )::integer;
        IF NEW.created_by IS NOT NULL THEN
            NEW.created_by_kind := 'member';
        ELSE
            NEW.created_by := NULLIF(
                current_setting('app.current_install_id', true), ''
            )::integer;
            NEW.created_by_kind :=
                CASE WHEN NEW.created_by IS NULL THEN 'system' ELSE 'plugin' END;
        END IF;
    END IF;
    RETURN NEW;
END;
$stamp$;
"""

_KINDLESS_STAMP = """
CREATE OR REPLACE FUNCTION public.fn_set_created_by() RETURNS trigger
    LANGUAGE plpgsql AS $stamp$
BEGIN
    IF NEW.created_by IS NULL THEN
        NEW.created_by := NULLIF(
            current_setting('app.current_user_id', true), ''
        )::integer;
    END IF;
    RETURN NEW;
END;
$stamp$;
"""

_TO_AUTHOR_STAMP = r"""
DO $$
DECLARE found record;
BEGIN
  FOR found IN
    SELECT pg_get_triggerdef(t.oid) AS def
    FROM pg_trigger t
    JOIN pg_class c ON c.oid = t.tgrelid
    WHERE c.relnamespace = current_schema()::regnamespace
      AND t.tgfoid = 'public.fn_set_created_by'::regproc
      AND EXISTS (
        SELECT 1 FROM pg_attribute a
        WHERE a.attrelid = t.tgrelid AND a.attname = 'created_by_kind'
          AND NOT a.attisdropped
      )
  LOOP
    EXECUTE regexp_replace(
      regexp_replace(found.def, 'CREATE TRIGGER', 'CREATE OR REPLACE TRIGGER'),
      'EXECUTE FUNCTION \S*fn_set_created_by\(\)',
      'EXECUTE FUNCTION public.fn_set_author()'
    );
  END LOOP;
END $$;
"""


def _upgrade() -> None:
    op.execute(_TO_AUTHOR_STAMP)


def upgrade() -> None:
    op.execute(_AUTHOR_STAMP)
    run_for_each_guild_schema(op.get_bind(), _upgrade)
    op.execute(_KINDLESS_STAMP)


def downgrade() -> None:
    """Nothing to undo: what this converges to is 0591's own state."""
