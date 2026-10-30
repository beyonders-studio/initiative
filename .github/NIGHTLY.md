# Nightly runs on forks

The `fix/skip-fork-nightlies` change keeps scheduled Nightly workloads in
`beyonders-studio/initiative`, while retaining intentional test runs in forks.
The workflow change is confined to `.github/workflows/nightly.yml`; the shared
Browser Journeys workflow keeps its existing behavior for its other callers.

## Execution policy

- **Scheduled upstream runs:** all three backend matrix variants, frontend,
  and Browser Journeys remain eligible to run.
- **Scheduled fork runs:** backend, frontend, and the reusable journeys call
  are skipped before their workloads start. Report is independently skipped.
  GitHub may still create a scheduled workflow record containing skipped jobs.
- **Manual runs:** upstream and forks can run the workloads on the selected
  branch. Only upstream's `dev` run manages the nightly issue.
- **Pull requests:** the nightly's existing path and target-branch filters
  remain. Backend and frontend run; Browser Journeys retains its existing
  `journeys` label requirement. Report never manages issues for PR runs,
  including PRs from forks targeting upstream.

Report still needs backend, frontend, and journeys. Its `!cancelled()` status
check permits reporting a failed night, even when a dependency failed or was
skipped. The report therefore has its own repository guard; relying on skipped
workloads alone would allow it to run on a fork. The failure aggregation and
issue open/comment/close commands are unchanged.

## Verification and handoff

The reported fork run
[41065593494](https://github.com/Dunky13/initiative/actions/runs/41065593494)
was rechecked on 2026-10-30: all five workload jobs succeeded; Report failed
because issues were disabled, with `FAILED=false`.

Local validation used `actionlint` 1.7.12 on Nightly and Browser Journeys, plus
GitHub's `@actions/expressions` 0.3.61 against the parsed workflow conditions.
The condition harness checked upstream, the user's fork, an upstream-owner
lookalike repository, and another fork; scheduled/manual/PR events; `dev` and
feature refs; journeys labels; every combination of success/failure/skipped/
cancelled dependency results; and run cancellation. The refreshed base failed
816 of 9,415 assertions; the candidate passed 9,416, including a check that all
other parsed workflow fields were unchanged. `git diff --check` passed.
`scripts/ci/check` reported no backend or frontend changes to check.

These are local expression and source checks, not a live scheduler test.
GitHub documents
[job conditions](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-jobs-with-conditions),
[status-check defaults](https://docs.github.com/en/actions/reference/workflows-and-actions/expressions#status-check-functions),
and [conditions on reusable calls](https://docs.github.com/en/actions/reference/workflows-and-actions/reusing-workflow-configurations#supported-keywords-for-jobs-that-call-a-reusable-workflow).

After merge, a fork must incorporate the change into its default branch for
its scheduled Nightly to use the guards. Verify the next scheduled fork run
has no executed workloads or report, and that upstream's next scheduled run
retains its matrix, frontend, journeys, and reporting. PR checks exercise the
PR event, not the scheduled event. No repository Actions settings, release
pipelines, or Security/Trivy policy are changed by this fix.
