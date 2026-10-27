"""The document editor, as the server runs it.

A document's Yjs state and its editor JSON are two views of one document, and
only the editor knows how one maps to the other. So the server runs the same
editor the browser does: its server build (``frontend/src/lib/yjs/serverEditor.ts``,
built by ``pnpm build:editor-server``), in an embedded V8 in worker processes
(:mod:`app.services.editor_worker`, through :mod:`app.services.worker_pool`).

The pool starts on the first call, holds one worker per process, and a worker
idle for ``_IDLE_SECONDS`` exits, so a server where nobody edits a document
never starts the engine.
"""

from __future__ import annotations

import asyncio
import atexit
import base64
import secrets
import threading
from pathlib import Path
from typing import Any, Optional

from app.services.worker_pool import Pool, PoolError

__all__ = ["EditorError", "apply", "bootstrap", "render", "shutdown"]

_BACKEND = Path(__file__).resolve().parents[2]
#: Where the editor's server build is: copied beside the backend in the image,
#: built into the frontend in a checkout.
_SCRIPTS = (
    _BACKEND / "editor" / "editor.js",
    _BACKEND.parent / "frontend" / "dist-editor" / "editor.js",
)
_HANDLER = Path(__file__).with_name("editor_worker.py")
#: Measured: a 411 KB document is bootstrapped or rendered in about 0.3 s.
_TIME_MS = 10_000
_HEAP_BYTES = 512 * 1024 * 1024
_IDLE_SECONDS = 300


class EditorError(Exception):
    """The editor gave no answer: it refused the document, or did not run."""


_pool: Optional[Pool] = None
_pool_lock = threading.Lock()


def _script() -> Path:
    for script in _SCRIPTS:
        if script.is_file():
            return script
    raise EditorError(
        "the editor's server build is missing: run `pnpm build:editor-server` "
        "in frontend/"
    )


def _the_pool() -> Pool:
    global _pool
    with _pool_lock:
        if _pool is None:
            script = _script()
            # The app's lifespan stops it; a process that has none stops it
            # on its way out.
            atexit.register(shutdown)
            _pool = Pool(
                handler=_HANDLER,
                arguments=[str(script), str(_HEAP_BYTES)],
                size=1,
                time_ms=_TIME_MS,
                idle_seconds=_IDLE_SECONDS,
            )
        return _pool


def shutdown() -> None:
    """Stop the pool's worker; the next call starts a new pool."""
    global _pool
    with _pool_lock:
        pool, _pool = _pool, None
    if pool is not None:
        pool.shutdown()


async def _ask(request: dict[str, Any]) -> dict[str, Any]:
    try:
        pool = _the_pool()
        reply = await asyncio.to_thread(pool.ask, request)
    except PoolError as exc:
        raise EditorError(str(exc)) from exc
    if "error" in reply:
        raise EditorError(reply["error"])
    return reply


async def bootstrap(content: Optional[dict]) -> bytes:
    """A document's Yjs state, from its editor JSON, or the state of an empty
    document when it has none. Written as a Yjs client of its own."""
    reply = await _ask(
        {"op": "bootstrap", "content": content, "client": secrets.randbits(32)}
    )
    return base64.b64decode(reply["state"])


async def render(state: bytes) -> dict:
    """The editor JSON a Yjs state reads as."""
    reply = await _ask(
        {"op": "render", "state": base64.b64encode(state).decode("ascii")}
    )
    return reply["content"]


async def from_markdown(text: str, *, plain: bool = False) -> dict:
    """The editor JSON ``text`` reads as: as Markdown, through the editor's
    own Markdown reading, or, ``plain``, as paragraphs."""
    reply = await _ask({"op": "markdown", "text": text, "plain": plain})
    return reply["content"]


async def apply(state: bytes, content: dict) -> bytes:
    """The Yjs update that makes ``state`` read as ``content``, rewriting only
    what changed. Written as a Yjs client of its own."""
    reply = await _ask(
        {
            "op": "apply",
            "state": base64.b64encode(state).decode("ascii"),
            "content": content,
            "client": secrets.randbits(32),
        }
    )
    return base64.b64decode(reply["update"])
