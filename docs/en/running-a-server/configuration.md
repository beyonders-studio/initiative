---
icon: lucide/sliders-horizontal
---

# Configuration

Initiative keeps its settings in two places. Environment variables hold what it needs before it can reach its own database, and they're read once, at start. Everything else lives in the app under **Settings → Platform**, takes effect the moment you save it, and never needs a restart at 5pm on a Friday.

The first half of this page is every environment variable. From [Settings in the app](#settings-in-the-app) on, it's the platform settings that don't have a page of their own, and the end covers [logs](#logs) and [monitoring](#monitoring-with-prometheus).

## Where settings go

| How you run it | Where variables go | To apply a change |
|---|---|---|
| Docker Compose | `.env` beside the compose file, passed through as below | `docker compose up -d` |
| [Native package](native-packages.md) | `/etc/initiative/server.env` | `systemctl restart initiative-server` (Debian) or `rc-service initiative-server restart` (Alpine) |

The example compose file hands the container only the variables it names: `APP_URL`, `SECRET_KEY`, `BEHIND_PROXY` and the database URL it builds. Any other line in `.env` reaches Initiative once something passes it on. The tidy way is an override file beside the compose file, which Compose reads on its own and which survives downloading a new `docker-compose.yml`:

```yaml
# docker-compose.override.yml
services:
  initiative:
    env_file: .env
```

After that, every line in `.env` reaches Initiative, and `docker compose up -d` recreates the container whenever one changes.

Every variable follows the same rules:

- A value that fails its check stops the start. The log names the variable and the reason, never the value.
- On/off values take `true` or `false`. `BEHIND_PROXY` must be lowercase, because the start script compares the text.
- Lists (`CORS_ALLOWED_ORIGINS`, `OIDC_SCOPES`, `AUTH_LOGIN_METHODS`) take items separated by commas or spaces, or a JSON list.

## Required

| Variable | Accepted values | Default |
|---|---|---|
| `SECRET_KEY` | At least 32 characters, with no whitespace at either end. `change-me`, `changeme`, `super-secret-key` and `secret` are refused. | None. Initiative won't start without it. |
| `DATABASE_URL` | `postgresql+asyncpg://USER:PASSWORD@HOST:PORT/DATABASE`, connecting as the database owner, with special characters in the password percent-encoded | `postgresql+asyncpg://initiative:initiative@localhost:5432/initiative` |
| `APP_URL` | The full address people open, such as `https://initiative.example.com` | `http://localhost:5173`. The compose file sets `http://localhost:8173`, and the native packages require it. |

**`SECRET_KEY`** signs session tokens, encrypts the secrets Initiative stores (email addresses, the SMTP password, sign-in provider secrets, AI keys, the S3 secret, the captcha secret, the Firebase service account), keys the lookup that finds an account by its email address, and derives the database logins' passwords. `openssl rand -hex 32` makes a good one.

**`DATABASE_URL`** is the owner, and Initiative makes its own logins from it. [The database connection](installation.md#the-database-connection) has the details, and the other way to set it up.

**`APP_URL`** decides:

- the links in every email, and where sign-in providers send people back to
- the browser origin allowed to make signed-in requests
- the domain passkeys belong to. Change the host and every passkey stops answering, so people sign in another way and add new ones.
- with `https`, that cookies are marked `Secure` and every response carries `Strict-Transport-Security: max-age=63072000; includeSubDomains`, which holds browsers to HTTPS on that host and its subdomains for two years

### Changing the secret key

1. Set `PREVIOUS_SECRET_KEY` to the current `SECRET_KEY`, exactly as it is.
2. Set `SECRET_KEY` to a new one.
3. Restart. Before it serves anything, Initiative re-encrypts everything sealed under the old key, recomputes the email lookups, and gives the database logins their new passwords. With `STORAGE_ENCRYPTION=local` it re-wraps each community's storage key too, and leaves the files alone.
4. Once the log says `secret-key rotation complete`, remove `PREVIOUS_SECRET_KEY` and restart again.

A start with both set finds anything already done and skips it, so an extra restart in between is harmless. A value that opens under neither key was unreadable before you started; the log counts them, and `PREVIOUS_SECRET_KEY` stays until you've looked.

To see the counts first, stop the server and run `python -m app.db.secret_key_rotation --dry-run` with both keys set.

Changing `SECRET_KEY` without step 1 leaves everything encrypted under the old key unreadable, sign-in included.

## Database

Leave all of these alone unless you have the particular reason each one is for.

| Variable | Accepted values | Default | What it does |
|---|---|---|---|
| `DATABASE_URL_APP` | A database URL | Unset | The request login, when you [name the logins yourself](installation.md#naming-the-logins-yourself). Set with `DATABASE_URL_ADMIN` or not at all. |
| `DATABASE_URL_ADMIN` | A database URL | Unset | The background-work login, set with `DATABASE_URL_APP`. |
| `DATABASE_URL_BOOTSTRAP` | A database URL | Unset | The owner, used at start to create all three logins with the passwords in their URLs. Allowed only beside the two above. |
| `DATABASE_URL_LISTEN` | A database URL | `DATABASE_URL` | The one connection each process holds open to pass live-update signals to the others, with PostgreSQL's `LISTEN` and `NOTIFY`. Point it straight at PostgreSQL when the other URLs go through a pooler that hands out a new connection per transaction, since that can't hold one open. |
| `DATABASE_URL_QUERY` | A database URL | `DATABASE_URL_APP` | Where dashboard widgets' SQL and export renders read, which may trail the primary by a moment. Point it at a read replica. It connects as the request login: with one owner URL, give only the host and database and Initiative fills the login in; with named logins, its user must match `DATABASE_URL_APP`'s or the start stops. |
| `DB_POOL_SIZE` | A whole number, 1 or more | `5` | Connections each request pool and each background pool keeps open, per process. |
| `DB_MAX_OVERFLOW` | A whole number, 0 or more | `10` | How many more each of those may open under load. |
| `DB_POOL_RECYCLE_SECONDS` | Seconds | `1800` | How old a pooled connection may get before it's closed and replaced. PostgreSQL's memory for a connection grows with every community it has served, and closing the connection is the only thing that gives it back. `-1` never replaces one. |
| `DB_COHORTS` | A whole number, 1 or more | `1` | Splits communities into this many groups, each with its own request, background and dashboard pools, so a connection only ever opens its own group's tables. A community's group is its id modulo this number. |
| `DB_COHORT_DATABASE` | A name containing `{cohort}`, such as `initiative_c{cohort}` | Unset | The database name each group's connections ask for, for a pooler with an alias per group. `{cohort}` becomes the group's number, and any other braces stop the start. Unset, every group uses the database the request login's URL names. |

??? techspec "How many connections one process opens"
    Pools open connections as they need them, up to these ceilings. With the defaults:

    | Pool | Most connections |
    |---|---|
    | Requests | `DB_POOL_SIZE` + `DB_MAX_OVERFLOW`, so 15 |
    | Background work | 15 |
    | Migrations and setting up communities | 15 |
    | Dashboard SQL | 4. A statement waits up to 5 seconds for one. |
    | Live-update signals | 1 |

    With `DB_COHORTS` above 1, each group adds a request pool, a background pool and a dashboard pool of those sizes, and the first two pools above serve the work that belongs to no community. The owner connection is open only during start-up. Multiply by the number of processes when you set PostgreSQL's `max_connections`.

## Sessions and signing keys

| Variable | Accepted values | Default | What it does |
|---|---|---|---|
| `AUTH_ACCESS_TTL_MINUTES` | Minutes | `15` | How long the short-lived token a signed-in browser or app presents lasts before it's renewed in the background. |
| `AUTH_REFRESH_TTL_DAYS` | Days | `30` | How long a browser session survives unused. Every use pushes it forward. The phone and desktop apps get 90 days whatever this says. **Idle minutes**, in [How long people stay signed in](#how-long-people-stay-signed-in), shortens it from the app. |
| `JWT_SIGNING_KEY` | The same rules as `SECRET_KEY` | `SECRET_KEY` | A separate key for signing tokens, so it can change without touching anything stored. Changing it invalidates every token signed with the old one. |
| `PREVIOUS_SECRET_KEY` | The old `SECRET_KEY`, exactly | Unset | Set only while [changing the secret key](#changing-the-secret-key). It's read as written, with no checks. |

## Network

| Variable | Accepted values | Default | What it does |
|---|---|---|---|
| `BEHIND_PROXY` | `true` or `false`, lowercase | `false`. The example compose file sets `true`. | Believe `X-Forwarded-For` and `X-Forwarded-Proto` from a trusted proxy, so each visitor is recognized by their own address and HTTPS is detected. See [Running behind a reverse proxy](#running-behind-a-reverse-proxy). |
| `FORWARDED_ALLOW_IPS` | Addresses or CIDR ranges, comma-separated | `127.0.0.0/8,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,169.254.0.0/16,fc00::/7,fe80::/10` | The proxies to believe, read only with `BEHIND_PROXY=true`. Setting it replaces the whole default, so list every proxy you trust. |
| `CORS_ALLOWED_ORIGINS` | Origins, such as `https://app.example.com` | None | Other websites allowed to make signed-in requests from a browser. `APP_URL` and the phone and desktop apps are always allowed. A path is dropped, since only the scheme, host and port count, and `*` adds nothing. |
| `CLIENT_COUNTRY_HEADER` | A header name, such as `CF-IPCountry` | Unset | The header your proxy writes the visitor's two-letter country code into. Initiative reads it to apply the minimum age for an account, and for a plug-in, where the visitor is, and never stores it. Unset, or holding something that isn't a country, the highest minimum applies. Set it only when every request reaches Initiative through that proxy. |

The container's `PUID` and `PGID` are on [Installation](installation.md#the-user-it-runs-as), and the native packages' `INITIATIVE_HOST` and `INITIATIVE_PORT` are on [Native server packages](native-packages.md#configure-and-start).

## Running behind a reverse proxy

Put Initiative behind a proxy that handles HTTPS and forwards to port 8173. It needs four things from the proxy:

| What | Why |
|---|---|
| WebSockets passed through | Live editing, notifications and counters each hold a connection open. The server sends a heartbeat on each one every 30 seconds, so an idle timeout of 60 seconds or more keeps them up. |
| `X-Forwarded-For` and `X-Forwarded-Proto` | Rate limits, sign-in records and the HTTPS check see the visitor rather than the proxy. |
| Requests up to 64 MB | A whiteboard is saved whole and can reach 64 MB. Files arrive in pieces of up to 50 MB. |
| `/.well-known/assetlinks.json` passed to Initiative | The Android app reads it before offering passkeys. See [The app association files](#the-app-association-files). |

Caddy does all four with nothing extra:

```text
initiative.example.com {
    reverse_proxy localhost:8173
}
```

nginx stops at 1 MB and drops WebSocket headers unless told otherwise. Inside the `server` block that serves your domain over HTTPS:

```nginx
client_max_body_size 64m;

location / {
    proxy_pass http://127.0.0.1:8173;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

Then set `BEHIND_PROXY=true`, which the example compose file already does. Initiative believes a proxy on the same machine, in the compose network or on your LAN with nothing more to set. Behind a Cloudflare Tunnel, or Cloudflare's proxied DNS in front of your own Caddy or nginx, it recognizes each visitor too: a request that resolves to one of Cloudflare's published addresses takes the visitor from `CF-Connecting-IP`.

The one setup that needs more is a proxy on another machine that reaches Initiative over a public address. List it in `FORWARDED_ALLOW_IPS`, along with every other proxy you trust. When requests carry `X-Forwarded-For` from an address Initiative doesn't believe, the log says which setting to change, at most once an hour.

With `BEHIND_PROXY=false`, Initiative takes each connection's own address as the visitor's, which is right only when nothing sits in front of it.

## The app association files

A phone lets an app use a site's passkeys only when the site lists the app in a file at a fixed address. Initiative serves both files, built from the project's own app identities, which are the project's to vouch for rather than something you configure:

| File | Read by | What it names |
|---|---|---|
| `/.well-known/assetlinks.json` | Android | The Initiative app's package and the fingerprint of the key it's signed with |
| `/.well-known/apple-app-site-association` | iPhone | The Initiative iPhone app. It answers 404 until that app is published. |

Both are served as JSON at exactly those paths, with no redirect, and only when `APP_URL` can carry a passkey at all: `https`, with a host name rather than an IP address. Anything else under `/.well-known/` answers 404, never the app's page.

There's nothing to set. Android checks the file on whatever server the app points at, so the Android app signs in with passkeys on yours by itself. An iPhone reads the file only for addresses built into the app, so on your server the iPhone app sends people to the browser for passkeys, which works everywhere. The Windows app reads neither file and uses passkeys on any `https` address.

If your proxy answers anything under `/.well-known/` itself, as some do for certificates, pass `/.well-known/assetlinks.json` through to Initiative. Without it, the Android app sends people to the browser for passkeys.

## Running more than one copy

Several copies of Initiative can serve one address from one database. They share these:

| Shared | How |
|---|---|
| The database | The same `DATABASE_URL` everywhere. Migrations take a lock, so copies starting together upgrade it once. |
| Uploads | [S3-compatible storage](object-storage.md), or the same `UPLOADS_DIR` mounted into every copy |
| Rate-limit counts | `RATE_LIMIT_STORAGE_URI` set to the same Redis URL. Unset, each copy counts on its own. |
| `SECRET_KEY` and every other variable | Identical everywhere |

Each copy keeps live editing sessions, cursors and who's here for the people connected to it. People editing a document through the same copy see each other type. Through different copies, each copy saves what changed every 30 seconds and takes in what the others saved on the same pass, so an edit reaches people on another copy within about a minute, and nobody's edits are lost.

Each process runs the document editor in a helper process that starts the first time somebody there edits a document and stops after 5 idle minutes. Its JavaScript heap is capped at 512 MB. A process where nobody edits never starts one.

Storage settings saved in the app reach the other copies within 30 seconds.

## Rate limits

Every limit counts against the signed-in account, so an office full of people behind one address doesn't share an allowance or lock each other out. A request with no account behind it yet counts against its network address. Loading the app's own pages and scripts counts against nothing.

| Variable | Accepted values | Default | What it does |
|---|---|---|---|
| `RATE_LIMIT_DEFAULT` | A count per period, such as `100/minute`, or several joined by `;`, such as `200/minute;2000/hour` | `100/minute` | The limit for every route without one of its own. Empty turns this default off, and the limits routes set for themselves remain. |
| `RATE_LIMIT_STORAGE_URI` | `memory://`, or a `redis://`, `rediss://`, `redis+sentinel://` or `redis+cluster://` URL | `memory://` | Where counts are kept. `memory://` counts in each process, and a Redis URL gives every process one count. While Redis can't be reached, each process counts in its own memory until it answers again. |
| `RATE_LIMIT_ENABLED` | `true` or `false` | `true` | `false` turns off every limit, including the ones routes set for themselves and the two below. It's for testing sign-in flows on your own machine. |

Two allowances count per email address typed in, whoever types it:

| Allowance | Limit |
|---|---|
| Sign-in codes and password-reset emails, together | 5 per 15 minutes per address |
| Wrong passwords | 5 per 15 minutes per address |

## Files and exports

| Variable | Accepted values | Default | What it does |
|---|---|---|---|
| `UPLOADS_DIR` | A directory | `uploads`, under the working directory, which is `/app/uploads` in the image | Where files live with local storage, and what [moving to S3](object-storage.md#moving-existing-files-to-s3) copies from. The native packages set `/var/lib/initiative/uploads`. |
| `STORAGE_ENCRYPTION` | Unset, `local` or `gcp_kms` | Unset | Encrypt every stored file in Initiative before it reaches storage. See [Encrypting stored files](object-storage.md#encrypting-stored-files). |
| `STORAGE_ENCRYPTION_KMS_KEY` | `projects/<p>/locations/<l>/keyRings/<r>/cryptoKeys/<k>` | Unset | The Cloud KMS key for `gcp_kms`, which stops the start without it. |
| `UPLOAD_SCANNER_URL` | The scanner's base URL | Unset | Scan every incoming file before storing it. See [Scanning uploads](object-storage.md#scanning-uploads). |
| `UPLOAD_SCANNER_TOKEN` | Text | Unset | The bearer token sent to the scanner. Required with `UPLOAD_SCANNER_URL`. |
| `EXPORT_MAX_DOWNLOAD_BYTES` | Bytes | `2147483648` (2 GiB) | The largest export Initiative hands back as a download. A larger one goes to `EXPORT_DESTINATION_DIR`. |
| `EXPORT_DESTINATION_DIR` | An absolute directory Initiative can write to | Unset | Where an export over that size is written, as `<dir>/guild_<id>/<file>`, with the path shown to the community's admins. Initiative never serves or deletes these, so collect them yourself. Unset, an export over the size is refused. |
| `EXPORT_PRESIGNED_DOWNLOADS` | `true` or `false` | `false` | With S3 storage, send a finished export's download straight from the bucket, through a link that lasts 5 minutes. Your bucket's CORS rules must allow `APP_URL`'s origin first. It does nothing with local storage or encrypted files. |

## The Initiative registry and plug-ins

Nothing to set. Your server follows the Initiative registry from its first start, and plug-ins are set up under **Settings → Platform → Integrations**. **Follow the registry**, on the same tab, stops the updates. See [Running plug-ins](plugins.md).

??? techspec "Mirrors, other registries, signing keys, and plug-ins from a file"
    Leave all of these unset unless you have the particular reason each one is for.

    | Variable | Accepted values | Default | What it's for |
    |---|---|---|---|
    | `MARKETPLACE_REGISTRY_URL` | A URL ending in `/` | `https://beyonders-studio.github.io/initiative-developer/public/` | A mirror, for a network that can't reach the registry. Initiative reads `metadata/` and `targets/` under it, and checks everything against the signing key built into the image. A server with no internet at all uploads a [registry bundle](plugins.md#the-initiative-registry). |
    | `MARKETPLACE_REGISTRY_TOKEN` | Text | Unset | A bearer token for a mirror that asks for one, sent only to that URL's origin. |
    | `MARKETPLACE_REGISTRY_TTL_SECONDS` | Seconds, 60 or more | `900` | How often the server asks for updates. |
    | `MARKETPLACE_REGISTRY_ROOT` | A file path | Unset | A different trusted root, so the server follows a registry somebody else signs. Its listings arrive as usual; a package's entitlement terms count only under the built-in root. |
    | `MARKETPLACE_EXTRA_CATALOG_DIR` | A directory | Unset | Listing files this server publishes as its own. See [Publishing your own listings](publishing-listings.md). |
    | `PLUGIN_SERVICES_CONFIG` | A file path | Unset | A JSON file of plug-in services set up at every start, in place of the form. See [Setting it up from a file](plugins.md#setting-it-up-from-a-file). |
    | `PLUGIN_PLATFORM_SIGNING_PRIVATE_KEY_PEM` | An Ed25519 private key, as PEM | Generated | The key Initiative signs what it sends plug-ins with. Unset, Initiative makes one on its first start and keeps it in the database, encrypted under `SECRET_KEY`, so every copy signs alike. Set it to bring your own (`openssl genpkey -algorithm ed25519 -out plugin-platform.pem`); changing it rotates the key. Any other kind of key is refused when it's used. |
    | `PLUGIN_PLATFORM_SIGNING_KEY_ID` | Text | The key's RFC 7638 thumbprint | The key id on what that key signs, so a plug-in picks it from the published key set during a rotation. |
    | `EXPRESSION_WORKERS` | 1 to 16 | `2` | Helper processes each server process may run for the plug-ins Initiative evaluates itself. They start on first use and leave after 5 idle minutes, and work beyond this many waits for one to come free. |

## AI assistant access (MCP)

| Variable | Accepted values | Default | What it does |
|---|---|---|---|
| `ENABLE_MCP` | `true` or `false` | `false` | Serve an MCP server at `<APP_URL>/api/v1/mcp/`, so AI assistants can work on somebody's behalf with their personal API key, reaching nothing that person can't. |

Leave it off unless you want that. [API keys & integrations](../account/api-keys-and-integrations.md) has how people connect.

## Logs and metrics

| Variable | Accepted values | Default | What it does |
|---|---|---|---|
| `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` | `INFO` | How much the application writes to standard error. The audit stream ignores it. |
| `METRICS_TOKEN` | Text; `openssl rand -hex 32` makes one | Unset | The bearer token Prometheus presents at `/api/v1/metrics`. Unset or blank, that route answers 404. |
| `FARO_COLLECTOR_URL` | A path starting with `/`, or an `http://` or `https://` URL | Unset | Where browsers that agreed to analytics send page views, errors and Web Vitals. Anything else stops the start. |

[Logs](#logs), [Monitoring with Prometheus](#monitoring-with-prometheus) and [Measuring the app in the browser](#measuring-the-app-in-the-browser) have what each one produces.

## Read on the first start only

These fill in a setting the first time the server starts, so a deployment tool can bring it up configured. After that the setting belongs to the app, and changing the variable does nothing.

| Variables | Fills in | Default |
|---|---|---|
| `ENABLE_PUBLIC_REGISTRATION` | **Let anyone sign up** | `true` |
| `DISABLE_GUILD_CREATION` | **Let anyone create a community**, the other way round | `false` |
| `GUILD_CREATION_DAILY_LIMIT` | **Communities one account may create per day**, 0 or more | `5` |
| `HIBP_CHECK_ENABLED` | **Check new passwords against known breaches** | `true` |
| `EXPORT_GUILD_COOLDOWN_HOURS` | **Hours between community exports** | `48` |
| `AUTH_LOGIN_METHODS` | **Ways in**: any of `password`, `sso`, `passkey`, `totp`, `email_otp` | `password`, `sso`, `totp`, `passkey` |
| `OIDC_ENABLED`, `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_PROVIDER_NAME`, `OIDC_SCOPES` | The server's own [sign-in provider](single-sign-on.md), when the issuer and client id are both set and no provider exists yet | `OIDC_ENABLED=false`, `OIDC_SCOPES=openid profile email offline_access` |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURE`, `SMTP_REJECT_UNAUTHORIZED`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_ADDRESS`, `SMTP_TEST_RECIPIENT` | [Email](email.md) | `SMTP_PORT=587`, `SMTP_SECURE=false`, `SMTP_REJECT_UNAUTHORIZED=true` |
| `FCM_ENABLED`, `FCM_PROJECT_ID`, `FCM_APPLICATION_ID`, `FCM_API_KEY`, `FCM_SENDER_ID`, `FCM_SERVICE_ACCOUNT_JSON` | [Push notifications](push-notifications.md) | `FCM_ENABLED=false` |
| `CAPTCHA_PROVIDER`, `CAPTCHA_SITE_KEY`, `CAPTCHA_SECRET_KEY` | The [captcha](#keeping-bots-out-captcha), with provider `hcaptcha`, `turnstile` or `recaptcha` | Unset |
| `STORAGE_BACKEND`, `S3_BUCKET`, `S3_REGION`, `S3_ENDPOINT_URL`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_USE_PATH_STYLE`, `S3_LOCAL_FALLBACK` | [Storage](object-storage.md), with backend `local` or `s3` | `STORAGE_BACKEND=local`, `S3_REGION=us-east-1`, and the rest unset or `false` |

`AUTH_LOGIN_METHODS` drops a value it doesn't know, leaves `email_otp` off while `SMTP_HOST` and `SMTP_FROM_ADDRESS` aren't both set, and keeps the default when what's left can't start a session. The log says which. `OIDC_SCOPES` left blank asks for the default, and a value naming no scope asks for `openid profile email`.

The first-owner pair is read at every start:

| Variables | What they do |
|---|---|
| `FIRST_OWNER_EMAIL`, `FIRST_OWNER_PASSWORD` | With both set, a start that finds no account at that address creates one there as the owner, with the address verified and a community of its own. The password skips the usual password checks, so make it a strong one, and remove both once the account exists. Unset, the first person to register becomes the owner. |

## Maintenance switches

| Variable | Accepted values | Default | What it does |
|---|---|---|---|
| `FORCE_GUILD_BACKFILL` | `true` or `false` | `false` | Every start brings each community's tables, database roles, grants and policies up to date where they've fallen behind. `true` re-applies every part to every community, which makes each start take longer. Set it for one start when a community's roles or grants have gone missing, then remove it. |

## Settings to leave unset

These exist for Initiative's own development and its test suite. Leave them unset on your server.

| Variables | What they're for |
|---|---|
| `GUILD_ROLE_PREFIX`, `PLATFORM_ROLE_PREFIX` | Keeping the test suite's database roles apart from a development database's on one PostgreSQL. Empty, or letters, digits and `_` not starting with a digit. |
| `WEBHOOK_ALLOW_PRIVATE_TARGETS` | Letting outgoing webhooks reach `http://` and private addresses on a developer's machine |

## Settings in the app

The [owner](platform-roles.md) changes these under **Settings → Platform**. Each takes effect when saved, with no restart.

| Tab | What's there | Covered on |
|---|---|---|
| **Authentication** | Ways in, and sign-in providers | [Single sign-on](single-sign-on.md) |
| **Security** | Session length, breached passwords, two-factor authentication, the captcha, what notifications carry | This page |
| **Branding** | Accent colors for light and dark mode, and **Ask arriving visitors about cookies** | [Measuring the app in the browser](#measuring-the-app-in-the-browser), for the cookie chooser |
| **Email** | The SMTP server | [Email](email.md) |
| **Push notifications** | Notifications on phones and the desktop app | [Push notifications](push-notifications.md) |
| **Community** | Sign-up, the directory, age, direct messages, guests, engagement ranking, exports, and how long deleted things are kept | This page |
| **Integrations** | AI, plug-in services and the marketplace registry | [Running plug-ins](plugins.md) and [AI features](../account/ai-features.md) |
| **Storage** | Local disk or S3 | [Object storage](object-storage.md) |
| **Intake** | Where security, moderation, support and feedback work lands | [Platform roles](platform-roles.md) |

### Who can sign up

Under **Community**, in **Who may join and create**:

| Setting | Starts as | What it does |
|---|---|---|
| **Let anyone sign up** | On | People make an account without an invite. Off, only invited people can. |
| **Let anyone create a community** | On | Off, only people who manage communities (operators and owners) can create one, and sign-up closes to invited people as well. |
| **Communities one account may create per day** | 5 | `0` is no limit. People who manage communities aren't counted. |

The first account on a new server can always register, whatever these say, and becomes the owner.

### The community directory

**Run a community directory**, under **Community**, starts off. On, communities can list themselves in a directory anyone signed in can browse, people ask to join without an invite, and **Join a community** appears beside their own communities. Each community lists itself from its own settings; see [Communities](../guides/communities.md).

Turning it off closes the directory without un-listing anyone, so switching it back on brings the same communities back.

### Asking members their age

**Check members' age**, under **Community**, starts on. While it's on:

- Sign-up asks for a date of birth, and turns away anyone under the minimum age for an account where they are. That's 13 in most countries and up to 16 in some. Initiative learns the country from `CLIENT_COUNTRY_HEADER`, and without it applies 16 to everyone.
- Joining a listed community from the directory and opening direct messages need the person to be 16 or older. A plug-in with a minimum age checks its own.
- Communities people are invited into never ask.

The date of birth is kept encrypted, so a plug-in's minimum age, which can differ by country, can be checked against it. An answer under 16 sticks, and the person isn't asked again. The usual cause is a mistyped year, and support staff and above can reset it from the [operator dashboard](platform-roles.md#managing-platform-users).

Turning it off asks you to confirm **Everyone here is 18 or older**, because nobody is asked their age again and plug-ins with a minimum age open for everyone. Do that only where you know every account belongs to an adult.

### Direct messages

| Setting | Starts as | What it does |
|---|---|---|
| **Let people message each other** | On | Turns on **My Messages**, with the connections and requests behind it. Messages are end-to-end encrypted, so nobody running the server can read them. Off hides **My Messages** and refuses new ones, and deletes nothing: switch it back on and conversations and connections are where they were. |
| **Direct messages for new accounts** | **Private** | The policy each new account starts on: **Private** (nobody can ask), **My communities** or **Anyone**. It's read once, when an account is made, so changing it opens and closes no existing account. |

People change their own policy afterwards; see [Messages](../guides/messages.md).

### Guests

**Allow guests**, under **Community**, starts off. Beside it, **Longest a guest may stay (days)** caps every guest's stay on the server, 90 to start with. A community can set a shorter cap for itself, never a longer one.

Switching guests off shuts every guest out at once and removes nobody. Switch it back on and they're in again until their time ends. See [Guests](../sharing/guests.md).

### Ranking search by engagement

**Let communities rank results by engagement**, under **Community**, starts on. Search lifts what more members recently opened or worked on, using a coarse level per item that an hourly pass works out and that names nobody. Off, no community ranks by engagement whatever it chose, and the next hourly pass deletes every level. A community with its own security standard can turn it off for itself too. [Data & compliance](../security/data-and-compliance.md) has what's kept, for your privacy policy.

### How long deleted things are kept

Deleting an account or a community hides it at once and erases it later. How much later is yours, under **Community**:

| Setting | Starts as | What happens during it |
|---|---|---|
| **Keep accounts for (days)** | 30 | The account is gone as far as everyone else can tell. If its holder signs back in, the deletion is called off, with their communities, roles and files where they left them. An operator can restore it too. |
| **Keep communities for (days)** | 90 | The community is gone for its members. An operator can restore it from **Operator dashboard › Communities**, choosing what it comes back as and, where nobody is left who could run it, who takes it over. |
| **Delete after (days on hold)** | 30 | A community [on hold](platform-roles.md#a-communitys-status) is closed to everyone in it. If the hold is still there when this runs out, the community is deleted and **Keep communities for** starts. The people who run it are told the date when it goes on hold. |

Each takes 1 to 3650 days. Leave one blank and nothing happens on that timer, which is the right answer for a deployment that has to keep records rather than shed them. Each window counts from the moment the thing was deleted or put on hold, so changing a number moves the date for everything already waiting. A pass runs once an hour and acts on whatever has run out.

When a community's window ends, its plug-ins are asked to erase what they hold about it, and the community is destroyed once each has answered. A plug-in that doesn't answer is asked again for about four days and then given up on. From the moment they're asked, the community can't be restored or have its status changed.

A restored community reconnects its installed plug-ins itself, the way it connected them the first time.

### How often a community can export everything

A whole-community export reads every last thing the community holds, so each community waits between them. **Hours between community exports**, under **Community**, starts at 48, and `0` is no wait. The wait counts from the community's last export, so changing it moves the next date for everyone already waiting.

### How long people stay signed in

Two separate clocks end a session, and it's worth keeping them apart. Under **Security**, in **How long people stay signed in**:

| Setting | Starts as | What it does |
|---|---|---|
| **Hours** | No limit | The longest anybody goes before signing in again, however much they use the app. Nothing pushes it forward. |
| **Idle minutes** | No limit, which leaves `AUTH_REFRESH_TTL_DAYS`: 30 days in a browser, 90 in the apps | How long a session may sit unused before it ends. Using the app resets it, so it only runs down once somebody has stopped. |

Both take a whole number, 1 or more.

!!! warning "Set Hours longer than the inactivity window"
    Shorter, **Hours** becomes the only thing that ends a session, and everybody is signed out on a timer whether they're using the app or not. That's occasionally what somebody wants, and rarely what they meant.

A browser session that's already open keeps the terms it started under and picks up a new **Hours** at its next sign-in. The phone and desktop apps are brought under a shorter **Hours** straight away, measured from their last sign-in, so shortening it can sign an app out at once. Lengthening or clearing it signs nobody out. **Idle minutes** applies to each session from its next renewal.

A community you've given **Its own security standard** in **Operator dashboard › Communities** can hold its members to 12-hour sessions and 15 idle minutes. Its members then get the stricter of that and your numbers, and belonging to two such communities comes to 12 hours, not 6. See [Community security](../security/community-security.md).

### Requiring two-factor authentication

Under **Security**, the first **Two-factor authentication** section says which second factors the server offers. The second says who has to hold one:

| Choice | Who has to |
|---|---|
| **Nobody has to** (the default) | Nobody. Anybody can set one up, and a community can ask its own members for one. |
| **People with a platform role** | Support, moderators, operators and owners: everybody whose reach is the whole server |
| **Everybody** | Every account. Communities stop being offered the question, because it's answered for their members. |

An authenticator app or a passkey both count, and so does a sign-in through a provider listed under **Providers whose sign-in counts**, because that provider runs a second factor of its own.

Nobody is signed out. The next time somebody this covers makes a request, they're asked to set one up, and carry on once they have. The page says how many people don't have one yet before you save.

!!! warning "Personal API keys and the phone app stop first"
    Neither can type in a code, so for anybody this covers they stop working until that person sets up a factor, and work again the moment they do. Turn it on for everybody and expect a scripted integration or two to go quiet until its owner spends a minute on their Security page.

The page refuses two things. You can't require a factor before you hold one yourself, and you can't require one while the server offers neither the authenticator app nor passkeys. Withdrawing the last of those two from **Ways in** is refused while a requirement stands, so lower the requirement first.

### Keeping bots out (captcha)

The captcha checks that somebody signing up, or asking for an emailed sign-in code, is a person. Under **Security**, in **Captcha**:

| Field | What it's for |
|---|---|
| **Provider** | **hCaptcha**, **Cloudflare Turnstile** or **Google reCAPTCHA v2**. **None** turns it off. |
| **Site key** | The public key that shows the widget |
| **Secret key** | The key the server checks answers with. Leave it blank when editing to keep the saved one. |

It comes on once all three are saved, and the section's badge says whether it's on. The first account on a new server is never asked. The browser loads the widget from the provider, whose addresses join the page's content security policy only while that provider is chosen.

### Checking passwords against known breaches

**Check new passwords against known breaches**, under **Security**, starts on. A new password, at sign-up or when it's reset or changed, that appears in the Have I Been Pwned breach list is refused. Only the first 5 characters of the password's SHA-1 hash leave the server, never the password.

If the check gets no answer within 2 seconds, the password is accepted and the log says why. So a server that can't reach the internet loses nothing but the wait, and switching the check off saves it. Every password needs at least 12 characters either way.

### What notifications may carry

Under **Security**, in **Notifications that leave the app**:

| Switch | Off, or on for the last one |
|---|---|
| **Phone and desktop notifications** | Nothing is sent to a phone or the desktop app, and the server stores no device registrations and declines new ones. Devices register again when you switch it back on. |
| **Email notifications** | No notification email is written, on any schedule anybody chose. |
| **Hide notification details** | On, a push or an email names the kind of thing that happened, such as "You were mentioned in a comment", and the app shows the rest. |

All three start open: notifications go out, and they say what they're about.

Every community is held to these as a ceiling. A community's own Security tab asks the same three questions, and the stricter answer wins, so a community can be quieter than your server and never louder. See [Community security](../security/community-security.md).

!!! note "Account mail always goes"
    Sign-in codes, address confirmations, password resets and the notices an account gets about itself go out whatever these say, so switching notification email off never locks somebody out of their own account.

## Logs

Two streams come out of Initiative, for two different readers. They get written whether anybody reads them or not, like the minutes of an HOA meeting.

| Stream | What's on it | `LOG_LEVEL` applies |
|---|---|---|
| Standard error | The application talking: what it checked at start-up, what it repaired, every request it answered, anything it thinks you should know | Yes |
| Standard output | The record of who did what: one line per recorded action, and nothing else | No |

Both are one JSON object per line, so a log platform reads fields rather than squinting at text. Whatever already collects your containers' output collects both.

Docker keeps a container's output in a file that grows until you say how much to keep. The example compose file keeps the last 50 MB per container, in five 10 MB files. Treat that as a buffer: if the record on standard output matters to you, ship it somewhere durable and let the buffer cover the stretch when the shipper is down.

### Standard error

`LOG_LEVEL` sets how much: `INFO` unless you say otherwise, `WARNING` to hear only about trouble, `DEBUG` when you're chasing something and want all of it.

| Field | What it holds |
|---|---|
| `ts` | When, in UTC, to the millisecond |
| `level` | `DEBUG`, `INFO`, `WARNING`, `ERROR` or `CRITICAL` |
| `logger` | The part of the application that wrote it |
| `stream` | `app` |
| `service` | `initiative` |
| `msg` | The message |
| `request_id`, `user_id`, `guild_id`, `route` | Which request it belongs to, whose account, which community and which route, where there is one |
| `exc` | An error's `type`, `message` and whole `traceback` |

A request's own line names the route, never the address. A request for task 3 in community 7 is logged as `GET /api/v1/c/{community_id}/tasks/{task_id} 200`, with the community in a field of its own and the query string left off, so whatever somebody typed into a search box stays out of the log. A request that crashes gets one line with its traceback, under the same request id as everything else it wrote.

Database, mail and validation errors are written as their codes (`sqlstate=23505 constraint=…`), never the values they were handed, and database statements are logged without their parameters. Each call to a webhook or a plug-in gets one line naming the target's origin, the answer and how long it took: `INFO` when it failed, `DEBUG` when it worked.

### Standard output

Every line is one recorded action:

| Field | What it holds |
|---|---|
| `stream` | `audit`, so a collector can route these lines and nothing else |
| `service` | `initiative` |
| `schema_version`, `event_uuid` | The line's format version, and an id unique to this line |
| `event_type`, `category`, `tier`, `is_write` | What happened, and how it's classed |
| `occurred_at` | When |
| `actor_user_id`, `target_user_id` | Who did it, and to whom. People appear as account ids, never names. |
| `guild_id` | The community, on every line about one |
| `target` | The thing it was done to, as a `type` and an `id` |
| `context` | The `request_id`, and on lines about signing in or arriving through a grant, the network address and what the browser or app called itself |
| `detail` | Numbers, switches and choices about the action. Free text is named, never copied. |

A filter on `event_type` makes an alert. `LOG_LEVEL` has no say over any of it.

Somebody reaching a community they don't belong to does it through a grant, for support or break-glass access, and while a grant is live every request made under it is a line of its own: the route, the method, the answer and which grant allowed it. Live editing isn't a request, so the first change somebody makes to a document or wiki page under a grant gets a line naming which one. See [Platform roles](platform-roles.md).

### Following one request

Every request gets an id, sent back in its `X-Request-Id` header. With `BEHIND_PROXY=true`, an id your proxy already put in `X-Request-Id` is kept, so one request has one name in your proxy's log, the application log and the record alike. Background work is named the same way, with an id that starts `job-`, so one pass of a sweep reads as one story.

## Monitoring with Prometheus

If Prometheus and Grafana already keep an eye on the rest of the house (the NAS, the router, the thermostat nobody is allowed to touch), Initiative can join them. Set `METRICS_TOKEN` and point a scrape at `/api/v1/metrics`:

```yaml
scrape_configs:
  - job_name: initiative
    metrics_path: /api/v1/metrics
    authorization:
      credentials_file: /etc/prometheus/initiative-token  # holds the METRICS_TOKEN value
    static_configs:
      - targets: ["initiative.lan:8173"]
```

Point `targets` at the app's own port, or at your proxy with `scheme: https` added. A scrape presenting the token as a bearer token gets the numbers, anything else is turned away, and with no token set the route answers 404.

No label ever names a community or a person.

| Metric | Type | What it tells you |
|---|---|---|
| `initiative_http_requests_total` | Counter | Requests answered, by `method`, `route` and `status`. `route` is the pattern, such as `/api/v1/c/{community_id}/initiatives/`, so every community shares one series. A request no route matched is `unmatched`. |
| `initiative_http_request_duration_seconds` | Histogram | How long those took, by `method` and `route` |
| `initiative_http_requests_in_progress` | Gauge | Requests being answered right now, by `method` |
| `initiative_websocket_connections` | Gauge | Live connections for notifications, live editing and counters. One open tab holds several. |
| `initiative_db_statement_duration_seconds` | Histogram | How long database statements took, by `engine` |
| `initiative_db_slow_statements_total` | Counter | Statements over 0.5 seconds, by `engine` |
| `initiative_db_pool_connections` | Gauge | Connections each engine's pool holds, by `engine` and `state`: `checked_out`, `idle` or `overflow` |
| `initiative_db_connection_communities` | Histogram | Communities a pooled connection served before it closed, by `cohort`. Only with `DB_COHORTS` above 1. |
| `initiative_db_cross_cohort_routes_total` | Counter | Times a connection served a community outside its group, by `cohort` |
| `initiative_sweep_pass_duration_seconds` | Histogram | How long a background pass over the communities took, by `pass` |
| `initiative_sweep_timer_lag_seconds` | Histogram | How late a scheduled sweep was picked up, by `sweep` |
| `initiative_sweep_timer_repairs_total` | Counter | Sweep timers the daily check had to set because nothing else had, by `sweep` |
| `initiative_plugin_hook_deliveries_total` | Counter | Webhooks arriving for plug-ins, by `outcome`: `refused`, `unroutable`, `delivered` or `failed` |
| `initiative_users`, `initiative_guilds` | Gauge | Accounts and communities, by `status` |
| `initiative_sessions_active` | Gauge | Sign-ins that haven't expired or been signed out |
| `initiative_active_users` | Gauge | Accounts that did something in the last day, week and month, by `window`: `1d`, `7d` or `30d` |
| `initiative_tools_created_total` | Counter | Tools created, by `tool` (`project`, `file`, `wiki`, …), imports and copies included |
| `initiative_page_views_total` | Counter | Pages opened in the app, by `route`, the page's pattern (`/c/$communityId/i/$initiativeId/projects/$projectId/`). Counted only while `METRICS_TOKEN` is set. Nothing is kept in the browser and nothing says whose visit it was. |
| `initiative_build_info` | Info | The version running, in its `version` label |
| `process_*`, `python_*` | | Memory, CPU and garbage collection for the process |

`engine` is `request` (people's requests), `system` (background work and start-up), `provisioning` (setting up a community's tables, never counted as slow) or `query` (SQL people write in dashboard widgets). With `DB_COHORTS` above 1, each group's pools report as `request/0`, `system/0`, `query/0` and so on.

Every series is per process. With several copies running, Prometheus scrapes each one: add request and statement series with `sum`, and take `initiative_users`, `initiative_guilds` and `initiative_sessions_active` with `max`, since every copy counts the same accounts.

**A dashboard to start from.** Download the [starter Grafana dashboard](assets/initiative-grafana-dashboard.json) and import it under **Dashboards → New → Import**, choosing your Prometheus data source. It opens with the headline counts, then traffic, errors, response times, the database and the process.

**Slow statements land in the log too.** Each statement over 0.5 seconds writes a warning to standard error with its engine, how long it took, the request id, and the first 2,000 characters of its SQL, as written and without the values in it. SQL somebody wrote in a dashboard widget is logged without its text.

## Health checks

Both answer without signing in and never count against a rate limit.

| Route | Asks | Answers |
|---|---|---|
| `/api/v1/healthz` | Is this process running? It touches nothing outside the process. | `200` with `{"status": "ok"}` |
| `/api/v1/readyz` | Can this process serve a request now? | `200` with `"status": "ok"`, or `"degraded"` when something optional failed. `503` with `"unavailable"` when a database check failed. |

`/readyz` lists each check under `checks`, as `ok` or `error`. The three database connections (`database`, `database_system`, `database_provisioning`) decide the answer. `storage`, `notify_bus` and `rate_limit_store`, plus `database_query` when `DATABASE_URL_QUERY` is set, are reported without failing it: each of those is usually down for every copy at once, and taking every copy out of rotation over one would turn a partial outage into a total one. Each check gets 3 seconds, and one answer is reused for 5 seconds however often it's asked.

Use `/healthz` for a liveness probe, which restarts a process that fails it, and `/readyz` for a readiness probe, which only takes the process out of rotation.

## Measuring the app in the browser

Prometheus sees the server. To see what happens in people's browsers (which pages they actually open, as opposed to the ones you spent a weekend on, plus the errors they hit and how fast pages load), point `FARO_COLLECTOR_URL` at a Grafana Faro collector, such as Alloy's `faro.receiver`. It takes a path on this server that your proxy passes to the collector, such as `/collect`, or a full `https://` address.

**Nobody is measured without saying yes.** Setting it adds an **Analytics** switch to the cookie chooser, and only a browser with that switch on sends anything. Every switch starts off, and the chooser itself appears only once the owner turns on **Ask arriving visitors about cookies** under **Settings → Platform → Branding**. With the chooser off, nothing optional is ever switched on, so nothing is sent.

**What gets sent.** Page views, uncaught errors and Web Vitals, grouped by a random session id the browser keeps. A page is named by its pattern (`/c/$communityId/projects/$projectId`), never its address, and nothing names the person.

A full address on another origin is added to the page's content security policy (`connect-src`) for you. A path needs nothing, since it's the app's own origin.
