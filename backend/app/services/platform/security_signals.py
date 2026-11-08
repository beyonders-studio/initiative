"""Counting what the security rules watch, and opening a case when one trips.

Every audit line passes :func:`observe` on its way out (``app.services.audit``),
and every counted rejection passes :func:`signal`. Each is one dict lookup —
most find no rule — and, for a match, an increment of a bucket held in this
process. Nothing is written per event, so an attack costs no writes.

Every :data:`FLUSH_INTERVAL`, :func:`flush` adds each rule's buckets into
``security_signal_windows`` in one statement, which returns the deployment's
totals across every instance. A window whose total has just reached its rule's
threshold is stamped — by exactly one instance — and that instance writes one
``security.threshold_crossed`` line and opens (or adds to) the rule's security
case for that key. A crash loses at most one interval of counts; the audit log
stays the record of the events themselves.

Keys never leave memory as they were: the table holds an HMAC of each, and the
threshold line, which is the audit record, names what was counted.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import audit_context
from app.core.audit_events import AuditEventType
from app.core.config import settings
from app.core.security_rules import (
    BY_NAME,
    BY_WATCHED,
    COLLAPSED_KEY,
    LONGEST_WINDOW,
    MAX_KEYS_PER_RULE,
    Envelope,
    SecurityRule,
    Signal,
    signal_envelope,
)

logger = logging.getLogger(__name__)

#: How often each instance adds what it counted to the shared table.
FLUSH_INTERVAL = timedelta(seconds=10)


@dataclass
class _Bucket:
    """One key's count in one window, in this process, since the last flush."""

    #: What was counted by, as it was; kept only until the flush.
    raw_key: str
    count: int = 0
    #: The newest counted line's facts, for the case should this trip.
    event_uuid: str | None = None
    subject_user: int | None = None
    subject_guild: int | None = None


@dataclass
class _Counts:
    #: rule name -> (hashed key, window start) -> bucket
    rules: dict[str, dict[tuple[str, datetime], _Bucket]] = field(default_factory=dict)


_lock = threading.Lock()
_counts = _Counts()


def hashed(rule: str, raw_key: str) -> str:
    """What a key is kept as outside memory: an HMAC under the deployment's
    secret, so the table can't be read back into addresses or accounts."""
    if raw_key == COLLAPSED_KEY:
        return COLLAPSED_KEY
    return hmac.new(
        settings.SECRET_KEY.encode(), f"{rule}:{raw_key}".encode(), hashlib.sha256
    ).hexdigest()


def window_start(at: datetime, window: timedelta) -> datetime:
    """The start of the fixed window ``at`` falls in."""
    seconds = window.total_seconds()
    stamp = at.timestamp()
    return datetime.fromtimestamp(stamp - stamp % seconds, tz=UTC)


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) else None


def observe(envelope: Envelope, *, now: datetime | None = None) -> None:
    """Count ``envelope`` for every rule that watches it. Never raises: a
    rule that can't count must not lose the line it was shown."""
    rules = BY_WATCHED.get(str(envelope.get("event_type")))
    if not rules:
        return
    try:
        moment = now or datetime.now(UTC)
        for rule in rules:
            if rule.when is not None and not rule.when(envelope):
                continue
            raw = rule.key(envelope)
            if raw is None:
                continue
            _count(rule, raw, envelope, moment)
    except Exception:  # pragma: no cover - a rule's own bug, logged
        logger.exception("security rules: could not count an event")


def _count(rule: SecurityRule, raw: str, envelope: Envelope, moment: datetime) -> None:
    start = window_start(moment, rule.window)
    with _lock:
        buckets = _counts.rules.setdefault(rule.name, {})
        slot = (hashed(rule.name, raw), start)
        if slot not in buckets and len(buckets) >= MAX_KEYS_PER_RULE:
            slot = (COLLAPSED_KEY, start)
            raw = COLLAPSED_KEY
        bucket = buckets.get(slot)
        if bucket is None:
            bucket = buckets[slot] = _Bucket(raw_key=raw)
        bucket.count += 1
        bucket.event_uuid = envelope.get("event_uuid") or bucket.event_uuid
        bucket.subject_user = _int(
            envelope.get("target_user_id") or envelope.get("actor_user_id")
        )
        bucket.subject_guild = _int(envelope.get("guild_id"))


