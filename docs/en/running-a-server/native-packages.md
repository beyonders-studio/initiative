---
icon: lucide/package-open
---

# Native server packages

The `initiative-server` packages run Initiative straight on a Linux host or an unprivileged Proxmox LXC, for a machine that would rather not run Docker. Each one carries the app, its locked Python dependencies, the browser app, the document editor and the signed updates for the phone and desktop apps. The installed server needs no Docker, Node.js, compiler or download step.

The `initiative-<version>.deb` on a release is the desktop app. For a server, take a package whose name starts with **`initiative-server`**.

## Supported targets

| Distribution | Python | Service manager | Architectures |
|---|---|---|---|
| Debian 13 | 3.14, carried in the package | systemd | `amd64`, `arm64` |
| Alpine 3.24 | 3.14, the system's | OpenRC | `x86_64`, `aarch64` |

Initiative runs on Python 3.14 everywhere. Debian 13's own Python is 3.13, so the Debian package carries 3.14 in `/usr/lib/initiative/python`, and its fixes arrive with Initiative's releases rather than Debian's updates.

The native dependencies are built for each target's Python and C library, so a Debian package won't install on Alpine, and copying a virtual environment between them won't work either. A major distribution or Python upgrade needs the matching package from a newer release.

## Install

You need a PostgreSQL database first, local or remote, and its owner's connection URL. Initiative is tested on PostgreSQL 16, 17 and 18. Installing the package creates no database accounts, chooses no passwords and runs no migrations.

Download the package for your distribution and architecture, and the checksum file beside it, from the release's **Native Server Packages** section. The names look like this:

| File | What it is |
|---|---|
| `initiative-server_0.78.0-1_amd64.deb` | The Debian package |
| `initiative-server-0.78.0-r1-x86_64.alpine` | The Alpine package. It's named `.alpine` rather than `.apk` so Android app updaters don't mistake it for the phone app, and `apk` installs it all the same. |
| `initiative-server.rsa.pub` | The key the Alpine packages are signed with |
| `initiative-server-deb-amd64.sha256`, `initiative-server-apk-amd64.sha256` | Checksums for one format and architecture (`amd64` or `arm64`). The Alpine one covers the key too. |

With the files a checksum file lists in the same folder, check them before installing:

```sh
sha256sum -c initiative-server-deb-amd64.sha256
```

On Debian, as root:

```sh
apt install ./initiative-server_0.78.0-1_amd64.deb
```

APT fetches the distribution packages it depends on. The `.deb` and its checksums are release downloads, not an APT repository.

On Alpine, as root, trust the signing key once, keeping its file name, then install:

```sh
cp initiative-server.rsa.pub /etc/apk/keys/
apk add ./initiative-server-0.78.0-r1-x86_64.alpine
```

Get that key from the release itself, and keep it in place for later upgrades. Don't use `--allow-untrusted`.

The package creates an unprivileged `initiative` account and installs a service, and **doesn't start it**. That gives you time to configure the server, and to take a database backup before any start can migrate the database.

## Configure and start

Edit `/etc/initiative/server.env` as root. It's read as `KEY=value` lines and never run as a shell script, so commands in it do nothing.

| Variable | Starts as | What it is |
|---|---|---|
| `SECRET_KEY` | Empty, and required | `openssl rand -hex 32` makes one. Keep it across upgrades: it encrypts stored data as well as signing sessions. |
| `DATABASE_URL` | Empty, and required | The owner's connection, such as `postgresql+asyncpg://initiative:PERCENT_ENCODED_PASSWORD@127.0.0.1:5432/initiative`. Percent-encode special characters in the password. |
| `APP_URL` | Empty, and required | The address people open, such as `https://tasks.example.org` |
| `INITIATIVE_HOST` | `127.0.0.1` | The address it listens on |
| `INITIATIVE_PORT` | `8173` | The port, 1 to 65535 |
| `BEHIND_PROXY` | `false` | `true` or `false` exactly. See below. |
| `FORWARDED_ALLOW_IPS` | Unset | Only for a proxy reaching Initiative over a public address |
| `UPLOADS_DIR` | `/var/lib/initiative/uploads` | Where files are kept |
| `ENABLE_PUBLIC_REGISTRATION` | `false` | Whether anyone may sign up without an invite, read on the first start only |

