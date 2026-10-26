# Initiative

[![CI](https://github.com/beyonders-studio/initiative/actions/workflows/ci.yml/badge.svg?branch=main&event=push)](https://github.com/beyonders-studio/initiative/actions/workflows/ci.yml?query=branch%3Amain+event%3Apush)
[![Latest Release](https://img.shields.io/github/v/release/beyonders-studio/initiative?sort=semver)](https://github.com/beyonders-studio/initiative/releases)
[![License](https://img.shields.io/github/license/beyonders-studio/initiative)](LICENSE)

Initiative is a shared workspace for groups that need to get things done together, like a small business, a club, a committee, the people running the community theater fundraiser, or your family. Projects, tasks, files, calendars and the rest live in one place, so the plan stops being spread across a group chat and three spreadsheets.

You can start with one board and a few tasks and never touch anything else. When the group needs more, the other tools are already there, and you decide who gets to see and change each one.

![Initiative showing a project board](docs/en/images/home/overview.png)

The [user guide](https://beyonders-studio.github.io/initiative/) covers using Initiative and running your own server.

> [!NOTE]
> Initiative hasn't reached 1.0 yet, so the API can still change between minor releases.

## What's in it

- Projects and tasks, with board, table and calendar views
- Files with real-time editing, including documents, spreadsheets and whiteboards
- Calendars, posts, wikis, catalogs, queues, counters and dashboards
- Communities with initiatives inside them, and sharing down to a single project or file
- A marketplace of plug-ins, dashboards and ready-made projects, fed by the Initiative registry
- Apps for iPhone, Android, Windows, Mac and Linux, and an installable web app

## The Initiative registry

The Initiative registry is a live, signed catalog of plug-ins, dashboards and ready-made projects, published at `https://beyonders-studio.github.io/initiative-developer/public/`. That address is built into Initiative, so every server follows the registry from its first start with nothing to set up. It checks for new listings every fifteen minutes and shows them in its communities' marketplaces, and every file is checked against Initiative's built-in key before it's used.

The registry is built from [initiative-developer](https://github.com/beyonders-studio/initiative-developer), and getting a listing into it is a pull request there. Once it's merged, it reaches every server that follows the registry. Plug-ins are written with the [plug-in SDK](https://github.com/beyonders-studio/initiative-plugin-sdk), and [Publishing your own listings](https://beyonders-studio.github.io/initiative/en/running-a-server/publishing-listings/#publishing-to-the-initiative-registry) walks through the rest.

## Self-hosting

Initiative is one image, `ghcr.io/beyonders-studio/initiative` (`linux/amd64` and `linux/arm64`), run beside Postgres. [docker-compose.example.yml](docker-compose.example.yml) is the supported setup, and it reads three required values from `.env`:

| Variable | |
|---|---|
| `APP_URL` | The public address people reach it at |
| `SECRET_KEY` | At least 32 characters. It encrypts stored data, so don't rotate it casually |
| `POSTGRES_PASSWORD` | Only read when the database is first created. It goes into the connection URL, so keep it alphanumeric |

Run `docker compose up -d` and point your reverse proxy at port 8173. The first account to register becomes the server owner.

Tags are `latest`, `stable` (promoted after a few days with no regressions) and version numbers.

> [!WARNING]
> Don't run the `dev` tag on a server you care about. It's built from unreleased work, and its database migrations often change between builds before a release settles them. A database that ran one of those in-between migrations may have no upgrade path to the release, so you'd be restoring from a backup.

These pages cover the rest:

- [Installation](https://beyonders-studio.github.io/initiative/en/running-a-server/installation/) has the image tags, PUID/PGID and the database setup
- [Configuration](https://beyonders-studio.github.io/initiative/en/running-a-server/configuration/) lists every setting
- [Email](https://beyonders-studio.github.io/initiative/en/running-a-server/email/), [single sign-on](https://beyonders-studio.github.io/initiative/en/running-a-server/single-sign-on/) and [push notifications](https://beyonders-studio.github.io/initiative/en/running-a-server/push-notifications/)
- [Backups and updates](https://beyonders-studio.github.io/initiative/en/running-a-server/backups-and-updates/)

If you'd rather not run a server, there's a [hosted option](https://beyonders-studio.github.io/initiative/en/self-host-or-hosted/) too.

## Apps

The phone apps are on the App Store and Google Play under Initiative, by Beyonders Studio. On Android you can also install from the releases page, or let Obtainium keep it updated for you:

[<img src="https://raw.githubusercontent.com/ImranR98/Obtainium/main/assets/graphics/badge_obtainium.png" alt="Get it on Obtainium" width="200">](https://apps.obtainium.imranr.dev/redirect?r=obtainium%3A%2F%2Fadd%2Fhttps%3A%2F%2Fgithub.com%2Fbeyonders-studio%2Finitiative)

The desktop installers (`.exe`, `.dmg` and `.deb`) are attached to releases that change the app. Most releases only change the web side, which the apps pick up from your server on their own, so they don't come with new installers. [Installing the app](https://beyonders-studio.github.io/initiative/en/getting-started/install-the-app/) has the details.

## Built with

FastAPI, SQLModel and PostgreSQL on the backend, React, TypeScript and Vite on the frontend, Capacitor for the phone apps and Electron for the desktop app.

## Contributing

[CONTRIBUTING.md](CONTRIBUTING.md) explains how to get a dev environment running and how changes get in. Pull requests go to the `dev` branch, and your first one asks you to sign the [Contributor License Agreement](CLA.md).

To report a security problem, follow [SECURITY.md](SECURITY.md) rather than opening an issue.

## License

Initiative is open core. Everything in this repository, which is the whole app you self-host, is licensed under the [AGPL-3.0](LICENSE). Morelitea LLC, doing business as Beyonders Studio, holds the copyright and the commercial rights.

| Repository | License | What it is |
|---|---|---|
| [initiative](https://github.com/beyonders-studio/initiative) | AGPL-3.0 | The app: backend, frontend, and the phone and desktop builds |
| [initiative-plugin-sdk](https://github.com/beyonders-studio/initiative-plugin-sdk) | MIT | The SDK and CLI for writing plug-ins |
| [initiative-developer](https://github.com/beyonders-studio/initiative-developer) | MIT | The plug-in registry, and a GitHub plug-in to start your own from |

Automations and billing are proprietary and live outside this repository. They exist to run the hosted service, and a self-hosted server is the complete product without them.
