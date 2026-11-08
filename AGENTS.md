# Repository Guidelines

## Frontend dev

This project uses pnpm, not npm.

### Planning and design documents

Keep AI-generated planning and design documents (PLAN.md, DESIGN.md and the like) in
`history/` at the repository root, which is gitignored, so the root holds only permanent
project files. Read `history/` only when asked to review past planning.

## Project Structure & Module Organization

`backend/` hosts the FastAPI service; routers sit in `app/api`, config in `core`, persistence helpers in `db`, domain models in `models`, payloads in `schemas`, and business logic in `services`, with `main.py` as the uvicorn entry point. `frontend/src` holds `pages` (laid out as the app's navigation), `components` (the app's chrome and what several pages share), `ui` (the UI kit), `routes` (the URLs), `hooks`, `lib`, `api` and `types`; frontend rule 8 says what goes where. The root `Dockerfile` builds the one image, whose uvicorn serves both the API and the built SPA; `docker-compose.example.yml` runs it beside Postgres. User-facing documentation is a Zensical static site under `docs/en/` (build/preview with `zensical build`/`serve`; see `docs/en/running-a-server/maintaining-these-docs.md`).

## Build, Test, and Development Commands

- `cd backend && uv sync` — create the `.venv` and install all runtime + dev deps from `uv.lock` ([uv](https://docs.astral.sh/uv/); `pyproject.toml` is the single source of truth, the lockfile pins exact versions).
- `cd backend && source .venv/bin/activate` — activate the synced env so bare `pytest`/`alembic`/`uvicorn`/`ruff` work, or prefix one-offs with `uv run` (e.g. `uv run pytest`).
- `cd backend && uvicorn app.main:app --reload` — run the API on http://localhost:8000.
- `cd backend && alembic upgrade head` — apply the latest database migrations (or run `python -m app.db.init_db` to migrate plus seed defaults).
- `cd backend && alembic revision --autogenerate -m "desc"` — generate a migration after SQLModel changes to **shared/`public` tables**. For **guild-content** tables use `python scripts/gen_guild_migration.py "desc"` instead (autogenerate against `guild_template` via `-x guild`; see "Adding or changing tables").
- `cd frontend && pnpm install && pnpm dev` — launch the Vite dev server (uses `VITE_API_URL`, defaults to `http://localhost:8000/api/v1`).
- `cd frontend && pnpm build:editor-server` — build the document editor the backend runs (`frontend/dist-editor/editor.js`, read by `app/services/editor_engine.py`). The image and CI build it; locally, the backend tests that use it fail until it is built.
- **Dev ports are per checkout.** The main working tree keeps `8000`/`5173`; each linked worktree gets the lowest free offset (`8001`/`5174`, `8002`/`5175`, …) and keeps it while it exists, so several checkouts can run a dev environment at once. `scripts/dev-ports.sh` is the single source of truth — every dev script sources it, and it exports `DEV_BACKEND_PORT`, `DEV_FRONTEND_PORT`, `VITE_API_URL`, `VITE_DEV_PROXY_TARGET` and per-checkout log paths. Pin a checkout by setting `DEV_BACKEND_PORT`/`DEV_FRONTEND_PORT` yourself. The VSCode "Dev Environment" debug config works in any worktree.
- **A linked worktree needs nothing copied in.** It reads the main checkout's `backend/.env`, tests included, then its own `backend/.env` on top if it has one, for whatever it is trying out (an OIDC provider, say; `app/core/config.py`). `dev-ports.sh` points it at the main checkout's compose file and Postgres. It shares the main checkout's dev database unless its branch changes migrations, committed or not: then it runs on a dev database of its own (`initiative_dev_<id>`, its roles prefixed `dev_<id>_`), which `dev-migrate` creates, migrates and the launch seeds, and `python scripts/drop_test_dbs.py --orphaned --yes` drops once the worktree is gone.
- `.mcp.json` gives agents a `browser` MCP server: `@playwright/mcp`, running headless on the Chromium `pnpm exec playwright install chromium` downloads (no Google Chrome needed).
- `cd backend && pytest app/services/guilds_test.py` — run the test files for the code you changed; CI runs the rest (see "Running Tests").
- `scripts/ci/check` — the fast checks CI runs (ruff, ruff format, ty, no merged migration edited, one Alembic head, biome, tsc, and generated-types / `env-contract.json` drift), for what the branch changed against `origin/dev`. CI calls the same script for those steps, and the husky pre-push hook runs it (`git push --no-verify` skips it once). No tests and no database. `scripts/ci/check all` runs everything; `scripts/ci/check codegen` regenerates drifted files for you to review and commit.
- `scripts/ci/api-compat` — whether the API still takes what the last release's did (oasdiff against the `openapi.json` that release's GitHub release carries; needs Docker and `gh`). CI runs it on pull requests. A break made on purpose is listed in `backend/api-breaking-changes.md`, under the release it ships in.

## Generated API Types (Orval)

Frontend TypeScript types and React Query hooks in `frontend/src/api/generated/` are auto-generated from the backend's OpenAPI spec using Orval. **Do not hand-edit these files.**

- Import types directly from `@/api/generated/initiativeAPI.schemas` (there is no re-export barrel).
- Generated files are committed to the repo so the frontend builds without a running backend.

**After changing backend schemas** (`backend/app/schemas/`), run `scripts/ci/check codegen` (or `cd frontend && pnpm generate:api`, which exports the spec itself when no backend is running) and commit the regenerated output; CI's `check-generated-types` job fails while it differs.

## Versioning

This project uses **semantic versioning** (semver) with a single source of truth: the `VERSION` file at the project root.

### `MIN_NATIVE_VERSION` (OTA native-compatibility floor)

The native (Capacitor) app receives web-bundle updates over the air: each Docker image ships the matching Capacitor bundle under `/app/ota`, served via `/api/v1/native/bundle/{manifest,download}`, and the app downloads it when the served version differs (see `useNativeUpdate`). The `MIN_NATIVE_VERSION` file at the project root is the **minimum native app (APK/IPA) version** the current web bundle requires — an OTA can only swap web assets, never native code.

- `scripts/promote.sh` bumps `MIN_NATIVE_VERSION` to the release version automatically when it detects a native change between `main` and `dev` (a `frontend/capacitor.config.ts` change, a committed change under `frontend/android`/`frontend/ios`, or an added/removed/bumped `@capacitor*`/`@capgo`/`@capawesome` plugin in `frontend/package.json`, other than the desktop app's `@capawesome/capacitor-electron`). Web-only releases leave it untouched.
- The app refuses a bundle whose `minNativeVersion` exceeds the installed native app version and prompts the user to update from the store/APK instead.
- **The desktop app has a floor of its own, `MIN_DESKTOP_VERSION`**, so a change to one app never makes the other's users reinstall (Obtainium and similar updaters install every new APK). `promote.sh` bumps it on a change under `frontend/electron` or to `@capawesome/capacitor-electron`. The signed statement carries it as `minDesktopVersion`, which the desktop app holds itself to; a statement without it falls back to `minNativeVersion`.
- **Every update the app installs is signed.** The image build signs a statement of the bundle (version, sha256, `minNativeVersion`) with the ECDSA P-256 key in the `ota-release` environment secret `OTA_SIGNING_KEY` (`frontend/scripts/sign-ota.mjs`, passed as the BuildKit secret `ota_signing_key`), and `/native/bundle/manifest` serves it. The app verifies it against the public keys in `frontend/src/lib/otaTrust.ts` (the release key, then an offline backup) and ignores an unsigned bundle, so local images never update the app.
  - **Dev images are signed with a separate dev key** (public half in `.github/ota-dev-key.pub`, baked in as `VITE_OTA_DEV_PUBLIC_KEY`). Only the dev app trusts it: `dev-app.yml` builds it as `studio.beyonders.initiative.dev` ("Initiative Dev"). See CONTRIBUTING.md.
  - **This key is the project's, not an operator's.** Unlike `SECRET_KEY`, which each deployment owns because it protects that deployment's own data, the update key vouches for code the project publishes to one app that talks to every server; a key held by each server would only prove what the server already sent.
- Edge case the detector can't see: a native-affecting change that lands **only** via `pnpm-lock.yaml` (no `package.json` range change). Release it with `scripts/promote.sh --force-native`.

### Releasing a Version

Code owners release with `scripts/promote.sh` or **Actions → Release**; see CONTRIBUTING.md, "Releases (Maintainers)".

### Changelog Maintenance

**IMPORTANT**: Always update `CHANGELOG.md` when making significant changes.

New entries go under `## [Unreleased]` at the top, never under a released version: `scripts/promote.sh` stamps that section with the version at release, and refuses to release while it is empty.

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
- ✅ Keep entries concise and user-focused
- ❌ Do NOT add changelog entries for minor refactoring or internal changes

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

### Announcements

The changelog is the record; an **announcement** is the interruption. It is a
dialog in front of somebody who did not ask for it, so the bar is "they have to
act, or they will be confused" — a breaking change, a setting that moved, a
feature nobody would find. Everything else belongs in the changelog only.

Two sources, one surface:

- **Authored** — written by an operator under Operator dashboard › Announcements
  (`announcements.manage`, operator and above). Use these for anything specific
  to one deployment ("we are upgrading on Sunday").
- **Compiled in** — declared in
  [`backend/app/core/builtin_announcements.py`](backend/app/core/builtin_announcements.py)
  and shipped with the release. Use these when *every* deployment needs to hear
  it and no operator would know to type it.

**Adding a built-in.** One entry in `BUILTIN_ANNOUNCEMENTS`, and nothing else.
The module's docstring has an example and the rules for its slug (permanent:
dismissals are recorded against it) and its pictures (static files in
`frontend/public/announcement-images/`, with alt text; `builtin_announcements_test`
checks both).

- `published_at` must be **at or before the release date**, or nobody sees it:
  a future date reads as scheduled.

**Choosing conditions.** Every one of these narrows the audience; the default
is "everybody, immediately", which is usually wrong for a notice worth shipping.

| Field | Use it when |
|---|---|
| `audience_accounts` | The notice is about a transition. `existing` for a change people lived through; `new` for an onboarding tip; `everyone` (default) for news that stands on its own. |
| `only_upgrading_from_below` | Built-ins only. Names the release the notice is about, so a fresh install — which was never on the old behaviour — is not told. Read from the deployment's recorded previous version. |
| `min_platform_role` | The thing that changed is behind a platform rung. (A capability would be more precise; that is not built yet.) |
| `guild_admins_only` | Only people who administer a community can act on it. |
| `trigger_route` | It explains a screen. The notice waits for a matching path (`*` one segment, `**` the rest) instead of queueing at sign-in. |
| `dismissals_required` | Missing it would cost somebody real work. Two or three, never more; it comes back until acknowledged that many times. |
| `expires_at` | It stops being true on a date. An end date retires it from the queue, and its bell line no longer opens it. |

**Announcement text is not translated.** Sections are markdown written once and
shown as-is — only the dialog's own chrome goes through i18n. Write in English
and keep it short.

**Seeing one locally.** The registry is read at import, so a new entry needs the
backend to reload. It then has to survive its own conditions: a built-in with
`only_upgrading_from_below` shows nothing on a dev database that has only ever
run one version, and one for `existing` accounts shows nothing to an account
created after its `published_at`.

## Internationalization (i18n)

All user-facing strings must be externalized for localization. **Never hardcode user-visible text in components or API error responses.**

### Frontend: react-i18next

Translation files live in `frontend/public/locales/en/<namespace>.json`. The app uses `i18next-http-backend` to lazy-load namespaces on first use.

Each tool owns the namespace named after its camel plural (`projects`, `files`, `counterGroups`, `calendars`, `dashboards`) — `lib/tools.test.ts` fails if one is missing. `communityHome` is the community front page, which is not a tool. `home` is the signed-in home page at `/` — its canvas, its starting layouts and its widgets. `comments` is the cross-tool comment surface (composer, thread, mention help); it is not owned by `files`. `editor` is the words of the kit's rich-text editor (`frontend/src/ui/editor`), which the plug-ins copy with the kit; it is not owned by `files` either. `layouts` is the words of the kit's layouts and their editor (`frontend/src/ui/layouts`), which lay out every tool's lists and item pages and which the plug-ins copy with the kit; it is not owned by `projects`. `ui` is the UI kit's own words (`frontend/src/ui`), which the plug-ins copy with the kit.

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

Python uses 4-space indentation, full type hints, `snake_case` modules/functions, and `PascalCase` SQLModel or schema classes; keep routing thin and push validation to `schemas` and `services`. React components are `PascalCase` files, hooks follow the `useThing` convention, and shared helpers live in `frontend/src/lib` or `api`. Ruff and Biome must pass before opening a PR.

**Extend before adding.** Before adding a strategy, enum value, column or service, find the mechanism that already does most of it and extend that: a task that repeats "after completion" is the existing `rolling` strategy, not a new one. A request or issue that names a shape (a stored timezone, a new mode) describes the need, not the design; when the existing mechanism covers it differently, say so instead of building the shape as written. A new kind of thing needs a maintainer's agreement on an issue first.

### Security-sensitive comments

**Do not write code comments that reference direct security issues** — specific vulnerabilities, exploit or bypass mechanisms, "without this an attacker could…" narratives, or step-by-step descriptions of how a control could be defeated. This source is public, so such comments are an attack-targeting surface: they hand an attacker a roadmap. Keep comments to **simple functional explanations** of what the code does and why, not how a protection works internally or how it could fail. Put exploit-level detail in the private issue tracker or a security doc, not inline.

## Testing Guidelines

Tests are co-located next to their source files using a `_test.py` suffix (e.g., `app/services/guilds_test.py` tests `app/services/guilds.py`). The root `backend/conftest.py` provides session, client, and auth fixtures. Locally, run the test files for the code you changed, by path, and leave the whole suite to CI: it runs the tests a change reaches on each pull request and every test on each push to `dev` (see "Which backend tests a pull request runs"). For new UI logic, add Vitest + Testing Library specs under the relevant feature folder (or `frontend/src/__tests__`); prioritize coverage for auth, project CRUD, and optimistic updates.

### Running Tests

Every test run gets its own Postgres database and its own set of cluster-global
roles, keyed on **(checkout, xdist worker)** — `initiative_test_<checkout>_<worker>`
and `test_<checkout>_<worker>_*` (see `backend/conftest.py`). Concurrent runs from
different worktrees therefore don't share a database or drop each other's roles.
Those databases persist so warm runs skip the migration; reclaim them with
`cd backend && python scripts/drop_test_dbs.py` (add `--yes` to actually drop,
`--orphaned` for those of checkouts that no longer exist — safe while others
test — or `--all` for every checkout's).

Parallelism is per invocation: pass `-n auto` for a big run; a single file runs
serially by default (`pytest.ini` says why). `-n auto` is capped by memory as
well as cores (`conftest.py`); `PYTEST_XDIST_AUTO_NUM_WORKERS` overrides it.

**Guild schemas are pooled per worker** (`app/testing/guild_pool.py`): a
finished test's guild schema is emptied and reused rather than dropped, and one
a test changed is rebuilt. A test *about* provisioning takes
`@pytest.mark.fresh_guild_schema`; `PYTEST_GUILD_POOL=0` turns the pool off
for a whole run, to rule it in or out when a failure looks order-dependent.
A test that leaves `guild_template` changed fails at teardown, because the
worker renders provisioning from the template once.

**Which backend tests a pull request runs.** The always-run core, then the
tests the change reaches ([pytest-testmon](https://testmon.org), from dev's
last full run). A change selection cannot see (migrations, `app/db/`, test
infrastructure, dependencies, CI) runs every test, as does every push to
`main` and `dev`; the run's summary page says which.

The **always-run core** is every test marked `always` (a file's
`pytestmark = pytest.mark.always`, or `@pytest.mark.always` on one test). Mark
a test `always` when it checks something across *every* table, route,
registry, capability or migration, scans the source tree for a pattern, or
reads a file outside `backend/`: selection only knows code a test has already
run, so a new file (a model, a route, a revision) or a frontend file reaches no
test until one of these catches it. Keep the core cheap: it runs on every pull
request.

**The nightly run** (`.github/workflows/nightly.yml`) varies what the gates
hold fixed: Postgres 16 and 18, `TZ=Pacific/Auckland` for both suites and a
German locale for the backend's (the frontend tests pin English in
`vitest.config.ts`, because the app formats in the browser's locale), and a
shuffled order (`pytest --shuffle=SEED`, the seed in the
run's header; `vitest --sequence.shuffle --sequence.seed=SEED`). A failed
night opens an issue labelled `nightly`. **A flaky test is quarantined, not
retried**: mark it `@pytest.mark.quarantine(issue=<number>, since="YYYY-MM-DD")`
and open the issue. Every run leaves it out except `pytest --quarantined`,
which the nightly runs and which fails once a quarantine is two weeks old: by
then the test is fixed or deleted (`app/testing/run_options.py`). It also
holds **what a community costs the database** (`pytest -m budget`,
`app/db/budgets_test.py`, deselected otherwise): its parsed policies' memory
per connection, the gates that read the standing staying `plpgsql`, and the
standing being read once a statement. Each is a count Postgres reports rather
than a time; when a change lowers one, lower its budget with it.

**The browser journeys** (`frontend/e2e/*.journey.ts`, Playwright, Chromium)
walk the paths a person takes through an image started from
`docker-compose.example.yml` as shipped: the first owner building a community
through to a task, and an invited member seeing only what they were let into.
`.github/workflows/journeys.yml` runs them on every push to `dev`, nightly, and
on a pull request labelled `journeys`. They need an empty database: the first
journey registers the first owner. No retries, as for every other test.

Coverage is **opt-in** (`pytest.ini` says why):

```bash
cd backend && pytest --cov=app --cov-config=.coveragerc --cov-report=term-missing --cov-branch
```

```bash
# Run tests for a specific module
cd backend && pytest app/services/guilds_test.py

# Single process — for a clean traceback or a debugger
cd backend && pytest -n 0 app/services/guilds_test.py

# Run tests for a whole directory
cd backend && pytest app/api/v1/tenant_endpoints/

# Run tests for files you've changed (vs dev); every test, with -n auto, when
# app/testing, app/models, app/core, app/db or a conftest.py changed
cd backend && ./scripts/test-changed.sh

# Run tests for staged files only
cd backend && ./scripts/test-changed.sh --staged

# Every backend test, as CI runs it on dev
cd backend && pytest -n auto

# The request-context seam's conformance suite (deselected by default; CI runs
# it on integration pushes and on pull requests that touch the seam)
cd backend && pytest -m seam app/db/seam_conformance_test.py

# Run one frontend test file
cd frontend && pnpm vitest run src/lib/backupPeek.test.ts

# Every frontend test, a worker per core
cd frontend && pnpm test:run

# The browser journeys (frontend/e2e/*.journey.ts) against a fresh install:
# start docker-compose.example.yml with the image to check, then
cd frontend && pnpm exec playwright install chromium && JOURNEYS_URL=http://localhost:8173 pnpm test:journeys

# Run frontend tests in watch mode
cd frontend && pnpm test

# Run frontend tests for files you've changed (vs dev); every test when
# src/lib, src/types, src/api or the shared test helpers changed
cd frontend && ./scripts/test-changed.sh

# Run frontend tests for staged files only
cd frontend && ./scripts/test-changed.sh --staged
```

### Test Factories

Both backend and frontend provide factory functions for creating test data with sensible defaults. Always use these instead of hand-crafting test objects.

**Backend factories** live in `app/testing/factories.py` and are re-exported from `app/testing/__init__.py`. They are async functions that persist models to the test database and accept keyword overrides for any field.

They are **schema-per-guild native**: tenant models (initiatives, projects, tasks, documents, counters, events, tags, uploads, …) exist only in per-guild Postgres schemas (`guild_<id>`), never in `public`. Every tenant factory routes the session to the right guild schema automatically (derived from its parent argument). Raw `session.add(<tenant model>)` in a test works when the row carries a `guild_id` or the session is already routed; an unroutable tenant write **raises** (fail-closed — see `app/testing/schema_harness.py`). For raw tenant *reads* on a fresh session, call `await route_session_to_guild(session, guild_id)` first.

The full set, with the auth helpers (`get_auth_headers`, …), is exported from `app/testing/__init__.py`.

**The role seam — `acting_user`** (fixture in `conftest.py`, backed by `app.testing.Actor`/`make_actor`): every endpoint test states its actor's platform and guild roles through this one seam and gets an `Actor` dataclass back. With the real-role `client` fixture the request then executes as the real `app_user` → `platform_<tier>`/`guild_<id>` roles — RLS enforced, like production.

```python
from app.models.platform.guild import CommunityRole

async def test_something(client, acting_user):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    # a.user / a.headers / a.guild / a.membership / a.initiative / a.project
    response = await client.get(a.g("/initiatives/"), headers=a.headers)
    assert response.status_code == 200

    # Second actor joining the same workspace at lower privilege:
    b = await acting_user(guild_role=CommunityRole.member, guild=a.guild,
                          initiative=a.initiative, initiative_role="member")
```

Platform role defaults: `owner` for public-path actors (`await acting_user()`), but `member` when `guild_role` is given — guild access must never depend on platform tier, and defaulting low keeps the suite proving that. Pass a platform tier explicitly (`await acting_user("support")`) to test platform ceilings. The superuser-backed `session` fixture is for setup/assertions only; `role_session` exercises the raw `app_user`/`app_admin` privilege boundary.

**Frontend factories** live in `src/__tests__/factories/` and are pure functions that return typed API response objects. They use auto-incrementing IDs and accept partial overrides via a spread pattern.

The full set is exported from `src/__tests__/factories/index.ts`; `resetFactories()` runs before every test.

```typescript
import { buildUser, buildCommunity, buildProject, buildTask } from "@/__tests__/factories";

const user = buildUser({ full_name: "Alice" });
const community = buildCommunity({ role: "admin" });
const project = buildProject({ owner_id: user.id, name: "My Project" });
const task = buildTask({ project_id: project.id, priority: "high" });
```

Frontend tests also use MSW (Mock Service Worker) handlers in `src/__tests__/helpers/handlers/` to mock API responses, and custom render helpers (`renderWithProviders`, `renderPage`) from `src/__tests__/helpers/render.tsx`.

## Commit & Pull Request Guidelines

Keep the first line imperative, ≤50 chars, and use additional lines for detail. Do not mention coding agents in commit messages. Separate backend, frontend, and infra changes when practical. PRs must describe the problem, list notable changes, call out schema or env updates, and attach screenshots/GIFs for UI tweaks plus the exact commands you ran for testing. **PRs must target the `dev` branch**, not `main`. Work is finished when its branch is pushed and its pull request is open.

## Security & Configuration Tips

The app connects through **three Postgres logins**, all on one database (see "Three engines" below). The operator normally sets **one** URL: `DATABASE_URL` as the database **owner**, with `DATABASE_URL_APP`/`_ADMIN` unset. `Settings._resolve_database_logins` then derives the three logins (canonical names, passwords from `SECRET_KEY` via `derive_database_password`) and rewrites the settings into the explicit shape (`DATABASE_URL` = provisioner, `_APP`, `_ADMIN`, `_BOOTSTRAP` = owner), so code reading them never branches on the mode; `settings.database_logins_derived` says which was given. Setting `DATABASE_URL_APP` + `DATABASE_URL_ADMIN` selects the explicit shape instead (`DATABASE_URL` = `app_provisioner`, optional `DATABASE_URL_BOOTSTRAP` = owner): existing installs, poolers, out-of-band provisioning, and the test suite/CI. Either way the owner connection **creates** the three logins at startup — see [`app/db/bootstrap.py`](backend/app/db/bootstrap.py); it is opened and disposed before migrations, and with no owner connection the app verifies rather than applies.

## Tenancy, Database Architecture & RLS

Tenancy is enforced in Postgres by **which role a request assumes** (`SET ROLE`) and by **what the request's standing says**, not by app-layer checks alone. There are two orthogonal dimensions — the per-guild schema/role, and the platform privilege ladder — both backed by real Postgres roles.

### The authorization gates (security standard)

This is the canonical access-control model. Every path that reads or writes tooling data — REST, WebSocket, background job, realtime push — must honor all of it, and it must be enforced **at the database layer** (RLS preferred), not in app code alone. "Tools" = every kind in `app/core/tools.py` `Tool` (projects, files, calendars, …) and their content (tasks, comments, …).

Four nested gates, outermost → innermost:

1. **Guild** — no tooling data exists outside its `guild_<id>` schema. Enforced by schema-per-guild + `SET ROLE`.
2. **Initiative** — a user must **not** reach content of an initiative they are not in. This is the **hard isolation boundary** (it keeps sensitive data away from non-cleared members of the *same guild*). Enforced by RLS via the schema's own `initiative_access(initiative_id, user_id, need_write, standing)`.
3. **Initiative role** — within an initiative, a member's role dictates which tools they may engage and how.
4. **Tool sharing (DAC)** — per-resource `resource_grants` are the **final** privilege gate: the schema's `resource_access()` in every content policy, and its sibling `resource_level()` — the rung the request holds on a row, mapped on every shareable model as `access_level` and read by `permissions.level_of` — for what a serializer reports and a route compares against.

Two cross-cutting overrides sit above all four:

- **PAM** — platform roles may be **temporarily** granted scoped access via the DB tooling (time-bound, audited `access_grants`; `pam_read`/`pam_write` RLS legs). Never a standing bypass.
- **Guild admin** — **always** has read/write to **every** aspect of their guild, regardless of initiative membership or sharing (`GuildContext.is_admin` / the `app.guild_admin` RLS leg, computed from the membership row by the standing statement). **The one exception is held content**: a row the platform holds (`held_at` set, [`app/db/holds.py`](backend/app/db/holds.py)) reads as absent to the whole community, guild admins included, and nobody in it can change or delete it. A RESTRICTIVE `held_restrict` policy on every holdable table (derived from `HoldMixin`) admits a held row only to the system engine and a `moderate` content grantee (`app.pam_moderate`), and `held_guard` refuses its deletion outright. Only the platform releases a hold ([`app/services/platform/holds.py`](backend/app/services/platform/holds.py)).

Two rules follow from this being a **DB-layer** standard: authorization is a property of the *current moment*, not of a connection or a cached snapshot (re-derive it when grant/role/membership/PAM change); and a non-DB-enforced channel (e.g. an out-of-band realtime push) must carry **no content it hasn't continuously authorized** — prefer a content-free signal + an RLS-gated refetch so the gates above are the only decision point.

### Three engines (Postgres logins) — [`session.py`](backend/app/db/session.py)

- **`app_user`** (`DATABASE_URL_APP`, `LOGIN NOINHERIT`, **RLS-enforced**) — the request path. Holds *no* standing access to any guild schema; every request `SET ROLE`s into a scoped role first.
- **`app_admin`** (`DATABASE_URL_ADMIN`, `LOGIN BYPASSRLS`) — the system engine: startup seeding, background jobs, and bootstrapping/lifecycle endpoints that can't run under a scoped role. Its boundary is **enumerated per-table GRANTs** — a new shared table gives it nothing until a decision is recorded. That decision lives in the shared-table registry: each table's `Grants(app_admin=…)` in [`app/db/public_rls.py`](backend/app/db/public_rls.py) `SHARED_TABLE_REGISTRY` (a verb set, or `None`) is the current truth; `SHARED_TABLES` is derived from it, every platform model must have a record (`models/layout_test.py`), and the registry is held against the live catalog for drift ([`security_invariants_test.py`](backend/app/db/security_invariants_test.py)); migrations still run the actual `GRANT`/`REVOKE` (the immutable record of *when* access changed). Guild schemas require `SET ROLE guild_<id>` (which **drops** the bypass), with `guild_role='admin'` for full-authority maintenance. No *user-facing* role ever bypasses RLS.
- **`app_provisioner`** (`DATABASE_URL`, `provisioning_engine`) — DDL only: migrations, `CREATE SCHEMA`/`CREATE ROLE`, guild provisioning. A least-privilege `NOSUPERUSER CREATEROLE` role that owns the app's objects — created at startup by [`app/db/bootstrap.py`](backend/app/db/bootstrap.py) over the owner connection; `FORCE ROW LEVEL SECURITY` keeps even the owner policy-bound for DML. The app never serves on a superuser connection — boot refuses a superuser/BYPASSRLS provisioning login.

### Schema-per-guild

Guild **content** (projects, tasks, documents, initiatives, counters, calendar, tags, comments, …) lives in a **per-guild schema `guild_<id>`** — one schema per guild. Shared **identity/config** tables (`users`, `guilds`, `guild_memberships`, `guild_invites`, `app_settings`, `access_grants`, `oidc_*`) live in `public`.

- The canonical structure of a guild schema is the Alembic-maintained **`guild_template`** schema. There is **no committed schema artifact** — provisioning reflects the live template at runtime ([`app/db/guild_ddl.py`](backend/app/db/guild_ddl.py) `render_guild_schema_ddl`) so new guilds match by construction. `guild_template` is seeded on fresh installs from the frozen baseline snapshot [`alembic/baseline/guild_template_0125.sql`](backend/alembic/baseline/guild_template_0125.sql) (a write-once seed, never edited) and evolved by ordinary guild migrations thereafter.
- Provisioning + per-guild roles live in [`schema_provisioning.py`](backend/app/db/schema_provisioning.py); the DDL it applies is rendered once per process by `get_provisioning_bundle()` (structure from the live template, RLS from the registry, stamp over both + grants). `backfill_guild_schemas()` re-provisions on boot only guilds whose stamp is stale, so a guild migration reaches existing guilds automatically; `FORCE_GUILD_BACKFILL=true` forces a full sweep.
- **Guild isolation** is the schema boundary + `SET ROLE` (the request login role cannot reach any guild schema). On top of that, the guild **content** tables (projects, tasks, documents, counters, calendar + children, property defs, and the polymorphic `resource_grants`) carry **initiative-member RLS**: per-command PERMISSIVE policies that defer to one function, `initiative_access(initiative_id, user_id, need_write, standing)` (initiative member OR guild admin OR PAM OR the system engine, all read from the request's standing rather than walked per row — see rule 7 below). Every gate takes the standing as its last argument: a policy passes `(SELECT current_standing())`, a sub-select naming no row, so the standing is read once per statement rather than once per row, and a leg a policy reads inline is its own once-per-statement sub-select (`app.db.authorization.Legs`). `public.standing` is the shared type; `current_standing()` is rendered into each schema with the gates, so a schema's policies still call only that schema's functions. A child table's **read** policy is one `EXISTS` into its parent and nothing more: that scan runs the parent's own `SELECT` policy, which asks the same question, so the child restates only the write standing (`app/db/child_read_shortcut_test.py` holds the assumption that makes it the same answer). The **structural** initiative tables (`initiatives`, `initiative_members`, `initiative_roles`, `initiative_role_permissions`) are **read** within the schema boundary and not initiative-scoped for reading (co-members read their roster, and the standing statement reads the membership table before any standing exists), except that a private initiative's own row reads as absent to anybody not in it (`private_initiative_read`, which asks `reader_initiatives()`); they are **written** by the initiative's managers — `managed_*` policies rendered from `MANAGED_TABLES` in [`tenancy.py`](backend/app/db/tenancy.py) that admit a manager of that initiative by the standing (`app.manager_initiatives`, a value the seam computed, so the membership table is gated by no read of itself), the community's admin, a settings rung beside a `read_write` grant, or the system engine; a member's own row into an initiative whose join policy is `open` is the one further way in. The app layer uses the **same** function — [`membership.py`](backend/app/services/membership.py)'s `initiative_scope_clause` emits `func.initiative_access(...)`, so there's no parallel re-implementation. Policies are **rendered at runtime** by [`app/db/guild_ddl.py`](backend/app/db/guild_ddl.py) `render_guild_rls_ddl()` from the per-table `INITIATIVE_PATHS` registry in [`app/db/initiative_rls.py`](backend/app/db/initiative_rls.py) (the single source of truth — `INITIATIVE_SCOPED_TABLES`, and in turn `GUILD_SCOPED_TABLES`, derive from it) — applied by `apply_guild_rls` during provisioning (+ boot backfill); the function is rendered into each guild schema by the same provisioning run, ahead of the policies that call it (the guild-logic functions live in the schema, see [`app/db/authorization.py`](backend/app/db/authorization.py); the ones that read shared tables stay in `public`; none pins a `SET search_path` and none is `SECURITY DEFINER`; the gates are `plpgsql`). The tables whose row names its subject as a `(kind, id)` pair — `comments`, `reactions`, `batched_notices`, `personal_items`, `relationships` — defer to one of those, `entity_access(kind, id, need_write, need_share_write, standing)`: one `CASE` arm per kind, derived from the comment parents, reaction targets, recentable tools and edge kinds, so a policy there is one call rather than one `EXISTS` per kind. One consequence: a guild member who isn't in an initiative gets **404** (RLS hides the row), not 403, for that initiative's content.

### Roles assumed per request (`set_rls_context`)

- **Per-guild roles** `guild_<id>` (read/write its schema), `guild_<id>_ro` (SELECT-only, for PAM *read* grants), `guild_<id>_support` (a scoped `read_write` grant), `guild_<id>_q` (the query surface), `guild_<id>_superadmin` (the seat, below) and `guild_<id>_plugin` (a plug-in acting as its community: grants rendered from `app/db/plugin_rls.py` `PLUGIN_TABLE_ACCESS` only, over the **`plugin_install_base`** floor). The rest inherit shared/`public` access from **`app_guild_base`** or its read-only twin **`app_guild_base_ro`**. The login roles are granted membership in every guild role **`WITH INHERIT FALSE`** — they can `SET ROLE` in but hold no standing access (fail-closed).
- **The seat's role and its floor.** A community's own sign-in configuration is written by `guild_<id>_superadmin`, which inherits `guild_<id>` (the full guild role, composed rather than granted afresh) and **`app_superadmin`** (the one shared floor holding `guild_auth_policies` writable). A request assumes it by **asking for it** — `SeatSessionDep`, which the configuration routes take — **and holding it**: the membership row says `superadmin`, or a live `superadmin` settings grant does. Holding the seat is not using it, so an ordinary content request by a seat holder routes as `guild_<id>` and carries none of those grants. `app_superadmin` takes **no** default privileges: a new shared table reaches it only through its registry record's `app_superadmin` grant and a migration.
- **Platform-tier roles** `platform_<tier>` (member/moderator/support/operator/owner, `NOLOGIN`) + a shared **`platform_base`** floor; the public/platform path assumes `platform_<users.role>`. A **suspended** account assumes **`platform_suspended`** instead, whatever its tier: it inherits only **`platform_base_ro`**, the read half of `platform_base` (its `SELECT`s, and the `SELECT` side of every policy granted to `platform_base`, derived in `public_rls.py`), so it reads its own rows and writes nothing.
- **Routing:** a **guild request** (`/c/{community_id}/…`) → `SET ROLE guild_<id>` (or `_ro`), `search_path = guild_<id>, public`; a **public/platform request** → `SET ROLE platform_<tier>`, `search_path = public`. Each request resets to the login role (`SET ROLE none`) first, and the connection is reset on return to the pool.
- **No standing all-guild bypass for users.** The only BYPASSRLS holder is the system engine (`app_admin`). A platform operator reaches a guild's data only via an explicit **break-glass** grant (below).

### Session Types (choose the right one)

| Session Dep | Engine / role assumed | When to use |
|---|---|---|
| `RLSSessionDep` (`get_guild_session`) | `app_user` → `SET ROLE guild_<id>`/`_ro` | Guild-scoped data under `/c/{community_id}/…` (projects, tasks, documents, initiatives, tags, comments, task statuses, collaboration, imports). Pair with `GuildContextDep`. |
| `UserSessionDep` (`get_user_session`) | `app_user` → `SET ROLE platform_<tier>` | Authenticated public/platform path with no guild: list/reorder/leave guilds, cross-guild "my" (`/me/*`) reads, platform reads governed by `platform_<tier>` policies. |
| `SystemSessionDep` (`get_system_session`) | `app_admin` (system engine: BYPASSRLS, grant-bounded) | Bootstrapping where the entity doesn't exist yet (create guild, accept invite), platform user management + `access_grants` endpoints (capability-gated), background jobs, startup seeding. Guild schemas only via `set_rls_context(guild_id=…)` — SET ROLE drops the bypass. |
| `SettingsRLSSessionDep` (`get_guild_settings_session`) | `app_user` → `SET ROLE guild_<id>` for a member; `guild_<id>_ro` for a settings-only grant, `guild_<id>_support` beside a `read_write` grant | The community's own configuration and roster — the surface an administrator keeps while its content is frozen (`read_only`), and the only session a settings-only grant may serve. Routed by `SettingsContextDep` (`get_guild_settings_context`, the seam established `for_settings`: the sign-in step-up, the `read_only` freeze and age gate govern the work, not the settings). A `suspended` community is in time out: its members, admins included, reach no surface at all, settings included; only a platform grant does. Gate by rung with `SettingsAdminContextDep`; a route that changes something takes `SettingsAdminWriteContextDep` / `SettingsSeatWriteContextDep`, which also ask a grantee for the `read_write` grant beside the rung. |
| `SeatSessionDep` (`get_guild_seat_session`) | `app_user` → `SET ROLE guild_<id>_superadmin` | The seat's configuration routes (sign-in settings and policy, provider connections and their claim rules, the billing handoff). Refuses anyone the standing says does not hold the seat. A route that changes something takes `SeatWriteSessionDep` / `SeatWriteContextDep`: a lent seat writes only beside a `read_write` content grant. |
| `SessionDep` (`get_session`) | `app_user`, login role (no `SET ROLE`) | Unauthenticated endpoints, or handlers that call `set_rls_context()` themselves after validating. |

### Path-based guild tenancy

The active guild is **addressed in the URL** (`/c/{community_id}/…`), never server-held. `get_guild_membership` (`GuildContextDep`) resolves the guild from the `Path` param and re-validates real membership **or** a live PAM/break-glass grant on every request (403 otherwise); the path is a selector, not a trust boundary. Cross-guild "my" views are dedicated `/api/v1/me/*` endpoints.

### Platform privilege ladder & capabilities

The 5-rung ladder (`member → moderator → support → operator → owner`, stored in `users.role`) maps to a capability set in [`capabilities.py`](backend/app/core/capabilities.py). Gate platform endpoints on a **capability** via `require_capability(...)`, never a role name; the frontend mirrors the capability strings in [`permissions.ts`](frontend/src/lib/permissions.ts) (reads backend-computed `UserRead.capabilities`). `config.manage` (owner-only) gates app config (OIDC, SMTP, branding, role labels, platform AI) under `/settings/platform`. The first/bootstrap user becomes `owner`; never leave the platform without a `config.manage` holder (`is_last_capability_holder`).

### Break-glass & PAM (cross-guild access without a standing bypass)

A user reaches a guild they don't belong to only through a **time-bound, per-guild, audited grant** (`access_grants` table, `/api/v1/access-grants`), routed through that guild's own `guild_<id>_ro`/`guild_<id>` roles + `pam_*` GUCs — never BYPASSRLS:

- **moderator / support** (`access.request`): request → an approver (`access.approve`) grants/denies → auto-expires. Read-only by default; a `read_write` grant edits *existing* content only (no authoring or member/permission management). A `moderate` grant reads everything including held content and edits nothing; only a `content.moderate` holder may request it, and it is never self-issued. Every other grant needs `access.request_any`, which a moderator does not hold: the moderator rung is moderation only.
- **operator / owner** (`data.bypass`): self-issue a **break-glass** grant (`POST /access-grants/break-glass`) — created **and** self-approved in one step (the row is the audit trail), short TTL. Break-glass is **a pair of grants, not an admin**: a content grant (`read` for full read-only of the guild, `read_write` to edit *existing* content) and, beside it, a `superadmin` settings grant for the community's own configuration. Neither makes the holder a guild admin — `app.guild_admin` is computed from the membership row and no grant sets it — so authoring, member management and permission changes stay closed. `data.bypass` is the *right to break glass*, not a standing bypass; with it removed, an operator reaches a guild only after clicking through.

**How a grant reaches a request.** The establishment seam is the only reader of `access_grants`: it looks the live rows up, routes into `guild_<id>_ro` (a read grant) or the restricted `guild_<id>_support` role (`read_write`), and its standing statement recomputes `app.pam_read` / `app.pam_write` from those same rows, in the database, so what the ~200 PAM policy legs read was written from a row rather than from a variable. Revoking or expiring a grant changes the next request's standing with no other write. A grant also counts only while its holder's platform rung may hold it (`may_hold_grant` in `capabilities.py`): the lookup and the standing statement both read the rung as it stands, so a demotion ends what the new rung cannot hold.

### Rules for writing backend endpoints

1. **Default to `RLSSessionDep`** for any endpoint that reads/writes guild-scoped data; it requires `GuildContextDep` in the same signature (the guild comes from the `/c/{community_id}` path).
2. **RLS context is transaction-local and replays automatically.** `set_rls_context()` applies `SET LOCAL`-scoped state and an `after_begin` hook re-applies it on every new transaction, so post-commit queries need no manual re-apply. Never set session-level (`is_local=false`) role/GUC/search_path state on a pooled connection — and don't hold a routed session past `RLS_CONTEXT_MAX_AGE_SECONDS` without re-validating via `establish_guild_access` (user-derived snapshots fail closed after the bound).
3. **Use `UserSessionDep`** for authenticated cross-guild/platform reads so the request is `platform_<tier>`-scoped; reserve `SystemSessionDep` (the system engine) for bootstrapping/lifecycle/jobs that genuinely can't run under a scoped role — and remember a new shared table needs an explicit `GRANT … TO app_admin` before the system engine can touch it, recorded in its [`public_rls.py`](backend/app/db/public_rls.py) `SHARED_TABLE_REGISTRY` record (CI fails until it has one).
4. **Never use `SessionDep` for guild-scoped data** — without a `SET ROLE` it can't even see the guild schema (and shared-table reads run as the bare login role).
5. **Gate platform endpoints on `require_capability(...)`**.
6. **`set_rls_context()` uses `set_config()`** (not `SET` commands) so the assumed role and GUCs land on the same pooled connection as subsequent queries.
7. **Route a person into a community only through the seam.** `establish_guild_access` (REST reaches it through `GuildContextDep`/`RLSSessionDep`) looks up the membership or grant, routes the session, and runs one statement that computes the reader's **standing** — membership, initiative roles, the admin fact, the tool switches — in the routed schema. That `GuildContext` is what endpoints and services read: it is **passed down** by whoever holds the session (`permissions.require_access`, `resource_access.authorize` and every serializer that reports a level take it as an argument), and an async helper that was handed only the session reads it back with `app.db.session.require_guild_context(session)`. It is stored as the session's replay parameters, so what Python believes and what the policies evaluate are the same values. `for_settings=True` is the community's own configuration and membership surface, which its administrator keeps while its content is closed. `set_rls_context` refuses a `user_id` and a `guild_id` together without one, and `app/api/context_seam_guard_test.py` fails on the shapes that would skip it. A routing carries **no role**: guild admin is a lookup (`app.guild_admin`, computed from the membership row), and trusted maintenance is admitted by the connection's own login (`app_admin`), not by anything a call says.
8. **A sweep, a poller or a lifecycle job routes with `guild_id` alone** — no user, no role. It runs on the system engine, and the policies' system leg names that login.

### Adding or changing tables

The path depends on **where the table lives**:

1. **Guild-scoped (content) table** — add/modify the SQLModel, then run **`python scripts/gen_guild_migration.py "desc"`**. It autogenerates a guild-scoped migration (`alembic -x guild revision --autogenerate` — reflects `guild_template`, filters to guild-content tables only, wraps the ops in the per-schema loop via `script.py.mako`) and applies it to `guild_template` + every `guild_<id>`. There is **no artifact to regenerate or commit** — provisioning reflects the live template, so new guilds match by construction.
   - **Classify it for initiative-member RLS — in ONE place.** Decide initiative-scoped vs guild-level:
     - *Initiative-scoped* (almost all content): add one entry to `INITIATIVE_PATHS` in [`app/db/initiative_rls.py`](backend/app/db/initiative_rls.py) describing how a row resolves its initiative (`direct()`, `via(parent, fk)`, a 2-hop helper, or a custom builder). `INITIATIVE_SCOPED_TABLES` and `GUILD_SCOPED_TABLES` **derive** from that registry, so you don't edit a second list; the rendered RLS (`app/db/guild_ddl.py`) then gives the table the four PERMISSIVE `initiative_member_*` policies deferring to `initiative_access` (applied on next boot — the registry edit bumps the provisioning stamp).
     - *Guild-level* (guild-wide config, the structural initiative tables, own-row-only): add it to `GUILD_LEVEL_TABLES` in [`tenancy.py`](backend/app/db/tenancy.py) — exempt, protected only by the schema boundary. (`uploads` is the canonical example: no FK to any initiative.)
     - *The operations community's alone* (a table only it fills, like `intake_cases`): classify it as above **and** add it to `OPERATIONS_TABLES` in [`tenancy.py`](backend/app/db/tenancy.py). Provisioning leaves it out of every other community and choosing the operations community creates it ([`operations_schema.py`](backend/app/db/operations_schema.py)), so it costs the other communities nothing. `gen_guild_migration.py` runs a change to it only where it is and refuses a diff that mixes it with other tables, and nothing every community has may name it: the render refuses a statement on another table that does (`guild_ddl.split_operations`).

   Enforcement is automatic: `tenancy_test.py` fails CI if the new table is in neither bucket; `guild_rls_test.py` fails if an initiative-scoped table lacks its policies in a freshly provisioned schema.

2. **Shared/platform table in `public`** (identity/config) — add it via Alembic migration with `ENABLE` + `FORCE ROW LEVEL SECURITY` and the table `GRANT`s/`REVOKE`s (e.g. config tables owner-only to write). **Declare it once, in the registry:** one `SharedTable` record in [`app/db/public_rls.py`](backend/app/db/public_rls.py) `SHARED_TABLE_REGISTRY`, holding its row security, its grants and its tier grants. Its policies (`rls=TableRls(...)`) go there, not in the migration, built from the predicate builders there (`own_row`, `guild_scoped`, `routed_admin`, `pam_read`, …, or literal SQL), rendered and applied at boot by `ensure_public_rls` and held to the catalog by `public_rls_test`. A policy for the platform tiers names the capability it guards (`Capability.USERS_READ`) in place of the tiers, and the render spells the tiers holding it from [`capabilities.py`](backend/app/core/capabilities.py) — which tier holds what is decided there alone. A migration writes no `CREATE POLICY` for a shared table, for the reason guild migrations don't render theirs: it would freeze what the registry said that day. A table nothing on the request path may read is registered as `FORCED_NO_POLICY`, which states the strictest state rather than implying it by absence. `SHARED_TABLES` in [`tenancy.py`](backend/app/db/tenancy.py) is derived from the registry, so the record is the one place to add it; give it its `grants=Grants(...)`: one verb set per role, `None` (the default) for no access — the system engine (`app_admin`), the bare login (`app_user`), the guild floor (`app_guild_base`, what every routed `guild_<id>` role inherits), the platform floor (`platform_base`), the seat floor (`app_superadmin`) and the install floor (`plugin_install_base`, what an installed plug-in's `guild_<id>_plugin` role inherits). `layout_test` and `tenancy_test` fail until every shared model has a record, [`system_grants.py`](backend/app/db/system_grants.py) reads the record per role, and `security_invariants_test` fails until the migration's `GRANT`/`REVOKE` match it. The two floors are granted the other way round from the login roles: the schema default gives each full DML on a new table, so a `None` there means the migration must `REVOKE ALL … FROM app_guild_base, platform_base`. `app_superadmin` and `plugin_install_base` take no default privileges at all, so their entries are `None` unless a migration grants them. The read floors take no default privileges either: a new table `platform_base` may read is granted `SELECT` to `platform_base_ro` in the same migration (`platform_base_ro_parity_test` fails until it is), as one `app_guild_base` may read is to `app_guild_base_ro`. A grant to a `platform_<tier>` role itself rather than its floor goes in the record's `tiers`, keyed by the capability that earns it like a policy; `security_invariants_test` holds every tier's direct grants to it. Gate the endpoints on the matching capability.

   **A policy opens access; it does not close it.** Postgres policies are PERMISSIVE by default, so `ENABLE` + `FORCE` with **zero** policies denies every role that is not BYPASSRLS — a grant alone reads nothing. That is the strictest state a table has, so an `app_admin`-only table — one whose migration `REVOKE`s the schema-default DML from `app_guild_base` and `platform_base` — is correct with no policies at all, and adding a `TO platform_<tier>` one would open a door rather than shut it. Write the policy at the moment a request-path role is actually granted something, and write it as a real lookup rather than a tier name. (`users` carries policies because the request path reads it; `auth_sessions`, `auth_providers`, `auth_provider_secrets`, `user_api_keys`, `user_tokens`, `user_emails` and `user_email_assertions` carry none because it cannot.)

3. **`access_grants`** is platform-scoped (managed cross-guild) like `users`: its endpoints use `SystemSessionDep` with explicit capability + ownership checks, with `platform_<tier>` policies for the access-request queue and an own-row policy for requesters.

4. **Backfill a new table BEFORE you lock it down.** `FORCE ROW LEVEL SECURITY` binds the table's *owner* — which is `app_provisioner`, the role every migration runs as. Once FORCE is on, the migration's own `INSERT` must satisfy a policy, and those policies key on request GUCs (`app.current_user_id`, `app.current_guild_id`) that a migration has no value for: nothing matches and the write is rejected with `new row violates row-level security policy`. Order the `upgrade()` as **create table → move the rows in → `ENABLE`/`FORCE` RLS + policies + grants** (migration `0179` is the reference). A fresh install has nothing to backfill, so only `app/db/migration_backfill_order_test.py` catches the wrong order. Writing to a table that *already* existed is the other way round: lift `NO FORCE ROW LEVEL SECURITY`, write, and restore `FORCE` in the same transaction (`try`/`finally`).

5. **Renaming / dropping** — `DROP POLICY IF EXISTS …` and `DISABLE ROW LEVEL SECURITY` before the DDL; always provide a clean downgrade.

6. **Session variables** — `app/db/gucs.py` declares each request variable (`app.current_user_id`, `app.pam_read`, …) once and renders its read; import it rather than spelling `current_setting(...)` yourself. SQL a migration freezes spells the read the way that module renders it: NULLIF-guarded, since an unset variable reads as `''` and a bare `''::int` fails the whole query for every policy on the table. `app.pam_guild_id` stays separate from `app.current_guild_id`: a matching `current_guild_id` counts as proof of membership, which a grantee does not have.

7. **Verify after migration** as `app_user` (not the superuser): for a shared/platform table, confirm each tier hits its ceiling (a missing policy silently returns zero rows; a wrong one leaks). For guild content, `SET ROLE guild_<id>` and confirm only that guild's schema is reachable.

### Never edit a migration

A revision runs **once** per database and is then stamped. Editing it in place
changes what a *fresh* database gets and **nothing else**: every database that
already ran it — deployments, the dev environment, other checkouts — keeps the
old shape, and no upgrade will ever repair it.

**A revision on `dev` is never edited, released or not.** To change what one
did, add a new revision after it. A revision your branch adds is yours to change
until it merges.

When a merged revision was edited anyway, the fix is a new revision that
converges **both** histories — the databases that ran the old shape and the
fresh installs that got the new one — so its DDL has to be conditional
(`ADD COLUMN IF NOT EXISTS`, `DROP CONSTRAINT IF EXISTS`).
[`20260907_0234`](backend/alembic/versions/20260907_0234_restore_dm_send_receipts.py)
is the reference.

CI enforces this: a pull request that modifies, renames or deletes a revision
already on its base branch fails the backend job (`No merged migration edited`
in `ci.yml`; `scripts/ci/check migrations` locally and before a push). That
includes docstring and comment edits — nothing runs from those, but the check
reads the file list, so leave merged files alone.

### Rules for writing frontend code

1. **React Query cache keys for the same data must match across components.** If the sidebar uses `["initiatives", communityId]` and a page uses `["initiatives", { communityId }]`, invalidation from one won't reach the other. Use prefix invalidation (`queryKey: ["initiatives"]`) when mutations should refresh all consumers.
2. **Guild context is in the URL path, not server-held.** Every guild-scoped request addresses its guild as `/api/v1/c/{communityId}/…`. Guild pages live under the `/c/$communityId` route tree; `useActiveCommunityId()` derives the current guild from the route. Cross-guild "my" views call the dedicated `/api/v1/me/*` endpoints.
3. **Widths are Tailwind's `sm:` … `xl:`, at device widths, and nothing else.** `src/ui/styles.css` sets them to 600 (unfolded foldable, portrait tablet), 840 (landscape tablet; the sidebar docks), 1200 (laptop) and 1600 (big desktop), in rem. Chrome (sidebar, navigation, header, page padding, type size) uses `sm:` … `xl:`, and `useWidthClass()` in code. Grids, forms and rows take no width at all: `grid-cols-fill-<spacing>/<columns>` for tiles (the minimum width, and the most columns a big screen gets), `grid-cols-pair` for form fields, `flex-wrap` for a title-and-actions row. Only where one piece swaps for another (a side panel for a row of chips, a rail for a drawer) does a page measure itself: `canvas-sm:` … against the page area, or `useRegionWidthClass(element)` in code. Tailwind's `@sm:`/`@md:` container variants are not these widths (they share `max-w-*`'s sizes), so they are refused. The `no-other-widths` Biome rule (`frontend/biome-plugins/`) refuses any other breakpoint, container size, arbitrary width variant or width query.
4. **Build each formatter once.** Dates, numbers, lists and sorting format through `src/ui/lib/intl.ts` (`dateTimeFormat`, `numberFormat`, `listFormat`, `collator`), which builds each `Intl` formatter once per locale and options. The `one-formatter` Biome rule refuses `new Intl.…`, `toLocaleString`, `toLocaleDateString`, `toLocaleTimeString` and `localeCompare` with a locale or options anywhere else.
5. **A control's gap spaces its icon from its label.** `Button`, the dropdown menu and command items, `Toggle`, the sidebar buttons and the alert dialog's actions set a gap on their root, so an icon or label inside one takes no `ml-*`/`mr-*`: the margin would add to the gap. The `no-gap-margins` Biome rule refuses it on their direct children (and on a slotted child's, under `asChild`); `ml-auto` and negative margins are allowed. `ContextMenuItem` and `SelectItem` set no gap, so their children still space themselves.
6. **Never use `localStorage` directly.** Import `getItem`, `setItem`, `removeItem` from `@/lib/storage` instead. The storage module uses an in-memory cache backed by Capacitor Preferences on native (preventing data loss when the OS clears localStorage) and delegates to localStorage on web. `initStorage()` hydrates the cache before React renders, so all reads are synchronous.
7. **`src/ui` is the UI kit our plug-ins copy,** with the rich-text editor's core in `ui/editor`, the field components in `ui/properties` and the layout core and its editor in `ui/layouts`. Nothing in it imports from outside it but npm packages and the generated API's types (`api/generated/initiativeAPI.schemas`). What it needs from the app comes through `ui/host.ts`, which `lib/kitHost.ts` fills at boot, and its words are the `ui`, `editor`, `properties` and `layouts` namespaces. The `ui-imports-only-ui` Biome rule refuses anything else in `src/ui` outside its tests. A component that needs Initiative's data, routes or hooks belongs outside it (rule 8). Plug-ins take the kit with `src/ui/refresh.mjs`, which copies it from an Initiative tag and whose `--check` fails when a copy has drifted.
8. **`pages/` is laid out as the app's navigation, and `components/` holds only what several pages share.** A page sits in the folder named for its place in the navigation: `site` (signed out), `signIn`, `my` (Home and the "My …" pages, `my/settings` for My Settings), `people`, `communities`, `community` (its home, members, search, tags, marketplace and plug-ins, with `settings`, `initiatives` and `tools/<tool>` inside), `operator` and `platform`; the few nothing in the navigation leads to (the share sheet's page, the link resolver, the licence notices) sit at the top. A page with parts of its own is a folder holding them, and a file is named for what it is there (`community/settings/security/SecurityPage.tsx`). `components/` keeps the app's chrome (the sidebar, navigation, banners and app-wide dialogs) and the pieces more than one folder of pages uses, grouped by feature, with a tool's in `components/tools/<tool>` under the tool's namespace name. A component the pages of only one folder use lives in that folder; `__tests__/componentsAreShared.test.ts` fails until it does.

## Guild Architecture Notes

- Guild membership has two roles (`admin`, `member`). Guild admins own memberships, invites, initiative/project configuration, and can delete their guild; they cannot delete users from the entire app. Keep server-side checks scoped to guild roles, not platform roles.
- The platform rule `community_creation_enabled` (Settings → Platform → Community; seeded once from `DISABLE_GUILD_CREATION`) governs community creation. Off, POST `/communities/` returns 403 for anyone without `communities.manage` and the frontend hides “Create community” affordances (`UserRead.can_create_communities`), so new users redeem invites issued by community admins.
- Every new guild automatically **provisions its `guild_<id>` schema + per-guild roles** (`provision_guild_schema`), seeds its settings row + mandatory plug-ins, and makes the creator a guild admin. It gets **no initiative** — naming the first one is the owner's decision, and the guild home's empty state is where they make it (`scripts/seed_dev_data.py` provisions its own through the same sequence the create endpoint uses). Be mindful when writing migrations or services so this invariant holds — guild deletion must drop the schema + roles (`deprovision_guild`) *and* clean up the shared rows (memberships, invites, OIDC mappings, access grants) that cascade off `public.guilds`.
