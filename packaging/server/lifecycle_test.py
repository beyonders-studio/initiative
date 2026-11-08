"""Exercise Debian service cleanup with the installed helper in an isolated root."""

import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import build

HERE = Path(__file__).resolve().parent
HELPER = shutil.which("deb-systemd-helper")


@unittest.skipUnless(HELPER, "requires Debian's installed deb-systemd-helper")
class DebianServiceLifecycleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="initiative-helper-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.env = {
            **os.environ,
            "DPKG_ROOT": str(self.root),
            "DPKG_MAINTSCRIPT_PACKAGE": "initiative-server",
        }
        self.unit = self.root / "usr/lib/systemd/system/initiative-server.service"
        self.unit.parent.mkdir(parents=True)
        shutil.copyfile(HERE / "debian/initiative-server.service", self.unit)
        self.link = (
            self.root
            / "etc/systemd/system/multi-user.target.wants/initiative-server.service"
        )
        self.link.parent.mkdir(parents=True)
        assert HELPER
        subprocess.run(
            [HELPER, "update-state", "initiative-server.service"],
            env=self.env,
            check=True,
        )

    def postrm(self, action: str) -> None:
        subprocess.run(
            ["/bin/sh", str(HERE / "debian/postrm"), action], env=self.env, check=True
        )

    def test_upgrade_and_remove_preserve_enabled_link_then_purge_cleans_it_offline(
        self,
    ) -> None:
        self.assertFalse(
            self.link.is_symlink(), "recording state must not enable the service"
        )
        self.link.symlink_to("/usr/lib/systemd/system/initiative-server.service")
        self.postrm("upgrade")
        self.assertTrue(self.link.is_symlink())
        # Removal has already deleted the package's unit before postrm executes.
        self.unit.unlink()
        self.postrm("remove")
        self.assertTrue(self.link.is_symlink())
        # Hide systemctl entirely: helper cleanup must work without systemd.
        tools = self.root / "test-tools"
        tools.mkdir()
        assert HELPER
        (tools / "deb-systemd-helper").symlink_to(HELPER)
        self.env["PATH"] = str(tools)
        self.postrm("purge")
        self.assertFalse(
            self.link.is_symlink(), "purge left a dangling enabled service link"
        )
        self.assertFalse(
            (
                self.root
                / "var/lib/systemd/deb-systemd-helper-enabled/initiative-server.service.dsh-also"
            ).exists()
        )
        self.postrm("purge")

    def test_purge_never_enables_an_unconfigured_service(self) -> None:
        self.assertFalse(self.link.is_symlink())
        self.unit.unlink()
        self.postrm("purge")
        self.assertFalse(self.link.is_symlink())


