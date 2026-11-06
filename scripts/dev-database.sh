#!/usr/bin/env bash
# Get this checkout's dev database ready to migrate. A worktree whose branch
# changes migrations has a database of its own (see scripts/dev-ports.sh), made
# here the first time; every other checkout runs on the main checkout's. Then
# the login roles and the search operator class are applied to it. Idempotent;
# dev-migrate.sh runs it before every migrate.
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SCRIPT_DIR/dev-ports.sh"
cd "$SCRIPT_DIR/.."

su_user="${POSTGRES_USER:-initiative}"
if [ -n "${DEV_DATABASE:-}" ] && ! docker compose exec -T db psql -U "$su_user" -d postgres -tAc \
    "SELECT 1 FROM pg_database WHERE datname = '$DEV_DATABASE'" | grep -q 1; then
    echo "This branch changes migrations, so it runs on a dev database of its own: $DEV_DATABASE"
    docker compose exec -T db createdb -U "$su_user" "$DEV_DATABASE"
fi

# The login roles and the search operator class: a deployment gets these from
# app.db.bootstrap at startup over its owner connection. A .env that names the
# three logins usually gives no owner, and the compose superuser is right here,
# so apply them the same way rather than leave every checkout to hit the boot
# warning, on this checkout's own database when it has one. A .env with
# DATABASE_URL as the owner needs no override. Idempotent; a failure is not
# fatal, since search works either way.
bootstrap_url=""
if grep -qsE '^DATABASE_URL_APP=.+' backend/.env "$DEV_MAIN_ROOT/backend/.env"; then
    bootstrap_url="postgresql+asyncpg://${su_user}:${POSTGRES_PASSWORD:-initiative}@localhost:5432/${DEV_DATABASE:-${POSTGRES_DB:-initiative}}"
fi
if ! (
    cd backend && source .venv/bin/activate &&
    if [ -n "$bootstrap_url" ]; then export DATABASE_URL_BOOTSTRAP="$bootstrap_url"; fi &&
    python -m app.db.bootstrap > /dev/null
); then
    echo "Database bootstrap did not complete — search may run without its index." >&2
fi
