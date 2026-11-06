#!/usr/bin/env bash
# Orchestrate the dev environment startup chain. Equivalent of the VSCode dev:setup
# task chain: deps -> db -> migrate -> seed -> backend (bg) -> frontend (bg) -> browser.
#
# Cleanup belongs to a *running* environment. Once both servers are up, every
# exit path tears them down and removes the seeded data: Ctrl+C (SIGINT), kill
# (SIGTERM), closing the terminal (SIGHUP), or either server exiting on its own.
# Interrupting the startup chain before that point leaves the database alone —
# nothing of this launch's is running yet, and the data is wanted for the next
# attempt. A seed cut short that way is cleared at the top of the next launch.
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# This checkout's ports, log paths and frontend API URLs. The main working tree
# keeps 8000/5173; linked worktrees get their own pair so several run at once.
. "$SCRIPT_DIR/dev-ports.sh"
# dev-ports.sh has already said why if it could not resolve them.
[ -n "${DEV_BACKEND_PORT:-}" ] || exit 1
cd "$SCRIPT_DIR/.."

BACKEND_PID=""
FRONTEND_PID=""
OPEN_PID=""

# The guard makes the function idempotent so the signal path (trap fires, the
# poll loop below falls through, EXIT trap fires) and the natural-exit path (a
# server died) both end in exactly one cleanup pass.
cleanup_done=false
cleanup() {
    if [ "$cleanup_done" = true ]; then
        return 0
    fi
    cleanup_done=true
    echo
    echo "Stopping dev environment..."
    # Stop the servers this script started, then let dev-cleanup.sh sweep up
    # whatever is still on the ports and remove the seeded data.
    for pid in "$BACKEND_PID" "$FRONTEND_PID" "$OPEN_PID"; do
        if [ -n "$pid" ]; then
            kill "$pid" 2>/dev/null || true
        fi
    done
    bash "$SCRIPT_DIR/dev-cleanup.sh" || true
}

# Startup isn't the environment, so stopping it isn't stopping the environment:
# say what was left behind and get out without touching the database.
abort_startup() {
    echo
    echo "Startup interrupted — dev data left in place."
    echo "  To remove it: bash scripts/dev-cleanup.sh"
    exit 130
}
trap abort_startup INT TERM HUP

# A server left over from a previous run holds open database sessions, and the
# seed below drops the guild schemas those sessions are sitting in. These ports
# are this checkout's, so what is on them is this checkout's to stop — the
# equivalent of the VSCode chain's dev:free-ports task.
bash scripts/dev-cleanup.sh --ports-only

port_holder() {
    if command -v lsof &>/dev/null; then
        lsof -ti:"$1" 2>/dev/null | head -1
    elif command -v fuser &>/dev/null; then
        fuser "$1"/tcp 2>/dev/null | tr -d ' ' | head -1
    fi
}
# Anything still on a port after that sweep is something this checkout could
# not stop; say so rather than letting uvicorn or Vite fail to bind later.
for spec in "backend:$DEV_BACKEND_PORT" "frontend:$DEV_FRONTEND_PORT"; do
    holder=$(port_holder "${spec#*:}")
    if [ -n "$holder" ]; then
        echo "Port ${spec#*:} (${spec%%:*}) is still held by pid $holder after the sweep above." >&2
        echo "It belongs to something this checkout cannot stop. Stop it yourself, or pin" >&2
        echo "this checkout elsewhere with DEV_BACKEND_PORT / DEV_FRONTEND_PORT." >&2
        exit 1
    fi
done

# Bring both environments in line with the lockfiles, so a pull that changed a
# dependency doesn't start the servers on the old set. Both are quick no-ops
# when nothing changed.
(cd backend && uv sync)
(cd frontend && pnpm install)

docker compose up db -d --wait

# A seed that stopped partway left rows the next one would collide with. Clear
# them here, before the migrate below puts the primary guild + superuser back.
seed_status="$(cd backend && .venv/bin/python ../scripts/seed_dev_data.py --status 2>/dev/null | tail -n 1)"
if [ "$seed_status" = partial ]; then
    echo "A previous seed was interrupted — clearing the partial data first."
    bash scripts/dev-cleanup.sh --data-only
fi

bash scripts/dev-migrate.sh
bash scripts/dev-seed.sh

# Spawning a server and recording its pid are two statements, and a signal
# landing between them would reach a cleanup that cannot see that server. Note
# the signal instead of acting on it, and let the check below run the teardown
# once both pids are recorded and the ports are known to be this launch's.
pending_signal=false
trap 'pending_signal=true' INT TERM HUP

# Start the backend in the background (uvicorn with --reload, port-cleanup built in).
nohup bash scripts/dev-backend.sh > "$DEV_BACKEND_LOG" 2>&1 &
BACKEND_PID=$!

# Start the frontend in the background (Vite, port-cleanup built in).
nohup bash scripts/dev-frontend.sh > "$DEV_FRONTEND_LOG" 2>&1 &
FRONTEND_PID=$!

# Open the browser once both servers actually answer, rather than the moment
# Vite binds its port — the API is still booting then, and the app lands on its
# "no server" screen. Same opener the VSCode launch uses.
nohup bash scripts/dev-open.sh > "$DEV_OPEN_LOG" 2>&1 &
OPEN_PID=$!

# The environment is up and both pids are recorded, so the servers, the ports
# and the seeded data are now this launch's to tear down.
trap cleanup INT TERM HUP EXIT

if [ "$pending_signal" = true ]; then
    exit 0
fi

echo
echo "Dev environment starting (checkout $DEV_CHECKOUT_ID):"
echo "  Backend:  http://localhost:$DEV_BACKEND_PORT   (logs: $DEV_BACKEND_LOG)"
echo "  Frontend: http://localhost:$DEV_FRONTEND_PORT   (logs: $DEV_FRONTEND_LOG)"
echo "  Stop:     press Ctrl+C in this terminal (or run bash scripts/dev-cleanup.sh)"
echo

# Block until a signal arrives or one of the servers exits. Poll rather than
# `wait`: plain `wait BACKEND_PID FRONTEND_PID` sits on the survivor when only
# one server goes down, so a backend that died at startup would leave the
# terminal blocked and the cleanup unrun, and `wait -n` (which returns on the
# first exit) needs bash 4.3+ — macOS still ships 3.2. `sleep` is interruptible,
# so a signal fires the trap above promptly. `set -e` is off from here so a
# server exiting non-zero doesn't bypass the trap on its way out.
set +e
while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$FRONTEND_PID" 2>/dev/null; do
    sleep 1
done

# Ctrl+C reaches both servers, so both go down and there is nothing to explain.
# One down while the other is still up means that server fell over on its own —
# point at its log, since the environment is about to disappear either way. The
# pause lets the second server finish exiting before the two are told apart.
sleep 0.5
backend_up=false
frontend_up=false
kill -0 "$BACKEND_PID" 2>/dev/null && backend_up=true
kill -0 "$FRONTEND_PID" 2>/dev/null && frontend_up=true
if [ "$cleanup_done" = false ]; then
    if [ "$backend_up" = false ] && [ "$frontend_up" = true ]; then
        echo "Backend exited — see $DEV_BACKEND_LOG"
    elif [ "$frontend_up" = false ] && [ "$backend_up" = true ]; then
        echo "Frontend exited — see $DEV_FRONTEND_LOG"
    fi
fi
