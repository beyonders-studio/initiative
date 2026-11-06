#!/usr/bin/env bash
# Resolve this checkout's dev ports, log paths and frontend API URLs. Sourced by
# every dev script so they all agree on which ports belong to this worktree:
#
#   . "$SCRIPT_DIR/dev-ports.sh"
#
# The main working tree keeps the familiar 8000/5173. Linked worktrees — one per
# agent or branch — take an offset derived from their path, so several of them
# run side by side instead of taking the ports from each other. The path is used
# rather than the branch so the offset survives a rename or a branch switch.
#
# Set DEV_BACKEND_PORT / DEV_FRONTEND_PORT yourself to pin a checkout to
# particular ports; both are honoured if already set.

DEV_PORTS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"

# A linked worktree's git dir lives under the main checkout's .git/worktrees/;
# the main working tree's is the .git directory itself.
if [ -z "${DEV_CHECKOUT_ID:-}" ]; then
    if git -C "$DEV_PORTS_ROOT" rev-parse --git-dir >/dev/null 2>&1 &&
        [ "$(git -C "$DEV_PORTS_ROOT" rev-parse --git-dir)" != \
          "$(git -C "$DEV_PORTS_ROOT" rev-parse --git-common-dir)" ]; then
        DEV_CHECKOUT_ID="$(printf '%s' "$DEV_PORTS_ROOT" | sha256sum | cut -c1-8)"
    else
        DEV_CHECKOUT_ID=main
    fi
fi

# The main checkout. A linked worktree runs on its Postgres through its compose
# file (and the .env beside it), and reads its backend/.env (app/core/config.py),
# so none of them is copied in.
DEV_MAIN_ROOT="$(git -C "$DEV_PORTS_ROOT" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
DEV_MAIN_ROOT="${DEV_MAIN_ROOT%/.git}"
[ -d "$DEV_MAIN_ROOT/.git" ] || DEV_MAIN_ROOT="$DEV_PORTS_ROOT"
export DEV_MAIN_ROOT
export COMPOSE_FILE="${COMPOSE_FILE:-$DEV_MAIN_ROOT/docker-compose.yml}"

# A worktree shares the main checkout's dev database unless its branch changes
# migrations, committed or not. Then it gets a database of its own on the same
# server, and role names of its own since roles are cluster-wide, so its
# migrations never reach the database every other checkout runs on.
# scripts/dev-database.sh creates it; drop_test_dbs.py --orphaned drops it once
# the worktree is gone.
if [ "$DEV_CHECKOUT_ID" != main ] && [ -z "${DATABASE_NAME:-}" ]; then
    dev_base="$(git -C "$DEV_PORTS_ROOT" merge-base HEAD origin/dev 2>/dev/null || true)"
    if [ -n "$dev_base" ] && {
        [ -n "$(git -C "$DEV_PORTS_ROOT" diff --name-only "$dev_base" -- backend/alembic/versions)" ] ||
            [ -n "$(git -C "$DEV_PORTS_ROOT" ls-files --others --exclude-standard -- backend/alembic/versions)" ]
    }; then
        export DATABASE_NAME="initiative_dev_$DEV_CHECKOUT_ID"
        export GUILD_ROLE_PREFIX="dev_${DEV_CHECKOUT_ID}_"
        export PLATFORM_ROLE_PREFIX="dev_${DEV_CHECKOUT_ID}_"
    fi
fi

# Offsets are handed out by a small registry rather than derived from the path.
# A digest would have to collide eventually — across a few dozen worktrees over
# any range that keeps the ports tidy it is likelier than not — and two
# checkouts landing on the same ports is the exact thing this file exists to
# prevent. The registry gives each checkout the lowest free offset and remembers
# it, so a checkout keeps its ports for as long as it exists.
DEV_PORTS_REGISTRY="${DEV_PORTS_REGISTRY:-${XDG_CACHE_HOME:-$HOME/.cache}/initiative/dev-ports}"

# Print the offset already recorded for this checkout, if it has one. No lock:
# reading a line that is only ever appended under one is safe, and it keeps the
# routine path — every launch after the first — off the lock entirely.
_dev_ports_lookup() {
    local off path
    [ -f "$DEV_PORTS_REGISTRY" ] || return 1
    while IFS=$'\t' read -r off path; do
        if [ -n "$off" ] && [ "$path" = "$1" ]; then
            printf '%s' "$off"
            return 0
        fi
    done < "$DEV_PORTS_REGISTRY"
    return 1
}

