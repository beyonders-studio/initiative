"""JSONata, as Initiative evaluates a declarative plug-in's expressions.

Standard JSONata (``jsonata-python``, a port of the reference implementation),
with no functions added, answering what the SDK's ``evaluate`` answers: the
same three bounds from the same contract, ``expressionTimeMs``,
``expressionDepth`` and ``expressionOutputBytes``, and ``$now()`` and
``$millis()`` fixed to the time of the call. Passing a bound is a failure, as
an expression that raises an error is (:class:`ExpressionError`).

**Where it runs.** The library checks the time and depth bounds between
evaluation steps, as the reference implementation does. One step can still run
long on its own (a regular expression, a large ``$pad``), so evaluations run in
worker processes (:mod:`app.services.worker_pool`), and one still busy after
the time bound and a grace period is stopped and replaced. The pool starts on
the first evaluation, holds at most ``EXPRESSION_WORKERS`` per process, and a
worker idle for ``_IDLE_SECONDS`` exits. Parsing, which publishing a manifest
needs, runs here.

An answer comes back as plain JSON, or :data:`UNDEFINED` when the expression
answers nothing.
"""

from __future__ import annotations

import asyncio
import atexit
import threading
from pathlib import Path
from typing import Any, final

import jsonata
from jsonata.parser import Parser

from app.core.config import settings
from app.services.marketplace import contract
from app.services.worker_pool import Pool, PoolError

__all__ = [
    "DEPTH",
    "OUTPUT_BYTES",
    "TIME_MS",
    "UNDEFINED",
    "ExpressionError",
    "evaluate",
    "holds",
    "parse",
    "shutdown",
    "step_reads",
]

TIME_MS = contract.cap("expressionTimeMs")
DEPTH = contract.cap("expressionDepth")
OUTPUT_BYTES = contract.cap("expressionOutputBytes")

_HANDLER = Path(__file__).parent.parent / "jsonata_worker.py"
#: How long a worker waits for its next evaluation before it exits.
_IDLE_SECONDS = 300
#: A worker's address space. Measured: about 42 MB at rest and about 60 MB
#: evaluating a 4.5 MB document. What a document can grow to is set by an
#: endpoint's steps and pages at the vendor response cap, not by the answer's
#: cap, so the limit is a fixed size well above that.
_ADDRESS_SPACE_BYTES = 256 * 1024 * 1024


@final
class _Undefined:
    """JSONata's ``undefined``: no answer, which is not ``null``."""

    _instance: _Undefined | None = None

    def __new__(cls) -> _Undefined:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "UNDEFINED"


UNDEFINED: Any = _Undefined()


class ExpressionError(Exception):
    """An expression that does not parse, failed, or passed one of its bounds.

    ``transient`` is a failure the same expression may not meet again: it ran
    out of time or memory, or no evaluator answered.
    """

    def __init__(
        self, message: str, position: int | None = None, *, transient: bool = False
    ) -> None:
        super().__init__(message)
        self.position = position
        self.transient = transient


def _failure(error: BaseException) -> ExpressionError:
    if isinstance(error, jsonata.JException):
        return ExpressionError(str(error), error.location)
    if isinstance(error, RecursionError):
        return ExpressionError("Stack overflow")
    return ExpressionError(str(error) or type(error).__name__)


def parse(text: str) -> Any:
    """An expression's syntax tree. Raises :class:`ExpressionError` when
    ``text`` is not a JSONata expression."""
    try:
        return jsonata.Jsonata(text).ast
    except Exception as error:
        raise _failure(error) from error


def step_reads(tree: Any) -> set[str]:
    """The step names a syntax tree reads at its root, as ``steps.<name>`` or
    ``$$.steps.<name>``."""
    names: set[str] = set()
    seen: set[int] = set()

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for child in node:
                walk(child)
            return
        if not isinstance(node, Parser.Symbol) or id(node) in seen:
            return
        seen.add(id(node))
        steps = getattr(node, "steps", None) if node.type == "path" else None
        if isinstance(steps, list) and steps:
            first = steps[0]
            start = 1 if (first.type, first.value) == ("variable", "$") else 0
            if (
                len(steps) > start + 1
                and (steps[start].type, steps[start].value) == ("name", "steps")
                and steps[start + 1].type == "name"
            ):
                names.add(str(steps[start + 1].value))
        for key, child in vars(node).items():
            if key != "_outer_instance":
                walk(child)

    walk(tree)
    return names


# --- evaluating, in the pool ------------------------------------------------

_pool: Pool | None = None
_pool_lock = threading.Lock()


def _the_pool() -> Pool:
    global _pool
    with _pool_lock:
        if _pool is None:
            # The app's lifespan stops it; a process that has none stops it
            # on its way out.
            atexit.register(shutdown)
            _pool = Pool(
                handler=_HANDLER,
                arguments=[
                    str(TIME_MS),
                    str(DEPTH),
                    str(OUTPUT_BYTES),
                    str(_ADDRESS_SPACE_BYTES),
                ],
                size=settings.EXPRESSION_WORKERS,
                time_ms=TIME_MS,
                idle_seconds=_IDLE_SECONDS,
            )
        return _pool


def shutdown() -> None:
    """Stop the pool's workers; the next evaluation starts a new pool."""
    global _pool
    with _pool_lock:
        pool, _pool = _pool, None
    if pool is not None:
        pool.shutdown()


async def _evaluate(
    text: str, document: Any, millis: int | None, predicate: bool
) -> dict[str, Any]:
    request: dict[str, Any] = {"expression": text, "predicate": predicate}
    if document is not UNDEFINED:
        request["document"] = document
    if millis is not None:
        request["millis"] = millis
    try:
        reply = await asyncio.to_thread(_the_pool().ask, request)
    except PoolError as exc:
        raise ExpressionError(str(exc), transient=True) from exc
    if "error" in reply:
        raise ExpressionError(
            reply["error"],
            reply.get("position"),
            transient=bool(reply.get("transient")),
        )
    return reply


async def evaluate(text: str, document: Any, *, millis: int | None = None) -> Any:
    """Evaluate one expression over ``document``, within the contract's bounds.

    ``millis`` fixes what ``$now()`` and ``$millis()`` answer; absent, they
    answer the moment of evaluation. ``document`` must be JSON, with
    :data:`UNDEFINED` for no input at all.
    """
    reply = await _evaluate(text, document, millis, False)
    return UNDEFINED if reply.get("undefined") else reply["value"]


async def holds(text: str, document: Any, *, millis: int | None = None) -> bool:
    """Whether a predicate holds: JSONata's ``$boolean`` of its answer is true."""
    reply = await _evaluate(text, document, millis, True)
    return reply.get("value") is True
