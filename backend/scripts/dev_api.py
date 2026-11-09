"""Run the API under the debugger on this checkout's port.

VSCode's launch.json is static JSON: it can substitute a variable but cannot run
a shell, so it has no way to ask which port a linked worktree was allocated. The
debug config points here instead. This asks ``scripts/dev-ports.sh`` — the one
place dev ports are decided — and then starts uvicorn in-process, so breakpoints
land exactly as they did when the config invoked the uvicorn module directly.

Run it by hand the same way:  python scripts/dev_api.py
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
DEV_PORTS_SH = BACKEND_DIR.parent / "scripts" / "dev-ports.sh"


#: What dev-ports.sh decides beside the port: a worktree whose branch changes
#: migrations runs on a database of its own (dev_database_urls.py), with role
#: names of its own, and the dev server plays Initiative Cloud.
DEV_VARIABLES = (
    "DATABASE_URL",
    "DATABASE_URL_APP",
    "DATABASE_URL_ADMIN",
    "DATABASE_URL_BOOTSTRAP",
    "DATABASE_URL_LISTEN",
    "DATABASE_URL_QUERY",
    "GUILD_ROLE_PREFIX",
    "PLATFORM_ROLE_PREFIX",
    "DEV_AS_CLOUD",
)


def dev_port() -> int:
    """This checkout's backend port, straight from dev-ports.sh, which also puts
    the database this checkout runs on into the environment.

    An explicit DEV_BACKEND_PORT wins, exactly as it does in the shell scripts.
    """
    names = ("DEV_BACKEND_PORT", *DEV_VARIABLES)
    printed = "; ".join(f'printf "%s\\n" "${{{name}:-}}"' for name in names)
    result = subprocess.run(
        ["bash", "-c", f". {shlex.quote(str(DEV_PORTS_SH))} && {{ {printed}; }}"],
        capture_output=True,
        text=True,
        check=False,
    )
    # dev-ports.sh explains itself on stderr when it cannot resolve a port, and
    # fails when it cannot give a worktree its own database.
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if result.returncode:
        raise SystemExit("dev_api: no database for this checkout — see above.")
    values = dict(zip(names, result.stdout.split("\n")))
    for name in DEV_VARIABLES:
        if values.get(name):
            os.environ.setdefault(name, values[name])
    port = values.get("DEV_BACKEND_PORT")
    if not port:
        raise SystemExit("dev_api: no port for this checkout — see above.")
    return int(port)


if __name__ == "__main__":
    import uvicorn

    # `python -m uvicorn` put the working directory on sys.path, which is how
    # "app.main" resolved before. Running a *script* puts the script's own
    # directory there instead — backend/scripts — so backend/ has to be added
    # back explicitly. PYTHONPATH as well as sys.path: the reloader serves from
    # a spawned subprocess, and that is what carries the path into it.
    os.chdir(BACKEND_DIR)
    sys.path.insert(0, str(BACKEND_DIR))
    existing = os.environ.get("PYTHONPATH")
    os.environ["PYTHONPATH"] = (
        f"{BACKEND_DIR}{os.pathsep}{existing}" if existing else str(BACKEND_DIR)
    )

    uvicorn.run("app.main:app", host="0.0.0.0", port=dev_port(), reload=True)
