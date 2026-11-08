"""Print the exports that point this checkout's database URLs at another database
on the same server. ``scripts/dev-ports.sh`` evals them for a worktree whose
branch changes migrations, which runs on a dev database of its own:

    python scripts/dev_database_urls.py initiative_dev_<id>

Each DATABASE_URL* the settings read, from the environment or a .env file, comes
out with only its database changed, so the logins and passwords stay the ones
the main checkout uses. Run it from backend/, where the settings read ``.env``.
"""

from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy.engine import make_url

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import ENV_FILES, Settings  # noqa: E402

URLS = (
    "DATABASE_URL",
    "DATABASE_URL_APP",
    "DATABASE_URL_ADMIN",
    "DATABASE_URL_BOOTSTRAP",
    "DATABASE_URL_LISTEN",
    "DATABASE_URL_QUERY",
)


def exports(database: str) -> list[str]:
    # In the settings' own order: the default, each .env file over the one
    # before it, and the environment over them all.
    given = {"DATABASE_URL": Settings.model_fields["DATABASE_URL"].default}
    for path in ENV_FILES:
        given.update(dotenv_values(path))
    given.update(os.environ)
    lines = []
    for name in URLS:
        if url := given.get(name):
            renamed = make_url(url).set(database=database)
            value = renamed.render_as_string(hide_password=False)
            lines.append(f"export {name}={shlex.quote(value)}")
    return lines


if __name__ == "__main__":
    print("\n".join(exports(sys.argv[1])))
