"""Work that runs once a transaction commits, and the tasks this process
starts on its own.

:func:`after_commit` registers a step on a session. The step runs when the
session's outermost transaction commits, and not at all when that transaction,
or the savepoint the step was registered in, rolls back; a savepoint that is
released keeps its steps for the outer commit. :func:`spawn` starts a task that
belongs to no transaction.

Every task either one starts is held here until it finishes, as the event loop
keeps only a weak reference to it. :func:`settle` waits for the steps a
session's commits started, and :func:`settle_all` for every task, as before
the pools close; a task spawned with ``cancel_on_settle`` is cancelled there
instead of waited for.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable, Hashable
from typing import Any, cast

from sqlalchemy import event
from sqlalchemy.orm import Session as SyncSession
from sqlalchemy.orm import SessionTransaction

logger = logging.getLogger(__name__)

#: A zero-arg callable. One that returns an awaitable runs as a task of its
#: own; one that does not runs inside the commit, and must not use the session.
Step = Callable[[], object]


#: Where a session keeps the steps waiting for its commit, keyed by the
#: transaction each was registered in and its key, and its commits'
#: unfinished steps.
_STEPS_KEY = "post_commit_steps"
_STARTED_KEY = "post_commit_started"

#: Every task started here, until it finishes.
_running: set[asyncio.Task[None]] = set()
#: The tasks :func:`settle_all` cancels rather than waits for.
_cancel_on_settle: set[asyncio.Task[None]] = set()


def after_commit[StepT: Step](
    session: Any, step: StepT, key: Hashable | None = None
) -> StepT:
    """Run ``step`` once ``session``'s transaction commits, and not at all if
    the transaction, or the savepoint the step was registered in, rolls back.
    A failure is logged with the step's name.

    With ``key``, one step per key per savepoint or transaction: the step
    already registered under ``key`` in the innermost one open is kept and
    returned, so a caller can add to it. A released savepoint's steps join the
    transaction around it, where one already under the same key is kept — and,
    where it has a ``join`` method, is handed the savepoint's to take what it
    adds. Returns the step that will run.

    ``session`` is an ``AsyncSession`` or a sync ``Session``. A session with no
    transaction open begins one here, so a rollback before its first statement
    still discards the step.
    """
    sync: SyncSession = getattr(session, "sync_session", session)
    txn = sync.get_nested_transaction() or sync.get_transaction() or sync.begin()
    steps: dict[tuple[SessionTransaction, Hashable], Step] = sync.info.setdefault(
        _STEPS_KEY, {}
    )
    return cast(StepT, steps.setdefault((txn, object() if key is None else key), step))


def spawn(work: Awaitable[object], *, cancel_on_settle: bool = False) -> None:
    """Run ``work`` as a task of its own, held until it finishes. A failure is
    logged. Outside an event loop it is closed unrun.

    With ``cancel_on_settle``, :func:`settle_all` cancels it rather than
    waiting for it: for long work that a later run can carry on from.
    """
    _hold(work, _name(work), *((_cancel_on_settle,) if cancel_on_settle else ()))


async def settle(session: Any) -> None:
    """Wait for the steps ``session``'s commits have started."""
    started: set[asyncio.Task[None]] = session.info.get(_STARTED_KEY, set())
    if started:
        await asyncio.gather(*started)


async def settle_all() -> None:
    """Wait for every task this process has started here, as before its pools
    close, cancelling those spawned with ``cancel_on_settle`` first. Those get
    one turn of the loop before the cancel, so work not yet started reaches its
    own handler."""
    if _cancel_on_settle:
        await asyncio.sleep(0)
    for task in _cancel_on_settle:
        task.cancel()
    if _running:
        await asyncio.gather(*_running, return_exceptions=True)


def _name(work: object) -> str:
    work = getattr(work, "func", work)
    return getattr(work, "__qualname__", None) or type(work).__qualname__


async def _logged(work: Awaitable[object], name: str) -> None:
    try:
        await work
    except Exception:
        logger.exception("background work %s failed", name)


def _hold(work: Awaitable[object], name: str, *also: set[asyncio.Task[None]]) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # A sync script: there is no loop to run it on.
        if inspect.iscoroutine(work):
            work.close()
        return
    task = loop.create_task(_logged(work, name))
    if inspect.iscoroutine(work):
        # Closes ``work`` when the task is cancelled before it starts.
        close = work.close
        task.add_done_callback(lambda _: close())
    for held in (_running, *also):
        held.add(task)
        task.add_done_callback(held.discard)


def _start_steps(session: SyncSession) -> None:
    # A savepoint's release is also a commit; the steps wait for the outer one.
    released = session.get_nested_transaction()
    if released is not None:
        _fold_steps(session, released)
        return
    steps: dict[Any, Step] | None = session.info.pop(_STEPS_KEY, None)
    if not steps:
        return
    started = session.info.setdefault(_STARTED_KEY, set())
    for step in steps.values():
        name = _name(step)
        try:
            work = step()
        except Exception:
            logger.exception("background work %s failed", name)
            continue
        if inspect.isawaitable(work):
            _hold(work, name, started)


def _fold_steps(session: SyncSession, released: SessionTransaction) -> None:
    steps: dict[tuple[SessionTransaction, Hashable], Step] | None = session.info.get(
        _STEPS_KEY
    )
    if not steps or released.parent is None:
        return
    folded: dict[tuple[SessionTransaction, Hashable], Step] = {}
    for (txn, key), step in steps.items():
        held = folded.setdefault(
            (released.parent if txn is released else txn, key), step
        )
        join = getattr(held, "join", None) if held is not step else None
        if join is not None:
            join(step)
    session.info[_STEPS_KEY] = folded


def _within(txn: SessionTransaction | None, ended: SessionTransaction) -> bool:
    while txn is not None:
        if txn is ended:
            return True
        txn = txn.parent
    return False


def _drop_steps(session: SyncSession, previous_transaction: SessionTransaction) -> None:
    steps: dict[tuple[SessionTransaction, Hashable], Step] | None = session.info.get(
        _STEPS_KEY
    )
    # What the database rolled back: the nearest savepoint, or the whole
    # transaction, which ``_forget_steps`` sees end.
    ended = previous_transaction
    while not ended.nested and ended.parent is not None:
        ended = ended.parent
    if steps and ended.nested:
        session.info[_STEPS_KEY] = {
            registered: step
            for registered, step in steps.items()
            if not _within(registered[0], ended)
        }


def _forget_steps(session: SyncSession, transaction: SessionTransaction) -> None:
    if transaction.parent is None:
        session.info.pop(_STEPS_KEY, None)


event.listen(SyncSession, "after_commit", _start_steps)
event.listen(SyncSession, "after_soft_rollback", _drop_steps)
event.listen(SyncSession, "after_transaction_end", _forget_steps)
