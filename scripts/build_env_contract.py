#!/usr/bin/env python3
"""Publish what this deployment requires, as data.

Whoever deploys Initiative has to answer one question — *what must I supply?* —
and until now the only honest answer was "read config.py". That file is 1,000
lines and declares 131 settings, of which five are actually mandatory. A
deployment tool that cannot tell those apart either carries all of them or
guesses, and both were happening: the Helm chart in initiative_infra parses this
module with `ast` to find out, and its own `verify-contracts.py` exists because
a required setting once went missing and nothing noticed until two features
failed closed in production.

So the app publishes it instead. Same idea as initiative-github's
`env-contract.json`, which is read rather than parsed, and the same file name, so
one consumer handles every app in the set.

Four classes, because "required" alone is the distinction that misleads:

  required      No default. The app will not start without it.
  runtime       Read once as a first-boot SEED, then owned by a database row and
                edited in Settings -> Platform (config.RUNTIME_SEEDED_SETTINGS).
                An operator does not need these at deploy time at all — which is
                the whole point of publishing them as their own class.
  env_only      Operator credentials for an optional feature with no database
                path, so the only place to set them is the environment. These are
                the ones a deployment tool genuinely must carry.
  optional      Everything else: tunables with defaults that work.

Regenerate after changing Settings, and commit the result:

    scripts/build_env_contract.py

Committed rather than built, because whoever reads it has a checkout and not a
build — the same reason initiative-github commits its own.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))


# config.py instantiates Settings at import, so describing the SCHEMA needs an
# environment that validates. Placeholders for exactly the fields with no
# default, so this runs on a fresh clone with no .env. A new required setting
# makes the import fail with pydantic naming it — which is the right failure:
# add it here, deliberately, rather than having the contract quietly omit it.
os.environ.setdefault("SECRET_KEY", "0" * 64)

from app.core.config import (
    ENV_ONLY_FEATURE_CREDENTIALS,
    RUNTIME_SEEDED_SETTINGS,
    Settings,
)

OUT = REPO_ROOT / "env-contract.json"


def build() -> dict[str, object]:
    required: list[str] = []
    runtime: list[str] = []
    env_only: list[str] = []
    optional: list[str] = []

    for name, field in Settings.model_fields.items():
        if name in RUNTIME_SEEDED_SETTINGS:
            # Listed here even when it has no default: the seed is optional by
            # construction, because the database row is the real home.
            runtime.append(name)
        elif name in ENV_ONLY_FEATURE_CREDENTIALS:
            env_only.append(name)
        elif field.is_required():
            required.append(name)
        else:
            optional.append(name)

    unknown = (RUNTIME_SEEDED_SETTINGS | ENV_ONLY_FEATURE_CREDENTIALS) - set(
        Settings.model_fields
    )
    if unknown:
        raise SystemExit(
            "config.py names settings that Settings does not declare: "
            + ", ".join(sorted(unknown))
        )

    return {
        "service": "initiative",
        # No prefix: an env var is the field name exactly. Stated because it is
        # NOT true of every app in the set — initiative-billing uses BILLING_.
        "env_prefix": "",
        "required": sorted(required),
        # Nothing to register with a vendor: Initiative is what apps register
        # WITH. The key is present and empty so every contract has one shape.
        "registration": [],
        "runtime": sorted(runtime),
        "env_only": sorted(env_only),
        "optional": sorted(optional),
    }


def main() -> None:
    OUT.write_text(json.dumps(build(), indent=2) + "\n", encoding="utf-8")
    contract = json.loads(OUT.read_text(encoding="utf-8"))
    print(
        f"wrote {OUT.name}: "
        f"{len(contract['required'])} required, "
        f"{len(contract['runtime'])} runtime-seeded, "
        f"{len(contract['env_only'])} env-only credentials, "
        f"{len(contract['optional'])} optional"
    )


if __name__ == "__main__":
    main()
