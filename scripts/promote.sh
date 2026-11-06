#!/bin/bash
set -euo pipefail

# ── Colors ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

# ── Globals ──────────────────────────────────────────────────────────────────
MODE=""              # promote | release | cherry-pick | rollback
BUMP_TYPE=""         # patch | minor | major | custom
CUSTOM_VERSION=""
CHERRY_SHAS=()
DRY_RUN=false
AUTO_CONFIRM=false
FORCE_NATIVE=false   # force MIN_NATIVE_VERSION bump even if no native change is detected
CLEANUP_BRANCH=""
CLEANUP_REMOTE=""      # a release branch pushed before its pull request opened
ALLOWED_OWNERS=("jordandrako" "LeeJMorel")
DATE=$(date +%Y-%m-%d)

# ── Helpers ──────────────────────────────────────────────────────────────────
die()  { echo -e "${RED}ERROR: $*${NC}" >&2; exit 1; }
warn() { echo -e "${YELLOW}$*${NC}"; }
info() { echo -e "${GREEN}$*${NC}"; }
dim()  { echo -e "${DIM}$*${NC}"; }

cleanup() {
    if [[ -n "$CLEANUP_REMOTE" ]]; then
        warn "Removing $CLEANUP_REMOTE from origin, since its pull request was not opened..."
        git push origin --delete "$CLEANUP_REMOTE" 2>/dev/null || true
    fi
    if [[ -n "$CLEANUP_BRANCH" ]]; then
        warn "Cleaning up branch $CLEANUP_BRANCH..."
        git cherry-pick --abort 2>/dev/null || true
        git checkout dev 2>/dev/null || git checkout main 2>/dev/null || true
        git branch -D "$CLEANUP_BRANCH" 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

# A release branch left on origin by a release whose pull request was closed
# without merging would refuse this run's push. One with an open pull request is
# a release in progress, and stops the run.
clear_stale_release_branch() {
    local branch="$1"
    git ls-remote --exit-code --heads origin "$branch" &>/dev/null || return 0
    local open
    open=$(gh pr list --head "$branch" --state open --json url -q '.[0].url')
    [[ -n "$open" ]] && die "$branch already has an open pull request: $open"
    warn "  $branch is left on origin from a release that never merged; deleting it"
    git push origin --delete "$branch" || die "Could not delete the stale $branch from origin"
}

confirm() {
    if $AUTO_CONFIRM; then return 0; fi
    local msg="${1:-Continue?}"
    read -rp "$(echo -e "${YELLOW}${msg} [y/N]: ${NC}")" ans
    [[ "$ans" =~ ^[Yy]$ ]]
}

# ── Usage ────────────────────────────────────────────────────────────────────
usage() {
    cat <<'EOF'
Usage: scripts/promote.sh [OPTIONS]

Safely manage promotions from dev to main via pull requests.

Options:
  --patch              Promote + bump patch version (0.29.1 -> 0.29.2)
  --minor              Promote + bump minor version (0.29.1 -> 0.30.0)
  --major              Promote + bump major version (0.29.1 -> 1.0.0)
  --version X.Y.Z      Promote + set explicit version
  --cherry-pick SHA... Cherry-pick specific commits instead of full merge
  --rollback           Revert a release on main
  --docs               Promote ONLY the docs (docs/ + zensical.toml) to main —
                       no app code, no version bump, no changelog
  --force-native       Force-bump MIN_NATIVE_VERSION to the release version even if no
                       native change is auto-detected (CI will build a fresh APK/IPA).
                       Use when a native-affecting change landed only via pnpm-lock.yaml.
  --dry-run            Show what would happen without making changes
  -y                   Auto-confirm prompts
  -h, --help           Show this help

Examples:
  scripts/promote.sh                        # Promote dev to main (no release)
  scripts/promote.sh --dry-run              # Preview what would be promoted
  scripts/promote.sh --patch                # Promote + patch release
  scripts/promote.sh --minor                # Promote + minor release
  scripts/promote.sh --major                # Promote + major release
  scripts/promote.sh --patch --force-native # Patch release, force a native APK rebuild
  scripts/promote.sh --cherry-pick abc123   # Cherry-pick a hotfix to main
  scripts/promote.sh --rollback             # Revert the latest release
  scripts/promote.sh --rollback --version 0.29.1  # Revert a specific release
  scripts/promote.sh --docs                 # Promote docs-only changes to main
  scripts/promote.sh --docs --dry-run       # Preview the docs that would be promoted
EOF
}

# ── Argument parsing ─────────────────────────────────────────────────────────
parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --patch)  BUMP_TYPE="patch"; shift ;;
            --minor)  BUMP_TYPE="minor"; shift ;;
            --major)  BUMP_TYPE="major"; shift ;;
            --version)
                BUMP_TYPE="custom"
                CUSTOM_VERSION="${2:-}"
                [[ -z "$CUSTOM_VERSION" ]] && die "--version requires an argument (X.Y.Z)"
                shift 2
                ;;
            --cherry-pick)
                MODE="cherry-pick"
                shift
                while [[ $# -gt 0 && ! "$1" =~ ^-- ]]; do
                    CHERRY_SHAS+=("$1")
                    shift
                done
                [[ ${#CHERRY_SHAS[@]} -eq 0 ]] && die "--cherry-pick requires at least one SHA"
                ;;
            --rollback) MODE="rollback"; shift ;;
            --docs)     MODE="docs"; shift ;;
            --force-native) FORCE_NATIVE=true; shift ;;
            --dry-run)  DRY_RUN=true; shift ;;
            -y)         AUTO_CONFIRM=true; shift ;;
            -h|--help)  usage; exit 0 ;;
            *)          die "Unknown option: $1" ;;
        esac
    done

    # Determine mode from flags
    if [[ -z "$MODE" ]]; then
        if [[ -n "$BUMP_TYPE" ]]; then
            MODE="release"
        else
            MODE="promote"
        fi
    fi

    # Cherry-pick can also have a version bump
    if [[ "$MODE" == "cherry-pick" && -n "$BUMP_TYPE" ]]; then
        : # valid combination
    fi

    # --force-native only does something when a version is bumped (release, or cherry-pick
    # with a bump) — that's the only path that stamps MIN_NATIVE_VERSION. Reject it elsewhere
    # so it never silently no-ops.
    if $FORCE_NATIVE && [[ -z "$BUMP_TYPE" ]]; then
        die "--force-native requires a version bump (--patch/--minor/--major/--version)"
    fi

    # --docs is a standalone, version-free promotion.
    if [[ "$MODE" == "docs" && -n "$BUMP_TYPE" ]]; then
        die "--docs cannot be combined with a version bump"
    fi
}

