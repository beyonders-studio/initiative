---
icon: lucide/package-open
---

# Native server packages

The `initiative-server` packages run the backend, browser app and document editor
directly on a Linux host or an unprivileged Proxmox LXC. They include the locked
Python dependencies and the matching signed phone/desktop update assets. The
installed server needs no Docker runtime, Node.js, Rust compiler or dependency
download step.

The existing `initiative-<version>.deb` is the **desktop client**. Choose a package
whose name starts with **`initiative-server`** for a headless server.

## Supported targets

- Debian 13, with system Python 3.13 and systemd.
- Alpine 3.24, with system Python 3.14 and OpenRC.
- Each release builds separately for amd64/x86_64 and arm64/aarch64.

The native dependencies are built for each target's Python ABI and libc. A Debian
package cannot be installed on Alpine, and a virtual environment copied between
these distributions is not a supported substitute. Major distribution/Python
upgrades require a matching rebuilt server package.

## Install

Provision a PostgreSQL 17 database first, using the connection requirements in
[Installation](installation.md#the-database-connection). The database can be local
or remote. Package installation does not create database accounts, choose database
passwords or run migrations.

Download the package for your distribution and architecture from the release's
**Native server packages** section. Check it against that release's server package
SHA-256 manifest before installing.

On Debian, install the local `.deb` with `apt install ./<downloaded-package>.deb`.
APT resolves the declared distribution dependencies. The `.deb` and checksum
manifest are release downloads, not an APT repository.

On Alpine, install the release's `initiative-server.rsa.pub` into `/etc/apk/keys/`
before using `apk add ./<downloaded-package>.alpine`. Obtain and verify the public key
through a trusted channel before installing it. Keep that trust key for subsequent
upgrades. Do not use `--allow-untrusted`. The Alpine package is named `.alpine`
rather than `.apk` so Android updaters don't mistake it for the phone app; `apk`
installs it the same.

The package creates the unprivileged `initiative` account and installs a service,
but **does not start it automatically**. This gives you time to configure a private
server and take a database backup before a package transaction can trigger a
schema migration.

## Configure and start

Edit `/etc/initiative/server.env` as root. Set at least:

```dotenv
DATABASE_URL=postgresql+asyncpg://initiative:PERCENT_ENCODED_PASSWORD@127.0.0.1:5432/initiative
SECRET_KEY=REPLACE_WITH_A_STRONG_UNIQUE_KEY
APP_URL=https://tasks.example.org
```

Use `openssl rand -hex 32` to generate the key. Percent-encode special characters
in a database URL password. Preserve the same `SECRET_KEY` across upgrades: it
protects encrypted data as well as sessions.

The server listens on `127.0.0.1:8173` by default. Put a reverse proxy with trusted
HTTPS and WebSocket support in front of it, and set `BEHIND_PROXY=true`. A proxy on
this machine or your LAN, and Cloudflare in front of it, need nothing more; see
[Running behind a reverse proxy](configuration.md#running-behind-a-reverse-proxy) for the one setup that does. To serve another
interface, explicitly set `INITIATIVE_HOST`; do not expose an unconfigured server
on a public network.

Public registration is disabled in the package's initial configuration. Supply
`FIRST_OWNER_EMAIL` and `FIRST_OWNER_PASSWORD` to bootstrap the first owner, or
temporarily enable registration while creating your first account privately.
Remove the bootstrap password from the configuration once the owner exists, and
leave public registration disabled for an invite-only instance.

The environment file is configuration data, not a shell script. Write dotenv
assignments; shell commands in it are not executed. See [Configuration](configuration.md)
for the other options and [Single sign-on](single-sign-on.md) for connecting
Authentik or another OIDC provider after the public URL works.

On Debian:

```sh
systemctl enable --now initiative-server
systemctl status initiative-server --no-pager
journalctl -u initiative-server -n 100 --no-pager
```

On Alpine:

```sh
rc-update add initiative-server default
rc-service initiative-server start
rc-service initiative-server status
tail -n 100 /var/log/initiative/server.err
```

Check readiness locally:

```sh
curl --fail http://127.0.0.1:8173/api/v1/readyz
```

The first explicit service start runs Initiative's normal database bootstrap and
migrations. A package transaction itself does not contact the database.

## Files, upgrades and removal

| Location | Purpose |
| --- | --- |
| `/usr/lib/initiative` | Package-owned application, dependencies and release assets |
| `/etc/initiative/server.env` | Operator-owned configuration and secrets |
| `/var/lib/initiative/uploads` | Uploaded files |
| `/var/lib/initiative` | Root-owned service home; `initiative` has read/traverse access |
| `/var/log/initiative` | OpenRC service output; Debian also uses the journal |

Keep local uploads under `/var/lib/initiative/uploads`, which the service owns.
The parent `/var/lib/initiative` is owned by root with mode 0750; upgrades also
secure the parent of an older installation. For a custom
storage or export directory under that parent, create it as root and grant the
`initiative` account access before configuring it. On Debian, a custom
`UPLOADS_DIR` outside `/var/lib/initiative` also needs a systemd override granting
`ReadWritePaths` for the chosen directory.

Before upgrading, back up the database, PostgreSQL roles, configuration and uploads
as described in [Backups and updates](backups-and-updates.md). Install the new
package with your distribution's package manager. It stops the running service so
old Python processes do not keep running against replaced files. Configuration
and uploaded files are preserved. Review the release notes, then explicitly start
the service again to apply migrations.

Removing the package stops the service and preserves operator configuration and
state. Debian purge removes packaged configuration, but deliberately preserves
uploaded files, database contents and the service account. Delete those separately
only when you intend to destroy the instance.

Installing an older package does not undo a database migration. Restore the
matching pre-upgrade database backup before starting an older application version
if a newer version changed its schema.

## Building and releasing packages

The recipes and lifecycle tests live in `packaging/server/`, and
`server-packages.yml` builds each package on its own distribution, then installs,
upgrades and removes it in a clean one, on both architectures.

| Build | Where it runs | Browser app, editor and app update |
| --- | --- | --- |
| Release | Release Candidate, on the release branch | Copied from that release's Docker image |
| Test | A pull request touching the packaging, or a run by hand | Built from source by `scripts/build-server-assets.sh` and signed with a key made for the run |

A release's packages carry exactly the web assets of the image the walk and the
journeys checked, and the candidate is checked only once its packages pass too.
Build and Release then attaches that run's packages to the release; without them,
it builds them from the image it publishes.

Signing an Alpine package needs an RSA PEM `SERVER_APK_SIGNING_KEY` in the
`ota-release` environment, and a release candidate fails without it. Its public
half is published beside the packages.

Test packages carry a `-server-test-` version suffix. They exercise the packaging
and never stand in for a release's packages.
