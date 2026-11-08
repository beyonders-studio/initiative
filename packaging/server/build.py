"""Build native server packages from source and prebuilt, signed web assets."""

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
PACKAGE = "initiative-server"


def run(
    args: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None
) -> None:
    subprocess.run(args, cwd=cwd, env=env, check=True)


def validate_assets(
    assets: Path, version: str, native: str, desktop: str, channel: str = "release"
) -> None:
    required = [
        "browser/index.html",
        "browser/THIRD_PARTY_NOTICES.txt",
        "editor/editor.js",
        "ota/bundle.zip",
        "ota/bundle.sha256",
        "ota/statement.json",
        "ota/statement.sig",
    ]
    for name in required:
        path = assets / name
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f"Missing or empty prepared asset: {name}")
    # Do not let prepared assets install symlinks escaping the immutable runtime.
    if any(path.is_symlink() for path in assets.rglob("*")):
        raise ValueError("Prepared assets must not contain symlinks")
    bundle = assets / "ota/bundle.zip"
    with bundle.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if (assets / "ota/bundle.sha256").read_text().strip() != digest:
        raise ValueError("OTA bundle.sha256 does not match bundle.zip")
    statement = json.loads((assets / "ota/statement.json").read_text())
    expected = {
        "v": 1,
        "version": version,
        "sha256": digest,
        "minNativeVersion": native,
        "minDesktopVersion": desktop,
    }
    if channel == "dev":
        signed_version = statement.get("version")
        if not isinstance(signed_version, str) or not signed_version.startswith(
            version + "-server-test-"
        ):
            raise ValueError("Dev assets must identify their server-test build")
        expected["version"] = signed_version
    if statement != expected:
        raise ValueError("OTA statement does not match source version/floors/bundle")
    signature = base64.b64decode(
        (assets / "ota/statement.sig").read_text().strip(), validate=True
    )
    if len(signature) != 64:
        raise ValueError("OTA signature must be the existing 64-byte P1363 signature")
    with zipfile.ZipFile(bundle) as archive:
        if "index.html" not in archive.namelist():
            raise ValueError("OTA bundle must have index.html at its root")
        for name in archive.namelist():
            if name.startswith("/") or ".." in Path(name).parts:
                raise ValueError("Unsafe OTA ZIP member")
    # Signature cryptographic verification belongs to the native app's existing
    # trust root; packaging preserves the signed bytes and never re-signs them.


def native_target(kind: str) -> tuple[str, str]:
    release = dict(
        line.split("=", 1)
        for line in Path("/etc/os-release").read_text().splitlines()
        if "=" in line
    )
    distro = release.get("ID", "").strip('"')
    version = release.get("VERSION_ID", "").strip('"')
    expected = ("debian", "13", "3.13") if kind == "deb" else ("alpine", "3.24", "3.14")
    if distro != expected[0] or not (
        version == expected[1] or version.startswith(expected[1] + ".")
    ):
        raise ValueError(f"Build {kind} natively on {expected[0]} {expected[1]}")
    python = f"/usr/bin/python{expected[2]}"
    run([python, "-c", "import sys; assert sys.version_info >= (3, 12)"])
    return python, expected[2]


def copy_file(source: Path, destination: Path, mode: int = 0o644) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    destination.chmod(mode)


def stage_application_source(root: Path) -> None:
    """Copy application code and its vendored runtime contracts without local files."""
    for name in ("app", "alembic", "vendor"):
        shutil.copytree(
            REPO / "backend" / name,
            root / name,
            ignore=shutil.ignore_patterns(
                "__pycache__", "*_test.py", "*.pyc", ".env", "._*", ".DS_Store"
            ),
        )
    for name in ("alembic.ini",):
        copy_file(REPO / "backend" / name, root / name)


