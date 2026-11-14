# Contributing to Initiative

Thanks for your interest in contributing! This guide covers what you need to know as a developer working on the codebase.

## Getting Set Up

### One Command (Recommended)

You need Docker, [uv](https://docs.astral.sh/uv/) and Node.js 26.12.1+ with pnpm (`corepack enable pnpm`). From a clone, run:

```bash
bash scripts/dev-pre-launch.sh
```

It says what's missing if anything is, then:
- Writes `backend/.env` from `backend/.env.example` with a key of its own, the first time
- Starts PostgreSQL in Docker (`docker-compose.dev.yml`)
- Runs migrations and creates the dev owner (`admin@example.com` / `changeme`)
- Seeds TTRPG-themed test data (campaigns, quests, NPCs, files, tags)
- Starts the backend (uvicorn) and frontend (Vite) dev servers
- Opens the app in your browser

Press Ctrl+C to stop it; that also removes the seeded data. If something else already listens on port 5432, run it the first time as `POSTGRES_PORT=5433 bash scripts/dev-pre-launch.sh`; later runs use the port in `backend/.env`.

In VS Code, the **Dev Environment** launch configuration (F5) starts the same environment under the debugger, and stopping the debug session cleans up the same way.

**Seeded logins** — every account below uses the password **`changeme`**:

| Accounts | Role |
|----------|------|
| `admin1@example.com` … `admin4@example.com` | Dedicated **guild admins** (platform tier: member) |
| `user1@example.com` … `user8@example.com` | Regular **guild members** (never guild admins) |
| `owner@` · `operator@` · `moderator@` · `support@` · `member@example.com` | One user per **platform-role** tier, for exercising the privilege ladder |

### Manual Setup

If you prefer not to use VS Code tasks, you can start each service by hand.

#### Prerequisites

- Python 3.14 and [uv](https://docs.astral.sh/uv/)
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

# Start development server
pnpm dev
# Frontend available at http://localhost:5173
```

`backend/.env.example` lists every setting; [Configuration](https://beyonders-studio.github.io/initiative/en/running-a-server/configuration/) explains them.

## Working in the Code

[AGENTS.md](AGENTS.md) is the guide to the code for people and coding agents alike: layout, commands, tests, generated API types, migrations, and the rules each part follows. `scripts/ci/check` runs the checks CI runs; the pre-push hook runs it for you.

## Testing the Android App Against `dev`

The published app only installs updates signed with the release key, so it stays put on a server running the `dev` image. Use the dev app instead:

1. Download the latest `initiative-dev-apk` artifact from the [Dev App](https://github.com/beyonders-studio/initiative/actions/workflows/dev-app.yml) workflow and install it. It installs beside the published app as **Initiative Dev**.
2. Point it at a server running the `dev` (or `dev-<sha>`) image. Every push to `dev` then reaches it over the air.

Install a newer dev APK when `dev` changes native code (a Capacitor plugin, anything under `frontend/android`), since an update can only swap web assets. The two apps share the `initiative://` sign-in link, so Android asks which one to open it with.

## Submitting Changes

**Agree the shape before you build something new.** A change that adds a new kind of thing (a new option on a model, an enum value, a table, a setting) starts as an issue, and the pull request follows once a maintainer has agreed how it should work.

1. Fork the repo and create a branch from **`dev`**
2. Make your changes
3. Ensure tests and linters pass
4. Keep commits focused — separate backend, frontend, and infra changes when practical
5. Open a pull request **targeting `dev`** describing what changed and why
6. Include screenshots or GIFs for UI changes

**Actions in your fork.** With Actions turned on in a fork, nothing there runs on its own: pushes to the fork's `main` and `dev` and the scheduled runs check nothing, and the workflows that publish images, apps, docs or releases skip. A pull request inside your fork runs CI as it would here, and you can start the nightly (browser journeys included) or the security scan by hand. Your pull request to this repository runs every check it needs here. The checks live in the workflows, so they reach your fork when you sync it; scheduled runs read them from its default branch, so sync that one too if it isn't `dev`.

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

When a `release/v*` PR merges to `main`, **tag-release.yml** creates the `vX.Y.Z` tag. The tag push triggers **docker-publish.yml**, which publishes the image `release-candidate.yml` built and checked for that tree (building and checking one if there is none), attaches the Android APK or desktop installers when `MIN_NATIVE_VERSION` or `MIN_DESKTOP_VERSION` moved, creates the GitHub Release and sends a Discord notification. No manual tagging is required.

**Retiring the app update key.** The owners hold a backup key offline, which every installed app already trusts. To retire the release key, set `OTA_SIGNING_KEY` in the `ota-release` environment to the backup private key, then ship an app update whose `frontend/src/lib/otaTrust.ts` replaces the retired public key with a new backup. No APK is needed, and servers do nothing.

## Mobile App Development

The frontend includes Capacitor for native iOS and Android apps:

```bash
# Start the backend so Capacitor apps can connect
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Build the web app and sync to native projects
cd frontend
pnpm build:capacitor
pnpm exec cap sync

# Open in Android Studio
pnpm exec cap open android

# Open in Xcode (macOS only)
pnpm exec cap open ios
```

**Requirements:**
- Android: Android Studio with SDK installed
- iOS: Xcode on macOS

In the Android emulator the local backend is available at `http://10.0.2.2:8000`.

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
