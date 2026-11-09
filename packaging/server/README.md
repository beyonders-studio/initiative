# Native server package tooling

Operator installation and upgrade instructions live in
[`docs/en/running-a-server/native-packages.md`](../../docs/en/running-a-server/native-packages.md).
These packages are `initiative-server`, separate from the Electron desktop
package `initiative`.

## Build inputs

Run on **Debian 13** or **Alpine 3.24**, on amd64/x86_64 or arm64/aarch64. A VM,
LXC or ordinary native host works; installing Docker is not a prerequisite. Do not
reuse a Python virtualenv between distributions or architectures.

Install the matching build manifest as root from the repository root:

```sh
# Debian 13
apt-get update
xargs apt-get install -y --no-install-recommends < packaging/server/debian/build-dependencies.txt

# Alpine 3.24
apk add $(cat packaging/server/alpine/build-dependencies.txt)
```

A release takes its browser, server editor and signed OTA assets from the
release's checked image (`/app/static`, `/app/editor`, `/app/ota`; see
`server-packages.yml`). For a test package, build them from source with
`scripts/build-server-assets.sh --output DIR`. The supplied directory must
contain `browser/` (including `index.html` and `THIRD_PARTY_NOTICES.txt`),
`editor/editor.js`, and `ota/{bundle.zip,bundle.sha256,statement.json,statement.sig}`.
The bundle checksum, version and both native version floors must agree with the
source. Release packages require the exact source `VERSION`; dev test packages
require a `VERSION-server-test-*` statement and must use the matching dev app
trust key. Packaging validates structure and integrity, preserves the signature
bytes, and leaves cryptographic signature verification to the existing native
app trust root. It neither creates a substitute signature nor embeds a signing
private key.

```sh
sh packaging/server/build.sh deb --assets prepared-assets --output dist/server --channel release --revision 1

# Alpine: APK_SIGNING_KEY names a private RSA PEM file outside the checkout.
# abuild signs the package; its public key is emitted beside the package.
sh packaging/server/build.sh apk --assets prepared-assets --output dist/server --channel release --revision 1
```

Builds install hash-pinned uv into an isolated build-tool venv and resolve the
locked backend runtime for Python 3.14: Alpine's own, and on Debian, whose own
is 3.13, the CPython build (`BUNDLED_PYTHON` in `build.py`) uv installs into the
package at `/usr/lib/initiative/python`. They reject a stale lockfile and
download no other interpreter. The package contains the runtime venv,
source, migrations, browser, editor, signed OTA assets, version floors, channel,
changelog, source licence, artwork notice and installed dependency notices.
Development/test tooling and uv do not ship. The launcher and worker subprocesses
use the installed venv Python with module entry points; generated scripts with
staging paths are removed. Package metadata constrains the Python minor ABI.

Alpine needs native `gcompat`, `libgcc`, `libstdc++` and `libmagic`. The launcher
preloads `/lib/libgcompat.so.0` for mini-racer and its editor subprocess. Locked
Typst is compiled from source on musl; Alpine's Rust toolchain and Perl are build
requirements. Defaults cap Cargo at two jobs and uv at one concurrent build;
`CARGO_BUILD_JOBS`, `MAKEFLAGS` and `UV_CONCURRENT_BUILDS` can lower these further.
The normal uv/Cargo caches are reusable. `--work-dir build/server-work` retains
build files on success/failure for diagnosis; it can include signing material
and must be treated as private, excluded from artifacts and deleted afterwards.

`abuild` emits a signed native APK using an internally generated APKBUILD over
the source-built payload. Dependency tracing is explicitly replaced with the
known ABI/system-library dependency list, preserving wheel binaries and vendored
libraries. Package publication is handled by CI, not this script.

## Lifecycle and configuration

The immutable runtime is root-owned at `/usr/lib/initiative`. Packages create a
non-login, non-root `initiative` identity. Its home, `/var/lib/initiative`, is
root-owned with group `initiative` and mode 0750. The service can write to its
`uploads/` child and `/var/log/initiative`, which it owns. Hooks transfer ownership
of an older writable home to root before setting its permissions and inspecting
children, so a running service cannot replace `uploads/` with a symlink while
root applies ownership. Existing uploaded data is preserved. Operators must
create and grant access to any custom storage or export children under the home.
`/etc/initiative/server.env` is
root-owned and group-readable by `initiative` (0640 in a 0750 directory).
It is a Debian conffile; Alpine's protected `/etc` semantics preserve operator
edits. The default contains no database credentials or application secrets.

Hooks never connect to PostgreSQL, migrate the database, enable the service or
start it. An operator supplies an existing PostgreSQL database/owner connection,
a strong `SECRET_KEY` and `APP_URL`, then manually enables/starts the service.
Normal FastAPI startup performs the application's existing database preparation.
`uvicorn --env-file` loads dotenv data; configuration is never sourced as shell.
Listener and proxy arguments are explicit, with a loopback listener and local
trusted proxies by default. Account registration is disabled by default; first
owner enrollment must be chosen explicitly.

A running managed service is stopped before upgrade/removal. Upgrades preserve
operator configuration and state and require a manual restart. Removal preserves
modified configuration, uploads, logs, database and service identity. Debian
purge removes its packaged configuration but retains uploads, logs, database and
identity. Debian purge also removes recorded service enablement links, including
when systemd is not running; upgrade and ordinary removal preserve enablement.
Alpine `apk del --purge` explicitly removes protected configuration;
do not use it when retaining configuration. An operator must back up the
database and uploads before upgrades: package rollback does not undo migrations.

## Validation

Focused input/listener tests do not need the application database or full backend
environment:

```sh
uv run --no-project --with python-dotenv python -m unittest discover -s packaging/server -p '*_test.py' -v
```

`smoke-test.sh` is a **destructive root integration test for a fresh disposable
native guest**. Never run it against an existing server. It installs runtime
PostgreSQL test dependencies and a disposable, local Unix-socket-only fixture;
no database provisioning occurs in production package hooks. The test verifies
native modules, MIME detection, a real editor worker, Typst PDF output, relocated
venv paths, migrations, every readiness check, API registration/login and
community/initiative/project/task persistence, SPA and signed manifest delivery,
a real package upgrade/restart, configuration/upload preservation and removal.
Debian additionally exercises purge. Supply separately built revisions 1 and 2
to test a version upgrade, rather than reinstalling an identical package.

```sh
# Debian disposable guest (requires bash):
bash packaging/server/smoke-test.sh deb dist/server/initiative-server_1.2.3-1_amd64.deb dist/server/upgrade/initiative-server_1.2.3-2_amd64.deb

# Alpine disposable guest; test/production public key must match the packages:
# APK_TRUSTED_KEY names initiative-server.rsa.pub from the build output.
bash packaging/server/smoke-test.sh apk dist/server/initiative-server-1.2.3-r1-x86_64.apk dist/server/upgrade/initiative-server-1.2.3-r2-x86_64.apk
```

This test launches the installed service executable as its actual service user
inside guests without an init manager. A real systemd/OpenRC boot and Proxmox LXC
acceptance still require their own environment evidence.
