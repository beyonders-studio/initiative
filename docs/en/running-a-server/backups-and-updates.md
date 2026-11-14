---
icon: lucide/save
---

# Backups & updates

Running your own server comes with two chores: keeping a copy of everything, and keeping current. Neither takes long, and both matter far more than they feel like they do, right up until the afternoon one of them matters enormously.

## What to back up

| What | Where it is | Why |
|---|---|---|
| The database | The `db` container, in the `postgres_data` volume | Every project, task, comment, document and setting, and the logins and per-community roles they're granted to |
| Uploads | `./uploads` beside the compose file, unless they're in [object storage](object-storage.md) | Every file people attached or uploaded |
| `SECRET_KEY` | Your `.env` | Without it, a restored database can't read what it encrypted |

Back up the first two together and on a schedule, and keep the copies somewhere that isn't the server. Keep `SECRET_KEY` somewhere safe and separate, with your other secrets. An export Initiative wrote to `EXPORT_DESTINATION_DIR` is yours to collect too; Initiative never deletes it.

On a [native package](native-packages.md), the uploads are in `/var/lib/initiative/uploads` and the settings, `SECRET_KEY` included, in `/etc/initiative/server.env`.

### The database

From the folder with your compose file, with the user the compose file uses (`initiative`, unless you set `POSTGRES_USER`):

```bash
docker compose exec -T db pg_dumpall -U initiative > initiative-$(date +%F).sql
```

`pg_dumpall` copies the whole `db` container into one file: the database, and the logins and per-community roles Initiative grants it to. It takes a consistent snapshot while Initiative runs, so there's no need to stop anything. The file holds the logins' password hashes, so keep it as safe as `SECRET_KEY`.

On a [native package](native-packages.md), give Initiative a PostgreSQL server of its own, and run `pg_dumpall` against it as a superuser. On a server shared with other apps, `pg_dumpall` copies their databases too.

Run it nightly and keep a couple of weeks. As a crontab line, writing into a `backups` folder you've made beside the compose file, with the `%` escaped the way cron needs:

```text
0 3 * * * cd /srv/initiative && docker compose exec -T db pg_dumpall -U initiative | gzip > backups/initiative-$(date +\%F).sql.gz
```

### Uploads

From the same folder, with `sudo` in front if the folder belongs to the container's user rather than yours:

```bash
tar -czf uploads-$(date +%F).tar.gz uploads
```

With [S3-compatible storage](object-storage.md), back up the bucket with your store's own versioning or replication. With [stored files encrypted](object-storage.md#encrypting-stored-files) under `local`, the copies open only with the same `SECRET_KEY`.

## Restoring

Restore a backup once, on another machine or a VM, so you know it works before the day you need it. Into a fresh setup with the same compose file and the same `.env`:

1. Start only the database:

    ```bash
    docker compose up -d db
    ```

2. Put the database back, roles and all:

    ```bash
    docker compose exec -T db psql -U initiative -d postgres < initiative-2026-11-07.sql
    ```

    For a nightly copy, unzip it on the way in:

    ```bash
    gunzip -c backups/initiative-2026-11-07.sql.gz | docker compose exec -T db psql -U initiative -d postgres
    ```

    It says role `initiative` and database `initiative` already exist, which is fine: the compose file made both when the database first started. It also sets the `initiative` login's password back to the one in the backup, which is why the restore wants the same `.env`.

3. Put the uploads back beside the compose file:

    ```bash
    tar -xzf uploads-2026-11-07.tar.gz
    ```

4. Start Initiative:

    ```bash
    docker compose up -d
    ```

At start, Initiative sets its logins' passwords again from `SECRET_KEY` and repairs any grant the restore didn't bring back, then runs whatever migrations the image is newer than. An image older than the backup refuses to start and says so (see [If it won't start](#if-it-wont-start)).

## Updating

```bash
docker compose pull
docker compose up -d
```

Back up first. It's one command and the cheapest insurance you'll ever buy.

Migrations run by themselves at start, before Initiative serves anything. Copies starting together take turns, so only one runs them. Migrations only go forward: going back to an older version means restoring the backup you took before updating.

A database from a release older than 0.75.0 first needs one start on 0.75.0 or a later release older than the one you're updating to, such as `ghcr.io/beyonders-studio/initiative:0.75.2`, and then the new one. The start-up message says which if that's you.

Initiative follows semantic versioning, and the [changelog](https://github.com/beyonders-studio/initiative/blob/main/CHANGELOG.md) lists what changed in each release. Which tag to follow (`latest`, `stable`, or a pinned version) is under [Docker images](installation.md#docker-images).

### Knowing what's running

| Where | What it says |
|---|---|
| `/api/v1/version` | `{"version": "0.78.0"}` |
| The version in the sidebar's footer | Opens **Version Information**: the version running, the newest release, **Update available** or **Up to date**, and the changelog |

The newest release comes from the project's GitHub releases, asked once every 6 hours and shared by everybody on your server. A server that can't reach GitHub shows it as **Unavailable** and asks again 15 minutes later.

When the server is updated, people with the app open are told a new version is ready and reload into it.

### The phone and desktop apps

The apps take the web part of each release from your server, so updating the server updates them on their next launch, with no app store involved. Each update is signed by the project, and an app accepts only a signed one. An image you built yourself carries none, so the apps stay on the version they have and say so.

Now and then a release changes the apps' native part too. The server then tells an app that's too old to update from its store or the release's APK (or, on a computer, the latest desktop download), and the app keeps its current version until it's updated. The phone apps and the desktop app each have their own minimum, so a change to one never makes the other's users reinstall.

## If it won't start

It's rare, and recoverable. First, read the end of the log:

```bash
docker compose logs initiative | tail -n 40
```

If the last thing it says is a message framed in lines of `=` telling you what to do, that message is the whole answer. The usual ones:

| Message | What to do |
|---|---|
| `This image is older than the database.` | Start the release that last upgraded the database, or a newer one. If it keeps starting the old image after a pull, look for a container left behind by an unfinished upgrade (Compose renames it to `<12 hex characters>_initiative`), remove it, and run `docker compose up -d` again. |
| `This database is from before v0.75.0` | Start once on the release it names first, as above. |
| `DATABASE_URL_ADMIN connects as …, which does not hold the BYPASSRLS attribute.` | Give Initiative its owner connection and restart, or run the `ALTER ROLE` it prints as a superuser. |

A setting that stops it starting is named too, with the reason and without its value.

Otherwise, find the report it wrote. The log is one JSON object per line and the container keeps retrying, so there may be several. This prints the most recent as plain text, and needs `jq`, which your package manager has:

```bash
docker compose logs --no-log-prefix initiative \
  | grep 'Initiative could not start' | tail -n 1 | jq -r .msg
```

It lists the version, how the database is set up, the PostgreSQL version, where the migrations stopped, and the error. The passwords and keys the server is configured with are taken out, but read it over before you post it. Then paste it into [an issue](https://github.com/beyonders-studio/initiative/issues).

The fix is almost always a newer release, which picks up exactly where this one stopped. Going back to the older version means restoring the backup you took before updating. You took one. It was one command.
