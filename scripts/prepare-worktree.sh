#!/usr/bin/env bash
# Prepare a linked worktree: install its dependencies. Nothing is copied in: it
# reads the main checkout's backend/.env and runs on its Postgres (see
# scripts/dev-ports.sh and backend/app/core/config.py).
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
(cd backend && uv sync)
(cd frontend && pnpm install)
