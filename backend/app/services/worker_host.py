"""One worker process of a :class:`app.services.worker_pool.Pool`.

Started as ``python -I worker_host.py <handler> <idle seconds> <argument>...``,
so it imports the standard library and installed packages and nothing of
Initiative. ``<handler>`` is the path of a module defining
``start(arguments) -> answer``; the host loads it by path, hands it the
remaining arguments once, and then asks ``answer`` one request at a time.

Requests arrive on stdin and answers leave on stdout, each a length-prefixed
JSON document. The process exits when stdin closes, when no request arrives
for the idle time, or after an answer carrying ``"replace": true``.
"""

from __future__ import annotations

import importlib.util
import json
import os
import select
import signal
import struct
import sys

_LENGTH = struct.Struct(">I")


def _read(stream: int, size: int) -> bytes | None:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = os.read(stream, size - len(chunks))
        if not chunk:
            return None
        chunks += chunk
    return bytes(chunks)


def _write(stream: int, data: bytes) -> None:
    view = memoryview(_LENGTH.pack(len(data)) + data)
    while view:
        view = view[os.write(stream, view) :]


def main(arguments: list[str]) -> None:
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    handler_path, idle, *handler_arguments = arguments
    spec = importlib.util.spec_from_file_location("worker_handler", handler_path)
    assert spec is not None and spec.loader is not None
    handler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(handler)
    answer = handler.start(handler_arguments)
    stdin, stdout = sys.stdin.fileno(), sys.stdout.fileno()
    while True:
        ready, _, _ = select.select([stdin], [], [], int(idle))
        if not ready:
            return
        header = _read(stdin, _LENGTH.size)
        if header is None:
            return
        body = _read(stdin, _LENGTH.unpack(header)[0])
        if body is None:
            return
        reply = answer(json.loads(body))
        _write(stdout, json.dumps(reply, ensure_ascii=False).encode("utf-8"))
        if reply.get("replace"):
            return


if __name__ == "__main__":
    main(sys.argv[1:])
