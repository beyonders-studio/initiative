"""A task's checklist: its stored shape, and the two ways it changes.

A checklist lives in ``tasks.checklist`` as an ordered JSONB array of
``{"id", "text", "done"}`` objects. Two writes reach it:

* **replace-all**, through ``PATCH /tasks/{id}`` — adding, renaming, reordering
  and deleting are one person editing a list, and they arrive together.
* **one tick**, through :func:`toggle_statement` — frequent, casual, and done by
  several people to the same task. It names a single item and rewrites only that
  item's ``done``, in one statement, so ticks of different items both land.
"""

from typing import Any, Iterable, Sequence

import json

from fastapi import HTTPException, status
from sqlalchemy import TextClause, text

from app.core.messages import ChecklistMessages
from app.schemas.tenant.task import (
    MAX_CHECKLIST_ITEMS,
    ChecklistItem,
    ChecklistItemInput,
    ChecklistProgress,
    mint_checklist_item_id,
)


def normalize(
    items: Sequence[ChecklistItemInput],
    existing: Sequence[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """The stored form of a written checklist — order as given, one id each.

    ``done`` for an item the task already holds is read from ``existing``, not
    from the payload: a whole-list write says what the lines are and what they
    say, and :func:`toggle_statement` is the only thing that ticks one. An item
    the task does not hold yet keeps the ``done`` it arrived with, which is what
    an import and a restore need.

    The list may not grow past :data:`MAX_CHECKLIST_ITEMS`, but a longer one —
    carried in by a migration or an import, which do not pass through here — can
    always be shortened.
    """
    held = {
        item["id"]: bool(item.get("done"))
        for item in (existing or [])
        if item.get("id")
    }
    stored: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        item_id = item.id or mint_checklist_item_id()
        if item_id in seen:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ChecklistMessages.DUPLICATE_ITEM_ID,
            )
        seen.add(item_id)
        item_text = item.text.strip()
        if not item_text:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ChecklistMessages.TEXT_EMPTY,
            )
        stored.append(
            {
                "id": item_id,
                "text": item_text,
                "done": held.get(item_id, item.done),
            }
        )
    if len(stored) > MAX_CHECKLIST_ITEMS and len(stored) >= len(existing or []):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ChecklistMessages.TOO_LONG,
        )
    return stored


def cloned(
    stored: Iterable[dict[str, Any]] | None, *, keep_done: bool = False
) -> list[dict[str, Any]]:
    """A copy of a checklist onto another task: the same lines, fresh ids.

    Nothing is ticked by default — a duplicated or recurring task has not done
    any of it yet. ``keep_done`` is for a project template, whose blueprint is
    copied as written.
    """
    return [
        {
            "id": mint_checklist_item_id(),
            "text": item.get("text", ""),
            "done": bool(item.get("done")) if keep_done else False,
        }
        for item in (stored or [])
        if item.get("text")
    ]


def read(stored: Iterable[dict[str, Any]] | None) -> list[ChecklistItem]:
    """The read shape of a stored checklist."""
    return [
        ChecklistItem(
            id=item["id"], text=item.get("text", ""), done=bool(item.get("done"))
        )
        for item in (stored or [])
        if item.get("id")
    ]


def progress(stored: Sequence[dict[str, Any]] | None) -> ChecklistProgress | None:
    """How much of a checklist is ticked, or ``None`` for a task without one.

    Read from the column the row already carries, so a list endpoint pays
    nothing extra for the count on every card.
    """
    if not stored:
        return None
    return ChecklistProgress(
        completed=sum(1 for item in stored if item.get("done")),
        total=len(stored),
    )


#: Rewrites one item's ``done`` in place, matching the item by id and leaving
#: the rest of the array — including its order — exactly as found. ``WHERE``
#: matches nothing when the task holds no such item, which is the 404.
_TOGGLE = text(
    """
    UPDATE tasks
       SET checklist = (
               SELECT coalesce(
                          jsonb_agg(
                              CASE WHEN elem->>'id' = :item_id
                                   THEN jsonb_set(elem, '{done}',
                                                  to_jsonb(:done ::boolean))
                                   ELSE elem
                              END
                              ORDER BY ord
                          ),
                          '[]'::jsonb
                      )
                 FROM jsonb_array_elements(checklist)
                      WITH ORDINALITY AS entry(elem, ord)
           ),
           updated_at = :now
     WHERE id = :task_id
       AND checklist @> :probe ::jsonb
    RETURNING checklist
    """
)


def toggle_statement() -> TextClause:
    """The single statement a tick runs. Bind ``task_id``, ``item_id``,
    ``done`` and ``now``; :func:`toggle_params` builds the rest."""
    return _TOGGLE


def toggle_params(*, task_id: int, item_id: str, done: bool, now: Any) -> dict:
    return {
        "task_id": task_id,
        "item_id": item_id,
        "done": done,
        "now": now,
        "probe": json.dumps([{"id": item_id}]),
    }


#: Takes one item out, matching it by id and leaving the rest of the array in
#: its order. ``WHERE`` matches nothing unless the task still holds the item as
#: :func:`remove_params` was given it, so a line ticked or reworded meanwhile is
#: kept as it is.
_REMOVE = text(
    """
    UPDATE tasks
       SET checklist = (
               SELECT coalesce(
                          jsonb_agg(elem ORDER BY ord)
                              FILTER (WHERE elem->>'id' <> :item_id),
                          '[]'::jsonb
                      )
                 FROM jsonb_array_elements(checklist)
                      WITH ORDINALITY AS entry(elem, ord)
           ),
           updated_at = :now
     WHERE id = :task_id
       AND checklist @> :probe ::jsonb
    RETURNING checklist
    """
)


def remove_statement() -> TextClause:
    """The single statement that takes one item out. :func:`remove_params`
    binds it."""
    return _REMOVE


def remove_params(*, task_id: int, item: dict[str, Any], now: Any) -> dict:
    """Bind :func:`remove_statement` to take ``item`` out of the task's list,
    only while the item still reads as it does here."""
    held = {
        "id": item["id"],
        "text": item.get("text", ""),
        "done": bool(item.get("done")),
    }
    return {
        "task_id": task_id,
        "item_id": held["id"],
        "now": now,
        "probe": json.dumps([held]),
    }
