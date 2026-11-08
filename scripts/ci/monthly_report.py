"""A month of CI, read from the GitHub API, as Markdown for a run's summary page.

    GH_TOKEN=... GITHUB_REPOSITORY=owner/repo \\
        python3 scripts/ci/monthly_report.py [YYYY-MM] >> "$GITHUB_STEP_SUMMARY"

Without a month it reports the one before the current one. It reports:

- releases shipped, and those that needed a fix: a patch release followed
  within ``FIX_WINDOW``, or an issue labelled ``regression`` names the version
  (the change failure rate, target well under 30%);
- time from a push to ``dev`` until ``dev`` is green;
- runs that failed and then passed on a re-run of the same commit, which is
  what a flake or an infrastructure fault looks like from here;
- how long each gate takes.

Standard library only, like the other scripts in this directory.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from statistics import median

API = "https://api.github.com"

#: A release followed by a patch inside this window needed a fix. The same
#: window as the soak before ``stable`` (promote-stable.yml).
FIX_WINDOW = timedelta(hours=72)

#: The gates: the workflow, and the event and branch that make a run that
#: gate's (``None`` for any branch).
GATES = (
    ("Pull request", "ci.yml", "pull_request", None),
    ("Integration (dev)", "ci.yml", "push", r"dev"),
    ("Release candidate", "release-candidate.yml", "push", r"release/v.+"),
    ("Nightly", "nightly.yml", "workflow_dispatch", r"dev"),
)

#: How far past the month runs are read, to find the green run that ends a
#: wait which started in it.
LOOK_AHEAD = timedelta(days=7)

VERSION_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value)


def month_bounds(month: str) -> tuple[datetime, datetime]:
    year, number = (int(part) for part in month.split("-"))
    start = datetime(year, number, 1, tzinfo=UTC)
    end = datetime(year + number // 12, number % 12 + 1, 1, tzinfo=UTC)
    return start, end


def weeks(start: datetime, end: datetime) -> list[str]:
    """The month as week-long ``created`` filters: the runs API returns at
    most 1,000 runs for one query, and a month of CI is more than that."""
    windows = []
    day = start.date()
    while day < end.date():
        last = min(day + timedelta(days=6), end.date() - timedelta(days=1))
        windows.append(f"{day:%Y-%m-%d}..{last:%Y-%m-%d}")
        day = last + timedelta(days=1)
    return windows


def previous_month(today: date) -> str:
    first = today.replace(day=1) - timedelta(days=1)
    return f"{first.year:04d}-{first.month:02d}"


@dataclass(frozen=True)
class Release:
    tag: str
    published: datetime

    @property
    def version(self) -> tuple[int, int, int]:
        match = VERSION_TAG.match(self.tag)
        assert match, self.tag
        major, minor, patch = match.groups()
        return int(major), int(minor), int(patch)


def needed_a_fix(releases: list[Release], regressions: set[str]) -> dict[str, str]:
    """Each release that needed one, and why: a patch on the same minor line
    within the window, or a regression reported against it."""
    reasons: dict[str, str] = {}
    for release in releases:
        major, minor, patch = release.version
        followed = [
            later
            for later in releases
            if later.version[:2] == (major, minor)
            and later.version[2] > patch
            and release.published < later.published <= release.published + FIX_WINDOW
        ]
        if followed:
            first = min(followed, key=lambda later: later.published)
            hours = (first.published - release.published).total_seconds() / 3600
            reasons[release.tag] = f"{first.tag} {hours:.0f} h later"
        elif release.tag.removeprefix("v") in regressions:
            reasons[release.tag] = "a regression was reported against it"
    return reasons


@dataclass(frozen=True)
class Run:
    created: datetime
    updated: datetime
    conclusion: str | None


def merge_to_green(runs: list[Run], start: datetime, end: datetime) -> list[timedelta]:
    """For each push between ``start`` and ``end``, how long until a run on
    that branch, at or after it, finished green; ``runs`` may go past ``end``
    to find it. A push whose run was cancelled or failed waits for the next one
    that passed; one with none yet is left out."""
    ordered = sorted(runs, key=lambda run: run.created)
    waits = []
    for index, run in enumerate(ordered):
        if not start <= run.created < end:
            continue
        green = next(
            (later for later in ordered[index:] if later.conclusion == "success"),
            None,
        )
        if green is not None:
            waits.append(green.updated - run.created)
    return waits


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(fraction * len(ordered)))]


def minutes(delta: timedelta | float) -> str:
    seconds = delta.total_seconds() if isinstance(delta, timedelta) else delta
    return f"{seconds / 60:.0f} min" if seconds < 5400 else f"{seconds / 3600:.1f} h"


# --- The API ------------------------------------------------------------------


def get(path: str, params: dict[str, str] | None = None) -> list[dict] | dict:
    """One page, or every page of a list (the ``Link`` header's ``next``)."""
    url = f"{API}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    items: list[dict] = []
    while url:
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {os.environ['GH_TOKEN']}",
                "Accept": "application/vnd.github+json",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.load(response)
            links = response.headers.get("Link", "")
        if isinstance(body, dict) and "workflow_runs" in body:
            body = body["workflow_runs"]
        if not isinstance(body, list):
            return body
        items.extend(body)
        match = re.search(r'<([^>]+)>;\s*rel="next"', links)
        url = match.group(1) if match else ""
    return items


def report(repo: str, month: str) -> str:
    start, end = month_bounds(month)
    lines = [f"## CI in {month}", ""]

    # Releases. A fix can land in the next month, so read past the end.
    releases = sorted(
        (
            Release(r["tag_name"], parse_time(r["published_at"]))
            for r in get(f"/repos/{repo}/releases", {"per_page": "100"})
            if r.get("published_at") and VERSION_TAG.match(r["tag_name"])
        ),
        key=lambda release: release.published,
    )
    shipped = [r for r in releases if start <= r.published < end]
    regressions = {
        label["name"].removeprefix("version: ")
        for issue in get(
            f"/repos/{repo}/issues",
            {"labels": "regression", "state": "all", "per_page": "100"},
        )
        for label in issue["labels"]
        if label["name"].startswith("version: ")
    }
    fixes = needed_a_fix(releases, regressions)
    failed = [r for r in shipped if r.tag in fixes]
    lines += ["### Releases", ""]
    if shipped:
        rate = 100 * len(failed) / len(shipped)
        lines.append(
            f"**{len(shipped)} shipped, {len(failed)} needed a fix "
            f"({rate:.0f}%; target well under 30%).**"
        )
        lines += [f"- {r.tag}: {fixes[r.tag]}" for r in failed]
    else:
        lines.append("None shipped.")
    lines.append("")

    # Each gate's runs this month.
    read: dict[str, list[dict]] = {}
    capped = []
    for _, workflow, _, _ in GATES:
        if workflow in read:
            continue
        read[workflow] = []
        for window in weeks(start, end + LOOK_AHEAD):
            try:
                week = get(
                    f"/repos/{repo}/actions/workflows/{workflow}/runs",
                    {"created": window, "per_page": "100"},
                )
            except urllib.error.HTTPError as error:
                if error.code != 404:  # not on the default branch yet
                    raise
                break
            if len(week) >= 1000:
                capped.append(f"{workflow} {window}")
            read[workflow] += week
    runs_by_file = {
        workflow: [r for r in runs if start <= parse_time(r["created_at"]) < end]
        for workflow, runs in read.items()
    }
    if capped:
        lines += [
            (
                "> **Undercounted:** the runs API stops at 1,000 runs a query, "
                f"and these weeks reached it: {', '.join(capped)}."
            ),
            "",
        ]

    dev_pushes = [
        Run(
            parse_time(r["created_at"]),
            parse_time(r["updated_at"]),
            r["conclusion"],
        )
        for r in read["ci.yml"]
        if r["event"] == "push" and r["head_branch"] == "dev"
    ]
    waits = [wait.total_seconds() for wait in merge_to_green(dev_pushes, start, end)]
    lines += ["### From a push to dev until dev is green", ""]
    if waits:
        lines.append(
            f"Median {minutes(median(waits))}, 90th percentile "
            f"{minutes(percentile(waits, 0.9))}, longest {minutes(max(waits))}, "
            f"over {len(waits)} pushes."
        )
    else:
        lines.append("No pushes to dev with a green run after them.")
    lines.append("")

    # Failed, then passed on a re-run of the same commit.
    rerun = []
    for workflow, runs in runs_by_file.items():
        for r in runs:
            if r["run_attempt"] > 1 and r["conclusion"] == "success":
                first = get(f"/repos/{repo}/actions/runs/{r['id']}/attempts/1")
                if isinstance(first, dict) and first["conclusion"] == "failure":
                    rerun.append(f"[{workflow} #{r['run_number']}]({r['html_url']})")
    finished = sum(1 for runs in runs_by_file.values() for r in runs if r["conclusion"])
    lines += ["### Red, then green on a re-run of the same commit", ""]
    lines.append(f"{len(rerun)} of {finished} finished runs.")
    lines += [f"- {link}" for link in rerun]
    lines.append("")

    lines += ["### Time in each gate", "", "| Gate | Runs | Median | 90th percentile |"]
    lines.append("|---|---|---|---|")
    for name, workflow, event, branch in GATES:
        took = [
            (
                parse_time(r["updated_at"]) - parse_time(r["run_started_at"])
            ).total_seconds()
            for r in runs_by_file[workflow]
            if r["event"] == event
            and (branch is None or re.fullmatch(branch, r["head_branch"] or ""))
            and r["conclusion"] in ("success", "failure")
            and r.get("run_started_at")
        ]
        if took:
            lines.append(
                f"| {name} | {len(took)} | {minutes(median(took))} "
                f"| {minutes(percentile(took, 0.9))} |"
            )
        else:
            lines.append(f"| {name} | 0 | | |")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    month = argv[1] if len(argv) > 1 and argv[1] else previous_month(date.today())
    print(report(os.environ["GITHUB_REPOSITORY"], month))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
