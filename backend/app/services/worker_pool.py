"""A small pool of worker processes (:mod:`worker_host`), each running one
handler module: JSONata evaluation (:mod:`jsonata_worker`) or the document
editor (:mod:`editor_worker`).

Each worker answers one request at a time. A worker still busy past a
request's deadline is stopped and replaced, which is what bounds work a
handler cannot interrupt on its own. Nothing starts until the first request;
a worker left idle exits by itself, and :meth:`Pool.shutdown` stops the rest.
A worker whose parent goes away reads the end of its input and exits.

Calls block, and are made from a thread (``asyncio.to_thread``), so one pool
serves every event loop in the process.
"""

from __future__ import annotations

import json
import os
import select
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

__all__ = ["Pool", "PoolError"]

HOST = Path(__file__).with_name("worker_host.py")
_LENGTH = struct.Struct(">I")


class PoolError(Exception):
    """No answer: the deadline passed, or the worker stopped."""


class _Overran(Exception):
    """The deadline passed before the worker answered."""


class _Worker:
    def __init__(self, arguments: list[str]) -> None:
        # ``-I``: the standard library and installed packages only, so the
        # worker imports nothing of the application.
        self.process = subprocess.Popen(
            [sys.executable, "-I", str(HOST), *arguments],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )
        assert self.process.stdin is not None and self.process.stdout is not None
        self.stdin = self.process.stdin.fileno()
        self.stdout = self.process.stdout.fileno()

    def call(self, data: bytes, deadline: float) -> bytes | None:
        """The worker's answer, or ``None`` when it has stopped. Raises
        :class:`_Overran` past ``deadline``."""
        try:
            view = memoryview(_LENGTH.pack(len(data)) + data)
            while view:
                view = view[os.write(self.stdin, view) :]
            header = self._read(_LENGTH.size, deadline)
            if header is None:
                return None
            return self._read(_LENGTH.unpack(header)[0], deadline)
        except BrokenPipeError, OSError:
            return None

    def _read(self, size: int, deadline: float) -> bytes | None:
        chunks = bytearray()
        while len(chunks) < size:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([self.stdout], [], [], remaining)[0]:
                raise _Overran
            chunk = os.read(self.stdout, size - len(chunks))
            if not chunk:
                return None
            chunks += chunk
        return bytes(chunks)

    def stop(self) -> None:
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait()
        for stream in (self.process.stdin, self.process.stdout):
            if stream is not None:
                stream.close()


class Pool:
    """Up to ``size`` workers running ``handler`` with ``arguments``, each
    answering within ``time_ms`` and a grace period, and exiting after
    ``idle_seconds`` without a request."""

    def __init__(
        self,
        *,
        handler: Path,
        arguments: list[str],
        size: int,
        time_ms: int,
        idle_seconds: int,
        grace_seconds: float = 1.0,
    ) -> None:
        self._size = max(1, size)
        self._time_ms = time_ms
        self._budget = time_ms / 1000 + grace_seconds
        self._arguments = [str(handler), str(idle_seconds), *arguments]
        self._lock = threading.Condition()
        self._idle: list[_Worker] = []
        self._live = 0
        self._closed = False

    def _take(self, deadline: float) -> tuple[_Worker, bool]:
        """A worker, and whether it was waiting idle (and so may have exited)."""
        with self._lock:
            while not self._idle and self._live >= self._size:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise PoolError("no worker came free in time")
                self._lock.wait(remaining)
            if self._idle:
                return self._idle.pop(), True
            self._live += 1
        try:
            return _Worker(self._arguments), False
        except BaseException:
            self._release(None)
            raise

    def _release(self, worker: _Worker | None) -> None:
        with self._lock:
            if worker is not None and not self._closed:
                self._idle.append(worker)
            else:
                self._live -= 1
            self._lock.notify()
        if worker is not None and self._closed:
            worker.stop()

    def ask(self, request: dict[str, Any]) -> dict[str, Any]:
        """One request's answer. Raises :class:`PoolError` when there is none."""
        data = json.dumps(request, ensure_ascii=False).encode("utf-8")
        waited = time.monotonic() + self._budget
        for _ in range(2):
            worker, was_idle = self._take(waited)
            try:
                reply = worker.call(data, time.monotonic() + self._budget)
            except _Overran:
                worker.stop()
                self._release(None)
                raise PoolError(f"timeout after {self._time_ms} milliseconds") from None
            except BaseException:
                worker.stop()
                self._release(None)
                raise
            if reply is not None:
                answered = json.loads(reply)
                if answered.get("replace"):
                    # It ran out of memory, and exits.
                    worker.stop()
                    self._release(None)
                else:
                    self._release(worker)
                return answered
            worker.stop()
            self._release(None)
            if not was_idle:
                break
            # It exited for being idle as it was handed this request: once more
            # on a fresh one.
        raise PoolError("the worker stopped")

    def shutdown(self) -> None:
        """Stop the waiting workers. One still answering is stopped when it
        would have been handed back."""
        with self._lock:
            self._closed = True
            idle, self._idle = self._idle, []
            self._live -= len(idle)
        for worker in idle:
            worker.stop()
