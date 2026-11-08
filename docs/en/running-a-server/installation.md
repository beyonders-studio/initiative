---
icon: lucide/package
---

# Installation

The usual way to run Initiative is Docker Compose: one file brings up the app and its PostgreSQL database, and it's the setup every release is tested on. That matters at 11pm when something has gone sideways and you'd like to be in good company.

On a headless Debian or Alpine host without Docker (a Proxmox LXC, say), use the [native server packages](native-packages.md) instead. The `initiative-<version>.deb` on a release is the desktop app, so look for the ones named `initiative-server`.

## Quick start

You need Docker with its Compose plugin, a domain pointed at the machine, and a reverse proxy that handles HTTPS.

```bash
curl -o docker-compose.yml https://raw.githubusercontent.com/beyonders-studio/initiative/main/docker-compose.example.yml

cat > .env <<EOF
APP_URL=https://initiative.example.com
SECRET_KEY=$(openssl rand -hex 32)
POSTGRES_PASSWORD=$(openssl rand -hex 32)
EOF

docker compose up -d
```

Point your proxy at port **8173** with WebSockets passed through, then open your domain. The first person to register becomes the [owner](platform-roles.md).

| In `.env` | What it is | If you leave it out |
|---|---|---|
| `APP_URL` | The address people open Initiative at. Links in emails, sign-in redirects and passkeys all use it. | `http://localhost:8173`, for trying it on the machine it runs on |
| `SECRET_KEY` | Signs sessions and encrypts what Initiative stores. At least 32 characters. | Compose refuses to start |
| `POSTGRES_PASSWORD` | The database owner's password. | Compose refuses to start |