# ── Version helpers ──────────────────────────────────────────────────────────
read_version() {
    [[ -f VERSION ]] || die "VERSION file not found (run from repo root)"
    cat VERSION | tr -d '[:space:]'
}

parse_version() {
    local ver="$1"
    [[ "$ver" =~ ^([0-9]+)\.([0-9]+)\.([0-9]+)$ ]] || die "Invalid version format: $ver"
    V_MAJOR="${BASH_REMATCH[1]}"
    V_MINOR="${BASH_REMATCH[2]}"
    V_PATCH="${BASH_REMATCH[3]}"
}

# Detect whether the native shell changed between two refs. OTA can only ship web assets,
# so when Capacitor plugins/config or the committed native projects change, the minimum
# native app version must move forward (old installs can't run the new web bundle) and CI
# must build a fresh APK/IPA. Used as an `if` condition, so it is exempt from `set -e`.
detect_native_change() {
    local base="$1" head="$2"
    # capacitor.config.ts changed?
    git diff --quiet "$base" "$head" -- frontend/capacitor.config.ts || return 0
    # committed native project files changed (Android/iOS source, Gradle, SPM, manifests)?
    git diff --quiet "$base" "$head" -- frontend/android frontend/ios || return 0
    # any @capacitor / @capacitor-community / @capgo / @capawesome plugin added/removed/bumped?
    # The Capawesome Electron platform is the desktop app's (detect_desktop_change).
    local re='"@(capacitor|capacitor-community|capgo|capawesome)/' desktop='"@capawesome/capacitor-electron"'
    local old new
    old=$(git show "$base:frontend/package.json" 2>/dev/null | grep -E "$re" | grep -vF "$desktop" | sort || true)
    new=$(git show "$head:frontend/package.json" 2>/dev/null | grep -E "$re" | grep -vF "$desktop" | sort || true)
    [[ "$old" != "$new" ]] && return 0
    return 1
}

# Detect whether the desktop app's shell changed between two refs: its Electron project and
# plugins, or the Capawesome Electron platform it runs on. It has a floor of its own,
# MIN_DESKTOP_VERSION, so a desktop change builds no APK and a phone change no installers.
detect_desktop_change() {
    local base="$1" head="$2"
    git diff --quiet "$base" "$head" -- frontend/electron || return 0
    local desktop='"@capawesome/capacitor-electron"'
    local old new
    old=$(git show "$base:frontend/package.json" 2>/dev/null | grep -F "$desktop" || true)
    new=$(git show "$head:frontend/package.json" 2>/dev/null | grep -F "$desktop" || true)
    [[ "$old" != "$new" ]] && return 0
    return 1
}

