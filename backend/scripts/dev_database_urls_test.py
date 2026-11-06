"""Tests for the database URLs a migration worktree runs on."""

import os
import shlex
import subprocess
import sys
from pathlib import Path

from sqlalchemy.engine import make_url

SCRIPT = Path(__file__).resolve().parent / "dev_database_urls.py"


def test_every_url_names_the_database_and_keeps_its_login():
    env = {
        **os.environ,
        "DATABASE_URL": "postgresql+asyncpg://app_provisioner:p1@db:5433/initiative",
        "DATABASE_URL_APP": "postgresql+asyncpg://app_user:p2@db:5433/initiative",
        "DATABASE_URL_ADMIN": "postgresql+asyncpg://app_admin:p3@db:5433/initiative",
    }
    printed = subprocess.run(
        [sys.executable, str(SCRIPT), "initiative_dev_ab12cd34"],
        capture_output=True,
        text=True,
        check=True,
        env=env,
        cwd=SCRIPT.parent.parent,
    ).stdout
    urls = {}
    for line in printed.splitlines():
        name, _, value = line.removeprefix("export ").partition("=")
        urls[name] = shlex.split(value)[0]
    for name, login, password in (
        ("DATABASE_URL", "app_provisioner", "p1"),
        ("DATABASE_URL_APP", "app_user", "p2"),
        ("DATABASE_URL_ADMIN", "app_admin", "p3"),
    ):
        url = make_url(urls[name])
        assert (url.username, url.password, url.host, url.port, url.database) == (
            login,
            password,
            "db",
            5433,
            "initiative_dev_ab12cd34",
        )
