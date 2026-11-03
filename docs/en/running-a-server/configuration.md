---
icon: lucide/sliders-horizontal
---

# Configuration

Initiative is configured with **environment variables**, set in your `docker-compose.yml`, a `.env` file, or your container environment. This page covers what you're most likely to touch, and `backend/.env.example` in the source lists the rest.

!!! tip "Some things are configured in the app, not here"
    Email, single sign-on, branding colors and AI are all set up from **Settings → Platform** in the running app, by the [owner](platform-roles.md) — friendlier than environment variables, and covered on their own pages. Environment variables are for the foundational settings below.

## Essential settings

| Variable | What it does | Default |
|---|---|---|
| `SECRET_KEY` | Signs sessions **and** encrypts sensitive stored data. Set a strong, unique value and keep it safe. | *required* |
| `DATABASE_URL` | The database, connecting as its owner. Initiative sets up its own logins from it. | *required* |
| `APP_URL` | Your public base URL. Needed for single-sign-on callbacks and correct links. Passkeys are bound to its host: change the host and every passkey registered stops answering, so people sign in another way and add new ones. | — |

See [Installation](installation.md#the-database-connection) for what it's used for, and for naming the logins yourself.

## Who can sign up

Under **Settings → Platform → Community**, in **Who may join and create**:

| Setting | What it does | Starts as |
|---|---|---|
| **Let anyone sign up** | People make an account without an invite. Off, only invited people can. | On |
| **Let anyone create a community** | Off, only the people who manage communities on this server can make one — and sign-up closes to invited people too. | On |
| **Communities one account may create per day** | `0` means no limit. People who manage communities aren't counted. | 5 |

Between them, you can run anything from a wide-open public server to a locked-down, invite-only, one-organization deployment. Nothing needs a restart.

??? techspec "Pre-filling from environment variables"
    The first time a server starts with these settings, `ENABLE_PUBLIC_REGISTRATION`, `DISABLE_GUILD_CREATION`, `GUILD_CREATION_DAILY_LIMIT`, `HIBP_CHECK_ENABLED` and `EXPORT_GUILD_COOLDOWN_HOURS` fill them in. After that the settings pages own them and the variables are ignored.

### The community directory

Communities can also list themselves publicly, so people find and join them without an invite. That whole feature is **off** until you turn it on, from **Settings → Platform → Community** as the [owner](platform-roles.md).

While it's off there is nothing to browse, nobody can join a community without an invite, and the listing control doesn't appear in community settings at all. Turning it off again later hides the directory rather than un-listing anyone: switch it back on and the same communities are there.

Listing is then each community admin's own decision: they pick the community's categories and certify that it holds no adult or illegal content. Initiative refuses to list a community with room for only a single member. See [Listing your community](../guides/communities.md#listing-your-community-admins).

### Asking members their age

Because a listed community is open to people its members haven't met, Initiative asks anyone joining one from the directory to confirm they're **16 or older**, once. Every account is asked its date of birth once, and it is kept encrypted at rest so a plug-in's minimum age — which can differ by country — can be checked against it. Set `CLIENT_COUNTRY_HEADER` to the header your proxy writes the visitor's country into (`CF-IPCountry` behind Cloudflare) so those limits apply by country; unset, a plug-in's highest minimum age applies to everyone. Only set it when every request reaches the server through that proxy. See [Finding a community to join](../guides/communities.md#finding-a-community-to-join).

**The rule belongs to the community, not to the way in.** Every route into a listed community is covered: the directory, an invite, and the group rules your identity provider drives. A community that hasn't listed itself asks nobody, whoever brings them in, and an unanswered question never costs somebody a membership they already have or holds up the rest of Initiative.

Where nobody is at a keyboard to be asked — a group sync, say — what counts is the answer already on the account. Someone who has never been asked is let in; someone who answered under the minimum is not. The listed community then puts the question at its own door the first time they open it, which is the moment there is finally somebody there to answer. Until they do, that community is the only thing closed to them.

A community that has been private until now collected its members under no such rule, so **listing it is refused while it holds anybody who has answered under the minimum**. That check runs on the way onto the shelf only: once listed, an ordinary edit is never failed over a member's answer.

The question sits under the same **Settings → Platform → Community** tab, as **Ask members to confirm they are 16 or older**, and is on by default. Turn it off only on a deployment where you already know every account belongs to an adult — Initiative asks you to confirm that, because nobody is asked again afterwards, including people who join a listed community later.

Someone who answers "not old enough yet" keeps that answer, so the question isn't asked until it comes out right. The usual cause is a mistyped year; support staff and above can reset it from the [operator dashboard](platform-roles.md#managing-platform-users).

### What new accounts can be reached at

Direct messages are off by default: every account is created on the **Private** policy, meaning nobody can even ask to message them until the person opens it up. The starting policy sits under the same **Settings → Platform → Community** tab.

It's read **once**, when an account is made. Changing it opens no existing account and closes none either — people who already have a setting keep it. See [Who can reach you](../guides/messages.md#who-can-reach-you).

### Guests

[Guests](../sharing/guests.md) are off until you switch on **Allow guests**, under the same **Settings → Platform → Community** tab. Beside it, **Longest a guest may stay (days)** caps every stay on the server, 90 days to start with. A community can set a shorter cap for itself, never a longer one.

Switching guests off shuts every guest out at once and removes nobody: switch it back on and they're in again until their time ends.

### Ranking search by engagement

Search puts what more members have recently opened or worked on a little higher, from a rough level per item that the server works out once an hour. It's on unless you switch off **Let communities rank results by engagement**, under the same **Settings → Platform → Community** tab. Off, no community ranks by engagement whatever it chose, and every level is deleted within the hour.

A community holding its own security standard can turn it off for itself as well. If your privacy policy needs to describe it, [Data & compliance](../security/data-and-compliance.md#what-initiative-keeps-about-use) has what is kept and for how long.

### How long people stay signed in

Two different things, and it's worth keeping them apart.

A session ends on its own when nobody uses it — that's the inactivity window, and it slides forward every time somebody uses the app. It's thirty days in a browser and ninety in the phone and desktop apps, so somebody who uses Initiative every day never reaches it.

The other one is the **absolute** limit: the longest anybody may go before signing in again, no matter how much they use it. Nothing slides it. It's blank by default, meaning there isn't one — a server you run for a club is not answering to an auditor — and it lives in **Settings → Platform → Security**, in hours.

!!! warning "Set it longer than the inactivity window"
    Set it shorter and it becomes the *only* thing ending a session: the inactivity window can never be reached first, so everybody gets signed out on a timer whether they're using the app or not. That may be exactly what you want. It's just rarely what somebody means to do.

Sessions already open keep the terms they were opened under and pick up the new one next time those people sign in.

!!! warning "The app on a phone is different"
    A phone holds a longer-lived credential, and the new limit is written into the ones already issued — measured from when that person last signed in. So somebody whose phone signed in three days ago, on a deployment that has just set twelve hours, is signed out at once and asked for their password again. Shortening the number, or turning on a community's twelve-hour switch, can therefore sign phones out immediately. Lengthening the number, or clearing it, signs nobody out — and a phone that is still signed in goes back to the longer window from its next renewal. A phone that was already signed out stays signed out: it has to sign in again, which is the point.

**A community can hold itself to a stricter one.** Where you've [let a community configure its own sign-in](single-sign-on.md#letting-a-community-use-a-provider), the switch is theirs rather than yours: under that community's own **Settings → Security**, and it's twelve hours — the figure HIPAA and NIST both land on. Its members then sign in again on that schedule whatever your own number says, and being in two such communities is still twelve hours, not six.

### Requiring two-factor authentication

By default nobody has to have [two-factor authentication](../account/two-factor-authentication.md) — anybody can set it up, and nobody is nagged. **Settings → Platform → Security** lets you change that, in two sizes:

| Who you ask | What it means |
|---|---|
| **People with a platform role** | Support, moderators, operators and owners. The people who can see across the whole server rather than just their own communities. |
| **Everybody** | Every account here. Communities stop being offered the question, because it's already answered for their members. |

Either one counts an authenticator app **or** a passkey — whichever somebody has, they're covered. So is somebody whose single sign-on did the second factor on the way in, even if they have nothing set up here.

Nobody is signed out. The next time somebody this covers opens the app they're asked to set one up, where they stand, and carry on once they have.

!!! warning "Personal API keys and the app on a phone stop first"
    Neither can type in a code, so for anybody this covers they stop working until that person sets a factor up — and start working again the moment they do. If you turn this on for everybody, expect a scripted integration or two to go quiet for as long as it takes its owner to spend a minute on their Security page.

    The page tells you how many people don't have a factor yet before you save, which is a reasonable proxy for how much of that you're about to cause.

Two things the page will stop you doing, both for the same reason: you can't require a factor while you haven't got one yourself, and you can't withdraw the authenticator app and passkeys from the [ways in](single-sign-on.md) while a requirement is standing. Lower the requirement first, then withdraw.

## What notifications may carry

**Settings → Platform → Security** asks three questions about everything that leaves the app:

| Switch | What changing it does |
|---|---|
| **Phone and desktop notifications** | Turn it off and nothing is sent to a phone or shown by the desktop app: this server stores no device registrations and declines new ones. Devices register again if you switch it back on. |
| **Email notifications** | Turn it off and no notification email is written, on any cadence anybody has chosen. |
| **Hide notification details** | Turn it **on** and a push or an email reads "You were mentioned in a comment", with the app the place to find out the rest. |

All three start open: notifications go out, and they say what they're about.

**Every community is held to these as a ceiling.** A community's own [Security tab](../security/community-security.md#what-notifications-carry) asks the same three questions for itself, and the stricter answer wins — so a community can be quieter than your server, never louder. Where you've switched something off, their switch says so and has nothing left to decide.

!!! note "Account mail is not a notification"
    Sign-in codes, address confirmations, password resets and the notices an account gets about itself go out whatever you set here. Switching notification email off must not be a way to lock somebody out of their own account.

## How long deleted things are kept

Deleting an account or a community hides it immediately and erases it later. How much later is yours, under **Settings → Platform → Community**:

| Window | Default | What happens during it |
|---|---|---|
| **Keep accounts for** | 30 days | The person has gone as far as everyone else is concerned. If they sign back in during the window, the deletion is called off entirely — communities, roles and files where they left them. You can also restore one. |
| **Keep communities for** | 90 days | It has vanished for its members. An operator can restore it from **Settings → Platform → Communities**, choosing what it comes back as and, where nobody is left who could run it, who takes it over. |
| **Delete after (days on hold)** | 30 days | The community sits [on hold](platform-roles.md#a-communitys-status). If nobody lifts the hold by the end of the window, it's deleted, and **Keep communities for** starts counting from there. Its superadmins get the date by email the moment it goes on hold. |

Leave any of them blank and **nothing happens on a timer** — the right answer for a deployment required to keep records rather than shed them. Each is counted from the moment each thing was deleted or put on hold, so changing the number moves the date for things already in the queue.

When a community's window ends, its plug-ins are asked to erase what they hold about it first, and it's destroyed once each has answered. A plug-in that doesn't answer is asked again for a few days and then given up on, so a purge can take up to about four days past the window. From the moment they're asked, the community can't be restored or have its status changed.

A restored community reconnects its installed plug-ins itself. It authorised those connections in the first place, so it authorises them again.

## How often a community can export everything

A whole-community export reads every last thing the community holds, so each community waits 48 hours between them. Change it with **Hours between community exports**, under **Settings → Platform → Community**. `0` means no wait. The wait is counted from the community's last export, so changing it moves the next date for everyone already waiting.

## Running behind a reverse proxy

For any real deployment you'll put Initiative behind a reverse proxy that handles HTTPS.

| Variable | What it does | Default |
|---|---|---|
| `BEHIND_PROXY` | Trust `X-Forwarded-*` headers from your proxy (so client IPs and HTTPS are detected correctly). | `false` |
| `FORWARDED_ALLOW_IPS` | Which proxy addresses or ranges to trust when `BEHIND_PROXY=true`, comma-separated. Only needed for a proxy that reaches the app over a public address. Setting it replaces the default, so list every proxy you trust. | This machine, its container networks and your LAN |

!!! warning "Only enable proxy trust behind an actual proxy"
    `BEHIND_PROXY` tells Initiative to believe the `X-Forwarded-*` headers it receives. Only turn it on when a trusted proxy is the one setting them.

    With it on, each visitor is recognised with nothing else to set when your proxy is on the same machine, in your compose file or on your LAN, behind a Cloudflare Tunnel, or behind Cloudflare's proxied DNS (the orange cloud) in front of your own Caddy or nginx.

    The one setup that needs more is a proxy on another machine that reaches Initiative over a public address. List it in `FORWARDED_ALLOW_IPS`; the log names the address to add when it sees one.

**Let 50 MB through per request.** A file of any size arrives in pieces of up to 50 MB, so that's the most your proxy ever has to pass in one go. nginx stops at 1 MB unless told otherwise, so add `client_max_body_size 50m;` to the server block. Caddy and Traefik pass it as they are.

## The app association files

A phone lets an app use a site's passkeys only when the site says, in a file at a fixed address, which apps may. Initiative serves both, built from the project's own app identities (they are the project's to vouch for, not something you configure):

| File | Read by | What it names |
|---|---|---|
| `/.well-known/assetlinks.json` | Android | The Initiative app's package and the fingerprint of the key it's signed with. |
| `/.well-known/apple-app-site-association` | iPhone | The Initiative iPhone app. It answers 404 until that app is published. |

They're served as JSON, at exactly those paths, with no redirect, and only when your address can carry a passkey at all (`https`, a host name rather than an IP address). Anything else under `/.well-known/` answers 404, never the app's page, because Apple and Google read an HTML page there as a broken file.

**If you self-host**, there's nothing to set. Android checks the file on whatever server the app points at, so the Android app signs in with passkeys on yours by itself. An iPhone only reads the file for addresses built into the app (the hosted service's `initiativetasks.com` and `demo.initiativetasks.com`), so on your server the iPhone app sends people to the browser for passkeys, which works for every server.

If your proxy answers anything under `/.well-known/` itself, as some do for certificates, pass `/.well-known/assetlinks.json` through to Initiative. Without it the Android app sends people to the browser for passkeys instead.

## Running more than one copy

Several copies of Initiative can serve one address. Here's what they share and what each keeps to itself.

| | Where it lives |
|---|---|
| Everything people save, including live edits | The database, so every copy sees it |
| Live editing sessions, cursors and who's here | Each copy, for the people connected to it |
| Rate-limit counts | Each copy, unless `RATE_LIMIT_STORAGE_URI` gives them one shared count (a `redis://` URL) |

People editing a document through the same copy see each other's typing as it happens. Through different copies, each one's changes reach the others within about half a minute, when their copy saves, and nobody's edits are lost: every save merges with what the other copies saved.

Each server process runs the document editor in a helper process of its own. It starts the first time somebody there opens a document to edit, uses about 90 MB while it runs, and stops after five idle minutes. A server where nobody edits a document never starts it. Budget for it per process when you size the container.

## Rate limits

Every limit counts against the **signed-in account**, not the network it's on, so an office full of people behind one address doesn't share an allowance or lock each other out. A request with no account behind it yet counts against the network address it came from.

A few count per **email address** typed in, whoever's typing it: sign-in codes and password-reset emails together come to five every fifteen minutes for one address, and so do wrong passwords. Loading the app's own pages and scripts counts against nothing.

| Variable | What it does | Default |
|---|---|---|
| `RATE_LIMIT_DEFAULT` | The limit for everything that doesn't set its own. Empty turns this default off; the limits individual routes set stay. | `100/minute` |
| `RATE_LIMIT_STORAGE_URI` | Where counts are kept. `memory://` counts in each process. A `redis://` (or `rediss://`, `redis+sentinel://`, `redis+cluster://`) URL gives every process one shared count. If it can't be reached, each process counts in its own memory until it answers again. | `memory://` |

## Keeping bots out (captcha)

To keep automated sign-ups out of open registration, ask for a captcha. It's set in **Settings → Platform → Security**, under **Captcha**, and applies to signing up and to asking for an emailed sign-in code.

| Field | What it's for |
|---|---|
| **Provider** | hCaptcha, Cloudflare Turnstile or Google reCAPTCHA v2. **None** turns the captcha off. |
| **Site key** | The public key that shows the widget. |
| **Secret key** | The server-side key that checks the answer. Write-only: leave it blank when editing and the saved one stays. |

The captcha switches on once all three are saved, and the section's badge says whether it's on. No restart.

??? techspec "Pre-filling from environment variables"
    On a fresh install's **first boot**, `CAPTCHA_PROVIDER`, `CAPTCHA_SITE_KEY` and `CAPTCHA_SECRET_KEY` fill these settings in. After that the settings page owns them and the variables are ignored.

## Checking passwords against known breaches

A new password that has already turned up in a data breach is turned away. Only the first five characters of the password's hash leave the server; the password never does. The switch is **Check new passwords against known breaches**, under **Settings → Platform → Security**, and it's on to begin with. Turn it off on a server that can't reach the internet.

## AI assistant access (MCP)

| Variable | What it does | Default |
|---|---|---|
| `ENABLE_MCP` | Expose the in-app MCP server (at `<APP_URL>/api/v1/mcp/`) so AI assistants can work with data on a user's behalf, bound by that user's API key and access rules. | `false` |

Leave it off unless you want that surface. See [API keys & integrations](../account/api-keys-and-integrations.md) for how users connect.

## The Initiative registry and plug-ins

Nothing to set. Your server follows the Initiative registry from the moment it starts, and the plug-ins your communities add are set up from **Settings → Platform → Integrations**. See [Running plug-ins](plugins.md).

??? techspec "Mirrors, other registries, and plug-ins from a file"
    Leave all of these unset unless you have the particular reason each one is for.

    | Variable | What it's for | Default |
    |---|---|---|
    | `MARKETPLACE_REGISTRY_URL` | A mirror of the Initiative registry, for a network that can't reach it directly. Everything from it is still checked against the key built into Initiative. A server with no internet access at all uploads a [registry bundle](plugins.md#the-initiative-registry) instead. | The Initiative registry |
    | `MARKETPLACE_REGISTRY_TOKEN` | A token for a mirror that asks for one. It is sent only to the registry's own address. | None |
    | `MARKETPLACE_REGISTRY_TTL_SECONDS` | How often the server checks for updates. At least 60. | `900` |
    | `MARKETPLACE_REGISTRY_ROOT` | A path to a different signing key. The server then trusts a registry somebody else signs, in place of the Initiative registry. | The key built into Initiative |
    | `PLUGIN_SERVICES_CONFIG` | A JSON file of plug-in services to set up at every start, in place of the form. See [Setting it up from a file](plugins.md#setting-it-up-from-a-file). | — |
    | `EXPRESSION_WORKERS` | How many small helper processes each server process may run for plug-ins Initiative runs itself. They start on first use, and an idle one leaves after five minutes. 1 to 16. | `2` |

## Your own marketplace listings

| Variable | What it does | Default |
|---|---|---|
| `MARKETPLACE_EXTRA_CATALOG_DIR` | A directory of listing files this server publishes as its own. Mount a folder there and its listings appear in your marketplace beside the built-in ones. Unset means no directory is read. | — |

See [Publishing your own listings](publishing-listings.md).

## File storage and push notifications

These have their own pages:

- **File storage** — keep uploads on local disk (default) or use S3-compatible object storage. See [Object storage](object-storage.md).
- **Mobile push** — connect Firebase Cloud Messaging from **Settings → Platform → Push notifications**. See [Push notifications](push-notifications.md).

## Mobile app version floor

`MIN_NATIVE_VERSION` (tracked in the source) records the minimum native mobile-app version the current web bundle needs. You rarely touch it by hand — it's part of how the mobile app updates safely over the air. Mentioned here only so it isn't a mystery if you spot it. See [Backups & updates](backups-and-updates.md).

## Logs

Two streams come out of the container, and they are for different readers.

**Standard error** is the application talking: what it checked at start-up, what it repaired, every request it answered, anything it thinks you should know. It is one JSON object per line, the web server's own lines included, so a log platform reads fields rather than squinting at text. `LOG_LEVEL` says how much. It's `INFO` unless you set it; `WARNING` if you would rather only hear about trouble; `DEBUG` when you are chasing something and want all of it. To turn up a single logger and leave the rest alone, start uvicorn with a `--log-config` file that sets that logger's level.

**The request line names the route, not the address.** A request for task 3 in community 7 is logged as `GET /api/v1/c/{community_id}/tasks/{task_id} 200`, with the community in a field of its own, and the query string is left off. Whatever somebody typed into a search box or pasted into a link stays out of the log. A request that crashes gets one line with its traceback, under the same request id as everything else it wrote.

**Standard output** is the audit stream: one JSON object per line, one line per recorded action — who did what, to which account or community, when — and nothing else on that stream. Every line carries `"stream": "audit"`, so a collector can route these and nothing else, and `"service": "initiative"`, so where the billing and automation services ship the same kind of line about the same community, a reader can tell whose it is. Whatever already ships your container's logs carries it, and a log platform reads it as records rather than text.

That is where the record is kept, searched and alerted on. A filter on `event_type` is an alert; `guild_id` is on every line about a community. `LOG_LEVEL` has no say over any of it.

**Every line says which request it came from.** An application line carries `request_id`, the account (`user_id`), the community (`guild_id`) and the `route`. An audit line carries the same id in its `context` block, and a line about somebody signing in, or reaching a community through a grant, adds the network address and what the browser or app called itself. Background work is named the same way, with an id that starts `job-`, so one pass of a sweep reads as one story. The id goes back to the caller as an `X-Request-Id` header, and behind a reverse proxy an id the proxy has already assigned is kept rather than replaced — so one request has one name in your proxy's log, your application log and the audit stream alike. People appear as account ids, not names.

??? techspec "Errors on a line"
    An `exc` field holds the exception's type, its message and the whole traceback. Database, mail and validation errors are written as their codes (`sqlstate=23505 constraint=…`), never the values they were handed, and database statements are logged without their parameters. Outgoing requests to webhooks and plug-ins get one line each, naming the target's origin, the answer and how long it took: `INFO` when it failed, `DEBUG` when it worked.

**Somebody visiting a community they don't belong to is recorded request by request.** Support access and emergency break-glass both work by a grant, and while one is live every single request made under it is a line of its own — the route, the method, the answer, and which grant allowed it. Knowing an operator held the keys for an hour is not the same as knowing what they opened, and this is the difference. Editing is over a live connection rather than a request, so that gets a line of its own the first time they change a document or a wiki page, naming which one.

**What stays on the box.** Docker holds a container's output in a file that keeps growing until you say how much to keep. The example compose file says the last 50 MB per container, in five files it rotates through. Treat that as a buffer rather than the record: if the audit stream matters to you, ship it somewhere durable and let the buffer cover the stretch when the shipper is down.

## Monitoring with Prometheus

If Prometheus and Grafana already keep an eye on the rest of the house (the NAS, the router, the thermostat nobody is allowed to touch), Initiative can join them.

| Variable | What it does | Default |
|---|---|---|
| `METRICS_TOKEN` | The token Prometheus presents to read `/api/v1/metrics`. Generate one with `openssl rand -hex 32`. | unset |

Until it's set, `/api/v1/metrics` answers *not found*, so there is nothing to switch off if you never use it. Once it is, a scrape carrying the token as a bearer token gets the numbers and anything else gets turned away.

```yaml
scrape_configs:
  - job_name: initiative
    metrics_path: /api/v1/metrics
    authorization:
      credentials_file: /etc/prometheus/initiative-token  # holds the METRICS_TOKEN value
    static_configs:
      - targets: ["initiative.lan:8173"]
```

Point `targets` at the app's own port, or at your proxy with `scheme: https` added.

**What it reports.** No label ever names a community or a person.

| Metric | What it tells you |
|---|---|
| `initiative_http_requests_total` | Requests answered, by `method`, `route` and `status`. `route` is the pattern (`/api/v1/c/{community_id}/initiatives/`), so every community shares one line. |
| `initiative_http_request_duration_seconds` | How long those took, as a histogram. |
| `initiative_http_requests_in_progress` | Requests being answered right now. |
| `initiative_websocket_connections` | Live connections: notifications, live editing, queues and counters. One open tab holds several. |
| `initiative_db_statement_duration_seconds` | How long database statements took, by `engine`. |
| `initiative_db_slow_statements_total` | Statements that took longer than half a second. |
| `initiative_db_pool_connections` | Database connections each engine holds, by `state`: `checked_out`, `idle`, `overflow`. |
| `initiative_users`, `initiative_guilds` | Accounts and communities, by `status`. |
| `initiative_sessions_active` | Sign-ins that haven't expired or been signed out. |
| `initiative_active_users` | Accounts that did something in the last day, week and month, by `window`: `1d`, `7d`, `30d`. |
| `initiative_tools_created_total` | Tools created, by `tool` (`project`, `file`, `wiki`, …). Imports and copies count too. |
| `initiative_page_views_total` | Pages opened in the app, by `route`, the page's pattern (`/c/$communityId/i/$initiativeId/projects/$projectId/`). Counted only while `METRICS_TOKEN` is set. Nothing is kept in the browser and nothing says whose visit it was. |
| `initiative_build_info` | The version running, in its `version` label. |
| `process_*`, `python_*` | Memory, CPU and garbage collection for the app's process. |

**A dashboard to start from.** Download the [starter Grafana dashboard](assets/initiative-grafana-dashboard.json) and import it (**Dashboards → New → Import**), choosing your Prometheus data source. It opens with the headline counts, then traffic, errors, response times, the database and the process.

**Slow statements land in the log too.** Each statement over half a second writes a warning to standard error: which engine, how long, the id of the request it served, and the SQL. It holds the query as written and never the values in it. SQL somebody wrote themselves, in a dashboard widget, is logged without its text. The request id is the same one described under [Logs](#logs), so one slow page can be followed from your proxy to the database.

??? techspec "Engines, and running more than one copy"
    `engine` is one of `request` (what people's requests run on), `system` (background jobs and start-up), `provisioning` (setting up a new community's tables; never flagged as slow) and `query` (SQL people write in dashboard widgets).

    Every series is per process. With several copies of the app running, Prometheus scrapes each one: add request and statement series with `sum`, and take `initiative_users`, `initiative_guilds` and `initiative_sessions_active` with `max`, because every copy counts the same accounts.

## Measuring the app in the browser (Grafana Faro)

Prometheus sees the server. To see what happens in people's browsers (which pages they actually open, as opposed to the ones you spent a weekend on, plus the errors they hit and how fast pages load), point Initiative at a Grafana Faro collector, such as Alloy's `faro.receiver`.

| Variable | What it does | Default |
|---|---|---|
| `FARO_COLLECTOR_URL` | Where browsers send measurements: a path on this server (`/collect`, which your proxy passes to the collector) or a full `https://` address. | unset |

**Nobody is measured without saying yes.** Setting it adds an **Analytics** switch to the cookie chooser, and only a browser with that switch on sends anything. Every switch starts off, and the chooser itself appears only once a platform owner turns it on under **Settings › Platform › Branding**. With the chooser off, nothing is sent.

**What gets sent.** Page views, uncaught errors and Web Vitals, grouped by a random session id the browser keeps. A page is named by its pattern (`/c/$communityId/projects/$projectId`), never by its address, and nothing names the person.

??? techspec "Collectors on another address"
    A full address on another origin is added to the page's `connect-src` automatically. A path is already covered, since it is the app's own origin.

## After changing settings

Most settings are read at startup, so **restart the container** after editing them:

```bash
docker compose up -d
```

## Related

- [Single sign-on](single-sign-on.md) · [Email](email.md) · [Push notifications](push-notifications.md) · [Object storage](object-storage.md) · [Publishing your own listings](publishing-listings.md)
- [Platform roles](platform-roles.md) — who can change in-app platform settings.
