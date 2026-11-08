"""How a cross-guild "my tools" list orders its rows.

Which rows a My Tools list holds is each tool's own list, asked inside each
community (``me_tools``). What is left here is the one thing a merge across
communities needs of its own: a sort key every community orders by alike, so
their pages merge (:func:`cross_guild.page_across_guilds`). Ids are unique per
schema, so no single statement spans guilds.
"""

from typing import Any, Callable, Optional

from sqlalchemy import ColumnElement, func


def name_key(model: Any) -> ColumnElement[Any]:
    """A row's name as it sorts: lower-cased and compared bytewise, so every
    guild orders names alike and their merge agrees with each guild's order."""
    return func.lower(model.name).collate("C")


def sort_key(
    model: Any,
    sort_by: Optional[str],
    sort_dir: Optional[str],
    *,
    default: Callable[[Any], ColumnElement[Any]],
    default_desc: bool = True,
) -> tuple[ColumnElement[Any], bool]:
    """The expression a cross-guild list orders by, and whether descending.

    ``sort_by`` is ``name``, ``updated_at`` or ``created_at``; anything else
    leaves the tool's own default order, which each caller states. Not the
    initiative: a cross-guild list merges each guild's rows by a key the tool's
    own row carries, and an initiative's name is not one. The row id is the
    descending tiebreak either way (:func:`cross_guild.page_across_guilds`).
    """
    descending = sort_dir == "desc"
    if sort_by == "name":
        return name_key(model), descending
    if sort_by in ("updated_at", "created_at"):
        return getattr(model, sort_by), descending
    return default(model), default_desc