# Print this checkout's offset, allocating one if it has none. Fails (no output)
# rather than guessing if the registry can't be used.
_dev_ports_allocate() {
    local root="$1" lock offset waited=0 off path
    local kept=() taken=()

    mkdir -p "$(dirname "$DEV_PORTS_REGISTRY")" 2>/dev/null || return 1
    lock="$DEV_PORTS_REGISTRY.lock"

    # mkdir either creates the directory or fails, atomically, which makes it a
    # lock on every platform — flock isn't on macOS by default.
    #
    # Nothing here ever takes a lock it doesn't own. Deciding a lock is stale and
    # removing it cannot be made atomic with mkdir: two waiters can reach that
    # conclusion together, and the second one deletes the lock the first has just
    # taken, putting both in this section choosing the same offset. Checking
    # ownership afterwards only narrows that window, it doesn't close it. So a
    # lock is only ever released by the process that created it, and a waiter
    # that runs out of patience gives up and says so.
    until mkdir "$lock" 2>/dev/null; do
        waited=$((waited + 1))
        if [ "$waited" -gt 100 ]; then
            return 1
        fi
        sleep 0.1
    done

    [ -f "$DEV_PORTS_REGISTRY" ] || : > "$DEV_PORTS_REGISTRY"
    while IFS=$'\t' read -r off path; do
        # Forget checkouts that have been deleted, so offsets stay small and
        # come back into use; a checkout that still exists keeps its ports even
        # while its dev environment is down.
        [ -n "$off" ] && [ -d "$path" ] || continue
        [ "$path" = "$root" ] && offset="$off"
        kept+=("$off	$path")
        taken+=("$off")
    done < "$DEV_PORTS_REGISTRY"

    if [ -z "${offset:-}" ]; then
        offset=1
        while printf '%s\n' "${taken[@]}" | grep -qx "$offset"; do
            offset=$((offset + 1))
        done
        kept+=("$offset	$root")
    fi

    printf '%s\n' "${kept[@]}" > "$DEV_PORTS_REGISTRY"
    rm -rf "$lock" 2>/dev/null
    printf '%s' "$offset"
}

if [ -n "${DEV_BACKEND_PORT:-}" ] && [ -n "${DEV_FRONTEND_PORT:-}" ]; then
    # Both pinned by hand, so there is nothing to allocate and no registry to
    # need — this is also the way out if the registry is unusable.
    DEV_PORT_OFFSET="${DEV_PORT_OFFSET:-0}"
elif [ "$DEV_CHECKOUT_ID" = main ]; then
    DEV_PORT_OFFSET=0
elif [ -z "${DEV_PORT_OFFSET:-}" ]; then
    DEV_PORT_OFFSET="$(_dev_ports_lookup "$DEV_PORTS_ROOT" || _dev_ports_allocate "$DEV_PORTS_ROOT" || true)"
fi

# There is deliberately no fallback. Deriving an offset from the path when the
# registry is unreachable is the collision this file exists to remove, and a
# port pair that might already be another checkout's is worse than no answer:
# the caller stops here instead, and says how to settle it.
if [ -z "${DEV_PORT_OFFSET:-}" ]; then
    echo "dev-ports: could not get a port offset for this checkout." >&2
    echo "  registry: $DEV_PORTS_REGISTRY" >&2
    echo "  Another checkout may be allocating right now — try again." >&2
    echo "  If none is, a run was killed while holding the lock; remove it:" >&2
    echo "    rm -rf $DEV_PORTS_REGISTRY.lock" >&2
    echo "  Or set DEV_BACKEND_PORT and DEV_FRONTEND_PORT to a pair no other" >&2
    echo "  checkout uses, which skips the registry entirely." >&2
fi

if [ -n "${DEV_PORT_OFFSET:-}" ]; then
    DEV_BACKEND_PORT="${DEV_BACKEND_PORT:-$((8000 + DEV_PORT_OFFSET))}"
    DEV_FRONTEND_PORT="${DEV_FRONTEND_PORT:-$((5173 + DEV_PORT_OFFSET))}"
fi

# Where the frontend reaches the backend. vite.config.ts reads
# VITE_DEV_PROXY_TARGET for its proxy; the SPA reads VITE_API_URL.
#
# The SPA's is RELATIVE, so every request it makes — REST and WebSocket alike —
# goes to the page's own origin and through Vite, which proxies `/api` with
# `ws: true`. An absolute one sends the SPA straight at the backend port and
# leaves that proxy unused, which is fine for REST and is not fine for a
# WebSocket: the upgrade has one more hop to survive, and a browser that cannot
# make it reports only that it could not connect.
#
# Anything outside the browser wants the absolute one and should use
# VITE_DEV_PROXY_TARGET, which is what it is for.
export VITE_DEV_PROXY_TARGET="${VITE_DEV_PROXY_TARGET:-http://localhost:${DEV_BACKEND_PORT}}"
export VITE_API_URL="${VITE_API_URL:-/api/v1}"
export VITE_DEV_PORT="$DEV_FRONTEND_PORT"

# One log per checkout, so two dev environments don't write over each other.
DEV_BACKEND_LOG="/tmp/initiative-${DEV_CHECKOUT_ID}-backend.log"
DEV_FRONTEND_LOG="/tmp/initiative-${DEV_CHECKOUT_ID}-frontend.log"
DEV_OPEN_LOG="/tmp/initiative-${DEV_CHECKOUT_ID}-open.log"

export DEV_CHECKOUT_ID DEV_PORT_OFFSET DEV_BACKEND_PORT DEV_FRONTEND_PORT
export DEV_BACKEND_LOG DEV_FRONTEND_LOG DEV_OPEN_LOG