# Bump MIN_NATIVE_VERSION to the release version when the native shell changed since `base`
# (or when --force-native is passed). Stages the file so it lands in the version-bump commit.
# The committed value is the single signal CI keys off to decide whether to build the APK
# (see docker-publish.yml `decide` job).
stamp_min_native_version() {
    local base="$1" head="$2" new_version="$3"
    local current_min
    current_min=$(cat MIN_NATIVE_VERSION 2>/dev/null | tr -d '[:space:]' || echo "unknown")
    if $FORCE_NATIVE; then
        echo "$new_version" > MIN_NATIVE_VERSION
        git add MIN_NATIVE_VERSION
        warn "  --force-native → MIN_NATIVE_VERSION $current_min → $new_version (new APK/IPA REQUIRED; CI will build it)"
    elif detect_native_change "$base" "$head"; then
        echo "$new_version" > MIN_NATIVE_VERSION
        git add MIN_NATIVE_VERSION
        warn "  Native surface changed → MIN_NATIVE_VERSION $current_min → $new_version (new APK/IPA REQUIRED; CI will build it)"
    else
        info "  No native changes → MIN_NATIVE_VERSION stays $current_min (web-only OTA release, no APK build)"
    fi
    current_min=$(cat MIN_DESKTOP_VERSION 2>/dev/null | tr -d '[:space:]' || echo "unknown")
    if detect_desktop_change "$base" "$head"; then
        echo "$new_version" > MIN_DESKTOP_VERSION
        git add MIN_DESKTOP_VERSION
        warn "  Desktop app changed → MIN_DESKTOP_VERSION $current_min → $new_version (new installers REQUIRED; CI will build them)"
    else
        info "  No desktop changes → MIN_DESKTOP_VERSION stays $current_min (no installer build)"
    fi
}

# Report (without staging) whether MIN_NATIVE_VERSION would move, mirroring
# stamp_min_native_version's decision. Used in the release preview / dry run.
preview_min_native_version() {
    local base="$1" head="$2" new_version="$3"
    local current_min
    current_min=$(cat MIN_NATIVE_VERSION 2>/dev/null | tr -d '[:space:]' || echo "unknown")
    if $FORCE_NATIVE; then
        warn "  MIN_NATIVE_VERSION: $current_min → $new_version (forced via --force-native; CI builds APK/IPA)"
    elif detect_native_change "$base" "$head"; then
        warn "  MIN_NATIVE_VERSION: $current_min → $new_version (native change detected; CI builds APK/IPA)"
    else
        info "  MIN_NATIVE_VERSION: stays $current_min (web-only OTA release, no APK build)"
    fi
    current_min=$(cat MIN_DESKTOP_VERSION 2>/dev/null | tr -d '[:space:]' || echo "unknown")
    if detect_desktop_change "$base" "$head"; then
        warn "  MIN_DESKTOP_VERSION: $current_min → $new_version (desktop change detected; CI builds installers)"
    else
        info "  MIN_DESKTOP_VERSION: stays $current_min (no installer build)"
    fi
    echo ""
}

calc_new_version() {
    local current="$1"
    parse_version "$current"

    case "$BUMP_TYPE" in
        patch)  echo "${V_MAJOR}.${V_MINOR}.$((V_PATCH + 1))" ;;
        minor)  echo "${V_MAJOR}.$((V_MINOR + 1)).0" ;;
        major)  echo "$((V_MAJOR + 1)).0.0" ;;
        custom)
            [[ "$CUSTOM_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] \
                || die "Invalid version: $CUSTOM_VERSION (expected X.Y.Z)"
            echo "$CUSTOM_VERSION"
            ;;
    esac
}

# ── Pre-flight checks ───────────────────────────────────────────────────────
preflight() {
    echo -e "${BOLD}Pre-flight checks${NC}"
    echo "─────────────────────────────────────"

    # gh CLI
    command -v gh &>/dev/null || die "gh CLI not found — install from https://cli.github.com"
    gh auth status &>/dev/null || die "gh CLI not authenticated — run 'gh auth login'"
    info "  gh CLI authenticated"

    # Clean working directory
    [[ -z "$(git status --porcelain)" ]] || die "Working directory not clean — commit or stash changes"
    info "  Working directory clean"

    # Fetch latest
    git fetch origin --quiet
    info "  Fetched latest from origin"

    # Check code owner: whoever runs it, or in the Release workflow whoever
    # started this attempt of the run, a re-run included (the app's token
    # belongs to no user).
    local login
    if [[ -n "${GITHUB_ACTIONS:-}" ]]; then
        login="${GITHUB_TRIGGERING_ACTOR:-${GITHUB_ACTOR:?}}"
    else
        login=$(gh api user --jq '.login' 2>/dev/null) || die "Could not determine GitHub user"
    fi
    local is_owner=false
    local login_lower
    login_lower=$(echo "$login" | tr '[:upper:]' '[:lower:]')
    for owner in "${ALLOWED_OWNERS[@]}"; do
        if [[ "$(echo "$owner" | tr '[:upper:]' '[:lower:]')" == "$login_lower" ]]; then
            is_owner=true
            break
        fi
    done
    $is_owner || die "User '$login' is not a code owner (allowed: ${ALLOWED_OWNERS[*]})"
    info "  Code owner: $login"

    echo ""
}

check_branch_sync() {
    local branch="$1" remote="origin/$1"

    # Check local branch exists
    git rev-parse --verify "$branch" &>/dev/null \
        || die "Local branch '$branch' not found"

    # Check remote branch exists
    git rev-parse --verify "$remote" &>/dev/null \
        || die "Remote branch '$remote' not found"

    local local_sha remote_sha
    local_sha=$(git rev-parse "$branch")
    remote_sha=$(git rev-parse "$remote")

    if [[ "$local_sha" != "$remote_sha" ]]; then
        die "Local '$branch' ($local_sha) is out of sync with '$remote' ($remote_sha) — pull or push first"
    fi
    info "  $branch synced with origin"
}

check_ci_passing() {
    local branch="$1"
    dim "  Checking CI status on $branch..."
    local status
    status=$(gh api "repos/{owner}/{repo}/commits/$branch/status" --jq '.state' 2>/dev/null) || true

    case "$status" in
        success) info "  CI passing on $branch" ;;
        pending) warn "  CI is still running on $branch — proceed with caution" ;;
        failure) die "CI is failing on $branch — fix before promoting" ;;
        *)
            # Fall back to check-runs if commit status API has no data
            local conclusion
            conclusion=$(gh api "repos/{owner}/{repo}/commits/$branch/check-runs" \
                --jq '[.check_runs[].conclusion] | if length == 0 then "none" elif all(. == "success") then "success" elif any(. == "failure") then "failure" else "pending" end' 2>/dev/null) || true
            case "$conclusion" in
                success) info "  CI passing on $branch" ;;
                none)    warn "  No CI checks found on $branch — proceed with caution" ;;
                pending) warn "  CI is still running on $branch — proceed with caution" ;;
                failure) die "CI is failing on $branch — fix before promoting" ;;
            esac
            ;;
    esac
}

