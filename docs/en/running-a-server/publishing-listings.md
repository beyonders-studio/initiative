---
icon: lucide/package-plus
---

# Publishing your own listings

Initiative's marketplace ships with ready-made projects, dashboards, home pages and plug-ins, and you can add your own. If your group rebuilds the same spring-season project from scratch every March, this is how it stops doing that.

There are two ways in, and both take the same listing file:

| | Your own directory | The Initiative registry |
|---|---|---|
| Who sees it | Your server | Every server that follows the registry |
| How | Drop a listing file in a folder | A pull request |
| Who decides | You | The registry's reviewers |

Neither needs a fork, a code change or a new build of Initiative. Most of this page is the directory, and [the registry](#publishing-to-the-initiative-registry) is at the end.

!!! info "Where the trust comes from"
    You control the directory, so a file being in it is your decision to publish it. Every listing shows the publisher named in its own file wherever it appears: on the card, on its page and in the dialog where somebody adds it. Listings that ship with Initiative are credited to Initiative, and a listing you add can't claim that credit (see [Names you can't use](#names-you-cant-use)).

## Turn it on

Set `MARKETPLACE_EXTRA_CATALOG_DIR` to a directory inside the container, and mount your own folder there:

```yaml
services:
  initiative:
    environment:
      MARKETPLACE_EXTRA_CATALOG_DIR: /app/marketplace-catalog
    volumes:
      - ./marketplace-catalog:/app/marketplace-catalog
```

Then restart Initiative. It reads the directory at every start, and on demand with a [rescan](#pick-up-changes-without-a-restart).

| | |
|---|---|
| Default | Unset: no directory is read, and the marketplace shows only the other sources. |
| Files read | `*.json` directly in the directory, in name order. A `README.md` or an image beside them is ignored, and so are subfolders. |
| Most files | 500. Past that, the first 500 by name are read and the scan says so. |
| Largest file | 1 MiB (1,048,576 bytes) |
| Unset after being set | Every listing the directory published is withdrawn, as if the directory were empty. |

## What a listing file looks like

One file per listing. Here's a complete dashboard listing:

```json
{
  "uid": "K7M2QX8N4TVB9C",
  "public_id": "acme.standup",
  "kind": "dashboard",
  "name": "Standup board",
  "publisher": "Acme Engineering",
  "description": "What everyone is on today.",
  "long_description": "One screen for the morning standup: what's in flight and what's waiting longest.",
  "avatar_url": "/marketplace/acme/standup.svg",
  "images": [],
  "version": "1.0.0",
  "release_notes": "First release.",
  "definition": {
    "schema_version": 1,
    "kind": "dashboard",
    "layout": { "columns": 12 },
    "widgets": [
      {
        "id": "open",
        "type": "stat",
        "title": "Open tasks",
        "grid": { "x": 0, "y": 0, "w": 4, "h": 2 },
        "binding": {
          "source": "query",
          "sql": "SELECT count(*) AS open FROM tasks WHERE completed_at IS NULL AND tasks.archived_at IS NULL"
        }
      },
      {
        "id": "oldest",
        "type": "table",
        "title": "Waiting longest",
        "grid": { "x": 4, "y": 0, "w": 8, "h": 5 },
        "binding": {
          "source": "query",
          "sql": "SELECT title, project.name AS project, due_date FROM tasks WHERE completed_at IS NULL AND tasks.archived_at IS NULL ORDER BY tasks.created_at LIMIT 12"
        }
      }
    ]
  }
}
```

| Field | Required | What it is |
|---|---|---|
| `uid` | Yes | The listing's product code. See [Choosing a uid](#choosing-a-uid). |
| `public_id` | Yes | A readable id, `<publisher>.<slug>`: up to 120 characters of lowercase letters, digits, `.`, `-` and `_`, with at least one dot. |
| `kind` | Yes | What it installs. See the table below. |
| `name` | Yes | What the card is called, and what an installed copy is called. |
| `publisher` | Yes | Who publishes it, as one name of up to 120 characters on one line: a person, a team or an organization. |
| `description` | Yes | The one-line blurb on the browse card. |
| `long_description` | No | The longer text on the detail page. |
| `avatar_url` | No | The listing's artwork. See [Artwork](#artwork). Left out, it gets Initiative's own logo. |
| `images` | No | Screenshots for the detail page, a list of paths with the same rules as `avatar_url`. |
| `version` | Yes | The version this file publishes, such as `1.2.0`: 1 to 32 characters of digits, lowercase letters, `.`, `-` and `+`. |
| `release_notes` | No | What changed, shown beside the version. |
| `min_app_version` | No | The oldest Initiative this version runs on, such as `0.78.0`. On an older server the card says **Needs a newer app** and it can't be installed. A pre-release suffix is ignored in the comparison. |
| `min_plugin_api` | No | For a plug-in: the oldest plug-in API it needs, as `MAJOR.MINOR`, such as `10.0`. See [A plug-in listing](#a-plug-in-listing). |
| `definition` | Yes | What installing produces. Its shape depends on `kind`. |
| `example` | No | For a tool's content only: the same thing filled in, shown beside it. |
| `registration` | For a plug-in | How the plug-in runs. Refused on any other kind. |

| `kind` | Installs | Into |
|---|---|---|
| `project`, `dashboard`, `calendar`, `counter_group`, `file`, `post`, `wiki`, `contact` | A copy of that tool's content | An initiative, by any member who may create that tool there |
| `plugin` | A plug-in | A community |
| `home_layout` | A home page | One person's home |
| `profile_pack` | Profile decorations | One person's library |

Everything is checked before it's published, by the same validation every other source goes through. A file that doesn't pass is skipped with the reason recorded, and the listings around it publish normally.

### Attribution is required

A listing states who publishes it, or it isn't published. `publisher` is required on every route into the catalog, because people decide whether to install something by who it's from. The name appears on the card, the detail page and the install dialog, always beside where the listing came from, so a name never stands in for its source.

### Names you can't use

`core.*` belongs to the listings Initiative ships. A file in your directory claiming a `core.` public id is refused and named in the scan result. Publish under your own prefix instead: an organization name, a domain or a team.

A `uid` or `public_id` already published by another source (a built-in, or the registry) is refused too, rather than quietly taken over. Two listings claiming the same identity is a mistake worth seeing.

## A tool's content

A listing for a tool's content (a project, a dashboard, a wiki and the rest) has the tool's importable export as its `definition`. So the quickest way to write one is to build the thing in Initiative, open its **Settings → Advanced**, export it with **Export** → **Importable file (.json)**, and paste the file into `definition`. Only somebody who could delete the thing can export it.

What installs is a new copy of the installer's own, called whatever the listing is called. Whatever the source, some things in the file never travel:

- **People.** Authors, assignees, attendees, comments, mentions (which keep their words and name nobody) and person fields.
- **Links out of the item.** A task's link to another task in the same project survives. A link to anything else is dropped, and a reference in a body becomes its label.
- **Uploads** from the community's storage.
- **Timestamps.** When the original was created, changed or archived.

Dates are kept as distances from each other. The installer picks a **Start date**, and the earliest date lands on it, so a launch plan with a deadline six weeks in stays six weeks in.

`example` is a second export of the same thing with some work filled in, such as a few tasks moving through the board, so the shape makes sense at a glance. The listing's page then shows **Blank** and **Example** side by side, and the installer chooses which to start from. A dashboard is different: its preview is drawn from generated sample data, and its `example` is sample data of your own to use instead.

### A project listing

Writing `layouts` by hand? A layout names a status or a property by its place in the file's own lists, counting from 1: a status id of `2` is the second of `task_statuses`, and `property:3` is the third of `property_definitions`.

Give the project its own `task_types`, up to 20, or it installs with the four every new project starts with (task, bug, idea and milestone). Each type has a shape in `layout_preset`, one of `plain`, `fix`, `discussion`, `dates`, `repeat` or `checklist`, and can bring `starting_values`, such as a checklist or a repeat, for the tasks people add later. A task names its type with `type_name`. Each type can have its own task page: a `task` layout whose `task_type` is the type's place in `task_types`, counting from 1. A page that leaves out `main` keeps its shape's.

Plug-ins placed in the installer's initiative show up on the new project's layouts.

### A dashboard listing

A dashboard's `definition` lays widgets on a grid of up to 12 columns and 500 rows. Each widget binds to a `query` with a `sql` statement, as in the example above. [Dashboards](../guides/dashboards.md) covers what a query can read.

| | |
|---|---|
| Widget types | `stat`, `table`, `chart`, `gantt`, `funnel`, `progress`, `heatmap`, `board`, and the shortcuts `bar_chart`, `line_chart`, `area_chart`, `pie_chart`, `stacked_bar_chart`, `timeline` and `percent_stat` |
| Most widgets | 50 |
| Widget title | 200 characters |
| One `sql` statement | 20,000 characters |
| Whole definition | 256 KiB |

A widget names only a type this server can draw and a source it can fetch, so a dashboard can't name an address or carry code. Dashboards only display: nothing in one can change anything.

## A home layout listing

A ready-made home page that people add to their own home as a new view. Its `definition` places widgets on a 12-column grid, where `y` and `h` count rows.

```json
"definition": {
  "schema_version": 1,
  "kind": "home_layout",
  "widgets": [
    { "id": "clock", "type": "clock", "grid": { "x": 0, "y": 0, "w": 4, "h": 6 },
      "options": { "mode": "timer", "timer": { "duration": 1500 } } },
    { "id": "focus", "type": "focus", "grid": { "x": 4, "y": 0, "w": 8, "h": 6 } }
  ]
}
```

| Widget | Smallest (w × h) | Once per page | Options |
|---|---|---|---|
| `greeting` | 4 × 2 | Yes | `yonder`: `true` or `false` |
| `gettingStarted` | 4 × 4 | Yes | |
| `focus` | 4 × 3 | Yes | |
| `tasks` | 5 × 5 | | |
| `comingUp` | 3 × 4 | | `days`: `3`, `7`, `14` or `30` |
| `calendar` | 5 × 7 | Yes | |
| `recent` | 3 × 3 | | `mode`: `viewed` or `changed`. `tools`: a non-empty list of tool kinds. |
| `bookmarks` | 3 × 3 | | `tools`: a non-empty list of tool kinds |
| `activity` | 3 × 4 | | `view`: `all` or `yours` |
| `communities` | 4 × 5 | Yes | |
| `progress` | 4 × 2 | Yes | |
| `clock` | 2 × 3 | | `mode`: `clock` or `timer`. `zones`: up to 3 time zone names. `timer`: `{ "duration": <seconds> }`, 60 to 86,400. `muted`: `true` or `false`. |

The tool kinds are the ones in the `kind` table above. A widget `id` is up to 40 letters, digits, `-` and `_`, unique on the page. A page holds up to 24 widgets, each at most 40 rows tall, and two widgets can't share a cell. Anything that would point at one person's own things (a community, a list, a note) is refused, as is a widget or option this server doesn't know. The refusal names the widget and the reason.

## A profile pack listing

A pack grants profile decorations: banners, frames and trophies.

```json
"definition": {
  "schema_version": 1,
  "kind": "profile_pack",
  "decorations": [
    { "id": "acme.harvest-banner", "slot": "banner", "name": "Harvest" }
  ]
}
```

Each decoration has an `id`, a `slot` (`banner`, `frame` or `trophy`) and a `name`. A pack grants between 1 and 160, each `id` once. A decoration is drawn where this build ships art for its `id`, or from an `image` naming a picture in the marketplace's media (see [Artwork](#artwork)).

## A plug-in listing

A plug-in's `definition` is its manifest, as the [plug-in SDK](https://github.com/beyonders-studio/initiative-plugin-sdk) builds it. Its `registration` says how it runs and the most it may ever be granted:

```json
"registration": {
  "kind": "container",
  "image": "ghcr.io/acme/tracker@sha256:…",
  "scope_ceiling": ["projects:read", "comments:write"],
  "compose": {
    "service": "tracker:\n  image: ${IMAGE}\n  environment:\n    INITIATIVE_URL: ${INITIATIVE_URL}\n",
    "base_url": "http://tracker:8080"
  }
}
```

| Field | What it is |
|---|---|
| `kind` | `container` for a plug-in that runs as its own program, or `declarative` for one Initiative runs itself (a manifest with no `service` block). It must match the manifest. |
| `image` | A container's image, pinned by digest: `<repository>@sha256:<64 hex characters>`. Not allowed on a declarative plug-in. |
| `scope_ceiling` | Everything it may ever be granted. Its manifest may ask for less, never more. A ceiling in your own directory is your approval of it. A scope this build doesn't know is dropped with a warning in the log. |
| `compose` | Optional, a container's only. `service` is the Docker Compose service as YAML text, up to 4,096 characters, and may use `${IMAGE}` and `${INITIATIVE_URL}`, which Initiative fills in when it shows the snippet. `base_url` is where the service answers on the Compose network: an `http` or `https` address of up to 512 characters. |

Where the plug-in runs and the keys it signs with aren't in the listing, because those belong to each server that runs it. A `registration` naming `base_url`, `page_origin`, `jwks` or `jwks_uri` is refused. Once the listing is published, the plug-in shows up under **Plug-in services** for you to finish. See [Running plug-ins](plugins.md).

`min_plugin_api` can sit beside `version` in the listing, in the manifest, or both, and two that disagree are refused. A server runs a version whose `min_plugin_api` has the same major number as the plug-in API it serves and a minor number no higher. Any other version is shown and can't be installed.

## Choosing a uid

The `uid` is a product code, like a barcode. It identifies the listing, so "install `K7M2QX8N4TVB9C`" means the same thing on every Initiative carrying it, which is what makes a listing shareable at all.

- **14 characters**, from `0123456789ABCDEFGHJKMNPQRSTVWXYZ`. `I`, `L`, `O` and `U` are left out so a code can be read aloud or copied by hand without confusion.
- **You assign it** once, when you first publish. Generate 14 random characters from that set:

    ```bash
    python3 -c "import secrets; print(''.join(secrets.choice('0123456789ABCDEFGHJKMNPQRSTVWXYZ') for _ in range(14)))"
    ```

- **It never changes and is never reused.** Editing the listing keeps the uid, and a genuinely different listing gets a new one. A uid already held by a different `public_id` is refused, and so is the reverse.

## Artwork

`avatar_url` and `images` are paths on your own Initiative, never links to other sites. Each must start with `/`, use only letters, digits, `/`, `.`, `-` and `_`, and contain no `//` or `..`.

There are two places a picture can live.

**A folder you mount.** Initiative serves its static files from `/app/static`, and the built-in listings keep their artwork in `/app/static/marketplace`. Mount your own folder inside that one, so the built-in pictures stay where they are:

```yaml
volumes:
  - ./marketplace-catalog:/app/marketplace-catalog
  - ./marketplace-art:/app/static/marketplace/acme
```

A file at `./marketplace-art/standup.svg` is then served at `/marketplace/acme/standup.svg`, which is what the example above names. Square artwork looks best on the cards.

**The marketplace's media.** An owner can upload a PNG, JPEG, GIF or WebP of up to 5 MiB through the API with a personal API key that isn't read-only. The answer names the path to use, `/api/v1/marketplace/media/<sha256>`. The picture is kept in the database, so nothing needs mounting, and it's the only way to give a profile pack decoration its own `image`.

```bash
curl -X POST https://initiative.example.com/api/v1/marketplace/local/media \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@standup.png"
```

## Publishing an update

Edit the file and bump `version`.

- **A version can't change once published.** Republishing the same version string with a different `definition`, `example`, `release_notes`, `min_app_version` or `min_plugin_api` is refused, so bump the version instead. That's what lets a `uid` and a version mean the same content on every server.
- **The name, blurbs, publisher and artwork are editable in place**, with no new version. Fixing a typo in a description doesn't need a release.
- **Content already installed stays as it is.** A project or dashboard someone installed is their own copy, and a new version reaches only people who install it afterwards.
- **A plug-in follows each community's own choice.** A community with **Update automatically** on (the default) gets a new version on its own, and one with it off updates by hand. A version that asks for more than the installed one (a new scope, or a new place inside initiatives) waits for the community's superadmin to accept it either way. A plug-in you set to **Install in every community** doesn't wait: each new version applies, with any new scopes inside its ceiling.

## Removing a listing

Delete the file. On the next scan the listing is withdrawn: it disappears from browse and can't be installed again.

Withdrawn isn't deleted. Communities that already installed it keep what they installed, working as it did, along with the record of where it came from. Put the file back and the listing is published again.

A file that's present but broken still claims its listing, so a file you're halfway through editing leaves the published listing alone rather than pulling it while you work.

## Pick up changes without a restart

Restarting Initiative rescans the directory. To pick up a change straight away, an owner can ask for a rescan with a personal API key that isn't read-only:

```bash
curl -X POST https://initiative.example.com/api/v1/marketplace/operator-catalog/rescan \
  -H "Authorization: Bearer $TOKEN"
```

The answer says what happened and names every file it skipped:

```json
{
  "published": 3,
  "withdrawn": 1,
  "skipped": 1,
  "problems": [
    { "file": "draft.json", "reason": "is not valid JSON (line 9, column 3)" }
  ]
}
```

| Answer | Meaning |
|---|---|
| `200` | The scan ran. Counts and problems as above. |
| `400` `MARKETPLACE_OPERATOR_CATALOG_NOT_CONFIGURED` | `MARKETPLACE_EXTRA_CATALOG_DIR` isn't set. |
| `400` `MARKETPLACE_OPERATOR_CATALOG_DIRECTORY_MISSING` | It's set, but nothing is mounted there. |
| `409` `MARKETPLACE_OPERATOR_CATALOG_SCAN_RUNNING` | A scan is already running. Only one runs at a time, and a second request is refused rather than queued. |

## When something doesn't appear

The scan result answers most of these directly.

| What you see | What it usually means |
|---|---|
| Nothing at all published | The directory isn't mounted where `MARKETPLACE_EXTRA_CATALOG_DIR` points. A rescan answers `400` and says so. |
| One file missing, the rest fine | That file was skipped. Its name and reason are in the scan result and the server log. |
| `is larger than 1048576 bytes` | The file is over 1 MiB. |
| `the 'core.' prefix is reserved` | The `public_id` starts with `core.`. Publish under your own prefix. |
| `is already published by the builtin catalog` (or `registry`) | The `uid` or `public_id` belongs to another source's listing. Pick a new uid and prefix. |
| `version … is already published with different content` | You changed a published version. Bump `version`. |
| A listing appears but can't be installed | Its `min_app_version` is newer than this Initiative, its `min_plugin_api` names a plug-in API this server doesn't serve, or the community already has it. |
| A plug-in listing never reaches the Plug-ins shelf | Communities are offered a plug-in only once it's live. Its row under **Plug-in services** says what it's waiting for. See [Running plug-ins](plugins.md). |
| Artwork shows a broken image | The file isn't where the path says, or the folder is mounted somewhere other than inside `/app/static`. |

## Publishing to the Initiative registry

The registry is a catalog every Initiative server follows unless its owner switches it off, so a listing there reaches people you'll never meet. Getting one in is a pull request to [initiative-developer](https://github.com/beyonders-studio/initiative-developer), and the review of that pull request is the listing's review.

1. **Add your listing** under `registry/sources/<publisher>/<uid>/`: a `listing.json`, with its artwork and screenshots beside it in `assets/`. The registry's [README](https://github.com/beyonders-studio/initiative-developer/tree/main/registry) has the format, which is this page's with pictures as files rather than paths on a server, and a complete example to copy.
2. **A new publisher also needs a record** in `registry/publishers/`, with the public half of an Ed25519 key. The registry's maintainers sign it in before anything under that prefix publishes, and from then on the prefix is yours alone.
3. **Open the pull request.** The checks build and verify the whole catalog with your listing in it, so a mistake shows up there rather than on somebody's server.

Merged is published. Servers pick it up at their next check, within 15 minutes on the default schedule, and show it under your publisher's name.

An update is another pull request that adds a version. The rules are the ones above: a published version never changes, and content somebody already installed stays as they installed it.

## Related

- [Configuration](configuration.md) for every setting, including `MARKETPLACE_EXTRA_CATALOG_DIR`.
- [Running plug-ins](plugins.md) for finishing a plug-in once its listing is published.
- [Platform roles](platform-roles.md) for who may rescan.
- [Plug-ins & the marketplace](../guides/plugins-and-marketplace.md) for how your listings look to the people installing them.
- [Tools](../guides/tools.md) for what each tool is, from a member's side.
