"""What narrows a tool's export: the tool's own list filters, and the filter
its content declares.

An export of a tool is that tool's list, rendered. So its filters are not
declared here: they are read off the tool's list route (``TOOL_LISTS``), and a
filter the list gains is one the export takes. A tool whose contents have a
filter of their own (a calendar's events by date) names it on its adapter
(``ToolExportAdapter.content_filters``).

Filters are one person's instruction for one render. Nothing keeps them past
the job that carries them.
"""

from __future__ import annotations

from collections import defaultdict
from functools import cache
from itertools import product
from typing import Any

from pydantic import BaseModel, ValidationError, create_model
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import ExportMessages
from app.core.tools import Tool, tool_export_source
from app.db.session import require_guild_context
from app.models.platform.user import User
from app.services.export.engine import ExportError

#: List params whose unset value shows one side of them (live rows) rather
#: than both.
_BOTH_WHEN_UNSET = ("archived",)


@cache
def filter_model(tool: Tool) -> type[BaseModel]:
    """The filters one tool's export takes: its list's own, and its
    content's."""
    from app.api.v1.tenant_endpoints.tool_lists import list_filter_model

    return create_model(
        f"{tool.value}_export_filters",
        __base__=list_filter_model(tool),
        **{name: (model | None, None) for name, model in _content(tool).items()},
    )


def _content(tool: Tool) -> dict[str, type[BaseModel]]:
    from app.services.export.adapters import ADAPTERS

    return ADAPTERS[tool_export_source(tool)].content_filters


def parse_filters(tool: Tool, raw: Any) -> BaseModel | None:
    """One tool's filters from a job's params, or ``None`` for none."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ExportError(ExportMessages.EXPORT_INVALID_PARAMS)
    try:
        return filter_model(tool).model_validate(raw)
    except ValidationError:
        raise ExportError(ExportMessages.EXPORT_INVALID_PARAMS)


async def narrow(
    session: AsyncSession,
    user: User,
    tool: Tool,
    filters: BaseModel | None,
    ids: list[int],
) -> list[int]:
    """The ids, in their order, that the tool's list answers with these
    filters.

    Each is asked about inside its own initiative, as that initiative's list
    asks: the export has already decided which rows it may carry, so the rule
    a list spanning initiatives adds about what is shared with the reader is
    not this question.

    A list shows one side of some choices when it is not asked about them:
    live rows rather than archived ones, ordinary projects rather than
    templates. An export with no choice carries both, so it takes each of the
    list's answers (``_BOTH_WHEN_UNSET``).
    """
    from app.api.v1.tenant_endpoints.tool_lists import (
        TOOL_LISTS,
        ListRequest,
        list_conditions,
    )

    listed = (
        filters.model_dump(exclude=set(_content(tool)), exclude_defaults=True)
        if filters
        else {}
    )
    if not listed or not ids:
        return ids
    spec = TOOL_LISTS[tool]
    values = {param.name: param.default.default for param in spec.params}
    values |= listed
    unset = [
        name for name in _BOTH_WHEN_UNSET if name in values and values[name] is None
    ]
    by_initiative: dict[int | None, list[int]] = defaultdict(list)
    for entity_id, initiative_id in await session.exec(
        select(spec.model.id, spec.model.initiative_id).where(spec.model.id.in_(ids))
    ):
        by_initiative[initiative_id].append(entity_id)
    kept: set[int] = set()
    for initiative_id, group in by_initiative.items():
        for sides in product((False, True), repeat=len(unset)):
            request = ListRequest(
                session,
                user,
                require_guild_context(session),
                values | {"initiative_id": initiative_id} | dict(zip(unset, sides)),
            )
            kept.update(
                await session.exec(
                    select(spec.model.id).where(
                        spec.model.id.in_(group), *await list_conditions(spec, request)
                    )
                )
            )
    return [entity_id for entity_id in ids if entity_id in kept]