def signal(kind: Signal, *, source_ip: str | None = None) -> None:
    """Count one high-volume rejection — a cross-site refusal, a 429, a
    refused captcha — against where the request came from: the request's own
    address, else ``source_ip`` where there is no request context (a refused
    socket handshake). Writes nothing."""
    observe(signal_envelope(kind, source_ip=audit_context.client_ip() or source_ip))


def _take() -> dict[str, dict[tuple[str, datetime], _Bucket]]:
    with _lock:
        taken = _counts.rules
        _counts.rules = {}
    return taken


def _give_back(taken: dict[str, dict[tuple[str, datetime], _Bucket]]) -> None:
    """Put counts a failed flush took back with what has been counted since,
    so the next flush adds them: a brief outage loses nothing, and a one-off
    event still trips its rule."""
    with _lock:
        for name, buckets in taken.items():
            pending = _counts.rules.setdefault(name, {})
            for slot, bucket in buckets.items():
                if slot not in pending and len(pending) >= MAX_KEYS_PER_RULE:
                    # The cap holds across what was taken and what came since.
                    slot = (COLLAPSED_KEY, slot[1])
                    if slot not in pending:
                        pending[slot] = _Bucket(raw_key=COLLAPSED_KEY)
                since = pending.get(slot)
                if since is None:
                    pending[slot] = bucket
                    continue
                since.count += bucket.count
                since.event_uuid = since.event_uuid or bucket.event_uuid
                since.subject_user = since.subject_user or bucket.subject_user
                since.subject_guild = since.subject_guild or bucket.subject_guild


def pending() -> int:
    """How many buckets wait for the next flush. For tests and metrics."""
    with _lock:
        return sum(len(buckets) for buckets in _counts.rules.values())


def discard() -> None:
    """Drop everything counted and not yet flushed, and every case waiting to
    be opened. For tests."""
    _take()
    _unopened.clear()


# -- Flushing -------------------------------------------------------------------


_UPSERT = text(
    """
    INSERT INTO security_signal_windows (rule, key, window_start, count)
    SELECT :rule, t.key, t.window_start, t.count
      FROM unnest(CAST(:keys AS text[]), CAST(:starts AS timestamptz[]),
                  CAST(:counts AS integer[])) AS t(key, window_start, count)
    ON CONFLICT (rule, key, window_start)
      DO UPDATE SET count = security_signal_windows.count + EXCLUDED.count
    RETURNING key, window_start, count, crossed_at
    """
)

_STAMP = text(
    """
    UPDATE security_signal_windows
       SET crossed_at = now()
     WHERE rule = :rule AND key = :key AND window_start = :start
       AND crossed_at IS NULL
    RETURNING count
    """
)


@dataclass
class Crossing:
    """A window that reached its rule's threshold in this flush."""

    rule: SecurityRule
    key: str
    raw_key: str
    window_start: datetime
    count: int
    bucket: _Bucket
    #: The ``security.threshold_crossed`` line, once written.
    line: dict[str, Any] | None = None


#: Crossings stamped whose case could not be opened yet: retried on every
#: flush until it opens. The stamp means no other instance will try.
_unopened: list[Crossing] = []


async def flush() -> list[Crossing]:
    """Add every counted bucket to the shared table, and open a case for each
    window this flush took over its rule's threshold. Returns those."""
    from app.db import cohorts

    taken = _take()
    crossings: list[Crossing] = []
    if taken:
        try:
            async with cohorts.system_session(None) as session:
                for name, buckets in taken.items():
                    crossings.extend(await _flush_rule(session, BY_NAME[name], buckets))
                await session.commit()
        except Exception:
            logger.exception("security rules: could not add this interval's counts")
            _give_back(taken)
            crossings = []
    # Cases a failed attempt left unopened go first, then this flush's. One
    # whose window has long passed is given up on: the audit line stands.
    now = datetime.now(UTC)
    waiting = [
        crossing
        for crossing in _unopened
        if now < crossing.window_start + 2 * crossing.rule.window
    ] + crossings
    _unopened.clear()
    for crossing in waiting:
        if not await _open(crossing):
            _unopened.append(crossing)
    return crossings


