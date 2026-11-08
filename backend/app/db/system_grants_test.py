"""The shared-table grant registry (issue #782): verbs and their render.

Pure metadata — no database. That every shared model table has a record is
``tenancy_test``; that the live catalog matches the registry (drift in
either direction) is ``security_invariants_test`` (integration).
"""

from dataclasses import fields

import pytest

from app.core.config import settings
from app.db import system_grants
from app.db.public_rls import (
    PLATFORM_TIER_ROLES,
    SHARED_TABLE_REGISTRY,
    Grants,
    role_name,
)
from app.db.system_grants import (
    VALID_GRANT_VERBS,
    grant_sql,
    grant_statements,
    revoke_statements,
    tier_table_grants,
)
from app.services.storage_backfill import _table_ddl

pytestmark = pytest.mark.always


def test_registry_uses_only_known_dml_verbs():
    """Guard against a typo'd or non-DML verb silently dropping out of the
    rendered GRANT (``grant_sql`` only emits the known verbs)."""
    for table, shared in SHARED_TABLE_REGISTRY.items():
        held = {role.name: getattr(shared.grants, role.name) for role in fields(Grants)}
        held |= {str(capability): verbs for capability, verbs in shared.tiers.items()}
        for holder, verbs in held.items():
            if verbs is None:
                continue
            assert verbs, f"{table}.{holder}: empty verb set (use None)"
            unknown = set(verbs) - VALID_GRANT_VERBS
            assert not unknown, f"{table}.{holder}: unknown verbs {sorted(unknown)}"


def test_grant_sql_renders_canonical_order():
    assert (
        grant_sql(frozenset({"DELETE", "SELECT", "INSERT"})) == "SELECT, INSERT, DELETE"
    )
    assert grant_sql(frozenset({"SELECT"})) == "SELECT"
    assert grant_sql(None) is None
    assert grant_sql(frozenset()) is None


def test_grant_statements_name_the_role_as_the_catalog_holds_it(monkeypatch):
    """A login is named as its connection URL names it, a floor carries the
    configured prefix, and both it and the table are quoted."""
    monkeypatch.setattr(
        settings, "DATABASE_URL_APP", "postgresql+asyncpg://req%22x:pw@h:5432/d"
    )
    monkeypatch.setitem(
        system_grants.ROLE_GRANTS, "app_user", {"t": frozenset({"SELECT", "INSERT"})}
    )
    monkeypatch.setitem(system_grants.ROLE_GRANTS, "platform_base", {"t": None})

    assert grant_statements("app_user", ["t"], sequences=["public.t_id_seq"]) == [
        'GRANT SELECT, INSERT ON TABLE public."t" TO "req""x"',
        'GRANT SELECT, USAGE ON SEQUENCE public.t_id_seq TO "req""x"',
    ]
    assert grant_statements("platform_base", ["t"]) == []
    assert revoke_statements("platform_base", ["t"]) == [
        f'REVOKE ALL ON TABLE public."t" FROM "{role_name("platform_base")}"'
    ]


def test_a_login_both_fields_name_keeps_the_verbs_of_each(monkeypatch):
    """The storage backfill table's grants revoke every present role first, so
    a deployment whose app and admin URLs share one login keeps the system
    engine's verbs on it; a role the catalog does not hold is left out."""
    url = "postgresql+asyncpg://shared:pw@h:5432/d"
    monkeypatch.setattr(settings, "DATABASE_URL_APP", url)
    monkeypatch.setattr(settings, "DATABASE_URL_ADMIN", url)
    absent = role_name("plugin_install_base")
    present = {system_grants.grantee(role) for role in system_grants.ROLE_GRANTS}

    statements = _table_ddl(present - {absent}).splitlines()
    assert not [s for s in statements if absent in s]
    to_login = [s for s in statements if s.endswith('"shared";')]
    assert to_login == [
        'REVOKE ALL ON TABLE public."storage_backfill_state" FROM "shared";',
        'REVOKE ALL ON TABLE public."storage_backfill_state" FROM "shared";',
        (
            'GRANT SELECT, INSERT, UPDATE ON TABLE public."storage_backfill_state" '
            'TO "shared";'
        ),
    ]
    last_revoke = max(i for i, s in enumerate(statements) if s.startswith("REVOKE"))
    assert last_revoke < min(
        i for i, s in enumerate(statements) if s.startswith("GRANT")
    )


def test_tier_grants_render_to_every_tier():
    """Every tier has an entry, and a capability's verbs land on each tier
    holding it."""
    rendered = tier_table_grants()
    assert set(rendered) == PLATFORM_TIER_ROLES
    assert rendered["platform_owner"]["app_settings"] == frozenset(
        {"INSERT", "UPDATE", "DELETE"}
    )
    assert rendered["platform_member"] == {}
