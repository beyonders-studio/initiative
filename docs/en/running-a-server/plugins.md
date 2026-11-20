---
icon: lucide/plug
---

# Running plug-ins

Communities add plug-ins from the marketplace. Whether a plug-in can run on your server at all is your call, and you make it in one place: **Settings → Platform → Integrations**. Only an [owner](platform-roles.md) can open it.

Most plug-ins need nothing from you. The rest need an address, a key or a few values from another service, and this page is where those go.

Plug-ins are also how a server stays lean. A tool only some groups use, [Counters](../guides/counters.md) first, comes as a tool plug-in, and a tool plug-in's tables exist only in the communities that added it. A server whose communities never count anything carries no counter tables at all.

## Where plug-ins come from

| Source | What it is |
|---|---|
| Ships with Initiative | Part of the build, and credited to Initiative. Nothing else can claim that credit, because the `core.` prefix is reserved for it. |
| The Initiative registry | A signed online catalog your server follows from its first start. See [below](#the-initiative-registry). |
| Your own directory | Listing files you publish yourself. See [Publishing your own listings](publishing-listings.md). |

Every plug-in from any of these gets a row under **Plug-in services**. Its listing says what the plug-in is and the most it may ever be granted. The row holds what only your server knows: where it runs, the keys it signs with, any values from its vendor, and whether you've suspended it.

## The Initiative registry

The registry is a catalog of plug-ins and content from BeyondersStudio and the publishers it signs for. Anyone can [propose a listing](publishing-listings.md#publishing-to-the-initiative-registry). It's a [TUF](https://theupdateframework.io/) repository: every file it brings is checked against a signing key built into Initiative before anything is used, so a listing arrives exactly as it was published or not at all.

Its panel is **Plug-in registry**, under **Integrations**.

| Control | What it does |
|---|---|
| **Get updates from the registry** | On by default, with **Refresh now** beside it to check straight away rather than at the next scheduled check. Off, the server stops asking for updates, and whatever the registry already brought stays. |
| **Drop a registry bundle** | Shown while updates are off, for a server with no internet access: a `.tar.gz` of the registry's `metadata` and `targets` folders, carried in by hand. It applies as soon as you drop it, and it's checked against the same key, so a bundle that spent a week in somebody's coat pocket is exactly as trustworthy as one that didn't. |

The panel also says when the registry last updated and how many listings came from it, and why the last attempt stopped, if it did. A listing it skipped is named with its reason.

Registry signatures expire on purpose: the newest one lasts a day. A server that hasn't reached the registry in a while says when the signatures it holds ran out, and that its listings may be out of date. Nothing the registry already brought stops working, and the next successful update brings it current. An update that fails for any reason changes nothing: the last verified catalog stays exactly as it was.

| Limit | Value |
|---|---|
| Listings read from one update | 500 |
| One file from the registry | 2 MiB, fetched with a 15-second timeout |
| A bundle | 32 MiB compressed, 64 MiB and 5,000 files unpacked |

??? techspec "Registry settings"
    These are environment variables, read at startup, so a change needs a restart. Whether the server gets updates from the registry at all is the **Get updates from the registry** switch, not a variable.

    | Variable | What it does | Default |
    |---|---|---|
    | `MARKETPLACE_REGISTRY_URL` | The repository's base address. Metadata is read from `<url>metadata/` and files from `<url>targets/`. Point it at a mirror, or at a curated repository signed under the same root. | `https://beyonders-studio.github.io/initiative-developer/public/` |
    | `MARKETPLACE_REGISTRY_ROOT` | A path to a different trusted root, for a repository signed under somebody else's keys. Its listings and plug-ins arrive as usual. The panel then says the server uses a different registry signing key. | Unset: the root shipped in the image |
    | `MARKETPLACE_REGISTRY_TOKEN` | A bearer token sent with registry requests, only to the origin of `MARKETPLACE_REGISTRY_URL`, for a mirror that asks for one. | Unset: none sent |
    | `MARKETPLACE_REGISTRY_TTL_SECONDS` | Seconds between scheduled checks. At least 60. | `900` |

    A build whose shipped root is a placeholder has no registry to follow. The panel says so, and no background check runs.

## What runs for each kind of plug-in

| | A tool plug-in | Runs inside Initiative | Runs as a container |
|---|---|---|---|
| What runs | Nothing. Initiative builds the tool from the plug-in's declaration, in each community that adds it. | Nothing extra. Initiative makes the plug-in's calls itself, from its manifest. | The plug-in's own program, beside Initiative. |
| What it needs from you | Nothing. | Its vendor values, if it talks to another service. | Where it answers, the keys it signs with, and any vendor values. |
| For example | Counters | GitHub | A plug-in with pages of its own, or a service answering what its manifest declares |

A row is **Live** once it has everything it needs, and only then are communities offered it. Until then it shows **Not live** with a line saying what's missing, and no community sees it on the Plug-ins shelf.

### A tool plug-in

There's nothing to set up. Once its listing arrives, communities can add it, and each community that does gets the tool's tables in its own schema. Removing it from a community hides the tool at once and deletes its contents 30 days later, a window the community's superadmin agrees to when removing it; adding it back within the window brings everything back. Turning on **Install in every community** for a tool plug-in adds it nowhere: each community adds a tool itself.

[Counters](../guides/counters.md) ships with Initiative as `core.counters`, so a server with registry updates switched off offers it too.

??? techspec "Where a tool plug-in's data lives"
    | What | Where |
    |---|---|
    | Its tables | In each installing community's `guild_<id>` schema only, named `p_`, the plug-in's listing uid in lower case, `_` and the table's declared key (`p_tsjvtcm0s7gv2x_counter_group`). No other community, and not `guild_template`, has them. |
    | Its columns | The ones every built-in tool table has, plus one typed column per declared field. |
    | Its row security | Rendered from the same records as a built-in tool's, so the initiative boundary, sharing, holds and the trash apply to it unchanged. The community's provisioning stamp names the installed tools it was rendered with, so the start-up backfill re-renders a community whose tools changed. |
    | Its kinds | The declared key, `.` and the uid in lower case (`counter_group.tsjvtcm0s7gv2x`). Each kind's numeric code is recorded in `public.plugin_kind_codes` when a version declaring it is registered. That row names the kind and its code and nothing about any community. |
    | Removal | The install is marked deleted at once. After `30` days the deletion sweep deletes its rows and everything naming them (links, comments, tags, search entries, permissions), and the community's next provisioning drops its tables. |

### A plug-in that runs inside Initiative

If it asks for nothing, it's live already and you can skip to the next section.

If it talks to another service, its row has a **Vendor client** section for the values that service issued for your server, such as a client ID and secret. Initiative encrypts them and uses them to connect communities and members to that service. A secret is never shown again once saved: the field says **Set. Type to replace it.**

1. Create a client at the vendor for your server.
2. Select **Edit** on the plug-in's row.
3. Copy each address under **Addresses to register with the vendor** (the **Callback address**, the **Setup address** and the **Webhook address**) into the vendor's settings for that client.
4. Fill in the values under **Vendor client**.
5. Select **Save**.

!!! tip "The GitHub plug-in fills all of that in for you"
    Its row has **Create the GitHub App**. Choose who owns the app: **Your GitHub account**, or **A GitHub organization** you're an owner of, giving its name as it appears in its address. Then select **Create the GitHub App**. GitHub opens with the plug-in's permissions, events and your server's addresses already filled in. Confirm it there, and GitHub sends all six values back to Initiative. You type and copy none of them.

??? techspec "What the GitHub App needs"
    A GitHub App keeps the permissions and events it was created with, so one made by hand, or made before the plug-in asked for more, needs these set on GitHub under its **Permissions & events**. Each organization's owner then accepts the change on GitHub, which asks them. `{APP_URL}` is Initiative's public address.

    | Setting | Value |
    |---|---|
    | Callback URL | `{APP_URL}/api/v1/plugin-connections/callback` |
    | Setup URL | `{APP_URL}/api/v1/plugin-connections/setup` |
    | Webhook URL | `{APP_URL}/api/v1/plugin-hooks/beyonders-studio.github` |
    | Expire user authorization tokens | On |
    | Request user authorization (OAuth) during installation | Off |
    | Repository permissions | Issues: read and write · Pull requests: read and write · Contents: read and write · Checks: read · Commit statuses: read · Dependabot alerts: read · Metadata: read |
    | Organization permissions | Members: read · Projects: read and write |
    | Events | Issues · Pull request · Release · Create · Delete · Pull request review · Check suite |

    The plug-in asks GitHub for every installation token with read access, plus write access to issues and pull requests for the writes it makes as the organization and, on an organization, its Projects permission. No installation token can change a repository's contents. Branches started from a task are created with the member's own account. What the plug-in does with all of it is on [GitHub](../guides/github.md).

### A plug-in that runs as a container

1. **Run it.** If its listing includes one, the row shows a **Compose service** with a **Copy** button. Add it to the `docker-compose.yml` that runs Initiative, then run `docker compose up -d`.
2. **Select Edit and fill in the Base URL**: where Initiative's server calls the plug-in, such as `http://tracker:8080` on the Compose network. A private address on your own network is fine. Select **Save**.
3. **Select Connect.** Initiative reads the keys the plug-in serves and shows each one's fingerprint.
4. **Compare the fingerprints** with the line the plug-in's container logs when it starts (`app key fingerprint: …`).
5. **Select Pin these keys** only if they match.

The plug-in goes live.

A pinned key set stays pinned. If the plug-in rotates its keys, select **Connect** again. The same form takes keys two other ways, and a plug-in can have both:

| Field | What to put there |
|---|---|
| **Pasted key set (JWKS)** | The key set the plug-in publishes. Every key needs a `kid` and must be a public Ed25519 key (`kty` `OKP`, `crv` `Ed25519`). A key carrying private material is refused. Two keys mean a rotation is under way. Clear the box to remove it. |
| **Key set address** | Where the plug-in publishes its key set, so a rotation needs no visit here. It must be `https`, on the **Base URL**'s own origin, with no query or fragment, so it only works when the **Base URL** is `https` too. |

Two more fields matter for plug-ins with pages that open inside Initiative:

| Field | What to put there |
|---|---|
| **Browser address** | Where a member's browser loads the plug-in's pages, when that differs from the **Base URL**. A Compose address works for the server and not for anybody's laptop. Leave it blank when the plug-in answers at the **Base URL** for both. |
| **Allowed origins** | One origin per line (`scheme://host:port`, no path), up to 20. Blank allows only the browser address's own origin. |

The **Base URL** and **Browser address** are `http` or `https` addresses with a host, an optional port and an optional path, and no query, fragment or credentials.

### Add one before its listing arrives

**Add plug-in service** takes the **Plug-in identifier** (`publisher.plugin-name`, lowercase) and whatever you already know: its address and its keys. The row shows **Waiting for its listing** until the listing turns up, from the registry or your own directory, and the listing fills in the rest.

### The switches on a plug-in

| Switch | What it does |
|---|---|
| **Suspend everywhere** | Every community that added the plug-in stops reaching it at once, and stops seeing it: its data, its settings, its events and its pages. Nothing goes to the plug-in while it's suspended. Nothing is deleted, and **Lift** puts everything where it was. A restart never lifts it for you. |
| **Install in every community** | Adds it to every community, new ones included, and community admins can't remove it or turn it off. Where it appears and what it may do stay each community's call. Shown as **In every community**. |
| **Who can use it** | The plug-in says this itself, in each release: **Every community**, **The operations community** (the [operations community](operations-community.md) alone), or, for a plug-in in **Beta**, the communities you pick, as many as you like. Until you pick one, nobody can use a beta plug-in. A community out of its reach can't find it, install it or use it, and a copy already added there disappears until it's back in reach; nothing is deleted. With **Install in every community** also on, it's added only where it can be used. When a release leaves beta, your list is deleted and every community can use it. |
| **Delete** | Removes the registration for good, after you type its identifier to confirm. Adding it back means registering it again. A plug-in from the registry can't be deleted, because the next update would bring it straight back, so suspend it instead. |

A row marked **Publisher switched off** has stopped because every plug-in from that publisher has. Nothing is deleted there either.

### Connect an account for every community

By default each community connects its own account for a plug-in (its own GitHub organization, say), and anyone who controls an account can connect it in as many communities as they like; each one gets that account's updates. On a server where every community works with the same account, connect it once instead: on the plug-in's page, under **Connect for every community**, select **Connect for every community** and finish at the vendor as the account's owner. Every community with the plug-in then uses that account and can't change or disconnect it; their own settings say it was connected for every community.

**Disconnect** ends it for every community. A community that had connected its own account before goes back to it; the others connect one when they want to. The section shows only for a connection the server can run end to end, such as GitHub's organization, and only once the plug-in's vendor values are set.

??? techspec "Switching a whole publisher off"
    A publisher is the part of a plug-in's identifier before the dot. The publishers list has no page in the app. An owner reaches it through the API with a personal API key that isn't read-only:

    ```bash
    # List the publishers this server knows, with their ids
    curl https://initiative.example.com/api/v1/plugin-publishers/ \
      -H "Authorization: Bearer $TOKEN"

    # Switch publisher 3 off: every plug-in under its prefix stops being live
    curl -X PATCH https://initiative.example.com/api/v1/plugin-publishers/3 \
      -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json" \
      -d '{"enabled": false}'
    ```

    `{"enabled": true}` turns it back on. A restart never changes a publisher you switched.

## Setting it up from a file

Rather click nothing? `PLUGIN_SERVICES_CONFIG` names a JSON file Initiative reads at every start, and does what you would have done on the form. It's unset by default, which reads no file.

```json
[
  {
    "public_id": "acme.tracker",
    "base_url": "http://tracker:8080",
    "page_origin": "https://tracker.example.com",
    "jwks": {
      "keys": [
        { "kty": "OKP", "crv": "Ed25519", "kid": "tracker-1", "x": "11qYAYKxCrfVS_7TyWQHOg7hcvPapiMlrwIaaPcHURo" }
      ]
    }
  },
  {
    "public_id": "beyonders-studio.github",
    "vendor_env": {
      "client_id": "GITHUB_APP_CLIENT_ID",
      "client_secret": "GITHUB_APP_CLIENT_SECRET",
      "app_slug": "GITHUB_APP_SLUG",
      "app_id": "GITHUB_APP_ID",
      "private_key": "GITHUB_APP_PRIVATE_KEY",
      "webhook_secret": "GITHUB_APP_WEBHOOK_SECRET"
    }
  }
]
```

| Field | What it is |
|---|---|
| `public_id` | Which plug-in. Required. |
| `base_url` | Where Initiative's server calls it. An entry with a `base_url` states the plug-in's whole placement: its browser address and keys come with it, and whichever of those the entry leaves out is cleared. `page_origin`, `jwks` and `jwks_uri` without a `base_url` are refused. |
| `page_origin` | Its **Browser address**. |
| `jwks` / `jwks_uri` | Its Ed25519 keys, pasted as a key set or by address. An address must be `https` on the `base_url`'s own origin, so it only works with an `https` base URL. |
| `allowed_origins` | A list of up to 20 origins. |
| `mandatory` | `true` installs it in every community. |
| `vendor_env` | Each vendor value, as the name of the environment variable holding it. They're read and stored encrypted at every start, so a secret never sits in the file, and rotating one is changing the variable and restarting. |

What the plug-in is comes from its listing, so an entry naming `listing_uid`, `kind`, `scope_ceiling`, `image`, `image_digest`, `registry`, `compose` or `availability` is refused, and so is one still naming `operations_only`, since who can use a plug-in is the plug-in's to say. So is a second entry for the same `public_id`. An entry for a plug-in whose listing hasn't arrived waits for it. A file that can't be read, or an entry that's refused, is logged and skipped, and the server starts anyway. An entry naming `enabled` is refused too, since suspending a plug-in is done here, and a plug-in you suspended stays suspended, whatever the file says.

## Initiative's own signing key

Initiative signs what it sends a plug-in with an Ed25519 key of its own, and plug-ins check it against the key set it publishes. There's nothing to set up: on first start Initiative generates the key and keeps it in the database, encrypted with `SECRET_KEY`, so every copy of the server signs with the same key. Supply your own only if you'd rather manage it yourself.

| Variable | What it does | Default |
|---|---|---|
| `PLUGIN_PLATFORM_SIGNING_PRIVATE_KEY_PEM` | Your own Ed25519 private key, in PEM. While set, it wins over the generated one, and changing it rotates the key. Any other kind of key is refused when it's used. | Unset: generated |
| `PLUGIN_PLATFORM_SIGNING_KEY_ID` | The key id stamped on what it signs, so a plug-in can pick it out of the key set during a rotation. | Unset: a generated key uses its RFC 7638 thumbprint |

Generate a key with:

```bash
openssl genpkey -algorithm ed25519 -out plugin-platform.pem
```

## Related

- [Configuration](configuration.md#the-initiative-registry-and-plug-ins) for every setting on this page.
- [Publishing your own listings](publishing-listings.md) for your own directory, and for getting a listing into the registry.
- [Plug-ins & the marketplace](../guides/plugins-and-marketplace.md) for what a community sees when it adds one.
