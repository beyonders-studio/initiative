"""A migration may not read the app's registries.

A migration is a historical record: it states the shape of the database at its
own revision. Anything it imports from the live app describes a *later* state,
so a value that moves later reaches back and changes what an old revision does.
That is not hypothetical — 0162 built its permission-key CHECK from
``PermissionKey``, and when a later revision removed two keys from that enum,
0162 began rejecting rows the intervening revisions had not deleted yet. Every
upgrade from an older database failed; a fresh one passed, so CI stayed green.

The rule is therefore an allow-list, not a list of banned registries: a
migration imports the helpers that *run* it, and states every value it writes.
Adding to ``_ALLOWED`` is a deliberate decision about a module whose contents
can never change the meaning of a past revision.
"""

from __future__ import annotations

import ast
from pathlib import Path


_VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"

#: Modules a migration may import from the app.
#:
#: ``app.db.guild_migrations`` is the per-guild-schema execution helper — it
#: carries no schema vocabulary, only the loop that applies a migration to each
#: schema. ``app.core.config`` is deployment configuration (bucket names,
#: connection settings), which describes the environment rather than the shape
#: of the database. ``app.core.encryption`` is the live encryption primitive: a
#: migration that writes a secret must produce something the *current* app can
#: read back, so pinning an old implementation is the broken version of this.
#: ``app.db.authorization`` is the same case in a different shape: every
#: database converges on that module's bodies, re-applied on each boot and
#: diffed by ``authorization_test``, so a literal copied into a revision is
#: replaced the next time the app starts. Copying one would only add a second
#: place for the same SQL to drift. ``app.services.storage`` is where the
#: deployment keeps its files: a migration that copies one must write it where
#: the current app reads it, as with encryption. ``app.core.recurrence`` is the
#: converter for RFC 5545 repeats: a migration that writes one must write what
#: the current app reads, and the standard it implements does not move. The
#: revision states the shape it converts from itself. ``app.core.legacy_references``
#: is the same case for links in a body: it states the spellings older builds
#: wrote and writes them as the current app reads them. ``app.services.editor_engine``
#: is the editor itself: a body's Yjs state is only read and written through it,
#: and a migration that changes one must leave what the current editor reads.
_ALLOWED = frozenset(
    {
        "app.db.guild_migrations",
        "app.core.config",
        "app.core.encryption",
        "app.db.authorization",
        "app.services.storage",
        "app.core.recurrence",
        "app.core.legacy_references",
        "app.services.editor_engine",
    }
)


def _app_imports(tree: ast.AST) -> set[str]:
    """Every ``app.*`` module a migration pulls from, however it is written."""
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            # Relative imports have no module of ours to name.
            if node.level == 0 and node.module and node.module.startswith("app"):
                modules.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("app"):
                    modules.add(alias.name)
    return modules


def test_migrations_import_no_app_registries():
    files = sorted(_VERSIONS.glob("*.py"))
    assert files, f"no migrations found under {_VERSIONS}"

    offenders: list[str] = []
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for module in sorted(_app_imports(tree) - _ALLOWED):
            offenders.append(f"{path.name}: {module}")

    assert not offenders, (
        "a migration must state the values it writes, not read them from the "
        "live app — a registry that changes later would reach back and change "
        "what this revision does to databases upgrading through it. Spell the "
        "values out as literals (see 0162, 0166, 0174), or add the module to "
        f"_ALLOWED if its contents can never do that: {offenders}"
    )
