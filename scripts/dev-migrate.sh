#!/usr/bin/env bash
# Run database migrations and seed the dev owner, on this checkout's dev database
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
bash "$SCRIPT_DIR/dev-database.sh"
cd "$SCRIPT_DIR/../backend"

. "$SCRIPT_DIR/dev-ports.sh"
. "$SCRIPT_DIR/dev-owner.sh"

source .venv/bin/activate
python -m app.db.init_db