# ── Changelog helpers ────────────────────────────────────────────────────────
check_unreleased_content() {
    [[ -f CHANGELOG.md ]] || die "CHANGELOG.md not found"

    # Extract content between [Unreleased] and the next ## heading
    local content
    content=$(awk '/^## \[Unreleased\]/{found=1; next} /^## \[/{found=0} found{print}' CHANGELOG.md \
        | sed '/^[[:space:]]*$/d')

    if [[ -z "$content" ]]; then
        die "CHANGELOG.md [Unreleased] section is empty — add release notes first"
    fi
    info "  Changelog [Unreleased] has content"
}

# Regenerate the committed frontend API client so it matches the tree.
#
# Every generated file carries the VERSION in its header ("OpenAPI spec
# version: X.Y.Z"), so a version bump alone makes all 55 of them stale — and
# CI's "Check Generated Types" job filters on backend/ and orval config, so a
# bump that touches neither skips the job and ships the stale headers. A bump
# that DOES touch backend/ fails that job instead, on a drift that has nothing
# to do with the change being shipped. Both paths need this.
#
# Exports the OpenAPI spec from the backend (no running server needed) and
# hands it to generate-api.sh --from-spec, the same call the CI job makes.
# Errors are surfaced (no `2>/dev/null` suppression) so a broken regen fails
# the release rather than silently shipping stale types.
#
# $1: the version being released, or empty when no bump is happening (the
#     regen still runs, to catch a picked schema change whose generated
#     output was left behind on the source branch).
regenerate_api_types() {
    local version="${1:-}"

    [[ -f frontend/package.json ]] || return 0
    if ! command -v pnpm &>/dev/null; then
        warn "  pnpm not found — skipping API type regeneration"
        return 0
    fi

    dim "  Exporting OpenAPI spec and regenerating frontend types..."
    local spec
    spec="$(mktemp)"
    (cd backend && .venv/bin/python scripts/export_openapi.py "$spec")
    frontend/scripts/generate-api.sh --from-spec "$spec"
    rm -f "$spec"

    if git diff --quiet frontend/src/api/generated/; then
        return 0
    fi
    git add frontend/src/api/generated/
    if [[ -n "$version" ]]; then
        git commit -m "regenerate API types for v$version"
    else
        git commit -m "regenerate API types"
    fi
}

stamp_changelog() {
    local version="$1"
    local date="$2"

    # Replace "## [Unreleased]" with "## [Unreleased]\n\n## [X.Y.Z] - YYYY-MM-DD"
    # BSD sed (macOS) requires -i '' while GNU sed (Linux) uses -i
    if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' "s/^## \[Unreleased\]/## [Unreleased]\n\n## [$version] - $date/" CHANGELOG.md
    else
        sed -i "s/^## \[Unreleased\]/## [Unreleased]\n\n## [$version] - $date/" CHANGELOG.md
    fi
}

# One version's changelog section, for a PR body. The changelog names its
# pictures by repository path, which a PR body resolves against the PR's own
# URL, so they are pointed at the commit instead (a commit outlives the
# release branch, which is deleted once it merges).
changelog_section_for_body() {
    local version="$1"
    local ref="$2"
    local repo
    repo=$(gh repo view --json nameWithOwner -q .nameWithOwner)
    awk '/^## \[/{if(found)exit} /^## \['"$version"'\]/{found=1} found{print}' CHANGELOG.md \
        | sed -E "s#\]\((docs/[^)]+)\)#](https://github.com/$repo/raw/$ref/\1)#g"
}

preview_changelog() {
    local version="$1"
    echo -e "${CYAN}Changelog preview for $version:${NC}"
    awk '/^## \[Unreleased\]/{found=1; next} /^## \[/{found=0} found && NR<=20{print}' CHANGELOG.md
    echo ""
}

