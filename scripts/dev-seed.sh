#!/usr/bin/env bash
# Seed TTRPG dev data, into this checkout's dev database
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/../backend"

. "$SCRIPT_DIR/dev-ports.sh"
. "$SCRIPT_DIR/dev-owner.sh"

source .venv/bin/activate
# The app imports alone take a few seconds before the seeder prints anything.
echo "Seeding dev data (loading the app first — this stays quiet for a moment)..."
python "$SCRIPT_DIR/seed_dev_data.py"