def stage_payload(
    stage: Path, assets: Path, channel: str, python: str, abi: str, work: Path
) -> None:
    root = stage / "usr/lib/initiative"
    root.mkdir(parents=True, exist_ok=True)
    stage_application_source(root)
    for name in (
        "VERSION",
        "MIN_NATIVE_VERSION",
        "MIN_DESKTOP_VERSION",
        "CLOUD_ORIGIN",
        "CHANGELOG.md",
    ):
        copy_file(REPO / name, root / name)
    (root / "IMAGE_CHANNEL").write_text(channel + "\n")
    for source, target in (("browser", "static"), ("editor", "editor"), ("ota", "ota")):
        shutil.copytree(assets / source, root / target)
    copy_file(HERE / "common/launch.py", root / "launch.py")
    copy_file(
        HERE / "common/initiative-server", stage / "usr/bin/initiative-server", 0o755
    )
    copy_file(HERE / "common/server.env", stage / "etc/initiative/server.env", 0o640)
    (stage / "etc/initiative").chmod(0o750)
    doc = stage / "usr/share/doc" / PACKAGE
    for name in ("LICENSE", "NOTICE.md"):
        copy_file(REPO / name, doc / name)
    for name in ("pyproject.toml", "uv.lock", ".env.example"):
        copy_file(REPO / "backend" / name, doc / name)
    # Build tools stay outside the package. Install uv from the same hash-pinned
    # requirements as the image build; never download a replacement interpreter.
    tools = work / "tools"
    run([python, "-m", "venv", str(tools)])
    run(
        [
            str(tools / "bin/python"),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--only-binary=:all:",
            "--require-hashes",
            "-r",
            str(REPO / "backend/uv-requirements.txt"),
        ]
    )
    env = {
        **os.environ,
        "UV_PROJECT_ENVIRONMENT": str(root / ".venv"),
        "UV_PYTHON_DOWNLOADS": "never",
        "UV_LINK_MODE": "copy",
        "UV_CONCURRENT_BUILDS": os.environ.get("UV_CONCURRENT_BUILDS", "1"),
        "CARGO_BUILD_JOBS": os.environ.get("CARGO_BUILD_JOBS", "2"),
        "MAKEFLAGS": os.environ.get("MAKEFLAGS", "-j2"),
    }
    # --locked checks pyproject consistency; --frozen alone would accept stale
    # metadata. Exporting the system interpreter overrides backend/.python-version.
    run(
        [
            str(tools / "bin/uv"),
            "sync",
            "--locked",
            "--no-dev",
            "--no-editable",
            "--python",
            python,
            "--no-managed-python",
            "--project",
            str(REPO / "backend"),
        ],
        env=env,
    )
    venv = root / ".venv"
    # Console/activation scripts embed the staging path. Use module entry points
    # and system Python symlinks instead; worker sys.executable remains installed.
    shutil.rmtree(venv / "bin")
    (venv / "bin").mkdir()
    for name in ("python", "python3", f"python{abi}"):
        (venv / "bin" / name).symlink_to(python)
    (venv / "pyvenv.cfg").write_text(
        f"home = /usr/bin\ninclude-system-site-packages = false\nversion = {abi}\n"
    )
    for path in venv.rglob("__pycache__"):
        shutil.rmtree(path)
    for path in root.rglob("*"):
        if not path.is_symlink():
            path.chmod(0o755 if path.is_dir() or path.stat().st_mode & 0o111 else 0o644)


def deb_package(stage: Path, output: Path, version: str, revision: int) -> None:
    arch = subprocess.check_output(["dpkg", "--print-architecture"], text=True).strip()
    if arch not in ("amd64", "arm64"):
        raise ValueError("Server packages support amd64 and arm64")
    control = stage / "DEBIAN"
    control.mkdir()
    (control / "control").write_text(
        f"Package: {PACKAGE}\nVersion: {version}-{revision}\nArchitecture: {arch}\n"
        "Maintainer: Beyonders Studio <jordan@morels.me>\n"
        "Section: web\nPriority: optional\n"
        "Depends: python3 (>= 3.13), python3 (<< 3.14), python3.13, adduser, init-system-helpers, "
        "libmagic1t64, libstdc++6, libgcc-s1, ca-certificates\n"
        "Homepage: https://github.com/beyonders-studio/initiative\n"
        "Description: Initiative server with bundled web application\n"
        " Native API, browser, document editor and signed OTA server assets.\n"
        " PostgreSQL is provisioned separately. Service activation is manual.\n"
    )
    (control / "conffiles").write_text("/etc/initiative/server.env\n")
    for name in ("postinst", "prerm", "postrm"):
        copy_file(HERE / "debian" / name, control / name, 0o755)
    copy_file(
        HERE / "debian/initiative-server.service",
        stage / "usr/lib/systemd/system/initiative-server.service",
    )
    run(
        [
            "dpkg-deb",
            "--root-owner-group",
            "--build",
            str(stage),
            str(output / f"{PACKAGE}_{version}-{revision}_{arch}.deb"),
        ]
    )


