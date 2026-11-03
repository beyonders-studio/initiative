"""The **field registry** — the datasets this deployment knows, and the bridge
from their declarations to the query engine.

Always the *field* registry, never the bare word: this codebase has several
registries (the initiative-RLS paths, the DAC resources, the auth providers) and
the qualifier is what says which one. It answers a single question — *what
fields does this thing have, and what may I do with them* — for every surface
that asks it.

One lookup for every consumer: the task list endpoint compiles filters through
:func:`allowed_fields` and orders through :func:`sort_fields`, the filter UI is
served :func:`describe`, and the query surface resolves names here rather than
against the physical schema.

Datasets are built on first use rather than at import. A declaration reads model
columns, and reading them at import time would tie this module's import order to
the mappers being configured — a fragility with nothing to gain, since the set
never changes within a process.
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache
from typing import Any, Callable

from app.services.fields import calendar_events as calendar_events_dataset
from app.services.fields import members as members_dataset
from app.services.fields import projects as projects_dataset
from app.services.fields import properties as property_datasets
from app.services.fields import relationships as relationships_dataset
from app.services.fields import task_assignees as task_assignees_dataset
from app.services.fields import tools as tool_datasets
from app.services.fields import task_statuses as task_statuses_dataset
from app.services.fields import task_types as task_types_dataset
from app.services.fields import tasks as tasks_dataset
from app.schemas.query import FilterOp
from app.services.fields.spec import Dataset, FieldContext, FieldSpec, SortContext

#: Every dataset, by the name a consumer refers to it by. One entry per
#: declaration module; the module owns its fields, this owns the set.
_BUILDERS: dict[str, Callable[[], Dataset]] = {
    "tasks": tasks_dataset.build,
    "projects": projects_dataset.build,
    "calendar_events": calendar_events_dataset.build,
    "counter_groups": tool_datasets.build_counter_groups,
    "counters": tool_datasets.build_counters,
    "task_statuses": task_statuses_dataset.build,
    "task_types": task_types_dataset.build,
    "task_assignees": task_assignees_dataset.build,
    "members": members_dataset.build,
    "metadata_definitions": property_datasets.build_metadata_definitions,
    "metadata_values": property_datasets.build_metadata_values,
    "relationships": relationships_dataset.build,
    # The datasets that are simply a tool. Declared together because there is
    # nothing to say about any of them individually (app.services.fields.tools).
    "files": tool_datasets.build_files,
    "file_versions": tool_datasets.build_file_versions,
    "queues": tool_datasets.build_queues,
    "queue_items": tool_datasets.build_queue_items,
    "calendars": tool_datasets.build_calendars,
    "dashboards": tool_datasets.build_dashboards,
    "posts": tool_datasets.build_posts,
    "collections": tool_datasets.build_collections,
    "wikis": tool_datasets.build_wikis,
    "wiki_pages": tool_datasets.build_wiki_pages,
}


#: The datasets, as a type. Derived from the builders above rather than typed
#: out again, so a new dataset is nameable by a client — and refused by FastAPI
#: when it is not one — the moment it is declared, with no second list and no
#: hand-rolled "unknown dataset" branch to keep in step.
DatasetName = Enum("DatasetName", {name: name for name in _BUILDERS}, type=str)
DatasetName.__doc__ = "A dataset the field registry describes."


@lru_cache(maxsize=None)
def _built() -> dict[str, Dataset]:
    return {name: build() for name, build in _BUILDERS.items()}


def dataset(name: str) -> Dataset:
    """The named dataset, or ``KeyError`` — callers name a constant, not input."""
    return _built()[name]


def dataset_names() -> tuple[str, ...]:
    """Every dataset a query may name."""
    return tuple(_built())


def allowed_fields(dataset_name: str, ctx: FieldContext) -> dict[str, Any]:
    """The ``allowed_fields`` mapping ``apply_filters`` consumes.

    A column field passes its column straight through; a computed one is bound
    to *ctx* here, because the engine calls a handler with ``(op, value)`` and
    knows nothing about whose request it is compiling for.

    Unknown fields are skipped by ``apply_filters`` rather than rejected, so a
    field this dataset does not declare simply narrows nothing — the same
    defense-in-depth the engine has always had.
    """
    resolved: dict[str, Any] = {}
    for spec in dataset(dataset_name).fields:
        if not spec.filterable:
            continue
        if spec.column is not None:
            resolved[spec.name] = spec.column
        else:
            resolved[spec.name] = _bind(spec, ctx)
    return resolved


def _bind(spec: FieldSpec, ctx: FieldContext) -> Callable[[Any, Any], Any]:
    """Bind a resolver to one request's context.

    A named function rather than a lambda so a traceback through a filter says
    which field it was compiling.
    """
    resolver = spec.resolve
    assert resolver is not None  # guaranteed by FieldSpec.__post_init__

    def resolve_field(op: Any, value: Any) -> Any:
        return resolver(op, value, ctx)

    resolve_field.__name__ = f"resolve_{spec.name}"
    return resolve_field


def allowed_ops(dataset_name: str) -> dict[str, frozenset[FilterOp]]:
    """The operators each field accepts, for ``apply_filters`` to enforce.

    Enforcement rather than description: a filter is applied in full or
    refused, so what a stored definition asks for and what it receives agree.
    """
    return {
        spec.name: spec.ops for spec in dataset(dataset_name).fields if spec.filterable
    }


def sort_fields(dataset_name: str, ctx: SortContext) -> dict[str, Any]:
    """The ``allowed_fields`` mapping ``apply_sorting`` consumes.

    Sorting lives in the same declaration as filtering because a field's
    orderability is a fact about the field, and because the query surface needs
    both from one place — ``ORDER BY`` is as much a part of SQL as ``WHERE``.

    Unlike filtering, these are plain expressions rather than callables: the
    sort engine takes a column to order by, so a field whose ordering depends on
    the request (a grouping in the reader's own timezone) is resolved here.
    """
    resolved: dict[str, Any] = {}
    for spec in dataset(dataset_name).fields:
        if not spec.sortable:
            continue
        resolved[spec.name] = spec.sort(ctx) if spec.sort is not None else spec.column
    return resolved


def sort_expression(dataset_name: str, field_name: str, ctx: SortContext) -> Any:
    """One field's ordering expression.

    For the caller that selects an ordering as a labelled column rather than
    only ordering by it — a cross-guild merge sorts in Python and needs the
    value carried out of SQL.
    """
    return sort_fields(dataset_name, ctx)[field_name]


def describe(dataset_name: str) -> list[dict[str, Any]]:
    """The dataset's fields as a client offers them, in the order it lists them.

    Deliberately not the resolvers: what a field compiles to is ours, and what
    it is called, holds, and is picked with is the client's. The operators here
    are what a *control* offers, which is the control's set narrowed to what the
    engine accepts — never the engine's full set, which includes shapes that are
    correct to compile and pointless to draw.
    """
    return [
        {
            "name": spec.name,
            "type": spec.type.value,
            "kind": spec.kind.value,
            "ops": sorted(op.value for op in spec.offered_ops),
            "multiple": spec.multiple,
            "sortable": spec.sortable,
            "options": list(spec.options),
        }
        for spec in dataset(dataset_name).offered
    ]


#: What a statement about live content leaves out, as field names.
#:
#: Archived means *finished with* and a template is a shape rather than work
#: anybody is doing, so neither belongs in the figures a dashboard reports by
#: default. Unlike the trash — which the query surface removes outright, in the
#: database, with no way to ask for it back — these are a **starting point**: a
#: report on what was archived last quarter is a fair question, so the builder
#: writes them as ordinary filter rows the author can see and delete.
_ARCHIVED_FIELD = "archived_at"
_TEMPLATE_FIELD = "is_template"


def default_filters(dataset_name: str) -> list[dict[str, Any]]:
    """The conditions a new statement about *dataset_name* starts with.

    Derived rather than listed, so a dataset that gains either lifecycle gets
    the filter without anybody remembering to add it here.

    A dataset that has no template flag of its own may still be *governed* by
    something that has one — a task is a project's, which is the same answer
    the sharing gate reaches for (``Dataset.tool``). Where that governing
    dataset is also one this dataset declares a way to, the filter is written
    through that relation, so ``tasks`` excludes the work inside a template
    project without ``tasks`` having to know what a template is.
    """
    spec = dataset(dataset_name)
    conditions: list[dict[str, Any]] = []
    if _ARCHIVED_FIELD in spec.by_name:
        conditions.append({"field": _ARCHIVED_FIELD, "op": "is_null", "value": True})

    template_field = _template_field(spec)
    if template_field is not None:
        conditions.append({"field": template_field, "op": "eq", "value": False})
    return conditions


def _template_field(spec: Dataset) -> str | None:
    """Where this dataset's template flag is read from, if it has one at all.

    A dataset that has no flag of its own may still be *governed* by something
    that has one — a task is a project's, which is the same answer the sharing
    gate reaches for (``Dataset.tool``). So a relation counts only when it
    reaches a dataset under that same governing tool: ``tasks`` excludes the
    work inside a template project through its ``project`` relation, while its
    relation to a member reaches a dataset governed by nothing and is not a
    place to look for one.
    """
    if _TEMPLATE_FIELD in spec.by_name:
        return _TEMPLATE_FIELD
    if spec.tool is None:
        return None
    for relation in spec.relations:
        related = dataset(relation.dataset)
        if related.tool is spec.tool and _TEMPLATE_FIELD in related.by_name:
            return f"{relation.name}.{_TEMPLATE_FIELD}"
    return None
