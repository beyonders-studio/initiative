"""a plug-in makes community contacts

``public.fn_install_owns_what_it_creates``, the trigger on every tool table
that writes the owner row of what a request creates, now also handles a
contact an installed plug-in creates outside any initiative. That contact goes
to the community contacts plug-in's install, which the request's standing names
(``app.community_contacts_install``), and is shared with every member to read,
as a person's community contact is. With no such install the insert is refused.
Everything else it does is unchanged.

Revision ID: 20261111_0607
Revises: 20261110_0606
Create Date: 2026-11-11
"""

from alembic import op

revision = "20261111_0607"
down_revision = "20261110_0606"
branch_labels = None
depends_on = None


_UPGRADE = """
CREATE OR REPLACE FUNCTION public.fn_install_owns_what_it_creates() RETURNS trigger
    LANGUAGE plpgsql AS $owns$
DECLARE
    v_install integer := NULLIF(current_setting('app.current_install_id'::text, true), ''::text)::integer;
    v_member integer := NULLIF(current_setting('app.current_user_id'::text, true), ''::text)::integer;
    v_holder integer := NULLIF(current_setting('app.community_contacts_install'::text, true), ''::text)::integer;
BEGIN
    IF NEW.initiative_id IS NULL THEN
        IF v_install IS NULL OR TG_ARGV[0] <> 'contact' THEN
            RETURN NULL;
        END IF;
        IF v_holder IS NULL THEN
            RAISE EXCEPTION 'no install holds the community''s contacts'
                USING ERRCODE = '42501';
        END IF;
        EXECUTE format(
            'INSERT INTO %I.resource_grants '
            '(resource_type, resource_id, initiative_id, plugin_install_id, level, '
            'all_initiative_members, created_at) '
            'VALUES ($1, $2, NULL, $3, ''owner'', false, now()), '
            '($1, $2, NULL, NULL, ''read'', true, now())',
            TG_TABLE_SCHEMA
        ) USING TG_ARGV[0], NEW.id, v_holder;
        RETURN NULL;
    END IF;
    IF v_install IS NULL AND v_member IS NULL THEN
        RETURN NULL;
    END IF;
    IF v_member IS NULL THEN
        EXECUTE format(
            'INSERT INTO %I.resource_grants '
            '(resource_type, resource_id, initiative_id, plugin_install_id, level, '
            'all_initiative_members, created_at) '
            'VALUES ($1, $2, $3, $4, ''owner'', false, now())',
            TG_TABLE_SCHEMA
        ) USING TG_ARGV[0], NEW.id, NEW.initiative_id, v_install;
    ELSE
        EXECUTE format(
            'INSERT INTO %I.resource_grants '
            '(resource_type, resource_id, initiative_id, user_id, level, '
            'all_initiative_members, created_at) '
            'VALUES ($1, $2, $3, $4, ''owner'', false, now())',
            TG_TABLE_SCHEMA
        ) USING TG_ARGV[0], NEW.id, NEW.initiative_id, v_member;
    END IF;
    RETURN NULL;
END;
$owns$;
"""

_DOWNGRADE = """
CREATE OR REPLACE FUNCTION public.fn_install_owns_what_it_creates() RETURNS trigger
    LANGUAGE plpgsql AS $owns$
DECLARE
    v_install integer := NULLIF(current_setting('app.current_install_id'::text, true), ''::text)::integer;
    v_member integer := NULLIF(current_setting('app.current_user_id'::text, true), ''::text)::integer;
BEGIN
    IF NEW.initiative_id IS NULL OR (v_install IS NULL AND v_member IS NULL) THEN
        RETURN NULL;
    END IF;
    IF v_member IS NULL THEN
        EXECUTE format(
            'INSERT INTO %I.resource_grants '
            '(resource_type, resource_id, initiative_id, plugin_install_id, level, '
            'all_initiative_members, created_at) '
            'VALUES ($1, $2, $3, $4, ''owner'', false, now())',
            TG_TABLE_SCHEMA
        ) USING TG_ARGV[0], NEW.id, NEW.initiative_id, v_install;
    ELSE
        EXECUTE format(
            'INSERT INTO %I.resource_grants '
            '(resource_type, resource_id, initiative_id, user_id, level, '
            'all_initiative_members, created_at) '
            'VALUES ($1, $2, $3, $4, ''owner'', false, now())',
            TG_TABLE_SCHEMA
        ) USING TG_ARGV[0], NEW.id, NEW.initiative_id, v_member;
    END IF;
    RETURN NULL;
END;
$owns$;
"""


def upgrade() -> None:
    op.execute(_UPGRADE)


def downgrade() -> None:
    op.execute(_DOWNGRADE)
