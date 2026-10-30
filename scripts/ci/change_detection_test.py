"""Runs ci.yml's Detect Changes step against sample diffs.

Test selection only knows code a test has already run, so a change it cannot
see has to run every backend test. These cases hold the step to that: each one
commits a change to a throwaway repository and reads the mode the step chose.
Run: python3 scripts/ci/change_detection_test.py
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import tempfile
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/ci.yml"

# Only the throwaway repository's own config applies.
GIT_ENV = {
    **os.environ,
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
}


def _diff_step() -> str:
    steps = yaml.safe_load(WORKFLOW.read_text())["jobs"]["changes"]["steps"]
    for step in steps:
        if step.get("id") == "diff":
            return step["run"]
    raise AssertionError("ci.yml's changes job has no step with id 'diff'")


def detect(
    changed: list[str],
    event: str = "pull_request",
    base_ref: str = "dev",
    head_ref: str = "feature",
    same_repo: bool = True,
    tested: str = "",
    fork: bool = False,
) -> dict[str, str]:
    """Commit ``changed`` on top of ``origin/<base_ref>`` and return the
    step's outputs."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = pathlib.Path(tmp)

        def git(*args: str) -> str:
            return subprocess.run(
                ["git", *args],
                cwd=repo,
                env=GIT_ENV,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()

        git("init", "-q")
        git("config", "user.name", "tester")
        git("config", "user.email", "tester@example.com")
        (repo / "README.md").write_text("base\n")
        git("add", ".")
        git("commit", "-qm", "base")
        base = git("rev-parse", "HEAD")
        git("update-ref", f"refs/remotes/origin/{base_ref}", base)
        for path in changed:
            (repo / path).parent.mkdir(parents=True, exist_ok=True)
            (repo / path).write_text("changed\n")
        git("add", ".")
        git("commit", "-qm", "change")

        output = repo.parent / f"{repo.name}.output"
        summary = repo.parent / f"{repo.name}.summary"
        try:
            # GitHub's default shell for a run step.
            subprocess.run(
                [
                    "bash",
                    "--noprofile",
                    "--norc",
                    "-eo",
                    "pipefail",
                    "-c",
                    _diff_step(),
                ],
                cwd=repo,
                env={
                    **GIT_ENV,
                    "EVENT": event,
                    "BASE_REF": base_ref,
                    "HEAD_REF": head_ref,
                    "SAME_REPO": str(same_repo).lower(),
                    "FORK": str(fork).lower(),
                    "BEFORE": base,
                    "TESTED": tested,
                    "GITHUB_OUTPUT": str(output),
                    "GITHUB_STEP_SUMMARY": str(summary),
                },
                check=True,
                capture_output=True,
                text=True,
            )
            return dict(line.split("=", 1) for line in output.read_text().splitlines())
        finally:
            output.unlink(missing_ok=True)
            summary.unlink(missing_ok=True)


class BackendModeTest(unittest.TestCase):
    def assertMode(self, changed: list[str], mode: str, event: str = "pull_request"):
        with self.subTest(changed=changed, event=event):
            self.assertEqual(detect(changed, event).get("backend_mode"), mode)

    def test_changes_selection_cannot_see_run_every_test(self) -> None:
        for path in [
            "backend/alembic/versions/20260930_0420_example.py",
            "backend/app/db/session.py",
            "backend/app/testing/factories.py",
            "backend/app/core/capabilities.py",
            "backend/app/core/config.py",
            "backend/conftest.py",
            "backend/pytest.ini",
            "backend/pyproject.toml",
            "backend/uv.lock",
            "backend/scripts/ci/example.py",
            "backend/app/services/example.sql",
            ".github/workflows/ci.yml",
            ".github/actions/setup-backend/action.yml",
            ".github/actions/test-database/action.yml",
        ]:
            self.assertMode([path], "full")

    def test_an_ordinary_backend_change_selects_tests(self) -> None:
        self.assertMode(["backend/app/services/guilds.py"], "select")

    def test_one_unseen_path_outweighs_the_rest(self) -> None:
        self.assertMode(
            ["backend/app/services/guilds.py", "backend/app/db/session.py"], "full"
        )

    def test_a_change_outside_the_backend_runs_the_core(self) -> None:
        self.assertMode(["frontend/src/main.tsx"], "core")

    def test_documentation_skips_the_backend(self) -> None:
        outputs = detect(["docs/en/index.md", "CHANGELOG.md"])
        self.assertEqual(outputs.get("backend"), "false")

    def test_an_integration_push_runs_every_test(self) -> None:
        self.assertMode(["backend/app/services/guilds.py"], "full", event="push")


class TestedTreeTest(unittest.TestCase):
    def test_an_exact_tree_already_tested_runs_nothing(self) -> None:
        for event in ["pull_request", "push"]:
            with self.subTest(event=event):
                outputs = detect(["backend/app/db/session.py"], event, tested="raw")
                self.assertEqual(outputs.get("backend"), "false")
                self.assertEqual(outputs.get("frontend"), "false")

    def test_a_release_of_a_tested_tree_runs_the_core(self) -> None:
        outputs = detect(
            ["VERSION", "CHANGELOG.md"],
            base_ref="main",
            head_ref="release/v1.2.3",
            tested="tree",
        )
        self.assertEqual(outputs.get("backend_mode"), "core")
        self.assertEqual(outputs.get("alembic"), "false")
        self.assertEqual(outputs.get("frontend"), "false")

    def test_an_untested_tree_runs_as_usual(self) -> None:
        self.assertEqual(
            detect(["backend/app/services/guilds.py"], "push").get("backend_mode"),
            "full",
        )


class TreeIdTest(unittest.TestCase):
    """scripts/ci/tested_tree.sh names a tree with and without a release's files."""

    def ids(self, files: dict[str, str]) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp:
            repo = pathlib.Path(tmp)

            def git(*args: str) -> None:
                subprocess.run(
                    ["git", *args],
                    cwd=repo,
                    env=GIT_ENV,
                    check=True,
                    capture_output=True,
                )

            git("init", "-q")
            git("config", "user.name", "tester")
            git("config", "user.email", "tester@example.com")
            for path, text in files.items():
                (repo / path).parent.mkdir(parents=True, exist_ok=True)
                (repo / path).write_text(text)
            git("add", ".")
            git("commit", "-qm", "tree")
            return subprocess.run(
                [str(ROOT / "scripts/ci/tested_tree.sh")],
                cwd=repo,
                env=GIT_ENV,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.split()

    BASE = {
        "backend/app/main.py": "app\n",
        "VERSION": "1.2.2\n",
        "CHANGELOG.md": "## [Unreleased]\n",
        "RELEASED_MIGRATION": "0001\n",
        "frontend/src/api/generated/version/version.ts": "1.2.2\n",
    }

    def test_a_release_keeps_the_tree_without_its_files(self) -> None:
        release = {
            **self.BASE,
            "VERSION": "1.2.3\n",
            "CHANGELOG.md": "## [1.2.3]\n",
            "RELEASED_MIGRATION": "0002\n",
            "MIN_DESKTOP_VERSION": "1.2.3\n",
            "frontend/src/api/generated/version/version.ts": "1.2.3\n",
        }
        before, after = self.ids(self.BASE), self.ids(release)
        self.assertNotEqual(before[0], after[0])
        self.assertEqual(before[1], after[1])

    def test_any_other_change_is_another_tree(self) -> None:
        changed = {**self.BASE, "backend/app/main.py": "changed\n"}
        self.assertNotEqual(self.ids(self.BASE)[1], self.ids(changed)[1])
        moved = {**self.BASE, "frontend/src/api/mutator.ts": "new\n"}
        self.assertNotEqual(self.ids(self.BASE)[1], self.ids(moved)[1])


class UpgradeTest(unittest.TestCase):
    def test_a_migration_runs_every_migration_check(self) -> None:
        outputs = detect(["backend/alembic/versions/20260930_0420_example.py"])
        self.assertEqual(outputs.get("alembic"), "true")
        self.assertEqual(outputs.get("upgrade"), "hop")

    def test_a_change_to_how_the_image_starts_upgrades(self) -> None:
        for path in ["Dockerfile", "backend/entrypoint.sh", "backend/app/main.py"]:
            with self.subTest(path=path):
                self.assertEqual(detect([path]).get("upgrade"), "hop")

    def test_an_ordinary_change_does_not_upgrade(self) -> None:
        self.assertEqual(
            detect(["backend/app/services/guilds.py"]).get("upgrade"), "false"
        )

    def test_an_integration_push_walks_every_release(self) -> None:
        self.assertEqual(detect(["README.md"], event="push").get("upgrade"), "walk")

    def test_a_release_is_walked_by_its_candidate(self) -> None:
        outputs = detect(["VERSION"], base_ref="main", head_ref="release/v1.2.3")
        self.assertEqual(outputs.get("upgrade"), "false")

    def test_a_release_branch_from_a_fork_walks(self) -> None:
        outputs = detect(
            ["VERSION"], base_ref="main", head_ref="release/v1.2.3", same_repo=False
        )
        self.assertEqual(outputs.get("upgrade"), "walk")

    def test_another_pull_request_into_main_walks(self) -> None:
        outputs = detect(["VERSION"], base_ref="main", head_ref="hotfix/login")
        self.assertEqual(outputs.get("upgrade"), "walk")


class ForkTest(unittest.TestCase):
    AREAS = ["backend", "seam", "upgrade", "frontend", "codegen", "tooling"]

    def test_a_push_to_a_fork_checks_nothing(self) -> None:
        outputs = detect(["backend/app/db/session.py"], "push", fork=True)
        self.assertEqual(
            {area: outputs.get(area) for area in self.AREAS},
            dict.fromkeys(self.AREAS, "false"),
        )

    def test_a_pull_request_in_a_fork_checks_as_usual(self) -> None:
        outputs = detect(["backend/app/db/session.py"], fork=True)
        self.assertEqual(outputs.get("backend_mode"), "full")
        self.assertEqual(outputs.get("seam"), "true")


if __name__ == "__main__":
    unittest.main()
