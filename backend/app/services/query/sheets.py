"""Reading the cells a statement's ``sheet()`` calls name.

A call names a spreadsheet by id or by name. It is looked up in the statement's
own transaction, under its own role and narrowing, so the file is found or not
exactly as the statement's other rows are: a file the reader cannot read is
not found, the same as one that does not exist. Archived and deleted files are
not found either.

The cells are read by the grid's own code in the editor's server build
(:func:`app.services.editor_engine.sheet_range`): the range, the formulas and
the header, as the grid shows them.

A range read is kept for :data:`_KEEP_SECONDS`, keyed on the file's last
save, so a dashboard read by many people opens the workbook once per save. The
key is asked only after the lookup has found the file for this statement. A
range the reader refused is not kept.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Iterable
from typing import Any

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.file_types import FileType
from app.core.messages import QueryMessages
from app.models.tenant.file import File
from app.services import editor_engine
from app.services.query.resolve import QueryError, Sheet, SheetCall

#: How long a read range is kept. Short, so a ``TODAY()`` in one moves on.
_KEEP_SECONDS = 60
#: How many cells the kept ranges hold between them, and how many ranges.
_KEEP_CELLS = 1_000_000
_KEEP_RANGES = 256

#: Kept ranges, oldest first: when each was read, the answer, and its cells.
_kept: OrderedDict[tuple[Any, ...], tuple[float, dict[str, Any], int]] = OrderedDict()

#: What each refusal the range reader gives is, as a statement's refusal.
_REFUSALS = {
    "unknown_sheet": QueryMessages.SHEET_UNKNOWN,
    "invalid_range": QueryMessages.SHEET_RANGE_INVALID,
    "too_large": QueryMessages.SHEET_RANGE_TOO_LARGE,
}


async def read(
    session: AsyncSession, calls: Iterable[SheetCall], guild_id: int
) -> dict[SheetCall, Sheet]:
    """What each call reads, from *session*'s routed transaction.

    Raises :class:`QueryError` naming what the call got wrong.
    """
    read_sheets: dict[SheetCall, Sheet] = {}
    for call in dict.fromkeys(calls):
        query = select(File.id, File.file_type, File.updated_at).where(
            File.archived_at.is_(None), File.deleted_at.is_(None)
        )
        if isinstance(call.file, int):
            query = query.where(File.id == call.file)
        else:
            query = query.where(
                File.name == call.file, File.file_type == FileType.sheet
            )
        found = (await session.exec(query.limit(2))).all()
        if not found:
            raise QueryError(QueryMessages.SHEET_NOT_FOUND, str(call.file))
        if len(found) > 1:
            raise QueryError(QueryMessages.SHEET_NAME_AMBIGUOUS, str(call.file))
        file_id, file_type, saved = found[0]
        if file_type != FileType.sheet:
            raise QueryError(QueryMessages.SHEET_NOT_A_SPREADSHEET, str(call.file))

        key = (guild_id, file_id, saved, call.range)
        kept = _kept.get(key)
        if kept is not None and time.monotonic() - kept[0] <= _KEEP_SECONDS:
            answer = kept[1]
        else:
            content = (
                await session.exec(select(File.content).where(File.id == file_id))
            ).one()
            try:
                answer = await editor_engine.sheet_range(content, call.range)
            except editor_engine.EditorError as failed:
                raise QueryError(QueryMessages.SHEET_UNREADABLE) from failed
            now = time.monotonic()
            for stale in [
                k for k, held in _kept.items() if now - held[0] > _KEEP_SECONDS
            ]:
                del _kept[stale]
            _kept.pop(key, None)
            if not answer.get("refused"):
                _kept[key] = (
                    now,
                    answer,
                    max(1, len(answer.get("rows") or ()))
                    * max(1, len(answer.get("columns") or ())),
                )
            cells = sum(entry[2] for entry in _kept.values())
            while _kept and (cells > _KEEP_CELLS or len(_kept) > _KEEP_RANGES):
                cells -= _kept.popitem(last=False)[1][2]

        refused = answer.get("refused")
        if refused:
            raise QueryError(_REFUSALS[refused], call.range or "")
        read_sheets[call] = Sheet.from_range(call, answer)
    return read_sheets
