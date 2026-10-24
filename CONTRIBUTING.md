# Contributing to Initiative

Thanks for your interest in contributing! This guide covers what you need to know as a developer working on the codebase.

## Getting Set Up

### One-Click Dev Environment (Recommended)

The project includes a VS Code task configuration that starts everything with a single command:

1. **Prerequisites**: Docker, Python 3.10+ venv at `backend/.venv/`, Node.js 26.12.1+ with pnpm, PostgreSQL client tools (`pg_isready`)
2. **Configure**: Copy `backend/.env.example` to `backend/.env` and set `DATABASE_URL` / `SECRET_KEY`
3. **Launch**: Open the VS Code Command Palette (`Ctrl+Shift+P`) and run **Tasks: Run Task** → **`dev:setup`**

This will:
- Start PostgreSQL via Docker
- Run migrations and create a dev superuser (`admin@example.com` / `changeme`)
- Seed TTRPG-themed test data (campaigns, quests, NPCs, files, tags)
- Start the backend (uvicorn) and frontend (Vite) dev servers
- Open the app in your browser

When you're done, run **`dev:cleanup`** from the task palette to remove all seeded test data. Stopping the debug session (if launched via F5) also triggers cleanup automatically.

**What gets seeded:**

A realistic, TTRPG-themed dataset that exercises the whole app. See `scripts/seed/` (one module per area, run in order by `scripts/seed_dev_data.py`) for the exact contents.

**Seeded logins** — every account below uses the password **`changeme`**:

| Accounts | Role |
|----------|------|
| `admin1@example.com` … `admin4@example.com` | Dedicated **guild admins** (platform tier: member) |
| `user1@example.com` … `user8@example.com` | Regular **guild members** (never guild admins) |
| `owner@` · `operator@` · `moderator@` · `support@` · `member@example.com` | One user per **platform-role** tier, for exercising the privilege ladder |

The bootstrap owner from your `.env` (`FIRST_OWNER_EMAIL`) is also available with its configured password.

The seeder records the accounts it created in `.vscode/.dev_seed_ids.json` (gitignored). Cleanup does not need it: it drops every community schema and wipes the shared rows.

### Manual Setup

If you prefer not to use VS Code tasks, you can start each service by hand.

#### Prerequisites

- Python 3.11+
- Node.js 26.12.1+ with pnpm
- PostgreSQL 17

#### Backend

```bash
cd backend

# Install uv if you don't have it (https://docs.astral.sh/uv/):
#   curl -LsSf https://astral.sh/uv/install.sh | sh

# Create the .venv and install all dependencies from the lockfile
uv sync
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Configure environment
cp .env.example .env
# Edit .env and set DATABASE_URL, SECRET_KEY, and other variables

# Run migrations and seed defaults
alembic upgrade head
# Or use: python -m app.db.init_db

# Start the API server
uvicorn app.main:app --reload
# API available at http://localhost:8000
# API docs at http://localhost:8000/api/v1/docs
```

#### Frontend

```bash
cd frontend

# Install dependencies
pnpm install

# Configure API URL (optional, defaults to http://localhost:8000/api/v1)
echo "VITE_API_URL=http://localhost:8000/api/v1" > .env

# Start development server
pnpm dev
# Frontend available at http://localhost:5173
```

