"""The grants the request-path Postgres roles hold on the shared (``public``)
tables, as views of ``app.db.public_rls.SHARED_TABLE_REGISTRY``.

Each shared table is declared once there, row security and grants together
(``SharedTable``). This module reads it per role: ``ROLE_GRANTS`` is one
table -> verbs matrix per role in ``Grants``, and ``tier_table_grants`` spells
the capability-keyed tier grants as the ``platform_<tier>`` roles holding each
capability. ``grant_statements`` and ``revoke_statements`` render a role's
grants as SQL to its catalog name (``grantee``: a login as its URL names it),
and ``missing_grants`` probes what that name does not hold. Those views are what the catalog is held to:

* ``security_invariants_test`` fails on any drift in either direction (a
  hotfix ``GRANT`` the registry doesn't know about, or a registry verb the
  catalog lacks);
* ``tenancy_test`` fails when a model's table has no placement, and a
  shared table's placement is its registry record.

Migrations remain the immutable record of *when* a grant changed (they still
run the actual ``GRANT``/``REVOKE``). See issue #782.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import fields

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.capabilities import roles_with_capability
from app.core.config import settings
from app.db.public_rls import (
    PLATFORM_TIER_ROLES,
    SHARED_TABLE_REGISTRY,
    Grants,
    platform_tier,
    role_name,
)

__all__ = [
    "LOGIN_SETTINGS",
    "ROLE_GRANTS",
    "VALID_GRANT_VERBS",
    "grant_sql",
    "grant_statements",
    "grantee",
    "missing_grants",
    "revoke_statements",
    "tier_table_grants",
]

# Canonical DML verb order for rendered ``GRANT`` statements. Grant order is
# semantically irrelevant, so the registry stores verb *sets* (compared directly
# against the catalog) and only imposes an order when rendering SQL — this keeps
# a re-grant written in a different order from reading as spurious "drift".
_VERB_ORDER: tuple[str, ...] = ("SELECT", "INSERT", "UPDATE", "DELETE")
VALID_GRANT_VERBS: frozenset[str] = frozenset(_VERB_ORDER)


#: One matrix per role in ``Grants`` (``app_admin``, ``app_user``, the four
#: floors): table -> the verbs it holds, or ``None``.
ROLE_GRANTS: dict[str, dict[str, frozenset[str] | None]] = {
    role.name: {
        table: getattr(shared.grants, role.name)
        for table, shared in SHARED_TABLE_REGISTRY.items()
    }
    for role in fields(Grants)
}


def tier_table_grants() -> dict[str, dict[str, frozenset[str]]]:
    """The registry's tier grants spelled as tiers: every ``platform_<tier>``
    role, unprefixed, with the verbs it holds per table. A tier holding no
    capability named there maps to an empty dict."""
    rendered: dict[str, dict[str, frozenset[str]]] = {
        role: {} for role in PLATFORM_TIER_ROLES
    }
    for table, shared in SHARED_TABLE_REGISTRY.items():
        for capability, verbs in shared.tiers.items():
            for role in roles_with_capability(capability):
                tables = rendered[platform_tier(role)]
                tables[table] = tables.get(table, frozenset()) | verbs
    return rendered


def grant_sql(verbs: frozenset[str] | None) -> str | None:
    """Render a registry verb set as a canonical ``GRANT`` verb list (fixed
    order), or ``None`` when the role gets no access — lets a future migration
    emit the grant straight from the registry instead of re-typing verbs."""
    if not verbs:
        return None
    return ", ".join(v for v in _VERB_ORDER if v in verbs)


#: The setting naming the login each login field of ``Grants`` stands for.
LOGIN_SETTINGS: dict[str, str] = {
    "app_admin": "DATABASE_URL_ADMIN",
    "app_user": "DATABASE_URL_APP",
}

#: What a login holding INSERT on a table holds on the table's row-id sequence.
_LOGIN_SEQUENCE_VERBS: dict[str, str] = {
    "app_admin": "ALL",
    "app_user": "SELECT, USAGE",
}


def grantee(role: str) -> str:
    """The catalog role a ``Grants`` field names: a login as the deployment's
    connection URL names it, a floor under its configured prefix."""
    setting = LOGIN_SETTINGS.get(role)
    return settings.database_login(setting)[0] if setting else role_name(role)


def _quoted(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def revoke_statements(role: str, tables: Iterable[str]) -> list[str]:
    """``REVOKE ALL`` on each of ``tables`` from ``role``'s catalog name
    (:func:`grantee`). Run every role's revokes before any role's grants and
    the tables converge on the registry, a login two fields name included."""
    to = _quoted(grantee(role))
    return [
        f"REVOKE ALL ON TABLE public.{_quoted(table)} FROM {to}" for table in tables
    ]


def grant_statements(
    role: str, tables: Iterable[str], *, sequences: Iterable[str] = ()
) -> list[str]:
    """The registry's verbs for ``role`` on each of ``tables``, as ``GRANT``
    statements to its catalog name (:func:`grantee`). ``sequences`` are the
    qualified row-id sequences of tables the role inserts into, granted what a
    login needs to insert."""
    to = _quoted(grantee(role))
    statements = [
        f"GRANT {verbs} ON TABLE public.{_quoted(table)} TO {to}"
        for table in tables
        if (verbs := grant_sql(ROLE_GRANTS[role][table]))
    ]
    statements += [
        f"GRANT {_LOGIN_SEQUENCE_VERBS[role]} ON SEQUENCE {sequence} TO {to}"
        for sequence in sequences
    ]
    return statements


_MISSING_GRANTS = text(
    "SELECT t.tbl, t.priv "
    "FROM unnest(CAST(:tables AS text[]), CAST(:verbs AS text[])) AS t(tbl, priv) "
    "WHERE to_regclass(format('public.%I', t.tbl)) IS NOT NULL "
    "  AND NOT has_table_privilege("
    "    CAST(:grantee AS text), format('public.%I', t.tbl), t.priv)"
)


async def missing_grants(conn: AsyncConnection, role: str) -> list[tuple[str, str]]:
    """The ``(table, verb)`` pairs the registry gives ``role`` that its catalog
    name does not effectively hold, in one round trip. A table the registry
    names but that does not exist yet (``tenancy.NON_MODEL_SHARED_TABLES`` are
    created by their service) has nothing to hold."""
    pairs = [
        (table, verb)
        for table, verbs in ROLE_GRANTS[role].items()
        for verb in sorted(verbs or ())
    ]
    rows = await conn.execute(
        _MISSING_GRANTS,
        {
            "tables": [table for table, _verb in pairs],
            "verbs": [verb for _table, verb in pairs],
            "grantee": grantee(role),
        },
    )
    return [(table, verb) for table, verb in rows]