async def _flush_rule(
    session: AsyncSession,
    rule: SecurityRule,
    buckets: dict[tuple[str, datetime], _Bucket],
) -> list[Crossing]:
    slots = list(buckets)
    rows = (
        await session.exec(
            _UPSERT,
            params={
                "rule": rule.name,
                "keys": [key for key, _ in slots],
                "starts": [start for _, start in slots],
                "counts": [buckets[slot].count for slot in slots],
            },
        )
    ).all()
    crossings: list[Crossing] = []
    for key, start, total, crossed_at in rows:
        if crossed_at is not None or total < rule.threshold:
            continue
        stamped = (
            await session.exec(
                _STAMP, params={"rule": rule.name, "key": key, "start": start}
            )
        ).first()
        if stamped is None:
            # Another instance's flush took it over first.
            continue
        bucket = buckets[(key, start)]
        crossings.append(
            Crossing(
                rule=rule,
                key=key,
                raw_key=bucket.raw_key,
                window_start=start,
                count=int(stamped[0]),
                bucket=bucket,
            )
        )
    return crossings


async def _open(crossing: Crossing) -> bool:
    """Write the one line a crossing gets, and open or add to its case.
    Returns whether the case is done with: ``False`` to try again."""
    from app.core.intake import IntakeStream
    from app.services.platform.intake import CaseRefs, open_case

    rule = crossing.rule
    if crossing.line is None:
        crossing.line = _write_line(crossing)
    line = crossing.line
    try:
        await open_case(
            IntakeStream.security,
            title=rule.title,
            body=(
                f"Rule `{rule.name}` ({rule.severity.value}): {crossing.count} in "
                f"{_span(rule.window)}, against a threshold of {rule.threshold}.\n\n"
                f"The audit line `{line['event_uuid']}` "
                "(`security.threshold_crossed`) names what was counted."
            ),
            refs=CaseRefs(
                subject_user=crossing.bucket.subject_user,
                subject_guild=crossing.bucket.subject_guild,
                source_event=line["event_uuid"],
                reported_at=crossing.window_start,
                severity=rule.severity.value,
            ),
            dedupe_key=f"rule:{rule.name}:{crossing.key}",
            window=rule.window,
        )
    except Exception:
        logger.exception("security rules: could not open the case for %s", rule.name)
        return False
    return True


def _write_line(crossing: Crossing) -> dict[str, Any]:
    """The one audit line a crossing gets, whatever becomes of its case."""
    from app.services import audit as audit_service

    rule = crossing.rule
    return audit_service.emit(
        event_type=AuditEventType.SECURITY_THRESHOLD_CROSSED,
        actor_user_id=None,
        target_user_id=crossing.bucket.subject_user,
        guild_id=crossing.bucket.subject_guild,
        detail={
            "rule": rule.name,
            "severity": rule.severity.value,
            # The audit log is the record: what was counted, by name.
            "key": crossing.raw_key,
            "count": crossing.count,
            "threshold": rule.threshold,
            "window_start": crossing.window_start.isoformat(),
            "window_seconds": int(rule.window.total_seconds()),
            "last_event": crossing.bucket.event_uuid,
        },
    )


def _span(window: timedelta) -> str:
    minutes = int(window.total_seconds() // 60)
    if minutes % (24 * 60) == 0:
        days = minutes // (24 * 60)
        return f"{days} day" + ("s" if days != 1 else "")
    if minutes % 60 == 0:
        hours = minutes // 60
        return f"{hours} hour" + ("s" if hours != 1 else "")
    return f"{minutes} minutes"


async def forget_old(session: AsyncSession, *, now: datetime | None = None) -> int:
    """Drop windows no rule can still read. ``session`` is the system
    engine's, unrouted. Returns how many went."""
    moment = now or datetime.now(UTC)
    result = await session.exec(
        text("DELETE FROM security_signal_windows WHERE window_start < :before"),
        params={"before": moment - 2 * LONGEST_WINDOW},
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def process_flush() -> None:
    """The background pass: add this interval's counts."""
    await flush()


async def sweep() -> None:
    """The hourly pass: drop windows no rule can still read."""
    from app.db import cohorts

    async with cohorts.system_session(None) as session:
        await forget_old(session)
        await session.commit()