See the [Key Environment Variables](./README.md#key-environment-variables) section in the README for full configuration options.

## Running Tests

```bash
# All backend tests
cd backend && pytest

# All frontend tests
cd frontend && pnpm test:run

# Only tests related to files you've changed (vs dev)
cd backend && ./scripts/test-changed.sh
cd frontend && ./scripts/test-changed.sh

# Only tests for staged files
cd backend && ./scripts/test-changed.sh --staged
cd frontend && ./scripts/test-changed.sh --staged
```

## Testing the Android App Against `dev`

The published app only installs updates signed with the release key, so it stays put on a server running the `dev` image. Use the dev app instead:

1. Download the latest `initiative-dev-apk` artifact from the [Dev App](https://github.com/beyonders-studio/initiative/actions/workflows/dev-app.yml) workflow and install it. It installs beside the published app as **Initiative Dev**.
2. Point it at a server running the `dev` (or `dev-<sha>`) image. Every push to `dev` then reaches it over the air.

Install a newer dev APK when `dev` changes native code (a Capacitor plugin, anything under `frontend/android`), since an update can only swap web assets. The two apps share the `initiative://` sign-in link, so Android asks which one to open it with.

The dev app and dev images trust the dev key (`.github/ota-dev-key.pub`); its private half is `OTA_SIGNING_KEY` in the `ota-dev` environment, beside the dev Android keystore. Both are released only to the `dev` branch. The published app never trusts the dev key.

## Code Style

- **Python**: 4-space indent, full type hints, `snake_case` functions, `PascalCase` models/schemas. Lint with `ruff check app`.
- **TypeScript/React**: `PascalCase` components, `useThing` hooks. Lint with `pnpm lint`.

Both linters must pass before merging.

## Project Layout

- `backend/app/api/` — FastAPI routers
- `backend/app/models/` — SQLModel domain models
- `backend/app/schemas/` — Request/response payloads
- `backend/app/services/` — Business logic
- `frontend/src/pages/` — Route-level React components
- `frontend/src/features/` — Feature-specific components and logic
- `frontend/src/hooks/` — Shared React hooks
- `frontend/src/api/` — API client and query hooks

Tests are co-located next to source files (`_test.py` for backend, `.test.ts` for frontend). Shared test factories live in `backend/app/testing/` and `frontend/src/__tests__/factories/`.

## Generated API Types

Frontend TypeScript types and React Query hooks are auto-generated from the backend's OpenAPI spec using [Orval](https://orval.dev). The generated files live in `frontend/src/api/generated/` and are committed to the repo.

**When you change backend schemas** (`backend/app/schemas/`), you must regenerate the frontend types:

```bash
# With the backend running locally:
cd frontend && pnpm generate:api

# Or without a running backend (export spec directly):
cd backend && python scripts/export_openapi.py ../frontend/openapi.json
cd frontend && pnpm orval
```

Commit the updated generated files alongside your schema changes. CI will fail if generated types are out of date.

**Important:** Do not hand-edit files in `frontend/src/api/generated/` — they will be overwritten on the next generation run.

**Breaking the API.** CI compares the API with the last release's and fails on a change that would break a client written against that release: a removed route or field, a newly required parameter, a narrower type. Run the same check with `scripts/ci/api-compat` (needs Docker and the GitHub CLI). If the break is intended, add the method, path and message it printed to [`backend/api-breaking-changes.md`](backend/api-breaking-changes.md) under the release it ships in, and say why in the pull request. Each release publishes its spec as `openapi.json` on its GitHub release.

## Submitting Changes

**Agree the shape before you build something new.** A change that adds a new kind of thing (a new option on a model, an enum value, a table, a setting) starts as an issue, and the pull request follows once a maintainer has agreed how it should work. Extend what's already there before adding something beside it: a new way for a task to repeat belongs in the existing repeat rules, not in a second schedule next to them.

1. Fork the repo and create a branch from **`dev`**
2. Make your changes
3. Ensure tests and linters pass
4. Keep commits focused — separate backend, frontend, and infra changes when practical
5. Open a pull request **targeting `dev`** describing what changed and why
6. Include screenshots or GIFs for UI changes

**Important:** Do not open PRs against `main`. The `main` branch is restricted to project maintainers (@jordandrako, @LeeJMorel) who promote changes from `dev` using the release tooling below. PRs targeting `main` from non-maintainers will be closed.

## Releases (Maintainers)

Only project maintainers (@jordandrako, @LeeJMorel) have admin access to `main`. All changes reach `main` through the promotion script — never by direct push or PR.

### Branching Model

| Branch | Purpose |
|--------|---------|
| `main` | Production — admin-only, every commit is deployable |
| `dev` | Integration — all feature work merges here via PR |
| `release/vX.Y.Z` | Release prep — version bump + changelog stamp, from `dev` or from a cherry-picked hotfix. This prefix is what triggers the tag and Docker build on merge |
| `promote/YYYY-MM-DD` | Code-only promotion (no version change) |
| `hotfix/YYYY-MM-DD` | Cherry-pick urgent fixes to main without a version bump |
| `rollback/vX.Y.Z` | Revert a bad release |

Contributors open PRs to `dev`. Maintainers promote `dev` to `main` when ready to release.

### Using `promote.sh`

The `scripts/promote.sh` script handles the full release lifecycle. It validates that the caller is a code owner before proceeding. Maintainers can also run it from **Actions → Release → Run workflow**, which asks a code owner to approve each run.

```bash
# Preview what would be promoted (safe, no side effects)
./scripts/promote.sh --dry-run

# Promote dev to main without a release
./scripts/promote.sh

# Create a patch release (0.29.1 → 0.29.2)
./scripts/promote.sh --patch

# Create a minor release (0.29.1 → 0.30.0)
./scripts/promote.sh --minor

# Cherry-pick a hotfix commit to main
./scripts/promote.sh --cherry-pick abc123

# Rollback the latest release
./scripts/promote.sh --rollback
```

### Post-Merge Automation

When a `release/v*` PR merges to `main`:

1. **tag-release.yml** extracts the version from the branch name and creates a `vX.Y.Z` tag
2. The tag push triggers **docker-publish.yml** which builds the Docker image, creates a GitHub Release with the Android APK, and sends a Discord notification

No manual tagging is required.

## Database Migrations

When modifying SQLModel classes:

```bash
cd backend

# Generate migration from model changes
alembic revision --autogenerate -m "Description of changes"

# Apply pending migrations
alembic upgrade head
```

## Mobile App Development

The frontend includes Capacitor for native iOS and Android apps:

```bash
# Start the backend so Capacitor apps can connect
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Build the web app and sync to native projects
cd frontend
pnpm build:capacitor
npx cap sync

# Open in Android Studio
npx cap open android

# Open in Xcode (macOS only)
npx cap open ios
```

**Requirements:**
- Android: Android Studio with SDK installed
- iOS: Xcode on macOS

In the Android emulator the local backend is available at `http://10.0.0.2:8000`.

## Desktop App Development

The desktop app is the same build running in Electron, through the [Capawesome Electron platform](https://github.com/capawesome-team/capacitor-electron). Its project lives in `frontend/electron/` and installs on its own, so installing the frontend never downloads Electron.

```bash
cd frontend
pnpm cap:desktop
```

That builds the web app, installs the Electron project, builds the app's own plugins (`frontend/electron/plugins/`), syncs and opens the app. It signs in like the phone app; a local backend is at `http://localhost:8000`.

After that, `pnpm --dir electron run build:installer` builds the installer for the computer you are on into `frontend/electron/dist/`. Releases build all three (Windows, macOS, Debian) in `.github/workflows/desktop-app.yml`, which also runs on pull requests that change `frontend/electron/`.

## Reporting Issues

Use the [issue templates](https://github.com/beyonders-studio/initiative/issues/new/choose) to file bug reports or feature requests.

## Security Vulnerabilities

Please **do not** open a public issue for security vulnerabilities. See [SECURITY.md](SECURITY.md) for responsible disclosure instructions.

## License

This repository is open source under the [AGPL-3.0](LICENSE). Morelitea LLC, doing business as Beyonders Studio, holds the copyright and full commercial rights. Initiative is open core — see [License](README.md#license) for what's open and what isn't.

Contributions are made under the [Contributor License Agreement](./CLA.md) (version 2), which grants Morelitea LLC, doing business as Beyonders Studio, the rights to your contribution, including the right to relicense it. You sign it once, on your first pull request: a CLA check comments asking you to, and you sign by posting this comment on the pull request:

```
I have read the CLA Document and I hereby sign the CLA
```

The check records your signature on this repository's `cla-signatures` branch and passes. Your later pull requests pass without asking again. If you contributed before version 2 (7 October 2026), signing it also covers those earlier contributions.
