"""The revisions after the metadata store that reshape tables older revisions
touch, for a test that runs an older revision on today's schema.

Such a test takes these off one guild schema first, newest first, and puts
them back last, oldest first. A new revision that reshapes a table an older
revision's test reaches is added to ``LATER`` here, once, rather than to every
such test.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

from sqlalchemy import text

_VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"

#: Oldest first.
LATER: tuple[str, ...] = (
    "20261030_0563_assignment_and_reaction_lines_are_one_table.py",
    "20261030_0564_imports_and_exports_are_data_jobs.py",
    "20261030_0567_an_initiatives_role_permissions_are_rules.py",
    "20261030_0568_a_community_sets_its_initiatives_defaults.py",
    "20261031_0573_a_rules_initiative_is_the_communitys.py",
)


def _load(name: str) -> ModuleType:
    path = _VERSIONS / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _steps(bind: Any, *, forward: bool) -> list[Callable[[], None]]:
    batched, data_jobs, rules, defaults, claims = (_load(name) for name in LATER)
    if forward:
        return [
            lambda: batched._upgrade(bind),
            data_jobs._upgrade_schema,
            rules._upgrade,
            defaults._upgrade,
            claims._create,
        ]
    return [
        claims._drop,
        defaults._downgrade,
        rules._downgrade,
        data_jobs._downgrade_schema,
        lambda: batched._downgrade(bind),
    ]


def step_later_revisions(bind: Any, schema: str, *, forward: bool) -> None:
    """Take :data:`LATER` off ``schema`` (``forward=False``) or put them back.
    Run inside an alembic ``Operations`` context on ``bind``."""
    for step in _steps(bind, forward=forward):
        bind.execute(
            text("SELECT set_config('search_path', :sp, true)"),
            {"sp": f"{schema}, public"},
        )
        step()


def later_revisions(schema: str, *, forward: bool) -> Callable[[Any], None]:
    """:func:`step_later_revisions` as its own step, for ``session.run_sync``."""
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    def apply(sync_session: Any) -> None:
        bind = sync_session.connection()
        with Operations.context(MigrationContext.configure(bind)):
            step_later_revisions(bind, schema, forward=forward)

    return apply
