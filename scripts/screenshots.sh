#!/usr/bin/env bash
# Take the screenshots (frontend/e2e/shots) of this checkout's running dev
# environment, light and dark: release pictures into docs/images/releases/,
# and the help center's (e2e/shots/help) into docs/en/images/. Both are
# published with the docs site, not shipped in the app.
#
#   pnpm screenshots                            # every shot
#   pnpm screenshots e2e/shots/help             # the help center's
#   pnpm screenshots e2e/shots/gantt.shot.ts    # one
#
# Start the dev environment with its seed data first (scripts/dev-pre-launch.sh).
# SHOTS_URL points the shots at another server instead.
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ -z "${SHOTS_URL:-}" ]; then
    . "$SCRIPT_DIR/dev-ports.sh"
    # dev-ports.sh has already said why if it could not resolve them.
    [ -n "${DEV_FRONTEND_PORT:-}" ] || exit 1
    export DEV_FRONTEND_PORT
    SHOTS_URL="http://localhost:$DEV_FRONTEND_PORT"
fi

if ! curl -s -o /dev/null -m 5 "$SHOTS_URL"; then
    echo "Nothing is answering at $SHOTS_URL. Start the dev environment first (scripts/dev-pre-launch.sh)." >&2
    exit 1
fi
export SHOTS_URL

cd "$SCRIPT_DIR/../frontend"
pnpm exec playwright test --project=light --project=dark "$@"