def apk_package(
    stage: Path, output: Path, version: str, revision: int, work: Path
) -> None:
    key_source = os.environ.get("APK_SIGNING_KEY")
    if not key_source or not Path(key_source).is_file():
        raise ValueError("APK_SIGNING_KEY must name the APK RSA private signing key")
    arch = subprocess.check_output(["apk", "--print-arch"], text=True).strip()
    if arch not in ("x86_64", "aarch64"):
        raise ValueError("Server packages support x86_64 and aarch64")
    (stage / "usr/lib/initiative/ALPINE_RUNTIME").write_text("musl\n")
    copy_file(
        HERE / "alpine/initiative-server.initd",
        stage / "etc/init.d/initiative-server",
        0o755,
    )
    recipe = work / "native" / PACKAGE
    if recipe.exists():
        shutil.rmtree(recipe)
    recipe.mkdir(parents=True)
    for source in (HERE / "alpine").glob("initiative-server.*-*"):
        copy_file(source, recipe / source.name, 0o755)
    payload = recipe / "payload.tar.gz"
    with tarfile.open(payload, "w:gz") as archive:
        for path in sorted(stage.iterdir()):
            archive.add(path, arcname=path.name)
    with payload.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha512").hexdigest()
    hooks = " ".join(path.name for path in sorted(recipe.glob("initiative-server.*-*")))
    (recipe / "APKBUILD").write_text(
        f"pkgname={PACKAGE}\npkgver={version}\npkgrel={revision}\n"
        'pkgdesc="Initiative native server and web application"\n'
        'url="https://github.com/beyonders-studio/initiative"\narch="x86_64 aarch64"\n'
        'license="AGPL-3.0-only"\n'
        'depends="python3>=3.14 python3<3.15 openrc libmagic gcompat libgcc libstdc++ ca-certificates"\n'
        'options="!check !strip !tracedeps !py3compile"\n'
        f'install="{hooks}"\nsource="payload.tar.gz"\n'
        f'sha512sums="{checksum}  payload.tar.gz"\n'
        'package() {\n    mkdir -p "$pkgdir"\n    cp -a "$srcdir"/usr "$srcdir"/etc "$pkgdir"/\n}\n'
    )
    # Stable public-key basename is also the APK signature trust lookup name.
    key = work / "initiative-server.rsa"
    copy_file(Path(key_source), key, 0o600)
    pub = output / "initiative-server.rsa.pub"
    run(["openssl", "rsa", "-in", str(key), "-pubout", "-out", str(pub)])
    env = {**os.environ, "PACKAGER_PRIVKEY": str(key), "PACKAGER_PUBKEY": str(pub)}
    command = ["abuild", "-d", "-m", "-P", str(work / "packages")]
    if os.geteuid() == 0:
        command.append("-F")
    # Alpine 3.24's default "all" also creates a repository index, which
    # requires installing the signing key into the builder's global trust.
    # Run its normal packaging phases explicitly: rootpkg still validates,
    # assembles and signs the standalone APK; no repository is published here.
    command.extend(
        [
            "validate",
            "builddeps",
            "clean",
            "fetch",
            "unpack",
            "prepare",
            "mkusers",
            "build",
            "rootpkg",
        ]
    )
    run(command, cwd=recipe, env=env)
    packages = list((work / "packages").rglob(f"{PACKAGE}-{version}-r{revision}.apk"))
    if len(packages) != 1:
        raise ValueError("abuild did not produce exactly one expected server APK")
    shutil.copyfile(packages[0], output / f"{PACKAGE}-{version}-r{revision}-{arch}.apk")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("deb", "apk"))
    parser.add_argument("--assets", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--channel", choices=("release", "dev"), default="release")
    parser.add_argument("--revision", type=int, default=1)
    parser.add_argument(
        "--work-dir",
        type=Path,
        help="Retain build tools/cache after failure for diagnosis",
    )
    args = parser.parse_args()
    version = (REPO / "VERSION").read_text().strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", version) or args.revision < 1:
        parser.error("VERSION must be numeric semver and --revision positive")
    assets, output = args.assets.resolve(), args.output.resolve()
    validate_assets(
        assets,
        version,
        (REPO / "MIN_NATIVE_VERSION").read_text().strip(),
        (REPO / "MIN_DESKTOP_VERSION").read_text().strip(),
        args.channel,
    )
    python, abi = native_target(args.kind)
    output.mkdir(parents=True, exist_ok=True)

    def build(work: Path) -> None:
        stage = work / "payload"
        if stage.exists():
            shutil.rmtree(stage)
        stage_payload(stage, assets, args.channel, python, abi, work)
        if args.kind == "deb":
            deb_package(stage, output, version, args.revision)
        else:
            apk_package(stage, output, version, args.revision, work)

    if args.work_dir:
        work = args.work_dir.resolve()
        work.mkdir(parents=True, exist_ok=True)
        build(work)
    else:
        with tempfile.TemporaryDirectory(prefix="initiative-server-") as temporary:
            build(Path(temporary))


if __name__ == "__main__":
    main()
