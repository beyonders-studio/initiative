"""JSONata evaluation in a worker process, for :mod:`worker_host`.

The host loads this module by path and calls :func:`start` with ``<time ms>
<depth> <output bytes> <address space bytes>``; this imports the standard
library and the JSONata library and nothing of Initiative.

A request is ``{"expression", "document"?, "millis"?, "predicate"?}``; the
answer is ``{"value"}``, ``{"undefined": true}`` or ``{"error", "position"}``.
Bounds are the library's own time and depth guardrails, a check on the
answer's size as JSON, and a limit on the process's address space where the
platform has one. An evaluation that runs out of memory is answered with
``"replace": true``, and the worker exits. One that ran out of time or memory
also carries ``"transient": true``: asked again, it may answer. An answer is
JSON as ``JSON.stringify`` writes it.
"""

from __future__ import annotations

import json
import math
import sys
from collections.abc import Callable
from functools import lru_cache
from typing import Any

import jsonata
from jsonata.parser import Parser
from jsonata.utils import Utils

#: The library's code for an evaluation past its time bound.
_TIMEOUT = "D1012"

#: No answer: JSONata's ``undefined``, which is not ``null``.
_UNDEFINED = object()


def _is_function(value: Any) -> bool:
    return isinstance(value, (jsonata.Jsonata.JFunctionCallable, Parser.Symbol))


def _number(value: float) -> Any:
    """A number as a double holds it and ``JSON.stringify`` writes it: integral
    below 1e21 as an integer, otherwise as a float."""
    as_float = float(value)
    if not math.isfinite(as_float):
        return None
    if as_float.is_integer() and abs(as_float) < 1e21:
        return int(as_float)
    return as_float


def plain(value: Any, *, top: bool = False) -> Any:
    """An answer as JSON reads it: a function or nothing is left out of an
    object and ``null`` in a list, and nothing at the top is undefined."""
    if value is None or _is_function(value):
        return _UNDEFINED if top else None
    if value is Utils.NULL_VALUE:
        return None
    if isinstance(value, (bool, str)):
        return value
    if isinstance(value, (int, float)):
        return _number(value)
    if isinstance(value, dict):
        return {
            str(key): plain(item)
            for key, item in value.items()
            if item is not None and not _is_function(item)
        }
    if isinstance(value, list):
        return [plain(item) for item in value]
    return _UNDEFINED if top else None


@lru_cache(maxsize=16)
def _clock(millis: int) -> dict[str, Any]:
    """``$now()`` and ``$millis()`` answering one instant, bound as the SDK
    binds them. One run's expressions share an instant, so they share these."""
    return {
        "now": jsonata.Jsonata(
            f"function($picture, $timezone) {{ $fromMillis({millis}, $picture, $timezone) }}"
        ).evaluate({}),
        "millis": jsonata.Jsonata(f"function() {{ {millis} }}").evaluate({}),
    }


@lru_cache(maxsize=256)
def _parsed(expression: str) -> jsonata.Jsonata:
    """An expression parsed once. Each run binds its own document and sets
    the bounds afresh: the library counts the time bound from when the bounds
    were set, and reads the instance it is evaluating from a thread-local."""
    parsed = jsonata.Jsonata(expression)
    parsed.set_output_convert_nulls(False)
    return parsed


def _run(expression: str, document: Any, millis: int | None, bounds: tuple) -> Any:
    time_ms, depth, _ = bounds
    parsed = _parsed(expression)
    parsed.environment.set_runtime_bounds(time_ms, depth)
    jsonata.Jsonata.CURRENT.jsonata = parsed
    bindings = _clock(millis) if millis is not None else None
    return plain(parsed.evaluate(document, bindings), top=True)


def answer(request: dict[str, Any], bounds: tuple) -> dict[str, Any]:
    """What one request answers: a value, undefined, or an error."""
    document = request.get("document")
    try:
        value = _run(request["expression"], document, request.get("millis"), bounds)
        if value is _UNDEFINED:
            return {"undefined": True}
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        if len(text.encode("utf-8")) > bounds[2]:
            return {"error": f"the answer is over {bounds[2]} bytes"}
        if request.get("predicate"):
            # ``$boolean`` of the answer, which is plain JSON already.
            truth = _run("$boolean($)", value, None, bounds)
            return {"value": truth is True}
        return {"value": value}
    except jsonata.JException as error:
        reply = {"error": str(error), "position": error.location}
        if error.error == _TIMEOUT:
            # The time bound depends on the machine's load as well as the
            # expression.
            reply["transient"] = True
        return reply
    except RecursionError:
        return {"error": "Stack overflow"}
    except MemoryError:
        return {
            "error": "the evaluation ran out of memory",
            "replace": True,
            "transient": True,
        }
    except Exception as error:  # every evaluation failure is one answer
        return {"error": str(error) or type(error).__name__}


def start(arguments: list[str]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Set the process's bounds, and answer requests within them."""
    # The depth bound is the library's; this only keeps Python's own limit
    # from being reached first.
    sys.setrecursionlimit(20_000)
    time_ms, depth, output, address_space = (int(value) for value in arguments)
    bounds = (time_ms, depth, output)
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (address_space, address_space))
    except ImportError, ValueError, OSError:
        pass
    return lambda request: answer(request, bounds)