The compose file also reads `POSTGRES_USER` and `POSTGRES_DB` (both `initiative` unless set) and `BEHIND_PROXY` (`true` unless set). Every other setting goes in the way [Configuration](configuration.md#where-settings-go) describes.

A proxy on the same machine or your LAN, or Cloudflare in front of it, needs nothing more. One on another machine that reaches Initiative over a public address goes in [`FORWARDED_ALLOW_IPS`](configuration.md#running-behind-a-reverse-proxy).

!!! warning "Choose both secrets once, and keep them"
    PostgreSQL reads `POSTGRES_PASSWORD` only when it first creates the database. Changing it later doesn't change the password; it stops Initiative connecting.

    `SECRET_KEY` encrypts stored data and derives the database logins' passwords. Keep a copy somewhere safe, apart from your backups. To change it, follow [Changing the secret key](configuration.md#changing-the-secret-key); a straight swap leaves everything encrypted under the old one unreadable.

## What the compose file runs

| Service | Image | Holds |
|---|---|---|
| `db` | `postgres:17` | The database, in the Docker volume `postgres_data`. Compose waits for `pg_isready` before starting the app. |
| `initiative` | `ghcr.io/beyonders-studio/initiative:latest` | The app on port `8173`. Uploads go to `./uploads` beside the compose file, mounted at `/app/uploads`. |

Initiative is tested on PostgreSQL 16, 17 and 18. Each container keeps its last 50 MB of output on disk, in five 10 MB files.

Two things need to survive a restart, and both need [backing up](backups-and-updates.md): the `postgres_data` volume and the `./uploads` folder. Compose names the volume after the project folder, so `docker volume ls` shows it as `<folder>_postgres_data`.

## The database connection

Initiative needs one URL, connecting as the database's owner:

```text
DATABASE_URL=postgresql+asyncpg://initiative:<password>@db:5432/initiative
```

The compose file builds it from `POSTGRES_USER`, `POSTGRES_PASSWORD` and `POSTGRES_DB`, so you don't type it. Percent-encode any special characters in a password you put in a URL by hand.

At every start, Initiative uses that connection to create three logins of its own, closes it, and serves every request on those. Each login can do only its own job, which is how [How your data is kept separate](../security/how-your-data-is-kept-separate.md) is held by the database itself.

??? techspec "The three logins"
    | Login | Used for |
    |---|---|
    | `app_provisioner` | Migrations and creating each community's tables. It owns the app's objects and isn't a superuser. |
    | `app_user` | Every request. Row-level security applies to it. |
    | `app_admin` | Background jobs and start-up seeding. |

    Each password is derived from `SECRET_KEY` and set again on every start, so [changing `SECRET_KEY`](configuration.md#changing-the-secret-key) changes them too with nothing else to do.

    The owner also installs the search index's match operator, a `LEAKPROOF` function, which only a PostgreSQL superuser may create. The compose file's owner is one. With an owner that isn't, search returns the same results while reading more of its index, and the log says so at start.

### Naming the logins yourself

A connection pooler with its own user list, a managed PostgreSQL service, or a DBA who'd rather Initiative never held the owner's password all want the logins named in advance. Give the connections directly:

| Variable | Connects as | Required |
|---|---|---|
| `DATABASE_URL` | `app_provisioner` | Yes |
| `DATABASE_URL_APP` | `app_user` | Yes |
| `DATABASE_URL_ADMIN` | `app_admin` | Yes |
| `DATABASE_URL_BOOTSTRAP` | The database owner | No |

`DATABASE_URL_APP` and `DATABASE_URL_ADMIN` go together; setting one without the other stops the start with a message saying so. `DATABASE_URL_BOOTSTRAP` is allowed only beside them.

With `DATABASE_URL_BOOTSTRAP`, Initiative creates or updates the three logins at every start, with the passwords in their URLs. Without it, Initiative checks that they exist and have what they need, and stops with the SQL to run if they don't. To print that SQL in advance and run it as the owner:

```bash
docker compose exec -T initiative python -m app.db.bootstrap --print-sql
```

Each password in it is the SCRAM hash PostgreSQL stores, never the password itself.

To go back to one URL, point `DATABASE_URL` at the owner, remove the other three, and restart.

## The user it runs as

The container starts as root, creates its own user, makes `/app/uploads` that user's, and runs Initiative as that user. Nothing runs as root after that first moment, and you never have to fix the folder's ownership yourself.

| Variable | Accepted values | Default |
|---|---|---|
| `PUID` | A positive whole number, not `0` | `1000` |
| `PGID` | A positive whole number, not `0` | `1000` |

To match the account that owns the uploads folder on a NAS, set both: `PUID=99` and `PGID=100` is Unraid's `nobody:users`. Anything else stops the container with an error. The first line of its log says which way it started:

```text
container user: root at start, then 1000:1000 (PUID/PGID)
```

### Starting it as that user yourself

Some setups never start a container as root, such as a Kubernetes cluster enforcing the `restricted` Pod Security profile. For those, start it as a non-root user from the outset:

| Where | How |
|---|---|
| Docker Compose | `user: "1000:1000"` on the `initiative` service |
| `docker run` | `--user 1000:1000` |
| Kubernetes | `runAsUser` and `runAsGroup`, and `fsGroup` for the uploads volume |

Initiative then does nothing as root. `PUID` and `PGID` don't apply and nothing is chowned, so `/app/uploads` must already be writable by that user. The first log line reads `container user: 1000:1000 from the start (no PUID/PGID, no chown)`, followed by a second line if `PUID` or `PGID` is set and being ignored.

To go back, remove `user:` (or `--user`) and restart.

## Docker images

Images are published for `linux/amd64` and `linux/arm64`. Pick a tag by how you feel about surprises:

| Tag | Moves to | Suits you if |
|---|---|---|
| `latest` | Every release, the day it ships | You like new things and will say something when one bites |
| `stable` | A release we've promoted by hand, at least 72 hours after it shipped and with no open regression reported against it | You'd rather somebody else found it first |
| `0.78`, `0` | The newest release in that line | You want fixes without choosing each one |
| `0.78.0` | Nowhere, ever | You upgrade when you decide to, and not a minute before |

The compose file uses `latest`. To follow `stable`, change its `image:` line to `ghcr.io/beyonders-studio/initiative:stable`, then:

```bash
docker compose pull && docker compose up -d
```

The 72 hours are a minimum, not a timer. `stable` moves when we promote the next release that qualifies, so it can sit on one version for a while, and a release carrying a security fix can reach it sooner. It works because people run `latest`: a bug report with the **Version** filled in is exactly what holds a release back.

### Checking an image is ours

You never have to. Every image is signed by the workflow that built it, and carries an SBOM (a list of everything inside it) and a record of how it was built. If your setup checks images before running them, this is the check, using [cosign](https://docs.sigstore.dev/cosign/system_config/installation/):

```bash
cosign verify ghcr.io/beyonders-studio/initiative:stable \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --certificate-identity-regexp '^https://github\.com/beyonders-studio/initiative/\.github/workflows/docker-image\.yml@refs/(heads/(main|release/v.+)|tags/v.+)$'
```

It passes only for an image our release workflow built from a release branch or tag. Images built from `dev` are signed too, from `refs/heads/dev`, which this check deliberately refuses.

To read the SBOM:

```bash
docker buildx imagetools inspect ghcr.io/beyonders-studio/initiative:stable --format '{{ json .SBOM }}'
```

## Once it's running

- [ ] Register the first account. It becomes the [owner](platform-roles.md).
- [ ] Set up [email](email.md), so sign-in codes, password resets and digests can go out.
- [ ] Set up [backups](backups-and-updates.md), and restore one once.