# ── Show commits ─────────────────────────────────────────────────────────────
show_commits() {
    local base="$1" head="$2"
    local count
    count=$(git rev-list --count "$base".."$head" 2>/dev/null) || count=0

    if [[ "$count" -eq 0 ]]; then
        die "No commits to promote ($base is up to date with $head)"
    fi

    echo -e "${BOLD}Commits to promote ($count):${NC}"
    git log --oneline --no-decorate -30 "$base".."$head"
    if [[ "$count" -gt 30 ]]; then
        dim "  ... and $((count - 30)) more"
    fi
    echo ""
}

# ── Modes ────────────────────────────────────────────────────────────────────
do_promote() {
    echo -e "${BOLD}Mode: Promote dev → main${NC}"
    echo "═══════════════════════════════════════"
    echo ""

    preflight
    check_branch_sync "dev"
    check_branch_sync "main"
    check_ci_passing "dev"
    echo ""

    show_commits "origin/main" "origin/dev"

    if $DRY_RUN; then
        info "Dry run complete — no changes made."
        return
    fi

    local branch="promote/$DATE"
    confirm "Create branch '$branch' and open PR to main?" || { echo "Aborted."; exit 0; }

    CLEANUP_BRANCH="$branch"
    git checkout -b "$branch" origin/dev
    git push -u origin "$branch"
    CLEANUP_BRANCH=""

    local pr_url
    pr_url=$(gh pr create \
        --base main \
        --head "$branch" \
        --title "Promote dev to main ($DATE)" \
        --body "$(cat <<EOF
## Summary
- Promotes current \`dev\` branch to \`main\`
- No version bump (code promotion only)

## Commits
$(git log --oneline -20 origin/main..HEAD)
EOF
)")

    info "PR created: $pr_url"
    git checkout dev
}

do_release() {
    local current new_version
    current=$(read_version)
    new_version=$(calc_new_version "$current")

    echo -e "${BOLD}Mode: Release v$new_version${NC}"
    echo "═══════════════════════════════════════"
    echo ""

    preflight
    check_branch_sync "dev"
    check_branch_sync "main"
    check_ci_passing "dev"
    check_unreleased_content

    # Check tag doesn't exist
    if git rev-parse "v$new_version" &>/dev/null; then
        die "Tag v$new_version already exists"
    fi
    info "  Tag v$new_version is available"
    echo ""

    show_commits "origin/main" "origin/dev"

    echo -e "${BOLD}Version: $current → $new_version${NC}"
    preview_changelog "$new_version"
    preview_min_native_version "origin/main" "origin/dev" "$new_version"

    if $DRY_RUN; then
        info "Dry run complete — no changes made."
        return
    fi

    confirm "Create release branch, bump version, and open PR?" || { echo "Aborted."; exit 0; }

    local branch="release/v$new_version"
    clear_stale_release_branch "$branch"
    CLEANUP_BRANCH="$branch"

    git checkout -b "$branch" origin/dev

    # Bump VERSION
    echo "$new_version" > VERSION

    # Stamp changelog
    stamp_changelog "$new_version" "$DATE"

    # Move the native min-version forward if the native shell changed since main.
    stamp_min_native_version "origin/main" "origin/dev" "$new_version"

    git add VERSION CHANGELOG.md
    git commit -m "bump version to $new_version"

    regenerate_api_types "$new_version"

    git push -u origin "$branch"
    CLEANUP_BRANCH=""
    CLEANUP_REMOTE="$branch"

    local pr_url
    pr_url=$(gh pr create \
        --base main \
        --head "$branch" \
        --title "Release v$new_version" \
        --label "release" \
        --body "$(cat <<EOF
## Summary
- Release **v$new_version** (was $current)
- Bumps VERSION and stamps CHANGELOG.md

## Changelog
$(changelog_section_for_body "$new_version" "$(git rev-parse HEAD)")

## Post-merge
Tag \`v$new_version\` will be created automatically, triggering Docker build + GitHub Release.
EOF
)")

    CLEANUP_REMOTE=""
    info "PR created: $pr_url"
    echo ""
    info "After merge:"
    info "  1. tag-release.yml auto-creates tag v$new_version"
    info "  2. docker-publish.yml builds + publishes Docker image"
    info "  3. GitHub Release + Discord notification"

    git checkout dev
}

# Copy the CHANGELOG entries a single commit added into the local [Unreleased]
# section. Used when a cherry-pick collides on CHANGELOG.md: main and dev hold
# different unreleased notes, so we keep main's and bring over only the entries
# belonging to the commit being picked.
port_changelog_entries() {
    local sha="$1"
    PORT_SHA="$sha" python3 - <<'PYEOF' || die "Could not port CHANGELOG entries for $sha"
import os, subprocess, sys

sha = os.environ["PORT_SHA"]


def show(ref):
    r = subprocess.run(["git", "show", f"{ref}:CHANGELOG.md"],
                       capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def unreleased(text):
    """Parse the [Unreleased] block into {section heading: [entry, ...]}."""
    out, section, buf = {}, None, []

    def flush():
        while buf and not buf[-1].strip():
            buf.pop()
        if buf and section is not None:
            out.setdefault(section, []).append("\n".join(buf))
        buf.clear()

    inside = False
    for line in text.splitlines():
        if line.startswith("## "):
            if inside:
                flush()
                break
            inside = line.strip().lower().startswith("## [unreleased]")
            continue
        if not inside:
            continue
        if line.startswith("### "):
            flush()
            section = line[4:].strip()
        elif line.startswith("- "):
            flush()
            buf.append(line)
        elif buf:
            buf.append(line)
    flush()
    return out


child, parent = unreleased(show(sha)), unreleased(show(sha + "^1"))
added = [(sec, e) for sec, entries in child.items() for e in entries
         if e not in set(parent.get(sec, []))]
if not added:
    sys.exit(0)

target = open("CHANGELOG.md").read().splitlines()
start = next((i for i, l in enumerate(target)
              if l.strip().lower().startswith("## [unreleased]")), None)
if start is None:
    sys.exit("CHANGELOG.md has no ## [Unreleased] section")
end = next((i for i in range(start + 1, len(target))
            if target[i].startswith("## ")), len(target))
block = target[start + 1:end]


def insert(block, section, entry):
    lines = entry.splitlines()
    head = next((i for i, l in enumerate(block)
                 if l.strip() == f"### {section}"), None)
    if head is None:
        while block and not block[-1].strip():
            block.pop()
        return block + ["", f"### {section}", ""] + lines
    stop = head + 1
    while stop < len(block) and not block[stop].startswith("### "):
        stop += 1
    while stop > head + 1 and not block[stop - 1].strip():
        stop -= 1
    if stop == head + 1:
        lines = [""] + lines
    return block[:stop] + lines + block[stop:]


for section, entry in added:
    block = insert(block, section, entry)

while block and not block[-1].strip():
    block.pop()
if block and block[0].strip():
    block.insert(0, "")
block.append("")

open("CHANGELOG.md", "w").write(
    "\n".join(target[:start + 1] + block + target[end:]) + "\n")
print("    ported %d CHANGELOG entr%s" % (len(added),
                                          "y" if len(added) == 1 else "ies"))
PYEOF
}

# Fold duplicate "### Section" headings in [Unreleased] into one, keeping the
# order they first appear. A cherry-pick that merges CHANGELOG.md cleanly can
# still leave two "### Fixed" blocks, since main and dev arrange them differently.
tidy_changelog() {
    [[ -f CHANGELOG.md ]] || return 0
    python3 - <<'PYEOF' || die "Could not tidy CHANGELOG.md"
lines = open("CHANGELOG.md").read().splitlines()
start = next((i for i, l in enumerate(lines)
              if l.strip().lower().startswith("## [unreleased]")), None)
if start is None:
    raise SystemExit(0)
end = next((i for i in range(start + 1, len(lines))
            if lines[i].startswith("## ")), len(lines))

order, sections, current = [], {}, None
for line in lines[start + 1:end]:
    if line.startswith("### "):
        current = line[4:].strip()
        if current not in sections:
            order.append(current)
            sections[current] = []
    elif current is not None:
        sections[current].append(line)

block = []
for head in order:
    body = []
    for line in sections[head]:
        if not line.strip() and (not body or not body[-1].strip()):
            continue
        body.append(line)
    while body and not body[-1].strip():
        body.pop()
    block += ["", f"### {head}", ""] + body
block.append("")

rebuilt = lines[:start + 1] + block + lines[end:]
if rebuilt != lines:
    open("CHANGELOG.md", "w").write("\n".join(rebuilt) + "\n")
    print("    tidied duplicate CHANGELOG sections")
PYEOF
}

# Tidy the changelog and fold the result into the commit just picked.
fold_changelog_into_head() {
    tidy_changelog
    if ! git diff --quiet -- CHANGELOG.md; then
        git add CHANGELOG.md
        git commit --amend --no-edit --no-verify >/dev/null
    fi
}

do_cherry_pick() {
    echo -e "${BOLD}Mode: Cherry-pick to main${NC}"
    echo "═══════════════════════════════════════"
    echo ""

    preflight
    check_branch_sync "main"
    echo ""

    # Validate all SHAs exist
    for sha in "${CHERRY_SHAS[@]}"; do
        git cat-file -t "$sha" &>/dev/null \
            || die "Commit $sha not found"
        dim "  $(git log --oneline -1 "$sha")"
    done
    echo ""

    local branch new_version=""
    if [[ -n "$BUMP_TYPE" ]]; then
        local current
        current=$(read_version)
        new_version=$(calc_new_version "$current")
        # tag-release.yml tags a merged PR only when its head branch starts with
        # "release/v", and reads the version from what follows. A version-bumping
        # hotfix is a release, so it has to carry that prefix or the merge lands a
        # bumped VERSION on main with no tag, no image, and no GitHub Release.
        branch="release/v$new_version"
        echo -e "${BOLD}Version: $current → $new_version${NC}"
    else
        branch="hotfix/$DATE"
    fi

    if $DRY_RUN; then
        echo -e "Would create branch ${CYAN}$branch${NC} from origin/main"
        echo "Would cherry-pick: ${CHERRY_SHAS[*]}"
        [[ -n "$new_version" ]] && echo "Would bump version to $new_version"
        info "Dry run complete — no changes made."
        return
    fi

    confirm "Cherry-pick ${#CHERRY_SHAS[@]} commit(s) to main via '$branch'?" || { echo "Aborted."; exit 0; }

    if [[ "$branch" == release/v* ]]; then clear_stale_release_branch "$branch"; fi
    CLEANUP_BRANCH="$branch"
    git checkout -b "$branch" origin/main

    for sha in "${CHERRY_SHAS[@]}"; do
        # A merge commit (a PR merged without squashing) needs an explicit
        # mainline; -m 1 replays the diff it introduced onto its first parent.
        local pick_args=("$sha")
        if [[ $(git rev-list --no-walk --count --merges "$sha") -eq 1 ]]; then
            pick_args=(-m 1 "$sha")
            dim "  $(git log --oneline -1 "$sha") (merge — replaying onto first parent)"
        fi

        if git cherry-pick "${pick_args[@]}"; then
            fold_changelog_into_head
            continue
        fi

        # CHANGELOG.md conflicts on nearly every hotfix, because main and dev
        # carry different unreleased notes. Keep main's and port over just the
        # entries this commit added; anything else is a real conflict.
        if [[ "$(git diff --name-only --diff-filter=U)" == "CHANGELOG.md" ]]; then
            dim "    CHANGELOG.md conflict — keeping main's and porting this commit's entries"
            git checkout --ours -- CHANGELOG.md
            port_changelog_entries "$sha"
            git add CHANGELOG.md
            GIT_EDITOR=true git cherry-pick --continue \
                || die "Cherry-pick failed for $sha — resolve conflicts and retry"
            fold_changelog_into_head
        else
            git cherry-pick --abort 2>/dev/null || true
            die "Cherry-pick failed for $sha — resolve conflicts and retry"
        fi
    done

    if [[ -n "$new_version" ]]; then
        echo "$new_version" > VERSION
        if [[ -f CHANGELOG.md ]]; then
            stamp_changelog "$new_version" "$DATE"
            git add VERSION CHANGELOG.md
        else
            git add VERSION
        fi
        # Move the native min-version forward if the cherry-picked changes touch the shell.
        stamp_min_native_version "origin/main" "HEAD" "$new_version"
        git commit -m "bump version to $new_version"
    fi

    # Same release bookkeeping the release mode does: the picked commits may
    # carry schema changes whose generated output stayed behind, and a bump
    # restamps the version in every generated header.
    regenerate_api_types "$new_version"

    git push -u origin "$branch"
    CLEANUP_BRANCH=""
    if [[ "$branch" == release/v* ]]; then CLEANUP_REMOTE="$branch"; fi

    local title="Hotfix: cherry-pick to main"
    [[ -n "$new_version" ]] && title="Hotfix v$new_version"

    local pr_url
    pr_url=$(gh pr create \
        --base main \
        --head "$branch" \
        --title "$title" \
        --body "$(cat <<EOF
## Summary
Cherry-pick hotfix to main.

## Commits
$(for sha in "${CHERRY_SHAS[@]}"; do git log --oneline -1 "$sha"; done)
$(if [[ -n "$new_version" ]]; then echo -e "\n## Version\nBumped to **v$new_version**\n\nTag will be created automatically after merge."; fi)
EOF
)")

    CLEANUP_REMOTE=""
    info "PR created: $pr_url"
    git checkout dev
}

do_rollback() {
    echo -e "${BOLD}Mode: Rollback${NC}"
    echo "═══════════════════════════════════════"
    echo ""

    preflight
    check_branch_sync "main"
    echo ""

    # Determine which version to roll back
    local target_tag
    if [[ "$BUMP_TYPE" == "custom" && -n "$CUSTOM_VERSION" ]]; then
        target_tag="v$CUSTOM_VERSION"
        git rev-parse "$target_tag" &>/dev/null || die "Tag $target_tag not found"
    else
        target_tag=$(git describe --tags --abbrev=0 origin/main 2>/dev/null) \
            || die "No tags found on main"
    fi

    info "  Rolling back: $target_tag"

    # Find the merge commit for this tag on main
    local tag_sha merge_sha
    tag_sha=$(git rev-parse "$target_tag")

    # The tag points to a commit; find the merge commit on main that introduced it
    merge_sha=$(git log --merges --ancestry-path --oneline "${tag_sha}^..origin/main" \
        --format="%H" 2>/dev/null | tail -1)

    # If no merge commit found, the tag commit itself might be on main
    if [[ -z "$merge_sha" ]]; then
        # Check if the tagged commit is directly on main (fast-forward merge)
        if git merge-base --is-ancestor "$tag_sha" origin/main 2>/dev/null; then
            # Look for the most recent merge commit before the tag
            merge_sha=$(git log --merges --oneline origin/main --format="%H" \
                -1 --ancestry-path "$tag_sha^..origin/main" 2>/dev/null) || true
        fi
    fi

    # Last resort: try to find the merge commit that has the tag as a parent
    if [[ -z "$merge_sha" ]]; then
        merge_sha=$(git log --merges --oneline origin/main --format="%H" \
            --grep="release/$(echo "$target_tag" | sed 's/^v/v/')" 2>/dev/null | head -1) || true
    fi

    # If still nothing, use the tag commit itself
    if [[ -z "$merge_sha" ]]; then
        merge_sha="$tag_sha"
        warn "  Could not find merge commit — will revert the tagged commit directly"
    else
        info "  Merge commit: $(git log --oneline -1 "$merge_sha")"
    fi

    local branch="rollback/$target_tag"

    if $DRY_RUN; then
        echo -e "Would create branch ${CYAN}$branch${NC} from origin/main"
        echo "Would revert commit: $(git log --oneline -1 "$merge_sha")"
        info "Dry run complete — no changes made."
        return
    fi

    confirm "Revert $target_tag on main via '$branch'?" || { echo "Aborted."; exit 0; }

    CLEANUP_BRANCH="$branch"
    git checkout -b "$branch" origin/main

    # Revert — use -m 1 for merge commits, plain revert for non-merge
    if git cat-file -p "$merge_sha" | grep -q "^parent.*parent"; then
        git revert -m 1 --no-edit "$merge_sha"
    else
        git revert --no-edit "$merge_sha"
    fi

    git push -u origin "$branch"
    CLEANUP_BRANCH=""

    local pr_url
    pr_url=$(gh pr create \
        --base main \
        --head "$branch" \
        --title "Rollback $target_tag" \
        --body "$(cat <<EOF
## Summary
Reverts the release **$target_tag** on main.

## Reverted commit
\`$(git log --oneline -1 "$merge_sha")\`

## Follow-up
- [ ] Investigate the issue on \`dev\`
- [ ] Fix and create a new patch release when ready
EOF
)")

    info "PR created: $pr_url"
    echo ""
    warn "Remember: follow up with a patch release after fixing the issue on dev."
    git checkout dev
}

# ── Docs-only promotion ──────────────────────────────────────────────────────
# The documentation site that gets promoted on its own. zensical.toml is the docs
# build config (nav/theme), so it travels with docs/ to keep main's build coherent.
DOCS_PATHS=("docs" "zensical.toml")

# Sync just the docs site from dev to main via a PR — no app code, no version bump,
# no changelog. Deletions inside docs/ are captured too, so main's docs tree ends up
# matching dev's exactly.
do_docs() {
    echo -e "${BOLD}Mode: Promote docs → main${NC}"
    echo "═══════════════════════════════════════"
    echo ""

    preflight
    check_branch_sync "dev"
    check_branch_sync "main"
    echo ""

    # Anything to promote?
    if git diff --quiet "origin/main" "origin/dev" -- "${DOCS_PATHS[@]}"; then
        die "No documentation changes between main and dev (${DOCS_PATHS[*]})"
    fi

    echo -e "${BOLD}Documentation changes (main → dev):${NC}"
    git diff --stat "origin/main" "origin/dev" -- "${DOCS_PATHS[@]}"
    echo ""

    if $DRY_RUN; then
        info "Dry run complete — no changes made."
        return
    fi

    confirm "Open a docs-only PR to main (no app code, no version bump)?" || { echo "Aborted."; exit 0; }

    local branch="docs/$DATE"
    CLEANUP_BRANCH="$branch"
    git checkout -b "$branch" origin/main

    # Make docs/ match dev exactly (added, changed AND removed files), then bring in
    # the docs build config.
    rm -rf docs
    git checkout origin/dev -- docs
    git checkout origin/dev -- zensical.toml
    git add -A docs zensical.toml

    # Safety net: refuse if anything outside the docs site got staged.
    local stray
    stray=$(git diff --cached --name-only | grep -vE '^docs/|^zensical\.toml$' || true)
    [[ -n "$stray" ]] && die "Refusing — non-docs files are staged:\n$stray"

    if git diff --cached --quiet; then
        die "No documentation changes to commit"
    fi

    git commit -m "docs: sync documentation to main ($DATE)"
    git push -u origin "$branch"
    CLEANUP_BRANCH=""

    local pr_url
    pr_url=$(gh pr create \
        --base main \
        --head "$branch" \
        --title "Docs update ($DATE)" \
        --body "$(cat <<EOF
## Summary
- Syncs the documentation site (\`docs/\` + \`zensical.toml\`) from \`dev\` to \`main\`.
- **Docs only** — no app code, no version bump, no changelog stamp.

## Changed files
$(git diff --stat "origin/main"..HEAD -- "${DOCS_PATHS[@]}")
EOF
)")

    info "PR created: $pr_url"
    info "Merging republishes the docs site (GitHub Pages) from main."
    git checkout dev
}

# ── Main ─────────────────────────────────────────────────────────────────────
main() {
    # Ensure we're at the repo root
    cd "$(git rev-parse --show-toplevel)" || die "Not in a git repository"

    parse_args "$@"

    echo ""
    case "$MODE" in
        promote)     do_promote ;;
        release)     do_release ;;
        cherry-pick) do_cherry_pick ;;
        rollback)    do_rollback ;;
        docs)        do_docs ;;
        *)           die "Unknown mode: $MODE" ;;
    esac
}

main "$@"
