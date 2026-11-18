#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FRONTEND_DIR="$(dirname "$SCRIPT_DIR")"
SPEC_PATH=""

# Parse args
while [[ $# -gt 0 ]]; do
  case "$1" in
    --from-spec) SPEC_PATH="$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

if [[ -n "$SPEC_PATH" ]]; then
  echo "Using provided OpenAPI spec: $SPEC_PATH"
  cp "$SPEC_PATH" "${FRONTEND_DIR}/openapi.json"
else
  # This checkout's backend port — a linked worktree's is not 8000. Sourced
  # only here: a --from-spec run (CI) needs no port and no port registry.
  set +u
  . "${FRONTEND_DIR}/../scripts/dev-ports.sh"
  set -u
  # dev-ports.sh has already said why if it could not resolve them.
  [ -n "${DEV_BACKEND_PORT:-}" ] || exit 1
  # Not a browser: this needs an absolute address, so it reads the proxy
  # target rather than VITE_API_URL, which the SPA takes relative.
  API_URL="${VITE_DEV_PROXY_TARGET}/api/v1"
  echo "Fetching OpenAPI spec from ${API_URL}/openapi.json..."
  # The backend takes several seconds to boot (migrations + guild backfill +
  # seeding), and editor tasks often start it in parallel with this script —
  # retry briefly instead of losing that race.
  fetched=0
  for attempt in $(seq 1 20); do
    if curl -sf "${API_URL}/openapi.json" -o "${FRONTEND_DIR}/openapi.json"; then
      fetched=1
      break
    fi
    [[ "$attempt" -eq 1 ]] && echo "Backend not responding yet; waiting (up to 30s)..."
    sleep 1.5
  done
  if [[ "$fetched" -ne 1 ]]; then
    # No running backend: fall back to exporting the spec directly from the
    # app (no server needed) — same path CI uses.
    echo "Backend unreachable; exporting the spec without a server..."
    (cd "${FRONTEND_DIR}/../backend" && uv run python scripts/export_openapi.py "${FRONTEND_DIR}/openapi.json")
  fi
fi

echo "Generating TypeScript types and React Query hooks..."
cd "$FRONTEND_DIR"
pnpm orval
# The tool records, beside the types: written after Orval, which empties the
# folder first.
(cd "${FRONTEND_DIR}/../backend" && uv run python ../scripts/build_tool_records.py)
pnpm format:api

echo "Done! Generated files in src/api/generated/"
