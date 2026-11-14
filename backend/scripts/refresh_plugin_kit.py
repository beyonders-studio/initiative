#!/usr/bin/env python
"""Refresh the vendored plugin-kit contract.

The contract is written in the ``initiative-plugin-sdk`` repository and vendored
here, so the diff a reviewer reads is the contract itself and no build step
depends on the network. This script is how the copy moves.

    python scripts/refresh_plugin_kit.py --ref v0.10.0     # from an SDK revision
    python scripts/refresh_plugin_kit.py --from ../initiative-plugin-sdk
    python scripts/refresh_plugin_kit.py --check           # is the copy current?

Moving it is a deliberate act: a newer contract may declare terms this build
does not act on yet, and ``contract_coverage_test`` fails until each one has a
handler or the normalizer's inventory is brought into line.

The kit also publishes the plug-in API's OpenAPI document
(``schemas/plugin-api.json``), the contract plug-ins are generated against.
Vendored beside the rest, it is what ``plugin_openapi_superset_test`` holds
this build's plug-in API to: everything it names must still be served. Kit
releases older than the first that publishes it have none, so a refresh to one
of them vendors none (and removes a copy left by a newer one).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
VENDOR = _BACKEND / "vendor" / "plugin-kit"

#: The browser validates a widget's meta too, against the same numbers, so the
#: contract is vendored where the SPA can import it as well. Same revision, one
#: refresh, and ``widget_meta_test`` fails if the two copies differ.
FRONTEND_CONTRACT = (
    _BACKEND.parent / "frontend" / "src" / "contract" / "manifest.contract.json"
)
RAW = "https://raw.githubusercontent.com/beyonders-studio/initiative-plugin-sdk"

#: What the kit publishes and this build reads: the contract, and the schema
#: generated from it that the conformance tests run.
FILES = {
    "manifest.contract.json": "manifest.contract.json",
    "plugin-manifest.json": "schemas/plugin-manifest.json",
}

#: What the kit publishes from some release on, and not before. Absent from the
#: kit, it is absent here too: ``None`` in the bodies below.
OPTIONAL_FILES = {
    "plugin-api.json": "schemas/plugin-api.json",
}


def from_checkout(root: Path) -> dict[str, str | None]:
    bodies: dict[str, str | None] = {
        local: (root / remote).read_text(encoding="utf-8")
        for local, remote in FILES.items()
    }
    for local, remote in OPTIONAL_FILES.items():
        path = root / remote
        bodies[local] = path.read_text(encoding="utf-8") if path.exists() else None
    return bodies


def _fetch(ref: str, remote: str) -> str:
    url = f"{RAW}/{ref}/{remote}"
    with urllib.request.urlopen(url, timeout=30) as response:
        return response.read().decode("utf-8")


def from_ref(ref: str) -> dict[str, str | None]:
    bodies: dict[str, str | None] = {
        local: _fetch(ref, remote) for local, remote in FILES.items()
    }
    for local, remote in OPTIONAL_FILES.items():
        try:
            bodies[local] = _fetch(ref, remote)
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
            bodies[local] = None
    return bodies


def stamp(root: Path | None, ref: str | None) -> dict[str, str]:
    """Which kit release the vendored copy came from."""
    if root is not None:
        version = json.loads((root / "package.json").read_text(encoding="utf-8"))[
            "version"
        ]
        revision = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        return {"KIT_VERSION": version, "KIT_REVISION": revision}
    with urllib.request.urlopen(f"{RAW}/{ref}/package.json", timeout=30) as response:
        version = json.loads(response.read().decode("utf-8"))["version"]
    return {"KIT_VERSION": version, "KIT_REVISION": ref or ""}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--ref", help="a kit tag, branch or commit to fetch")
    source.add_argument(
        "--from", dest="checkout", type=Path, help="a local kit checkout to copy from"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero if the vendored copy differs, writing nothing",
    )
    args = parser.parse_args()

    if args.checkout is None and args.ref is None and not args.check:
        parser.error("give --ref or --from")

    if args.check and args.checkout is None and args.ref is None:
        args.ref = (VENDOR / "KIT_REVISION").read_text(encoding="utf-8").strip()

    bodies = from_checkout(args.checkout) if args.checkout else from_ref(args.ref)
    for body in bodies.values():
        if body is not None:
            json.loads(body)  # refuse to write something that is not JSON at all
    bodies.update({k: f"{v}\n" for k, v in stamp(args.checkout, args.ref).items()})

    stale = False
    targets = {VENDOR / name: body for name, body in bodies.items()}
    targets[FRONTEND_CONTRACT] = bodies["manifest.contract.json"]
    for target, body in targets.items():
        current = target.read_text(encoding="utf-8") if target.exists() else None
        if current == body:
            continue
        if args.check:
            print(f"{target} differs from the kit", file=sys.stderr)
            stale = True
        elif body is None:
            # The kit at this revision publishes no such file.
            target.unlink()
            print(f"removed {target}")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="utf-8")
            print(f"wrote {target}")
    if stale:
        return 1
    if args.check:
        print("the vendored contract is current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