@unittest.skipUnless(
    sys.platform == "linux" and os.geteuid() == 0,
    "requires root on Linux for real service-identity ownership checks",
)
class StateDirectoryOwnershipTest(unittest.TestCase):
    # Exercise native filesystem operations without changing global users or
    # directories. Only account/metadata lookups and absolute installation paths
    # are adapted; install/chown/chmod run unchanged as root.
    uid = 65534
    gid = 65534
    hooks = (
        "debian/postinst",
        "alpine/initiative-server.post-install",
        "alpine/initiative-server.post-upgrade",
    )

    def fixture(
        self, directory: str, hook: str, *, barrier: bool = False
    ) -> tuple[Path, Path, dict[str, str]]:
        root = Path(directory)
        root.chmod(0o755)
        state = root / "var/lib/initiative"
        config = root / "etc/initiative"
        config.mkdir(parents=True)
        (config / "server.env").write_text("operator configuration stays unchanged\n")
        (root / "var/lib").mkdir(parents=True)
        (root / "var/log").mkdir(parents=True)
        tools = root / "tools"
        tools.mkdir()
        stubs = {
            "getent": "exit 0",
            "id": f"echo {self.uid}",
            "deb-systemd-helper": "exit 0",
        }
        for name, body in stubs.items():
            (tools / name).write_text(f"#!/bin/sh\n{body}\n")
            (tools / name).chmod(0o755)
        env = {
            **os.environ,
            "PATH": f"{tools}:{os.environ['PATH']}",
            "DPKG_ROOT": str(root),
        }
        if barrier:
            install = shutil.which("install")
            assert install
            env.update(
                {"INITIATIVE_TEST_ROOT": str(root), "INITIATIVE_TEST_INSTALL": install}
            )
            (tools / "install").write_text(
                "#!/bin/sh\n"
                ': > "$INITIATIVE_TEST_ROOT/paused"\n'
                'while [ ! -e "$INITIATIVE_TEST_ROOT/resume" ]; do sleep 0.01; done\n'
                'exec "$INITIATIVE_TEST_INSTALL" "$@"\n'
            )
            (tools / "install").chmod(0o755)
        source = (HERE / hook).read_text()
        for name in ("/var/lib/initiative", "/var/log/initiative", "/etc/initiative"):
            source = source.replace(name, str(root) + name)
        source = source.replace("root:initiative", f"0:{self.gid}")
        source = source.replace(
            "-o initiative -g initiative", f"-o {self.uid} -g {self.gid}"
        )
        rewritten = root / "hook"
        rewritten.write_text(source)
        return state, rewritten, env

    def as_service(self, code: str, *args: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-c", code, *(str(path) for path in args)],
            check=False,
            user=self.uid,
            group=self.gid,
            extra_groups=[],
            capture_output=True,
            text=True,
        )

    def assert_layout(self, state: Path) -> None:
        self.assertEqual((state.stat().st_uid, state.stat().st_gid), (0, self.gid))
        self.assertEqual(stat.S_IMODE(state.stat().st_mode), 0o750)
        uploads = state / "uploads"
        self.assertEqual(
            (uploads.stat().st_uid, uploads.stat().st_gid), (self.uid, self.gid)
        )
        self.assertEqual(stat.S_IMODE(uploads.stat().st_mode), 0o750)
        writable = self.as_service(
            "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('kept upload')",
            uploads / "saved.txt",
        )
        self.assertEqual(writable.returncode, 0, writable.stderr)
        denied = self.as_service(
            "import os,sys; os.rename(sys.argv[1], sys.argv[2])",
            uploads,
            state / "renamed",
        )
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn("PermissionError", denied.stderr)

    def test_fresh_install_and_reconfigure_seal_parent_keep_uploads_writable(
        self,
    ) -> None:
        for hook in self.hooks:
            with (
                self.subTest(hook=hook),
                tempfile.TemporaryDirectory(prefix="initiative-owner-") as temporary,
            ):
                state, script, env = self.fixture(temporary, hook)
                for _ in range(2):
                    subprocess.run(
                        ["/bin/sh", str(script), "configure"],
                        env=env,
                        check=True,
                        capture_output=True,
                    )
                    self.assert_layout(state)
                self.assertEqual(
                    (state / "uploads/saved.txt").read_text(), "kept upload"
                )
                self.assertEqual(
                    (Path(temporary) / "etc/initiative/server.env").read_text(),
                    "operator configuration stays unchanged\n",
                )

    def test_upgrade_locks_old_parent_before_service_can_swap_uploads(self) -> None:
        for hook in self.hooks:
            with (
                self.subTest(hook=hook),
                tempfile.TemporaryDirectory(prefix="initiative-race-") as temporary,
            ):
                state, script, env = self.fixture(temporary, hook, barrier=True)
                uploads = state / "uploads"
                uploads.mkdir(parents=True)
                os.chown(state, self.uid, self.gid)
                os.chmod(state, 0o770)
                os.chown(uploads, self.uid, self.gid)
                (uploads / "legacy.txt").write_text("preserved older upload")
                os.chown(uploads / "legacy.txt", self.uid, self.gid)
                victim = Path(temporary) / "victim"
                victim.mkdir(mode=0o700)
                before = victim.stat()
                process = subprocess.Popen(
                    ["/bin/sh", str(script), "configure"],
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    start_new_session=True,
                )
                try:
                    deadline = time.monotonic() + 10
                    while not (Path(temporary) / "paused").exists():
                        if process.poll() is not None:
                            self.fail(
                                f"hook exited before the install barrier: {process.communicate()}"
                            )
                        if time.monotonic() >= deadline:
                            self.fail("hook did not reach the install barrier")
                        time.sleep(0.01)
                    attack = self.as_service(
                        "import os,sys; os.rename(sys.argv[1], sys.argv[2]); os.symlink(sys.argv[3], sys.argv[1])",
                        uploads,
                        state / "old-uploads",
                        victim,
                    )
                finally:
                    (Path(temporary) / "resume").touch()
                    try:
                        stdout, stderr = process.communicate(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.communicate()
                        raise
                after = victim.stat()
                self.assertEqual(
                    (after.st_uid, after.st_gid, stat.S_IMODE(after.st_mode)),
                    (before.st_uid, before.st_gid, stat.S_IMODE(before.st_mode)),
                    "root followed the raced uploads symlink and changed its target",
                )
                self.assertNotEqual(
                    attack.returncode,
                    0,
                    "service replaced uploads after the hook checked it",
                )
                self.assertIn("PermissionError", attack.stderr)
                self.assertEqual(process.returncode, 0, stdout + stderr)
                self.assert_layout(state)
                self.assertEqual(
                    (uploads / "legacy.txt").read_text(), "preserved older upload"
                )

    def test_existing_upload_symlink_is_rejected_without_touching_target(self) -> None:
        for hook in self.hooks:
            with (
                self.subTest(hook=hook),
                tempfile.TemporaryDirectory(prefix="initiative-link-") as temporary,
            ):
                state, script, env = self.fixture(temporary, hook)
                state.mkdir()
                os.chown(state, self.uid, self.gid)
                victim = Path(temporary) / "victim"
                victim.mkdir(mode=0o700)
                before = victim.stat()
                (state / "uploads").symlink_to(victim)
                result = subprocess.run(
                    ["/bin/sh", str(script), "configure"],
                    check=False,
                    env=env,
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(result.returncode, 0)
                after = victim.stat()
                self.assertEqual(
                    (after.st_uid, after.st_gid, stat.S_IMODE(after.st_mode)),
                    (before.st_uid, before.st_gid, stat.S_IMODE(before.st_mode)),
                )
                self.assertEqual(state.stat().st_uid, 0)


@unittest.skipUnless(
    shutil.which("abuild") and shutil.which("apk"),
    "requires Alpine's installed abuild and apk tools",
)
class StandaloneApkTest(unittest.TestCase):
    def test_signed_package_build_needs_no_global_trust_or_repository_index(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="initiative-apk-test-") as temporary:
            root = Path(temporary)
            stage, work, output = root / "payload", root / "work", root / "output"
            (stage / "usr/lib/initiative").mkdir(parents=True)
            (stage / "etc/initiative").mkdir(parents=True)
            (stage / "usr/lib/initiative/test-payload.txt").write_text(
                "standalone package fixture\n"
            )
            (stage / "etc/initiative/server.env").write_text("SECRET_KEY=\n")
            work.mkdir()
            output.mkdir()
            key = root / "fixture.rsa"
            subprocess.run(
                ["openssl", "genrsa", "-out", str(key), "2048"],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            keys = Path("/etc/apk/keys")
            trusted_before = {
                path.name: path.read_bytes()
                for path in keys.iterdir()
                if path.is_file()
            }
            with patch.dict(os.environ, {"APK_SIGNING_KEY": str(key)}):
                build.apk_package(stage, output, "1.2.3", 1, work)
            packages = list(output.glob("*.apk"))
            self.assertEqual(len(packages), 1)
            self.assertFalse(list(work.rglob("APKINDEX.tar.gz")))
            self.assertFalse(list(work.rglob("Packages.adb")))
            self.assertEqual(
                trusted_before,
                {
                    path.name: path.read_bytes()
                    for path in keys.iterdir()
                    if path.is_file()
                },
            )
            # A package signed with a new fixture key is rejected by default.
            rejected = subprocess.run(
                ["apk", "verify", str(packages[0])], check=False, capture_output=True
            )
            self.assertNotEqual(rejected.returncode, 0)
            # Trust only this invocation's fixture key, without --allow-untrusted.
            trust = root / "isolated-trust"
            trust.mkdir()
            public = output / "initiative-server.rsa.pub"
            shutil.copyfile(public, trust / public.name)
            subprocess.run(
                ["apk", "verify", "--keys-dir", str(trust), str(packages[0])],
                check=True,
            )


if __name__ == "__main__":
    unittest.main()
