# Repository Guidelines

## Frontend dev

This project uses pnpm, not npm.

### Managing AI-Generated Planning Documents

AI assistants often create planning and design documents during development:

- PLAN.md, IMPLEMENTATION.md, ARCHITECTURE.md
- DESIGN.md, CODEBASE_SUMMARY.md, INTEGRATION_PLAN.md
- TESTING_GUIDE.md, TECHNICAL_DESIGN.md, and similar files

**Best Practice: Use a dedicated directory for these ephemeral files**

**Recommended approach:**

- Create a `history/` directory in the project root
- Store ALL AI-generated planning/design docs in `history/`
- Keep the repository root clean and focused on permanent project files
- Only access `history/` when explicitly asked to review past planning

**Example .gitignore entry (optional):**

```
# AI planning documents (ephemeral)
history/
```

**Benefits:**

- ✅ Clean repository root
- ✅ Clear separation between ephemeral and permanent documentation
- ✅ Easy to exclude from version control if desired
- ✅ Preserves planning history for archeological research
- ✅ Reduces noise when browsing the project

## Project Structure & Module Organization

`backend/` hosts the FastAPI service; routers sit in `app/api`, config in `core`, persistence helpers in `db`, domain models in `models`, payloads in `schemas`, and business logic in `services`, with `main.py` as the uvicorn entry point. `frontend/src` stays feature-first (`api`, `components`, `features`, `pages`, `hooks`, `lib`, `types`). Dockerfiles plus the root `docker-compose.yml` wire Postgres and the one image, whose uvicorn serves both the API and the built SPA. User-facing documentation is a Zensical static site under `docs/en/` (build/preview with `zensical build`/`serve`; see `docs/en/running-a-server/maintaining-these-docs.md`).

## Build, Test, and Development Commands

