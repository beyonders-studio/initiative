---
name: create-pr
description: Open a pull request for the current changes, then watch it to green — poll CI and the Greptile review together, addressing review findings as soon as they post instead of waiting for the full rollup, fixing failures; asks Greptile to re-review until confidence is high only when the user wants that. Use when the user says "make a PR", "open a pull request", "ship this", or asks to watch a PR's CI / review status.
user-invocable: true
---

# /create-pr — Open a PR and babysit it to green

Create a pull request for the working changes, then stay with it: watch CI and
the Greptile review *at the same time*, fix whatever lands first, and keep
looping until every check is green and every review finding is fixed or
answered (or the user tells you to stop). Greptile's feedback almost always
arrives before CI finishes — address it then, rather than sitting on it until
the rollup completes.

Asking Greptile to review again, round after round until it reaches 5/5, is a
separate ask: do it only when the user asks for it ("get it to 5/5", "loop
Greptile").

Repo rules that this skill must honor (from `CLAUDE.md`):
- **PRs target `dev`, never `main`.**
- Commit subjects are imperative, ≤50 chars. **Never** add `Co-Authored-By`
  trailers or mention coding agents.
- Update `CHANGELOG.md` **before** opening the PR for any user-facing feature,
  fix, or breaking change (skip for pure internal refactors). New changes go
  under `## [Unreleased]`, never under an already-released version.

## 1. Pre-flight — get the change into shape

1. `git status` and `git diff --stat` to see what's staged/unstaged. If there
   are no changes at all, stop and tell the user.
2. Run the quality gates for what changed (don't run the whole world if only
   one side changed):
   - **`scripts/ci/check`**: the fast checks CI runs, by the same script CI
     calls (ruff, ruff format, ty, no merged migration edited, one Alembic head,
     biome, tsc, and generated-types / `env-contract.json` drift), for what the
     branch changed against `origin/dev`. No database, no tests; seconds.
     When `codegen` fails, read why before committing anything:
     - "it differs from what is committed": it has regenerated the files.
       Review the diff and commit it.
     - "uncommitted changes, which regenerating would overwrite": it stopped
       before generating. Commit or discard those changes and run it again.
     - anything else (a missing `.venv` or `node_modules`, an export error):
       nothing was regenerated. Fix that and run it again.
   - Tests for what changed: `cd backend && ./scripts/test-changed.sh` and
     `cd frontend && ./scripts/test-changed.sh`.
   Fix anything that fails before opening the PR — a red gate locally will be
   red in CI, and a CI round-trip on this repo costs up to ~26 minutes. Never
   push a speculative fix hoping CI will validate it; reproduce it locally
   first.
3. If the change is user-facing, add a concise `CHANGELOG.md` entry under
   `## [Unreleased]` in the right subsection (Added / Changed / Fixed /
   Security).

## 2. Branch, commit, push

1. Determine the current branch (`git branch --show-current`). If it is `dev`
   or `main`, create a fresh feature branch off it:
   `git checkout -b <type>/<short-kebab-summary>` (e.g. `fix/…`, `feat/…`).
   If already on a feature branch, keep using it.
2. Stage the intended files explicitly and commit. Imperative subject ≤50
   chars; add a body explaining the *why*. **No** `Co-Authored-By`, no agent
   mentions. A pre-commit hook (lint-staged/biome) may run — let it.
3. `git push -u origin <branch>`. The husky pre-push hook runs
   `scripts/ci/check` again for what the branch changed; if it fails, fix and
   push again rather than skipping it with `--no-verify`.

## 3. Open the PR

Create it against `dev` with a structured body:

```bash
gh pr create --base dev --title "<imperative title>" --body "$(cat <<'EOF'
## Problem
<what was wrong / what this enables>

## Changes
- <bullet per notable change, link files as [name](path)>

## Testing
- <exact commands you ran and their result>

Fixes #<issue>   # only if it closes an issue
EOF
)"
```

Capture the PR number from the returned URL.

## 4. Watch CI *and* Greptile together

Greptile usually posts its first review while CI is still running, and CI
failures usually surface one job at a time. **Do not wait for the whole rollup
to finish before reading review feedback** — watch both signals in one loop and
act on whichever lands first.

Snapshot what you have already seen, then wait for the *next* event:

```bash
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
PR=$(gh pr view --json number -q .number)

# Baseline: the newest Greptile review id we've already read (0 if none yet).
seen_review() {
  gh api "repos/$REPO/pulls/$PR/reviews" \
    --jq '[.[] | select(.user.login|test("greptile";"i")) | .id] | max // 0'
}
SEEN=$(seen_review)
START=$(date +%s)

# Wait for: a new Greptile review, a failed check, or everything green.
while :; do
  FAILED=$(gh pr view "$PR" --json statusCheckRollup \
    -q '[.statusCheckRollup[] | select(.conclusion=="FAILURE" or .conclusion=="TIMED_OUT") | .name] | join(", ")')
  PENDING=$(gh pr view "$PR" --json statusCheckRollup \
    -q '[.statusCheckRollup[] | select(.status!="COMPLETED")] | length')
  NOW=$(seen_review)
  if [ "$NOW" != "$SEEN" ]; then echo "EVENT=greptile review=$NOW"; break; fi
  if [ -n "$FAILED" ];       then echo "EVENT=ci-failure jobs=$FAILED"; break; fi
  if [ "$PENDING" -eq 0 ];   then echo "EVENT=ci-green"; break; fi
  echo "waiting: $PENDING check(s) pending, $(( $(date +%s) - START ))s elapsed"
  sleep 30
done
```

**Run this in the background** (`run_in_background: true`). A full backend run
takes **up to ~26 minutes**, and the Bash tool caps a foreground call at
600000ms (10 min) — a blocking wait cannot cover one cycle, and blocking the
session for 26 minutes would be wrong even if it could. Background it, do the
Greptile work while it runs, and read its output when it breaks.

Each time it breaks, handle the event (§5 or §6) and then **re-enter this loop**
with `SEEN` updated to the review you just read. The loop is finished when
`EVENT=ci-green`, Greptile's first review has posted, and every finding in it is
fixed or answered (and, when the user asked for the re-review loop, the bar in
§5 is met). CI often goes green first on a small PR, so after `EVENT=ci-green`
keep waiting for that first review. Greptile sometimes never answers: if it
hasn't posted 15 minutes after CI went green, stop and say so in the report.

**Batching pushes.** A push cancels the in-flight run and restarts it from
zero, so never push once per finding — collect a whole Greptile round (plus any
CI failure already visible) into one commit and push once.

Given the timings, the usual call is easy: Greptile posts within a minute or
two, when the backend job has barely started, so **push the batch as soon as
it's ready** — you're discarding two minutes of a run that was testing the
pre-fix commit anyway, and the fixed code's results arrive ~26 minutes from the
push either way. Waiting for the current run to finish first just adds its
remaining time to that.

Hold the push only when the run is nearly done and its result would change what
you commit — you're minutes from learning about failures you'd want to fold
into the same batch.

## 5. Handle a Greptile round

Read the review body and the inline findings:

```bash
gh api "repos/$REPO/pulls/$PR/reviews" \
  --jq '.[] | select(.user.login|test("greptile";"i")) | {id, submitted_at, body}'
gh api "repos/$REPO/pulls/$PR/comments" --jq '.[] | {path, line, body}'
```

For each finding, judge whether it's a real issue in scope for this PR.
- **In scope + valid** → fix it (edit, commit with the rest of the batch, push).
- **Out of scope / false positive** → reply briefly saying why; don't fix.

After pushing a round of fixes, reply on each thread, one call per reply, with
the path in quotes (never built from a word-split loop variable, which posts to
the PR itself):

```bash
gh api "repos/$REPO/pulls/$PR/comments/<comment id>/replies" -f body="<reply>"
```

Then go back to §4's loop (with `SEEN` set to the review you just handled).

Only when the user asked for a re-review or the 5/5 loop, also post a comment
holding only `@greptile` (it re-runs reliably only when it stands alone); §4's
loop then waits on the re-review and any still-running CI together:

```bash
gh pr comment "$PR" --body "@greptile"
```

**In the re-review loop, aim for 5/5 confidence.** Accept 4/5 only if the remaining findings are
genuinely out of scope for this PR.

## 6. Handle a CI failure

The CI workflow's jobs on this repo include **Backend Lint & Tests**,
**Frontend Lint & Tests**, and **Check Generated Types**. When a job concludes
`FAILURE`:

1. Pull its log:
   `gh run view --job <jobId> --log-failed | tail -80`
   (get `<jobId>` from the `detailsUrl` in the rollup, or
   `gh run view <runId> --json jobs`).
2. Reproduce and fix locally. Common repo-specific gotchas:
   - **Locale keys**: `locale-keys.test.ts` requires every `en` key be
     mirrored in `de`/`es`/`fr`. Add new keys to all four locale files.
   - **API compatibility** (a step in Check Generated Types): the change
     breaks what the last release's API took. Keep the old shape, or, if
     the break is intended, add the lines it printed to
     `backend/api-breaking-changes.md` and say why in the PR body.
   - **Generated types**: if backend schemas changed, regenerate per
     `CLAUDE.md` (Orval) and commit the output.
3. Other jobs may still be running — fix the one you have while they finish. If
   a second job fails while you're working, fold that fix into the same commit.
4. Commit, push, and re-enter §4's loop.

**Frontend Lint & Tests** and **Check Generated Types** report in a few
minutes; **Backend Lint & Tests** is the long pole. Detect Changes picks its
mode from the diff (CLAUDE.md, "Which backend tests a pull request runs"):
- **every test** (the ~26-minute case) for a change test selection cannot see:
  under `backend/`, `alembic/`, `app/db/`, `app/testing/`,
  `app/core/capabilities.py`, `app/core/config.py`, `conftest.py`,
  `pytest.ini`, `pyproject.toml`, `uv.lock`, `scripts/ci/` and non-Python
  files under `app/`; and `.github/workflows/ci.yml` or
  `.github/actions/setup-backend/`. The `changes` job in `ci.yml` holds the
  list, and wins if this one drifts;
- **the always-run core plus the tests the change reaches** for an ordinary
  backend change;
- **only the always-run core** when nothing in `backend/` changed but more
  than documentation did.
If you touch one of the every-test paths, expect the long run and plan the
batch around it. A documentation-only PR skips the job.

## 7. Report

Summarize for the user:
- PR URL and number.
- Final check status (table: check → pass/fail).
- Greptile confidence score and any findings you intentionally left unaddressed
  (with the reason).
- `mergeStateStatus` — if it's `BLOCKED` only on `REVIEW_REQUIRED`, say so:
  all automated gates are green and it's waiting on a human approval
  (@jordandrako / @LeeJMorel), which this skill cannot self-approve.

## Notes on pacing

- **Budget the real numbers.** Backend Lint & Tests runs up to ~60 minutes on a
  full-suite PR; the frontend and generated-types jobs land in a few. Greptile
  typically posts within the first minute or two. The §4 loop exists so those
  60 minutes aren't dead time.
- A 30s poll is right for a run of this length; anything tighter just burns API
  calls. Always background the loop — a foreground Bash call maxes out at 10
  minutes, less than half a backend cycle.
- Tell the user the expected wait when you start watching, and don't go silent:
  report each event as you handle it rather than only at the end.
- Don't re-run local gates you already ran this session just because you're
  pushing again; run the ones the new edits actually touch.
- Never fabricate a check result — only report statuses you actually read from
  `gh`.
