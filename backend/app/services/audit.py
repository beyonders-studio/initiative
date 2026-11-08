"""Writing down what was done.

One function. A call site is a single line, and adding a newly-audited action
is that line plus an ``AuditEventType`` member, which carries its own metadata —
there is no second place to register anything.

The record is one JSON line on the ``audit`` logger, written after the
transaction that performed the action commits, so the line and the action
land together or not at all. It is written nowhere else: the platform that
ships this process's logs is where the record is kept, queried, retained and
alerted on. A record staged inside a savepoint goes with the savepoint.
:func:`emit` is the other half: one line for something that has already
happened and has no transaction to ride.

Every line carries the ``context`` of the request it came from — the id that
request is known by, and what let the caller in. See ``app.core.audit_context``.

Identity is never in the line — ids only.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from enum import Enum
from functools import partial
from typing import Any
from uuid import uuid4

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import audit_context
from app.core.audit_events import (
    SCHEMA_VERSION,
    SERVICE,
    AuditCategory,
    AuditEventType,
)
from app.db import post_commit
from app.services.platform import security_signals

audit_logger = logging.getLogger("audit")


def _identifies_the_caller(event_type: AuditEventType) -> bool:
    """Whether this event's line carries where the request came from.

    Two families need it: getting in, and reaching past the communities you
    belong to. For a sign-in, the address is most of what tells one from
    another; for privileged access, it is part of what the access is reviewed
    against. Somebody making a file in their own community is not either
    of those, and their line carries the request id alone.
    """
    return event_type.category is AuditCategory.AUTHENTICATION or event_type.tier == 1


def _write(envelope: dict[str, Any]) -> None:
    """Put one envelope on the stream.

    Best-effort: a logging handler that throws must not take down a
    transaction that has already committed, nor a request that has already
    been served.
    """
    try:
        audit_logger.info(json.dumps(envelope, separators=(",", ":")))
    except Exception:  # pragma: no cover - a broken handler, not our logic
        logging.getLogger(__name__).exception("audit log line could not be emitted")
    # Every line passes the security rules on its way out: one lookup, and a
    # count in memory for the few they watch (app.core.security_rules).
    security_signals.observe(envelope)


async def record(
    session: AsyncSession,
    *,
    event_type: AuditEventType,
    actor_user_id: int | None,
    target_user_id: int | None = None,
    guild_id: int | None = None,
    target_type: str | None = None,
    target_id: int | None = None,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Stage one action's record for ``session``'s commit, and return it.

    ``actor_user_id`` is ``None`` for an action nobody signed in took: a
    refused sign-in, a system sweep. ``guild_id`` names the community the
    action happened in or to, where there is one. Staged, not emitted: the
    caller owns the transaction, which is what makes the record and the thing
    it records land together.
    """
    envelope = _envelope(
        event_type=event_type,
        actor_user_id=actor_user_id,
        target_user_id=target_user_id,
        guild_id=guild_id,
        target_type=target_type,
        target_id=target_id,
        detail=detail,
    )
    post_commit.after_commit(session, partial(_write, envelope))
    return envelope


def emit(
    *,
    event_type: AuditEventType,
    actor_user_id: int | None,
    target_user_id: int | None = None,
    guild_id: int | None = None,
    target_type: str | None = None,
    target_id: int | None = None,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write one line now, and return it.

    For something already done by the time it is recorded — a request that has
    been served — where there is no transaction for the line to ride and
    nothing left to undo.
    """
    envelope = _envelope(
        event_type=event_type,
        actor_user_id=actor_user_id,
        target_user_id=target_user_id,
        guild_id=guild_id,
        target_type=target_type,
        target_id=target_id,
        detail=detail,
    )
    _write(envelope)
    return envelope


def _envelope(
    *,
    event_type: AuditEventType,
    actor_user_id: int | None,
    target_user_id: int | None,
    guild_id: int | None,
    target_type: str | None,
    target_id: int | None,
    detail: dict[str, Any] | None,
) -> dict[str, Any]:
    """The line, as both halves write it.

    The request context is read here rather than when the line goes out, so a
    record staged now and committed later says where it came from.
    """
    return {
        # The key a collector routes on: this line is the audit stream, and
        # the application's own logs are not.
        "stream": "audit",
        # And which service's: billing and auto write the same shape.
        "service": SERVICE,
        "schema_version": SCHEMA_VERSION,
        "event_uuid": str(uuid4()),
        "event_type": event_type.value,
        "occurred_at": datetime.now(UTC).isoformat(),
        "actor_user_id": actor_user_id,
        "target_user_id": target_user_id,
        "guild_id": guild_id,
        "target": (
            {"type": target_type, "id": target_id} if target_type is not None else None
        ),
        "tier": event_type.tier,
        "category": event_type.category.value,
        "is_write": event_type.is_write,
        "context": audit_context.envelope_context(
            caller=_identifies_the_caller(event_type)
        ),
        "detail": detail or {},
    }


_OMITTED = object()


def _recordable(value: Any) -> Any:
    """``value`` as it may appear in a record, or ``_OMITTED``.

    Booleans, numbers, ``None`` and enumeration members are copied. A string
    is not: a string field can hold a secret, an address, a name, a URL, and
    the record names the field instead. A list or set is copied only when
    every element is.
    """
    if isinstance(value, Enum):
        return value.value
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, (list, tuple, set, frozenset)):
        items = [_recordable(item) for item in value]
        if any(item is _OMITTED for item in items):
            return _OMITTED
        return sorted(items, key=repr) if isinstance(value, (set, frozenset)) else items
    return _OMITTED


def changed_fields(
    before: Mapping[str, Any], after: Mapping[str, Any]
) -> dict[str, Any]:
    """What a write changed, in the form a configuration record carries.

    ``{"changed": [field, ...], "values": {field: {"from": .., "to": ..}}}``.
    Every field whose value differs is named; a before/after pair is copied
    in only where both sides are recordable (see ``_recordable``), so a
    rotated secret or a retyped address is recorded as the fact that the
    field moved and nothing more. Fields present on one side only count as
    changed from or to ``None``.
    """
    names = sorted(set(before) | set(after))
    changed: list[str] = []
    values: dict[str, dict[str, Any]] = {}
    for name in names:
        old, new = before.get(name), after.get(name)
        if old == new:
            continue
        changed.append(name)
        old_r, new_r = _recordable(old), _recordable(new)
        if old_r is not _OMITTED and new_r is not _OMITTED:
            values[name] = {"from": old_r, "to": new_r}
    return {"changed": changed, "values": values}


def snapshot(obj: Any, names: Iterable[str]) -> dict[str, Any]:
    """The named attributes of ``obj``, for a before/after ``changed_fields``."""
    return {name: getattr(obj, name) for name in names}


async def record_settings_change(
    session: AsyncSession,
    *,
    guild_id: int | None,
    actor_user_id: int | None,
    area: str,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    extras: Mapping[str, Any] | None = None,
) -> None:
    """Stage the record for one area of a guild's settings, when it moved.

    ``guild_id`` ``None`` is the deployment's own settings row. ``extras`` ride
    along in the detail beside what ``changed_fields`` reports.
    """
    changes = changed_fields(before, after)
    if not changes["changed"]:
        return
    platform = guild_id is None
    await record(
        session,
        event_type=(
            AuditEventType.PLATFORM_SETTINGS_CHANGED
            if platform
            else AuditEventType.GUILD_SETTINGS_CHANGED
        ),
        actor_user_id=actor_user_id,
        guild_id=guild_id,
        target_type=None if platform else "guild",
        target_id=guild_id,
        detail={"area": area, **changes, **(extras or {})},
    )
