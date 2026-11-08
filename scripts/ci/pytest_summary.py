"""Turn a pytest log into a short Markdown summary for a CI run's summary page.

    python3 scripts/ci/pytest_summary.py pytest.log ["Heading"] >> "$GITHUB_STEP_SUMMARY"

Reads the output of a pytest-xdist run (``-v -ra --durations=N``) and writes
the result line, the failures grouped by worker, each failure with its short
reason, and the slowest tests. Prints nothing when the log does not exist,
so it can run after a job that stopped before the tests.

Standard library only: it runs before, and without, the backend's
dependencies.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

ANSI = re.compile(r"\x1b\[[0-9;]*m")
# "[gw3] [ 45%] FAILED app/x_test.py::test_y" (xdist, -v)
WORKER_OUTCOME = re.compile(r"^\[(gw\d+)\] \[\s*\d+%\] (FAILED|ERROR) (\S+)")
# "FAILED app/x_test.py::test_y - AssertionError: ..." (the -ra summary)
SHORT_SUMMARY = re.compile(r"^(FAILED|ERROR) (\S+)(?: - (.*))?$")
# "12.34s call     app/x_test.py::test_y" (--durations)
DURATION = re.compile(r"^(\d+\.\d+)s (setup|call|teardown)\s+(\S+)$")
# "===== 9637 passed, 265 skipped, 1 error in 2659.65s (0:44:19) ====="
RESULT = re.compile(r"^=+ (.*\d+ \w+.* in [\d.]+s.*?) =+$")

#: How many failures on one worker, and no other, reads as one poisoned
#: connection rather than separate bugs.
ONE_WORKER_THRESHOLD = 3
SLOWEST_SHOWN = 10


@dataclass
class Run:
    result: str | None = None
    workers: Counter[str] = field(default_factory=Counter)
    failures: dict[str, str] = field(default_factory=dict)
    slowest: list[tuple[float, str, str]] = field(default_factory=list)


def parse(text: str) -> Run:
    run = Run()
    in_durations = False
    for raw in text.splitlines():
        line = ANSI.sub("", raw).rstrip()
        if match := WORKER_OUTCOME.match(line):
            run.workers[match[1]] += 1
            continue
        if "slowest" in line and "durations" in line and line.startswith("="):
            in_durations = True
            continue
        if in_durations:
            if match := DURATION.match(line):
                run.slowest.append((float(match[1]), match[2], match[3]))
                continue
            if line.startswith("="):
                in_durations = False
        if match := SHORT_SUMMARY.match(line):
            run.failures[match[2]] = (match[3] or match[1].lower()).strip()
            continue
        if match := RESULT.match(line):
            run.result = match[1]
    return run


def _reason(text: str, limit: int = 240) -> str:
    """One failure's reason as Markdown: `<class ...>` would render as a tag."""
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return text.replace("&", "&amp;").replace("<", "&lt;")


def render(run: Run, title: str = "Backend tests") -> str:
    out = [f"### {title}", ""]
    out.append(run.result or "No result line: the run stopped before pytest finished.")
    if run.workers:
        total = sum(run.workers.values())
        out += ["", "#### Failures by worker", "", "| Worker | Failures |", "|---|---|"]
        out += [f"| {w} | {n} |" for w, n in sorted(run.workers.items())]
        if len(run.workers) == 1 and total >= ONE_WORKER_THRESHOLD:
            worker = next(iter(run.workers))
            out += [
                "",
                (
                    f"All {total} failures are on {worker}. That usually means one test left "
                    "its database connection in a bad state for the tests after it on that "
                    "worker: look at its first failure, not each one."
                ),
            ]
    if run.failures:
        out += ["", "#### Failures", ""]
        out += [
            f"- `{test}`: {_reason(reason)}" for test, reason in run.failures.items()
        ]
    if run.slowest:
        out += [
            "",
            "#### Slowest tests",
            "",
            "| Time | Phase | Test |",
            "|---|---|---|",
        ]
        for seconds, phase, test in sorted(run.slowest, reverse=True)[:SLOWEST_SHOWN]:
            out.append(f"| {seconds:.1f}s | {phase} | `{test}` |")
    return "\n".join(out) + "\n"


def main(argv: list[str]) -> int:
    path = Path(argv[1])
    if not path.exists():
        return 0
    title = argv[2] if len(argv) > 2 else "Backend tests"
    sys.stdout.write(render(parse(path.read_text(errors="replace")), title))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