- `cd backend && uv sync` — create the `.venv` and install all runtime + dev deps from `uv.lock` ([uv](https://docs.astral.sh/uv/); `pyproject.toml` is the single source of truth, the lockfile pins exact versions).
- `cd backend && source .venv/bin/activate` — activate the synced env so bare `pytest`/`alembic`/`uvicorn`/`ruff` work, or prefix one-offs with `uv run` (e.g. `uv run pytest`).
- `cd backend && uvicorn app.main:app --reload` — run the API on http://localhost:8000.
- `cd backend && alembic upgrade head` — apply the latest database migrations (or run `python -m app.db.init_db` to migrate plus seed defaults).
- `cd backend && alembic revision --autogenerate -m "desc"` — generate a migration after SQLModel changes.
- `cd frontend && pnpm install && pnpm dev` — launch the Vite dev server (uses `VITE_API_URL`, defaults to `http://localhost:8000/api/v1`).
- `.mcp.json` gives agents a `browser` MCP server: `@playwright/mcp`, pinned in `frontend` devDependencies to the release built on the same Playwright minor as `@playwright/test`, running headless on the Chromium `pnpm exec playwright install chromium` downloads (no Google Chrome needed). `frontend/src/__tests__/playwrightMcp.test.ts` fails when the two drift apart; bump them together.
- `docker-compose up --build` — start Postgres 17 and the app image (API and SPA from one uvicorn).
- `cd backend && pytest` / `ruff check app` and `cd frontend && pnpm lint` — run tests and linters. Tests are co-located alongside source files in `app/` (not in a separate `tests/` directory).

## Generated API Types (Orval)

Frontend TypeScript types and React Query hooks in `frontend/src/api/generated/` are auto-generated from the backend's OpenAPI spec using Orval. **Do not hand-edit these files.**

- `frontend/src/types/api.ts` re-exports all generated types and adds backward-compatible aliases (e.g., `Task = TaskListRead`).
- Generated files are committed to the repo so the frontend builds without a running backend.

**After changing backend schemas** (`backend/app/schemas/`), regenerate:

```bash
# Option 1: With a running backend
cd frontend && pnpm generate:api

# Option 2: Without a running backend
cd backend && python scripts/export_openapi.py ../frontend/openapi.json
cd frontend && pnpm orval && pnpm biome format src/api/generated --write
```

Always commit the regenerated output. CI enforces this — the `check-generated-types` job will fail if generated files don't match the current backend schemas.

**Key files:**
- `frontend/orval.config.ts` — Orval configuration
- `frontend/src/api/mutator.ts` — Axios wrapper that preserves auth/guild interceptors
- `frontend/scripts/generate-api.sh` — Generation script (supports `--from-spec <path>` for CI)
- `backend/scripts/export_openapi.py` — Exports OpenAPI JSON without a running server

## Versioning

This project uses **semantic versioning** (semver) with a single source of truth: the `VERSION` file at the project root.

### How Versioning Works

- **Single source**: The `VERSION` file contains the current version (e.g., `0.1.0`)
- **Backend**: Reads VERSION file and exposes via `/api/v1/version` endpoint and OpenAPI schema
- **Frontend**: Vite injects VERSION as `__APP_VERSION__` constant, displayed in the sidebar footer
- **Docker**: VERSION is copied into the image and set as OCI labels

### Releasing a Version

Releases are managed by `scripts/promote.sh`, which creates a PR from `dev` to `main` with the version bump and changelog stamp. Only code owners (@jordandrako, @LeeJMorel) can run this script.

```bash
# Patch release (0.29.1 → 0.29.2)
./scripts/promote.sh --patch

# Minor release (0.29.1 → 0.30.0)
./scripts/promote.sh --minor

# Major release (0.29.1 → 1.0.0)
./scripts/promote.sh --major

# Preview without making changes
./scripts/promote.sh --dry-run
```

After the release PR merges to `main`, `tag-release.yml` auto-creates the version tag, which triggers the Docker build and GitHub Release.

### Semantic Versioning Guidelines

- **MAJOR** (1.0.0): Breaking changes, incompatible API changes
- **MINOR** (0.2.0): New features, backward-compatible additions
- **PATCH** (0.1.1): Bug fixes, backward-compatible fixes

### Changelog Maintenance

**IMPORTANT**: Always update `CHANGELOG.md` when making significant changes.

**Determining where to add changes:**

1. Check git log for recent "bump version to X.Y.Z" commits
2. If that version exists, it's already released
3. Add your changes to an `[Unreleased]` section at the top of the changelog
4. When the version is bumped, the unreleased section becomes the new version

**Example workflow:**

```bash
# Check recent history
git log --oneline --grep="bump version" -n 1

# If output shows "bump version to 0.7.2"
# Then 0.7.2 is released, add changes to [Unreleased]
```

**Changelog format:**

```markdown
## [Unreleased]

### Added

- New features go here

### Changed

- Modifications to existing features

### Fixed

- Bug fixes

## [0.7.2] - 2026-01-12

...existing released versions...
```

**Rules:**

- ✅ Update changelog for all feature additions, breaking changes, and bug fixes
- ✅ Update the changelog **before** creating a PR, not after
- ✅ Use `[Unreleased]` section if the current VERSION has already been tagged
- ✅ Keep entries concise and user-focused
- ❌ Do NOT add changelog entries for minor refactoring or internal changes
- ❌ Do NOT put new changes under an already-released version number

#### Screenshots

A change people will want to see can carry a picture, shown under its bullet
in the version dialog and on **What's new**, in light or dark to match the app.

1. Add a shot in `frontend/e2e/shots/<name>.shot.ts`: walk to the screen, then
   `await shoot(page, "<name>")` (or `shoot(page, "<name>", locator)` for one
   part of it). `gantt.shot.ts` is the example; `barovia.ts` walks to the
   seed's best-filled project.
2. With the dev environment running on its seed data, run
   `cd frontend && pnpm screenshots` (or `pnpm screenshots e2e/shots/<name>.shot.ts`).
   It signs in as `admin1@example.com` and writes
   `docs/images/releases/<name>.webp` and `<name>.dark.webp`.
3. Look them over, then put the picture under its bullet, by its repository path
   so GitHub draws it too:
   `![What it shows](docs/images/releases/<name>.webp)`.
   Several pictures on consecutive lines under one bullet become a strip that
   scrolls sideways, each opening in the lightbox.

The pictures live with the help center, so GitHub Pages publishes them when the
release reaches `main` and the app loads them from there
(`frontend/src/lib/releaseImages.ts`); no install or app update carries them.
Name a picture for what it shows, not the release; a name already used would
replace a released picture. `releaseImages.test.ts` fails when a picture the
changelog names is missing either theme or its alt text.

### Docker Builds with Specific Versions

Build Docker images with version labels:

```bash
export VERSION=$(cat VERSION)
docker-compose build --build-arg VERSION=$VERSION
```

The version will be included as OCI image labels and available in the container.

## Internationalization (i18n)

All user-facing strings must be externalized for localization. **Never hardcode user-visible text in components or API error responses.**

### Frontend: react-i18next

Translation files live in `frontend/public/locales/en/<namespace>.json`. The app uses `i18next-http-backend` to lazy-load namespaces on first use.

**Namespaces**: `common`, `auth`, `nav`, `projects`, `tasks`, `documents`, `initiatives`, `settings`, `tags`, `guilds`, `import`, `notifications`, `stats`, `landing`, `errors`, `dates`, `access`, `command`, `counters`, `dashboard`, `events`, `properties`, `queues`, `trash`

**Rules:**

1. **Use `useTranslation` in components** — call `const { t } = useTranslation("<namespace>")` and replace all hardcoded strings with `t("key")`.
2. **Cross-namespace references** use the `namespace:key` syntax — e.g., `t("common:loading")` from within a component using the `auth` namespace.
3. **Interpolation** uses `{{variable}}` syntax in JSON — `t("register.joiningGuild", { guildName })` maps to `"You're joining {{guildName}}."`.
4. **Plurals** use `_one`/`_other` suffixes in JSON — `{ "tasksArchived_one": "{{count}} task archived", "tasksArchived_other": "{{count}} tasks archived" }`.
5. **API error handling** — use `getErrorMessage(error, "namespace:fallbackKey")` from `@/lib/errorMessage` instead of displaying raw `detail` strings. This maps backend error codes to localized messages via `errors.json`.
6. **Utility functions outside React** — pass the `t` function as a parameter: `export const getLabel = (value: string, t: TFunction) => t(\`dates:status.${value}\`)`.
7. **Add new keys** to the appropriate namespace JSON file when adding new UI text. Keep keys organized with dot-notation grouping (e.g., `login.title`, `login.subtitle`).

```tsx
// Component pattern
const { t } = useTranslation("projects");
<CardTitle>{t("createProject.title")}</CardTitle>
<Input placeholder={t("createProject.namePlaceholder")} />
<Button>{submitting ? t("common:submitting") : t("common:save")}</Button>

// Error handling pattern
import { getErrorMessage } from "@/lib/errorMessage";
setError(getErrorMessage(err, "projects:createProject.error"));

// Toast pattern
toast.success(t("projects:projectCreated"));
```

### Backend: Error code constants

All `HTTPException` detail strings must use constants from `backend/app/core/messages.py` instead of inline strings. These constants are machine-readable codes (e.g., `EMAIL_ALREADY_REGISTERED`) that the frontend maps to localized messages.

**Rules:**

1. **Add new constants** to the appropriate class in `messages.py` (`AuthMessages`, `GuildMessages`, `OidcMessages`, or create new classes as needed).
2. **Use constants in HTTPException** — `raise HTTPException(status_code=400, detail=AuthMessages.INCORRECT_CREDENTIALS)`.
3. **Map codes in `errors.json`** — add a corresponding entry in `frontend/public/locales/en/errors.json` so the frontend can display a localized message.
4. **Tests assert on constants** — use `assert response.json()["detail"] == "EMAIL_ALREADY_REGISTERED"`, not substring matching on human-readable text.

## Coding Style & Naming Conventions

Python uses 4-space indentation, full type hints, `snake_case` modules/functions, and `PascalCase` SQLModel or schema classes; keep routing thin and push validation to `schemas` and `services`. React components are `PascalCase` files, hooks follow the `useThing` convention, and shared helpers live in `frontend/src/lib` or `api`. Ruff and ESLint must pass before opening a PR.

## Testing Guidelines

Tests are co-located next to their source files using a `_test.py` suffix (e.g., `app/services/guilds_test.py` tests `app/services/guilds.py`). Shared test factories live in `app/testing/factories.py` and are re-exported from `app/testing/__init__.py`. The root `backend/conftest.py` provides session, client, and auth fixtures. Run all tests with `cd backend && pytest` (testpaths is set to `app` in `pytest.ini`). For new UI logic, add Vitest + Testing Library specs under the relevant feature folder (or `frontend/src/__tests__`); prioritize coverage for auth, project CRUD, and optimistic updates.

### Running Tests

```bash
# Run all backend tests
cd backend && pytest

# Run tests for a specific module
cd backend && pytest app/services/guilds_test.py

# Run tests for a whole directory
cd backend && pytest app/api/v1/endpoints/

# Run tests for files you've changed (vs dev)
cd backend && ./scripts/test-changed.sh

# Run tests for staged files only
cd backend && ./scripts/test-changed.sh --staged

# Run all frontend tests
cd frontend && pnpm test:run

# Run frontend tests in watch mode
cd frontend && pnpm test

# Run frontend tests for files you've changed (vs dev)
cd frontend && ./scripts/test-changed.sh

# Run frontend tests for staged files only
cd frontend && ./scripts/test-changed.sh --staged
```

### Test Factories

Both backend and frontend provide factory functions for creating test data with sensible defaults. Always use these instead of hand-crafting test objects.

**Backend factories** live in `app/testing/factories.py` and are re-exported from `app/testing/__init__.py`. They are async functions that persist models to the test database and accept keyword overrides for any field.

Available factories:
- `create_user(session, **overrides)` — creates a `User` with unique email, hashed password, and default notification preferences
- `create_guild(session, creator=None, **overrides)` — creates a `Guild`; auto-creates a creator user if not provided
- `create_guild_membership(session, user=None, guild=None, role=GuildRole.member)` — links a user to a guild
- `create_initiative(session, guild, creator, **overrides)` — creates an `Initiative` with built-in roles and adds the creator as project manager
- `create_initiative_member(session, initiative, user, role_name="member")` — adds a user to an initiative with proper role lookup
- `create_project(session, initiative, owner, **overrides)` — creates a `Project` with owner permission

Auth helpers:
- `get_auth_token(user)` — returns a JWT string for the user
- `get_auth_headers(user)` — returns `{"Authorization": "Bearer <token>"}` dict
- `get_guild_headers(session, guild, user)` — async; wraps `get_auth_headers` (guild context is path-based now, so it writes no state). Address the guild in the URL, e.g. `/api/v1/c/{guild.id}/initiatives/`

```python
from app.testing import create_user, create_guild, create_guild_membership, get_guild_headers
from app.models.guild import GuildRole

async def test_something(session, client):
    user = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, creator=user)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)
    headers = await get_guild_headers(session, guild, user)
    response = await client.get(f"/api/v1/c/{guild.id}/initiatives/", headers=headers)
    assert response.status_code == 200
```

**Frontend factories** live in `src/__tests__/factories/` and are pure functions that return typed API response objects. They use auto-incrementing IDs and accept partial overrides via a spread pattern.

Available factories:
- `buildUser(overrides?)` / `buildUserPublic(overrides?)` / `buildUserGuildMember(overrides?)` — user objects at different detail levels
- `buildGuild(overrides?)` / `buildGuildInviteStatus(overrides?)` — guild and invite objects
- `buildInitiative(overrides?)` / `buildInitiativeMember(overrides?)` — initiative objects
- `buildProject(overrides?)` / `buildProjectPermission(overrides?)` — project objects
- `buildProjectTaskStatus(overrides?)` / `buildDefaultTaskStatuses(projectId?)` — task status objects (the latter returns all four default statuses)
- `buildTask(overrides?)` / `buildTaskListResponse(items?)` / `buildTaskAssignee(overrides?)` — task objects
- `buildTag(overrides?)` / `buildTagSummary(overrides?)` — tag objects
- `buildDocumentSummary(overrides?)` — document objects
- `buildComment(overrides?)` — comment objects
- `buildNotification(overrides?)` — notification objects
- `resetFactories()` — resets all ID counters (called automatically in test setup)

```typescript
import { buildUser, buildGuild, buildProject, buildTask } from "@/__tests__/factories";

const user = buildUser({ full_name: "Alice" });
const guild = buildGuild({ role: "admin" });
const project = buildProject({ owner_id: user.id, name: "My Project" });
const task = buildTask({ project_id: project.id, priority: "high" });
```

Frontend tests also use MSW (Mock Service Worker) handlers in `src/__tests__/helpers/handlers/` to mock API responses, and custom render helpers (`renderWithProviders`, `renderPage`) from `src/__tests__/helpers/render.tsx`.

## Commit & Pull Request Guidelines

History favors short subjects (e.g., `MVP WIP 1`), so keep the first line imperative, ≤50 chars, and use additional lines for detail. Do not mention coding agents in commit messages. Separate backend, frontend, and infra changes when practical. PRs must describe the problem, list notable changes, call out schema or env updates, and attach screenshots/GIFs for UI tweaks plus the exact commands you ran for testing. **PRs must target the `dev` branch**, not `main`.

## Security & Configuration Tips

Copy `backend/.env.example`, set `DATABASE_URL`, `SECRET_KEY`, and optional `FIRST_OWNER_*`, then run `alembic upgrade head` (or `python -m app.db.init_db`) so the schema is current and default settings/owner are seeded. The SPA reads `VITE_API_URL`; align it with the reverse-proxy host in every environment. If enabling OIDC, ensure `APP_URL` is publicly reachable so computed callback URLs stay valid.

## Tenancy, Database Architecture & RLS

Tenancy is enforced in Postgres, not just app code. See **CLAUDE.md → "Tenancy, Database Architecture & RLS"** for the authoritative full detail. Key facts:

- **Schema-per-guild.** Each guild's content lives in its own `guild_<id>` schema; shared identity/config lives in `public`. Isolation = the schema boundary + per-request `SET ROLE`.
- **Three logins:** `app_user` (RLS-enforced request path), `app_admin` (the **only** BYPASSRLS role — jobs/seeding/bootstrapping), `app_provisioner` (migrations + provisioning, not a superuser). `DATABASE_URL` alone is the database owner and the app derives all three (see CLAUDE.md); `DATABASE_URL_APP`/`_ADMIN` name them explicitly. No standing all-guild bypass on the request path; `app.is_superadmin` is retired from it.
- **Guild context is path-based:** guild requests are addressed as `/c/{guild_id}/…`. There is **no `X-Guild-ID` header and no `users.active_guild_id`** (both removed). Cross-guild "my" views are `/api/v1/me/*`.
- **Initiative-member RLS** on guild content defers to one function, `public.initiative_access(initiative_id, user_id, need_write)` (member OR guild admin OR PAM). A non-member sees **404** (row hidden), not 403. The structural initiative tables are guild-scoped only (not initiative-gated).
- **Cross-guild access** (PAM / break-glass) is time-bound, per-guild, and audited — never a standing bypass.

### Session Types (choose the right one)

| Session Dep | Engine / role assumed | When to use |
|---|---|---|
| `RLSSessionDep` (`get_guild_session`) | `app_user` → `SET ROLE guild_<id>`/`_ro` | Guild-scoped data under `/c/{guild_id}/…`. Pair with `GuildContextDep`. |
| `UserSessionDep` (`get_user_session`) | `app_user` → `platform_<tier>` | Authenticated cross-guild/platform reads with no guild (`/me/*`, list/reorder/leave guilds). |
| `SystemSessionDep` (`get_system_session`) | `app_admin` (**BYPASSRLS**) | Bootstrapping (create guild, accept invite), platform user/access-grant mgmt, background jobs, seeding. |
| `SessionDep` (`get_session`) | `app_user`, login role | Unauthenticated, or handlers that call `set_rls_context()` themselves after validating. |

### Rules for writing backend endpoints

1. **Default to `RLSSessionDep`** (+ `GuildContextDep`) for any guild-scoped data; the guild comes from the `/c/{guild_id}` path. Never use `SessionDep` for guild-scoped data.
2. **After every `session.commit()` followed by a query** (incl. `session.refresh()`), call `await reapply_rls_context(session)` — a commit may release the connection back to the pool.
3. **Use `UserSessionDep`** for authenticated cross-guild/platform reads; reserve `SystemSessionDep` (BYPASSRLS) for bootstrapping/lifecycle/jobs that can't run under a scoped role.
4. **Gate platform endpoints on `require_capability(...)`** — never reintroduce a request-path `is_superadmin`.
5. **`set_rls_context()` uses `set_config()`** so the assumed role/GUCs land on the same pooled connection as subsequent queries.

### Adding or changing tables

The path depends on where the table lives:

1. **Guild-scoped (content) table** — add/modify the SQLModel + autogenerate the migration, then do **both**: regenerate the guild schema (`python scripts/gen_guild_schema.py`), and classify it for initiative RLS in **one** place — either *initiative-scoped* via an entry in `INITIATIVE_PATHS` in `app/db/initiative_rls.py` (then `python scripts/gen_guild_rls.py` to regenerate `guild_rls.sql`), or *guild-level* via `GUILD_LEVEL_TABLES` in `app/db/tenancy.py`. CI fails if a new table is in neither bucket, or if the committed `guild_rls.sql` drifts from the generator. Content tables do **not** get the old `guild_isolation`/`is_superadmin` policies.
2. **Shared/platform table in `public`** (identity/config) — Alembic migration with `ENABLE` + `FORCE ROW LEVEL SECURITY` and role-scoped `TO platform_<tier>` policies + own-row predicates; gate the endpoints on the matching capability.
3. **Renaming/dropping** — `DROP POLICY IF EXISTS …` and `DISABLE ROW LEVEL SECURITY` before the DDL; always provide a clean downgrade.
4. **Verify** as `app_user` (not the superuser): for guild content, `SET ROLE guild_<id>` and confirm only that guild's schema is reachable. A missing policy silently returns zero rows; a wrong one leaks.

### Rules for writing frontend code

1. **React Query cache keys for the same data must match across components.** If the sidebar uses `["initiatives", guildId]` and a page uses `["initiatives", { guildId }]`, invalidation from one won't reach the other. Use prefix invalidation (`queryKey: ["initiatives"]`) when mutations should refresh all consumers.
2. **Guild context is in the URL path, not server-held.** Every guild-scoped request addresses its guild as `/api/v1/c/{guildId}/…`; there is no `X-Guild-ID` header and no server-held active guild (the `users.active_guild_id` column was removed). `useActiveGuildId()` derives the guild from the route; cross-guild "my" views call `/api/v1/me/*`.
3. **Never use `localStorage` directly.** Import `getItem`, `setItem`, `removeItem` from `@/lib/storage` instead. The storage module uses an in-memory cache backed by Capacitor Preferences on native (preventing data loss when the OS clears localStorage) and delegates to localStorage on web. `initStorage()` hydrates the cache before React renders, so all reads are synchronous.

## Guild Architecture Notes

- Guilds are the primary tenancy boundary; users can join many. The active guild is **addressed in the URL path** (`/c/{guild_id}/…`) — there is no server-held active guild (`users.active_guild_id` was removed) and no `X-Guild-ID` header. `GuildContextDep`/`RLSSessionDep` resolve the guild from the path and re-validate membership (or a live PAM/break-glass grant) per request; a forged/stale path fails closed (403). Cross-guild "my" views are `/api/v1/me/*`.
- Guild membership has two roles (`admin`, `member`). Guild admins own memberships, invites, initiative/project config, and can delete their guild. A guild admin sees the whole guild via the `current_guild_role='admin'` RLS leg, not a bypass.
- **Platform roles are a 5-rung ladder** (`member → support → moderator → operator → owner`, stored in `users.role`) resolved to capabilities in `backend/app/core/capabilities.py`. Gate platform endpoints on a capability via `require_capability(...)`, not a role name. App-wide config (OIDC, SMTP, branding, role labels, platform AI) requires `config.manage` (owner-only); the first/bootstrap user becomes `owner`. Never leave the platform without a `config.manage` holder.
- The platform rule `community_creation_enabled` (seeded once from `DISABLE_GUILD_CREATION`) governs community creation: off, POST `/communities/` returns 403 without `communities.manage` and the SPA hides “Create community” affordances.
- Every new guild **provisions its `guild_<id>` schema + per-guild roles**, seeds its settings row + mandatory plug-ins, and makes the creator a guild admin. It gets **no initiative** — the owner names the first one from the guild home's empty state. Guild deletion must drop the schema + roles and clean up the shared rows that cascade off `public.guilds`.

## Docker Deployment

This project uses GitHub Actions to automatically build and publish Docker images to the GitHub Container Registry (`ghcr.io/beyonders-studio/initiative`).

### How It Works

- **Automatic builds**: Triggered when you push version tags (e.g., `v0.1.1`)
- **Multi-arch support**: Builds for both `linux/amd64` and `linux/arm64` (Apple Silicon)
- **Multiple tags**: Creates `latest`, `1`, `1.2`, and `1.2.3` tags for flexibility
- **Version injection**: Builds Docker images with the correct VERSION from tags

### Setup Requirements

No registry secrets: the workflows push with their own `GITHUB_TOKEN` (`packages: write`). See `.github/DOCKER_SETUP.md`; after the package's first push, set its visibility to public once so anyone can pull it.

### Deployment Workflow

The typical deployment process:

```bash
# 1. Create a release PR (bumps version + stamps changelog)
./scripts/promote.sh --patch   # or --minor / --major

# 2. Merge the release PR on GitHub

# 3. tag-release.yml auto-creates the version tag
#    docker-publish.yml builds, publishes, and notifies

# 4. Verify on GHCR
# Check: https://github.com/beyonders-studio/initiative/pkgs/container/initiative
```

The GitHub Actions workflow will:

- Build the Docker image with the new version
- Tag it appropriately (e.g., `latest`, `0.1`, `0.1.1`)
- Push to GHCR
- Support both x86_64 and ARM architectures

### Using Published Images

The easiest way to get started is with docker-compose:

```bash
# Copy the example configuration
cp docker-compose.example.yml docker-compose.yml

# Update SECRET_KEY and other settings as needed
nano docker-compose.yml

# Start the application
docker-compose up -d
```

This will:

- Pull the latest image from GHCR (`ghcr.io/beyonders-studio/initiative:latest`)
- Start PostgreSQL 17 database
- Configure automatic restarts and health checks
- Mount persistent volumes for uploads

Or pull and run manually:

```bash
docker pull ghcr.io/beyonders-studio/initiative:latest
docker pull ghcr.io/beyonders-studio/initiative:0.1.1  # specific version
```

### Manual Deployment

To trigger a build without a version tag:

1. Go to GitHub Actions → "Build and Push Docker Image"
2. Click "Run workflow"
3. Optionally specify a custom tag

### Important Notes

- Images include the VERSION file and expose version via `/api/v1/version`
- Frontend version checking will detect new deployments automatically
- Builds use GitHub Actions cache for faster subsequent builds
- Both backend and frontend are bundled in a single image

## Landing the Plane (Session Completion)

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**

- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