A missing required value, a port out of range, or a `BEHIND_PROXY` that isn't `true` or `false` stops the service with a message naming it. Every other setting in [Configuration](configuration.md) goes in the same file.

Put a reverse proxy with HTTPS and WebSockets in front, and set `BEHIND_PROXY=true`. A proxy on this machine or your LAN, or Cloudflare in front of it, needs nothing more; [Running behind a reverse proxy](configuration.md#running-behind-a-reverse-proxy) has the one setup that does. Set `INITIATIVE_HOST` yourself to listen on another interface, and only once the server is configured.

The first account registered becomes the owner, whatever `ENABLE_PUBLIC_REGISTRATION` says, so register it before you open the server up. To have it made for you instead, set `FIRST_OWNER_EMAIL` and `FIRST_OWNER_PASSWORD`, start the server, then remove both. After that, people sign up only with an invite unless you change **Let anyone sign up** in the app.

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

Then check it's ready:

```sh
curl --fail http://127.0.0.1:8173/api/v1/readyz
```

The first start runs Initiative's usual database setup and migrations. Installing a package never touches the database.

| | Debian | Alpine |
|---|---|---|
| Runs as | `initiative` | `initiative` |
| Restarts | On failure, after 5 seconds | Up to 5 times in 60 seconds, 5 seconds apart |
| Application log | The journal | `/var/log/initiative/server.err` |
| The record of who did what | The journal | `/var/log/initiative/server.log` |

## Files

| Location | What it holds | Owned by |
|---|---|---|
| `/usr/lib/initiative` | The application, its dependencies and release assets | The package |
| `/etc/initiative/server.env` | Your configuration and secrets, mode `0640` | You |
| `/var/lib/initiative` | The service's home, mode `0750` | `root`, readable by `initiative` |
| `/var/lib/initiative/uploads` | Uploaded files | `initiative` |
| `/var/log/initiative` | Service output on Alpine | `initiative` |

For a storage or export folder of your own under `/var/lib/initiative`, create it as root and give the `initiative` account access before pointing a setting at it. On Debian the service can write only to `/var/lib/initiative` and `/var/log/initiative`, so a folder anywhere else needs a systemd override:

```sh
systemctl edit initiative-server
```

```ini
[Service]
ReadWritePaths=/srv/initiative-files
```

## Upgrades and removal

Before upgrading, back up the database, `/etc/initiative/server.env` and the uploads, as [Backups & updates](backups-and-updates.md) describes. Then install the new package the same way as the first. It stops the running service so no old process keeps running against replaced files, and leaves your configuration and uploads alone. Read the release notes, then start the service again, which applies the migrations.

Installing an older package doesn't undo a migration. To run an older version on a database a newer one changed, restore the backup taken before the upgrade first.

| Command | Stops the service | Removes your configuration | Removes uploads, logs, the database and the `initiative` account |
|---|---|---|---|
| `apt remove initiative-server` | Yes | No | No |
| `apt purge initiative-server` | Yes | Yes | No |
| `apk del initiative-server` | Yes | No | No |
| `apk del --purge initiative-server` | Yes | Yes | No |

Delete the rest by hand only when you mean to be done with the server for good.

## Building the packages

The recipes live in `packaging/server/`, and its `README.md` has how to build one yourself. Every build is installed, upgraded and removed in a clean copy of its distribution, on both architectures, before it's kept.

| Build | Made by | Browser app, editor and app update |
|---|---|---|
| Release | The release candidate run, on the release branch | Copied from that release's Docker image |
| Test | A pull request touching the packaging, or a run by hand | Built from source by `scripts/build-server-assets.sh`, and signed with a key made for the run |

A release's packages carry exactly the web assets of the image that was tested, and the release is cut only once its packages pass too. Test packages carry a `-server-test-` version suffix, and never stand in for a release's.
