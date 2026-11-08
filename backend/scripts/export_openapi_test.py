"""Tests for the offline OpenAPI export script.

Run the script the way CI's ``check-generated-types`` job does — in a clean
environment with no ``.env`` and none of the app's required variables — so a
regression in its dummy-value bootstrapping (e.g. a placeholder SECRET_KEY
that the startup validator rejects) fails here instead of in a downstream
workflow. Also gives the ``scripts/`` directory pytest coverage so the CI
test-scope derivation (which maps changed dirs to pytest targets) collects
tests for scripts-only PRs rather than exiting with "no tests ran".
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
SCRIPT = BACKEND_DIR / "scripts" / "export_openapi.py"


@pytest.mark.parametrize(
    ("flags", "path"), [([], "/api/v1/auth/token"), (["--plugin"], "/projects/")]
)
def test_export_runs_without_app_env(tmp_path, flags, path):
    out = tmp_path / "openapi.json"
    env = {
        k: v
        for k, v in os.environ.items()
        # Drop the app's own config so the script must self-bootstrap its
        # dummy values — mirroring a fresh CI checkout with no .env.
        if not (k.startswith(("DATABASE_URL", "SECRET_KEY", "APP_URL")))
    }
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *flags, str(out)],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    spec = json.loads(out.read_text())
    assert spec["info"]["title"]
    assert path in spec["paths"]
