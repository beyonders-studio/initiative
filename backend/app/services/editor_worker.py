"""The document editor in a worker process, for :mod:`worker_host`.

The host loads this module by path and calls :func:`start` with ``<editor
script> <heap bytes>``: the server build of the editor
(``frontend/src/lib/yjs/serverEditor.ts``, built by ``pnpm
build:editor-server``), run in an embedded V8 held to that much heap. This
imports the standard library and ``mini-racer`` and nothing of Initiative.

A request is one of:

- ``{"op": "bootstrap", "content": <editor JSON or null>, "client": <Yjs
  client id>}``, answered ``{"state": <base64>}``;
- ``{"op": "render", "state": <base64>}``, answered ``{"content": <editor
  JSON>}``;
- ``{"op": "apply", "state": <base64>, "content": <editor JSON>, "client":
  <Yjs client id>}``, answered ``{"update": <base64>}``, the update that makes
  the state read as the content;
- ``{"op": "markdown", "text": <text>, "plain": <bool>}``, answered
  ``{"content": <editor JSON>}``: the text read as Markdown, as the editor's
  own Markdown view reads it, or, ``plain``, as paragraphs.

A request the editor refuses is answered ``{"error"}``; one that runs out of
heap also carries ``"replace": true``, and the worker exits.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Callable

from py_mini_racer import JSEvalException, JSOOMException, MiniRacer


def answer(engine: MiniRacer, request: dict[str, Any]) -> dict[str, Any]:
    """What one request answers: a state, a document, or an error."""
    try:
        if request["op"] == "bootstrap":
            content = request.get("content")
            state = engine.call(
                "serverEditor.bootstrap",
                None if content is None else json.dumps(content),
                request["client"],
            )
            return {"state": base64.b64encode(bytes.fromhex(state)).decode("ascii")}
        if request["op"] == "apply":
            update = engine.call(
                "serverEditor.apply",
                base64.b64decode(request["state"]).hex(),
                json.dumps(request["content"]),
                request["client"],
            )
            return {"update": base64.b64encode(bytes.fromhex(update)).decode("ascii")}
        if request["op"] == "render":
            state = base64.b64decode(request["state"]).hex()
            return {"content": json.loads(engine.call("serverEditor.render", state))}
        if request["op"] == "markdown":
            return {
                "content": json.loads(
                    engine.call(
                        "serverEditor.fromMarkdown",
                        request["text"],
                        bool(request["plain"]),
                    )
                )
            }
        return {"error": f"no such operation: {request['op']}"}
    except JSOOMException:
        return {"error": "the editor ran out of memory", "replace": True}
    except JSEvalException as error:
        return {"error": str(error).splitlines()[0]}


def start(arguments: list[str]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Load the editor into a fresh engine, and answer requests with it."""
    script, heap_bytes = arguments
    engine = MiniRacer()
    engine.set_hard_memory_limit(int(heap_bytes))
    engine.eval(Path(script).read_text(encoding="utf-8"))
    return lambda request: answer(engine, request)
